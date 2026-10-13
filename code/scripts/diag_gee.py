# -*- coding: utf-8 -*-
"""GEE 提取自检：同一批 3 个点，分别用「时间段序列」和「回溯窗口」两种方式取 WorldPop，对比结果。
用法：uv run python scripts/diag_gee.py [GEE 服务账号 JSON 路径]    （不给路径就用本机默认凭证）"""
import os
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from plugins import gee_catalog as C
from plugins import gee_extract as G

key = sys.argv[1] if len(sys.argv) > 1 else None
df = pd.DataFrame({"lon": [113.2883353, 113.2955387, 113.30], "lat": [23.1392933, 23.1440092, 23.12], "date": ["2018-05-01"] * 3})
ds = [C.SOURCE_BY_KEY["pop.worldpop"]]
for mode, windows, periods in (("seq", [], G.make_periods("2020-01-01", "2020-12-31", "YS")), ("rel", ["cur"], [])):
    for buf in (0, 1000):
        out = os.path.join(tempfile.mkdtemp(), "o.csv")
        r = G.run(df, "lon", "lat", "date", ds, buf, mode, windows, periods, "median", "mean", out, key=key, batch=10, workers=1, log=print)
        print(f"\n===== 模式 {mode}，缓冲区 {buf} m =====")
        print(pd.read_csv(r, encoding="utf-8-sig").to_string() if r else "未完成")
