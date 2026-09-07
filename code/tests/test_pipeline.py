"""测试 pipeline.py 中的辅助函数。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline import _opt, _any_gee, _any_osm

# 完整默认选项
FULL = {
    "air_quality": True, "weather": True, "streetview": True,
    "gee_viirs": True, "gee_ndvi": True, "gee_lst": True,
    "gee_elevation": True, "gee_precipitation": True,
    "gee_ndwi": True, "gee_evi": True, "gee_population": True,
    "gee_era5_climate": True, "gee_era5_hourly": True,
    "gee_landcover": True, "gee_s5p_no2": True,
    "gee_jrc_water": True, "gee_modis_lst": True,
    "gee_dynamic_world": True, "gee_hansen_forest": True,
    "gee_canopy_height": True,
    "osm_roads": True, "osm_buildings": True,
    "osm_green_spaces": True, "osm_water_bodies": True,
    "osm_stats": True,
}

EMPTY = {k: False for k in FULL}


class TestOpt:
    """测试 _opt 辅助函数。"""

    def test_all_enabled_none(self):
        """options=None 时全部启用。"""
        assert _opt(None, "air_quality") is True
        assert _opt(None, "gee_ndvi") is True
        assert _opt(None, "nonexistent_key") is True

    def test_explicit_true(self):
        """显式设置 True。"""
        assert _opt(FULL, "air_quality") is True
        assert _opt(FULL, "gee_ndvi") is True

    def test_explicit_false(self):
        """显式设置 False。"""
        assert _opt(EMPTY, "air_quality") is False
        assert _opt(EMPTY, "gee_ndvi") is False

    def test_missing_key_defaults_true(self):
        """未设置的键默认为 True。"""
        partial = {"air_quality": False}
        assert _opt(partial, "air_quality") is False
        assert _opt(partial, "weather") is True  # 未设置，默认启用


class TestAnyGee:
    """测试 _any_gee 函数。"""

    def test_all_enabled(self):
        assert _any_gee(FULL) is True

    def test_all_disabled(self):
        assert _any_gee(EMPTY) is False

    def test_only_one_enabled(self):
        partial = dict(EMPTY, gee_ndvi=True)
        assert _any_gee(partial) is True

    def test_none_options(self):
        assert _any_gee(None) is True


class TestAnyOsm:
    """测试 _any_osm 函数。"""

    def test_all_enabled(self):
        assert _any_osm(FULL) is True

    def test_all_disabled(self):
        assert _any_osm(EMPTY) is False

    def test_only_roads(self):
        partial = dict(EMPTY, osm_roads=True)
        assert _any_osm(partial) is True

    def test_none_options(self):
        assert _any_osm(None) is True
