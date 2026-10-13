# -*- coding: utf-8 -*-
"""日值 → 月值聚合：逐月对一个「日」数据序列求均值（或总和），输出为一个新的「月」数据序列（COG）。

只统计有效像元：无效值（NaN 或文件声明的无效值）不参与；某像元当月没有任何有效值则仍为无效值。
当月缺少的日期不会补，均值只基于现有天数，每个月实际用了多少天记录在 _月聚合记录.csv 里。
"""
import calendar
import csv
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

from core import cog
from core import raster_catalog as RC


def _read(path, var):
    if Path(path).suffix.lower() == ".nc":
        arr, tr, info = cog.nc_read(path, var)
        return arr, tr, info["crs"], info["nodata"]
    import rasterio
    with rasterio.open(path) as ds:
        return ds.read(1), ds.transform, ds.crs, ds.nodata


def daily_to_monthly(src, out, stat="mean", var=None, log=print, progress=lambda i, n: None, stop=None, **cog_opts):
    """src: 日序列 Series；out: 月序列 Series（temporal=month，folder 已设置）。返回每月使用天数的列表。"""
    assert src.temporal == "day" and out.temporal == "month" and stat in ("mean", "sum")
    files = src.files()
    by_month = defaultdict(list)
    for k, ps in files.items():
        by_month[k[:6]].append(ps[0])
    months = sorted(by_month)
    records = []
    for mi, ym in enumerate(months):
        if stop is not None and stop.is_set():
            break
        progress(mi, len(months))
        total = cnt = None
        for p in by_month[ym]:
            arr, tr, crs, nod = _read(p, var)
            a = arr.astype("float64")
            ok = ~np.isnan(a)
            if nod is not None and not np.isnan(nod):
                ok &= a != nod
            if total is None:
                total, cnt = np.zeros(a.shape), np.zeros(a.shape, dtype="int32")
            total[ok] += a[ok]
            cnt += ok
        y, m = int(ym[:4]), int(ym[4:])
        out_arr = np.full(total.shape, np.nan, dtype="float32")
        good = cnt > 0
        out_arr[good] = (total[good] / cnt[good] if stat == "mean" else total[good]).astype("float32")
        dst = out.folder / f"{y:04d}" / f"{out.id}_{ym}.tif"
        cog.array_to_cog(out_arr, tr, crs, dst, nodata=float("nan"),
                         tags=dict(STATISTIC=stat, SOURCE_SERIES=src.id, DAYS_USED=len(by_month[ym]),
                                   DAYS_IN_MONTH=calendar.monthrange(y, m)[1]), **cog_opts)
        records.append((ym, len(by_month[ym]), calendar.monthrange(y, m)[1]))
        log(f"{ym}: 使用 {len(by_month[ym])}/{calendar.monthrange(y, m)[1]} 天")
    progress(len(months), len(months))
    return records


def write_record(out, records, stat, src_id):
    path = out.folder / "_月聚合记录.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["月份", "使用天数", "当月天数", "缺少天数", "统计方式", "来源序列"])
        for ym, used, total in records:
            w.writerow([ym, used, total, total - used, "月均" if stat == "mean" else "月总和", src_id])
    return path
