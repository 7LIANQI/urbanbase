"""数据采集器包 —— 每种数据源一个采集器类。"""

from .air_quality import AirQualityCollector
from .weather import WeatherCollector
from .streetview import StreetViewCollector
from .gee import GEECollector
from .osm import OSMCollector

__all__ = [
    "AirQualityCollector",
    "WeatherCollector",
    "StreetViewCollector",
    "GEECollector",
    "OSMCollector",
]
