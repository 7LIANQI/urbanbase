"""采集历史统一索引：输出文件夹 + SQLite 缓存 + PostgreSQL。"""
from dataclasses import dataclass
from datetime import datetime
import glob
import json
import os
from pathlib import Path


@dataclass
class HistoryRecord:
    source_id: str
    source_label: str
    output_dir: str = ""
    sqlite_id: int | None = None
    pg_id: int | None = None
    lon: float | None = None
    lat: float | None = None
    radius: float | None = None
    start_date: str = ""
    end_date: str = ""
    label: str = ""
    collected_at: str = ""
    file_count: int = 0
    success: bool | None = None
    error_msg: str = ""

    @property
    def available(self):
        return bool(self.output_dir and Path(self.output_dir).is_dir())

    @property
    def key(self):
        if self.output_dir:
            return "dir:" + os.path.normcase(os.path.abspath(self.output_dir))
        return f"src:{self.source_id}"

    def location(self):
        if self.lon is None or self.lat is None:
            return "位置未知"
        return f"{self.lon:.6f}, {self.lat:.6f}"


def _dt(value):
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return datetime.min


def folder_record(folder):
    path = Path(folder).resolve()
    rec = HistoryRecord(
        source_id="folder:" + str(path),
        source_label="文件夹",
        output_dir=str(path),
        file_count=len([p for p in path.rglob("*") if p.is_file()]),
        collected_at=datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        success=True,
    )
    meta = path / "meta.json"
    if meta.exists():
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            rec.collected_at = data.get("readable_time") or rec.collected_at
            loc = data.get("location", "")
            if "Lon:" in loc and "Lat:" in loc:
                rec.lon = float(loc.split("Lon:")[1].split(",")[0].strip())
                rec.lat = float(loc.split("Lat:")[1].strip())
        except Exception:
            pass
    index = path / "index.json"
    if index.exists():
        try:
            data = json.loads(index.read_text(encoding="utf-8"))
            point = data.get("query_point", {})
            rec.lon = float(point.get("lon", rec.lon)) if point.get("lon") is not None else rec.lon
            rec.lat = float(point.get("lat", rec.lat)) if point.get("lat") is not None else rec.lat
            rec.radius = float(data.get("radius_m", rec.radius)) if data.get("radius_m") is not None else rec.radius
            span = data.get("time_range", {})
            rec.start_date, rec.end_date = span.get("start", ""), span.get("end", "")
        except Exception:
            pass
    return rec


def sqlite_record(row):
    return HistoryRecord(
        source_id="sqlite:" + str(row.get("id")),
        source_label="SQLite",
        output_dir=row.get("output_dir", ""),
        sqlite_id=row.get("id"),
        lon=row.get("lon"), lat=row.get("lat"), radius=row.get("radius"),
        start_date=row.get("start_date", ""), end_date=row.get("end_date", ""),
        label=row.get("label", ""), collected_at=row.get("collected_at", ""),
        file_count=row.get("file_count", 0),
        success=bool(row.get("success", True)), error_msg=row.get("error_msg", ""),
    )


def postgres_record(row):
    return HistoryRecord(
        source_id="postgres:" + str(row.get("id")),
        source_label="PostgreSQL",
        output_dir=row.get("output_dir", "") or "",
        pg_id=row.get("id"),
        lon=row.get("lon"), lat=row.get("lat"), radius=row.get("radius"),
        start_date=row.get("start_date", ""), end_date=row.get("end_date", ""),
        label=row.get("label", ""), collected_at=row.get("collected_at", ""),
        file_count=row.get("file_count", 0),
        success=bool(row.get("success", True)), error_msg=row.get("error_msg", ""),
    )


def merge_records(records):
    merged = {}
    for rec in records:
        old = merged.get(rec.key)
        if old is None:
            merged[rec.key] = rec
            continue
        # 文件夹记录作为主记录；数据库字段补全位置、时间和任务 ID。
        if old.source_label == "文件夹":
            base, other = old, rec
        elif rec.source_label == "文件夹":
            base, other = rec, old
        else:
            base, other = old, rec
        merged[rec.key] = base
        old, rec = base, other
        old.sqlite_id = old.sqlite_id or rec.sqlite_id
        old.pg_id = old.pg_id or rec.pg_id
        labels = {old.source_label, rec.source_label}
        old.source_label = "+".join(sorted(labels))
        for field in ("lon", "lat", "radius", "start_date", "end_date", "label", "collected_at"):
            if getattr(old, field) in (None, "") and getattr(rec, field) not in (None, ""):
                setattr(old, field, getattr(rec, field))
    return sorted(merged.values(), key=lambda r: _dt(r.collected_at), reverse=True)


def collect(patterns, sqlite_cache=None, pg_store=None, start_time=None):
    records, errors = [], []
    folders = {}
    for pattern in patterns:
        for folder in glob.glob(pattern):
            folders[os.path.normcase(os.path.abspath(folder))] = folder
    for folder in folders.values():
        try:
            records.append(folder_record(folder))
        except Exception as e:
            errors.append(("文件夹", folder, str(e)))
    if sqlite_cache is not None:
        try:
            rows = sqlite_cache.query_history(
                start_time=start_time, limit=5000
            )
            records += [sqlite_record(row) for row in rows]
        except Exception as e:
            errors.append(("SQLite", "", str(e)))
    if pg_store is not None:
        try:
            rows = pg_store.query_collection_runs(start_time=start_time)
            records += [postgres_record(row) for row in rows]
        except Exception as e:
            errors.append(("PostgreSQL", "", str(e)))
    return merge_records(records), errors
