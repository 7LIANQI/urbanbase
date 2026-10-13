# -*- coding: utf-8 -*-
"""日值序列 → 月值序列。用法:
    python scripts/daily_to_monthly.py <栅格数据根目录> <日序列id> <新月序列id> [--stat mean|sum] [--name 名称]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import raster_catalog as RC  # noqa: E402
from core.aggregate import daily_to_monthly, write_record  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("src_id")
    ap.add_argument("out_id")
    ap.add_argument("--stat", default="mean", choices=["mean", "sum"])
    ap.add_argument("--name", default="")
    a = ap.parse_args()
    series, _ = RC.load_all(a.root)
    src = next(s for s in series if s.id == a.src_id)
    folder = src.folder.parent / a.out_id
    stat_cn = "月均" if a.stat == "mean" else "月总和"
    out = RC.Series(id=a.out_id, name=a.name or f"{src.name.split('（')[0]}（{stat_cn}，由日值聚合）", category=src.category,
                    product=src.product, variable=src.variable, unit=src.unit, temporal="month", crs=src.crs or "EPSG:4326",
                    resolution=src.resolution, dtype="float32", check_gaps=True, folder=folder)
    recs = daily_to_monthly(src, out, a.stat, log=print)
    out.start, out.end = recs[0][0][:4] + "-" + recs[0][0][4:], recs[-1][0][:4] + "-" + recs[-1][0][4:]
    short = [(ym, u, t) for ym, u, t in recs if u < t]
    out.notes = (f"由日序列 {src.id} 按月{('平均' if a.stat == 'mean' else '求和')}得到：只统计有效像元，缺的日期不补，"
                 f"均值基于当月现有天数。共 {len(recs)} 个月，其中 {len(short)} 个月不满整月（见 _月聚合记录.csv）。无效值为 NaN。")
    out.save()
    print("记录:", write_record(out, recs, a.stat, src.id))


if __name__ == "__main__":
    main()
