# -*- coding: utf-8 -*-
"""整理「完整数据」文件夹：按数据序列重命名、归类，并写入 dataset.json，所有改动可回滚，不删除任何文件。

目标结构（与「栅格数据目录」工具的约定一致）:
    <根>/<类别>/<数据序列id>/<id>_<日期>.<ext>   + dataset.json
    <根>/_压缩包备份/   原 .rar 压缩包（内容已有解压版本，原样保留）
    <根>/_整理记录/     整理记录 csv（旧路径→新路径）、回滚.py、数据清单.csv、README.md、杂项

用法:
    python scripts/organize_env_data.py "<根目录>"             # 只生成计划并打印摘要（不改动任何文件）
    python scripts/organize_env_data.py "<根目录>" --execute   # 执行
"""
import argparse
import csv
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.raster_catalog import Series  # noqa: E402

JUNK = ("._", ".DS_Store", "~$")


def is_junk(name):
    return name.startswith(JUNK) or name == ".DS_Store"


# ---------------------------------------------------------------- 数据序列定义
def series_defs():
    """序列 id → 元数据（类别、名称、时间尺度、说明）。"""
    D = {}

    def add(sid, cat, name, temporal, **kw):
        D[sid] = dict(id=sid, category=cat, name=name, temporal=temporal, **kw)

    add("tmp_cn1km", "t2m", "气温（月均，约 1 km，逐年文件）", "year", variable="tmp", resolution="约 0.0083°（≈1 km）",
        notes="原文件 tmp_YYYY.nc；每个文件含 12 个月（time=1..12），网格 5146×7849，纬度由北向南。按历史记录单位为 0.1 ℃，入库前需 ÷10，请先确认。坐标系未写入文件，按经纬度（WGS84）推定。")
    add("pre_cn1km", "precip", "降水（月累计，约 1 km，逐年文件）", "year", variable="pre", resolution="约 0.0083°（≈1 km）",
        notes="原文件 pre_YYYY.nc；每个文件含 12 个月，网格与气温一致。单位与缩放系数未在文件中说明，入库前请确认。坐标系未写入文件，按经纬度（WGS84）推定。注意：1996 年文件不完整（11、12 月全为 0，原压缩包也不完整），2012 年之后的研究不受影响。")
    add("rhum_cmfd", "rhum", "相对湿度（CMFD 年均，0.1°）", "static", variable="rhum", unit="%", product="CMFD V0200 (ITPCAS)",
        resolution="0.1°", notes="单个文件含 1951–2024 共 74 个年值（time 维）。原文件 rhum_CMFD_V0200_B-01_01yr_010deg_1951-2024.nc。")
    add("sd_cn005", "sunshine", "日照时数（日值，0.05°）", "day", variable="SD", resolution="0.05°", crs="EPSG:4326",
        notes="原文件 SDYYYYMMDD.nc，按年份子文件夹存放。部分日期在源数据中缺失（见检查结果），压缩包与解压文件数一致。")
    add("gdp_cn1km", "gdp", "GDP 空间分布（1 km）", "year", variable="GDP", resolution="1 km",
        check_gaps=False, notes="年份不连续（2010、2015、2020–2024）。投影为自定义 Krasovsky_1940_Albers（非 EPSG），int32。附带 .tfw/.aux.xml/.ovr 等辅助文件一并保留。")
    add("forestcover_cn1km", "forest", "中国森林覆盖（逐年，1 km）", "year", variable="ForestCover", product="China Forest Dataset v1.0",
        resolution="约 1226 m", notes="原文件 China-ForestCover_1km_YYYY_v1.0.tif；WGS_1984_Albers 投影，uint8，无效值 0。")
    add("pft_cn1km", "forest", "中国植被功能型 PFT（逐年，1 km）", "year", variable="PFT", product="China Forest Dataset v1.0",
        resolution="约 1226 m", notes="原文件 China-PFTs_1km_YYYY_v1.0.tif；分类说明见 PFT_分类说明.xlsx。")
    for kind, cn in (("gain", "增加"), ("loss", "损失")):
        for part, pn in (("duration", "持续年数"), ("startyear", "起始年份")):
            add(f"forest{kind}_{part}_cn1km", "forest", f"中国森林{cn}（{pn}，1 km）", "static", variable=f"Forest{kind.title()}_{part}",
                product="China Forest Dataset v1.0", resolution="约 1226 m",
                notes=f"原文件 China-ForestChange_{kind.title()}_{part.title() if part == 'duration' else 'StartYear'}_1km_v1.0.tif。")
    return D


# ---------------------------------------------------------------- 计划
class Plan:
    def __init__(self, root):
        self.root = Path(root)
        self.moves = []            # (src, dst, series_id, kind)
        self.defs = series_defs()
        self.series_files = defaultdict(list)

    def move(self, src, dst, sid, kind="data"):
        self.moves.append((Path(src), Path(dst), sid, kind))
        if kind == "data" and sid:
            self.series_files[sid].append(Path(dst))

    def dst(self, sid, name):
        return self.root / self.defs[sid]["category"] / sid / name


def build(root):
    P = Plan(root)
    R = P.root
    bak = R / "_压缩包备份"
    misc = R / "_整理记录" / "杂项"

    # ---- 气温、降水：tmp_YYYY.nc / pre_YYYY.nc；rar → 备份
    for folder, pre, sid in (("气温", "tmp", "tmp_cn1km"), ("降水", "pre", "pre_cn1km")):
        for f in sorted((R / folder).iterdir()):
            m = re.fullmatch(pre + r"_(\d{4})\.(nc|rar)", f.name)
            if m and m.group(2) == "nc":
                P.move(f, P.dst(sid, f"{sid}_{m.group(1)}.nc"), sid)
            elif m:
                P.move(f, bak / P.defs[sid]["category"] / f.name, None, "backup")
    # ---- 湿度
    for f in (R / "湿度").iterdir():
        if f.suffix == ".nc" and not is_junk(f.name):
            P.move(f, P.dst("rhum_cmfd", "rhum_cmfd.nc"), "rhum_cmfd")
    # ---- 日照：SDYYYY/ 目录 + rar
    for f in sorted((R / "日照").iterdir()):
        if is_junk(f.name):
            continue
        if f.suffix == ".rar":
            P.move(f, bak / "sunshine" / f.name, None, "backup")
        elif f.is_dir() and re.fullmatch(r"SD\d{4}", f.name):
            y = f.name[2:]
            for g in sorted(f.iterdir()):
                m = re.fullmatch(r"SD(\d{8})\.nc", g.name)
                if m:
                    P.move(g, P.dst("sd_cn005", f"{y}/sd_cn005_{m.group(1)}.nc"), "sd_cn005")
    # ---- GDP：GDPYYYY/GDPYYYY.* （含辅助文件）
    for d in sorted((R / "GDP").iterdir()):
        m = re.fullmatch(r"GDP(\d{4})", d.name)
        if m and d.is_dir():
            for g in sorted(d.iterdir()):
                if is_junk(g.name):
                    continue
                suffix = g.name[len(d.name):]                      # 如 .tif / .tif.ovr / .tfw
                P.move(g, P.dst("gdp_cn1km", f"gdp_cn1km_{m.group(1)}{suffix}"), "gdp_cn1km")
    # ---- 森林
    F = R / "植被类型" / "China_Forest_Dataset_v1.0"
    for g in sorted((F / "1_Forest_Cover_Annual_1981-2023").iterdir()):
        m = re.fullmatch(r"China-ForestCover_1km_(\d{4})_v1\.0\.tif", g.name)
        if m:
            P.move(g, P.dst("forestcover_cn1km", f"forestcover_cn1km_{m.group(1)}.tif"), "forestcover_cn1km")
    for g in sorted((F / "2_PFT_Annual_1981-2023").iterdir()):
        m = re.fullmatch(r"China-PFTs_1km_(\d{4})_v1\.0\.tif", g.name)
        if m:
            P.move(g, P.dst("pft_cn1km", f"pft_cn1km_{m.group(1)}.tif"), "pft_cn1km")
        elif g.name == "PFT_Classification.xlsx":
            P.move(g, P.dst("pft_cn1km", "PFT_分类说明.xlsx"), "pft_cn1km", "doc")
    for sub, kind in (("3_Forest_Change_Gain", "gain"), ("4_Forest_Change_Loss", "loss")):
        for g in sorted((F / sub).iterdir()):
            m = re.fullmatch(r"China-ForestChange_(Gain|Loss)_(Duration|StartYear)_1km_v1\.0\.tif", g.name)
            if m:
                sid = f"forest{kind}_{m.group(2).lower()}_cn1km"
                P.move(g, P.dst(sid, f"{sid}.tif"), sid)
    # README.docx 正被 Word 打开时不移动（关闭后可手动放进 forest/ 或再运行本脚本）
    if (F / "README.docx").exists() and not os.environ.get("SKIP_README_MOVE", "1") == "1":
        P.move(F / "README.docx", R / "forest" / "README_China_Forest_Dataset_v1.0.docx", None, "doc")
    # ---- 空气污染：CHAP_<污染物>_<Y1K|Y10K>_<年>_<版本>.nc
    for g in sorted((R / "空气污染").iterdir()):
        if is_junk(g.name):
            continue
        m = re.fullmatch(r"(E?CHAP)_([A-Za-z0-9.]+?)_Y(\d+)K_(\d{4})_(V\d+)\.nc", g.name)
        if not m:
            print("⚠️ 未识别的文件，保持原位:", g.name)
            continue
        fam, pol, km, year, ver = m.groups()
        sid = f"{fam.lower()}_{pol.lower().replace('.', '')}_{km}km"
        if sid not in P.defs:
            P.defs[sid] = dict(id=sid, category="airq", temporal="year", variable=pol, resolution=f"{km} km",
                               name=f"{'中国高分辨率空气污染' if fam == 'CHAP' else '空气污染化学组分'} {pol}（年均，{km} km）",
                               product=fam, versions={}, notes="")
        P.defs[sid]["versions"].setdefault(ver, []).append(int(year))
        P.move(g, P.dst(sid, f"{sid}_{year}.nc"), sid)
    for sid, d in P.defs.items():                     # 把原版本号写进说明（文件名里不再保留）
        if d.get("versions"):
            d["notes"] = "原文件名 " + d["product"] + "_" + d["variable"] + "_Y" + d["resolution"].split()[0] + "K_<年>_<版本>.nc；版本：" + \
                "；".join(f"{v}（{min(ys)}–{max(ys)}）" for v, ys in sorted(d["versions"].items()))
    return P


def validate(P):
    dsts = [m[1] for m in P.moves]
    low = [str(d).lower() for d in dsts]
    assert len(set(low)) == len(low), "目标路径重复（含大小写）"
    for s, d, *_ in P.moves:
        assert s.exists(), f"源不存在 {s}"
        assert not d.exists(), f"目标已存在 {d}"


# ---------------------------------------------------------------- 执行
def companion(path):
    return path.with_name("._" + path.name)


def execute(P):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = P.root / "_整理记录"
    (log_dir / "杂项").mkdir(parents=True, exist_ok=True)
    rows = []
    for src, dst, sid, kind in P.moves:
        dst.parent.mkdir(parents=True, exist_ok=True)
        size = src.stat().st_size
        os.rename(src, dst)
        rows.append((str(src.relative_to(P.root)), str(dst.relative_to(P.root)), sid or "", kind, size))
        c = companion(src)
        if c.exists():                                    # macOS 在 exFAT 上的 ._ 伴随文件一起移动
            os.rename(c, companion(dst))
            rows.append((str(c.relative_to(P.root)), str(companion(dst).relative_to(P.root)), sid or "", "appledouble", c.stat().st_size if companion(dst).exists() else 0))
    # 旧目录里只剩杂项文件的，杂项移到记录目录，空目录移除
    leftovers = []
    for old in ("气温", "降水", "湿度", "日照", "GDP", "植被类型", "空气污染"):
        base = P.root / old
        for dp, dns, fns in os.walk(base, topdown=False):
            dpp = Path(dp)
            for fn in fns:
                if is_junk(fn):
                    tgt = log_dir / "杂项" / f"{old}__{'__'.join(dpp.relative_to(base).parts)}__{fn}".replace("____", "__")
                    n = 1
                    while tgt.exists():
                        tgt = tgt.with_name(tgt.name + f".{n}")
                        n += 1
                    try:
                        os.rename(dpp / fn, tgt)
                        rows.append((str((dpp / fn).relative_to(P.root)), str(tgt.relative_to(P.root)), "", "junk", 0))
                    except FileNotFoundError:      # 伴随文件已随主文件一起移走
                        pass
            try:
                dpp.rmdir()
                leftovers.append(str(dpp.relative_to(P.root)))
            except OSError:
                pass
    for name in ("._气温", "._降水", "._湿度", "._日照", "._GDP", "._植被类型", "._空气污染"):
        f = P.root / name
        if f.exists():
            try:
                os.rename(f, log_dir / "杂项" / name)
                rows.append((name, str((log_dir / "杂项" / name).relative_to(P.root)), "", "junk", 0))
            except FileNotFoundError:
                pass

    csv_path = log_dir / f"整理记录_{stamp}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["旧路径", "新路径", "数据序列", "类型", "字节数"])
        w.writerows(rows)
    (log_dir / "回滚.py").write_text(ROLLBACK, encoding="utf-8")
    write_manifests(P, log_dir)
    return csv_path, len(rows), leftovers


ROLLBACK = '''# -*- coding: utf-8 -*-
"""回滚：按整理记录 csv 把文件移回原位置。用法: python 回滚.py 整理记录_xxx.csv （在本文件所在的 _整理记录 目录里运行）"""
import csv, os, sys
from pathlib import Path
root = Path(__file__).resolve().parent.parent
rows = list(csv.reader(open(sys.argv[1], encoding="utf-8-sig")))[1:]
for old, new, *_ in reversed(rows):
    s, d = root / new, root / old
    if s.exists():
        d.parent.mkdir(parents=True, exist_ok=True)
        os.rename(s, d)
print("已回滚", len(rows), "条（新建的 dataset.json、README、数据清单不会被删除）")
'''


def write_manifests(P, log_dir):
    inv = []
    for sid, d in sorted(P.defs.items()):
        files = [f for f in P.series_files.get(sid, []) if f.suffix.lower() in (".nc", ".tif", ".tiff")]
        if not files:
            continue
        folder = P.root / d["category"] / sid
        keys = sorted(re.findall(r"_(\d{4}(?:\d{2})?(?:\d{2})?)\.(?:nc|tif)$", f.name)[0] for f in files if re.search(r"_(\d{4}(?:\d{2})?(?:\d{2})?)\.(?:nc|tif)$", f.name))
        s = Series(id=sid, name=d["name"], category=d["category"], product=d.get("product", ""), variable=d.get("variable", ""),
                   unit=d.get("unit", ""), temporal=d["temporal"], crs=d.get("crs", ""), resolution=d.get("resolution", ""),
                   check_gaps=d.get("check_gaps", True), notes=d.get("notes", ""), folder=folder)
        if d["temporal"] != "static" and keys:
            fmt = lambda k: k if len(k) == 4 else (f"{k[:4]}-{k[4:6]}" if len(k) == 6 else f"{k[:4]}-{k[4:6]}-{k[6:8]}")
            s.start, s.end = fmt(keys[0]), fmt(keys[-1])
        s.save()
        total = sum(f.stat().st_size for f in files if f.exists())
        inv.append((d["category"], sid, d["name"], len(files), s.start, s.end, round(total / 1e9, 2), d.get("notes", "")))
    with open(log_dir / "数据清单.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["类别", "数据序列id", "名称", "文件数", "起始", "结束", "大小(GB)", "说明"])
        w.writerows(inv)
    lines = ["# 环境数据整理说明", "", f"整理时间：{datetime.now():%Y-%m-%d %H:%M}", "",
             "目录结构：`<类别>/<数据序列id>/<id>_<日期>.<ext>`，每个数据序列文件夹里有 `dataset.json`（可用「栅格数据目录」工具编辑和检查）。",
             "原 `.rar` 压缩包保存在 `_压缩包备份/`；所有改动的新旧路径见 `_整理记录/整理记录_*.csv`，需要时用 `_整理记录/回滚.py` 恢复。", "",
             "| 类别 | 数据序列 | 名称 | 文件数 | 起止 | 大小(GB) |", "|---|---|---|---|---|---|"]
    lines += [f"| {c} | {i} | {n} | {k} | {a}~{b} | {g} |" for c, i, n, k, a, b, g, _ in inv]
    (log_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


CHAP_VER = {"co_10km": "V1", "co_1km": "V2", "no2_10km": "V1", "no2_1km": "V2", "o3_1km": "V3", "pm1_1km": "V3",
            "pm10_1km": "V4", "pm25_1km": "V4", "so2_10km": "V1", "so2_1km": "V2",
            "cl_1km": "V1", "nh4_1km": "V1", "no3_1km": "V1", "so4_1km": "V1"}
POLL = {"pm25": "PM2.5"}


def old_name(sid, rel):
    """新位置（相对 <类别>/<sid>/）→ 旧位置（相对根）。仅用于补救/核对。"""
    base = Path(rel).name
    y = re.search(r"_(\d{4})", base)
    y = y.group(1) if y else ""
    if sid == "tmp_cn1km":
        return f"气温/tmp_{y}.nc"
    if sid == "pre_cn1km":
        return f"降水/pre_{y}.nc"
    if sid == "rhum_cmfd":
        return "湿度/rhum_CMFD_V0200_B-01_01yr_010deg_1951-2024.nc"
    if sid == "sd_cn005":
        return f"日照/SD{y}/SD{base.split('_')[-1]}"
    if sid == "gdp_cn1km":
        return f"GDP/GDP{y}/GDP{y}{base[len('gdp_cn1km_' + y):]}"
    d = "植被类型/China_Forest_Dataset_v1.0/"
    if sid == "forestcover_cn1km":
        return f"{d}1_Forest_Cover_Annual_1981-2023/China-ForestCover_1km_{y}_v1.0.tif"
    if sid == "pft_cn1km":
        return f"{d}2_PFT_Annual_1981-2023/" + ("PFT_Classification.xlsx" if base.endswith(".xlsx") else f"China-PFTs_1km_{y}_v1.0.tif")
    m = re.fullmatch(r"forest(gain|loss)_(duration|startyear)_cn1km", sid)
    if m:
        part = "Duration" if m.group(2) == "duration" else "StartYear"
        return f"{d}{'3_Forest_Change_Gain' if m.group(1) == 'gain' else '4_Forest_Change_Loss'}/China-ForestChange_{m.group(1).title()}_{part}_1km_v1.0.tif"
    m = re.fullmatch(r"(e?chap)_([a-z0-9]+?)_(\d+)km", sid)
    if m:
        fam, pol, km = m.groups()
        key = f"{pol}_{km}km"
        name = POLL.get(pol, pol.upper() if pol in ("co", "no2", "o3", "so2", "pm1", "pm10") else pol.title() if pol in ("cl",) else pol.upper())
        if pol in ("nh4", "no3", "so4"):
            name = pol.upper()
        if pol == "cl":
            name = "Cl"
        return f"空气污染/{fam.upper()}_{name}_Y{km}K_{y}_{CHAP_VER[key]}.nc"
    raise KeyError(sid)


def finish(root):
    """数据已移动但记录没写完时，从新目录结构反推记录并补全 dataset.json、清单、回滚脚本、杂项清理。"""
    R = Path(root)
    P = Plan(R)
    for dpp in sorted(p for p in R.iterdir() if p.is_dir() and not p.name.startswith("_")):
        for sd in sorted(p for p in dpp.iterdir() if p.is_dir()):
            if not any(sd.rglob("*")):
                continue
            sid = sd.name
            if sid not in P.defs and re.fullmatch(r"e?chap_.+_\d+km", sid):
                m = re.fullmatch(r"(e?chap)_([a-z0-9]+?)_(\d+)km", sid)
                fam, pol, km = m.groups()
                name = POLL.get(pol, {"cl": "Cl"}.get(pol, pol.upper()))
                P.defs[sid] = dict(id=sid, category="airq", temporal="year", variable=name, resolution=f"{km} km",
                                   name=f"{'中国高分辨率空气污染' if fam == 'chap' else '空气污染化学组分'} {name}（年均，{km} km）",
                                   product=fam.upper(), versions={}, notes="")
                P.defs[sid]["versions"] = {CHAP_VER[f"{pol}_{km}km"]: sorted({int(re.search(r"_(\d{4})", f.name).group(1)) for f in sd.glob("*.nc") if not is_junk(f.name)})}
            if sid not in P.defs:
                continue
            for f in sorted(sd.rglob("*")):
                if f.is_file() and not is_junk(f.name) and f.name != "dataset.json":
                    P.move(R / old_name(sid, str(f.relative_to(sd))), f, sid, "doc" if f.suffix == ".xlsx" else "data")
    for sid, d in P.defs.items():
        if d.get("versions"):
            d["notes"] = "原文件名 " + d["product"] + "_" + d["variable"] + "_Y" + d["resolution"].split()[0] + "K_<年>_<版本>.nc；版本：" + \
                "；".join(f"{v}（{min(ys)}–{max(ys)}）" for v, ys in sorted(d["versions"].items()))
    # 备份的 rar
    rows_extra = []
    for f in sorted((R / "_压缩包备份").rglob("*.rar")):
        if is_junk(f.name):
            continue
        folder = {"t2m": "气温", "precip": "降水", "sunshine": "日照"}[f.parent.name]
        rows_extra.append((f"{folder}/{f.name}", str(f.relative_to(R)), "", "backup", f.stat().st_size))
    log_dir = R / "_整理记录"
    (log_dir / "杂项").mkdir(parents=True, exist_ok=True)
    rows = [(str(s.relative_to(R)), str(d.relative_to(R)), sid, kind, d.stat().st_size) for s, d, sid, kind in P.moves] + rows_extra
    # 杂项清理 + 旧空目录
    for old in ("气温", "降水", "湿度", "日照", "GDP", "植被类型", "空气污染"):
        base = R / old
        for dp, dns, fns in os.walk(base, topdown=False):
            dpp = Path(dp)
            if old == "GDP" and any(p.name.startswith("gdp_cn1km") for p in dpp.iterdir()):
                continue                      # exFAT 不分大小写：GDP 与新类别 gdp 是同一个目录，别动已整理好的文件夹
            for fn in fns:
                if is_junk(fn) and fn not in ("README.docx", "~$README.docx", "._README.docx"):
                    tgt = log_dir / "杂项" / f"{old}__{'__'.join(dpp.relative_to(base).parts)}__{fn}".replace("____", "__")
                    n = 1
                    while tgt.exists():
                        tgt = tgt.with_name(tgt.name + f".{n}")
                        n += 1
                    try:
                        os.rename(dpp / fn, tgt)
                    except FileNotFoundError:
                        pass
            try:
                dpp.rmdir()
            except OSError:
                pass
    for name in ("._气温", "._降水", "._湿度", "._日照", "._GDP", "._植被类型", "._空气污染"):
        f = R / name
        if f.exists():
            try:
                os.rename(f, log_dir / "杂项" / name)
            except FileNotFoundError:
                pass
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = log_dir / f"整理记录_{stamp}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["旧路径", "新路径", "数据序列", "类型", "字节数"])
        w.writerows(rows)
    (log_dir / "回滚.py").write_text(ROLLBACK, encoding="utf-8")
    write_manifests(P, log_dir)
    return csv_path, len(rows)


def write_inventory(root, log_dir=None):
    """按各数据序列的 dataset.json 重新生成「数据清单.csv」和 README.md（不依赖整理计划）。"""
    from core.raster_catalog import load_all
    R = Path(root)
    log_dir = Path(log_dir) if log_dir else R / "_整理记录"
    log_dir.mkdir(parents=True, exist_ok=True)
    ser, _ = load_all(R)
    inv = []
    for s in sorted(ser, key=lambda x: (x.category, x.id)):
        files = [f for ps in s.files().values() for f in ps]
        inv.append((s.category, s.id, s.name, len(files), s.start, s.end, round(sum(f.stat().st_size for f in files) / 1e9, 2), s.notes))
    with open(log_dir / "数据清单.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["类别", "数据序列id", "名称", "文件数", "起始", "结束", "大小(GB)", "说明"])
        w.writerows(inv)
    lines = ["# 环境数据整理说明", "", f"更新时间：{datetime.now():%Y-%m-%d %H:%M}", "",
             "目录结构：`<类别>/<数据序列id>/<id>_<日期>.<ext>`，每个数据序列文件夹里有 `dataset.json`（可用「栅格数据目录」工具编辑和检查）。",
             "原 `.rar` 压缩包保存在 `_压缩包备份/`；所有改动的新旧路径见 `_整理记录/整理记录_*.csv`。",
             "回滚：先对**最新**的记录运行 `回滚.py <记录.csv>`，再依次对更早的记录运行（后做的改动要先撤销）。", "",
             "| 类别 | 数据序列 | 名称 | 文件数 | 起止 | 大小(GB) |", "|---|---|---|---|---|---|"]
    lines += [f"| {c} | {i} | {n} | {k} | {a}~{b} | {g} |" for c, i, n, k, a, b, g, _ in inv]
    (log_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def merge_airq(root, execute=False):
    """把 CHAP 的 10 km / 1 km 拆分序列合并成每种污染物一个序列（如 chap_co），并打开「允许网格变化」。"""
    from core.raster_catalog import Series
    R = Path(root)
    A = R / "airq"
    log_dir = R / "_整理记录"
    moves, defs = [], {}
    for pol in sorted({m.group(1) for d in A.iterdir() if (m := re.fullmatch(r"chap_([a-z0-9]+)_10km", d.name))}):
        parts = [A / f"chap_{pol}_10km", A / f"chap_{pol}_1km"]
        if not all(p.exists() for p in parts):
            continue
        new = A / f"chap_{pol}"
        info = []                                            # (分辨率, 起, 止, 版本)
        years = []
        for d in parts:
            old = Series.load(d)
            ys = sorted(int(re.search(r"_(\d{4})\.nc$", f.name).group(1)) for f in d.glob("*.nc") if not is_junk(f.name))
            years += ys
            ver = re.search(r"版本：(V\d+)", old.notes)
            info.append((old.resolution, min(ys), max(ys), ver.group(1) if ver else ""))
            for f in sorted(d.glob("*.nc")):
                if not is_junk(f.name):
                    y = re.search(r"_(\d{4})\.nc$", f.name).group(1)
                    moves.append((f, new / f"chap_{pol}_{y}.nc"))
        assert len(set(years)) == len(years), f"{pol} 年份重叠"
        var = {"co": "CO", "no2": "NO2", "so2": "SO2"}.get(pol, pol.upper())
        seg = "；".join(f"{a}–{b} 年：{r}，{v}" for r, a, b, v in info)
        defs[pol] = (new, parts, Series(
            id=f"chap_{pol}", name=f"中国高分辨率空气污染 {var}（年均，10 km→1 km）", category="airq", product="CHAP", variable=var,
            temporal="year", start=str(min(years)), end=str(max(years)), check_gaps=True, multi_grid=True,
            resolution="；".join(f"{a}–{b} 年 {r}" for r, a, b, _ in info),
            notes=f"原文件名 CHAP_{var}_Y<10|1>K_<年>_<版本>.nc。{seg}。注意：跨 2018/2019 年分辨率和算法版本都有变化，跨期使用时请留意系统性差异。",
            folder=new))
    print(f"计划合并 {len(defs)} 个污染物序列，移动 {len(moves)} 个文件")
    for pol, (new, parts, s) in defs.items():
        print(f"  {new.name}: {s.resolution}")
    if not execute:
        print("（演练：没有改动任何文件）")
        return
    assert all(not d.exists() for _, d in moves), "目标已存在"
    rows = []
    for src, dst in moves:
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.rename(src, dst)
        rows.append((str(src.relative_to(R)), str(dst.relative_to(R)), dst.parent.name, "data", dst.stat().st_size))
    for pol, (new, parts, s) in defs.items():
        s.save()
        for d in parts:
            for f in sorted(d.iterdir()):                      # 旧序列的 dataset.json 与杂项移到记录目录，再删空目录
                tgt = log_dir / "杂项" / f"airq__{d.name}__{f.name}"
                os.rename(f, tgt)
                rows.append((str(f.relative_to(R)), str(tgt.relative_to(R)), d.name, "meta" if f.name == "dataset.json" else "junk", 0))
            d.rmdir()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = log_dir / f"整理记录_{stamp}_合并空气污染.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["旧路径", "新路径", "数据序列", "类型", "字节数"])
        w.writerows(rows)
    write_inventory(R)
    print(f"完成：{len(rows)} 条记录 → {csv_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--finish", action="store_true", help="补救：数据已移动，从新结构反推记录并补全清单")
    ap.add_argument("--merge-airq", action="store_true", help="合并 CHAP 的 10 km / 1 km 序列（可与 --execute 一起用）")
    a = ap.parse_args()
    if a.merge_airq:
        merge_airq(a.root, a.execute)
        return
    if a.finish:
        csv_path, n = finish(a.root)
        print(f"已补全：{n} 条记录 → {csv_path}")
        return
    P = build(a.root)
    validate(P)
    by = defaultdict(int)
    for _, _, sid, kind in P.moves:
        by[(sid or kind)] += 1
    print(f"计划移动 {len(P.moves)} 个文件，涉及 {len([k for k in by if k not in ('backup', 'doc')])} 个数据序列：")
    for k, v in sorted(by.items()):
        print(f"  {k:32s} {v}")
    if not a.execute:
        print("\n（演练：没有改动任何文件。确认无误后加 --execute 执行）")
        return
    csv_path, n, left = execute(P)
    print(f"\n完成：{n} 条记录写入 {csv_path}；移除空文件夹 {len(left)} 个")


if __name__ == "__main__":
    main()
