# -*- coding: utf-8 -*-
"""Google Earth Engine 遥感数据插件：夜光、NDVI、地表温度。

GEE 使用 google-auth / google-api-core 发起请求，不直接通过 requests。
要让 GEE 走代理，你需要在系统层级配置代理（环境变量或 VPN 全局模式）：
  - HTTP_PROXY / HTTPS_PROXY 环境变量
  - 或在 Clash/V2Ray 中设置 TUN 模式让 googleapis.com 走代理

本模块在初始化 GEE 前会尝试应用环境变量中的代理设置。
"""
import os
import json

import ee
import pandas as pd
from google.oauth2 import service_account

from utils import make_logger
from config import LST_SCALE, LST_OFFSET, LST_KELVIN


def initialize_gee(key_path=None, log_callback=None, proxy_url=None):
    """初始化 Google Earth Engine。

    Args:
        proxy_url: 可选，代理 URL（如 http://127.0.0.1:7890）。
                   会设置 HTTP_PROXY/HTTPS_PROXY 环境变量。
    """
    log = make_logger(log_callback)

    # 如果指定了代理，设置环境变量（GEE 底层库会读取）
    if proxy_url:
        os.environ.setdefault("HTTP_PROXY", proxy_url)
        os.environ.setdefault("HTTPS_PROXY", proxy_url)
        log(f"🔗 GEE 使用代理: {proxy_url}")

    try:
        if key_path and os.path.exists(key_path):
            with open(key_path, 'r', encoding='utf-8') as f:
                key_data = json.load(f)

            project_id = key_data.get('project_id')
            if not project_id:
                log("❌ JSON 文件中未找到 project_id")
                return False

            credentials = service_account.Credentials.from_service_account_file(
                key_path,
                scopes=['https://www.googleapis.com/auth/earthengine'],
            )
            ee.Initialize(credentials, project=project_id)
            log(f"✅ GEE 初始化成功 (Project: {project_id})")
            return True
        else:
            ee.Initialize()
            log("✅ GEE 使用默认凭证初始化成功")
            return True
    except Exception as e:
        log(f"❌ GEE 初始化失败: {e}")
        return False


def get_gee_stats(roi_geometry, start_date, end_date, output_dir, log_callback=None):
    """获取 VIIRS 夜光 / Sentinel-2 NDVI / Landsat 8 地表温度统计。"""
    log = make_logger(log_callback)

    reducer_base = (
        ee.Reducer.mean()
        .combine(ee.Reducer.sampleStdDev(), sharedInputs=True)
        .combine(ee.Reducer.minMax(), sharedInputs=True)
        .combine(ee.Reducer.median(), sharedInputs=True)
    )

    # ---- VIIRS 夜光 ----
    log("  获取 VIIRS 夜光数据...")
    viirs_col = (
        ee.ImageCollection("NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG")
        .filterDate(start_date, end_date)
        .select('avg_rad')
    )

    def calc_viirs(img):
        stats = img.reduceRegion(
            reducer=reducer_base, geometry=roi_geometry, scale=500, maxPixels=1e9,
        )
        return ee.Feature(None, stats).set({'Date': img.date().format('YYYY-MM-dd')})

    try:
        viirs_feats = viirs_col.map(calc_viirs).getInfo()
        viirs_data = [f['properties'] for f in viirs_feats['features']]
        if viirs_data:
            viirs_df = pd.DataFrame(viirs_data)
            col_mapping = {
                'avg_rad_mean': '夜光均值',
                'avg_rad_stdDev': '夜光标准差',
                'avg_rad_min': '夜光最小值',
                'avg_rad_max': '夜光最大值',
                'avg_rad_median': '夜光中位数',
            }
            exist_cols = [c for c in ['Date'] + list(col_mapping) if c in viirs_df.columns]
            if exist_cols:
                viirs_df = viirs_df[exist_cols].rename(
                    columns={k: v for k, v in col_mapping.items() if k in viirs_df.columns}
                )
                viirs_df.to_csv(os.path.join(output_dir, "viirs_stats.csv"), index=False)
                log("  VIIRS 数据已保存")
            else:
                log("  VIIRS 无有效列，跳过")
        else:
            log("  VIIRS 无数据，跳过")
    except Exception as e:
        log(f"  VIIRS 处理出错: {e}")

    # ---- NDVI ----
    log("  获取 Sentinel-2 NDVI 数据...")
    s2 = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(roi_geometry)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20))
    )

    def add_ndvi(img):
        ndvi = img.normalizedDifference(['B8', 'B4']).rename('NDVI')
        return img.addBands(ndvi)

    s2_ndvi = s2.map(add_ndvi).select('NDVI')

    def calc_ndvi(img):
        mean = img.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=roi_geometry, scale=10, maxPixels=1e9,
        )
        return ee.Feature(None, mean).set({'Date': img.date().format('YYYY-MM-dd')})

    try:
        ndvi_feats = s2_ndvi.map(calc_ndvi).getInfo()
        ndvi_data = [
            f['properties'] for f in ndvi_feats['features']
            if f['properties'].get('NDVI') is not None
        ]
        if ndvi_data:
            ndvi_df = pd.DataFrame(ndvi_data)
            if 'Date' in ndvi_df.columns and 'NDVI' in ndvi_df.columns:
                ndvi_df = ndvi_df[['Date', 'NDVI']]
                ndvi_df.columns = ['Date', '区域NDVI均值']
                ndvi_df.to_csv(os.path.join(output_dir, "ndvi_stats.csv"), index=False)
                log("  NDVI 数据已保存")
            else:
                log("  NDVI 缺少必要列，跳过")
        else:
            log("  NDVI 无数据，跳过")
    except Exception as e:
        log(f"  NDVI 处理出错: {e}")

    # ---- 地表温度 ----
    log("  获取 Landsat 8 地表温度数据...")
    l8 = (
        ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
        .filterBounds(roi_geometry)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lt('CLOUD_COVER', 20))
    )

    def proc_lst(img):
        lst = (
            img.select('ST_B10')
            .multiply(LST_SCALE)
            .add(LST_OFFSET)
            .subtract(LST_KELVIN)
            .rename('LST_Celsius')
        )
        return img.addBands(lst)

    l8_lst = l8.map(proc_lst).select('LST_Celsius')

    lst_reducer = (
        ee.Reducer.mean()
        .combine(ee.Reducer.minMax(), sharedInputs=True)
        .combine(ee.Reducer.median(), sharedInputs=True)
    )

    def calc_lst(img):
        stats = img.reduceRegion(
            reducer=lst_reducer, geometry=roi_geometry, scale=30, maxPixels=1e9,
        )
        return ee.Feature(None, stats).set({'Date': img.date().format('YYYY-MM-dd')})

    try:
        lst_feats = l8_lst.map(calc_lst).getInfo()
        lst_data = [
            f['properties'] for f in lst_feats['features']
            if f['properties'].get('LST_Celsius_mean') is not None
        ]
        if lst_data:
            lst_df = pd.DataFrame(lst_data)
            expected = [
                'Date', 'LST_Celsius_mean', 'LST_Celsius_min',
                'LST_Celsius_max', 'LST_Celsius_median',
            ]
            exist = [c for c in expected if c in lst_df.columns]
            if exist:
                lst_df = lst_df[exist]
                rename = {
                    'LST_Celsius_mean': '地表温度均值(C)',
                    'LST_Celsius_min': '最低温',
                    'LST_Celsius_max': '最高温',
                    'LST_Celsius_median': '温度中位数',
                }
                lst_df = lst_df.rename(columns={k: v for k, v in rename.items() if k in lst_df.columns})
                lst_df.to_csv(os.path.join(output_dir, "lst_stats.csv"), index=False)
                log("  地表温度数据已保存")
            else:
                log("  地表温度缺少必要列，跳过")
        else:
            log("  地表温度无数据，跳过")
    except Exception as e:
        log(f"  地表温度处理出错: {e}")


def get_era5_climate_stats(roi_geometry, start_date, end_date, output_dir,
                           log_callback=None):
    """获取 ERA5-Land 气候逐日数据（日聚合方式，避免逐时 getInfo 超时）。

    数据集: ECMWF/ERA5_LAND/HOURLY
    先在服务端按天聚合 → reduceRegion，大幅减少传回客户端的数据量。
    """
    log = make_logger(log_callback)

    start = ee.Date(start_date)
    end = ee.Date(end_date)
    n_days = end.difference(start, 'day').round().getInfo()
    n_days = max(1, min(n_days, 366))  # 最多一年

    log(f"  拉取 ERA5 数据（{n_days} 天）...")

    era5 = (
        ee.ImageCollection("ECMWF/ERA5_LAND/HOURLY")
        .filterBounds(roi_geometry)
        .filterDate(start, end)
        .select([
            'temperature_2m',
            'surface_solar_radiation_downwards',
            'dewpoint_temperature_2m',
        ])
    )

    def process_hourly(img):
        temp_c = img.select('temperature_2m').subtract(273.15)
        dew_c = img.select('dewpoint_temperature_2m').subtract(273.15)
        solar_w = img.select('surface_solar_radiation_downwards').divide(3600)
        sunshine = solar_w.gt(120).rename('sunshine')
        a = temp_c.multiply(17.625).divide(temp_c.add(243.04)).exp()
        b = dew_c.multiply(17.625).divide(dew_c.add(243.04)).exp()
        rh = b.divide(a).multiply(100).rename('humidity')
        return img.addBands([
            temp_c.rename('temp_c'), solar_w.rename('solar_w'), sunshine, rh,
        ])

    processed = era5.map(process_hourly).select(
        ['temp_c', 'solar_w', 'sunshine', 'humidity'])

    # 服务端按天聚合
    def make_daily(day_offset):
        day_start = start.advance(day_offset, 'day')
        day_end = day_start.advance(1, 'day')
        day_imgs = processed.filterDate(day_start, day_end)

        daily = (
            day_imgs.select('temp_c').mean().rename('temp_mean')
            .addBands(day_imgs.select('temp_c').reduce(ee.Reducer.max()).rename('temp_max'))
            .addBands(day_imgs.select('temp_c').reduce(ee.Reducer.min()).rename('temp_min'))
            .addBands(day_imgs.select('humidity').mean().rename('humidity_mean'))
            .addBands(day_imgs.select('solar_w').mean().rename('solar_mean'))
            .addBands(day_imgs.select('solar_w').reduce(ee.Reducer.max()).rename('solar_max'))
            .addBands(day_imgs.select('sunshine').reduce(ee.Reducer.sum()).rename('sun_hours'))
        )
        stats = daily.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=roi_geometry,
            scale=11132, maxPixels=1e9,
        )
        return ee.Feature(None, stats).set(
            'Date', day_start.format('YYYY-MM-dd'),
        )

    try:
        daily_feats = ee.FeatureCollection(
            ee.List.sequence(0, n_days - 1).map(make_daily)
        )
        result = daily_feats.getInfo()

        records = [
            f['properties'] for f in result.get('features', [])
            if f.get('properties', {}).get('temp_mean') is not None
        ]

        if not records:
            log("  ERA5-Land 无有效数据（该区域/时间段可能无覆盖）")
            return

        df = pd.DataFrame(records)
        # 使用显式映射，避免 getInfo 返回键顺序不一致导致列名错位
        column_map = {
            'temp_mean': '日均气温_C',
            'temp_max': '日最高气温_C',
            'temp_min': '日最低气温_C',
            'humidity_mean': '日均相对湿度_pct',
            'solar_mean': '太阳辐射日均_Wm2',
            'solar_max': '太阳辐射峰值_Wm2',
            'sun_hours': '日照时数_h',
        }
        df = df.rename(columns=column_map)
        # 确保 Date 在第一列
        cols = ['Date', '日均气温_C', '日最高气温_C', '日最低气温_C',
                '日均相对湿度_pct', '太阳辐射日均_Wm2', '太阳辐射峰值_Wm2', '日照时数_h']
        df = df[[c for c in cols if c in df.columns]]

        for c in df.columns:
            if c != 'Date':
                df[c] = df[c].round(1)

        df.to_csv(os.path.join(output_dir, "era5_climate_stats.csv"), index=False)
        log(f"  ERA5 气候逐日数据已保存（{len(df)} 天）")
    except Exception as e:
        log(f"  ERA5 气候数据处理出错: {e}")


def get_era5_hourly_stats(roi_geometry, target_date, output_dir,
                          log_callback=None):
    """获取 ERA5-Land 单日逐时数据（气温/辐射/湿度/日照）。

    仅取 24 小时，数据量小，可用于逐时折线图展示。
    """
    log = make_logger(log_callback)

    date_obj = ee.Date(target_date)
    next_day = date_obj.advance(1, 'day')

    log(f"  拉取 {target_date} 逐时 ERA5 数据...")

    era5 = (
        ee.ImageCollection("ECMWF/ERA5_LAND/HOURLY")
        .filterBounds(roi_geometry)
        .filterDate(date_obj, next_day)
        .select([
            'temperature_2m',
            'surface_solar_radiation_downwards',
            'dewpoint_temperature_2m',
        ])
    )

    def process_hourly(img):
        temp_c = img.select('temperature_2m').subtract(273.15)
        dew_c = img.select('dewpoint_temperature_2m').subtract(273.15)
        solar_w = img.select('surface_solar_radiation_downwards').divide(3600)
        a = temp_c.multiply(17.625).divide(temp_c.add(243.04)).exp()
        b = dew_c.multiply(17.625).divide(dew_c.add(243.04)).exp()
        rh = b.divide(a).multiply(100).rename('humidity')

        stats = img.addBands([
            temp_c.rename('temp_c'), solar_w.rename('solar_w'), rh,
        ]).reduceRegion(
            reducer=ee.Reducer.mean(), geometry=roi_geometry,
            scale=11132, maxPixels=1e9,
        )
        return ee.Feature(None, stats).set({
            'Hour': img.date().getRelative('hour', 'day'),
            'Datetime': img.date().format('YYYY-MM-dd HH:mm'),
        })

    try:
        feats = ee.FeatureCollection(era5.map(process_hourly)).getInfo()
        records = [
            f['properties'] for f in feats.get('features', [])
            if f.get('properties', {}).get('temp_c') is not None
        ]

        if not records:
            log("  逐时数据为空")
            return

        df = pd.DataFrame(records)
        df = df.rename(columns={
            'temp_c': '气温_C',
            'solar_w': '太阳辐射_Wm2',
            'humidity': '相对湿度_pct',
        })
        keep = ['Hour', 'Datetime', '气温_C', '太阳辐射_Wm2', '相对湿度_pct']
        df = df[[c for c in keep if c in df.columns]]
        for c in df.columns:
            if c not in ('Hour', 'Datetime'):
                df[c] = df[c].round(1)

        df.to_csv(os.path.join(output_dir, "era5_hourly.csv"), index=False)
        log(f"  逐时数据已保存（{len(df)} 条）")
    except Exception as e:
        log(f"  逐时数据处理出错: {e}")


# ===================== 新增 GEE 数据采集函数 =====================

def get_elevation_stats(roi_geometry, output_dir, log_callback=None):
    """获取 SRTM 海拔数据（均值/最小/最大/中位数/标准差）。

    数据集: USGS/SRTMGL1_003 (30m 分辨率)
    输出: elevation_stats.csv
    """
    log = make_logger(log_callback)
    log("  获取 SRTM 海拔数据...")

    try:
        dem = ee.Image("USGS/SRTMGL1_003")
        elev_reducer = (
            ee.Reducer.mean()
            .combine(ee.Reducer.minMax(), sharedInputs=True)
            .combine(ee.Reducer.median(), sharedInputs=True)
            .combine(ee.Reducer.sampleStdDev(), sharedInputs=True)
        )
        stats = dem.reduceRegion(
            reducer=elev_reducer,
            geometry=roi_geometry,
            scale=30,
            maxPixels=1e9,
        ).getInfo()

        if stats and stats.get('elevation_mean') is not None:
            record = {
                '海拔均值_m': round(stats.get('elevation_mean', 0), 1),
                '海拔最小值_m': round(stats.get('elevation_min', 0), 1),
                '海拔最大值_m': round(stats.get('elevation_max', 0), 1),
                '海拔中位数_m': round(stats.get('elevation_median', 0), 1),
                '海拔标准差_m': round(stats.get('elevation_stdDev', 0), 1),
            }
            df = pd.DataFrame([record])
            df.to_csv(os.path.join(output_dir, "elevation_stats.csv"), index=False)
            log(f"  海拔数据已保存（均值: {record['海拔均值_m']}m）")
        else:
            log("  海拔数据为空，跳过")
    except Exception as e:
        log(f"  海拔数据处理出错: {e}")


def get_precipitation_stats(roi_geometry, start_date, end_date, output_dir,
                            log_callback=None):
    """获取 CHIRPS 逐日降水数据时间序列。

    数据集: UCSB-CHG/CHIRPS/DAILY (约 5.5km 分辨率)
    输出: precipitation_stats.csv（每日降水量 mm）
    """
    log = make_logger(log_callback)
    log("  获取 CHIRPS 降水数据...")

    try:
        chirps = (
            ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY")
            .filterBounds(roi_geometry)
            .filterDate(start_date, end_date)
            .select('precipitation')
        )

        def calc_precip(img):
            stats = img.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=roi_geometry,
                scale=5566,
                maxPixels=1e9,
            )
            return ee.Feature(None, stats).set({
                'Date': img.date().format('YYYY-MM-dd'),
            })

        feats = chirps.map(calc_precip).getInfo()
        records = [
            f['properties'] for f in feats.get('features', [])
            if f.get('properties', {}).get('precipitation') is not None
        ]

        if records:
            df = pd.DataFrame(records)
            df = df[['Date', 'precipitation']]
            df.columns = ['Date', '降水量_mm']
            df['降水量_mm'] = df['降水量_mm'].round(2)
            df.to_csv(os.path.join(output_dir, "precipitation_stats.csv"), index=False)
            log(f"  降水数据已保存（{len(df)} 天）")
        else:
            log("  降水数据为空，跳过")
    except Exception as e:
        log(f"  降水数据处理出错: {e}")


def get_ndwi_evi_stats(roi_geometry, start_date, end_date, output_dir,
                       log_callback=None):
    """从 Sentinel-2 计算 NDWI 和 EVI 时间序列。

    NDWI (McFeeters): (Green - NIR) / (Green + NIR) = (B3 - B8) / (B3 + B8)
    EVI: 2.5 * ((B8 - B4) / (B8 + 6*B4 - 7.5*B2 + 1))

    输出: ndwi_stats.csv, evi_stats.csv
    """
    log = make_logger(log_callback)

    s2 = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(roi_geometry)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20))
    )

    def add_indices(img):
        # NDWI: (Green - NIR) / (Green + NIR)
        ndwi = img.normalizedDifference(['B3', 'B8']).rename('NDWI')
        # EVI: 2.5 * ((NIR - Red) / (NIR + 6*Red - 7.5*Blue + 1))
        evi = img.expression(
            '2.5 * ((B8 - B4) / (B8 + 6 * B4 - 7.5 * B2 + 1))',
            {
                'B8': img.select('B8').toFloat(),
                'B4': img.select('B4').toFloat(),
                'B2': img.select('B2').toFloat(),
            },
        ).rename('EVI')
        return img.addBands([ndwi, evi])

    s2_indices = s2.map(add_indices).select(['NDWI', 'EVI'])

    def calc_indices(img):
        stats = img.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=roi_geometry,
            scale=10,
            maxPixels=1e9,
        )
        return ee.Feature(None, stats).set({
            'Date': img.date().format('YYYY-MM-dd'),
        })

    # ---- NDWI ----
    try:
        log("  计算 Sentinel-2 NDWI...")
        ndwi_feats = s2_indices.select('NDWI').map(calc_indices).getInfo()
        ndwi_records = [
            f['properties'] for f in ndwi_feats.get('features', [])
            if f.get('properties', {}).get('NDWI') is not None
        ]
        if ndwi_records:
            ndwi_df = pd.DataFrame(ndwi_records)
            ndwi_df = ndwi_df[['Date', 'NDWI']]
            ndwi_df.columns = ['Date', '区域NDWI均值']
            ndwi_df['区域NDWI均值'] = ndwi_df['区域NDWI均值'].round(4)
            ndwi_df.to_csv(os.path.join(output_dir, "ndwi_stats.csv"), index=False)
            log(f"  NDWI 数据已保存（{len(ndwi_df)} 景）")
        else:
            log("  NDWI 无有效数据，跳过")
    except Exception as e:
        log(f"  NDWI 处理出错: {e}")

    # ---- EVI ----
    try:
        log("  计算 Sentinel-2 EVI...")
        evi_feats = s2_indices.select('EVI').map(calc_indices).getInfo()
        evi_records = [
            f['properties'] for f in evi_feats.get('features', [])
            if f.get('properties', {}).get('EVI') is not None
        ]
        if evi_records:
            evi_df = pd.DataFrame(evi_records)
            evi_df = evi_df[['Date', 'EVI']]
            evi_df.columns = ['Date', '区域EVI均值']
            evi_df['区域EVI均值'] = evi_df['区域EVI均值'].round(4)
            evi_df.to_csv(os.path.join(output_dir, "evi_stats.csv"), index=False)
            log(f"  EVI 数据已保存（{len(evi_df)} 景）")
        else:
            log("  EVI 无有效数据，跳过")
    except Exception as e:
        log(f"  EVI 处理出错: {e}")


def get_population_stats(roi_geometry, output_dir, log_callback=None):
    """获取人口密度数据（WorldPop 为主，GPW 为备）。

    数据集优先级:
        1. WorldPop/GP/100m/pop — 100m 分辨率，2020 年
        2. CIECIN/GPWv411/GPW_Population_Count — ~1km 分辨率，2020 年（备用）

    输出: population_stats.csv
    """
    log = make_logger(log_callback)
    log("  获取人口密度数据...")

    # 计算 ROI 面积
    try:
        area_sq_m = roi_geometry.area(1).getInfo()
        area_sq_km = area_sq_m / 1e6 if area_sq_m else 1.0
    except Exception:
        area_sq_km = 1.0
        log("    ⚠️ 无法计算 ROI 面积，使用估算值")

    # ---- 方案1: WorldPop (100m) ----
    result = _try_worldpop(roi_geometry, area_sq_km, log)

    # ---- 方案2: GPW v4 (备选) ----
    if result is None:
        log("    WorldPop 无数据，尝试 GPW v4...")
        result = _try_gpw(roi_geometry, area_sq_km, log)

    if result is None:
        log("    ⚠️ 所有人口数据源均无有效数据（该区域可能无覆盖）")
        # 写入占位 CSV
        empty_record = {
            '总人口估算': 0,
            '平均人口密度_人每平方千米': 0,
            '最大人口密度_人每平方千米': 0,
            'ROI面积_km2': round(area_sq_km, 3),
            '数据来源': '无有效数据',
        }
        df = pd.DataFrame([empty_record])
        df.to_csv(os.path.join(output_dir, "population_stats.csv"), index=False)
        return

    record = {
        '总人口估算': round(result['total'], 1),
        '平均人口密度_人每平方千米': round(result['density'], 1),
        '最大人口密度_人每平方千米': round(result['max_density'], 1),
        'ROI面积_km2': round(area_sq_km, 3),
        '数据来源': result.get('source', 'unknown'),
    }
    df = pd.DataFrame([record])
    df.to_csv(os.path.join(output_dir, "population_stats.csv"), index=False)
    log(f"  人口数据已保存（来源: {record['数据来源']}, 估算总人口: {record['总人口估算']:.0f}, "
        f"密度: {record['平均人口密度_人每平方千米']:.1f} 人/km²）")


def _try_worldpop(roi_geometry, area_sq_km, log):
    """尝试从 WorldPop 获取人口数据。"""
    try:
        # WorldPop 100m 人口计数集合 —— 按年份组织
        pop_col = ee.ImageCollection("WorldPop/GP/100m/pop")
        # 按时间降序排列，获取最新可用影像（通常是 2020 年）
        pop_sorted = pop_col.filterBounds(roi_geometry).sort('system:time_start', False)
        pop_img = pop_sorted.first()

        # 验证影像是否有效（通过检查 band 名称）
        band_names = pop_img.bandNames().getInfo()
        if not band_names or 'population' not in band_names:
            log(f"    WorldPop 影像无 population 波段 (bands: {band_names})")
            return None

        # 获取影像年份
        try:
            img_date = pop_img.date().format('YYYY').getInfo()
            log(f"    WorldPop 影像年份: {img_date}")
        except Exception:
            img_date = 'unknown'

        pop_reducer = (
            ee.Reducer.sum()
            .combine(ee.Reducer.mean(), sharedInputs=True)
            .combine(ee.Reducer.max(), sharedInputs=True)
        )
        stats = pop_img.select('population').reduceRegion(
            reducer=pop_reducer,
            geometry=roi_geometry,
            scale=100,
            maxPixels=1e9,
        ).getInfo()

        if not stats:
            return None

        total_pop = stats.get('population_sum')
        mean_pop = stats.get('population_mean')
        max_pop = stats.get('population_max')

        # 全为 None 或 0 → 无数据
        if (total_pop is None or total_pop == 0) and (mean_pop is None or mean_pop == 0):
            log(f"    WorldPop 数据全为 0/None (sum={total_pop}, mean={mean_pop})")
            return None

        return {
            'total': total_pop or 0,
            'density': (mean_pop or 0) * 100,  # 100m像素 → km²
            'max_density': (max_pop or 0) * 100,
            'source': f'WorldPop ({img_date})',
        }
    except Exception as e:
        log(f"    WorldPop 处理出错: {e}")
        return None


def _try_gpw(roi_geometry, area_sq_km, log):
    """尝试从 GPW v4 获取人口数据（低分辨率备选）。"""
    try:
        gpw = ee.Image("CIESIN/GPWv411/GPW_Population_Count/GPW_Population_Count_2020")

        pop_reducer = (
            ee.Reducer.sum()
            .combine(ee.Reducer.mean(), sharedInputs=True)
            .combine(ee.Reducer.max(), sharedInputs=True)
        )
        stats = gpw.select('population').reduceRegion(
            reducer=pop_reducer,
            geometry=roi_geometry,
            scale=1000,  # GPW 约 1km 分辨率
            maxPixels=1e9,
        ).getInfo()

        if not stats:
            return None

        total_pop = stats.get('population_sum')
        mean_pop = stats.get('population_mean')
        max_pop = stats.get('population_max')

        if (total_pop is None or total_pop == 0) and (mean_pop is None or mean_pop == 0):
            log(f"    GPW 数据全为 0/None")
            return None

        return {
            'total': total_pop or 0,
            'density': (mean_pop or 0) * 1,  # GPW 像元单位已是 人/像元(~1km²)
            'max_density': max_pop or 0,
            'source': 'GPW v4 (2020)',
        }
    except Exception as e:
        log(f"    GPW 处理出错: {e}")
        return None
