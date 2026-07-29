# -*- coding: utf-8 -*-
"""Google Earth Engine 遥感数据插件：夜光、NDVI、地表温度。

GEE 使用 google-auth / google-api-core 发起请求，不直接通过 requests。
如需代理，请在系统层级配置（环境变量 HTTP_PROXY/HTTPS_PROXY 或 VPN 全局模式）。
"""
import os
import json

import ee
import pandas as pd
from google.oauth2 import service_account

from utils import make_logger
from config import LST_SCALE, LST_OFFSET, LST_KELVIN


def initialize_gee(key_path=None, log_callback=None):
    """初始化 Google Earth Engine。"""
    log = make_logger(log_callback)

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


def get_gee_stats(roi_geometry, start_date, end_date, output_dir, log_callback=None,
                  enable_viirs=True, enable_ndvi=True, enable_lst=True):
    """获取 VIIRS 夜光 / Sentinel-2 NDVI / Landsat 8 地表温度统计。"""
    log = make_logger(log_callback)

    reducer_base = (
        ee.Reducer.mean()
        .combine(ee.Reducer.sampleStdDev(), sharedInputs=True)
        .combine(ee.Reducer.minMax(), sharedInputs=True)
        .combine(ee.Reducer.median(), sharedInputs=True)
    )

    # ---- VIIRS 夜光 ----
    if enable_viirs:
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
    else:
        log("  ⏭️ VIIRS 夜光已禁用")

    # ---- NDVI ----
    if enable_ndvi:
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
    else:
        log("  ⏭️ NDVI 已禁用")

    # ---- 地表温度 ----
    if enable_lst:
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
    else:
        log("  ⏭️ 地表温度已禁用")


def _process_era5_hourly(img):
    """ERA5 逐时数据处理 —— 将原始波段转换为气温/辐射/湿度。

    此函数被 get_era5_climate_stats 和 get_era5_hourly_stats 共用。
    """
    temp_c = img.select('temperature_2m').subtract(273.15)
    dew_c = img.select('dewpoint_temperature_2m').subtract(273.15)
    solar_w = img.select('surface_solar_radiation_downwards').divide(3600)
    a = temp_c.multiply(17.625).divide(temp_c.add(243.04)).exp()
    b = dew_c.multiply(17.625).divide(dew_c.add(243.04)).exp()
    rh = b.divide(a).multiply(100).rename('humidity')
    return img.addBands([
        temp_c.rename('temp_c'), solar_w.rename('solar_w'), rh,
    ])


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

    def process_hourly_with_sunshine(img):
        """带日照标记的逐时处理（仅用于逐日聚合）。"""
        img = _process_era5_hourly(img)
        sunshine = img.select('solar_w').gt(120).rename('sunshine')
        return img.addBands(sunshine)

    processed = era5.map(process_hourly_with_sunshine).select(
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
        img = _process_era5_hourly(img)
        stats = img.reduceRegion(
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
                       log_callback=None, enable_ndwi=True, enable_evi=True):
    """从 Sentinel-2 计算 NDWI 和 EVI 时间序列。

    NDWI (McFeeters): (Green - NIR) / (Green + NIR) = (B3 - B8) / (B3 + B8)
    EVI: 2.5 * ((B8 - B4) / (B8 + 6*B4 - 7.5*B2 + 1))

    输出: ndwi_stats.csv, evi_stats.csv
    """
    log = make_logger(log_callback)

    if not enable_ndwi and not enable_evi:
        return

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
    if enable_ndwi:
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
    else:
        log("  ⏭️ NDWI 已禁用")

    # ---- EVI ----
    if enable_evi:
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
    else:
        log("  ⏭️ EVI 已禁用")


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


# ===================== P0: 土地覆盖 / 大气污染 / 地表水 =====================

# ESA WorldCover 地物类别映射
_LANDCOVER_CLASSES = {
    10: "森林",
    20: "灌木",
    30: "草地",
    40: "耕地",
    50: "建成区",
    60: "裸地/稀疏植被",
    70: "雪/冰",
    80: "永久水体",
    90: "草本湿地",
    95: "红树林",
    100: "苔藓/地衣",
}


def get_landcover_stats(roi_geometry, output_dir, log_callback=None):
    """获取 ESA WorldCover 土地覆盖分类（2021 年，10m 分辨率）。

    数据集: ESA/WorldCover/v200
    输出: landcover_stats.csv —— 各地类面积与占比
    """
    log = make_logger(log_callback)
    log("  获取 ESA WorldCover 土地覆盖数据...")

    try:
        wc = ee.ImageCollection("ESA/WorldCover/v200").first()
        # 使用 connectedPixelCount 获取各类别像元数
        # 方法：对每个类别构建二值图 → reduceRegion sum
        landcover_img = wc.select('Map')

        # 使用 frequencyHistogram 一次性获取各类别像元计数
        hist = landcover_img.reduceRegion(
            reducer=ee.Reducer.frequencyHistogram(),
            geometry=roi_geometry,
            scale=10,
            maxPixels=1e9,
        ).getInfo()

        hist_data = hist.get('Map', {})
        if not hist_data:
            log("  WorldCover 无数据，跳过")
            return

        # 计算像元面积（10m × 10m = 100 m²）
        pixel_area_m2 = 100.0
        total_pixels = sum(int(v) for v in hist_data.values())
        total_area_m2 = total_pixels * pixel_area_m2

        records = []
        for class_id_str, count_str in sorted(hist_data.items(),
                                               key=lambda x: int(x[1]), reverse=True):
            class_id = int(class_id_str)
            pixel_count = int(count_str)
            area_m2 = pixel_count * pixel_area_m2
            pct = (pixel_count / total_pixels * 100) if total_pixels > 0 else 0
            label = _LANDCOVER_CLASSES.get(class_id, f"类别{class_id}")
            records.append({
                "类别代码": class_id,
                "地物类别": label,
                "像元数": pixel_count,
                "面积_m2": round(area_m2, 1),
                "面积_km2": round(area_m2 / 1e6, 4),
                "占比_pct": round(pct, 2),
            })

        if records:
            # 计算汇总指标
            built_pct = sum(r["占比_pct"] for r in records if r["类别代码"] == 50)
            water_pct = sum(r["占比_pct"] for r in records if r["类别代码"] == 80)
            green_pct = sum(r["占比_pct"] for r in records
                           if r["类别代码"] in (10, 20, 30, 90, 95, 100))
            impervious_pct = built_pct  # 建成区近似不透水面

            summary = {
                "类别代码": "",
                "地物类别": "【汇总】",
                "像元数": total_pixels,
                "面积_m2": round(total_area_m2, 1),
                "面积_km2": round(total_area_m2 / 1e6, 4),
                "占比_pct": 100.0,
            }
            records.append(summary)

            df = pd.DataFrame(records)
            df.to_csv(os.path.join(output_dir, "landcover_stats.csv"), index=False)
            log(f"  土地覆盖数据已保存（{len(records) - 1} 类, "
                f"建成区 {built_pct:.1f}%, 绿地 {green_pct:.1f}%, 水体 {water_pct:.1f}%）")
        else:
            log("  土地覆盖数据为空，跳过")
    except Exception as e:
        log(f"  土地覆盖数据处理出错: {e}")


def get_s5p_no2_stats(roi_geometry, start_date, end_date, output_dir,
                      log_callback=None):
    """获取 Sentinel-5P 对流层 NO₂ 柱浓度时间序列。

    数据集: COPERNICUS/S5P/OFFL/L3_NO2 (约 1113m 分辨率, 2018.7+)
    Harp 格式三级产品，已去除云/雪像素。
    输出: s5p_no2_stats.csv —— 逐日 NO₂ 柱浓度统计
    """
    log = make_logger(log_callback)
    log("  获取 Sentinel-5P NO₂ 数据...")

    try:
        s5p = (
            ee.ImageCollection("COPERNICUS/S5P/OFFL/L3_NO2")
            .filterBounds(roi_geometry)
            .filterDate(start_date, end_date)
            .select('tropospheric_NO2_column_number_density')
        )

        def calc_no2(img):
            stats = img.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=roi_geometry,
                scale=1113,
                maxPixels=1e9,
            )
            return ee.Feature(None, stats).set({
                'Date': img.date().format('YYYY-MM-dd'),
            })

        feats = s5p.map(calc_no2).getInfo()
        records = [
            f['properties'] for f in feats.get('features', [])
            if f.get('properties', {}).get('tropospheric_NO2_column_number_density') is not None
        ]

        if records:
            df = pd.DataFrame(records)
            df = df[['Date', 'tropospheric_NO2_column_number_density']]
            # 单位转换：mol/m² → µmol/m²（乘以 1e6）
            df['NO2柱浓度_umol_per_m2'] = (
                df['tropospheric_NO2_column_number_density'] * 1e6
            ).round(2)
            df = df[['Date', 'NO2柱浓度_umol_per_m2']]
            df.to_csv(os.path.join(output_dir, "s5p_no2_stats.csv"), index=False)
            log(f"  对流层 NO₂ 数据已保存（{len(df)} 天）")
        else:
            log("  该区域/时间段无 Sentinel-5P NO₂ 数据（可能因为云覆盖或 2018.7 前）")
    except Exception as e:
        log(f"  Sentinel-5P NO₂ 处理出错: {e}")


def get_jrc_water_stats(roi_geometry, output_dir, log_callback=None):
    """获取 JRC 全球地表水数据（1984-2021 年长期统计）。

    数据集: JRC/GSW1_4/GlobalSurfaceWater (30m 分辨率)
    波段:
      - occurrence: 水体出现频率（0-100%）
      - seasonality: 季节性变化（0-12 个月）
      - recurrence: 年度重现频率
      - max_extent: 最大水域范围
    输出: jrc_water_stats.csv —— 水体统计汇总
    """
    log = make_logger(log_callback)
    log("  获取 JRC 全球地表水数据...")

    try:
        gsw = ee.Image("JRC/GSW1_4/GlobalSurfaceWater")

        bands = ['occurrence', 'seasonality', 'recurrence', 'max_extent']
        stats_reducer = (
            ee.Reducer.mean()
            .combine(ee.Reducer.median(), sharedInputs=True)
            .combine(ee.Reducer.minMax(), sharedInputs=True)
        )

        stats = gsw.select(bands).reduceRegion(
            reducer=stats_reducer,
            geometry=roi_geometry,
            scale=30,
            maxPixels=1e9,
        ).getInfo()

        if not stats:
            log("  JRC 地表水数据为空，跳过")
            return

        # 计算水体面积（occurrence > 50% 的区域）
        water_mask = gsw.select('occurrence').gt(50)
        water_area_stats = water_mask.multiply(ee.Image.pixelArea()).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=roi_geometry,
            scale=30,
            maxPixels=1e9,
        ).getInfo()

        # 计算季节性水体面积（seasonality > 6 的区域）
        seasonal_mask = gsw.select('seasonality').gt(6)
        seasonal_area_stats = seasonal_mask.multiply(ee.Image.pixelArea()).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=roi_geometry,
            scale=30,
            maxPixels=1e9,
        ).getInfo()

        water_area_m2 = water_area_stats.get('occurrence_sum', 0) or 0
        seasonal_area_m2 = seasonal_area_stats.get('seasonality_sum', 0) or 0

        record = {
            "水体出现频率均值_pct": round(stats.get('occurrence_mean', 0), 1),
            "水体出现频率中位数_pct": round(stats.get('occurrence_median', 0), 1),
            "季节性均值_月": round(stats.get('seasonality_mean', 0), 2),
            "常年水体面积_km2": round(water_area_m2 / 1e6, 4),
            "季节性水体面积_km2": round(seasonal_area_m2 / 1e6, 4),
            "最大水域范围占比_pct": round(stats.get('max_extent_mean', 0) * 100, 1),
            "年际重现频率均值_pct": round(stats.get('recurrence_mean', 0), 1),
        }

        df = pd.DataFrame([record])
        df.to_csv(os.path.join(output_dir, "jrc_water_stats.csv"), index=False)
        log(f"  JRC 地表水数据已保存（常年水体 {record['常年水体面积_km2']:.3f} km²）")
    except Exception as e:
        log(f"  JRC 地表水处理出错: {e}")


# ===================== P1: MODIS LST / Dynamic World =====================

def get_modis_lst_stats(roi_geometry, start_date, end_date, output_dir,
                        log_callback=None):
    """获取 MODIS MOD11A2 8天合成地表温度时间序列（Landsat LST 补充）。

    数据集: MODIS/061/MOD11A2 (1km 分辨率, 8天合成)
    波段: LST_Day_1km, LST_Night_1km
    缩放: 值 × 0.02 → Kelvin, Kelvin - 273.15 → Celsius
    输出: modis_lst_stats.csv —— 每 8 天白天/夜间 LST
    """
    log = make_logger(log_callback)
    log("  获取 MODIS 8天 LST 数据...")

    try:
        modis = (
            ee.ImageCollection("MODIS/061/MOD11A2")
            .filterBounds(roi_geometry)
            .filterDate(start_date, end_date)
            .select(['LST_Day_1km', 'LST_Night_1km'])
        )

        def calc_modis_lst(img):
            # MODIS LST: scale 0.02 → Kelvin
            day_c = img.select('LST_Day_1km').multiply(0.02).subtract(273.15).rename('day_c')
            night_c = img.select('LST_Night_1km').multiply(0.02).subtract(273.15).rename('night_c')
            img_with_c = img.addBands([day_c, night_c])
            stats = img_with_c.select(['day_c', 'night_c']).reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=roi_geometry,
                scale=1000,
                maxPixels=1e9,
            )
            return ee.Feature(None, stats).set({
                'Date': img.date().format('YYYY-MM-dd'),
            })

        feats = modis.map(calc_modis_lst).getInfo()
        records = [
            f['properties'] for f in feats.get('features', [])
            if f.get('properties', {}).get('day_c') is not None
        ]

        if records:
            df = pd.DataFrame(records)
            df = df[['Date', 'day_c', 'night_c']]
            df.columns = ['Date', '白天LST_C', '夜间LST_C']
            df['白天LST_C'] = df['白天LST_C'].round(1)
            df['夜间LST_C'] = df['夜间LST_C'].round(1)
            df.to_csv(os.path.join(output_dir, "modis_lst_stats.csv"), index=False)
            log(f"  MODIS LST 数据已保存（{len(df)} 个8天周期）")
        else:
            log("  MODIS LST 无数据，跳过")
    except Exception as e:
        log(f"  MODIS LST 处理出错: {e}")


# Dynamic World 类别映射
_DW_CLASSES = {
    0: "水域",
    1: "森林",
    2: "草地",
    3: "耕地",
    4: "湿地",
    5: "灌木",
    6: "建成区",
    7: "裸地",
    8: "雪/冰",
}


def get_dynamic_world_stats(roi_geometry, start_date, end_date, output_dir,
                            log_callback=None):
    """获取 Dynamic World 近实时土地覆盖时间序列。

    数据集: GOOGLE/DYNAMICWORLD/V1 (10m, Sentinel-2 近实时, 2020.6+)
    波段: label (最可能类别) + 各类别概率
    输出: dw_stats.csv —— 各时期主要地类面积占比
    """
    log = make_logger(log_callback)
    log("  获取 Dynamic World 土地覆盖数据...")

    try:
        dw = (
            ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
            .filterBounds(roi_geometry)
            .filterDate(start_date, end_date)
            .select('label')
        )

        def calc_dw(img):
            # 获取各类别直方图
            hist = img.reduceRegion(
                reducer=ee.Reducer.frequencyHistogram(),
                geometry=roi_geometry,
                scale=10,
                maxPixels=1e9,
            )
            return ee.Feature(None, hist).set({
                'Date': img.date().format('YYYY-MM-dd'),
            })

        feats = dw.map(calc_dw).getInfo()
        feature_list = feats.get('features', [])
        if not feature_list:
            log("  Dynamic World 无数据，跳过")
            return

        records = []
        for feat in feature_list:
            props = feat.get('properties', {})
            date_str = props.get('Date', '')
            label_hist = props.get('label', {})
            if not label_hist:
                continue

            total = sum(int(v) for v in label_hist.values())
            if total == 0:
                continue

            row = {'Date': date_str}
            for class_id_str, count_str in label_hist.items():
                class_id = int(class_id_str)
                class_name = _DW_CLASSES.get(class_id, f"类别{class_id}")
                pct = int(count_str) / total * 100
                row[f"{class_name}_pct"] = round(pct, 2)
            records.append(row)

        if records:
            df = pd.DataFrame(records)
            # 确保 Date 在第一列
            cols = ['Date'] + [c for c in df.columns if c != 'Date']
            df = df[cols]
            df.to_csv(os.path.join(output_dir, "dw_stats.csv"), index=False)
            log(f"  Dynamic World 数据已保存（{len(df)} 期）")
        else:
            log("  Dynamic World 无有效数据，跳过")
    except Exception as e:
        log(f"  Dynamic World 处理出错: {e}")


# ===================== P2: 森林变化 / 树冠高度 =====================

def get_hansen_forest_stats(roi_geometry, output_dir, log_callback=None):
    """获取 Hansen 全球森林变化数据（2000-2023 年）。

    数据集: UMD/hansen/global_forest_change_2023_v1_11 (30m)
    波段:
      - treecover2000: 2000 年树木覆盖率（0-100%）
      - loss: 期间损失（1=损失, 0=未损失）
      - gain: 期间增长（1=增长, 0=非增长, 2000-2012）
      - lossyear: 损失年份（0=未损失, 1-23=2001-2023）
    输出: hansen_forest_stats.csv —— 森林变化汇总
    """
    log = make_logger(log_callback)
    log("  获取 Hansen 全球森林变化数据...")

    try:
        gfc = ee.Image("UMD/hansen/global_forest_change_2023_v1_11")

        # 树冠覆盖率统计
        cover_stats = gfc.select('treecover2000').reduceRegion(
            reducer=ee.Reducer.mean().combine(
                ee.Reducer.median(), sharedInputs=True
            ).combine(ee.Reducer.minMax(), sharedInputs=True),
            geometry=roi_geometry,
            scale=30,
            maxPixels=1e9,
        ).getInfo()

        # 损失面积（loss=1）
        loss_area = gfc.select('loss').multiply(
            ee.Image.pixelArea()
        ).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=roi_geometry,
            scale=30,
            maxPixels=1e9,
        ).getInfo()

        # 增长面积（gain=1）
        gain_area = gfc.select('gain').multiply(
            ee.Image.pixelArea()
        ).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=roi_geometry,
            scale=30,
            maxPixels=1e9,
        ).getInfo()

        # 按年份统计损失
        loss_area_m2 = loss_area.get('loss_sum', 0) or 0
        gain_area_m2 = gain_area.get('gain_sum', 0) or 0

        # 逐年损失统计
        yearly_records = []
        for year_offset in range(1, 24):  # 2001-2023
            year_img = gfc.select('lossyear').eq(year_offset)
            year_loss = year_img.multiply(ee.Image.pixelArea()).reduceRegion(
                reducer=ee.Reducer.sum(),
                geometry=roi_geometry,
                scale=30,
                maxPixels=1e9,
            ).getInfo()
            loss_val = year_loss.get('lossyear_sum', 0) or 0
            if loss_val > 0:
                yearly_records.append({
                    "年份": 2000 + year_offset,
                    "损失面积_km2": round(loss_val / 1e6, 4),
                })

        record = {
            "2000年树冠覆盖率均值_pct": round(cover_stats.get('treecover2000_mean', 0), 1),
            "2000年树冠覆盖率中位数_pct": round(cover_stats.get('treecover2000_median', 0), 1),
            "2000年树冠覆盖率最大值_pct": round(cover_stats.get('treecover2000_max', 0), 1),
            "2000-2023损失总面积_km2": round(loss_area_m2 / 1e6, 4),
            "2000-2012增长总面积_km2": round(gain_area_m2 / 1e6, 4),
            "净变化_km2": round((gain_area_m2 - loss_area_m2) / 1e6, 4),
        }

        df = pd.DataFrame([record])
        df.to_csv(os.path.join(output_dir, "hansen_forest_stats.csv"), index=False)

        # 逐年损失单独保存
        if yearly_records:
            yearly_df = pd.DataFrame(yearly_records)
            yearly_df.to_csv(
                os.path.join(output_dir, "hansen_loss_by_year.csv"), index=False
            )

        log(f"  森林变化数据已保存（树冠覆盖 {record['2000年树冠覆盖率均值_pct']:.1f}%, "
            f"损失 {record['2000-2023损失总面积_km2']:.3f} km²）")
    except Exception as e:
        log(f"  Hansen 森林变化处理出错: {e}")


def get_canopy_height_stats(roi_geometry, output_dir, log_callback=None):
    """获取 ETH 全球树冠高度数据（2020 年，10m 分辨率）。

    数据集: projects/meta-forest-monitoring-okw37/assets/ETH_Global_Canopy_Height_2020
    波段: height (单位: 米, 仅树木覆盖区域有值, 其他为 0)
    输出: canopy_height_stats.csv —— 树冠高度统计
    """
    log = make_logger(log_callback)
    log("  获取 ETH 全球树冠高度数据...")

    try:
        ch = ee.Image(
            "projects/meta-forest-monitoring-okw37/assets/ETH_Global_Canopy_Height_2020"
        )

        # 全区域统计（含 0 值 —— 非树木区域）
        ch_reducer = (
            ee.Reducer.mean()
            .combine(ee.Reducer.median(), sharedInputs=True)
            .combine(ee.Reducer.minMax(), sharedInputs=True)
            .combine(ee.Reducer.sampleStdDev(), sharedInputs=True)
        )
        stats = ch.select('height').reduceRegion(
            reducer=ch_reducer,
            geometry=roi_geometry,
            scale=10,
            maxPixels=1e9,
        ).getInfo()

        # 仅树木区域统计（>2m）
        canopy_mask = ch.select('height').gt(2)
        canopy_stats = ch.select('height').updateMask(canopy_mask).reduceRegion(
            reducer=ch_reducer,
            geometry=roi_geometry,
            scale=10,
            maxPixels=1e9,
        ).getInfo()

        # 树木覆盖率（高度 > 2m 的像元占比）
        canopy_pixels = canopy_mask.multiply(ee.Image.pixelArea()).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=roi_geometry,
            scale=10,
            maxPixels=1e9,
        ).getInfo()

        # ROI 总面积
        total_area_m2 = roi_geometry.area(1).getInfo()
        total_area_ha = total_area_m2 / 10000 if total_area_m2 else 1.0
        canopy_area_m2 = canopy_pixels.get('height_sum', 0) or 0
        canopy_area_ha = canopy_area_m2 / 10000

        record = {
            "树冠高度均值_m": round(stats.get('height_mean', 0), 1),
            "树冠高度中位数_m": round(stats.get('height_median', 0), 1),
            "树冠高度最大值_m": round(stats.get('height_max', 0), 1),
            "树冠高度标准差_m": round(stats.get('height_stdDev', 0), 1),
            "树木区域平均树高_m": round(canopy_stats.get('height_mean', 0), 1),
            "树木区域最大树高_m": round(canopy_stats.get('height_max', 0), 1),
            "树冠覆盖率_pct": round(canopy_area_ha / total_area_ha * 100, 2) if total_area_ha > 0 else 0,
            "树冠面积_ha": round(canopy_area_ha, 2),
        }

        df = pd.DataFrame([record])
        df.to_csv(os.path.join(output_dir, "canopy_height_stats.csv"), index=False)
        log(f"  树冠高度数据已保存（树木区域平均树高 {record['树木区域平均树高_m']:.1f} m, "
            f"树冠覆盖率 {record['树冠覆盖率_pct']:.1f}%）")
    except Exception as e:
        log(f"  树冠高度处理出错: {e}")
        # ETH Canopy Height 是社区数据集，可能因权限拒绝访问
        if "Permission" in str(e) or "403" in str(e) or "denied" in str(e).lower():
            log("    ⚠️ ETH 树冠高度数据集可能需要额外授权（非 GEE 官方数据集）")
