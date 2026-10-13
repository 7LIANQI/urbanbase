"""坐标系转换：GCJ-02 / BD-09 往返误差、投影坐标、境外不加密。"""
import numpy as np

from core.crs import _wgs_to_gcj, to_wgs84


def test_crs_roundtrip():
    lon, lat = np.array([113.264, 76.0, 116.3912]), np.array([23.129, 39.47, 39.9055])
    glon, glat = _wgs_to_gcj(lon, lat)
    assert np.abs(glon - lon).max() > 1e-4                     # 确实偏移了
    blon, blat = to_wgs84(glon, glat, "gcj02")
    assert np.abs(blon - lon).max() < 1e-7 and np.abs(blat - lat).max() < 1e-7
    # 境外不偏移
    olon, olat = _wgs_to_gcj(np.array([-0.12]), np.array([51.5]))
    assert olon[0] == -0.12 and olat[0] == 51.5
    # Web 墨卡托
    x, y = to_wgs84([12600000.0], [2650000.0], "epsg3857")
    assert abs(x[0] - 113.19) < 0.01 and abs(y[0] - 23.15) < 0.01
    assert to_wgs84([1.0], [2.0], "wgs84")[0][0] == 1.0
