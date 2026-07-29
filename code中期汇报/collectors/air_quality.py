"""空气质量采集器。"""
import json

from .base import BaseCollector
from plugins.air_quality_plugin import get_air_quality_by_lonlat


class AirQualityCollector(BaseCollector):
    """采集 OpenWeatherMap 空气质量数据。"""

    collector_name = "air_quality"

    def collect(self):
        api_key = self.kwargs.get("openweather_key", "")

        if not api_key:
            self.log("⚠️ 未提供 OpenWeatherMap Key")
            return {}

        self.log("获取空气质量...")
        data = get_air_quality_by_lonlat(
            self.lon, self.lat, api_key,
            log_callback=self.kwargs.get("log_callback"),
        )
        if data:
            path = self._path("air_quality.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.log(f"  AQI 等级: {data['now']['aqi']}")
            return {"air_quality": path}

        self.log("空气质量获取失败")
        return {}
