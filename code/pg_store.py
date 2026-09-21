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
    PG_BIN_DIR, PG_DATA_DIR, PG_LOG_PATH,
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
    """转 float，非数值或 NaN/inf 返回 None。"""
    try:
        f = float(v)
    except (ValueError, TypeError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _parse_coord(v):
    """把各种写法的经纬度转成 float，带单位/度分秒/全角符号都兼容。

    支持：
      - "116.39"、116.39
      - "116.39°E"、"39.90°N"
      - "116°23'28\\"E"（度分秒）
      - "39度54分30秒"
      - "73.98W"（西经/南纬 → 负数）

    返回 None 表示无法解析（例如 "116.39,39.90" 挤在一列）。
    """
    import re

    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f

    s = str(v).strip()
    if not s:
        return None

    upper = s.upper()
    neg = ("W" in upper) or ("S" in upper) or ("西" in s) or ("南" in s)

    # 是否含度分秒分隔符（决定是否按度分秒解析）
    has_dms = any(m in s for m in ("°", "º", "′", "″", "'", '"', "度", "分", "秒"))

    # 去掉单位/符号，把度分秒分隔符统一成空格
    cleaned = (s.replace("°", " ").replace("º", " ")
                 .replace("′", " ").replace("″", " ")
                 .replace("'", " ").replace('"', " ")
                 .replace("度", " ").replace("分", " ").replace("秒", " "))
    # 只保留数字、点、负号、空格
    cleaned = re.sub(r"[^0-9.\-\s]", " ", cleaned)
    parts = cleaned.split()
    if not parts:
        return None
    try:
        deg = float(parts[0])
    except ValueError:
        return None

    if not has_dms:
        # 无度分秒符号时只认单个数字，避免把 "116.39,39.90" 误当成分秒
        if len(parts) != 1:
            return None
        return -abs(deg) if (neg or deg < 0) else abs(deg)

    minutes = float(parts[1]) if len(parts) > 1 else 0.0
    seconds = float(parts[2]) if len(parts) > 2 else 0.0
    val = abs(deg) + minutes / 60.0 + seconds / 3600.0
    if deg < 0 or neg:
        val = -val
    return val


def _parse_date(v):
    """把常见日期字符串解析为 datetime，失败返回 None。"""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    s = str(v).strip()
    if not s:
        return None
    # ISO8601 带毫秒/时区（如 2026-09-01T12:34:56.789Z）→ 去掉毫秒与 Z
    if "T" in s:
        s = s.split(".")[0].rstrip("Z").rstrip("z")
    for fmt in (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d",
        "%Y%m%d",
    ):
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


# ==================== 文件读取 / 列识别 / 距离工具 ====================

# 时间列的常见关键词（用于自动识别）
TIME_HINTS = ("日期", "时间", "date", "time", "datetime")


def _haversine_m(lon1, lat1, lon2, lat2):
    """两个经纬度点间的球面距离（米），Haversine 简化版。"""
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)
    dlat, dlon = rlat2 - rlat1, rlon2 - rlon1
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
    return 6371000.0 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _radius_bounds(lon, lat, radius):
    """按半径生成经纬度包围盒，考虑纬度对经度距离的影响。

    Returns:
        (lon_min, lon_max, lat_min, lat_max)
    """
    lat_delta = radius / 110540.0
    cos_lat = max(math.cos(math.radians(lat)), 0.01)  # 高纬保护
    lon_delta = radius / (111320.0 * cos_lat)
    return (lon - lon_delta, lon + lon_delta, lat - lat_delta, lat + lat_delta)


def _geom_first_point(geom):
    """从 GeoJSON geometry 提取第一个坐标点作为代表点 (lon, lat)。"""
    if not isinstance(geom, dict):
        return None, None
    coords = geom.get("coordinates")
    gtype = geom.get("type")
    if not isinstance(coords, (list, tuple)) or not coords:
        return None, None
    if gtype == "Point" and len(coords) >= 2:
        return _as_float(coords[0]), _as_float(coords[1])
    if gtype in ("LineString", "MultiPoint"):
        pt = coords[0]
        if isinstance(pt, (list, tuple)) and len(pt) >= 2:
            return _as_float(pt[0]), _as_float(pt[1])
    if gtype == "Polygon":
        ring = coords[0]
        if (isinstance(ring, (list, tuple)) and ring
                and isinstance(ring[0], (list, tuple)) and len(ring[0]) >= 2):
            return _as_float(ring[0][0]), _as_float(ring[0][1])
    return None, None


def _find_time_in_props(props):
    """从 GeoJSON properties 里找常见时间字段并解析为 datetime。"""
    if not isinstance(props, dict):
        return None
    for k, v in props.items():
        if any(hint in str(k).lower() for hint in TIME_HINTS):
            obs = _parse_date(v)
            if obs is not None:
                return obs
    return None


def _detect_encoding(path):
    """探测文本文件编码：优先 UTF-8（含 BOM），回退 GB18030/GBK。"""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            with open(path, "r", encoding=enc) as f:
                f.read(65536)
            return enc
        except (UnicodeDecodeError, OSError):
            continue
    return "utf-8"


def _detect_delimiter(path, encoding):
    """在表头行探测 CSV 分隔符（逗号/分号/Tab/竖线）。"""
    try:
        with open(path, "r", encoding=encoding) as f:
            header = f.readline()
    except (OSError, UnicodeDecodeError):
        return ","
    counts = {sep: header.count(sep) for sep in (",", ";", "\t", "|")}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def read_table(path):
    """读取 CSV / Excel 文件为 pandas DataFrame（自动探测编码与分隔符）。"""
    import pandas as pd
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        return pd.read_excel(path)
    enc = _detect_encoding(path)
    sep = _detect_delimiter(path, enc)
    return pd.read_csv(path, encoding=enc, sep=sep)


def detect_columns(df):
    """自动识别 DataFrame 中的经度/纬度/时间列（模糊匹配）。

    按"包含关键词"匹配，并排除歧义列（如「经纬度」同时含经纬度则都不算）。
    Returns:
        (lon_col, lat_col, time_col)，识别不到返回 None。
    """
    cols = [str(c) for c in df.columns]
    lowered = [c.strip().lower() for c in cols]

    def find(positive, negative):
        for c, cl in zip(cols, lowered):
            if any(p in cl for p in positive) and not any(n in cl for n in negative):
                return c
        return None

    # 「经纬度」「坐标」等组合列名同时含经纬语义，都不应被单独匹配
    combined = ("经纬", "坐标", "coord")
    lon_col = find(
        ("lon", "lng", "long", "经度", "东经"),
        ("lat", "纬度", "北纬") + combined,
    )
    lat_col = find(
        ("lat", "纬度", "北纬"),
        ("lon", "lng", "long", "经度", "东经") + combined,
    )
    time_col = next(
        (c for c, cl in zip(cols, lowered) if any(k in cl for k in TIME_HINTS)),
        None,
    )
    return lon_col, lat_col, time_col


def read_points_txt(path):
    """读取 TXT 点位列表（每行一个点，lon,lat，逗号/空白/分号分隔）。

    返回 DataFrame（列名 lon, lat, col2, col3...），无有效点返回空 DataFrame。
    """
    import re

    import pandas as pd

    enc = _detect_encoding(path)
    rows = []
    with open(path, "r", encoding=enc) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p for p in re.split(r"[,\s;]+", line) if p]
            if len(parts) < 2:
                continue
            rows.append(parts)

    if not rows:
        return pd.DataFrame()

    ncol = max(len(r) for r in rows)
    for r in rows:
        r.extend([""] * (ncol - len(r)))
    cols = ["lon", "lat"] + [f"col{i}" for i in range(2, ncol)]
    return pd.DataFrame(rows, columns=cols)


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

    def start_server(self):
        """启动便携版 PostgreSQL 服务（调用 pg_ctl start）。

        Returns:
            (成功, 消息)。
        """
        import subprocess

        if self.is_available():
            return True, "PostgreSQL 已在运行，无需重复启动"

        pg_ctl = os.path.join(PG_BIN_DIR, "pg_ctl.exe")
        if not os.path.exists(pg_ctl):
            return False, f"未找到 pg_ctl.exe（{PG_BIN_DIR}）"
        if not os.path.exists(PG_DATA_DIR):
            return False, "数据目录不存在，请先运行 scripts/pg_init.bat 初始化"

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            # 不能用 capture_output=True：pg_ctl start 拉起的 postgres 后台进程
            # 会继承管道句柄，导致 communicate() 永远等不到 EOF 而卡死。
            # 这里输出重定向到 DEVNULL，避免死锁。
            subprocess.run(
                [pg_ctl, "-D", PG_DATA_DIR, "-l", PG_LOG_PATH, "start"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=90, creationflags=creationflags,
            )
        except Exception as e:
            return False, f"启动进程出错: {e}"

        if self.is_available():
            return True, "PostgreSQL 已启动，可以正常使用本地数据了"

        return False, "启动未成功：请查看 D:\\PostgreSQL17\\pg.log"

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

    def query_local(self, lon, lat, radius, start_date=None, end_date=None,
                    dataset_ids=None):
        """按位置/时间查询本地库，返回 dict（供 LocalDataCollector 用）。

        local_records 按真实球面距离过滤并按距离升序返回（自带 distance_m）。
        dataset_ids: 可选，仅查询这些数据集的记录（None/空 = 查全部）。
        """
        result = {"runs": [], "metrics": [], "spatial": [], "local_records": []}
        lon0, lon1, lat0, lat1 = _radius_bounds(lon, lat, radius)

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

                # 自有数据集：Haversine 距离过滤 + 按距离升序（最近优先）
                haversine_a = (
                    "power(sin(radians(lat - %s) / 2), 2)"
                    " + cos(radians(%s)) * cos(radians(lat))"
                    " * power(sin(radians(lon - %s) / 2), 2)"
                )
                dist_expr = (
                    f"6371000.0 * 2 * atan2(sqrt({haversine_a}), "
                    f"sqrt(1 - ({haversine_a})))"
                )
                ds_filter = ""
                params = [lat, lat, lon, lat, lat, lon, lon0, lon1, lat0, lat1]
                if dataset_ids:
                    ds_filter = " AND dataset_id = ANY(%s)"
                    params.append(list(dataset_ids))
                params.append(radius)
                cur.execute(
                    f"""
                    SELECT id, dataset_id, lon, lat, obs_time, payload, distance_m
                    FROM (
                        SELECT id, dataset_id, lon, lat, obs_time, payload,
                               {dist_expr} AS distance_m
                        FROM local_records
                        WHERE lon BETWEEN %s AND %s AND lat BETWEEN %s AND %s
                              {ds_filter}
                    ) _t
                    WHERE distance_m <= %s
                    ORDER BY distance_m ASC
                    LIMIT 1000
                    """,
                    params,
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

    def import_dataframe(self, df, name, description="", source="",
                         lon_col=None, lat_col=None, time_col=None):
        """把 DataFrame 导入本地库（批量插入）。

        Args:
            lon_col / lat_col / time_col: 显式指定坐标/时间列名。
                经度/纬度列为 None 时对应记录存为 NULL，无法按坐标查询。

        Returns:
            (dataset_id, 记录数, 含有效经纬度的记录数)；失败返回 (None, 0, 0)。
        """
        if df is None or df.empty:
            return None, 0, 0

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO local_datasets (name, description, source)
                       VALUES (%s, %s, %s) RETURNING id""",
                    (name, description, source),
                )
                dataset_id = cur.fetchone()["id"]

                rows = []
                with_coords = 0
                for _, row in df.iterrows():
                    payload = _json_safe({str(k): v for k, v in row.items()})
                    lon_v = _parse_coord(row[lon_col]) if lon_col else None
                    lat_v = _parse_coord(row[lat_col]) if lat_col else None
                    obs = _parse_date(row[time_col]) if time_col else None
                    if lon_v is not None and lat_v is not None:
                        with_coords += 1
                    rows.append((dataset_id, lon_v, lat_v, obs, Jsonb(payload)))

                if rows:
                    cur.executemany(
                        """INSERT INTO local_records
                           (dataset_id, lon, lat, obs_time, payload)
                           VALUES (%s, %s, %s, %s, %s)""",
                        rows,
                    )
            conn.commit()
            return dataset_id, len(rows), with_coords
        except Exception:
            conn.rollback()
            return None, 0, 0
        finally:
            conn.close()

    def import_geojson(self, path, name, description="", source=""):
        """导入 GeoJSON（FeatureCollection）到本地库。

        每个 Feature 的坐标取第一个点作为代表 lon/lat，properties 作为 payload。
        Returns: (dataset_id, 记录数, 含有效经纬度的记录数)；失败返回 (None, 0, 0)。
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None, 0, 0

        features = obj.get("features", []) if isinstance(obj, dict) else []
        if not features:
            return None, 0, 0

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO local_datasets (name, description, source)
                       VALUES (%s, %s, %s) RETURNING id""",
                    (name, description, source),
                )
                dataset_id = cur.fetchone()["id"]

                rows = []
                with_coords = 0
                for feat in features:
                    if not isinstance(feat, dict):
                        continue
                    geom = feat.get("geometry")
                    props = feat.get("properties")
                    lon_v, lat_v = _geom_first_point(geom)
                    obs = _find_time_in_props(props)
                    if lon_v is not None and lat_v is not None:
                        with_coords += 1
                    payload = _json_safe(
                        props if isinstance(props, dict) else {"properties": props}
                    )
                    rows.append((dataset_id, lon_v, lat_v, obs, Jsonb(payload)))

                if rows:
                    cur.executemany(
                        """INSERT INTO local_records
                           (dataset_id, lon, lat, obs_time, payload)
                           VALUES (%s, %s, %s, %s, %s)""",
                        rows,
                    )
            conn.commit()
            return dataset_id, len(rows), with_coords
        except Exception:
            conn.rollback()
            return None, 0, 0
        finally:
            conn.close()

    def import_csv(self, path, name, description="", source="",
                   lon_col=None, lat_col=None, time_col=None):
        """导入 CSV / Excel 到本地库（自动识别坐标/时间列，亦可显式指定）。

        Returns: (dataset_id, 记录数, 含有效经纬度的记录数)；失败返回 (None, 0, 0)。
        """
        try:
            df = read_table(path)
        except Exception:
            return None, 0, 0
        if lon_col is None or lat_col is None:
            auto_lon, auto_lat, auto_time = detect_columns(df)
            lon_col = lon_col or auto_lon
            lat_col = lat_col or auto_lat
            time_col = time_col or auto_time
        return self.import_dataframe(
            df, name, description, source,
            lon_col=lon_col, lat_col=lat_col, time_col=time_col,
        )


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
