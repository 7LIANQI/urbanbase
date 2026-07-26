"""实时天气采集器。"""
import json

from .base import BaseCollector
from plugins.weather_plugin import get_weather_by_lonlat


class WeatherCollector(BaseCollector):
    """采集 OpenWeatherMap 实时天气数据。"""

    collector_name = "weather"

    def collect(self):
        api_key = self.kwargs.get("openweather_key", "")
        proxies = self.kwargs.get("air_proxy")

        if not api_key:
            self.log("⚠️ 未提供 OpenWeatherMap Key，跳过天气")
            return {}

        self.log("获取实时天气...")
        data = get_weather_by_lonlat(
            self.lon, self.lat, api_key,
            log_callback=self.kwargs.get("log_callback"),
            proxies=proxies,
        )
        if data:
            path = self._path("weather.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            w = data["now"]
            self.log(f"  气温: {w['temp_c']}℃, 湿度: {w['humidity']}%, 天气: {w['weather']}")
            return {"weather": path}

        self.log("天气数据获取失败")
        return {}
