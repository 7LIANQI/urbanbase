#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""城市街道环境大数据采集 —— 核心采集管线。

重构为采集器架构：每种数据源由独立的 Collector 类负责，
process_location() 作为轻量编排器遍历已启用的采集器。
支持并行采集以提高吞吐量。
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from utils import make_logger
from collectors import (
    AirQualityCollector,
    WeatherCollector,
    StreetViewCollector,
    GEECollector,
    OSMCollector,
)

# 默认选项：全部启用
_DEFAULT_OPTIONS = {
    "air_quality": True,
    "weather": True,
    "streetview": True,
    "gee_viirs": True,
    "gee_ndvi": True,
    "gee_lst": True,
    "gee_elevation": True,
    "gee_precipitation": True,
    "gee_ndwi": True,
    "gee_evi": True,
    "gee_population": True,
    "gee_era5_climate": True,
    "gee_era5_hourly": True,
    "gee_landcover": True,
    "gee_s5p_no2": True,
    "gee_jrc_water": True,
    "gee_modis_lst": True,
    "gee_dynamic_world": True,
    "gee_hansen_forest": True,
    "gee_canopy_height": True,
    "osm_roads": True,
    "osm_buildings": True,
    "osm_green_spaces": True,
    "osm_water_bodies": True,
    "osm_stats": True,
}


def _opt(options, key):
    """安全获取选项值，options 为 None 时默认全部启用。"""
    if options is None:
        return True
    return options.get(key, True)


def _any_gee(options):
    """判断是否启用了任意 GEE 子模块。"""
    gee_keys = [
        "gee_viirs", "gee_ndvi", "gee_lst", "gee_elevation",
        "gee_precipitation", "gee_ndwi", "gee_evi", "gee_population",
        "gee_era5_climate", "gee_era5_hourly",
        "gee_landcover", "gee_s5p_no2", "gee_jrc_water",
        "gee_modis_lst", "gee_dynamic_world", "gee_hansen_forest",
        "gee_canopy_height",
    ]
    return any(_opt(options, k) for k in gee_keys)


def _any_osm(options):
    """判断是否启用了任意 OSM 子模块。"""
    osm_keys = [
        "osm_roads", "osm_buildings", "osm_green_spaces",
        "osm_water_bodies", "osm_stats",
    ]
    return any(_opt(options, k) for k in osm_keys)


def _build_collectors(lon, lat, radius, start_date, end_date,
                      output_dir, log, options, baidu_key,
                      openweather_key, gee_key_path, log_callback):
    """构建所有启用的采集器实例。"""
    common = dict(
        lon=lon, lat=lat, radius=radius,
        start_date=start_date, end_date=end_date,
        output_dir=output_dir, log=log,
        log_callback=log_callback,
        options=options,
    )

    collectors = []

    if _opt(options, "air_quality"):
        collectors.append(AirQualityCollector(
            **common,
            openweather_key=openweather_key,
        ))

    if _opt(options, "weather"):
        collectors.append(WeatherCollector(
            **common,
            openweather_key=openweather_key,
        ))

    if _opt(options, "streetview"):
        collectors.append(StreetViewCollector(
            **common,
            baidu_key=baidu_key,
        ))

    if _any_gee(options):
        collectors.append(GEECollector(
            **common,
            gee_key_path=gee_key_path,
        ))

    if _any_osm(options):
        collectors.append(OSMCollector(**common))

    return collectors


def process_location(lon, lat, radius=500, start_date=None, end_date=None,
                     baidu_key=None, openweather_key=None, gee_key_path=None,
                     log_callback=None, output_base_dir=None,
                     options=None,
                     parallel=True, step_callback=None, label=None):
    """采集指定位置的所有城市环境数据。

    Args:
        options: 可选，细粒度控制 dict。为 None 时全部启用。
        parallel: 是否启用并行采集（默认 True）。
            - True: 空气质量/天气/街景/GEE/OSM 并行执行
            - False: 串行执行（与旧版行为一致，便于调试）
        label: 可选，时间切片标签（如 "2015年"），用于输出目录命名
    """
    log = make_logger(log_callback)

    if start_date is None or end_date is None:
        end = datetime.now()
        start = end - timedelta(days=365)
        start_date = start.strftime("%Y-%m-%d")
        end_date = end.strftime("%Y-%m-%d")
        log(f"未指定时间范围，使用默认: {start_date} 至 {end_date}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = output_base_dir if output_base_dir else "."
    if label:
        # 时间切片模式：目录名包含标签以便识别
        out_dir = os.path.join(base, f"output_{lon}_{lat}_{radius}m_{label}_{ts}")
    else:
        out_dir = os.path.join(base, f"output_{lon}_{lat}_{radius}m_{ts}")
    os.makedirs(out_dir, exist_ok=True)

    index = {
        "query_point": {"lon": lon, "lat": lat},
        "radius_m": radius,
        "time_range": {"start": start_date, "end": end_date},
        "timestamp": ts,
        "files": {},
    }

    # 构建采集器列表
    collectors = _build_collectors(
        lon, lat, radius, start_date, end_date,
        out_dir, log, options,
        baidu_key, openweather_key, gee_key_path, log_callback,
    )

    if not collectors:
        log("⚠️ 未启用任何数据采集模块")
        return out_dir

    # 执行采集
    total = len(collectors)
    if step_callback:
        step_callback("准备采集", 0, total)

    if parallel and total > 1:
        log(f"🚀 并行采集 {total} 个数据模块...")
        completed = 0
        with ThreadPoolExecutor(max_workers=min(total, 5)) as executor:
            future_map = {
                executor.submit(c.collect): c
                for c in collectors
            }
            for future in as_completed(future_map):
                collector = future_map[future]
                try:
                    files = future.result()
                    if files:
                        index["files"].update(files)
                except Exception as e:
                    log(f"⚠️ {collector.collector_name} 采集失败: {e}")
                completed += 1
                if step_callback:
                    step_callback(collector.collector_name, completed, total)
    else:
        log(f"🔗 串行采集 {total} 个数据模块...")
        for i, c in enumerate(collectors, 1):
            log(f"  ▶ {c.collector_name}")
            if step_callback:
                step_callback(c.collector_name, i - 1, total)
            try:
                files = c.collect()
                if files:
                    index["files"].update(files)
            except Exception as e:
                log(f"⚠️ {c.collector_name} 采集失败: {e}")
            if step_callback:
                step_callback(c.collector_name, i, total)

    # ---- 保存索引 ----
    index_path = os.path.join(out_dir, "index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    meta = {
        "timestamp": ts,
        "location": f"Lon:{lon}, Lat:{lat}",
        "readable_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    meta_path = os.path.join(out_dir, "meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # ---- 记录到本地缓存数据库 ----
    try:
        from local_cache import get_cache
        cache = get_cache()
        cache.record_collection(
            lon=lon, lat=lat, radius=radius,
            start_date=start_date, end_date=end_date,
            output_dir=out_dir,
            data_sources=options or {},
            file_count=len(index.get("files", {})),
            success=True,
        )
    except Exception:
        pass  # 缓存记录失败不影响主流程

    log(f"\n✅ 所有数据已保存至: {out_dir}")
    return out_dir


if __name__ == "__main__":
    test_lon = 116.3912
    test_lat = 39.9055
    test_radius = 500
    test_baidu_key = "YOUR_BAIDU_KEY_HERE"
    test_openweather_key = "YOUR_OPENWEATHER_KEY_HERE"
    test_gee_key_path = None

    process_location(test_lon, test_lat, test_radius,
                     baidu_key=test_baidu_key,
                     openweather_key=test_openweather_key,
                     gee_key_path=test_gee_key_path)
