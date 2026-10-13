"""批量转 COG：日期识别、命名模板、坐标系检查与重投影、单文件转换。"""
import os
import re
from datetime import date, timedelta
from pathlib import Path

import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.shutil import copy as rcopy
from rasterio.vrt import WarpedVRT
from rasterio.warp import calculate_default_transform

RESAMPLING = {"平均（连续数据：温度、指数等）": "AVERAGE", "最近邻（分类数据：土地覆盖等）": "NEAREST"}
COMPRESS = {"DEFLATE（推荐）": "DEFLATE", "LZW": "LZW", "ZSTD（更小更快，需较新 GDAL）": "ZSTD", "不压缩": "NONE"}
DATE_MODES = {"自动识别文件名中的日期": "auto", "年积日（如 2019193 = 2019 年第 193 天）": "doy", "正则表达式": "regex"}
TARGET_CRS = {"WGS84（EPSG:4326，默认）": "EPSG:4326", "CGCS2000（EPSG:4490）": "EPSG:4490",
              "保持原坐标系（不重投影）": None, "自定义 EPSG…": "custom"}
TEMPLATE_PRESETS = ["{id}_{date}", "{name}", "{name}_cog", "{YYYY}{MM}_{name}"]


# ---------------------------------------------------------------- 日期识别
def find_date(name, temporal, mode="auto", regex=""):
    """从文件名识别日期，按时间尺度截断后返回元组：year→(年,) month→(年,月) day→(年,月,日)。失败返回 None。"""
    s = Path(name).stem
    y = mo = d = None
    if mode == "regex":
        try:
            m = re.search(regex, s)
        except re.error:
            return None
        if not m or "Y" not in m.groupdict():
            return None
        g = m.groupdict()
        y = int(g["Y"])
        mo = int(g["M"]) if g.get("M") else None
        d = int(g["D"]) if g.get("D") else None
        if g.get("DOY"):
            try:
                dt = date(y, 1, 1) + timedelta(days=int(g["DOY"]) - 1)
            except ValueError:
                return None
            mo, d = dt.month, dt.day
    elif mode == "doy":
        m = re.search(r"(?<!\d)((?:19|20)\d{2})[-_.]?(\d{3})(?!\d)", s)
        if not m:
            return None
        try:
            dt = date(int(m.group(1)), 1, 1) + timedelta(days=int(m.group(2)) - 1)
        except ValueError:
            return None
        y, mo, d = dt.year, dt.month, dt.day
    else:
        pats = {"day": r"(?<!\d)((?:19|20)\d{2})[-_.]?(\d{2})[-_.]?(\d{2})(?!\d)",
                "month": r"(?<!\d)((?:19|20)\d{2})[-_.]?(\d{2})(?!\d)",
                "year": r"(?<!\d)((?:19|20)\d{2})(?!\d)"}
        m = re.search(pats[temporal], s)
        if not m:
            return None
        g = [int(x) for x in m.groups()] + [None, None]
        y, mo, d = g[0], g[1], g[2]
    if y is None:
        return None
    if mo is not None and not 1 <= mo <= 12:
        return None
    if d is not None:
        try:
            date(y, mo or 1, d)
        except ValueError:
            return None
    need = {"year": 1, "month": 2, "day": 3}[temporal]
    parts = (y, mo, d)[:need]
    return None if any(p is None for p in parts) else tuple(parts)


def date_text(d, temporal):
    """日期元组 → 文件名里的日期串：YYYY / YYYYMM / YYYYMMDD。"""
    return "" if temporal == "static" or not d else "".join(f"{v:04d}" if i == 0 else f"{v:02d}" for i, v in enumerate(d))


def render_name(template, src_name, sid, d, temporal):
    """按模板生成目标文件名（含 .tif）。占位符：{name} {id} {date} {YYYY} {MM} {DD}。"""
    y, m, dd = (list(d or ()) + [None, None, None])[:3]
    out = template
    for k, v in {"{name}": Path(src_name).stem, "{id}": sid or "", "{date}": date_text(d, temporal),
                 "{YYYY}": f"{y:04d}" if y else "", "{MM}": f"{m:02d}" if m else "", "{DD}": f"{dd:02d}" if dd else ""}.items():
        out = out.replace(k, v)
    out = re.sub(r'[\\/:*?"<>|]', "_", out).strip("_. ")
    if "{" in out or "}" in out or not out:
        raise ValueError("命名模板含有未知占位符或结果为空")
    return out + ".tif"


# ---------------------------------------------------------------- 坐标系
def _epsg(crs):
    try:
        return crs.to_epsg() if crs else None
    except Exception:
        return None


def crs_action(src_crs, target, assign=None):
    """判断该文件需要怎样处理坐标系。返回 (动作, 说明)。
    动作：keep 不改 / same 已是目标 / relabel 仅改标签 / reproject 重投影 / missing 缺坐标系。"""
    if src_crs is None and not assign:
        return "missing", "没有坐标系"
    cur = CRS.from_user_input(assign) if src_crs is None else src_crs
    if target is None:
        return "keep", cur.to_string()
    tgt = CRS.from_user_input(target)
    if cur == tgt:
        return "same", f"已是 {tgt.to_string()}"
    if {_epsg(cur), _epsg(tgt)} == {4326, 4490}:        # 两者在米级内一致，只改标签不重采样
        return "relabel", f"{cur.to_string()} → {tgt.to_string()}（仅改标签）"
    return "reproject", f"{cur.to_string()} → {tgt.to_string()}（重投影）"


def read_crs(path):
    with rasterio.open(path) as ds:
        return ds.crs


# ---------------------------------------------------------------- 转换
def to_cog(src, dst, compress="DEFLATE", blocksize=512, resampling="AVERAGE", target_crs=None,
           assign_crs=None, assign_nodata=None, res=None):
    """转成 COG。target_crs=None 表示保持原坐标系；assign_* 仅对源文件缺失该信息时生效。
    重投影的重采样：连续数据用双线性，分类数据（resampling=NEAREST）用最近邻。"""
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    tmp = str(dst) + ".part"
    opts = dict(driver="COG", compress=compress, blocksize=blocksize, overview_resampling=resampling,
                num_threads="ALL_CPUS", predictor="YES" if compress in ("DEFLATE", "LZW", "ZSTD") else "NO")
    with rasterio.open(src) as ds:
        action, _ = crs_action(ds.crs, target_crs, assign_crs)
        if action == "missing":
            raise ValueError("文件没有坐标系，请在「补坐标系」里指定")
        src_crs = ds.crs or CRS.from_user_input(assign_crs)
        nodata = ds.nodata if ds.nodata is not None else assign_nodata
        if action == "reproject":
            if nodata is None:
                if ds.dtypes[0].startswith("float"):
                    nodata = -9999.0                    # 浮点栅格：重投影后边缘用 -9999 填充
                else:
                    raise ValueError("整型栅格重投影需要先指定无效值（边缘填充用）")
            dst_crs = CRS.from_user_input(target_crs)
            kw = {"resolution": res} if res else {}
            tr, w, h = calculate_default_transform(src_crs, dst_crs, ds.width, ds.height, *ds.bounds, **kw)
            rs = Resampling.nearest if resampling == "NEAREST" else Resampling.bilinear
            with WarpedVRT(ds, src_crs=src_crs, crs=dst_crs, transform=tr, width=w, height=h,
                           resampling=rs, src_nodata=nodata, nodata=nodata) as vrt:
                rcopy(vrt, tmp, **opts)
        elif action == "relabel" or ds.crs is None or (assign_nodata is not None and ds.nodata is None):
            out_crs = CRS.from_user_input(target_crs) if (action == "relabel" and target_crs) else src_crs
            kw = dict(src_crs=src_crs, crs=out_crs)
            if nodata is not None:
                kw.update(src_nodata=nodata, nodata=nodata)
            with WarpedVRT(ds, **kw) as vrt:
                rcopy(vrt, tmp, **opts)
        else:
            rcopy(ds, tmp, **opts)
    os.replace(tmp, dst)          # 先写临时文件再改名，中断不会留下残缺的 .tif
    return dst


# ================================================================ NetCDF 支持（按时间层拆分，数值保持原样）
_LAT = ("lat", "latitude", "y")
_LON = ("lon", "longitude", "x")


def _open_nc(path):
    import xarray as xr
    # mask_and_scale=False：保持原始整数/浮点值，不做缩放，也不把无效值换成 NaN
    return xr.open_dataset(path, mask_and_scale=False, decode_times=False)


def _pick_var(ds, var=None):
    if var and var in ds.data_vars:
        return var
    for k, v in ds.data_vars.items():
        d = [x.lower() for x in v.dims]
        if any(x in _LAT for x in d) and any(x in _LON for x in d):
            return k
    raise ValueError("没有找到带经纬度的二维栅格变量")


def _layer_dates(ds, tdim, n, path):
    """每个时间层的日期 (年, 月, 日)；无法确定的返回 None。返回 (列表, 来源说明)。"""
    if tdim is None:
        return [None], "无时间维，日期取自文件名"
    tv = ds[tdim]
    units = tv.attrs.get("units", "")
    if "since" in units:
        from xarray.coding.times import decode_cf_datetime
        import pandas as pd
        dt = pd.to_datetime(decode_cf_datetime(tv.values, units, tv.attrs.get("calendar", "standard")))
        return [(t.year, t.month, t.day) for t in dt], "时间坐标"
    m = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", Path(path).stem)
    if m and n == 12:
        return [(int(m.group(1)), i + 1, 1) for i in range(12)], "时间坐标无单位，按文件名年份推定为 12 个月"
    if m and n in (365, 366):
        d0 = date(int(m.group(1)), 1, 1)
        return [((d0 + timedelta(days=i)).year, (d0 + timedelta(days=i)).month, (d0 + timedelta(days=i)).day) for i in range(n)], "按文件名年份推定为逐日"
    return [None] * n, "无法确定各层日期"


def nc_describe(path, var=None, assume_crs="EPSG:4326"):
    """读取 NetCDF 头信息。返回 dict：var、层数、各层日期、坐标系、无效值、数据类型、缩放等。"""
    ds = _open_nc(path)
    try:
        var = _pick_var(ds, var)
        v = ds[var]
        lat = next(d for d in v.dims if d.lower() in _LAT)
        lon = next(d for d in v.dims if d.lower() in _LON)
        others = [d for d in v.dims if d not in (lat, lon)]
        if len(others) > 1:
            raise ValueError(f"变量 {var} 有多个额外维度 {others}，暂不支持")
        tdim = others[0] if others else None
        n = ds.sizes[tdim] if tdim else 1
        dates, dnote = _layer_dates(ds, tdim, n, path)
        a = v.attrs
        wkt = ds["spatial_ref"].attrs.get("crs_wkt") if "spatial_ref" in ds else None
        if wkt:
            crs, cnote = CRS.from_wkt(wkt), "文件内置"
        else:
            crs, cnote = CRS.from_user_input(assume_crs), "文件未写坐标系，按经纬度推定"
        nod = a.get("_FillValue", a.get("missing_value"))
        return dict(var=var, lat=lat, lon=lon, tdim=tdim, n=n, dates=dates, date_note=dnote, crs=crs, crs_note=cnote,
                    nodata=None if nod is None else float(nod), dtype=str(v.dtype), scale=float(a.get("scale_factor", 1.0)),
                    offset=float(a.get("add_offset", 0.0)), units=str(a.get("units", "")), shape=(ds.sizes[lat], ds.sizes[lon]))
    finally:
        ds.close()


def nc_read(path, var=None, index=0, assume_crs="EPSG:4326"):
    """读 NetCDF 的一层（无时间维时 index=0），保持原始数值。返回 (数组[北在上], transform, info)。"""
    import numpy as np
    from rasterio.transform import from_origin
    info = nc_describe(path, var, assume_crs)
    ds = _open_nc(path)
    try:
        v = ds[info["var"]]
        if info["tdim"]:
            v = v.isel({info["tdim"]: index})
        arr = np.asarray(v.transpose(info["lat"], info["lon"]).values)
        lat = np.asarray(ds[info["lat"]].values, dtype="float64")
        lon = np.asarray(ds[info["lon"]].values, dtype="float64")
    finally:
        ds.close()
    dx, dy = float(lon[1] - lon[0]), abs(float(lat[1] - lat[0]))
    if lat[0] < lat[-1]:                                  # 纬度由南向北：翻成北在上，数值不变
        arr, top = arr[::-1], lat[-1]
    else:
        top = lat[0]
    return arr, from_origin(lon[0] - dx / 2, top + dy / 2, dx, dy), info


def array_to_cog(arr, transform, crs, dst, nodata=None, scale=1.0, offset=0.0, tags=None, **opts):
    """把一个二维数组写成 COG（先写临时 GeoTIFF）。opts 同 to_cog。"""
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".tif")
    os.close(fd)
    try:
        with rasterio.open(tmp, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1, dtype=arr.dtype,
                           crs=crs, transform=transform, nodata=nodata) as out:
            out.write(arr, 1)
            if scale != 1.0 or offset != 0.0:
                out.scales, out.offsets = (scale,), (offset,)
            if tags:
                out.update_tags(**{k: str(v) for k, v in tags.items()})
        return to_cog(tmp, dst, **opts)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def nc_layer_to_cog(path, var, index, dst, assume_crs="EPSG:4326", **opts):
    """把 NetCDF 的第 index 层转成 COG。数值、数据类型、无效值保持原样，
    缩放系数和偏移量写入 GeoTIFF 的 scale/offset 元数据（不直接乘进数值）。opts 同 to_cog。"""
    arr, transform, info = nc_read(path, var, index, assume_crs)
    return array_to_cog(arr, transform, info["crs"], dst, nodata=info["nodata"], scale=info["scale"], offset=info["offset"],
                        tags=dict(SOURCE_FILE=Path(path).name, SOURCE_VARIABLE=info["var"], TIME_INDEX=index,
                                  UNITS=info["units"]), **opts)
