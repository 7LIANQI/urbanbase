"""百度街景/全景静态图插件。

注意：百度地图 API 会检测请求来源 IP。走代理后会变成海外 IP，
百度会拒绝服务。因此默认 proxies=None（直连），仅在特殊场景下才传代理。
"""
import os
import requests

from utils import make_logger
from config import BAIDU_PANORAMA_URL


def _lnglat_str(lon, lat):
    return f"{float(lon)},{float(lat)}"


def get_streetview_metadata(lon, lat, ak, log_callback=None, *,
                            coordtype="wgs84ll", proxies=None):
    """探测指定坐标是否有百度街景覆盖。"""
    log = make_logger(log_callback)

    params = {
        "ak": ak,
        "location": _lnglat_str(lon, lat),
        "width": 64,
        "height": 64,
        "heading": 0,
        "pitch": 0,
        "fov": 90,
    }
    if coordtype:
        params["coordtype"] = coordtype

    try:
        r = requests.get(BAIDU_PANORAMA_URL, params=params,
                         timeout=8, proxies=proxies)
        ct = r.headers.get("Content-Type", "")
        if r.status_code == 200 and "image" in ct:
            return True
        else:
            log(f"百度街景探测：无覆盖或返回非图片 content-type={ct}")
            return False
    except Exception as e:
        log(f"百度街景探测异常: {e}")
        return False


def download_streetview_image(lon, lat, heading, pitch, ak, save_path,
                              log_callback=None, *,
                              coordtype="wgs84ll", proxies=None):
    """下载指定方向的百度街景图片。"""
    log = make_logger(log_callback)

    params = {
        "ak": ak,
        "location": _lnglat_str(lon, lat),
        "width": 640,
        "height": 480,
        "heading": int(heading),
        "pitch": int(pitch),
        "fov": 90,
    }
    if coordtype:
        params["coordtype"] = coordtype

    try:
        resp = requests.get(BAIDU_PANORAMA_URL, params=params,
                            timeout=10, proxies=proxies)
        ct = resp.headers.get("Content-Type", "")
        if resp.status_code == 200 and "image" in ct:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(resp.content)
            return True
        else:
            log(f"百度街景图获取失败: HTTP {resp.status_code} ct={ct}")
            log(f"   响应片段: {resp.text[:300]}")
            return False
    except Exception as e:
        log(f"百度街景图片下载异常: {e}")
        return False
