# -*- coding: utf-8 -*-
"""PostgreSQL 本地持久化存储层。

作为平台的本地数据库，负责「写」与「读」两个方向：
  - 写：把每次采集的结果扁平化落库（采集运行记录、数值指标、空间要素、文件引用）
  - 读：按经纬度/时间范围查询历史采集结果 + 导师导入的本地数据集

与 local_cache.py（SQLite 元数据缓存）互补：SQLite 存元数据/缓存，
PostgreSQL 存数据本体（可做数值时间序列与空间要素的持久化查询）。
"""
import json
import math
import os
from datetime import datetime
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from config import (
    PG_HOST, PG_PORT, PG_DBNAME, PG_USER, PG_PASSWORD,
)


# ==================== 建表 SQL ====================

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS collection_runs (
    id           BIGSERIAL PRIMARY KEY,
    lon          DOUBLE PRECISION NOT NULL,
    lat          DOUBLE PRECISION NOT NULL,
    radius       DOUBLE PRECISION NOT NULL,
    start_date   TEXT NOT NULL,
    end_date     TEXT NOT NULL,
    label        TEXT DEFAULT '',
    output_dir   TEXT UNIQUE,
    data_sources JSONB DEFAULT '{}',
    file_count   INTEGER DEFAULT 0,
    success      BOOLEAN DEFAULT TRUE,
    error_msg    TEXT DEFAULT '',
    collected_at TIMESTAMP NOT NULL,
    created_at   TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_runs_loc ON collection_runs (lon, lat, collected_at);

CREATE TABLE IF NOT EXISTS metric_points (
    id         BIGSERIAL PRIMARY KEY,
    run_id     BIGINT REFERENCES collection_runs(id) ON DELETE CASCADE,
    source     TEXT NOT NULL,
    metric     TEXT NOT NULL,
    value      DOUBLE PRECISION,
    unit       TEXT DEFAULT '',
    obs_time   TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_metric_run ON metric_points (run_id, source, metric);

CREATE TABLE IF NOT EXISTS spatial_features (
    id            BIGSERIAL PRIMARY KEY,
    run_id        BIGINT REFERENCES collection_runs(id) ON DELETE CASCADE,
    layer         TEXT NOT NULL,
    feature_count INTEGER DEFAULT 0,
    geojson       JSONB NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_spatial_run ON spatial_features (run_id, layer);

CREATE TABLE IF NOT EXISTS data_files (
    id         BIGSERIAL PRIMARY KEY,
    run_id     BIGINT REFERENCES collection_runs(id) ON DELETE CASCADE,
    file_key   TEXT NOT NULL,
    file_path  TEXT NOT NULL,
    file_type  TEXT DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_files_run ON data_files (run_id);

CREATE TABLE IF NOT EXISTS local_datasets (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    source      TEXT DEFAULT '',
    imported_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS local_records (
    id         BIGSERIAL PRIMARY KEY,
    dataset_id BIGINT REFERENCES local_datasets(id) ON DELETE CASCADE,
    lon        DOUBLE PRECISION,
    lat        DOUBLE PRECISION,
    obs_time   TIMESTAMP,
    payload    JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_local_ll ON local_records (lon, lat, obs_time);
"""


# ==================== 通用工具 ====================

def _is_number(v):
    """判断值是否可存为 DOUBLE PRECISION 的数值。"""
    if v is None or isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    try:
        float(v)
        return True
    except (ValueError, TypeError):
        return False


def _as_float(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _parse_date(v):
    """把常见日期字符串解析为 datetime，失败返回 None。"""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    s = str(v).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _json_safe(obj):
    """递归把 numpy / Decimal / 其他类型转成 JSON 可序列化的原生类型。"""
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, (int, float)):
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        return obj
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    # numpy 标量（np.int64 / np.float64 等）
    if hasattr(obj, "item"):
        try:
            return _json_safe(obj.item())
        except Exception:
            return str(obj)
    return str(obj)


class PostgresStore:
    """PostgreSQL 存储管理器（单例，连接按操作独立新建，线程安全）。"""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, host=None, port=None, dbname=None, user=None, password=None):
        if self._initialized:
            return
        self.configure(host, port, dbname, user, password)
        self._initialized = True

    def configure(self, host=None, port=None, dbname=None, user=None, password=None):
        self.host = host or PG_HOST
        self.port = int(port or PG_PORT)
        self.dbname = dbname or PG_DBNAME
        self.user = user or PG_USER
        self.password = password if password is not None else PG_PASSWORD

    def _dsn(self, dbname=None):
        return (
            f"host={self.host} port={self.port} "
            f"dbname={dbname or self.dbname} "
            f"user={self.user} password={self.password}"
        )

    def _get_conn(self):
        """新建连接（每次操作独立，线程安全）。"""
        return psycopg.connect(self._dsn(), row_factory=dict_row, connect_timeout=5)

    # ==================== 连接 / 建库 ====================

    def is_available(self):
        """PostgreSQL 是否可连接。"""
        try:
            conn = self._get_conn()
            conn.close()
            return True
        except Exception:
            return False

    def ensure_database(self):
        """若目标库不存在则创建（连接维护库 postgres）。返回 True 表示库可用。"""
        try:
            admin = psycopg.connect(
                self._dsn(dbname="postgres"), autocommit=True, connect_timeout=5,
            )
            with admin.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM pg_database WHERE datname = %s", (self.dbname,),
                )
                if cur.fetchone() is None:
                    cur.execute(f'CREATE DATABASE "{self.dbname}"')
            admin.close()
            return True
        except Exception:
            return False

    def init_schema(self):
        """建库（若缺）并创建所有表。返回 (成功, 错误信息)。"""
        self.ensure_database()
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_SQL)
            conn.commit()
            return True, ""
        except Exception as e:
            return False, str(e)
        finally:
            conn.close()

    # ==================== 写入 ====================

    def record_run(self, lon, lat, radius, start_date, end_date, label="",
                   output_dir="", data_sources=None, file_count=0,
                   success=True, error_msg=""):
        """写入/更新采集运行记录，返回 run_id。"""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO collection_runs
                        (lon, lat, radius, start_date, end_date, label,
                         output_dir, data_sources, file_count, success,
                         error_msg, collected_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (output_dir)
                    DO UPDATE SET
                        lon = EXCLUDED.lon, lat = EXCLUDED.lat,
                        radius = EXCLUDED.radius, start_date = EXCLUDED.start_date,
                        end_date = EXCLUDED.end_date, label = EXCLUDED.label,
                        data_sources = EXCLUDED.data_sources,
                        file_count = EXCLUDED.file_count,
                        success = EXCLUDED.success, error_msg = EXCLUDED.error_msg,
                        collected_at = EXCLUDED.collected_at
                    RETURNING id
                    """,
                    (round(lon, 6), round(lat, 6), radius, start_date, end_date,
                     label, output_dir,
                     Jsonb(_json_safe(data_sources or {})),
                     file_count, success, error_msg, datetime.now()),
                )
                row = cur.fetchone()
            conn.commit()
            return row["id"]
        finally:
            conn.close()

    def _clear_run_details(self, run_id):
        """清空某次采集的明细（保证重复落库幂等）。"""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM metric_points WHERE run_id = %s", (run_id,))
                cur.execute("DELETE FROM spatial_features WHERE run_id = %s", (run_id,))
                cur.execute("DELETE FROM data_files WHERE run_id = %s", (run_id,))
            conn.commit()
        finally:
            conn.close()

    def insert_metrics(self, run_id, metrics):
        """批量插入指标。metrics: [(source, metric, value, unit, obs_time), ...]"""
        if not metrics:
            return
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO metric_points
                       (run_id, source, metric, value, unit, obs_time)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    [(run_id, m[0], m[1], m[2], m[3], m[4]) for m in metrics],
                )
            conn.commit()
        finally:
            conn.close()

    def insert_spatial(self, run_id, layer, geojson_obj, feature_count=0):
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO spatial_features
                       (run_id, layer, feature_count, geojson)
                       VALUES (%s, %s, %s, %s)""",
                    (run_id, layer, feature_count,
                     Jsonb(_json_safe(geojson_obj))),
                )
            conn.commit()
        finally:
            conn.close()

    def insert_files(self, run_id, file_map):
        """file_map: {file_key: file_path}"""
        if not file_map:
            return
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO data_files (run_id, file_key, file_path, file_type)
                       VALUES (%s, %s, %s, %s)""",
                    [(run_id, k, v, os.path.splitext(v)[1].lstrip(".").lower())
                     for k, v in file_map.items()],
                )
            conn.commit()
        finally:
            conn.close()

    # ==================== 扁平化（写路径核心） ====================

    def persist_output(self, output_dir, lon, lat, radius, start_date, end_date,
                       options=None, label=""):
        """把一次采集的 output 目录内容扁平化落库。返回 run_id 或 None。"""
        files = {}
        index_path = os.path.join(output_dir, "index.json")
        if os.path.exists(index_path):
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    files = json.load(f).get("files", {})
            except (json.JSONDecodeError, OSError):
                files = {}

        run_id = self.record_run(
            lon, lat, radius, start_date, end_date, label=label,
            output_dir=output_dir, data_sources=options or {},
            file_count=len(files), success=True,
        )
        self._clear_run_details(run_id)

        metrics = []
        spatial = []
        file_refs = {}

        for key, value in files.items():
            # 街景等可能是列表
            if isinstance(value, list):
                for p in value:
                    if os.path.exists(p):
                        file_refs[f"{key}/{os.path.basename(p)}"] = p
                continue
            path = value
            if not os.path.exists(path):
                continue
            ext = os.path.splitext(path)[1].lower()
            if ext == ".geojson":
                fc, obj = self._load_geojson(path)
                if obj is not None:
                    spatial.append((key, fc, obj))
            elif ext == ".json":
                metrics.extend(self._flatten_json(key, path))
            elif ext == ".csv":
                metrics.extend(self._flatten_csv(key, path))
            else:
                file_refs[key] = path

        self.insert_metrics(run_id, metrics)
        for layer, fc, obj in spatial:
            self.insert_spatial(run_id, layer, obj, fc)
        self.insert_files(run_id, file_refs)
        return run_id

    @staticmethod
    def _load_geojson(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            return len(obj.get("features", [])), obj
        except (json.JSONDecodeError, OSError):
            return 0, None

    @staticmethod
    def _flatten_json(source, path):
        """把 JSON 文件扁平化成指标列表 [(source, metric, value, unit, obs_time)]。"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

        metrics = []

        def walk(obj, prefix):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    walk(v, f"{prefix}.{k}" if prefix else str(k))
            # 只接受真正的数值（跳过 "200" 这类字符串型元数据 code）
            elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
                metrics.append((prefix, float(obj)))

        walk(data, "")

        # 清洗指标名：去掉 now. / components. 前缀噪音
        cleaned = []
        for metric, value in metrics:
            m = metric
            if m.startswith("now."):
                m = m[4:]
            if m.startswith("components."):
                m = m[len("components."):]
            cleaned.append((source, m, value, "", None))
        return cleaned

    @staticmethod
    def _flatten_csv(source, path):
        """把统计 CSV 扁平化成指标列表（带日期列则保留时间维度）。"""
        try:
            import pandas as pd
        except ImportError:
            return []
        try:
            df = pd.read_csv(path)
        except Exception:
            return []
        if df.empty:
            return []

        date_col = None
        for c in df.columns:
            if any(k in str(c) for k in ("日期", "date", "Date", "时间", "time")):
                date_col = c
                break

        metrics = []
        for _, row in df.iterrows():
            obs_time = _parse_date(row[date_col]) if date_col else None
            for col in df.columns:
                if col == date_col:
                    continue
                val = row[col]
                if _is_number(val):
                    metrics.append((source, str(col), float(val), "", obs_time))
        return metrics

    # ==================== 读取 ====================

    @staticmethod
    def _row_serializable(row):
        out = {}
        for k, v in row.items():
            if isinstance(v, datetime):
                out[k] = v.strftime("%Y-%m-%d %H:%M:%S")
            elif isinstance(v, Decimal):
                out[k] = float(v)
            elif isinstance(v, (dict, list)):
                out[k] = v
            elif isinstance(v, (int, float, str, bool, type(None))):
                out[k] = v
            else:
                out[k] = str(v)
        return out

    def query_local(self, lon, lat, radius, start_date=None, end_date=None):
        """按位置/时间查询本地库，返回 dict（供 LocalDataCollector 用）。"""
        result = {"runs": [], "metrics": [], "spatial": [], "local_records": []}
        delta = radius / 111000.0
        lon0, lon1 = round(lon, 6) - delta, round(lon, 6) + delta
        lat0, lat1 = round(lat, 6) - delta, round(lat, 6) + delta

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                where = "lon BETWEEN %s AND %s AND lat BETWEEN %s AND %s"
                params = [lon0, lon1, lat0, lat1]
                if start_date:
                    where += " AND collected_at >= %s"
                    params.append(start_date)
                if end_date:
                    where += " AND collected_at <= %s"
                    params.append(end_date + " 23:59:59")

                cur.execute(
                    f"SELECT * FROM collection_runs WHERE {where} "
                    f"ORDER BY collected_at DESC",
                    params,
                )
                runs = cur.fetchall()
                result["runs"] = [self._row_serializable(r) for r in runs]

                run_ids = [r["id"] for r in runs]
                if run_ids:
                    cur.execute(
                        "SELECT * FROM metric_points WHERE run_id = ANY(%s) "
                        "ORDER BY source, metric, obs_time",
                        (run_ids,),
                    )
                    result["metrics"] = [self._row_serializable(r) for r in cur.fetchall()]

                    cur.execute(
                        "SELECT id, run_id, layer, feature_count, created_at "
                        "FROM spatial_features WHERE run_id = ANY(%s)",
                        (run_ids,),
                    )
                    result["spatial"] = [self._row_serializable(r) for r in cur.fetchall()]

                cur.execute(
                    """SELECT id, dataset_id, lon, lat, obs_time, payload
                       FROM local_records
                       WHERE lon BETWEEN %s AND %s AND lat BETWEEN %s AND %s
                       ORDER BY obs_time DESC NULLS LAST
                       LIMIT 1000""",
                    (lon0, lon1, lat0, lat1),
                )
                result["local_records"] = [
                    self._row_serializable(r) for r in cur.fetchall()
                ]
            return result
        finally:
            conn.close()

    def list_datasets(self):
        """列出已导入的本地数据集。"""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT d.id, d.name, d.description, d.source, d.imported_at,
                              COUNT(r.id) AS record_count
                       FROM local_datasets d
                       LEFT JOIN local_records r ON r.dataset_id = d.id
                       GROUP BY d.id
                       ORDER BY d.imported_at DESC"""
                )
                return [self._row_serializable(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def query_dataset(self, dataset_id, limit=500):
        """查询某个导入数据集的记录。"""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, dataset_id, lon, lat, obs_time, payload
                       FROM local_records WHERE dataset_id = %s
                       ORDER BY id LIMIT %s""",
                    (dataset_id, limit),
                )
                return [self._row_serializable(r) for r in cur.fetchall()]
        finally:
            conn.close()

    # ==================== 导入导师数据 ====================

    def import_csv(self, path, name, description="", source=""):
        """导入 CSV 到本地库，自动识别坐标/时间列。返回 (dataset_id, 记录数)。"""
        try:
            import pandas as pd
        except ImportError:
            return None, 0
        try:
            df = pd.read_csv(path)
        except Exception:
            return None, 0
        if df.empty:
            return None, 0

        lon_col = next((c for c in df.columns
                        if str(c).lower() in ("lon", "lng", "longitude", "经度")), None)
        lat_col = next((c for c in df.columns
                        if str(c).lower() in ("lat", "latitude", "纬度")), None)
        time_col = next((c for c in df.columns
                         if any(k in str(c) for k in ("日期", "date", "时间", "time"))), None)

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO local_datasets (name, description, source)
                       VALUES (%s, %s, %s) RETURNING id""",
                    (name, description, source),
                )
                dataset_id = cur.fetchone()["id"]

                count = 0
                for _, row in df.iterrows():
                    payload = _json_safe({str(k): v for k, v in row.items()})
                    lon_v = _as_float(row[lon_col]) if lon_col else None
                    lat_v = _as_float(row[lat_col]) if lat_col else None
                    obs = _parse_date(row[time_col]) if time_col else None
                    cur.execute(
                        """INSERT INTO local_records
                           (dataset_id, lon, lat, obs_time, payload)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (dataset_id, lon_v, lat_v, obs, Jsonb(payload)),
                    )
                    count += 1
            conn.commit()
            return dataset_id, count
        except Exception:
            conn.rollback()
            return None, 0
        finally:
            conn.close()


# ==================== 模块级便捷接口 ====================

_store = None


def get_store(host=None, port=None, dbname=None, user=None, password=None):
    """获取全局 PostgresStore 单例（可传入连接参数覆盖默认）。"""
    global _store
    if _store is None:
        _store = PostgresStore(host, port, dbname, user, password)
    elif any(x is not None for x in (host, port, dbname, user, password)):
        _store.configure(host, port, dbname, user, password)
    return _store
