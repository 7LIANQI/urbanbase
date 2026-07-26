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
    ]
    return any(_opt(options, k) for k in gee_keys)


def _any_osm(options):
    """判断是否启用了任意 OSM 子模块。"""
    osm_keys = [
        "osm_roads", "osm_buildings", "osm_green_spaces",
        "osm_water_bodies", "osm_stats",
    ]
    return any(_opt(options, k) for k in osm_keys)


def _resolve_proxies(proxy_config):
    """解析代理配置，返回各服务的代理字典。

    Returns:
        dict: {
            "air_proxy": dict or None,
            "street_proxy": dict or None,
            "gee_proxy": str or None,
            "osm_proxy": dict or None,
        }
    """
    if not proxy_config:
        return {
            "air_proxy": None,
            "street_proxy": None,
            "gee_proxy": None,
            "osm_proxy": None,
        }
    pc = proxy_config
    proxy_url = pc.get("url", "").strip()
    _proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    return {
        "air_proxy": _proxies if pc.get("air", True) else None,
        "street_proxy": _proxies if pc.get("street", False) else None,
        "gee_proxy": proxy_url if pc.get("gee", True) else None,
        "osm_proxy": _proxies if pc.get("osm", True) else None,
    }


def _build_collectors(lon, lat, radius, start_date, end_date,
                      output_dir, log, options, proxy_map, baidu_key,
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
            air_proxy=proxy_map["air_proxy"],
        ))

    if _opt(options, "weather"):
        collectors.append(WeatherCollector(
            **common,
            openweather_key=openweather_key,
            air_proxy=proxy_map["air_proxy"],
        ))

    if _opt(options, "streetview"):
        collectors.append(StreetViewCollector(
            **common,
            baidu_key=baidu_key,
            street_proxy=proxy_map["street_proxy"],
        ))

    if _any_gee(options):
        collectors.append(GEECollector(
            **common,
            gee_key_path=gee_key_path,
            gee_proxy=proxy_map["gee_proxy"],
        ))

    if _any_osm(options):
        collectors.append(OSMCollector(
            **common,
            osm_proxy=proxy_map["osm_proxy"],
        ))

    return collectors


def process_location(lon, lat, radius=500, start_date=None, end_date=None,
                     baidu_key=None, openweather_key=None, gee_key_path=None,
                     log_callback=None, output_base_dir=None,
                     proxy_config=None, options=None,
                     parallel=True, step_callback=None):
    """采集指定位置的所有城市环境数据。

    Args:
        options: 可选，细粒度控制 dict。为 None 时全部启用。
        proxy_config: 可选，分服务代理配置 dict。
        parallel: 是否启用并行采集（默认 True）。
            - True: 空气质量/天气/街景/GEE/OSM 并行执行
            - False: 串行执行（与旧版行为一致，便于调试）
    """
    log = make_logger(log_callback)

    # 解析代理配置
    proxy_map = _resolve_proxies(proxy_config)

    if start_date is None or end_date is None:
        end = datetime.now()
        start = end - timedelta(days=365)
        start_date = start.strftime("%Y-%m-%d")
        end_date = end.strftime("%Y-%m-%d")
        log(f"未指定时间范围，使用默认: {start_date} 至 {end_date}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = output_base_dir if output_base_dir else "."
    out_dir = os.path.join(base, f"output_{lon}_{lat}_{radius}m_{timestamp}")
    os.makedirs(out_dir, exist_ok=True)

    index = {
        "query_point": {"lon": lon, "lat": lat},
        "radius_m": radius,
        "time_range": {"start": start_date, "end": end_date},
        "timestamp": timestamp,
        "files": {},
    }

    # 构建采集器列表
    collectors = _build_collectors(
        lon, lat, radius, start_date, end_date,
        out_dir, log, options, proxy_map,
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
        "timestamp": timestamp,
        "location": f"Lon:{lon}, Lat:{lat}",
        "readable_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    meta_path = os.path.join(out_dir, "meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

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
