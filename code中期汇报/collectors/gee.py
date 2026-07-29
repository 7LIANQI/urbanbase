"""Google Earth Engine 遥感数据采集器。"""
import os
from datetime import datetime, timedelta

from .base import BaseCollector
from plugins.gee_plugin import (
    initialize_gee,
    get_gee_stats,
    get_era5_climate_stats,
    get_era5_hourly_stats,
    get_elevation_stats,
    get_precipitation_stats,
    get_ndwi_evi_stats,
    get_population_stats,
    get_landcover_stats,
    get_s5p_no2_stats,
    get_jrc_water_stats,
    get_modis_lst_stats,
    get_dynamic_world_stats,
    get_hansen_forest_stats,
    get_canopy_height_stats,
)


class GEECollector(BaseCollector):
    """采集 GEE 遥感数据（VIIRS/NDVI/LST/ERA5/海拔/降水/NDWI/EVI/人口）。"""

    collector_name = "gee"

    # 子模块: option_key -> (label, csv_filename)
    SUB_MODULES = {
        "gee_viirs":       ("VIIRS 夜光", "viirs_stats.csv"),
        "gee_ndvi":        ("NDVI 植被", "ndvi_stats.csv"),
        "gee_lst":         ("LST 地表温度", "lst_stats.csv"),
        "gee_elevation":   ("海拔", "elevation_stats.csv"),
        "gee_precipitation": ("降水", "precipitation_stats.csv"),
        "gee_ndwi":        ("NDWI 水体", "ndwi_stats.csv"),
        "gee_evi":         ("EVI 植被", "evi_stats.csv"),
        "gee_population":  ("人口", "population_stats.csv"),
        "gee_era5_climate": ("ERA5 气候逐日", "era5_climate_stats.csv"),
        "gee_era5_hourly": ("ERA5 逐时", "era5_hourly.csv"),
        # ---- 新增遥感模块 ----
        "gee_landcover":   ("土地覆盖", "landcover_stats.csv"),
        "gee_s5p_no2":     ("Sentinel-5P NO₂", "s5p_no2_stats.csv"),
        "gee_jrc_water":   ("JRC 地表水", "jrc_water_stats.csv"),
        "gee_modis_lst":   ("MODIS LST", "modis_lst_stats.csv"),
        "gee_dynamic_world": ("Dynamic World", "dw_stats.csv"),
        "gee_hansen_forest": ("Hansen 森林变化", "hansen_forest_stats.csv"),
        "gee_canopy_height": ("树冠高度", "canopy_height_stats.csv"),
    }

    # 核心遥感指标（合并为一次 GEE 调用的模块）
    CORE_KEYS = ["gee_viirs", "gee_ndvi", "gee_lst"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.options = self.kwargs.get("options") or {}
        self._gee_initialized = False

    def _opt(self, key):
        return self.options.get(key, True)

    def _any_enabled(self, keys):
        return any(self._opt(k) for k in keys)

    def _init_gee(self):
        """延迟初始化 GEE（只执行一次）。"""
        if self._gee_initialized:
            return True

        gee_key_path = self.kwargs.get("gee_key_path")
        log_callback = self.kwargs.get("log_callback")

        self.log("初始化 GEE...")
        ok = initialize_gee(
            key_path=gee_key_path,
            log_callback=log_callback,
        )
        if not ok:
            self.log("⚠️ GEE 初始化失败，跳过遥感模块")
            return False

        self._gee_initialized = True
        return True

    def collect(self):
        # 检查是否启用了任何 GEE 子模块
        all_keys = list(self.SUB_MODULES)
        if not self._any_enabled(all_keys):
            self.log("⏭️ 遥感数据模块已禁用")
            return {}

        if not self._init_gee():
            return {}

        # 懒加载 ee（仅在需要时导入）
        import ee
        roi = ee.Geometry.Point(self.lon, self.lat).buffer(self.radius).bounds()
        log_cb = self.kwargs.get("log_callback")
        files = {}

        try:
            # ---- 核心遥感指标（合并调用） ----
            if self._any_enabled(self.CORE_KEYS):
                self.log("计算核心遥感指标...")
                get_gee_stats(
                    roi, self.start_date, self.end_date, self.output_dir,
                    log_callback=log_cb,
                    enable_viirs=self._opt("gee_viirs"),
                    enable_ndvi=self._opt("gee_ndvi"),
                    enable_lst=self._opt("gee_lst"),
                )
                if self._opt("gee_viirs"):
                    files["viirs_stats"] = self._path("viirs_stats.csv")
                if self._opt("gee_ndvi"):
                    files["ndvi_stats"] = self._path("ndvi_stats.csv")
                if self._opt("gee_lst"):
                    files["lst_stats"] = self._path("lst_stats.csv")
            else:
                self.log("⏭️ 核心遥感指标已禁用")

            # ---- 海拔 ----
            if self._opt("gee_elevation"):
                self.log("获取海拔数据...")
                get_elevation_stats(roi, self.output_dir, log_callback=log_cb)
                files["elevation_stats"] = self._path("elevation_stats.csv")
            else:
                self.log("⏭️ 海拔数据已禁用")

            # ---- 降水 ----
            if self._opt("gee_precipitation"):
                self.log("获取降水数据...")
                get_precipitation_stats(
                    roi, self.start_date, self.end_date, self.output_dir,
                    log_callback=log_cb,
                )
                files["precipitation_stats"] = self._path("precipitation_stats.csv")
            else:
                self.log("⏭️ 降水数据已禁用")

            # ---- NDWI + EVI ----
            if self._any_enabled(["gee_ndwi", "gee_evi"]):
                self.log("获取 NDWI/EVI 数据...")
                get_ndwi_evi_stats(
                    roi, self.start_date, self.end_date, self.output_dir,
                    log_callback=log_cb,
                    enable_ndwi=self._opt("gee_ndwi"),
                    enable_evi=self._opt("gee_evi"),
                )
                if self._opt("gee_ndwi"):
                    files["ndwi_stats"] = self._path("ndwi_stats.csv")
                if self._opt("gee_evi"):
                    files["evi_stats"] = self._path("evi_stats.csv")
            else:
                self.log("⏭️ NDWI/EVI 已禁用")

            # ---- 人口密度 ----
            if self._opt("gee_population"):
                self.log("获取人口密度数据...")
                get_population_stats(roi, self.output_dir, log_callback=log_cb)
                files["population_stats"] = self._path("population_stats.csv")
            else:
                self.log("⏭️ 人口密度已禁用")

            # ---- ERA5 气候逐日 ----
            if self._opt("gee_era5_climate"):
                self.log("计算 ERA5 气候逐日数据...")
                get_era5_climate_stats(
                    roi, self.start_date, self.end_date, self.output_dir,
                    log_callback=log_cb,
                )
                files["era5_climate_stats"] = self._path("era5_climate_stats.csv")
            else:
                self.log("⏭️ ERA5 气候逐日已禁用")

            # ---- ERA5 逐时 ----
            if self._opt("gee_era5_hourly"):
                # 使用用户指定的 end_date；ERA5-Land 有 3-5 天延迟，
                # 若用户选的 end_date 太新可能无数据，回退到 7 天前
                if self.end_date:
                    latest_date = self.end_date
                else:
                    latest_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
                self.log(f"计算 ERA5 逐时数据（{latest_date}）...")
                get_era5_hourly_stats(
                    roi, latest_date, self.output_dir,
                    log_callback=log_cb,
                )
                files["era5_hourly"] = self._path("era5_hourly.csv")
            else:
                self.log("⏭️ ERA5 逐时已禁用")

            # ==== 新增遥感模块 ====

            # ---- 土地覆盖 (ESA WorldCover) ----
            if self._opt("gee_landcover"):
                self.log("获取 ESA WorldCover 土地覆盖数据...")
                get_landcover_stats(roi, self.output_dir, log_callback=log_cb)
                files["landcover_stats"] = self._path("landcover_stats.csv")
            else:
                self.log("⏭️ 土地覆盖已禁用")

            # ---- Sentinel-5P NO₂ ----
            if self._opt("gee_s5p_no2"):
                self.log("获取 Sentinel-5P 对流层 NO₂ 数据...")
                get_s5p_no2_stats(
                    roi, self.start_date, self.end_date, self.output_dir,
                    log_callback=log_cb,
                )
                files["s5p_no2_stats"] = self._path("s5p_no2_stats.csv")
            else:
                self.log("⏭️ Sentinel-5P NO₂ 已禁用")

            # ---- JRC 地表水 ----
            if self._opt("gee_jrc_water"):
                self.log("获取 JRC 全球地表水数据...")
                get_jrc_water_stats(roi, self.output_dir, log_callback=log_cb)
                files["jrc_water_stats"] = self._path("jrc_water_stats.csv")
            else:
                self.log("⏭️ JRC 地表水已禁用")

            # ---- MODIS LST ----
            if self._opt("gee_modis_lst"):
                self.log("获取 MODIS 8天 LST 数据...")
                get_modis_lst_stats(
                    roi, self.start_date, self.end_date, self.output_dir,
                    log_callback=log_cb,
                )
                files["modis_lst_stats"] = self._path("modis_lst_stats.csv")
            else:
                self.log("⏭️ MODIS LST 已禁用")

            # ---- Dynamic World ----
            if self._opt("gee_dynamic_world"):
                self.log("获取 Dynamic World 土地覆盖数据...")
                get_dynamic_world_stats(
                    roi, self.start_date, self.end_date, self.output_dir,
                    log_callback=log_cb,
                )
                files["dw_stats"] = self._path("dw_stats.csv")
            else:
                self.log("⏭️ Dynamic World 已禁用")

            # ---- Hansen 森林变化 ----
            if self._opt("gee_hansen_forest"):
                self.log("获取 Hansen 森林变化数据...")
                get_hansen_forest_stats(roi, self.output_dir, log_callback=log_cb)
                files["hansen_forest_stats"] = self._path("hansen_forest_stats.csv")
                # 逐年损失数据（额外产出）
                loss_year_path = self._path("hansen_loss_by_year.csv")
                if os.path.exists(loss_year_path):
                    files["hansen_loss_by_year"] = loss_year_path
            else:
                self.log("⏭️ Hansen 森林变化已禁用")

            # ---- 树冠高度 ----
            if self._opt("gee_canopy_height"):
                self.log("获取 ETH 全球树冠高度数据...")
                get_canopy_height_stats(roi, self.output_dir, log_callback=log_cb)
                files["canopy_height_stats"] = self._path("canopy_height_stats.csv")
            else:
                self.log("⏭️ 树冠高度已禁用")

        except Exception as e:
            self.log(f"⚠️ GEE 数据处理失败: {e}")

        return files
