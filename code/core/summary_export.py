# -*- coding: utf-8 -*-
"""多采集点汇总导出：宽表 CSV（指标 × 时间切片 Cur/2y/3y/5y/10y）。

把多个采集点的 output 目录聚合成一张宽表：
  列: 经度, 纬度, 数据类别, 指标, Cur, 2y, 3y, 5y, 10y
  时间切片含义（暴露窗口，累计均值）:
    Cur = 最近 1 年均值
    2y / 3y / 5y / 10y = 最近 2 / 3 / 5 / 10 年均值
  静态指标（DEM、人口等）只有 Cur；实时指标（OpenWeather）只有 Cur。
"""
import json
import os

import pandas as pd

# 时间序列指标: (key, 类别, 指标, 文件名, 值列)
TIME_SERIES = [
    ("降雨", "气象", "降雨", "precipitation_stats.csv", "precipitation"),
    ("气温", "气象", "气温", "era5_climate_stats.csv", "日平均气温_C"),
    ("湿度", "气象", "湿度", "era5_climate_stats.csv", "日均相对湿度_pct"),
    ("日照", "气象", "日照", "era5_climate_stats.csv", "日照时数_h"),
    ("地温", "气象", "地温(地表温度)", "lst_stats.csv", "地表温度均值(C)"),
    ("太阳辐射", "辐射", "太阳辐射", "era5_climate_stats.csv", "太阳辐射日均_Wm2"),
    ("紫外线", "辐射", "紫外线", "uv_stats.csv", "总紫外_Wm2"),
    ("NDVI", "植被", "NDVI", "ndvi_stats.csv", "区域NDVI均值"),
    ("EVI", "植被", "EVI", "evi_stats.csv", "区域EVI均值"),
    ("SAVI", "植被", "SAVI", "savi_stats.csv", "区域SAVI均值"),
    ("NDWI", "植被", "NDWI", "ndwi_stats.csv", "区域NDWI均值"),
    ("MNDWI", "植被", "MNDWI", "mndwi_stats.csv", "区域MNDWI均值"),
    ("植被覆盖度", "植被", "植被覆盖度", "fvc_stats.csv", "区域植被覆盖度均值"),
    ("夜间灯光", "社会经济", "夜间灯光", "viirs_stats.csv", "夜光均值"),
    ("NO2", "污染", "NO2", "s5p_no2_stats.csv", "NO2柱浓度_umol_per_m2"),
]

# 实时 JSON 指标（只有 Cur）: (类别, 指标, 文件名, 取值函数)
def _air_aqi(d):
    try:
        return float(d["now"]["aqi"])
    except Exception:
        return None


def _air_pm25(d):
    try:
        return float(d["now"]["components"]["pm2_5"])
    except Exception:
        return None


def _air_pm10(d):
    try:
        return float(d["now"]["components"]["pm10"])
    except Exception:
        return None


def _weather_temp(d):
    try:
        return float(d["now"]["temp_c"])
    except Exception:
        return None


def _weather_humidity(d):
    try:
        return float(d["now"]["humidity"])
    except Exception:
        return None


REALTIME_JSON = [
    ("污染", "AQI", "air_quality.json", _air_aqi),
    ("污染", "PM2.5", "air_quality.json", _air_pm25),
    ("污染", "PM10", "air_quality.json", _air_pm10),
    ("气象", "气温(实时)", "weather.json", _weather_temp),
    ("气象", "湿度(实时)", "weather.json", _weather_humidity),
]


def _read_lonlat(output_dir):
    """从 meta.json 读取经纬度。"""
    try:
        with open(os.path.join(output_dir, "meta.json"), "r", encoding="utf-8") as f:
            meta = json.load(f)
        loc = meta.get("location", "")
        # location 形如 "Lon:116.3912, Lat:39.9055"
        lon = lat = None
        if "Lon:" in loc:
            parts = loc.split(",")
            lon = float(parts[0].split("Lon:")[1].strip())
            lat = float(parts[1].split("Lat:")[1].strip())
        return lon, lat
    except Exception:
        return None, None


def _compute_slices(dates, values):
    """计算 Cur/2y/3y/5y/10y 时间切片（最近 N 年累计均值）。"""
    if not dates or not values:
        return [None] * 5
    df = pd.DataFrame({"date": pd.to_datetime(dates, errors="coerce"),
                       "val": pd.to_numeric(values, errors="coerce")}).dropna()
    if df.empty:
        return [None] * 5
    max_date = df["date"].max()
    slices = []
    for years in (1, 2, 3, 5, 10):
        since = max_date - pd.DateOffset(years=years)
        sub = df[df["date"] >= since]["val"]
        slices.append(round(float(sub.mean()), 4) if not sub.empty else None)
    return slices


def _extract_time_series(path, value_col):
    """从时间序列 CSV 读取 (dates, values)。"""
    try:
        df = pd.read_csv(path)
    except Exception:
        return [], []
    date_col = "Date" if "Date" in df.columns else ("时间" if "时间" in df.columns else None)
    if date_col is None or value_col not in df.columns:
        return [], []
    return df[date_col].tolist(), df[value_col].tolist()


def build_summary_csv(output_dirs, output_path):
    """把多个采集输出目录聚合成一张宽表 CSV。

    Args:
        output_dirs: 输出目录列表
        output_path: 生成的 CSV 路径
    Returns:
        (成功, 行数或错误信息)
    """
    rows = []
    for d in output_dirs:
        if not os.path.isdir(d):
            continue
        lon, lat = _read_lonlat(d)

        # 时间序列指标
        for key, cat, label, fname, col in TIME_SERIES:
            path = os.path.join(d, fname)
            if not os.path.exists(path):
                continue
            dates, vals = _extract_time_series(path, col)
            if not dates:
                continue
            slices = _compute_slices(dates, vals)
            rows.append([lon, lat, cat, label] + slices)

        # 实时 JSON 指标（只有 Cur）
        for cat, label, fname, getter in REALTIME_JSON:
            path = os.path.join(d, fname)
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                val = getter(data)
            except Exception:
                val = None
            if val is None:
                continue
            rows.append([lon, lat, cat, label, val, None, None, None, None])

    if not rows:
        return False, "未找到任何可导出的数据"

    cols = ["经度", "纬度", "数据类别", "指标", "Cur", "2y", "3y", "5y", "10y"]
    df = pd.DataFrame(rows, columns=cols)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    return True, len(df)
