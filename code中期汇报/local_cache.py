# -*- coding: utf-8 -*-
"""本地数据缓存与历史查询模块（SQLite）。

提供三张核心表:
  1. collection_runs — 每次采集的元数据
  2. gee_cache — GEE 遥感数据片段缓存（按参数分组避免重复调用）
  3. osm_snapshots — OSM 矢量快照存档（保留各时点下载结果）
"""
import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from threading import Lock


# ---- 数据库路径 ----
def _default_db_path():
    """默认数据库路径：项目根目录下的 local_cache.db。"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_cache.db")


class LocalCache:
    """本地数据缓存管理器（线程安全）。"""

    _instance = None
    _lock = Lock()

    def __new__(cls, db_path=None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path=None):
        if self._initialized:
            return
        self._db_path = db_path or _default_db_path()
        self._write_lock = Lock()
        self._init_tables()
        self._initialized = True

    # ==================== 数据库初始化 ====================

    def _get_conn(self):
        """获取数据库连接（每次新建，线程安全）。"""
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        """创建所有表（如果不存在）。"""
        conn = self._get_conn()
        try:
            conn.executescript("""
                -- 采集运行记录
                CREATE TABLE IF NOT EXISTS collection_runs (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    lon             REAL NOT NULL,
                    lat             REAL NOT NULL,
                    radius          REAL NOT NULL,
                    start_date      TEXT NOT NULL,
                    end_date        TEXT NOT NULL,
                    label           TEXT DEFAULT '',
                    output_dir      TEXT NOT NULL UNIQUE,
                    data_sources    TEXT DEFAULT '{}',
                    file_count      INTEGER DEFAULT 0,
                    success         INTEGER DEFAULT 1,
                    error_msg       TEXT DEFAULT '',
                    collected_at    TEXT NOT NULL,
                    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                );

                -- 索引：按位置查询历史
                CREATE INDEX IF NOT EXISTS idx_runs_location
                    ON collection_runs(lon, lat, collected_at);

                -- 索引：按时间查询
                CREATE INDEX IF NOT EXISTS idx_runs_time
                    ON collection_runs(collected_at);

                -- GEE 数据缓存
                CREATE TABLE IF NOT EXISTS gee_cache (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    lon             REAL NOT NULL,
                    lat             REAL NOT NULL,
                    radius          REAL NOT NULL,
                    dataset         TEXT NOT NULL,
                    start_date      TEXT NOT NULL,
                    end_date        TEXT NOT NULL,
                    csv_path        TEXT NOT NULL,
                    row_count       INTEGER DEFAULT 0,
                    cached_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                );

                -- 索引：按位置+数据集查询缓存命中
                CREATE UNIQUE INDEX IF NOT EXISTS idx_gee_cache_key
                    ON gee_cache(lon, lat, radius, dataset, start_date, end_date);

                -- OSM 矢量快照
                CREATE TABLE IF NOT EXISTS osm_snapshots (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    lon             REAL NOT NULL,
                    lat             REAL NOT NULL,
                    radius          REAL NOT NULL,
                    layer           TEXT NOT NULL,
                    geojson_path    TEXT NOT NULL,
                    feature_count   INTEGER DEFAULT 0,
                    osm_timestamp   TEXT DEFAULT '',
                    collected_at    TEXT NOT NULL,
                    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                );

                -- 索引：按位置+图层查询历史
                CREATE INDEX IF NOT EXISTS idx_osm_snap_key
                    ON osm_snapshots(lon, lat, radius, layer, collected_at);

                -- 定时任务执行历史
                CREATE TABLE IF NOT EXISTS schedule_history (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    triggered_at    TEXT NOT NULL,
                    status          TEXT NOT NULL DEFAULT 'running',
                    output_dir      TEXT DEFAULT '',
                    duration_ms     INTEGER DEFAULT 0,
                    error_msg       TEXT DEFAULT '',
                    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                );
            """)
            conn.commit()
        finally:
            conn.close()

    # ==================== 采集记录 ====================

    def record_collection(self, lon, lat, radius, start_date, end_date,
                          output_dir, data_sources=None, label="",
                          success=True, error_msg="", file_count=0):
        """记录一次采集运行。

        Args:
            lon, lat: 中心坐标
            radius: 缓冲区半径 (m)
            start_date, end_date: 时间范围
            output_dir: 输出目录路径
            data_sources: dict，启用的数据源 {key: enabled}
            label: 时间切片标签（可选，如 "2020年"）
            success: 是否成功
            error_msg: 错误信息
            file_count: 产出文件数
        """
        with self._write_lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO collection_runs
                       (lon, lat, radius, start_date, end_date, label,
                        output_dir, data_sources, file_count,
                        success, error_msg, collected_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        round(lon, 6), round(lat, 6), radius,
                        start_date, end_date, label,
                        output_dir,
                        json.dumps(data_sources or {}, ensure_ascii=False),
                        file_count,
                        1 if success else 0,
                        error_msg,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    # ==================== 历史查询 ====================

    def query_history(self, lon=None, lat=None, radius_m=1000,
                      start_time=None, end_time=None,
                      limit=200):
        """查询历史采集记录。

        Args:
            lon, lat: 中心坐标（可选，不传则查全部）
            radius_m: 坐标匹配范围 (m)，仅当 lon/lat 均提供时生效
            start_time: 最早采集时间 "YYYY-MM-DD"
            end_time: 最晚采集时间 "YYYY-MM-DD"
            limit: 最大返回条数

        Returns:
            list[dict]: 每条记录的完整字段
        """
        conn = self._get_conn()
        try:
            conditions = ["1=1"]
            params = []

            if lon is not None and lat is not None:
                # 粗略经纬度范围过滤（±度数近似，再在 Python 中精确过滤）
                delta = radius_m / 111000.0
                conditions.append("lon BETWEEN ? AND ?")
                params.extend([lon - delta, lon + delta])
                conditions.append("lat BETWEEN ? AND ?")
                params.extend([lat - delta, lat + delta])

            if start_time:
                conditions.append("collected_at >= ?")
                params.append(start_time)
            if end_time:
                conditions.append("collected_at <= ?")
                params.append(end_time + " 23:59:59")

            where = " AND ".join(conditions)
            rows = conn.execute(
                f"SELECT * FROM collection_runs WHERE {where} "
                f"ORDER BY collected_at DESC LIMIT ?",
                params + [limit],
            ).fetchall()

            results = []
            for row in rows:
                d = dict(row)
                # 解析 JSON 字段
                try:
                    d["data_sources"] = json.loads(d["data_sources"])
                except (json.JSONDecodeError, TypeError):
                    d["data_sources"] = {}
                results.append(d)

            # 如果提供了精确坐标，在 Python 中做精确距离过滤
            if lon is not None and lat is not None and results:
                results = self._filter_by_distance(results, lon, lat, radius_m)

            return results
        finally:
            conn.close()

    @staticmethod
    def _filter_by_distance(records, lon, lat, radius_m):
        """按实际距离过滤记录（使用简化的球面距离）。"""
        import math
        filtered = []
        for r in records:
            # Haversine 简化版（短距离足够精确）
            dlat = math.radians(r["lat"] - lat)
            dlon = math.radians(r["lon"] - lon)
            a = (math.sin(dlat / 2) ** 2 +
                 math.cos(math.radians(lat)) * math.cos(math.radians(r["lat"])) *
                 math.sin(dlon / 2) ** 2)
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            dist = 6371000 * c
            if dist <= radius_m:
                r["_distance_m"] = round(dist, 1)
                filtered.append(r)
        return filtered

    def get_timeline(self, lon, lat, radius=500):
        """获取指定位置所有历史采集的时间线。

        Returns:
            pandas.DataFrame 或 dict list，按时间排序
        """
        records = self.query_history(lon, lat, radius_m=radius)
        records.sort(key=lambda r: r["collected_at"])
        return records

    def get_latest(self, lon, lat, radius=500):
        """获取指定位置最近一次采集记录。"""
        records = self.query_history(lon, lat, radius_m=radius, limit=1)
        return records[0] if records else None

    # ==================== 统计查询 ====================

    def get_summary(self):
        """获取全局统计摘要。"""
        conn = self._get_conn()
        try:
            total = conn.execute(
                "SELECT COUNT(*) as cnt FROM collection_runs"
            ).fetchone()["cnt"]

            success = conn.execute(
                "SELECT COUNT(*) as cnt FROM collection_runs WHERE success=1"
            ).fetchone()["cnt"]

            unique_locations = conn.execute(
                "SELECT COUNT(DISTINCT round(lon,4)||','||round(lat,4)) as cnt "
                "FROM collection_runs"
            ).fetchone()["cnt"]

            latest = conn.execute(
                "SELECT MAX(collected_at) as t FROM collection_runs"
            ).fetchone()["t"]

            return {
                "总采集次数": total,
                "成功次数": success,
                "独立位置数": unique_locations,
                "最近采集": latest or "无",
            }
        finally:
            conn.close()

    # ==================== GEE 缓存 ====================

    def get_gee_cache(self, lon, lat, radius, dataset, start_date, end_date):
        """查询 GEE 数据缓存。

        Returns:
            csv_path 或 None
        """
        conn = self._get_conn()
        try:
            row = conn.execute(
                """SELECT csv_path FROM gee_cache
                   WHERE lon=? AND lat=? AND radius=? AND dataset=?
                     AND start_date=? AND end_date=?
                   ORDER BY cached_at DESC LIMIT 1""",
                (round(lon, 6), round(lat, 6), radius, dataset,
                 start_date, end_date),
            ).fetchone()
            if row and os.path.exists(row["csv_path"]):
                return row["csv_path"]
            return None
        finally:
            conn.close()

    def set_gee_cache(self, lon, lat, radius, dataset, start_date, end_date,
                      csv_path, row_count=0):
        """存入 GEE 数据缓存。"""
        if not os.path.exists(csv_path):
            return
        with self._write_lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO gee_cache
                       (lon, lat, radius, dataset, start_date, end_date,
                        csv_path, row_count, cached_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (round(lon, 6), round(lat, 6), radius, dataset,
                     start_date, end_date, csv_path, row_count,
                     datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                )
                conn.commit()
            finally:
                conn.close()

    def clear_gee_cache(self, older_than_days=None):
        """清理 GEE 缓存。"""
        with self._write_lock:
            conn = self._get_conn()
            try:
                if older_than_days:
                    conn.execute(
                        "DELETE FROM gee_cache WHERE cached_at < datetime('now', ?)",
                        (f"-{older_than_days} days",),
                    )
                else:
                    conn.execute("DELETE FROM gee_cache")
                conn.commit()
            finally:
                conn.close()

    # ==================== OSM 快照 ====================

    def record_osm_snapshot(self, lon, lat, radius, layer, geojson_path,
                            feature_count=0):
        """记录一次 OSM 矢量快照。"""
        if not os.path.exists(geojson_path):
            return
        with self._write_lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """INSERT INTO osm_snapshots
                       (lon, lat, radius, layer, geojson_path, feature_count,
                        osm_timestamp, collected_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (round(lon, 6), round(lat, 6), radius, layer,
                     geojson_path, feature_count,
                     datetime.now().strftime("%Y-%m-%d"),
                     datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                )
                conn.commit()
            finally:
                conn.close()

    def get_osm_history(self, lon, lat, radius, layer):
        """获取指定位置+图层的 OSM 历史快照列表。"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT * FROM osm_snapshots
                   WHERE lon=? AND lat=? AND radius=? AND layer=?
                   ORDER BY collected_at DESC""",
                (round(lon, 6), round(lat, 6), radius, layer),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ==================== 定时任务历史 ====================

    def record_schedule_run(self, status, output_dir="", duration_ms=0,
                            error_msg=""):
        """记录定时采集执行历史。"""
        with self._write_lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """INSERT INTO schedule_history
                       (triggered_at, status, output_dir, duration_ms, error_msg)
                       VALUES (?, ?, ?, ?, ?)""",
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                     status, output_dir, duration_ms, error_msg),
                )
                conn.commit()
            finally:
                conn.close()

    def get_schedule_history(self, limit=20):
        """查询定时采集执行历史。"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM schedule_history ORDER BY triggered_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ==================== 数据导出 ====================

    def export_summary_df(self):
        """导出全局汇总 DataFrame。"""
        try:
            import pandas as pd
        except ImportError:
            return None

        conn = self._get_conn()
        try:
            df = pd.read_sql_query(
                "SELECT * FROM collection_runs ORDER BY collected_at DESC",
                conn,
            )
            return df
        finally:
            conn.close()

    def get_nearby_locations(self, lon, lat, radius_m=5000):
        """查找附近位置的历史采集，按距离排序。"""
        results = self.query_history(lon, lat, radius_m=radius_m)
        results.sort(key=lambda r: r.get("_distance_m", float("inf")))
        return results


# ==================== 模块级便捷接口 ====================

_cache = None


def get_cache():
    """获取全局 LocalCache 单例。"""
    global _cache
    if _cache is None:
        _cache = LocalCache()
    return _cache
