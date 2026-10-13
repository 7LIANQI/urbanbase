"""点位坐标系转换：统一转成 WGS84 经纬度（GEE 与地图使用）。

CGCS2000 与 WGS84 在米级以内一致，按相同处理。GCJ-02 / BD-09 为国内加密坐标，用迭代法反算。
"""
import numpy as np

# key -> (显示名, 说明)
CRS_OPTIONS = [
    ("wgs84", "WGS84 经纬度（EPSG:4326）", "GPS、OSM、遥感数据常用，默认"),
    ("cgcs2000", "CGCS2000 经纬度（EPSG:4490）", "国内测绘坐标，与 WGS84 相差在米级以内，按 WGS84 处理"),
    ("gcj02", "GCJ-02（高德 / 腾讯 / 谷歌中国地图）", "国内加密坐标，会转换成 WGS84"),
    ("bd09", "BD-09（百度地图）", "百度加密坐标，会转换成 WGS84"),
    ("epsg3857", "Web 墨卡托（EPSG:3857，单位米）", "投影坐标，X/Y 列是米"),
    ("custom", "其他（自定义 EPSG 代码）", "如 UTM、CGCS2000 投影带等，请填写 EPSG 数字"),
]
LABELS = {k: n for k, n, _ in CRS_OPTIONS}
HINTS = {k: h for k, _, h in CRS_OPTIONS}

_A, _EE = 6378245.0, 0.00669342162296594323
_XPI = np.pi * 3000.0 / 180.0


def _tlat(x, y):
    r = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * np.sqrt(np.abs(x))
    r += (20.0 * np.sin(6.0 * x * np.pi) + 20.0 * np.sin(2.0 * x * np.pi)) * 2.0 / 3.0
    r += (20.0 * np.sin(y * np.pi) + 40.0 * np.sin(y / 3.0 * np.pi)) * 2.0 / 3.0
    r += (160.0 * np.sin(y / 12.0 * np.pi) + 320 * np.sin(y * np.pi / 30.0)) * 2.0 / 3.0
    return r


def _tlon(x, y):
    r = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * np.sqrt(np.abs(x))
    r += (20.0 * np.sin(6.0 * x * np.pi) + 20.0 * np.sin(2.0 * x * np.pi)) * 2.0 / 3.0
    r += (20.0 * np.sin(x * np.pi) + 40.0 * np.sin(x / 3.0 * np.pi)) * 2.0 / 3.0
    r += (150.0 * np.sin(x / 12.0 * np.pi) + 300.0 * np.sin(x / 30.0 * np.pi)) * 2.0 / 3.0
    return r


def _wgs_to_gcj(lon, lat):
    dlat, dlon = _tlat(lon - 105.0, lat - 35.0), _tlon(lon - 105.0, lat - 35.0)
    rad = lat / 180.0 * np.pi
    magic = 1 - _EE * np.sin(rad) ** 2
    sq = np.sqrt(magic)
    dlat = dlat * 180.0 / ((_A * (1 - _EE)) / (magic * sq) * np.pi)
    dlon = dlon * 180.0 / (_A / sq * np.cos(rad) * np.pi)
    inside = (lon > 73.66) & (lon < 135.05) & (lat > 3.86) & (lat < 53.55)    # 境外不加密
    return np.where(inside, lon + dlon, lon), np.where(inside, lat + dlat, lat)


def _gcj_to_wgs(lon, lat):
    wlon, wlat = lon.copy(), lat.copy()
    for _ in range(8):                               # 迭代反算，精度可达 1e-9 度
        glon, glat = _wgs_to_gcj(wlon, wlat)
        wlon, wlat = wlon - (glon - lon), wlat - (glat - lat)
    return wlon, wlat


def _bd_to_gcj(lon, lat):
    x, y = lon - 0.0065, lat - 0.006
    z = np.sqrt(x * x + y * y) - 0.00002 * np.sin(y * _XPI)
    th = np.arctan2(y, x) - 0.000003 * np.cos(x * _XPI)
    return z * np.cos(th), z * np.sin(th)


def to_wgs84(x, y, key="wgs84", epsg=None):
    """x、y 为数组/序列，返回 (lon, lat) 的 numpy 数组。无法解析的值返回 NaN。"""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if key in ("wgs84", "cgcs2000"):
        return x, y
    if key == "gcj02":
        return _gcj_to_wgs(x, y)
    if key == "bd09":
        return _gcj_to_wgs(*_bd_to_gcj(x, y))
    from pyproj import Transformer
    code = 3857 if key == "epsg3857" else int(epsg)
    t = Transformer.from_crs(code, 4326, always_xy=True)
    lon, lat = t.transform(x, y)
    return np.asarray(lon, dtype=float), np.asarray(lat, dtype=float)
