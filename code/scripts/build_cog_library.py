# -*- coding: utf-8 -*-
"""把整理好的原始数据（含 NetCDF）批量转成 COG 库。原始数据不动，数值保持原样（不缩放、不改单位）。

    python scripts/build_cog_library.py <原始数据根目录> <COG库根目录> [--only 序列id,...]

转换规则（按数据序列 id）:
    tmp_cn1km / pre_cn1km    每年 1 个 nc（含 12 个月）→ 逐月 COG，新序列 *_month
    rhum_cmfd                单个 nc（74 个年值）→ 逐年 COG，新序列 rhum_cmfd_year
    chap_* / echap_*         每年 1 个 nc → 逐年 COG，序列 id 不变
    其余（日照月均、GDP、森林）已是 tif：原样复制，并带上 dataset.json
已存在的输出自动跳过，可断点续跑。
"""
import argparse
import csv
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import cog  # noqa: E402
from core import raster_catalog as RC  # noqa: E402

# 源数据中已知不完整、不应当作有效值写入的层：{(序列id, 文件年份): [层序号(从0)]}
SKIP = {("pre_cn1km", 1996): [10, 11]}          # 1996 年 11、12 月在源文件中全为 0（文件不完整）

PLAN = {
    "tmp_cn1km": ("tmp_cn1km_month", "month", "气温（月均，约 1 km，逐月）"),
    "pre_cn1km": ("pre_cn1km_month", "month", "降水（月累计，约 1 km，逐月）"),
    "rhum_cmfd": ("rhum_cmfd_year", "year", "相对湿度（CMFD 年均，0.1°，逐年）"),
}


def plan_for(sid):
    if sid in PLAN:
        return PLAN[sid]
    if sid.startswith(("chap_", "echap_")):
        return (sid, "year", None)
    return None


def convert_series(src, out_root, log):
    outid, temporal, name = plan_for(src.id)
    out = RC.Series(**{k: getattr(src, k) for k in ("category", "product", "variable", "unit", "resolution", "multi_grid", "source", "link")},
                    id=outid, name=name or src.name, temporal=temporal, check_gaps=True,
                    folder=out_root / src.category / outid)
    made, skipped, failed = [], [], []
    first = None
    for key, ps in sorted(src.files().items()):
        f = ps[0]
        info = cog.nc_describe(f)
        first = first or info
        fy = int(key[:4]) if key else None
        for i in range(info["n"]):
            if i in SKIP.get((src.id, fy), []):
                skipped.append((f.name, i))
                continue
            d = info["dates"][i] if info["dates"][i] is not None else (fy,)
            d = d[:{"year": 1, "month": 2}[temporal]]
            dst = out.folder / f"{d[0]:04d}" / out.filename(d)
            if dst.exists() and dst.stat().st_size > 0:
                made.append(dst)
                continue
            try:
                cog.nc_layer_to_cog(f, info["var"], i, dst)
                made.append(dst)
            except Exception as e:
                failed.append((f.name, i, str(e)))
                log(f"  ✗ {f.name} 第 {i + 1} 层失败: {e}")
        log(f"  {f.name}: 完成（累计 {len(made)} 个输出）")
    keys = sorted({p.stem.rsplit("_", 1)[-1] for p in made})
    fmt = lambda k: k if len(k) == 4 else f"{k[:4]}-{k[4:6]}"
    out.start, out.end = fmt(keys[0]), fmt(keys[-1])
    out.crs = first["crs"].to_string()
    out.dtype = first["dtype"]
    out.nodata = "" if first["nodata"] is None or first["nodata"] != first["nodata"] else f"{first['nodata']:g}"
    out.scale, out.offset = float(f"{first['scale']:.8g}"), float(f"{first['offset']:.8g}")   # 去掉 float32 的小数噪声
    out.unit = out.unit or first["units"]
    extra = f" 源数据中 {', '.join(f'{n} 第{i + 1}层' for n, i in skipped)} 不完整，未转换。" if skipped else ""
    out.notes = (f"由原始序列 {src.id}（NetCDF）转成 COG，数值、数据类型、无效值保持原样，未做缩放或单位换算；"
                 f"缩放系数 {first['scale']:g}、偏移 {first['offset']:g} 记在文件的 scale/offset 元数据里（读取数组时需要自己乘）。"
                 f"坐标系{first['crs_note']}。{extra} 原说明：{src.notes}")
    out.save()
    return out, made, skipped, failed


def copy_series(src, out_root, log):
    out = RC.Series(**{k: getattr(src, k) for k in ("id", "name", "category", "product", "variable", "unit", "temporal", "start", "end",
                                                   "check_gaps", "multi_grid", "crs", "resolution", "nodata", "dtype", "scale", "offset",
                                                   "source", "link", "notes")}, folder=out_root / src.category / src.id)
    n = 0
    for key, ps in sorted(src.files().items()):
        f = ps[0]
        if f.suffix.lower() not in (".tif", ".tiff"):
            continue
        dst = out.folder / f.relative_to(src.folder)
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
        n += 1
    for extra in src.folder.glob("*"):                      # 说明文件、月聚合记录等一并带上
        if extra.is_file() and extra.suffix.lower() in (".xlsx", ".csv") and not extra.name.startswith("._"):
            shutil.copy2(extra, out.folder / extra.name)
    out.notes = (src.notes + " 本序列在 COG 库中是原样复制（原本已是 GeoTIFF），未做重投影。").strip()
    out.save()
    return out, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src_root")
    ap.add_argument("out_root")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    out_root = Path(a.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    logf = open(out_root / "_转换记录.log", "a", encoding="utf-8")

    def log(m):
        line = f"{datetime.now():%H:%M:%S} {m}"
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    series, _ = RC.load_all(a.src_root)
    only = {x for x in a.only.split(",") if x}
    t0 = time.time()
    summary = []
    for s in sorted(series, key=lambda x: (x.category, x.id)):
        if only and s.id not in only:
            continue
        log(f"▶ {s.id}（{s.name}）")
        if plan_for(s.id):
            out, made, skipped, failed = convert_series(s, out_root, log)
            summary.append((s.id, out.id, len(made), len(skipped), len(failed)))
        elif any(f.suffix.lower() in (".tif", ".tiff") for ps in s.files().values() for f in ps):
            out, n = copy_series(s, out_root, log)
            summary.append((s.id, out.id, n, 0, 0))
        else:
            log("  （没有 tif 文件，跳过）")
    with open(out_root / "_转换汇总.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["原序列", "COG库序列", "输出文件数", "跳过层数", "失败数"])
        w.writerows(summary)
    log(f"全部完成，用时 {(time.time() - t0) / 60:.1f} 分钟")


if __name__ == "__main__":
    main()
