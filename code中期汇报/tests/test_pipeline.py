"""测试 pipeline.py 中的辅助函数。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline import _opt, _any_gee, _any_osm, _resolve_proxies

# 完整默认选项
FULL = {
    "air_quality": True, "weather": True, "streetview": True,
    "gee_viirs": True, "gee_ndvi": True, "gee_lst": True,
    "gee_elevation": True, "gee_precipitation": True,
    "gee_ndwi": True, "gee_evi": True, "gee_population": True,
    "gee_era5_climate": True, "gee_era5_hourly": True,
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


class TestResolveProxies:
    """测试 _resolve_proxies 函数。"""

    def test_no_proxy_config(self):
        result = _resolve_proxies(None)
        assert result["air_proxy"] is None
        assert result["street_proxy"] is None
        assert result["gee_proxy"] is None
        assert result["osm_proxy"] is None

    def test_full_proxy(self):
        config = {
            "url": "http://127.0.0.1:7890",
            "air": True, "street": True, "gee": True, "osm": True,
        }
        result = _resolve_proxies(config)
        assert result["air_proxy"] == {"http": "http://127.0.0.1:7890",
                                       "https": "http://127.0.0.1:7890"}
        assert result["street_proxy"] is not None
        assert result["gee_proxy"] == "http://127.0.0.1:7890"
        assert result["osm_proxy"] is not None

    def test_street_direct(self):
        """百度街景默认直连（不走代理）。"""
        config = {"url": "http://127.0.0.1:7890"}
        result = _resolve_proxies(config)
        # 默认：street=False
        assert result["street_proxy"] is None
        # 默认：air/gee/osm=True
        assert result["air_proxy"] is not None
        assert result["gee_proxy"] is not None
        assert result["osm_proxy"] is not None
