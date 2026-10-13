# -*- coding: utf-8 -*-
"""GEE 数据源目录：按「指标类别」组织，每个类别有多个可选数据源（全局设置里选定）。

新增数据源：在对应 Category 的 sources 里加一个 Source。build(ctx) 返回
composite(start, end, reducer, geom) -> 波段名等于 columns 的 ee.Image。
mode: series 时间序列（按时间窗聚合）/ nearest 取最接近 start 的一景 / static 静态（不分时间）。
"""
from dataclasses import dataclass, field
from typing import Callable

import ee

CATALOG_URL = "https://developers.google.com/earth-engine/datasets/catalog/"
# 数据性质标注：key -> (角标文字, 说明)
ORIGIN = {
    "model": ("模式", "再分析（数值模式）的输出，不是实测或卫星反演；格点值是模式对大气、陆面的模拟，存在系统偏差，地形复杂处尤其明显。"),
    "blend": ("融合", "以站点数据为主、结合气候平均态做插值，无站点的地区用再分析补缺，含一定的模式成分。"),
}


@dataclass
class Source:
    key: str
    label: str                  # 设置里显示的名称
    columns: list
    scale: float                # 原生分辨率(米)，reduceRegion 用此尺度
    gee_id: str
    resolution: str
    coverage: str
    unit: str
    processing: str
    build: Callable = field(repr=False, default=None)
    mode: str = "series"
    scene: bool = False         # 景级数据：按几何过滤以提速
    notes: str = ""
    link: str = ""
    category: str = ""
    temporal: str = ""          # 类别强制的时间聚合（如降水用均值），空表示听用户的
    spatial: str = ""           # 类别强制的空间聚合（分类数据用众数），空表示听用户的
    kind: str = "raster"        # raster 栅格；vector 矢量（按点所在要素取属性）
    labels: dict = field(default_factory=dict)   # {列名: {代码: 名称}}，导出时自动追加「列名_名称」列
    origin: str = ""            # 数据性质：model 模式数据（再分析）/ blend 插值融合；空表示观测或遥感反演

    def url(self):
        return self.link or CATALOG_URL + self.gee_id.replace("/", "_")

    def badge(self):
        """列表里的醒目标注，如「〔模式〕」；无特殊性质返回空串。"""
        return f"〔{ORIGIN[self.origin][0]}〕" if self.origin in ORIGIN else ""

    def short(self):
        return f"{self.label}{self.badge()}"

    def text(self):
        t = (f"{self.label}\nGEE: {self.gee_id}\n分辨率: {self.resolution}；时间: {self.coverage}\n"
             f"输出: {', '.join(self.columns)}（{self.unit}）")
        return t + (f"\n⚠ {ORIGIN[self.origin][1]}" if self.origin in ORIGIN else "")

    def html(self):
        esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>")
        rows = [("GEE 数据集", f"<code>{self.gee_id}</code>")]
        if self.origin in ORIGIN:
            rows.append(("数据性质", f"<b style='color:#d93025'>{esc(ORIGIN[self.origin][0])}数据</b>：{esc(ORIGIN[self.origin][1])}"))
        rows += [("空间分辨率", esc(self.resolution)),
                ("时间覆盖", esc(self.coverage)), ("输出列", esc(", ".join(self.columns))),
                ("单位", esc(self.unit)), ("处理方法", esc(self.processing))]
        if self.mode != "series":
            rows.append(("时间方式", "静态，不分时间，只输出一列" if self.mode == "static"
                         else "按年份取最接近的一期；时间粒度设为月度时，同一年内各月的值相同"))
        names = {"mean": "均值", "median": "中值", "mode": "众数（出现最多的类别）"}
        if self.temporal:
            rows.append(("时间聚合", f"固定为{names.get(self.temporal, self.temporal)}（忽略全局选择）"))
        if self.spatial:
            rows.append(("空间聚合", f"固定为{names.get(self.spatial, self.spatial)}（忽略全局选择）"))
        if self.kind == "vector":
            rows.append(("取值方式", "矢量数据：取点位本身所在的那个要素的属性，不受缓冲区影响"))
        if self.labels:
            rows.append(("名称列", "导出时自动追加「" + "、".join(f"{c}_名称" for c in self.labels) + "」列，写出代码对应的中文名称"))
        if self.notes:
            rows.append(("注意", esc(self.notes)))
        body = "".join(f"<tr><td style='color:#5f6368;padding:3px 10px 3px 0;vertical-align:top'>{k}</td><td>{v}</td></tr>"
                       for k, v in rows)
        return (f"<h3 style='margin:0 0 6px 0'>{esc(self.label)}</h3><table>{body}</table>"
                f"<p><a href='{self.url()}'>在 GEE 数据目录中查看 ›</a></p>")


@dataclass
class Category:
    key: str
    name: str
    theme: str
    sources: list
    desc: str = ""
    temporal: str = ""
    spatial: str = ""

    def __post_init__(self):
        for s in self.sources:
            s.category = self.key
            s.key = f"{self.key}.{s.key}"
            if self.temporal:
                s.temporal = self.temporal
            if self.spatial:
                s.spatial = self.spatial


# ================================================================ 通用构件
def _safe(col, names, reducer):
    """时间合成；空集合也返回带正确波段名的全掩膜影像（避免整批失败）。"""
    col = col.map(lambda i: i.select(names).toFloat())
    blank = ee.ImageCollection([ee.Image.constant([0] * len(names)).rename(names).toFloat().selfMask()])
    return getattr(col.merge(blank), reducer)()


def _series(col_fn, conv, cols, scene=False):
    def build(ctx):
        raw = col_fn()

        def comp(s, e, red, geom):
            c = raw.filterDate(s, e)                 # 先筛选再逐景处理：只对窗口内的影像做运算，不依赖 map 后的元数据
            if scene:
                c = c.filterBounds(geom)
            return _safe(c.map(conv), cols, red)
        return comp
    return build


def _nearest(col_fn, conv):
    """取年份与 start 所在年份最接近的一景（多年一期的数据取最近的一期），再用 conv 转成输出波段。"""
    def build(ctx):
        col = col_fn()

        def comp(s, e, red, geom):
            y = ee.Number(ee.Date(s).get("year"))
            c = col.map(lambda i: i.set("_d", ee.Number(i.date().get("year")).subtract(y).abs()))
            return conv(ee.Image(c.sort("_d").first()))
        return comp
    return build


def _by_year(col_fn, conv, names, lo, hi):
    """逐年数据：取观测年份那一景。早于 lo 年留空；晚于 hi 年用最新一年（年度产品通常滞后一年）。"""
    def build(ctx):
        col = col_fn()
        blank = ee.Image.constant([0] * len(names)).rename(names).toFloat().selfMask()

        def comp(s, e, red, geom):
            y = ee.Number(ee.Date(s).get("year"))
            year = y.min(hi)
            img = conv(ee.Image(col.filter(ee.Filter.calendarRange(year, year, "year")).first()))
            return ee.Image(ee.Algorithms.If(y.gte(lo), img, blank))
        return comp
    return build


def _smod_conv(i):
    code = i.select("smod_code")
    code = code.updateMask(code.neq(-200))
    l1 = code.remap([30, 23, 22, 21, 13, 12, 11], [3, 2, 2, 2, 1, 1, 1]).rename("DEGURBA1_GHS")
    return ee.Image.cat([code.rename("SMOD_GHS"), l1]).toFloat()


def _static(img_fn):
    def build(ctx):
        img = img_fn()
        return lambda s, e, red, geom: img
    return build


# ================================================================ 植被 / 水体指数
_IDX = ["NDVI", "EVI", "SAVI", "NDWI", "MNDWI"]


def _idx_image(blue, green, red, nir, swir, good):
    ndvi = nir.subtract(red).divide(nir.add(red)).rename("NDVI")
    evi = nir.subtract(red).multiply(2.5).divide(
        nir.add(red.multiply(6)).subtract(blue.multiply(7.5)).add(1)).rename("EVI")
    savi = nir.subtract(red).multiply(1.5).divide(nir.add(red).add(0.5)).rename("SAVI")
    ndwi = green.subtract(nir).divide(green.add(nir)).rename("NDWI")
    mndwi = green.subtract(swir).divide(green.add(swir)).rename("MNDWI")
    return ee.Image.cat([ndvi, evi, savi, ndwi, mndwi]).updateMask(good)


def _mod_idx(img):
    qa = img.select("StateQA")
    good = qa.bitwiseAnd(3).eq(0).And(qa.bitwiseAnd(4).eq(0)).And(qa.bitwiseAnd(1024).eq(0))
    r = img.multiply(0.0001)
    return _idx_image(r.select("sur_refl_b03"), r.select("sur_refl_b04"), r.select("sur_refl_b01"),
                      r.select("sur_refl_b02"), r.select("sur_refl_b06"), good)


def _ls_idx(img):
    good = img.select("QA_PIXEL").bitwiseAnd(30).eq(0)
    r = img.multiply(2.75e-5).add(-0.2)
    return _idx_image(r.select("SR_B2"), r.select("SR_B3"), r.select("SR_B4"),
                      r.select("SR_B5"), r.select("SR_B6"), good)


def _s2_idx(img):
    scl = img.select("SCL")
    good = scl.gte(4).And(scl.lte(7))
    r = img.multiply(0.0001)
    return _idx_image(r.select("B2"), r.select("B3"), r.select("B4"),
                      r.select("B8"), r.select("B11"), good)


_FVC_DEFAULT = (0.05, 0.86)


def _fvc_endpoints(c, ctx):
    """c：端元期内、已筛选并算好指数的影像集合。NDVI 的 5% / 95% 分位数作为 FVC 端元；
    5 km 粗尺度 + 大 tileScale 控制内存，失败回退经验值。"""
    try:
        p = _safe(c, ["NDVI"], "median").reduceRegion(
            ee.Reducer.percentile([5, 95]), ctx.region, 5000, maxPixels=1e9,
            bestEffort=True, tileScale=16).getInfo()
        soil, veg = p["NDVI_p5"], p["NDVI_p95"]
        if soil is None or veg is None or veg - soil < 0.2:
            raise ValueError("端元不合理")
        return soil, veg
    except Exception as e:
        ctx.log(f"⚠️ FVC 端元计算失败（{str(e)[:60]}），改用经验值 NDVIsoil={_FVC_DEFAULT[0]}, NDVIveg={_FVC_DEFAULT[1]}")
        return _FVC_DEFAULT


def _index_source(tag, col_fn, fn, which, fvc_period, scene):
    """which: 'veg' → NDVI/EVI/SAVI/FVC；'water' → NDWI/MNDWI。"""
    raw = ["NDVI", "EVI", "SAVI"] if which == "veg" else ["NDWI", "MNDWI"]
    cols = [f"{n}_{tag}" for n in raw] + ([f"FVC_{tag}"] if which == "veg" else [])

    def build(ctx):
        rawcol = col_fn()
        calc = lambda i: fn(i).copyProperties(i, ["system:time_start"])
        if which == "veg":
            ep = rawcol.filterDate(*fvc_period)
            if scene:
                ep = ep.filterBounds(ctx.region)
            soil, veg = _fvc_endpoints(ep.map(calc), ctx)

        def comp(s, e, red, geom):
            c = rawcol.filterDate(s, e)
            if scene:
                c = c.filterBounds(geom)
            c = _safe(c.map(calc), _IDX if which == "veg" else raw, red)
            if which == "veg":
                fvc = c.select("NDVI").subtract(soil).divide(veg - soil).clamp(0, 1).rename("FVC")
                c = c.select(raw).addBands(fvc)
            else:
                c = c.select(raw)
            return c.rename(cols)
        return comp
    return build, cols


_FVC = ("植被覆盖度 FVC 用像元二分模型 (NDVI−NDVIsoil)/(NDVIveg−NDVIsoil)，端元取点位范围内近年 NDVI 的 "
        "5%/95% 分位数（5 km 尺度计算），限制在 0–1；若范围过大计算失败，改用经验值 0.05/0.86 并写入日志。")


def _idx_sources(which):
    out = []
    specs = [
        ("modis", "MODIS MOD09A1（500 m）", "MOD", lambda: ee.ImageCollection("MODIS/061/MOD09A1"), _mod_idx, 500,
         ("2020-01-01", "2023-12-31"), False, "MODIS/061/MOD09A1", "500 m，8 天合成", "2000-02 至今",
         "地表反射率 ×0.0001；用 StateQA 去云、云影与内部云标记；指数由反射率自行计算。",
         "分辨率较粗，建议缓冲区 ≥1 km；时间最长，适合 5 年、10 年窗口。"),
        ("landsat", "Landsat 8/9（30 m）", "LS",
         lambda: ee.ImageCollection("LANDSAT/LC08/C02/T1_L2").merge(ee.ImageCollection("LANDSAT/LC09/C02/T1_L2")),
         _ls_idx, 30, ("2022-01-01", "2023-12-31"), True, "LANDSAT/LC08/C02/T1_L2 + LANDSAT/LC09/C02/T1_L2",
         "30 m，16 天重访（8+9 合并约 8 天）", "LC08 自 2013-04，LC09 自 2021-10",
         "Collection 2 Level-2 地表反射率 = DN×2.75e-5 − 0.2；用 QA_PIXEL 去膨胀云、卷云、云、云影。",
         "街道尺度较合适；2013 年之前的观测点、长窗口的早期部分会缺失。"),
        ("s2", "Sentinel-2（10 m）", "S2", lambda: ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED"),
         _s2_idx, 10, ("2022-01-01", "2023-12-31"), True, "COPERNICUS/S2_SR_HARMONIZED",
         "10–20 m，约 5 天重访", "2017 起全球覆盖（部分地区 2015 起）",
         "L2A 地表反射率 = DN×1e-4；用 SCL 只保留植被、裸土、水体、未分类（4–7）；MNDWI 的 SWIR 用 B11（20 m）。",
         "精度最高，但时间最短、数据量最大、速度最慢。"),
    ]
    for key, label, tag, col_fn, fn, scale, period, scene, gid, res, cov, proc, note in specs:
        build, cols = _index_source(tag, col_fn, fn, which, period, scene)
        s = Source(key, label, cols, scale, gid, res, cov, "无量纲（指数）",
                   proc + (" " + _FVC if which == "veg" else ""), build, scene=scene, notes=note)
        out.append(s)
    return out


# ================================================================ 地表温度
def _mod_lst(key, label, asset, tag, times, since, res_text="1 km，逐日", extra_note=""):
    cols = [f"LSTd_{tag}", f"LSTn_{tag}"]

    def conv(img):
        img = img.select(["LST_Day_1km", "QC_Day", "LST_Night_1km", "QC_Night"])      # 只取用到的波段，减少计算量
        out = []
        for band, qc, name in (("LST_Day_1km", "QC_Day", cols[0]), ("LST_Night_1km", "QC_Night", cols[1])):
            lst = img.select(band)
            out.append(lst.updateMask(lst.gt(0).And(img.select(qc).bitwiseAnd(3).lte(1)))
                       .multiply(0.02).subtract(273.15).rename(name))
        return ee.Image.cat(out)
    return Source(key, label, cols, 1000, asset, res_text, f"{since} 至今", "℃",
                  f"原始值 ×0.02 得开尔文再减 273.15；QC 最低 2 位 ≤1 才保留。白天约 {times[0]}、夜间约 {times[1]} 过境。",
                  _series(lambda: ee.ImageCollection(asset), conv, cols),
                  notes="云多时有效天数少，窗口较短时可能为空。" + extra_note)


def _ls_lst_conv(img):
    good = img.select("QA_PIXEL").bitwiseAnd(30).eq(0)
    return (img.select("ST_B10").multiply(0.00341802).add(149.0).subtract(273.15)
            .updateMask(good).rename("LSTd_LS"))


# ================================================================ ERA5-Land / TerraClimate 等
def _era5_conv(spec):
    """spec: [(输出名, 原波段, 变换)]"""
    def conv(i):
        return ee.Image.cat([f(i.select(b)).rename(n) for n, b, f in spec])
    return conv


_ERA5 = "ECMWF/ERA5_LAND/DAILY_AGGR"
_ERA5_RES = "0.1°（约 11 km），逐日"
_ERA5_COV = "1950 至今（约有数天滞后）"
_ERA5_NOTE = "再分析（模式）数据，不是观测，分辨率粗；缓冲区小于约半个像元时按所在像元取值。"
_K = lambda x: x.subtract(273.15)


def _daily_series(asset, spec, scene=False):
    return _series(lambda: ee.ImageCollection(asset), _era5_conv(spec), [n for n, _, _ in spec])


_ERA5M = "ECMWF/ERA5_LAND/MONTHLY_AGGR"


def _terra(spec):
    return _daily_series("IDAHO_EPSCOR/TERRACLIMATE", spec)


# ================================================================ 人口 / 土地 / 地形
def _density(count_img, name):
    """人口计数 → 人口密度（人/km²），与像元大小无关，不同来源可比。"""
    return count_img.divide(ee.Image.pixelArea().divide(1e6)).rename(name)


def _worldpop_build(ctx):
    col = ee.ImageCollection("WorldPop/GP/100m/pop")
    proj = col.first().projection()

    def comp(s, e, red, geom):
        year = ee.Number(ee.Date(s).get("year")).max(2000).min(2020)
        img = col.filter(ee.Filter.eq("year", year)).select("population").mosaic().setDefaultProjection(proj)
        return _density(img, "POPD_WP")
    return comp


def _wc_img():
    wc = ee.ImageCollection("ESA/WorldCover/v200").first().select("Map")
    return ee.Image.cat([wc.eq(50).rename("BUILT_WC"), wc.eq(10).rename("TREE_WC"),
                         wc.eq(30).rename("GRASS_WC"), wc.eq(80).rename("WATER_WC")]).toFloat()


def _dw_conv(i):
    return i.select(["built", "trees", "grass", "water"], ["BUILT_DW", "TREE_DW", "GRASS_DW", "WATER_DW"])


def _dem(tag, img_fn):
    def make():
        dem = img_fn()
        return ee.Image.cat([dem.rename(f"ELEV_{tag}"), ee.Terrain.slope(dem).rename(f"SLOPE_{tag}")])
    return _static(make)


def _mosaic_dem(asset, band):
    def f():
        col = ee.ImageCollection(asset).select(band if band else 0)
        return col.mosaic().setDefaultProjection(col.first().projection())
    return f


def _dem_source(key, label, tag, img_fn, res, cov, proc, notes, gid, link=""):
    return Source(key, label, [f"ELEV_{tag}", f"SLOPE_{tag}"], 30 if "30" in res.split()[0] else 90, gid, res, cov,
                  "海拔 m；坡度 °", proc, _dem(tag, img_fn), mode="static", notes=notes, link=link)


# ================================================================ 目录
def _mk():
    cats = []

    cats.append(Category("veg", "植被指数（NDVI / EVI / SAVI / FVC）", "植被与水体", _idx_sources("veg"),
                         "植被绿度与覆盖度"))
    cats.append(Category("water", "水体指数（NDWI / MNDWI）", "植被与水体", _idx_sources("water"),
                         "水体与湿度相关指数"))

    cats.append(Category("lst", "地表温度", "温度与气象", [
        _mod_lst("aqua8", "MODIS Aqua MYD11A2（1 km，8 天，推荐）", "MODIS/061/MYD11A2", "MYD8", ("13:30", "01:30"), "2002-07",
                 "1 km，8 天合成", "8 天合成是官方对逐日数据的平均，影像数只有逐日的约 1/8，计算量小得多，适合月度、年度和长窗口，建议优先用。"),
        _mod_lst("terra8", "MODIS Terra MOD11A2（1 km，8 天）", "MODIS/061/MOD11A2", "MOD8", ("10:30", "22:30"), "2000-02",
                 "1 km，8 天合成", "8 天合成，计算量小，适合长窗口。"),
        _mod_lst("aqua", "MODIS Aqua MYD11A1（1 km，逐日）", "MODIS/061/MYD11A1", "MYD", ("13:30", "01:30"), "2002-07",
                 "1 km，逐日", "逐日影像数量大，长窗口（3、5、10 年）和月度粒度会很慢，容易超时或内存不足；只在需要逐日精度时使用。"),
        _mod_lst("terra", "MODIS Terra MOD11A1（1 km，逐日）", "MODIS/061/MOD11A1", "MOD", ("10:30", "22:30"), "2000-02",
                 "1 km，逐日", "同上，计算量大。"),
        Source("landsat", "Landsat 8/9 ST_B10（30 m）", ["LSTd_LS"], 30,
               "LANDSAT/LC08/C02/T1_L2 + LANDSAT/LC09/C02/T1_L2", "30 m，16 天重访", "LC08 自 2013-04，LC09 自 2021-10",
               "℃", "Collection 2 Level-2 地表温度：ST_B10×0.00341802 + 149.0 得开尔文，再减 273.15；QA_PIXEL 去云与云影。",
               _series(lambda: ee.ImageCollection("LANDSAT/LC08/C02/T1_L2").merge(ee.ImageCollection("LANDSAT/LC09/C02/T1_L2")),
                       _ls_lst_conv, ["LSTd_LS"], scene=True),
               scene=True, notes="只有白天一景（约 10:30），没有夜间；窗口短时有效景数少。"),
        Source("era5", "ERA5-Land 皮肤温度（11 km）", ["SKT_ERA5"], 11132, _ERA5, _ERA5_RES, _ERA5_COV, "℃",
               "skin_temperature 日均值减 273.15。", _daily_series(_ERA5, [("SKT_ERA5", "skin_temperature", _K)]),
               notes=_ERA5_NOTE),
    ], "遥感反演或再分析的地表（皮肤）温度"))


    cats.append(Category("t2m", "气温（近地面）", "温度与气象", [
        Source("era5", "ERA5-Land 近地面气温（11 km）", ["TAVG_ERA5", "TMAX_ERA5", "TMIN_ERA5"], 11132, _ERA5,
               _ERA5_RES, _ERA5_COV, "℃", "离地 2 米高度气温（temperature_2m）的日均、日最高、日最低，减 273.15。",
               _daily_series(_ERA5, [("TAVG_ERA5", "temperature_2m", _K), ("TMAX_ERA5", "temperature_2m_max", _K),
                                     ("TMIN_ERA5", "temperature_2m_min", _K)]), notes=_ERA5_NOTE),
        Source("era5m", "ERA5-Land 月聚合近地面气温（11 km）", ["TAVG_ERA5M", "TMAX_ERA5M", "TMIN_ERA5M"], 11132, _ERA5M,
               "0.1°（约 11 km），逐月", "1950-02 至 2026-08", "℃",
               "离地 2 米高度气温（temperature_2m）的月均、月内最高、月内最低，减 273.15；直接取月聚合产品，不必逐日合成，月度粒度下计算量小得多。",
               _daily_series(_ERA5M, [("TAVG_ERA5M", "temperature_2m", _K), ("TMAX_ERA5M", "temperature_2m_max", _K),
                                      ("TMIN_ERA5M", "temperature_2m_min", _K)]),
               notes="月内最高、最低是逐小时值里的极值，不是日最高的平均。" + _ERA5_NOTE),
        Source("terra", "TerraClimate 月最高/最低气温（4.6 km）", ["TMAX_TC", "TMIN_TC"], 4638.3, "IDAHO_EPSCOR/TERRACLIMATE",
               "约 4 km（1/24°），逐月", "1958-01 至 2024-12", "℃", "tmmx、tmmn ×0.1。",
               _terra([("TMAX_TC", "tmmx", lambda x: x.multiply(0.1)), ("TMIN_TC", "tmmn", lambda x: x.multiply(0.1))]),
               notes="月尺度；当前窗口（30 天）可能只覆盖一个月。数据截至 2024 年底，之后的观测点会是空值。"),
    ], "离地约 2 米高度的空气温度（气象常规观测高度）"))

    cats.append(Category("precip", "降水", "温度与气象", [
        Source("chirps", "CHIRPS 日降水（5 km）", ["PRCP_CHIRPS"], 5566, "UCSB-CHG/CHIRPS/DAILY", "0.05°（约 5.5 km），逐日",
               "1981 至今", "mm/天（窗口内日均）", "precipitation（红外+站点融合降水）。",
               _daily_series("UCSB-CHG/CHIRPS/DAILY", [("PRCP_CHIRPS", "precipitation", lambda x: x)]),
               notes="覆盖约南北纬 50° 之间。"),
        Source("era5", "ERA5-Land 日降水（11 km）", ["PRCP_ERA5"], 11132, _ERA5, _ERA5_RES, _ERA5_COV,
               "mm/天（窗口内日均）", "total_precipitation_sum（m）×1000。",
               _daily_series(_ERA5, [("PRCP_ERA5", "total_precipitation_sum", lambda x: x.multiply(1000))]),
               notes=_ERA5_NOTE),
        Source("era5m", "ERA5-Land 月聚合降水（11 km）", ["PRCP_ERA5M"], 11132, _ERA5M,
               "0.1°（约 11 km），逐月", "1950-02 至 2026-08", "mm/月（窗口内月均）",
               "total_precipitation_sum（m，当月累计）×1000。",
               _daily_series(_ERA5M, [("PRCP_ERA5M", "total_precipitation_sum", lambda x: x.multiply(1000))]),
               notes="模式降水，山区和强降水偏差较大；是月累计量，年度粒度下得到的是各月的平均值，不是年总量。" + _ERA5_NOTE),
        Source("terra", "TerraClimate 月降水（4.6 km）", ["PRCP_TC"], 4638.3, "IDAHO_EPSCOR/TERRACLIMATE",
               "约 4 km，逐月", "1958-01 至 2024-12", "mm/月（窗口内月均）", "pr（月累计降水）。",
               _terra([("PRCP_TC", "pr", lambda x: x)]), notes="数据截至 2024 年底，之后的观测点会是空值。"),
    ], "降水量。时间聚合固定用均值（日降水的中值几乎总是 0，没有意义）", temporal="mean"))

    cats.append(Category("srad", "太阳辐射（向下短波）", "温度与气象", [
        Source("era5", "ERA5-Land 向下短波辐射（11 km）", ["SRAD_ERA5"], 11132, _ERA5, _ERA5_RES, _ERA5_COV, "W/m²（日均）",
               "surface_solar_radiation_downwards_sum（J/m² 日累计）÷ 86400。",
               _daily_series(_ERA5, [("SRAD_ERA5", "surface_solar_radiation_downwards_sum", lambda x: x.divide(86400))]),
               notes="到达地表的太阳总辐射（含云影响），不是净辐射，也不是紫外线。" + _ERA5_NOTE),
        Source("terra", "TerraClimate 向下短波辐射（4.6 km）", ["SRAD_TC"], 4638.3, "IDAHO_EPSCOR/TERRACLIMATE",
               "约 4 km，逐月", "1958-01 至 2024-12", "W/m²（月均）", "srad ×0.1。",
               _terra([("SRAD_TC", "srad", lambda x: x.multiply(0.1))]), notes="数据截至 2024 年底，之后的观测点会是空值。"),
    ], "到达地表的太阳辐射"))

    cats.append(Category("ntl", "夜间灯光", "人类活动", [
        Source("viirs_annual", "VIIRS 年度 V2.2（463 m）", ["NTL_VIIRS_Y"], 463.83, "NOAA/VIIRS/DNB/ANNUAL_V22",
               "约 463 m（15 角秒），逐年", "2012（4 月起）–2024", "nW/(cm²·sr)",
               "average_masked（掩膜后的年平均辐亮度）；取观测年份那一年。观测年份晚于 2024 时用 2024 年的值，早于 2012 年留空。",
               _by_year(lambda: ee.ImageCollection("NOAA/VIIRS/DNB/ANNUAL_V22"),
                        lambda i: i.select("average_masked").rename("NTL_VIIRS_Y"), ["NTL_VIIRS_Y"], 2012, 2024),
               mode="nearest", notes="年度产品通常滞后一年发布；2012 年只含 4–12 月。适合年尺度分析。"),
        Source("blackmarble", "NASA 黑色大理石日度 VNP46A2（500 m）", ["NTL_BM"], 500, "NASA/VIIRS/002/VNP46A2",
               "500 m，逐日", "2012-01 至今（近实时）", "nW/(cm²·sr)",
               "Gap_Filled_DNB_BRDF_Corrected_NTL：已校正月光、大气和观测角度，云遮挡处用邻近有效观测补缺。",
               _series(lambda: ee.ImageCollection("NASA/VIIRS/002/VNP46A2"),
                       lambda i: i.select("Gap_Filled_DNB_BRDF_Corrected_NTL").rename("NTL_BM"), ["NTL_BM"]),
               notes="逐日数据量很大：5、10 年窗口约几千景，月度粒度尤其慢，长窗口建议用年度 V2.2。保留渔火、火灾等临时光源，雪面会抬高数值。"),
        Source("viirs", "VIIRS 月度夜光（463 m）", ["NTL_VIIRS"], 463.83, "NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG",
               "约 463 m（15 角秒），逐月", "2014-01 至今", "nW/(cm²·sr)", "avg_rad，已做杂散光校正。",
               _series(lambda: ee.ImageCollection("NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG"),
                       lambda i: i.select("avg_rad").rename("NTL_VIIRS"), ["NTL_VIIRS"]),
               notes="可能有负值或噪声，低亮度区不可靠。"),
        Source("dmsp", "DMSP-OLS 年夜光（1 km）", ["NTL_DMSP"], 927.67, "NOAA/DMSP-OLS/NIGHTTIME_LIGHTS",
               "约 1 km，逐年", "1992–2013", "DN（0–63，无量纲）", "stable_lights（去除火光、云等的稳定灯光）；取最接近观测日的一期。",
               _nearest(lambda: ee.ImageCollection("NOAA/DMSP-OLS/NIGHTTIME_LIGHTS").select("stable_lights"),
                        lambda i: i.select("stable_lights").rename("NTL_DMSP")),
               mode="nearest", notes="只到 2013 年，与 VIIRS 数值不可直接比较；高亮区饱和。"),
    ], "夜间灯光亮度"))

    cats.append(Category("pop", "人口密度", "人类活动", [
        Source("worldpop", "WorldPop 100 m（逐年）", ["POPD_WP"], 100, "WorldPop/GP/100m/pop", "100 m，逐年",
               "2000–2020", "人/km²", "population（每像元人数）÷ 像元面积；取观测年份（超出范围取最近年份）。",
               _worldpop_build, mode="nearest", notes="分国家发布的数据拼接而成；缓冲区内取平均密度。"),
        Source("ghs", "GHSL GHS-POP R2023A（100 m）", ["POPD_GHS"], 100, "JRC/GHSL/P2023A/GHS_POP", "100 m，每 5 年",
               "1975–2030（5 年一期，含预测）", "人/km²", "population_count ÷ 像元面积；取最接近观测日的一期。",
               _nearest(lambda: ee.ImageCollection("JRC/GHSL/P2023A/GHS_POP"),
                        lambda i: _density(i.select("population_count"), "POPD_GHS")),
               mode="nearest", notes="2025 年及以后为预测值。"),
        Source("gpw", "GPW v4.11（1 km）", ["POPD_GPW"], 927.67, "CIESIN/GPWv411/GPW_Population_Count", "约 1 km，每 5 年",
               "2000、2005、2010、2015、2020", "人/km²", "population_count ÷ 像元面积；取最接近观测日的一期。",
               _nearest(lambda: ee.ImageCollection("CIESIN/GPWv411/GPW_Population_Count"),
                        lambda i: _density(i.select("population_count"), "POPD_GPW")),
               mode="nearest", notes="基于行政区人口普查插值，空间细节少。"),
    ], "人口密度（人/km²，由各来源的人口数换算，不同来源可比）"))

    cats.append(Category("landcover", "土地覆盖比例", "土地与地形", [
        Source("worldcover", "ESA WorldCover v200（10 m，2021）", ["BUILT_WC", "TREE_WC", "GRASS_WC", "WATER_WC"], 10,
               "ESA/WorldCover/v200", "10 m", "2021 年（静态）", "比例 0–1（缓冲区内该类像元占比）",
               "Map 分类：建设用地=50、树木=10、草地=30、水体=80；各类转成 0/1 后取缓冲区平均。",
               _static(_wc_img), mode="static", notes="只有 2021 年一期，不分时间窗。"),
        Source("dw", "Dynamic World（10 m，近实时）", ["BUILT_DW", "TREE_DW", "GRASS_DW", "WATER_DW"], 10,
               "GOOGLE/DYNAMICWORLD/V1", "10 m，约 5 天", "2015-06 至今", "概率 0–1",
               "各类概率（built、trees、grass、water）在时间窗内取聚合。", _series(
                   lambda: ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1"), _dw_conv,
                   ["BUILT_DW", "TREE_DW", "GRASS_DW", "WATER_DW"], scene=True),
               scene=True, notes="是分类概率而非面积占比；数据量大，速度慢。"),
    ], "建成区、树木、草地、水体所占比例"))

    cats.append(Category("tree", "树木覆盖率", "土地与地形", [
        Source("hansen", "Hansen 2000 树冠覆盖（30 m）", ["TREEPCT_HANSEN"], 30,
               "UMD/hansen/global_forest_change_2023_v1_11", "30 m", "2000 年（静态）", "%",
               "treecover2000：2000 年树冠覆盖百分比。", _static(
                   lambda: ee.Image("UMD/hansen/global_forest_change_2023_v1_11").select("treecover2000").rename("TREEPCT_HANSEN")),
               mode="static", notes="只反映 2000 年，之后的变化没有体现。"),
        Source("vcf", "MODIS VCF MOD44B（250 m，逐年）", ["TREEPCT_VCF"], 250, "MODIS/061/MOD44B", "250 m，逐年",
               "2000 至今", "%", "Percent_Tree_Cover，取最接近观测日的一年。",
               _nearest(lambda: ee.ImageCollection("MODIS/061/MOD44B"),
                        lambda i: i.select("Percent_Tree_Cover").rename("TREEPCT_VCF")), mode="nearest",
               notes="分辨率较粗，城区小块绿地会被低估。"),
    ], "树冠覆盖百分比"))

    cats.append(Category("dem", "高程与坡度（DEM）", "土地与地形", [
        _dem_source("srtm", "SRTM v3（30 m）", "SRTM", lambda: ee.Image("USGS/SRTMGL1_003").select("elevation"),
                    "30 m", "2000 年获取（静态）", "SRTM 雷达高程；坡度由 ee.Terrain.slope 计算。",
                    "地表模型，含建筑和树冠；覆盖约北纬 60° 至南纬 56°。", "USGS/SRTMGL1_003"),
        _dem_source("nasadem", "NASADEM（30 m）", "NASA", lambda: ee.Image("NASA/NASADEM_HGT/001").select("elevation"),
                    "30 m", "2000 年获取（静态）", "SRTM 的重处理版本，空洞更少；坡度由 ee.Terrain.slope 计算。",
                    "地表模型，含建筑和树冠。", "NASA/NASADEM_HGT/001"),
        _dem_source("cop30", "Copernicus GLO-30（30 m）", "COP", _mosaic_dem("COPERNICUS/DEM/GLO30", "DEM"),
                    "30 m", "2010–2015 年数据（静态）", "TanDEM-X 雷达数字表面模型，瓦片拼接；坡度由 ee.Terrain.slope 计算。",
                    "地表模型（DSM），公认精度较高，山区推荐。", "COPERNICUS/DEM/GLO30"),
        _dem_source("alos", "ALOS AW3D30 v3.2（30 m）", "ALOS", _mosaic_dem("JAXA/ALOS/AW3D30/V3_2", "DSM"),
                    "30 m", "2006–2011 年数据（静态）", "ALOS 光学立体测绘数字表面模型，瓦片拼接。",
                    "地表模型（DSM）。", "JAXA/ALOS/AW3D30/V3_2"),
        _dem_source("merit", "MERIT DEM（约 90 m）", "MERIT", lambda: ee.Image("MERIT/DEM/v1_0_3").select("dem"),
                    "约 90 m（3 角秒）", "静态", "在 SRTM、AW3D30 基础上去除误差（条纹、树高偏差等）。",
                    "分辨率较粗，但已去除植被偏差，适合地形水文分析。", "MERIT/DEM/v1_0_3"),
        _dem_source("fabdem", "FABDEM（30 m，社区数据集）", "FAB", _mosaic_dem("projects/sat-io/open-datasets/FABDEM", None),
                    "30 m", "静态", "在 Copernicus GLO-30 基础上去除建筑与树木高度，更接近裸地高程。",
                    "社区维护的数据集，不是 Google 官方目录；首次使用建议先小批量验证。许可 CC BY-NC-SA 4.0（仅限非商业，"
                    "衍生成果需以相同方式共享）。引用：Hawker 等 (2022), A 30 m global map of elevation with forests and "
                    "buildings removed, Environmental Research Letters。",
                    "projects/sat-io/open-datasets/FABDEM", link="https://gee-community-catalog.org/projects/fabdem/"),
    ], "海拔与坡度（坡度用同一 DEM 计算）"))

    cats.append(Category("urban", "城乡分类（城市化程度）", "区域与城乡", [
        Source("smod", "GHSL 城市化程度 GHS-SMOD R2023A（1 km）", ["SMOD_GHS", "DEGURBA1_GHS"], 1000,
               "JRC/GHSL/P2023A/GHS_SMOD_V2-0", "1 km，每 5 年一期", "1975–2030（5 年一期，2025 年及以后为预测）",
               "分类代码",
               "Degree of Urbanisation 方法分类。SMOD_GHS 为 8 类：30 城市中心、23 密集城区、22 半密集城区、21 郊区/近郊、13 乡村聚落、12 低密度乡村、11 极低密度乡村、10 水体；"
               "DEGURBA1_GHS 为合并的 3 大类：3 城市、2 城镇与半密集区、1 乡村。取与观测年份最接近的一期。",
               _nearest(lambda: ee.ImageCollection("JRC/GHSL/P2023A/GHS_SMOD_V2-0"), _smod_conv),
               mode="nearest",
               labels={"SMOD_GHS": {30: "城市中心", 23: "密集城区", 22: "半密集城区", 21: "郊区或近郊", 13: "乡村聚落",
                                    12: "低密度乡村", 11: "极低密度乡村", 10: "水体"},
                       "DEGURBA1_GHS": {3: "城市", 2: "城镇与半密集区", 1: "乡村"}},
               notes="分类数据：缓冲区内取众数（出现最多的类别），多期窗口也取众数；与 GHSL 人口、建筑数据同源，适合和人口密度配合使用。"),
    ], "城市、城镇、乡村的分类", temporal="mode", spatial="mode"))

    order = list(dict.fromkeys(c.theme for c in cats))
    return sorted(cats, key=lambda c: order.index(c.theme))      # 同主题放在一起（稳定排序）


CATEGORIES = _mk()
for _c in CATEGORIES:                       # 统一标注数据性质（避免逐个来源改参数）
    for _s in _c.sources:
        if _s.gee_id.startswith("ECMWF/ERA5_LAND"):
            _s.origin = "model"
        elif _s.gee_id == "IDAHO_EPSCOR/TERRACLIMATE":
            _s.origin = "blend"
CAT_BY_KEY = {c.key: c for c in CATEGORIES}
SOURCE_BY_KEY = {s.key: s for c in CATEGORIES for s in c.sources}
THEMES = list(dict.fromkeys(c.theme for c in CATEGORIES))


def selected_source(cat_key, settings):
    """读取全局设置里该类别选定的数据源，未设置则用第一个。"""
    cat = CAT_BY_KEY[cat_key]
    key = settings.value(f"gee_sources/{cat_key}", "")
    return SOURCE_BY_KEY.get(key) if key in SOURCE_BY_KEY and SOURCE_BY_KEY[key].category == cat_key else cat.sources[0]


# ---------------------------------------------------------------- 输出字段的中文说明（采集报告用，一句话）
_VI = {"NDVI": "归一化植被指数（−1~1，越大绿度越高）", "EVI": "增强型植被指数（高绿度区不易饱和）",
       "SAVI": "土壤调节植被指数（裸土多的区域更可靠）", "FVC": "植被覆盖度（0~1，由 NDVI 换算）",
       "NDWI": "归一化水体指数（越大越像水体或湿润）", "MNDWI": "改进的水体指数（城区水体更突出）"}
_SENSOR = {"MOD": "MODIS 500 m", "LS": "Landsat 30 m", "S2": "Sentinel-2 10 m"}
FIELD_DESC = {}
for _k, _v in _VI.items():
    for _s, _n in _SENSOR.items():
        FIELD_DESC[f"{_k}_{_s}"] = f"{_v}，{_n}"
for _p, _n in (("MYD8", "Aqua 8 天"), ("MOD8", "Terra 8 天"), ("MYD", "Aqua 逐日"), ("MOD", "Terra 逐日")):
    FIELD_DESC[f"LSTd_{_p}"] = f"白天地表温度（℃），MODIS {_n}"
    FIELD_DESC[f"LSTn_{_p}"] = f"夜间地表温度（℃），MODIS {_n}"
for _src, _n in (("ERA5", "ERA5-Land"), ("ERA5M", "ERA5-Land 月聚合")):
    FIELD_DESC[f"TAVG_{_src}"] = f"近地面平均气温（℃），{_n}（模式）"
    FIELD_DESC[f"TMAX_{_src}"] = f"近地面最高气温（℃），{_n}（模式）"
    FIELD_DESC[f"TMIN_{_src}"] = f"近地面最低气温（℃），{_n}（模式）"
FIELD_DESC.update({
    "LSTd_LS": "白天地表温度（℃），Landsat 30 m（约 10:30 一景）", "SKT_ERA5": "皮肤温度即地表温度（℃），ERA5-Land（模式）",
    "TMAX_TC": "月最高气温（℃），TerraClimate（融合）", "TMIN_TC": "月最低气温（℃），TerraClimate（融合）",
    "PRCP_CHIRPS": "降水（mm/天，窗口内日均），CHIRPS", "PRCP_ERA5": "降水（mm/天，窗口内日均），ERA5-Land（模式）",
    "PRCP_ERA5M": "降水（mm/月，窗口内月均），ERA5-Land 月聚合（模式）", "PRCP_TC": "降水（mm/月，窗口内月均），TerraClimate（融合）",
    "SRAD_ERA5": "向下短波辐射即地表太阳总辐射（W/m²，日均），ERA5-Land（模式）", "SRAD_TC": "向下短波辐射（W/m²，月均），TerraClimate（融合）",
    "NTL_VIIRS_Y": "夜间灯光亮度（nW/cm²/sr），VIIRS 年度", "NTL_BM": "夜间灯光亮度（nW/cm²/sr），NASA 黑色大理石日度",
    "NTL_VIIRS": "夜间灯光亮度（nW/cm²/sr），VIIRS 月度", "NTL_DMSP": "夜间灯光（DN 0–63，无量纲），DMSP 年度，只到 2013 年",
    "POPD_WP": "人口密度（人/km²），WorldPop", "POPD_GHS": "人口密度（人/km²），GHSL", "POPD_GPW": "人口密度（人/km²），GPW v4",
    "BUILT_WC": "建成区占比（0–1），ESA WorldCover 2021", "TREE_WC": "树木占比（0–1），ESA WorldCover 2021",
    "GRASS_WC": "草地占比（0–1），ESA WorldCover 2021", "WATER_WC": "水体占比（0–1），ESA WorldCover 2021",
    "BUILT_DW": "建成区概率（0–1），Dynamic World", "TREE_DW": "树木概率（0–1），Dynamic World",
    "GRASS_DW": "草地概率（0–1），Dynamic World", "WATER_DW": "水体概率（0–1），Dynamic World",
    "TREEPCT_HANSEN": "树冠覆盖率（%），Hansen 2000 年", "TREEPCT_VCF": "树木覆盖率（%），MODIS VCF 逐年",
    "SMOD_GHS": "城市化程度 7 类代码（30 城市中心…10 水体），GHS-SMOD", "DEGURBA1_GHS": "城市化程度 3 类代码（3 城市、2 城镇与半密集区、1 乡村）",
})
for _p, _n in (("SRTM", "SRTM"), ("NASA", "NASADEM"), ("COP", "Copernicus GLO-30"), ("ALOS", "ALOS AW3D30"), ("MERIT", "MERIT"), ("FAB", "FABDEM")):
    FIELD_DESC[f"ELEV_{_p}"] = f"海拔（m），{_n}"
    FIELD_DESC[f"SLOPE_{_p}"] = f"坡度（°），{_n}"
FIELD_DESC.update({"CN_PROV": "点所在省级行政区名称（本地县级矢量）", "CN_CITY": "点所在地级市名称（直辖市取市名，省直辖县级写「省直辖县级行政区划」）",
                   "CN_COUNTY": "点所在县（区、县级市）名称", "CN_COUNTY_GB": "县级行政区划代码（国标 gb，9 位）"})


def describe(col):
    """输出列名 → 一句话说明；列名可带窗口后缀（_cur、_y3 …）或「_名称」后缀。找不到返回空串。"""
    tail = "（名称）" if col.endswith("_名称") else ""
    base = col[:-3] if tail else col
    best = max((k for k in FIELD_DESC if base == k or base.startswith(k + "_")), key=len, default=None)
    return (FIELD_DESC[best] + (tail and "，中文名称")) if best else ""
