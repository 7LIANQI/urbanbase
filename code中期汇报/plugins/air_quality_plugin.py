"""OpenWeatherMap 空气质量插件。"""
import requests

from utils import make_logger
from config import OPENWEATHER_AIR_POLLUTION_URL


def get_air_quality_by_lonlat(lon, lat, api_key, log_callback=None, proxies=None):
    """获取 AQI 和污染物浓度。

    Args:
        proxies: 可选，requests 格式的代理字典，如 {"http": "...", "https": "..."}
    """
    log = make_logger(log_callback)

    params = {"lat": lat, "lon": lon, "appid": api_key}
    try:
        resp = requests.get(
            OPENWEATHER_AIR_POLLUTION_URL,
            params=params, timeout=10, proxies=proxies,
        )
        if resp.status_code == 200:
            data = resp.json()
            if "list" in data and len(data["list"]) > 0:
                item = data["list"][0]
                return {
                    "code": "200",
                    "now": {
                        "aqi": item["main"]["aqi"],
                        "components": item["components"],
                    },
                }
        else:
            log(f"OpenWeatherMap 返回 HTTP {resp.status_code}")
    except Exception as e:
        log(f"OpenWeatherMap 请求异常: {e}")
    return None
