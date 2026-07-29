# -*- coding: utf-8 -*-
"""街景本地存档管理（SQLite）。

将每次采集的街景图像保存到统一存档目录，支持：
- 按位置 + 日期查询历史采集
- 生成对比对（同一方向、不同时间的街景）
- 自动去重（同一 panoid 不重复存储）
"""
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from threading import Lock


class StreetViewArchive:
    """街景本地存档管理器（线程安全）。"""

    _instances = {}
    _lock = Lock()

    def __new__(cls, base_dir="streetview_archive"):
        key = os.path.abspath(base_dir)
        if key not in cls._instances:
            with cls._lock:
                if key not in cls._instances:
                    inst = super().__new__(cls)
                    inst._initialized = False
                    cls._instances[key] = inst
        return cls._instances[key]

    def __init__(self, base_dir="streetview_archive"):
        if self._initialized:
            return
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = str(self.base_dir / "archive.db")
        self._write_lock = Lock()
        self._init_db()
        self._initialized = True

    def _get_conn(self):
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS archive (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    lon         REAL NOT NULL,
                    lat         REAL NOT NULL,
                    panoid      TEXT NOT NULL,
                    date_str    TEXT DEFAULT '',
                    heading     INTEGER DEFAULT 0,
                    image_path  TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                );

                CREATE INDEX IF NOT EXISTS idx_archive_location
                    ON archive(lon, lat, collected_at);

                CREATE UNIQUE INDEX IF NOT EXISTS idx_archive_unique
                    ON archive(panoid, heading);
            """)
            conn.commit()
        finally:
            conn.close()

    # ==================== 存档操作 ====================

    def save(self, lon, lat, panoid, date_str, heading, image_path):
        """保存一张街景图像到存档。

        Args:
            lon, lat: 拍摄位置 (WGS84)
            panoid: 百度全景 ID
            date_str: 拍摄日期 (如 "202211")
            heading: 视角方向 (0/90/180/270)
            image_path: 源图像文件路径

        Returns:
            存档后的文件路径，或 None（存储失败或已存在）
        """
        if not os.path.exists(image_path):
            return None

        # 存档目录: archive/{lon:.6f},{lat:.6f}/
        loc_dir = self.base_dir / f"{lon:.6f}_{lat:.6f}"
        loc_dir.mkdir(parents=True, exist_ok=True)

        # 目标文件名: {date_str}_heading_{heading}.jpg
        dest_filename = f"{date_str}_heading_{heading}.jpg"
        dest_path = loc_dir / dest_filename

        with self._write_lock:
            conn = self._get_conn()
            try:
                # 检查是否已存在（去重）
                existing = conn.execute(
                    "SELECT id FROM archive WHERE panoid=? AND heading=?",
                    (panoid, heading),
                ).fetchone()
                if existing:
                    return str(dest_path) if dest_path.exists() else None

                # 拷贝图像
                shutil.copy2(image_path, dest_path)

                # 写入数据库
                conn.execute(
                    """INSERT OR IGNORE INTO archive
                       (lon, lat, panoid, date_str, heading, image_path, collected_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        round(lon, 6), round(lat, 6), panoid,
                        date_str, int(heading), str(dest_path),
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                conn.commit()
                return str(dest_path)
            except sqlite3.IntegrityError:
                return str(dest_path) if dest_path.exists() else None
            finally:
                conn.close()

    # ==================== 查询操作 ====================

    def query(self, lon, lat, radius_m=50):
        """查询指定位置附近的历史街景记录。

        Returns:
            list[dict]: 按拍摄日期降序排列
        """
        delta = radius_m / 111000.0
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT * FROM archive
                   WHERE lon BETWEEN ? AND ?
                     AND lat BETWEEN ? AND ?
                   ORDER BY date_str DESC, heading""",
                (lon - delta, lon + delta, lat - delta, lat + delta),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_comparison_pairs(self, lon, lat, radius_m=50):
        """获取可对比的街景对（同方向、不同日期）。

        Returns:
            list[dict]: 按日期分组的对比信息
                [{"heading": 0, "images": [
                    {"date_str": "202105", "path": "...", "panoid": "..."},
                    {"date_str": "202211", "path": "...", "panoid": "..."},
                ]}, ...]
        """
        records = self.query(lon, lat, radius_m)
        if len(records) < 2:
            return []

        # 按 heading 分组
        by_heading = {}
        for r in records:
            h = r["heading"]
            if h not in by_heading:
                by_heading[h] = []
            by_heading[h].append(r)

        # 只保留有 2+ 条记录的 heading
        result = []
        for h, imgs in sorted(by_heading.items()):
            if len(imgs) >= 2:
                # 按日期排序
                imgs.sort(key=lambda x: x["date_str"])
                result.append({
                    "heading": h,
                    "images": [
                        {
                            "date_str": img["date_str"],
                            "path": img["image_path"],
                            "panoid": img["panoid"],
                        }
                        for img in imgs
                    ],
                })
        return result

    def get_summary(self, lon, lat, radius_m=50):
        """获取汇总信息。"""
        records = self.query(lon, lat, radius_m)
        if not records:
            return {"count": 0, "date_range": "", "headings": []}

        dates = sorted(set(r["date_str"] for r in records if r["date_str"]))
        headings = sorted(set(r["heading"] for r in records))
        return {
            "count": len(records),
            "date_range": f"{dates[0]} ~ {dates[-1]}" if dates else "",
            "dates": dates,
            "headings": headings,
        }

    def count_all(self):
        """统计总存档数。"""
        conn = self._get_conn()
        try:
            total = conn.execute("SELECT COUNT(*) as cnt FROM archive").fetchone()["cnt"]
            locations = conn.execute(
                "SELECT COUNT(DISTINCT round(lon,4)||','||round(lat,4)) as cnt FROM archive"
            ).fetchone()["cnt"]
            return {"总存档数": total, "独立位置数": locations}
        finally:
            conn.close()
