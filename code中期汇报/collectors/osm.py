"""OSM 矢量数据采集器。"""
import json
import os

from .base import BaseCollector
from plugins.osm_plugin import get_osm_vector_data, compute_osm_stats


class OSMCollector(BaseCollector):
    """采集 OpenStreetMap 矢量数据并计算统计指标。"""

    collector_name = "osm"

    # 子模块映射: option_key -> (log_label, geojson_filename)
    SUB_MODULES = {
        "osm_roads":        ("道路", "roads.geojson"),
        "osm_buildings":    ("建筑", "buildings.geojson"),
        "osm_green_spaces": ("绿地", "green_spaces.geojson"),
        "osm_water_bodies": ("水体", "water_bodies.geojson"),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.options = self.kwargs.get("options") or {}

    def _opt(self, key):
        return self.options.get(key, True)

    def collect(self):
        # 检查是否启用了任何 OSM 子模块
        enabled = any(self._opt(k) for k in self.SUB_MODULES) or self._opt("osm_stats")
        if not enabled:
            self.log("⏭️ OSM 矢量数据模块已禁用")
            return {}

        self.log("下载 OSM 矢量数据...")
        get_osm_vector_data(
            self.lon, self.lat, self.radius, self.output_dir,
            log_callback=self.kwargs.get("log_callback"),
        )

        files = {}
        for key, (_label, filename) in self.SUB_MODULES.items():
            if self._opt(key):
                geojson_path = self._path(filename)
                if os.path.exists(geojson_path):
                    files[key] = geojson_path

        # OSM 统计指标
        if self._opt("osm_stats"):
            self.log("计算 OSM 统计指标...")
            compute_osm_stats(
                self.output_dir, self.radius,
                log_callback=self.kwargs.get("log_callback"),
            )
            stats_path = self._path("osm_stats.json")
            if os.path.exists(stats_path):
                files["osm_stats"] = stats_path
        else:
            self.log("⏭️ OSM 统计指标已禁用")

        return files
