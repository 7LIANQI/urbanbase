"""测试街景插件中的坐标转换函数。

验证 WGS84 → GCJ02 → BD09 → BD09MC 转换链的正确性。
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 直接导入内部函数进行白盒测试
from plugins.streetview_plugin import (
    _wgs84_to_gcj02,
    _gcj02_to_bd09,
    _bd09_to_bd09mc,
    _wgs84_to_bd09mc_local,
)


class TestWGS84ToGCJ02:
    """测试 WGS84 → GCJ02 坐标转换。"""

    def test_beijing_tiananmen(self):
        """天安门广场坐标转换。"""
        lon, lat = _wgs84_to_gcj02(116.3912, 39.9055)
        # GCJ02 与 WGS84 偏移通常在 100-700 米（约 0.001-0.007 度）
        assert abs(lon - 116.3912) < 0.02
        assert abs(lat - 39.9055) < 0.02
        # 偏移不应该为 0（中国境内应有显著偏移）
        offset = math.sqrt((lon - 116.3912) ** 2 + (lat - 39.9055) ** 2)
        assert offset > 0.001, f"偏移过小: {offset}，可能转换未生效"

    def test_shanghai(self):
        """上海陆家嘴坐标转换。"""
        lon, lat = _wgs84_to_gcj02(121.4737, 31.2304)
        assert abs(lon - 121.4737) < 0.02
        assert abs(lat - 31.2304) < 0.02
        offset = math.sqrt((lon - 121.4737) ** 2 + (lat - 31.2304) ** 2)
        assert offset > 0.001

    def test_return_type(self):
        """测试返回类型。"""
        result = _wgs84_to_gcj02(116.0, 40.0)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert all(isinstance(v, float) for v in result)


class TestGCJ02ToBD09:
    """测试 GCJ02 → BD09 坐标转换。"""

    def test_beijing(self):
        """北京 GCJ02 → BD09。"""
        gcj_lon, gcj_lat = _wgs84_to_gcj02(116.3912, 39.9055)
        bd_lon, bd_lat = _gcj02_to_bd09(gcj_lon, gcj_lat)
        # BD09 额外偏移通常较小（<0.005度）
        assert abs(bd_lon - gcj_lon) < 0.01
        assert abs(bd_lat - gcj_lat) < 0.01


class TestBD09ToBD09MC:
    """测试 BD09 → BD09MC（百度墨卡托）转换。"""

    def test_beijing_meters(self):
        """北京 BD09 转墨卡托应为米级坐标。"""
        gcj_lon, gcj_lat = _wgs84_to_gcj02(116.3912, 39.9055)
        bd_lon, bd_lat = _gcj02_to_bd09(gcj_lon, gcj_lat)
        x, y = _bd09_to_bd09mc(bd_lon, bd_lat)
        # 北京附近 BD09MC 坐标大约在 x=12950000, y=4850000 附近
        assert 12_000_000 < x < 14_000_000, f"x={x} 超出预期范围"
        assert 4_000_000 < y < 6_000_000, f"y={y} 超出预期范围"


class TestWGS84ToBD09MCLocal:
    """测试完整的 WGS84 → BD09MC 本地转换链。"""

    def test_chain_returns_meters(self):
        """完整转换链返回米级坐标。"""
        x, y = _wgs84_to_bd09mc_local(116.3912, 39.9055)
        assert 12_000_000 < x < 14_000_000
        assert 4_000_000 < y < 6_000_000

    def test_different_points_different_results(self):
        """不同坐标应产生不同的结果。"""
        x1, y1 = _wgs84_to_bd09mc_local(116.3912, 39.9055)
        x2, y2 = _wgs84_to_bd09mc_local(121.4737, 31.2304)
        # 北京和上海的结果应显著不同
        assert abs(x1 - x2) > 100_000
        assert abs(y1 - y2) > 100_000
