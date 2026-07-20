#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""城市街道环境大数据采集 —— 核心采集管线。"""
import os
import json
from datetime import datetime, timedelta

import ee

from utils import make_logger
from plugins import (
    get_air_quality_by_lonlat,
    get_weather_by_lonlat,
    get_streetview_metadata,
    download_streetview_image,
    initialize_gee,
    get_gee_stats,
    get_era5_climate_stats,
    get_era5_hourly_stats,
    get_elevation_stats,
    get_precipitation_stats,
    get_ndwi_evi_stats,
    get_population_stats,
    get_osm_vector_data,
    compute_osm_stats,
)


def process_location(lon, lat, radius=500, start_date=None, end_date=None,
                     baidu_key=None, openweather_key=None, gee_key_path=None,
                     enable_air_quality=True, enable_streetview=True,
                     enable_gee=True, enable_osm=True,
                     log_callback=None, output_base_dir=None,
                     proxy_config=None):
    """采集指定位置的所有城市环境数据。

    Args:
        proxy_config: 可选，分服务代理配置 dict：
            {"url": "http://127.0.0.1:7890",
             "air": True,     # OpenWeatherMap 走代理
             "street": False,  # 百度直连（走代理会被拒）
             "gee": True,      # GEE 走代理
             "osm": True}      # OSM 走代理
    """
    log = make_logger(log_callback)

    # 解析代理配置
    pc = proxy_config or {}
    proxy_url = pc.get("url", "").strip()
    _proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

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

    # ---- 空气质量 ----
    if enable_air_quality:
        log("获取空气质量...")
        if openweather_key:
            air_proxy = _proxies if pc.get("air", True) else None
            air_data = get_air_quality_by_lonlat(
                lon, lat, openweather_key,
                log_callback=log_callback, proxies=air_proxy,
            )
            if air_data:
                air_path = os.path.join(out_dir, "air_quality.json")
                with open(air_path, "w", encoding="utf-8") as f:
                    json.dump(air_data, f, ensure_ascii=False, indent=2)
                index["files"]["air_quality"] = air_path
                log(f"  AQI 等级: {air_data['now']['aqi']}")
            else:
                log("空气质量获取失败")
        else:
            log("⚠️ 未提供 OpenWeatherMap Key")
    else:
        log("⏭️ 空气质量模块已禁用")

    # ---- 实时天气（气温、湿度） ----
    if enable_air_quality:  # 复用空气质量开关（同一 API Key）
        log("获取实时天气...")
        if openweather_key:
            air_proxy = _proxies if pc.get("air", True) else None
            weather_data = get_weather_by_lonlat(
                lon, lat, openweather_key,
                log_callback=log_callback, proxies=air_proxy,
            )
            if weather_data:
                weather_path = os.path.join(out_dir, "weather.json")
                with open(weather_path, "w", encoding="utf-8") as f:
                    json.dump(weather_data, f, ensure_ascii=False, indent=2)
                index["files"]["weather"] = weather_path
                w = weather_data["now"]
                log(f"  气温: {w['temp_c']}℃, 湿度: {w['humidity']}%, 天气: {w['weather']}")
            else:
                log("天气数据获取失败")
        else:
            log("⚠️ 未提供 OpenWeatherMap Key，跳过天气")
    else:
        log("⏭️ 天气模块已禁用")

    # ---- 街景 ----
    if enable_streetview:
        log("获取街景（百度）...")
        if baidu_key:
            # 百度地图默认**不走**代理 —— 走代理会被百度当作海外 IP 拒绝
            sv_proxy = _proxies if pc.get("street", False) else None
            has_view = get_streetview_metadata(
                lon, lat, baidu_key, log_callback=log_callback, proxies=sv_proxy,
            )
            if has_view:
                img_dir = os.path.join(out_dir, "streetview_images")
                os.makedirs(img_dir, exist_ok=True)
                for angle in [0, 90, 180, 270]:
                    img_path = os.path.join(img_dir, f"heading_{angle}.jpg")
                    success = download_streetview_image(
                        lon, lat, angle, 0, baidu_key, img_path,
                        log_callback=log_callback, proxies=sv_proxy,
                    )
                    if success:
                        index["files"].setdefault("streetview_images", []).append(img_path)

                meta_path = os.path.join(out_dir, "streetview_status.txt")
                with open(meta_path, "w", encoding="utf-8") as f:
                    f.write("Baidu Street View Available")
                index["files"]["streetview_metadata"] = meta_path
            else:
                log("⚠️ 该地点无百度街景覆盖或请求失败")
        else:
            log("⚠️ 未提供百度地图 AK (Key)")
    else:
        log("⏭️ 街景模块已禁用")

    # ---- GEE 遥感 ----
    if enable_gee:
        log("初始化 GEE...")
        gee_proxy = proxy_url if pc.get("gee", True) else None
        initialize_gee(key_path=gee_key_path, log_callback=log_callback,
                       proxy_url=gee_proxy)
        try:
            roi_geometry = ee.Geometry.Point(lon, lat).buffer(radius).bounds()
            log("计算遥感指标...")
            get_gee_stats(roi_geometry, start_date, end_date, out_dir,
                          log_callback=log_callback)
            index["files"]["viirs_stats"] = os.path.join(out_dir, "viirs_stats.csv")
            index["files"]["ndvi_stats"] = os.path.join(out_dir, "ndvi_stats.csv")
            index["files"]["lst_stats"] = os.path.join(out_dir, "lst_stats.csv")

            # 新增: 海拔
            get_elevation_stats(roi_geometry, out_dir, log_callback=log_callback)
            index["files"]["elevation_stats"] = os.path.join(out_dir, "elevation_stats.csv")

            # 新增: 降水
            get_precipitation_stats(roi_geometry, start_date, end_date, out_dir,
                                    log_callback=log_callback)
            index["files"]["precipitation_stats"] = os.path.join(out_dir, "precipitation_stats.csv")

            # 新增: NDWI + EVI
            get_ndwi_evi_stats(roi_geometry, start_date, end_date, out_dir,
                               log_callback=log_callback)
            index["files"]["ndwi_stats"] = os.path.join(out_dir, "ndwi_stats.csv")
            index["files"]["evi_stats"] = os.path.join(out_dir, "evi_stats.csv")

            # 新增: 人口密度
            get_population_stats(roi_geometry, out_dir, log_callback=log_callback)
            index["files"]["population_stats"] = os.path.join(out_dir, "population_stats.csv")

            log("计算 ERA5 气候逐日数据...")
            get_era5_climate_stats(roi_geometry, start_date, end_date, out_dir,
                                   log_callback=log_callback)
            index["files"]["era5_climate_stats"] = os.path.join(out_dir, "era5_climate_stats.csv")

            # 最近一天逐时数据（ERA5-Land 有约 5 天入库延迟，取 7 天前）
            latest_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            log(f"计算 ERA5 逐时数据（{latest_date}）...")
            get_era5_hourly_stats(roi_geometry, latest_date, out_dir,
                                  log_callback=log_callback)
            index["files"]["era5_hourly"] = os.path.join(out_dir, "era5_hourly.csv")
        except Exception as e:
            log(f"⚠️ GEE 数据处理失败: {e}")
    else:
        log("⏭️ 遥感数据模块已禁用")

    # ---- OSM 矢量 ----
    if enable_osm:
        log("下载 OSM 矢量数据...")
        osm_proxy = _proxies if pc.get("osm", True) else None
        get_osm_vector_data(lon, lat, radius, out_dir,
                            log_callback=log_callback, proxies=osm_proxy)
        index["files"]["osm_roads"] = os.path.join(out_dir, "roads.geojson")
        index["files"]["osm_buildings"] = os.path.join(out_dir, "buildings.geojson")
        index["files"]["osm_green_spaces"] = os.path.join(out_dir, "green_spaces.geojson")
        index["files"]["osm_water_bodies"] = os.path.join(out_dir, "water_bodies.geojson")

        # 新增: 计算 OSM 统计指标（建筑/路网/绿地）
        log("计算 OSM 统计指标...")
        compute_osm_stats(out_dir, radius, log_callback=log_callback)
        index["files"]["osm_stats"] = os.path.join(out_dir, "osm_stats.json")
    else:
        log("⏭️ OSM 矢量数据模块已禁用")

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
