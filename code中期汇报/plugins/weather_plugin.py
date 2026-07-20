"""OpenWeatherMap 气象数据插件：气温、湿度、气压、风速等。

使用 Current Weather API，与空气质量共用同一个 API Key。
"""
from utils import make_logger

# OpenWeatherMap Current Weather API
OPENWEATHER_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"


def get_weather_by_lonlat(lon, lat, api_key, log_callback=None, proxies=None):
    """获取实时天气数据（气温、湿度、气压、风速、云量等）。

    Args:
        proxies: 可选，requests 格式的代理字典。

    Returns:
        dict 或 None: {
            "code": "200",
            "now": {
                "temp_c": 25.3,         # 气温 (℃)
                "feels_like_c": 26.1,   # 体感温度 (℃)
                "humidity": 65,          # 相对湿度 (%)
                "pressure_hpa": 1013,    # 气压 (hPa)
                "wind_speed_ms": 3.5,   # 风速 (m/s)
                "wind_deg": 180,         # 风向 (度)
                "clouds": 75,            # 云量 (%)
                "weather": "多云",       # 天气描述
            }
        }
    """
    import requests
    log = make_logger(log_callback)

    params = {
        "lat": lat, "lon": lon,
        "appid": api_key,
        "units": "metric",   # 摄氏度
        "lang": "zh_cn",     # 中文天气描述
    }
    try:
        resp = requests.get(OPENWEATHER_WEATHER_URL, params=params,
                            timeout=10, proxies=proxies)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "code": "200",
                "now": {
                    "temp_c": data["main"].get("temp"),
                    "feels_like_c": data["main"].get("feels_like"),
                    "humidity": data["main"].get("humidity"),
                    "pressure_hpa": data["main"].get("pressure"),
                    "wind_speed_ms": data["wind"].get("speed"),
                    "wind_deg": data["wind"].get("deg"),
                    "clouds": data["clouds"].get("all"),
                    "weather": data["weather"][0]["description"]
                    if data.get("weather") else "N/A",
                },
            }
        else:
            log(f"天气 API 返回 HTTP {resp.status_code}")
    except Exception as e:
        log(f"天气数据请求异常: {e}")
    return None
