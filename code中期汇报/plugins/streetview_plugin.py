"""百度街景插件（基于内部 API，零额外依赖）。

通过百度地图内部接口（mapsv0.bdimg.com）直接获取街景图，
绕过官方 Panorama API 的服务开通限制。
只需 requests 库，无需安装 streetlevel 等重量级依赖。

流程：
  1. WGS84 → BD09MC 坐标转换（优先用百度 geoconv API，失败则本地计算）
  2. 查找最近全景的 panoid
  3. 直接下载四个方向（0°/90°/180°/270°）的街景图
"""
import math
import os
import re
import time

import requests

from utils import make_logger

# ---- 模块级缓存（带 TTL） ----
_CACHE_TTL_SECONDS = 600  # 10 分钟过期

_panoid_cache = {}  # key="lon,lat" -> (panoid, date_str, timestamp)


# ============================================================
#  坐标转换：WGS84 → BD09MC
# ============================================================

def _wgs84_to_gcj02(lon, lat):
    """WGS84 → GCJ02（火星坐标系），纯本地计算。"""
    a = 6378245.0
    ee = 0.00669342162296594323

    def _transform_lat(x, y):
        ret = (-100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y +
               0.1 * x * y + 0.2 * math.sqrt(abs(x)))
        ret += ((20.0 * math.sin(6.0 * x * math.pi) +
                 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0)
        ret += ((20.0 * math.sin(y * math.pi) +
                 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0)
        ret += ((160.0 * math.sin(y / 12.0 * math.pi) +
                 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0)
        return ret

    def _transform_lon(x, y):
        ret = (300.0 + x + 2.0 * y + 0.1 * x * x +
               0.1 * x * y + 0.1 * math.sqrt(abs(x)))
        ret += ((20.0 * math.sin(6.0 * x * math.pi) +
                 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0)
        ret += ((20.0 * math.sin(x * math.pi) +
                 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0)
        ret += ((150.0 * math.sin(x / 12.0 * math.pi) +
                 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0)
        return ret

    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
    dlon = (dlon * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
    return lon + dlon, lat + dlat


def _gcj02_to_bd09(lon, lat):
    """GCJ02 → BD09，纯本地计算。"""
    x, y = lon, lat
    z = math.sqrt(x * x + y * y) + 0.00002 * math.sin(y * math.pi * 3000.0 / 180.0)
    theta = math.atan2(y, x) + 0.000003 * math.cos(x * math.pi * 3000.0 / 180.0)
    return z * math.cos(theta) + 0.0065, z * math.sin(theta) + 0.006


def _bd09_to_bd09mc(lon, lat):
    """BD09 → BD09MC（百度墨卡托），纯本地计算。"""
    EARTH_RADIUS = 6378137.0
    x = lon * math.pi / 180.0 * EARTH_RADIUS
    y = math.log(math.tan(math.pi / 4.0 + lat * math.pi / 360.0)) * EARTH_RADIUS
    return x, y


def _wgs84_to_bd09mc_local(lon, lat):
    """WGS84 → BD09MC，全程本地计算，无需 API Key。"""
    gcj_lon, gcj_lat = _wgs84_to_gcj02(lon, lat)
    bd_lon, bd_lat = _gcj02_to_bd09(gcj_lon, gcj_lat)
    return _bd09_to_bd09mc(bd_lon, bd_lat)


def _wgs84_to_bd09mc_remote(lon, lat, ak, log):
    """WGS84 → BD09MC，通过百度 geoconv API（需 AK）。"""
    try:
        resp = requests.get(
            "https://api.map.baidu.com/geoconv/v1/",
            params={"coords": f"{lon},{lat}", "from": 1, "to": 6, "ak": ak},
            timeout=10,
        )
        data = resp.json()
        if data.get("status") == 0:
            r = data["result"][0]
            return r["x"], r["y"]
        else:
            log(f"geoconv API 失败: status={data.get('status')} {data.get('message', '')}")
            return None, None
    except requests.RequestException as e:
        log(f"geoconv API 网络异常: {e}")
        return None, None
    except (ValueError, KeyError, TypeError) as e:
        log(f"geoconv API 响应解析异常: {e}")
        return None, None


def _to_bd09mc(lon, lat, ak, log):
    """坐标转换：优先用百度 API，失败则本地计算。"""
    if ak:
        x, y = _wgs84_to_bd09mc_remote(lon, lat, ak, log)
        if x is not None:
            return x, y
        log("回退到本地坐标转换...")
    return _wgs84_to_bd09mc_local(lon, lat)


# ============================================================
#  Panoid 查找 & 街景下载
# ============================================================

def _find_panoid(lon, lat, ak, log):
    """通过百度内部接口查找最近的全景 panoid，同时获取拍摄日期。

    Returns:
        (panoid, date_str) 或 (None, None)
        date_str 格式如 "202211"（YYYYMM）。
    """
    cache_key = f"{lon},{lat}"
    if cache_key in _panoid_cache:
        entry = _panoid_cache[cache_key]
        if isinstance(entry, tuple) and len(entry) >= 3:
            panoid, date_str, cached_time = entry
            if time.time() - cached_time < _CACHE_TTL_SECONDS:
                return panoid, date_str
        # 过期或旧格式，删除缓存条目
        del _panoid_cache[cache_key]

    x, y = _to_bd09mc(lon, lat, ak, log)
    log(f"BD09MC 坐标: x={x:.2f}, y={y:.2f}")

    ts = str(int(time.time() * 1000))
    try:
        resp = requests.get(
            "https://mapsv0.bdimg.com/",
            params={
                "qt": "qsdata",
                "x": f"{x:.6f}",
                "y": f"{y:.6f}",
                "l": "17.031",
                "action": "0",
                "mode": "day",
                "t": ts,
            },
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        match = re.search(r'"id":"([^"]+)"', resp.text)
        if match:
            panoid = match.group(1)

            # 尝试解析拍摄日期
            date_str = None
            date_match = re.search(r'"Time":"(\d{6})"', resp.text)
            if date_match:
                date_str = date_match.group(1)
                year, month = date_str[:4], date_str[4:]
                log(f"✅ 找到 panoid: {panoid}，拍摄时间: {year}年{month}月")
            else:
                log(f"✅ 找到 panoid: {panoid}")

            _panoid_cache[cache_key] = (panoid, date_str, time.time())
            return panoid, date_str

        log(f"未找到 panoid，响应片段: {resp.text[:200]}")
    except requests.RequestException as e:
        log(f"查找 panoid 网络异常: {e}")
    except (ValueError, TypeError, AttributeError) as e:
        log(f"查找 panoid 解析异常: {e}")

    _panoid_cache[cache_key] = (None, None, time.time())
    return None, None


def _download_directional(panoid, heading, save_path, log):
    """从百度内部接口下载指定方向的街景图。"""
    try:
        resp = requests.get(
            "https://mapsv0.bdimg.com/",
            params={
                "qt": "pr3d",
                "fovy": "90",
                "quality": "100",
                "panoid": panoid,
                "heading": str(heading),
                "pitch": "0",
                "width": "640",
                "height": "480",
            },
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        ct = resp.headers.get("Content-Type", "")
        if resp.status_code == 200 and "image" in ct:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(resp.content)
            return True
        else:
            log(f"heading={heading}° 下载失败: HTTP {resp.status_code} ct={ct}")
            return False
    except requests.RequestException as e:
        log(f"heading={heading}° 下载网络异常: {e}")
        return False
    except OSError as e:
        log(f"heading={heading}° 文件写入失败: {e}")
        return False


# ============================================================
#  对外接口（与原官方 API 版本签名兼容）
# ============================================================

def get_streetview_metadata(lon, lat, ak, log_callback=None, *,
                            coordtype="wgs84ll", proxies=None):
    """探测指定坐标是否有百度街景覆盖。

    Returns:
        (has_view, date_str): has_view 为 bool，date_str 为拍摄日期字符串（如 "202211"）或 None。
        旧版调用者若只取 bool 值: `has_view = get_streetview_metadata(...)` 仍然兼容。
    """
    log = make_logger(log_callback)
    panoid, date_str = _find_panoid(lon, lat, ak, log)
    return (panoid is not None, date_str)


def download_streetview_image(lon, lat, heading, pitch, ak, save_path,
                              log_callback=None, *,
                              coordtype="wgs84ll", proxies=None):
    """下载指定方向的百度街景图片。"""
    log = make_logger(log_callback)
    panoid, date_str = _find_panoid(lon, lat, ak, log)
    if panoid is None:
        return False
    return _download_directional(panoid, int(heading), save_path, log)
