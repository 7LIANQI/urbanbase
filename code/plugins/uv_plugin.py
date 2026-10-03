# -*- coding: utf-8 -*-
"""本地紫外线数据读取插件。

数据源: 中国地表晴空紫外辐射数据集 (1981-2023)
  - 10km 分辨率 (0.1°), netCDF3 格式, 覆盖中国 (lon 73.5~135, lat 18~53.5)
  - 逐日文件 UV_YYYYMMDD.nc: 24 小时总紫外 (W/m²), 维度 (time, lat, lon)
  - 光谱文件 UV_05nm_YYYYMMDDHH.nc: 241 波段 (280-400nm, 0.5nm), 维度 (band, lat, lon)
"""
import os
import re

from utils import make_logger


def _nearest_index(arr, value):
    """找数组中最接近 value 的下标（纯 Python，不依赖 numpy）。"""
    return int(min(range(len(arr)), key=lambda i: abs(arr[i] - value)))


def _parse_uv_filename(fname):
    """解析文件名 -> (类型, 时间串)。类型: 'daily' 或 'spectral'。"""
    m = re.match(r"UV_05nm_(\d{10})\.nc$", fname)
    if m:
        return "spectral", m.group(1)  # YYYYMMDDHH
    m = re.match(r"UV_(\d{8})\.nc$", fname)
    if m:
        return "daily", m.group(1)  # YYYYMMDD
    return None, None


def get_uv_stats(lon, lat, data_dir, output_dir, log_callback=None):
    """读取最近网格点的紫外数据，输出 uv_stats.csv。

    Args:
        lon, lat: 查询坐标
        data_dir: 存放 .nc 文件的目录
        output_dir: 输出目录

    Returns:
        {file_key: path} 字典（供 index.json 用），无数据返回 {}。
    """
    log = make_logger(log_callback)

    # scipy 仅在本函数内按需加载，避免 app 启动时因缺依赖崩溃
    try:
        import numpy as np
        from scipy.io import netcdf_file
    except ImportError:
        log("⚠️ 缺少 scipy 依赖，无法读取紫外线数据（请运行 pip install scipy）")
        return {}

    if not os.path.isdir(data_dir):
        log("⚠️ 紫外线数据目录不存在")
        return {}

    nc_files = sorted(f for f in os.listdir(data_dir) if f.endswith(".nc"))
    if not nc_files:
        log("⚠️ 紫外线数据目录为空，无 .nc 文件")
        return {}

    rows = []  # (时间, 类型, 总紫外, UV-A, UV-B)
    for fname in nc_files:
        ftype, tstr = _parse_uv_filename(fname)
        if ftype is None:
            continue
        path = os.path.join(data_dir, fname)
        try:
            nc = netcdf_file(path, mode="r", mmap=False)
            lat_arr = nc.variables["lat"].data.copy()
            lon_arr = nc.variables["lon"].data.copy()
            lat_i = _nearest_index(lat_arr, lat)
            lon_i = _nearest_index(lon_arr, lon)
            uv = nc.variables["UV"].data.copy()
            band = nc.variables["band"].data.copy() if ftype == "spectral" else None
            nc.close()
        except Exception as e:
            log(f"⚠️ 读取 {fname} 失败: {e}")
            continue

        if ftype == "daily":
            # uv shape (24, lat, lon) -> 24 小时总紫外
            hourly = uv[:, lat_i, lon_i]
            ymd = f"{tstr[:4]}-{tstr[4:6]}-{tstr[6:8]}"
            for h, val in enumerate(hourly):
                rows.append((f"{ymd} {h:02d}:00", "总紫外", float(val), "", ""))
        else:
            # uv shape (band, lat, lon) -> 光谱积分
            spectral = uv[:, lat_i, lon_i]
            ymdh = f"{tstr[:4]}-{tstr[4:6]}-{tstr[6:8]} {tstr[8:10]}:00"
            total = float(np.sum(spectral))                 # 全波段总紫外
            uva = float(np.sum(spectral[band >= 315]))      # UV-A: 315-400nm
            uvb = float(np.sum(spectral[band < 315]))       # UV-B: 280-315nm
            rows.append((ymdh, "光谱", total, uva, uvb))

    if not rows:
        log("⚠️ 未解析到任何紫外线数据")
        return {}

    import pandas as pd
    df = pd.DataFrame(rows, columns=["时间", "类型", "总紫外_Wm2", "UV_A_Wm2", "UV_B_Wm2"])
    out_path = os.path.join(output_dir, "uv_stats.csv")
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    log(f"  紫外线数据已保存（{len(df)} 条）")
    return {"uv_stats": out_path}
