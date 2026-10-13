# -*- coding: utf-8 -*-
"""点位指标提取的「采集报告」（一份 Markdown）：提取设置、缺期处理（最近一期替代）、各列有值/空值情况与原因、字段说明。"""
import os
from collections import Counter

import numpy as np
import pandas as pd

_FILL_RULES = """\
规则（对本地数据和 GEE 数据都一样）：

1. **窗口内有数据的单位都参与计算，缺的单位不参与。** 例如观测日在 2025 年、窗口为前 3 年（2022–2024），而数据只有 2022、2023 两年，则只对这两年求均值（或中值）。
2. **整个窗口一个单位都没有数据时，改用离这个窗口最近的一期**（前后一样近时取较早的一期），数值就是那一期的值（不做插值）。例如 GDP 只有 2010、2015、2020–2024 年，观测在 2018 年、窗口为当前年，则取 2020 年（差 2 年，比 2015 年的差 3 年更近）。
3. 因此不会再因为「缺期」出现空值。仍然为空的只可能是：点在数据覆盖的空间范围之外、点周围的像元全是无效值，或这个数据序列一期数据都没有。
4. 「偏差」指替代用的那一期与窗口相差的年数。偏差越大，越不能代表观测当时的情况；分析时请留意偏差大的列，必要时只保留偏差较小的点。
5. 取最近一期对本地数据不设上限；GEE 数据只在窗口前后各 2 年范围内找，超出的仍为空。
6. 每一列的有值数里，包含了用最近一期替代的点；替代了多少个点见下表。"""


def _bullets(d, indent=0):
    out = []
    for k, v in d.items():
        pad = "  " * indent
        if isinstance(v, dict):
            out.append(f"{pad}- **{k}**")
            out += _bullets(v, indent + 1)
        else:
            out.append(f"{pad}- {k}：{'、'.join(map(str, v)) if isinstance(v, (list, tuple)) else v}")
    return out


def write_report(out_csv, df, groups, diag=None, failed=None, local_series=None, n_points=None, desc=None, settings=None,
                 append=False):
    """df：最终输出表；groups：{数据源名称: [输出列]}；diag：引擎诊断（used/expected/reason/sub/gap/cols）；
    failed：{key: (名称, 错误信息)}（GEE 出错被跳过的数据源）；desc：{输出列: 说明} 或函数；settings：提取设置 dict。
    append=True 时把本次提取作为新的一节接在已有报告后面（已有报告不存在则新建）。
    返回 md 路径（与输出 CSV 同目录同名，后缀 _采集报告.md）。"""
    n = n_points or len(df)
    desc = desc if callable(desc) else (lambda c, d=desc or {}: d.get(c, ""))
    dcols = list(diag["cols"]) if diag else []
    rows = []
    for src, cols in groups.items():
        for c in cols:
            if c not in df.columns:
                continue
            valid = int(df[c].notna().sum())
            row = dict(数据源=src, 输出列=c, 说明=desc(c), 总点数=n, 有值=valid, 空值=n - valid,
                       空值率=round((n - valid) / n, 4) if n else 0)
            if diag and c in dcols:
                k = dcols.index(c)
                used, exp, reason = diag["used"][:, k], diag["expected"][:, k], diag["reason"][:, k]
                row.update(平均用到单位数=round(float(used[used > 0].mean()), 2) if (used > 0).any() else 0,
                           平均应有单位数=round(float(exp[exp > 0].mean()), 2) if (exp > 0).any() else 0)
                rc = Counter(r for r in reason if r)
                for name in ("无数据文件", "点在栅格范围外", "该范围内全是无效值"):
                    row[f"空值原因·{name}"] = rc.get(name, 0)
                if "sub" in diag:
                    sub = diag["sub"][:, k].astype(bool) & df[c].notna().to_numpy()
                    g = diag["gap"][:, k][sub]
                    row.update(替代点数=int(sub.sum()), 平均偏差年=round(float(g.mean()), 2) if sub.any() else 0,
                               最大偏差年=round(float(g.max()), 2) if sub.any() else 0)
            rows.append(row)
    rep = pd.DataFrame(rows)
    path = os.path.splitext(out_csv)[0] + "_采集报告.md"

    lines = ["<!-- cols=%d -->" % len(rep), f"点位数：{n}；本次输出列：{len(rep)}", ""]
    if settings:
        lines += ["### 提取设置", ""] + _bullets(settings) + [""]
    fill = rep[rep["替代点数"] > 0] if len(rep) and "替代点数" in rep else rep.iloc[0:0]
    if len(fill):
        lines += [f"### 缺期处理：本次有 {len(fill)} 列用到了最近一期替代", "",
                  "| 数据源 | 输出列 | 替代的点数 | 占比 | 平均偏差（年） | 最大偏差（年） |", "|---|---|---|---|---|---|"]
        for _, r in fill.iterrows():
            flag = " ⚠️" if r["最大偏差年"] > 3 else ""
            lines.append(f"| {r['数据源']} | {r['输出列']} | {int(r['替代点数'])} | {r['替代点数'] / n:.0%} | {r['平均偏差年']} | {r['最大偏差年']}{flag} |")
        lines += ["", "⚠️ 表示最大偏差超过 3 年。规则见文件开头的「缺期处理规则」。", ""]
    else:
        lines += ["### 缺期处理", "", "本次没有任何一列需要用最近一期替代。", ""]
    if failed:
        lines += ["### 出错被跳过的数据源（对应列全部为空）", ""]
        lines += [f"- **{name}**：{msg[:300]}" for name, msg in failed.values()]
        lines.append("")
    problems = rep[rep["空值率"] > 0.5] if len(rep) else rep
    if len(problems):
        lines += ["### 空值较多的列（超过一半的点没有值）", "", "| 数据源 | 输出列 | 空值率 | 原因 |", "|---|---|---|---|"]
        for _, r in problems.iterrows():
            why = ""
            if "空值原因·无数据文件" in r:
                why = "；".join(f"{k.split('·')[1]} {int(r[k])}" for k in r.index if str(k).startswith("空值原因·") and pd.notna(r[k]) and r[k])
            lines.append(f"| {r['数据源']} | {r['输出列']} | {r['空值率']:.0%} | {why} |")
        lines.append("")
    lines += ["### 各列概况", "", "| 数据源 | 输出列 | 有值 | 空值 | 空值率 | 平均用到/应有的时间单位 |", "|---|---|---|---|---|---|"]
    for _, r in rep.iterrows():
        unit = f"{r['平均用到单位数']} / {r['平均应有单位数']}" if "平均用到单位数" in r and pd.notna(r.get("平均用到单位数")) else "—"
        lines.append(f"| {r['数据源']} | {r['输出列']} | {r['有值']} | {r['空值']} | {r['空值率']:.0%} | {unit} |")
    lines += ["", "「平均用到/应有的时间单位」小于 1 说明窗口内有缺期（缺的单位不参与计算）。", ""]
    lines += ["### 字段说明", "", "| 输出列 | 含义 |", "|---|---|"]
    lines += [f"| {r['输出列']} | {r['说明']} |" for _, r in rep.iterrows() if r["说明"]]
    lines += [""]
    if local_series:
        lines += ["### 本地数据序列的覆盖范围", ""] + [f"- {s.id}（{s.name}）：{s.start or '—'} 至 {s.end or '—'}" for s in local_series if s.kind != "vector"] + [""]

    # 已有报告：按「## 第 N 次提取」切成各次，新的一次接在后面
    blocks = report_blocks(path) if append else []
    from datetime import datetime
    blocks.append(f"## 第 {len(blocks) + 1} 次提取（{datetime.now():%Y-%m-%d %H:%M}）\n\n" + "\n".join(lines))
    _assemble(path, blocks, n)
    return path


def report_blocks(path):
    """读一份报告，返回各次提取的文本块（列表）。新格式按「## 第 N 次提取」切；旧格式（单次、无分节标记）整份当作一次。"""
    import re
    from datetime import datetime
    if not os.path.exists(path):
        return []
    old = open(path, encoding="utf-8").read()
    parts = old.split("\n## 第 ")
    if len(parts) > 1:
        return ["## 第 " + b.rstrip("\n") + "\n" for b in parts[1:]]
    body = old.split("\n", 1)[1] if old.startswith("#") else old
    body = body.replace("\n## ", "\n### ").strip("\n")
    m = re.search(r"输出列：(\d+)", body)
    when = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
    return [f"## 第 1 次提取（{when}，旧版报告）\n\n<!-- cols={m.group(1) if m else 0} -->\n" + body + "\n"]


def _assemble(path, blocks, n):
    import re
    blocks = [re.sub(r"^## 第 \d+ 次", f"## 第 {i} 次", b) for i, b in enumerate(blocks, 1)]          # 重新编号
    total = sum(int(m) for b in blocks for m in re.findall(r"<!-- cols=(\d+) -->", b))
    head = ["# 点位指标采集报告", "", f"点位数：{n}；共 {len(blocks)} 次提取，累计输出列 {total}。每次提取的设置、替代情况、空值情况和字段说明依次记在下面。", "",
            "## 缺期处理规则", "", _FILL_RULES, "", "列名后缀是时间窗口：`cur` = 观测当年（或当月），`y1`/`y2`/`y3`/`y5`/`y10` = 观测之前的 1/2/3/5/10 年；自定义时间段用你填的名称。", ""]
    open(path, "w", encoding="utf-8").write("\n".join(head) + "\n" + "\n".join(blocks))


def merge_reports(paths, out_path):
    """把几份报告按顺序合并成一份（已是新格式的多次报告也能合并）。点位数取第一份里写的点位数。"""
    import re
    blocks, n = [], 0
    for p in paths:
        blocks += report_blocks(p)
        if not n:
            m = re.search(r"点位数：(\d+)", open(p, encoding="utf-8").read())
            n = int(m.group(1)) if m else 0
    _assemble(out_path, blocks, n)
    return out_path
