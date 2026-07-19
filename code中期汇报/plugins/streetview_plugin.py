# streetview_plugin.py  （百度街景/全景静态图版本）
import os
import requests

# 百度全景静态图 API
BAIDU_PANORAMA_URL = "https://api.map.baidu.com/panorama/v2"

def _lnglat_str(lon, lat, coordtype: str = "wgs84ll") -> str:
    return f"{float(lon)},{float(lat)}"


def get_streetview_metadata(lon, lat, ak, log_callback=None, *, coordtype="wgs84ll"):
    def log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    location = _lnglat_str(lon, lat, coordtype)
    params = {
        "ak": ak,
        "location": location,
        "width": 64,
        "height": 64,
        "heading": 0,
        "pitch": 0,
        "fov": 90,
    }
    if coordtype:
        params["coordtype"] = coordtype

    try:
        r = requests.get(BAIDU_PANORAMA_URL, params=params, timeout=8)
        ct = r.headers.get("Content-Type", "")
        if r.status_code == 200 and "image" in ct:
            return True
        else:
            # 常见：该点无街景，会返回小图/状态码/非image
            log(f"百度街景探测：无覆盖或返回非图片 content-type={ct}")
            return False
    except Exception as e:
        log(f"百度街景探测异常: {e}")
        return False


def download_streetview_image(
    lon, lat, heading, pitch, ak, save_path, log_callback=None, *, coordtype="wgs84ll"
):
    def log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    location = _lnglat_str(lon, lat, coordtype)
    params = {
        "ak": ak,
        "location": location,
        "width": 640,
        "height": 480,
        "heading": int(heading),
        "pitch": int(pitch),
        "fov": 90,
    }
    if coordtype:
        params["coordtype"] = coordtype

    try:
        resp = requests.get(BAIDU_PANORAMA_URL, params=params, timeout=10)
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