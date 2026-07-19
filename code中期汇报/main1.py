#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import json
from datetime import datetime, timedelta
import ee
# 导入插件
from plugins.air_quality_plugin import get_air_quality_by_lonlat
from plugins.streetview_plugin import get_streetview_metadata, download_streetview_image
from plugins.gee_plugin import initialize_gee, get_gee_stats
from plugins.osm_plugin import get_osm_vector_data

def process_location(lon, lat, radius=500, start_date=None, end_date=None,
                     baidu_key=None, openweather_key=None, gee_key_path=None,
                     enable_air_quality=True, enable_streetview=True,
                     enable_gee=True, enable_osm=True,
                     log_callback=None):
    """主函数：采集所有数据"""
    def log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)
    if start_date is None or end_date is None:
        end = datetime.now()
        start = end - timedelta(days=365)
        start_date = start.strftime("%Y-%m-%d")
        end_date = end.strftime("%Y-%m-%d")
        log(f"未指定时间范围，使用默认: {start_date} 至 {end_date}")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = f"./output_{lon}_{lat}_{radius}m_{timestamp}"
    os.makedirs(out_dir, exist_ok=True)
    index = {
        "query_point": {"lon": lon, "lat": lat},
        "radius_m": radius,
        "time_range": {"start": start_date, "end": end_date},
        "timestamp": timestamp,
        "files": {}
    }
    # 空气质量
    if enable_air_quality:
        log("获取空气质量...")
        if openweather_key:
            air_data = get_air_quality_by_lonlat(lon, lat, openweather_key, log_callback=log)
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
    # 街景
    if enable_streetview:
        log("获取街景（百度）...")
    # 注意：此处变量已改为 baidukey，请确保传入的是百度地图 AK
        if baidu_key: 
        # 1. 探测是否有街景（百度无标准 metadata，采用轻量探测）
            has_view = get_streetview_metadata(lon, lat, baidu_key, log_callback=log)
        
            if has_view:
            # 2. 创建图片存储目录
                img_dir = os.path.join(out_dir, "streetview_images")
                os.makedirs(img_dir, exist_ok=True)
            
            # 3. 循环下载四个方向的图片
                for angle in [0, 90, 180, 270]:
                    img_path = os.path.join(img_dir, f"heading_{angle}.jpg")
                
                # 调用百度下载函数
                    success = download_streetview_image(
                        lon, lat, angle, 0, baidu_key, img_path, log_callback=log
                    )
                
                    if success:
                        index["files"].setdefault("streetview_images", []).append(img_path)
            
            # 4. 生成简单的状态文件（替代原腾讯的 metadata.json）
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
    if enable_gee:
        log("初始化 GEE...")
        initialize_gee(key_path=gee_key_path, log_callback=log)
        try:
            roi_geometry = ee.Geometry.Point(lon, lat).buffer(radius).bounds()
            log("计算遥感指标...")
            get_gee_stats(roi_geometry, start_date, end_date, out_dir, log_callback=log)
            index["files"]["viirs_stats"] = os.path.join(out_dir, "viirs_stats.csv")
            index["files"]["ndvi_stats"] = os.path.join(out_dir, "ndvi_stats.csv")
            index["files"]["lst_stats"] = os.path.join(out_dir, "lst_stats.csv")
        except Exception as e:
            log(f"⚠️ GEE 数据处理失败: {e}")
    else:
        log("⏭️ 遥感数据模块已禁用")
    # OSM 矢量
    if enable_osm:
        log("下载 OSM 矢量数据...")
        get_osm_vector_data(lon, lat, radius, out_dir, log_callback=log)
        index["files"]["osm_roads"] = os.path.join(out_dir, "roads.geojson")
        index["files"]["osm_buildings"] = os.path.join(out_dir, "buildings.geojson")
        index["files"]["osm_green_spaces"] = os.path.join(out_dir, "green_spaces.geojson")
        index["files"]["osm_water_bodies"] = os.path.join(out_dir, "water_bodies.geojson")
    else:
        log("⏭️ OSM 矢量数据模块已禁用")
    # 保存索引文件
    index_path = os.path.join(out_dir, "index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    # 生成历史记录元数据 meta.json
    meta = {
        "timestamp": timestamp,
        "location": f"Lon:{lon}, Lat:{lat}",
        "readable_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
    test_tencent_key = "YOUR_TENCENT_KEY_HERE"
    test_openweather_key = "YOUR_OPENWEATHER_KEY_HERE"
    test_gee_key_path = None
    process_location(test_lon, test_lat, test_radius,
                     tencent_key=test_tencent_key,
                     openweather_key=test_openweather_key,
                     gee_key_path=test_gee_key_path)