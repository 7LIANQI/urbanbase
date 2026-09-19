"""测试 pg_store 中的纯工具函数（不依赖数据库连接）。"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from pg_store import (
        _haversine_m, _radius_bounds, _geom_first_point, detect_columns,
        _parse_coord, _parse_date, read_points_txt,
    )
except ImportError:
    pytest.skip("psycopg 未安装，跳过 pg_store 工具测试", allow_module_level=True)

import pandas as pd


class TestHaversine:
    """测试球面距离计算。"""

    def test_same_point_zero(self):
        assert _haversine_m(116.39, 39.90, 116.39, 39.90) == 0

    def test_one_degree_latitude(self):
        # 纬度相差 1°，球面距离约 111km
        d = _haversine_m(0.0, 0.0, 0.0, 1.0)
        assert 110_000 < d < 112_000

    def test_symmetric(self):
        a = _haversine_m(116.39, 39.90, 121.47, 31.23)
        b = _haversine_m(121.47, 31.23, 116.39, 39.90)
        assert a == pytest.approx(b)


class TestRadiusBounds:
    """测试包围盒计算。"""

    def test_center_inside(self):
        lon0, lon1, lat0, lat1 = _radius_bounds(116.39, 39.90, 1000)
        assert lon0 < 116.39 < lon1
        assert lat0 < 39.90 < lat1

    def test_lon_delta_wider_at_high_lat(self):
        # 高纬度处经度 1° 对应的实际距离更短，故经度方向包围盒应更宽
        lon0, lon1, lat0, lat1 = _radius_bounds(116.39, 39.90, 1000)
        assert (lon1 - lon0) > (lat1 - lat0)


class TestGeomFirstPoint:
    """测试 GeoJSON 坐标点提取。"""

    def test_point(self):
        lon, lat = _geom_first_point({"type": "Point", "coordinates": [116.39, 39.90]})
        assert lon == pytest.approx(116.39)
        assert lat == pytest.approx(39.90)

    def test_polygon(self):
        geom = {
            "type": "Polygon",
            "coordinates": [[[116.0, 39.0], [117.0, 39.0], [116.0, 40.0], [116.0, 39.0]]],
        }
        lon, lat = _geom_first_point(geom)
        assert lon == pytest.approx(116.0)
        assert lat == pytest.approx(39.0)

    def test_empty(self):
        assert _geom_first_point(None) == (None, None)
        assert _geom_first_point({"type": "Point", "coordinates": []}) == (None, None)


class TestDetectColumns:
    """测试坐标/时间列自动识别。"""

    def test_chinese(self):
        df = pd.DataFrame({"经度": [116.0], "纬度": [39.0], "日期": ["2026-01-01"]})
        lon, lat, time = detect_columns(df)
        assert (lon, lat, time) == ("经度", "纬度", "日期")

    def test_english_upper(self):
        df = pd.DataFrame({"LONGITUDE": [1], "LATITUDE": [2]})
        lon, lat, time = detect_columns(df)
        assert (lon, lat, time) == ("LONGITUDE", "LATITUDE", None)

    def test_fuzzy_with_suffix(self):
        df = pd.DataFrame({"经度(度)": [1], "latitude_deg": [2]})
        lon, lat, _ = detect_columns(df)
        assert lon == "经度(度)"
        assert lat == "latitude_deg"

    def test_combined_column_ambiguous(self):
        # 「经纬度」同时含经度和纬度，应判定为都不匹配，交给手动选择
        df = pd.DataFrame({"经纬度": ["116.39,39.90"]})
        lon, lat, _ = detect_columns(df)
        assert lon is None and lat is None

    def test_missing(self):
        df = pd.DataFrame({"a": [1], "b": [2]})
        lon, lat, time = detect_columns(df)
        assert (lon, lat, time) == (None, None, None)


class TestParseCoord:
    """测试经纬度单元格清洗。"""

    def test_plain_number(self):
        assert _parse_coord(116.39) == pytest.approx(116.39)
        assert _parse_coord("116.39") == pytest.approx(116.39)

    def test_with_unit(self):
        assert _parse_coord("116.39°E") == pytest.approx(116.39)
        assert _parse_coord("39.90°N") == pytest.approx(39.90)

    def test_dms(self):
        assert _parse_coord("116°23'28\"E") == pytest.approx(116.39111, abs=1e-4)

    def test_chinese_dms(self):
        assert _parse_coord("39度54分") == pytest.approx(39.9)

    def test_west_negative(self):
        assert _parse_coord("73.98W") == pytest.approx(-73.98)

    def test_combined_cell_rejected(self):
        # 挤在一列的 "116.39,39.90" 不应被误解析
        assert _parse_coord("116.39,39.90") is None

    def test_nan(self):
        assert _parse_coord(float("nan")) is None


class TestParseDate:
    """测试日期解析。"""

    def test_iso_with_millis_and_z(self):
        d = _parse_date("2026-09-01T12:34:56.789Z")
        assert d is not None
        assert d.year == 2026 and d.month == 9 and d.day == 1
        assert d.hour == 12 and d.minute == 34

    def test_plain_date(self):
        d = _parse_date("2026-09-01")
        assert d is not None and d.day == 1

    def test_invalid(self):
        assert _parse_date("不是日期") is None


class TestReadPointsTxt:
    """测试 TXT 点位列表读取。"""

    def test_comma(self, tmp_path):
        p = tmp_path / "points.txt"
        p.write_text("116.39,39.90\n116.40,39.91\n", encoding="utf-8")
        df = read_points_txt(str(p))
        assert list(df.columns[:2]) == ["lon", "lat"]
        assert len(df) == 2

    def test_whitespace_and_extra_col(self, tmp_path):
        p = tmp_path / "points.txt"
        p.write_text("116.39 39.90 A站\n116.40\t39.91 B站\n", encoding="utf-8")
        df = read_points_txt(str(p))
        assert len(df) == 2
        assert df.iloc[0]["col2"] == "A站"

    def test_skip_comment_and_blank(self, tmp_path):
        p = tmp_path / "points.txt"
        p.write_text("# 这是注释\n\n116.39,39.90\n", encoding="utf-8")
        df = read_points_txt(str(p))
        assert len(df) == 1

    def test_empty(self, tmp_path):
        p = tmp_path / "empty.txt"
        p.write_text("# 只有注释\n", encoding="utf-8")
        assert read_points_txt(str(p)).empty
