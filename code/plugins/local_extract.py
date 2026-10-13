# -*- coding: utf-8 -*-
"""本地栅格库的点位提取引擎：与 GEE 提取同一套口径（缓冲区/像元、回溯窗口/时间段序列、年/月粒度、时间与空间聚合）。

数据来自「栅格数据目录」里的各数据序列（COG）。读取一律用窗口，不整图读入。
数值 = 原始值 × scale + offset（来自各序列的 dataset.json）；无效值不参与；缺失的期不参与，全缺则输出为空。
"""
import json
import math
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import rasterio.transform
from pyproj import Transformer
from rasterio.windows import Window

from core.crs import to_wgs84
from core import raster_catalog as RC

WINDOW_YEARS = {"cur": 0, "y1": 1, "y2": 2, "y3": 3, "y5": 5, "y10": 10}
_RED = {"median": np.nanmedian, "mean": np.nanmean, "max": np.nanmax, "min": np.nanmin}
_M_LAT, _M_LON = 110574.0, 111320.0


def _fd_limit():
    """尽量调高「同时打开文件数」上限，返回当前上限。macOS 图形程序默认只有 256。"""
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        want = 16384 if hard in (-1, resource.RLIM_INFINITY) else min(hard, 16384)
        if soft < want:
            resource.setrlimit(resource.RLIMIT_NOFILE, (want, hard))
            soft = want
        return soft
    except Exception:
        return 256


# 每个线程缓存已打开的栅格文件。月序列一个点的窗口要用几十个文件，缓存装不下就会反复打开（外置硬盘上慢 20 倍）
_CACHE_CAP = 200 if _fd_limit() >= 4096 else 48


def window_units(key, gran):
    return 1 if key == "cur" else WINDOW_YEARS[key] * (12 if gran == "month" else 1)


def _mode(a):
    v = a[~np.isnan(a)]
    if v.size == 0:
        return np.nan
    u, c = np.unique(v, return_counts=True)
    return float(u[np.argmax(c)])


def _reduce(stack, red):
    """沿第 0 轴逐像元合成（忽略 NaN）。全 NaN 的像元返回 NaN。"""
    if red == "mode":
        flat = stack.reshape(stack.shape[0], -1)
        return np.array([_mode(flat[:, i]) for i in range(flat.shape[1])]).reshape(stack.shape[1:])
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return _RED[red](stack, axis=0)


class LocalSeries:
    """一个数据序列的读取封装：文件索引、坐标转换、窗口读取（线程内缓存已打开的文件）。"""

    def __init__(self, s):
        if s.temporal == "day":
            raise ValueError(f"{s.id}：暂不支持逐日序列，请先用「日→月聚合」转成月序列")
        self.s = s
        self.files = {k: ps[0] for k, ps in s.files().items() if ps[0].suffix.lower() in (".tif", ".tiff")}
        if not self.files:
            raise ValueError(f"{s.id}：没有可读取的 GeoTIFF 文件（NetCDF 请先转成 COG）")
        with rasterio.open(next(iter(self.files.values()))) as ds:
            self.crs = ds.crs
        nd = (s.nodata or "").strip().lower()
        self.nodata_override = None if nd == "" else ("none" if nd == "none" else float(nd))   # 序列声明的无效值优先
        self.tf = None if (self.crs is not None and self.crs.to_epsg() == 4326) else (
            Transformer.from_crs(4326, self.crs, always_xy=True) if self.crs is not None else None)
        self._tl = threading.local()
        keys = list(self.files)
        self.years = sorted({int(k[:4]) for k in keys}) if s.temporal in ("year", "month") else []
        self.months = sorted({int(k[:4]) * 12 + int(k[4:6]) - 1 for k in keys}) if s.temporal == "month" else []

    def _ds(self, path):
        cache = getattr(self._tl, "cache", None)
        if cache is None:
            cache = self._tl.cache = {}
        d = cache.get(path)
        if d is None:
            if len(cache) > _CACHE_CAP:
                for p in list(cache)[:16]:
                    cache.pop(p).close()
            d = cache[path] = rasterio.open(path)
        return d

    def xy(self, lon, lat):
        return (lon, lat) if self.tf is None else self.tf.transform(lon, lat)

    def read(self, path, lon, lat, r):
        """读缓冲区窗口，返回 (数组[含 NaN], 圆内掩膜)；点在栅格外返回 None。"""
        ds = self._ds(path)
        x, y = self.xy(lon, lat)
        geo = ds.crs is not None and ds.crs.is_geographic
        if geo:
            rx, ry = r / (_M_LON * max(math.cos(math.radians(lat)), 0.01)), r / _M_LAT
        else:
            rx = ry = r
        try:
            row, col = ds.index(x, y)
        except Exception:
            return None
        if not (0 <= row < ds.height and 0 <= col < ds.width):
            return None
        px, py = abs(ds.transform.a), abs(ds.transform.e)
        nx, ny = int(math.ceil(rx / px)), int(math.ceil(ry / py))
        r0, c0 = max(row - ny, 0), max(col - nx, 0)
        r1, c1 = min(row + ny + 1, ds.height), min(col + nx + 1, ds.width)
        a = ds.read(1, window=Window(c0, r0, c1 - c0, r1 - r0)).astype("float64")
        nod = ds.nodata if self.nodata_override is None else (None if self.nodata_override == "none" else self.nodata_override)
        if nod is not None:
            a[np.isnan(a) if np.isnan(nod) else np.isclose(a, nod, rtol=1e-6, atol=0)] = np.nan
        rows, cols = np.mgrid[r0:r1, c0:c1]
        xc, yc = rasterio.transform.xy(ds.transform, rows, cols, offset="center")      # 像元中心
        xc, yc = np.asarray(xc).reshape(rows.shape), np.asarray(yc).reshape(rows.shape)
        if geo:
            dx, dy = (xc - x) * _M_LON * math.cos(math.radians(lat)), (yc - y) * _M_LAT
        else:
            dx, dy = xc - x, yc - y
        inside = dx * dx + dy * dy <= r * r
        if r <= 0 or not inside.any():                            # 无缓冲区或缓冲区小于半个像元：取点所在像元
            inside = np.zeros_like(inside)
            inside[row - r0, col - c0] = True
        return a, inside


def unit_files(ls, kind, y, m):
    """某个时间单位（年/月）对应的文件列表（先逐文件合成再跨单位合成）。"""
    t = ls.s.temporal
    if t == "static":
        return list(ls.files.values())[:1]
    if t == "year":
        f = ls.files.get(f"{y:04d}")
        return [f] if f else []
    # 月序列
    if kind == "month":
        f = ls.files.get(f"{y:04d}{m:02d}")
        return [f] if f else []
    return [f for mm in range(1, 13) if (f := ls.files.get(f"{y:04d}{mm:02d}"))]


def units_for(kind, y, m, key, gran):
    """窗口包含的单位 [(kind,y,m)]。cur 为观测日所在单位；其余为所在单位之前的 N 年。"""
    if key == "cur":
        return [(kind, y, m)]
    out, yy, mm = [], y, m
    for _ in range(window_units(key, gran)):
        if kind == "month":
            mm -= 1
            if mm == 0:
                yy, mm = yy - 1, 12
        else:
            yy -= 1
        out.append((kind, yy, mm))
    return out


def nearest_unit(ls, kind, units):
    """窗口内一个文件都没有时，找离窗口最近的有数据单位（前后等距时取较早的）。
    返回 ((kind, y, m), 偏差年数)；序列里没有任何可用单位返回 None。"""
    if ls.s.temporal == "static" or not units:
        return None
    month_axis = ls.s.temporal == "month" and kind == "month"
    av = ls.months if month_axis else ls.years
    if not av:
        return None
    idx = [y * 12 + m - 1 for _k, y, m in units] if month_axis else [y for _k, y, _m in units]
    lo, hi = min(idx), max(idx)
    cand = []
    below, above = [a for a in av if a < lo], [a for a in av if a > hi]
    if below:
        cand.append((lo - below[-1], 0, below[-1]))
    if above:
        cand.append((above[0] - hi, 1, above[0]))
    if not cand:
        return None
    gap, _, a = min(cand)
    if month_axis:
        y, m = divmod(a, 12)
        return (kind, y, m + 1), gap / 12.0
    return (kind, a, 1), float(gap)


def value_for(ls, lon, lat, r, groups, red_t, red_s, memo, info=None):
    """groups: 每个单位的文件列表。先逐像元合成各单位，再跨单位合成，最后做空间聚合；缺失返回 NaN。
    info（dict）会被填入：expected 应有单位数、used 实际有数据的单位数、reason 为空的原因。"""
    comps, masks = [], []
    n_files = n_read = 0
    for files in groups:
        arrs = []
        for f in files:
            n_files += 1
            if f not in memo:
                memo[f] = ls.read(f, lon, lat, r)
            if memo[f] is not None:
                n_read += 1
                arrs.append(memo[f])
        if not arrs:
            continue
        shapes = {a.shape for a, _ in arrs}
        if len(shapes) == 1:
            comps.append((_reduce(np.stack([a for a, _ in arrs]), red_t), arrs[0][1]))
        else:                                              # 同一单位内网格不同：先空间后时间
            comps.append((np.array([_spatial(a, m, red_s) for a, m in arrs]), None))
    if info is not None:
        info["expected"], info["used"] = len(groups), len(comps)
        info["reason"] = ("无数据文件" if n_files == 0 else "点在栅格范围外" if n_read == 0 else "")
    if not comps:
        return np.nan
    if len({c[0].shape for c in comps}) == 1 and all(c[1] is not None for c in comps):
        stack = np.stack([c[0] for c in comps])
        comp = _reduce(stack, red_t)
        mask = comps[-1][1]
        val = _spatial(comp, mask, red_s)
    else:                                                  # 跨单位网格不同（如 10 km 与 1 km）：先空间后时间
        vals = [(_spatial(c[0], c[1], red_s) if c[1] is not None else float(_reduce(c[0][:, None], red_t)[0])) for c in comps]
        val = float(_reduce(np.array(vals)[:, None], red_t)[0])
    if info is not None and np.isnan(val) and not info["reason"]:
        info["reason"] = "该范围内全是无效值"
    return val


def _spatial(arr, mask, red):
    v = arr[mask]
    v = v[~np.isnan(v)]
    if v.size == 0:
        return np.nan
    return _mode(v) if red == "mode" else float(np.median(v) if red == "median" else np.mean(v))


# ---------------------------------------------------------------- 矢量面数据（如行政区划）：点在面内
import re as _re

_ATTR = _re.compile(r"^\s*([^\[\|\s]+)\s*(?:\[(\d*):(\d*)\])?\s*(?:\|\s*(\w+)(?::(\w+))?)?\s*$")


def eval_attr(df, expr, folder=None):
    """属性表达式：字段名，可带切片和查表。如 name、gb[3:9]、gb[3:5]|cn_province、gb[3:7]|table:city。
    table:xxx 读取数据序列文件夹里的 lookup_xxx.csv（两列：code, name）。"""
    from core.admin_cn import LOOKUPS
    m = _ATTR.match(expr)
    if not m:
        raise ValueError(f"属性映射表达式无法解析：{expr}")
    fld, a, b, lk, arg = m.groups()
    ser = df[fld].astype(str)
    if a or b:
        ser = ser.str.slice(int(a) if a else None, int(b) if b else None)
    if lk == "table":
        t = pd.read_csv(Path(folder) / f"lookup_{arg}.csv", dtype=str, encoding="utf-8-sig")
        ser = ser.map(dict(zip(t["code"], t["name"])))
    elif lk:
        ser = ser.map(LOOKUPS[lk])
    return ser


def vector_columns(s):
    return list(s.attributes)


def series_columns(s, cols):
    """序列 s 在输出列 cols 里占的列。"""
    return list(s.attributes) if s.kind == "vector" else [c for c in cols if c == s.id or c.startswith(s.id + "_")]


def vector_values(s, lon, lat):
    """点在面内匹配。返回 DataFrame（与 lon/lat 等长）：属性列 + 匹配方式 + 距离。
    先判断点是否落在面内（含边界）；不在任何面内且设了就近距离时，取最近的面（距离为到面边界的实际距离，米）。"""
    import geopandas as gpd
    from pyproj import Geod
    from shapely.geometry import Point
    from shapely.ops import nearest_points
    f = next(iter(s.files().values()))[0]
    g = gpd.read_file(f)
    g = g[g.geom_type.isin(["Polygon", "MultiPolygon"])].to_crs(4326).reset_index(drop=True)
    attrs = pd.DataFrame({c: eval_attr(g, e, s.folder) for c, e in s.attributes.items()})
    n = len(lon)
    out = pd.DataFrame({c: pd.Series([None] * n, dtype=object) for c in attrs.columns})
    match = pd.Series([""] * n, dtype=object)
    dist = pd.Series([np.nan] * n)
    ok = ~(np.isnan(lon) | np.isnan(lat)) & (np.abs(lon) <= 180) & (np.abs(lat) <= 90)
    idx = np.flatnonzero(ok)
    pts = gpd.GeoDataFrame({"_i": idx}, geometry=gpd.points_from_xy(lon[idx], lat[idx]), crs=4326)
    j = gpd.sjoin(pts, g[["geometry"]], how="left", predicate="intersects")
    j = j[~j["_i"].duplicated()]                                   # 点正好在边界上、同时属于两个面时取第一个
    hit = j.dropna(subset=["index_right"])
    for c in attrs.columns:
        out.loc[hit["_i"].to_numpy(), c] = attrs[c].to_numpy()[hit["index_right"].astype(int).to_numpy()]
    match.loc[hit["_i"].to_numpy()] = "点在面内"
    miss = j[j["index_right"].isna()]["_i"].to_numpy()
    if len(miss) and s.nearest_m > 0:
        deg = s.nearest_m / 90000.0                                 # 粗略换成度，只用来缩小搜索范围
        geod = Geod(ellps="WGS84")
        sub = gpd.points_from_xy(lon[miss], lat[miss])
        ti, d = g.sindex.nearest(sub, return_all=False, max_distance=deg * 1.5, return_distance=True)
        for k, t in zip(ti[0], ti[1]):
            i = miss[k]
            p0 = Point(lon[i], lat[i])
            p1 = nearest_points(p0, g.geometry.iloc[t])[1]
            _, _, meters = geod.inv(p0.x, p0.y, p1.x, p1.y)
            if meters <= s.nearest_m:
                for c in attrs.columns:
                    out.loc[i, c] = attrs[c].iloc[t]
                match.loc[i], dist.loc[i] = "就近匹配", round(float(meters), 1)
    out[f"{s.id}_match"] = match
    out[f"{s.id}_dist_m"] = dist
    return out


def column_names(series, mode, windows, periods):
    cols = []
    for s in series:
        if s.kind == "vector":
            cols += vector_columns(s)
        elif s.temporal == "static":
            cols.append(s.id)
        else:
            cols += [f"{s.id}_{lab}" for lab in (windows if mode == "rel" else [p[0] for p in periods])]
    return cols


def run(df, lon_col, lat_col, date_col, series, buffer_m, mode, windows, periods, temporal, spatial,
        gran="year", crs="wgs84", epsg=None, workers=4, log=print, progress=lambda d, t: None, stop=None, diag=None,
        fill=True):
    """返回 (结果 DataFrame[index=行号], 列名列表)。series 为 raster_catalog.Series 列表。"""
    df = df.reset_index(drop=True)
    lon, lat = to_wgs84(pd.to_numeric(df[lon_col], errors="coerce"), pd.to_numeric(df[lat_col], errors="coerce"), crs, epsg)
    dates = pd.to_datetime(df[date_col], errors="coerce") if mode == "rel" else pd.Series([pd.NaT] * len(df))
    lss = [(LocalSeries(s) if s.kind != "vector" else None) for s in series]
    cols = column_names(series, mode, windows, periods)
    kind = "month" if gran == "month" else "year"
    pers = [(lab, pd.Timestamp(a), pd.Timestamp(b)) for lab, a, b in periods]
    out = np.full((len(df), len(cols)), np.nan)
    used = np.zeros((len(df), len(cols)), dtype="int16")          # 每个值实际用到的时间单位数
    expected = np.zeros((len(df), len(cols)), dtype="int16")      # 应有的时间单位数
    reason = np.full((len(df), len(cols)), "", dtype=object)
    sub = np.zeros((len(df), len(cols)), dtype=bool)               # 窗口内没有数据，改用最近一期
    gap = np.zeros((len(df), len(cols)))                           # 改用的那一期与窗口相差几年
    done = [0]
    lock = threading.Lock()

    def one(i):
        if stop is not None and stop.is_set():
            return
        lo, la = lon[i], lat[i]
        if not (-180 <= lo <= 180 and -90 <= la <= 90) or np.isnan(lo) or np.isnan(la):
            return
        memo, j = {}, 0
        for s0, ls in zip(series, lss):
            if ls is None:                       # 矢量序列：之后统一做点在面内，这里只留出列位置
                j += len(vector_columns(s0))
                continue
            s = ls.s
            red_t = "mode" if s.categorical else temporal
            red_s = "mode" if s.categorical else spatial
            r = 0 if buffer_m <= 0 else buffer_m
            def put(j, units):
                groups = [unit_files(ls, k, y, m) for k, y, m in units]
                if fill and units and not any(groups):             # 窗口内一个文件都没有：用离窗口最近的一期
                    alt = nearest_unit(ls, kind, units)
                    if alt:
                        groups = [unit_files(ls, *alt[0])]
                        sub[i, j], gap[i, j] = True, alt[1]
                inf = {}
                out[i, j] = _fin(value_for(ls, lo, la, r, groups, red_t, red_s, memo, inf), s)
                used[i, j], expected[i, j], reason[i, j] = inf["used"], len(units) or inf["expected"], inf["reason"]
                if sub[i, j] and np.isnan(out[i, j]):
                    sub[i, j] = False
            if s.temporal == "static":
                put(j, [(kind, 0, 0)])
                j += 1
                continue
            if mode == "rel":
                d = dates[i]
                if pd.isna(d):
                    j += len(windows)
                    continue
                for w in windows:
                    put(j, units_for(kind, d.year, d.month, w, gran))
                    j += 1
            else:
                for lab, a, b in pers:
                    put(j, [(kind, a.year, a.month)])
                    j += 1
        with lock:
            done[0] += 1
            if done[0] % 50 == 0:
                progress(done[0], len(df))

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, range(len(df))))
    progress(len(df), len(df))
    res = pd.DataFrame(out, columns=cols)
    for s0 in series:                                            # 矢量序列：整批点一起做点在面内
        if s0.kind != "vector":
            continue
        vv = vector_values(s0, np.asarray(lon, float), np.asarray(lat, float))
        miss = (vv[f"{s0.id}_match"] == "").to_numpy()           # 匹配方式、距离只用于诊断，不输出
        for c in vector_columns(s0):
            res[c] = vv[c].to_numpy()
            k = cols.index(c)
            expected[:, k] = 1
            used[:, k] = (~miss).astype(int)
            reason[:, k] = np.where(miss, "点不在任何面内（也不在就近距离内）", "")
    if diag is not None:
        diag.update(used=used, expected=expected, reason=reason, cols=cols, sub=sub, gap=gap)
    return res, cols


def _fin(v, s):
    if np.isnan(v):
        return np.nan
    return v if s.categorical else v * s.scale + s.offset
