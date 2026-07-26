"""OpenWeatherMap 空气质量插件。"""
import json as _json

import requests

from utils import make_logger, retry_on_network_error
from config import OPENWEATHER_AIR_POLLUTION_URL


@retry_on_network_error(max_retries=2, base_delay=0.5)
def _fetch_air_quality(lon, lat, api_key, proxies):
    """实际发起 API 请求（带重试）。"""
    return requests.get(
        OPENWEATHER_AIR_POLLUTION_URL,
        params={"lat": lat, "lon": lon, "appid": api_key},
        timeout=10, proxies=proxies,
    )


def get_air_quality_by_lonlat(lon, lat, api_key, log_callback=None, proxies=None):
    """获取 AQI 和污染物浓度。

    Args:
        proxies: 可选，requests 格式的代理字典，如 {"http": "...", "https": "..."}
    """
    log = make_logger(log_callback)

    try:
        resp = _fetch_air_quality(lon, lat, api_key, proxies)
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
    except requests.RequestException as e:
        log(f"OpenWeatherMap 请求异常: {e}")
    except _json.JSONDecodeError as e:
        log(f"OpenWeatherMap 响应解析失败: {e}")
    except (ValueError, KeyError, TypeError) as e:
        log(f"OpenWeatherMap 数据结构异常: {e}")
    return None
