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

        self.log("获取街景（百度）...")
        has_view, date_str, panoid = get_streetview_metadata(
            self.lon, self.lat, baidu_key or "",
            log_callback=self.kwargs.get("log_callback"),
        )
        if not has_view:
            self.log("⚠️ 该地点无百度街景覆盖或请求失败")
            return {}

        img_dir = self._ensure_dir("streetview_images")
        files = {}
        archived_count = 0

        for angle in self.HEADINGS:
            img_path = f"{img_dir}/heading_{angle}.jpg"
            success = download_streetview_image(
                self.lon, self.lat, angle, 0, baidu_key or "", img_path,
                log_callback=self.kwargs.get("log_callback"),
            )
            if success:
                files.setdefault("streetview_images", []).append(img_path)
                # 自动存档到本地街景数据库
                try:
                    from plugins.streetview_archive import StreetViewArchive
                    archive = StreetViewArchive()
                    archive.save(
                        self.lon, self.lat, panoid, date_str or "",
                        angle, img_path,
                    )
                    archived_count += 1
                except Exception:
                    pass
            time.sleep(0.15)

        if archived_count > 0:
            self.log(f"  📂 已存档 {archived_count} 张街景到本地数据库")

        # 检查是否有历史存档可对比
        try:
            from plugins.streetview_archive import StreetViewArchive
            archive = StreetViewArchive()
            summary = archive.get_summary(self.lon, self.lat)
            if summary["count"] > archived_count:
                self.log(
                    f"  💡 该位置有 {summary['count']} 条历史街景记录 "
                    f"（{summary['date_range']}），可进行时间对比"
                )
        except Exception:
            pass

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
