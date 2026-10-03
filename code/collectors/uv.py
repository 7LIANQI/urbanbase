"""本地紫外线数据采集器。"""
from .base import BaseCollector
from plugins.uv_plugin import get_uv_stats
from config import UV_DATA_DIR


class UVCollector(BaseCollector):
    """从本地 netCDF3 文件读取紫外线数据（中国晴空紫外数据集）。"""

    collector_name = "uv"

    def collect(self):
        data_dir = self.kwargs.get("uv_data_dir") or UV_DATA_DIR
        if not data_dir:
            self.log("⚠️ 未配置紫外线数据目录")
            return {}
        self.log("读取本地紫外线数据...")
        return get_uv_stats(
            self.lon, self.lat, data_dir, self.output_dir,
            log_callback=self.kwargs.get("log_callback"),
        )
