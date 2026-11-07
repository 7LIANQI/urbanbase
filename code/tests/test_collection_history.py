"""采集历史：文件夹与 SQLite/PostgreSQL 合并去重。"""
import json
from pathlib import Path

from core import collection_history as H


class _Cache:
    def query_history(self, start_time=None, limit=5000):
        return [{
            "id": 7, "lon": 113.2, "lat": 23.1, "radius": 1000,
            "start_date": "2020-01-01", "end_date": "2020-12-31",
            "label": "2020年", "output_dir": str(self.folder),
            "file_count": 3, "success": True, "error_msg": "",
            "collected_at": "2026-10-01 08:00:00",
        }]


class _Pg:
    def query_collection_runs(self, start_time=None, limit=5000):
        return [{
            "id": 42, "lon": 113.2, "lat": 23.1, "radius": 1000,
            "start_date": "2020-01-01", "end_date": "2020-12-31",
            "label": "2020年", "output_dir": str(self.folder),
            "file_count": 4, "success": True, "error_msg": "",
            "collected_at": "2026-10-01 08:00:00",
        }, {
            "id": 43, "lon": 114.0, "lat": 22.0, "radius": 500,
            "start_date": "2021-01-01", "end_date": "2021-12-31",
            "label": "旧记录", "output_dir": "D:/missing-output",
            "file_count": 2, "success": True, "error_msg": "",
            "collected_at": "2026-10-02 09:00:00",
        }]


def test_merge_folder_sqlite_and_postgres(tmp_path):
    folder = tmp_path / "output_test"
    folder.mkdir(exist_ok=True)
    (folder / "meta.json").write_text(json.dumps({
        "location": "Lon:113.2, Lat:23.1", "readable_time": "2026-10-01 08:00:00",
    }), encoding="utf-8")
    cache, pg = _Cache(), _Pg()
    cache.folder = pg.folder = folder
    records, errors = H.collect(
        [str(tmp_path / "output_*")], cache, pg
    )
    assert not errors and len(records) == 2
    available = [r for r in records if r.available]
    assert len(available) == 1
    rec = available[0]
    assert rec.sqlite_id == 7 and rec.pg_id == 42
    assert "文件夹" in rec.source_label and "PostgreSQL" in rec.source_label
    missing = [r for r in records if not r.available][0]
    assert missing.pg_id == 43 and not missing.available


def test_sqlite_delete(tmp_path):
    from database.local_cache import LocalCache
    db = tmp_path / "cache.db"
    LocalCache._instance = None
    cache = LocalCache(str(db))
    cache.record_collection(
        113, 23, 500, "2020-01-01", "2020-12-31",
        str(tmp_path / "out"), success=True,
    )
    rows = cache.query_history()
    assert len(rows) == 1
    cache.delete_collection(rows[0]["id"])
    assert cache.query_history() == []
    LocalCache._instance = None
