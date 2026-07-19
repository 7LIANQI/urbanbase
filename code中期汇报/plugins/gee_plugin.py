"""Google Earth Engine 遥感数据插件：夜光、NDVI、地表温度。"""
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
                    'LST_Celsius_mean': '地表温度均值(℃)',
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
