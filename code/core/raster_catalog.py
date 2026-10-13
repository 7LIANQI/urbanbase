# -*- coding: utf-8 -*-
"""栅格数据目录：每个「数据序列」一个文件夹 + 一个 dataset.json，扫描文件夹即得目录，无需维护总清单。

目录约定（<根目录> 下任意层级放文件夹即可，推荐按类别分）:
    <根目录>/<类别>/<数据序列id>/dataset.json        元数据（可用「数据目录」工具编辑）
    <根目录>/<类别>/<数据序列id>/[任意子文件夹/]<id>_<日期>.tif
文件名规则（日期位数由 temporal 决定）:
    static: <id>.tif        year: <id>_2020.tif        month: <id>_202007.tif        day: <id>_20200715.tif
一个「数据序列」= 一种产品的一个变量在一种时间尺度上的一组文件。同一数据有年、月两种尺度时，
就是两个数据序列（如 ndvi_mod_month、ndvi_mod_year），用 product / variable 字段把它们关联起来。
"""
import json
import re
from dataclasses import asdict, dataclass, field, fields
from datetime import date, timedelta
from pathlib import Path

TEMPORAL = {"static": "静态", "year": "年", "month": "月", "day": "日"}
_DATE_RE = {"year": r"(\d{4})", "month": r"(\d{4})(\d{2})", "day": r"(\d{4})(\d{2})(\d{2})"}
MANIFEST = "dataset.json"
RASTER_EXT = (".tif", ".tiff")
VECTOR_EXT = (".geojson", ".gpkg", ".shp")
DATA_EXT = RASTER_EXT + (".nc",) + VECTOR_EXT   # 目录扫描认的数据文件；.nc 多为尚未转 COG 的原始数据（不做文件头检查）


@dataclass
class Series:
    id: str = ""
    name: str = ""
    category: str = "other"          # 与 GEE 指标类别 key 对应（veg、lst、dem…），其余用 other
    product: str = ""                # 产品，如 MOD09A1
    variable: str = ""               # 变量，如 NDVI
    unit: str = ""
    temporal: str = "static"         # static / year / month / day
    start: str = ""                  # 声明的覆盖起点：yyyy、yyyy-mm 或 yyyy-mm-dd
    end: str = ""
    check_gaps: bool = True          # 是否检查区间内缺期（不规则间隔的数据请关掉）
    kind: str = "raster"             # raster 栅格 / vector 矢量（如行政区划面）
    attributes: dict = field(default_factory=dict)   # 矢量用：{输出列: 来源字段表达式}，如 {"县": "name", "省代码": "gb[3:5]"}
    nearest_m: float = 0.0           # 矢量用：点不在任何面内时，取最近面的最大距离（米）；0 表示不启用
    categorical: bool = False        # 分类数据（如植被类型）：提取时取众数，不求平均
    multi_grid: bool = False         # 允许网格变化：不同时期的文件分辨率/范围不同时（如 10 km 与 1 km 拼成一个序列）
    crs: str = ""                    # 如 EPSG:4326，留空则不检查
    resolution: str = ""             # 文字说明，如 "1 km"
    nodata: str = ""                 # 留空则不检查；提取时优先于文件自带的无效值（填 none 表示不屏蔽任何值）
    dtype: str = ""                  # 如 float32，留空则不检查
    scale: float = 1.0
    offset: float = 0.0
    source: str = ""
    link: str = ""
    notes: str = ""
    folder: Path = field(default=None, repr=False, compare=False)    # 不写入 json

    def to_dict(self):
        d = asdict(self)
        d.pop("folder")
        return {"schema": 1, **d}

    def save(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / MANIFEST).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, folder):
        raw = json.loads((Path(folder) / MANIFEST).read_text(encoding="utf-8"))
        names = {f.name for f in fields(cls)} - {"folder"}
        s = cls(**{k: v for k, v in raw.items() if k in names})
        s.folder = Path(folder)
        return s

    # ---------- 文件名 ----------
    def filename(self, d):
        """d: (年, 月, 日) 元组（static 传空元组）。返回规范文件名。"""
        parts = {"static": "", "year": "_{:04d}", "month": "_{:04d}{:02d}", "day": "_{:04d}{:02d}{:02d}"}[self.temporal]
        return self.id + parts.format(*d) + ".tif"

    def parse(self, name):
        """规范文件名 → 日期键（static 为 ""，其余为 YYYY / YYYYMM / YYYYMMDD）；不符合返回 None。"""
        stem = Path(name).stem
        if self.temporal == "static":
            return "" if stem == self.id else None
        m = re.fullmatch(re.escape(self.id) + "_" + _DATE_RE[self.temporal], stem)
        return "".join(m.groups()) if m else None

    def files(self):
        """{日期键: [路径...]}，只含符合命名规则的文件（同键多个说明重复）。"""
        out = {}
        for p in sorted(self.folder.rglob("*")):
            if p.suffix.lower() in DATA_EXT and not p.name.startswith("._"):
                k = self.parse(p.name)
                if k is not None:
                    out.setdefault(k, []).append(p)
        return out

    def stray_files(self):
        """文件夹里命名不符合规则的栅格文件。"""
        return [p for p in sorted(self.folder.rglob("*")) if p.suffix.lower() in DATA_EXT
                and not p.name.startswith("._") and self.parse(p.name) is None]

    def files_between(self, start, end):
        """取日期落在 [start, end) 内的文件（start、end 为 date）。static 返回唯一文件。"""
        out = []
        for k, ps in sorted(self.files().items()):
            if self.temporal == "static" or start <= key_to_date(k) < end:
                out.append(ps[0])
        return out


# ---------- 日期工具 ----------
def key_to_date(k):
    return date(int(k[:4]), int(k[4:6]) if len(k) >= 6 else 1, int(k[6:8]) if len(k) == 8 else 1)


def parse_bound(text, end=False):
    """'2020' / '2020-07' / '2020-07-15' → date；end=True 时取该期的最后一天。失败返回 None。"""
    m = re.fullmatch(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", (text or "").strip())
    if not m:
        return None
    y, mo, d = int(m.group(1)), m.group(2), m.group(3)
    try:
        if d:
            return date(y, int(mo), int(d))
        if mo:
            first = date(y, int(mo), 1)
            return (date(y + (int(mo) == 12), int(mo) % 12 + 1, 1) - timedelta(days=1)) if end else first
        return date(y, 12, 31) if end else date(y, 1, 1)
    except ValueError:
        return None


def expected_keys(s):
    """按声明的起止与时间尺度，列出应有的日期键。"""
    a, b = parse_bound(s.start), parse_bound(s.end, end=True)
    if s.temporal == "static" or a is None or b is None or a > b:
        return []
    keys = []
    if s.temporal == "year":
        keys = [f"{y:04d}" for y in range(a.year, b.year + 1)]
    elif s.temporal == "month":
        y, m = a.year, a.month
        while (y, m) <= (b.year, b.month):
            keys.append(f"{y:04d}{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    else:
        d = a
        while d <= b:
            keys.append(d.strftime("%Y%m%d"))
            d += timedelta(days=1)
    return keys


def actual_range(s):
    ks = sorted(s.files())
    return (ks[0], ks[-1]) if ks and ks[0] else (None, None)


def fmt_key(k):
    return "" if not k else (k if len(k) == 4 else f"{k[:4]}-{k[4:6]}" + (f"-{k[6:8]}" if len(k) == 8 else ""))


# ---------- 加载 ----------
def load_all(root):
    """扫描根目录下所有 dataset.json。返回 (序列列表, 读取失败信息列表)。"""
    series, errors = [], []
    for p in sorted(Path(root).rglob(MANIFEST)):
        try:
            series.append(Series.load(p.parent))
        except Exception as e:
            errors.append((p, str(e)))
    return series, errors


# ---------- 一致性检查 ----------
@dataclass
class Issue:
    level: str       # error / warn / info
    series: str
    path: str
    message: str


def check(root, deep=False, progress=lambda i, n: None, stop=None):
    """检查目录与文件的一致性。deep=True 时读取每个文件的头信息（较慢）。"""
    issues = []
    add = lambda lv, sid, path, msg: issues.append(Issue(lv, sid, str(path or ""), msg))
    series, errors = load_all(root)
    for p, e in errors:
        add("error", "", p, f"dataset.json 无法读取：{e}")
    seen = {}
    for s in series:
        if s.id in seen:
            add("error", s.id, s.folder, f"数据序列 id 重复（另一个在 {seen[s.id]}）")
        seen[s.id] = s.folder
    for i, s in enumerate(series):
        if stop is not None and stop.is_set():
            break
        progress(i, len(series))
        _check_series(s, deep, add)
    progress(len(series), len(series))
    return issues


def _check_vector(s, files, add):
    """矢量序列：文件可读、有坐标系、有要素；属性映射里用到的字段都存在。"""
    if not files:
        add("warn", s.id, s.folder, "没有找到矢量文件")
        return
    try:
        import geopandas as gpd
        g = gpd.read_file(next(iter(files.values()))[0])
    except Exception as e:
        add("error", s.id, s.folder, f"矢量文件无法读取：{e}")
        return
    if g.crs is None:
        add("error", s.id, s.folder, "矢量文件没有坐标系")
    if len(g) == 0:
        add("error", s.id, s.folder, "矢量文件里没有要素")
    import re as _re
    for col, expr in s.attributes.items():
        fld = _re.split(r"[\[|]", expr)[0].strip()
        t = _re.search(r"\|\s*table:(\w+)", expr)
        if t and not (s.folder / f"lookup_{t.group(1)}.csv").exists():
            add("error", s.id, s.folder, f"属性映射「{col} ← {expr}」需要查表文件 lookup_{t.group(1)}.csv，但文件夹里没有")
        if fld not in g.columns:
            add("error", s.id, s.folder, f"属性映射「{col} ← {expr}」用到的字段 {fld} 不存在（文件字段：{', '.join(map(str, g.columns))}）")
    bad = int((~g.geom_type.isin(["Polygon", "MultiPolygon"])).sum())
    if bad:
        add("info", s.id, s.folder, f"有 {bad} 个要素不是面（线或点），做「点在面内」匹配时会被忽略")


def _check_series(s, deep, add):
    sid = s.id or str(s.folder)
    if not s.id or not re.fullmatch(r"[A-Za-z0-9_\-]+", s.id):
        add("error", sid, s.folder, "id 为空或含有不允许的字符（只能用字母、数字、下划线、连字符）")
        return
    if s.temporal not in TEMPORAL:
        add("error", sid, s.folder, f"时间尺度 {s.temporal!r} 无效，应为 static / year / month / day")
        return
    if s.temporal != "static":
        a, b = parse_bound(s.start), parse_bound(s.end, end=True)
        if a is None or b is None:
            add("error", sid, s.folder, "起止时间未填或格式不对（应为 yyyy、yyyy-mm 或 yyyy-mm-dd）")
        elif a > b:
            add("error", sid, s.folder, "起始时间晚于结束时间")
    files = s.files()
    for k, ps in files.items():
        if len(ps) > 1:
            add("error", sid, ps[1], f"同一日期 {fmt_key(k) or '静态'} 有 {len(ps)} 个文件：" + "; ".join(p.name for p in ps))
    for p in s.stray_files():
        add("warn", sid, p, f"文件名不符合规则（应为 {s.filename((2000, 1, 1)).replace('2000', 'YYYY').replace('01', 'MM', 1) if s.temporal != 'static' else s.id + '.tif'} 形式）")
    if not files:
        add("warn", sid, s.folder, "没有找到任何符合命名规则的栅格文件")
        return
    exp = set(expected_keys(s))
    got = set(files)
    if s.temporal != "static" and exp:
        extra = sorted(got - exp)
        if extra:
            add("warn", sid, s.folder, f"{len(extra)} 个文件在声明的时间范围之外（如 {fmt_key(extra[0])}）：请扩大声明的范围或移走文件")
        if s.check_gaps:
            miss = sorted(exp - got)
            if miss:
                add("warn", sid, s.folder, f"声明范围内缺 {len(miss)} 期：" + "、".join(fmt_key(k) for k in miss[:8]) + (" …" if len(miss) > 8 else ""))
        lo, hi = actual_range(s)
        if lo and (fmt_key(lo) > fmt_key(min(exp)) or fmt_key(hi) < fmt_key(max(exp))):
            add("info", sid, s.folder, f"实际范围 {fmt_key(lo)} ~ {fmt_key(hi)} 小于声明的 {s.start} ~ {s.end}")
    if s.kind == "vector":
        _check_vector(s, files, add)
        return
    if deep:
        _check_headers(s, files, add)


def _check_headers(s, files, add):
    import rasterio
    ref = None
    grids = set()
    for k, ps in sorted(files.items()):
        p = ps[0]
        if p.suffix.lower() == ".nc":          # 原始 NetCDF：不读文件头，转 COG 后再做深度检查
            continue
        try:
            with rasterio.open(p) as ds:
                crs = ds.crs.to_string() if ds.crs else ""
                info = (crs, ds.dtypes[0], ds.width, ds.height, tuple(round(v, 9) for v in ds.transform[:6]))
                nod = ds.nodata
                cog = bool(ds.profile.get("tiled")) and bool(ds.overviews(1))
        except Exception as e:
            add("error", s.id, p, f"无法打开：{e}")
            continue
        if s.crs and crs and crs.replace("EPSG:", "") != s.crs.replace("EPSG:", ""):
            add("error", s.id, p, f"坐标系 {crs} 与声明的 {s.crs} 不一致")
        if not crs:
            add("error", s.id, p, "文件没有坐标系")
        if s.dtype and info[1] != s.dtype:
            add("warn", s.id, p, f"数据类型 {info[1]} 与声明的 {s.dtype} 不一致")
        if s.nodata not in ("", "none") and (nod is None or abs(float(nod) - float(s.nodata)) > 1e-6 * max(1.0, abs(float(s.nodata)))):
            add("warn", s.id, p, f"无效值 {nod} 与声明的 {s.nodata} 不一致")
        if not cog:
            add("info", s.id, p, "不是 COG（没有分块或缩略图），读取会较慢；可用「栅格转 COG」转换")
        grids.add(info[2:])
        if ref is None:
            ref = (k, info)
        elif info[2:] != ref[1][2:] and not s.multi_grid:
            add("error", s.id, p, f"尺寸或空间范围与 {fmt_key(ref[0]) or '首个文件'} 不一致（同一数据序列的网格应相同；若是有意混合不同分辨率，请打开「允许网格变化」）")
    if s.multi_grid and len(grids) > 1:
        add("info", s.id, s.folder, f"该序列包含 {len(grids)} 种不同的网格（已允许网格变化）；跨时期使用时注意分辨率差异")
