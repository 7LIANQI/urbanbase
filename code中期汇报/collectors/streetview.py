"""街景采集器。"""
import time

from .base import BaseCollector
from plugins.streetview_plugin import get_streetview_metadata, download_streetview_image


class StreetViewCollector(BaseCollector):
    """采集百度街景全景图片。"""

    collector_name = "streetview"

    HEADINGS = [0, 90, 180, 270]

    def collect(self):
        baidu_key = self.kwargs.get("baidu_key", "")
        proxies = self.kwargs.get("street_proxy")

        self.log("获取街景（百度）...")
        has_view, date_str = get_streetview_metadata(
            self.lon, self.lat, baidu_key or "",
            log_callback=self.kwargs.get("log_callback"),
            proxies=proxies,
        )
        if not has_view:
            self.log("⚠️ 该地点无百度街景覆盖或请求失败")
            return {}

        img_dir = self._ensure_dir("streetview_images")
        files = {}
        for angle in self.HEADINGS:
            img_path = f"{img_dir}/heading_{angle}.jpg"
            success = download_streetview_image(
                self.lon, self.lat, angle, 0, baidu_key or "", img_path,
                log_callback=self.kwargs.get("log_callback"),
                proxies=proxies,
            )
            if success:
                files.setdefault("streetview_images", []).append(img_path)
            time.sleep(0.15)

        # 写入街景状态文件（含拍摄日期）
        meta_path = self._path("streetview_status.txt")
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write("Baidu Street View Available\n")
            if date_str:
                year, month = date_str[:4], date_str[4:]
                f.write(f"date={date_str}\n")
                f.write(f"拍摄时间: {year}年{month}月\n")
        files["streetview_metadata"] = meta_path

        return files
