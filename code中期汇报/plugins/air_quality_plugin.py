import requests

def get_air_quality_by_lonlat(lon, lat, api_key, log_callback=None):
    """获取 AQI 和污染物浓度"""
    def log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)
    url = "https://api.openweathermap.org/data/2.5/air_pollution"
    params = {"lat": lat, "lon": lon, "appid": api_key}
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if "list" in data and len(data["list"]) > 0:
                item = data["list"][0]
                return {"code": "200", "now": {"aqi": item["main"]["aqi"], "components": item["components"]}}
        else:
            log(f"OpenWeatherMap 返回 HTTP {resp.status_code}")
    except Exception as e:
        log(f"OpenWeatherMap 请求异常: {e}")
    return None