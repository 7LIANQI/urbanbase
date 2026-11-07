"""点位时序分析：识别宽表时间列、标准化长表并计算趋势。"""
from dataclasses import dataclass
import re
from datetime import datetime
from pathlib import Path
import warnings

import numpy as np
import pandas as pd


_FIXED = re.compile(r"^(?P<metric>.+)_(?P<period>P(?P<date>\d{4}(?:\d{2})?(?:\d{2})?))$")
_RELATIVE = re.compile(r"^(?P<metric>.+)_(?P<period>cur|y(?:1|2|3|5|10))$")
_REL_ORDER = {"cur": 0, "y1": 1, "y2": 2, "y3": 3, "y5": 5, "y10": 10}


@dataclass(frozen=True)
class TimeColumn:
    column: str
    metric: str
    period: str
    kind: str
    order: float


def _fixed_order(text):
    text = text[1:]
    if len(text) == 4:
        return float(int(text))
    if len(text) == 6:
        return int(text[:4]) + (int(text[4:6]) - 1) / 12
    if len(text) == 8:
        return int(text[:4]) + (int(text[4:6]) - 1) / 12 + (int(text[6:8]) - 1) / 365
    raise ValueError(f"无法识别时间段：{text}")


def discover_time_columns(df, mode="auto", metrics=None):
    """从点位宽表中识别 `指标_P2020` 和 `指标_cur/y3` 列。"""
    selected = set(metrics) if metrics else None
    found = []
    for column in df.columns:
        name = str(column)
        match = _FIXED.match(name)
        if match and mode in ("auto", "fixed"):
            metric = match.group("metric")
            if selected is None or metric in selected:
                found.append(TimeColumn(name, metric, match.group("period")[1:], "fixed",
                                        _fixed_order(match.group("period"))))
            continue
        match = _RELATIVE.match(name)
        if match and mode in ("auto", "relative"):
            metric = match.group("metric")
            if selected is None or metric in selected:
                period = match.group("period")
                found.append(TimeColumn(name, metric, period, "relative", _REL_ORDER[period]))
    kinds = {x.kind for x in found}
    if len(kinds) > 1:
        raise ValueError("同一张表同时包含历史时间段和相对窗口，请选择一种时间口径")
    return sorted(found, key=lambda x: (x.metric.casefold(), x.order))


def metric_names(df):
    columns = discover_time_columns(df)
    return sorted({x.metric for x in columns}, key=str.casefold)


def to_long(df, time_columns, id_col=None, lon_col=None, lat_col=None):
    """宽表 -> (point_id, metric, period, value, axis_value) 长表。"""
    if not time_columns:
        raise ValueError("没有选中可用时间列")
    ids = df[id_col].astype(str) if id_col and id_col in df.columns else df.index.astype(str)
    lon = (pd.to_numeric(df[lon_col], errors="coerce") if lon_col in df.columns
           else pd.Series(np.nan, index=df.index))
    lat = (pd.to_numeric(df[lat_col], errors="coerce") if lat_col in df.columns
           else pd.Series(np.nan, index=df.index))
    parts = []
    for col in time_columns:
        values = pd.to_numeric(df[col.column], errors="coerce")
        part = pd.DataFrame({
            "point_id": ids.values,
            "metric": col.metric,
            "period": col.period,
            "axis_value": col.order,
            "kind": col.kind,
            "value": values.values,
            "lon": lon.values,
            "lat": lat.values,
        })
        part["_row"] = np.arange(len(df))
        parts.append(part)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def records_to_long(df, date_col, metric_cols, id_col=None, lon_col=None, lat_col=None):
    """按日期列组织的记录 -> 标准长表。"""
    if not metric_cols:
        raise ValueError("没有选择指标列")
    dates = pd.to_datetime(df[date_col], errors="coerce")
    ids = df[id_col].astype(str) if id_col and id_col in df.columns else df.index.astype(str)
    lon = (pd.to_numeric(df[lon_col], errors="coerce") if lon_col in df.columns
           else pd.Series(np.nan, index=df.index))
    lat = (pd.to_numeric(df[lat_col], errors="coerce") if lat_col in df.columns
           else pd.Series(np.nan, index=df.index))
    row_keys = pd.factorize(ids, sort=False)[0]
    parts = []
    for metric in metric_cols:
        values = pd.to_numeric(df[metric], errors="coerce")
        order = dates.dt.year + (dates.dt.dayofyear - 1) / 365.25
        part = pd.DataFrame({
            "point_id": ids.values,
            "metric": metric,
            "period": dates.dt.strftime("%Y-%m-%d").values,
            "axis_value": order.values,
            "kind": "date",
            "value": values.values,
            "lon": lon.values,
            "lat": lat.values,
            "_row": row_keys,
        })
        parts.append(part[part["period"].notna()])
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def summarize(long):
    """按点位和指标计算首末期、变化量、均值、范围和线性斜率。"""
    if long.empty:
        return pd.DataFrame()
    result = []
    for metric, part in long.groupby("metric", sort=False):
        # 每个原始点只出现一次；重复时期取均值，避免重复记录放大权重。
        axis_map = part.groupby("period")["axis_value"].first()
        periods = sorted(part["period"].dropna().unique(), key=lambda p: float(axis_map[p]))
        row_ids = sorted(part["_row"].dropna().unique())
        if not periods or not row_ids:
            continue
        # 保留整列全空的指标。默认 pivot_table 会丢掉零列矩阵，
        # 随后的 argmax 就会报“empty sequence”。显式补齐行列后，
        # 仍然输出 valid_count=0，而不会中断其他指标。
        matrix = part.pivot_table(
            index="_row", columns="period", values="value", aggfunc="mean", dropna=False,
        ).reindex(index=row_ids, columns=periods)
        arr = matrix.to_numpy(dtype=float)
        valid = ~np.isnan(arr)
        n, k = arr.shape
        rows = np.arange(n)
        first_idx = np.argmax(valid, axis=1)
        last_idx = k - 1 - np.argmax(valid[:, ::-1], axis=1)
        none = ~valid.any(axis=1)
        first = arr[rows, first_idx]
        last = arr[rows, last_idx]
        first[none] = np.nan
        last[none] = np.nan
        count = valid.sum(axis=1)
        x = np.array([axis_map[p] for p in periods], dtype=float)
        xm = np.divide((valid * x).sum(axis=1), count, out=np.zeros(n), where=count > 0)
        ym = np.divide(np.nansum(np.where(valid, arr, 0), axis=1), count,
                       out=np.zeros(n), where=count > 0)
        dx = valid * (x - xm[:, None])
        dy = np.where(valid, arr - ym[:, None], 0)
        den = (dx * dx).sum(axis=1)
        slope = np.divide((dx * dy).sum(axis=1), den, out=np.full(n, np.nan), where=den > 0)
        first_period = np.array(periods, dtype=object)[np.where(none, 0, first_idx)]
        last_period = np.array(periods, dtype=object)[np.where(none, 0, last_idx)]
        first_period[none] = None
        last_period[none] = None
        rows_df = pd.DataFrame({
            "_row": matrix.index.to_numpy(),
            "metric": metric,
            "first_period": first_period,
            "last_period": last_period,
            "first": first,
            "last": last,
            "change": last - first,
            "change_pct": np.divide(last - first, first, out=np.full(n, np.nan), where=first != 0) * 100,
            "mean": np.nan,
            "min": np.nan,
            "max": np.nan,
            "valid_count": count,
            "total_periods": k,
            "all_missing": count == 0,
            "slope_per_year": slope,
        })
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            rows_df["mean"] = np.nanmean(arr, axis=1)
            rows_df["min"] = np.nanmin(arr, axis=1)
            rows_df["max"] = np.nanmax(arr, axis=1)
        result.append(rows_df)
    if not result:
        return pd.DataFrame()
    stats = pd.concat(result, ignore_index=True)
    meta = long.groupby("_row")[["point_id", "lon", "lat"]].first().reset_index()
    return stats.merge(meta, on="_row", how="left").drop(columns="_row")


def write_outputs(long, stats, base_path, report_extra=None):
    """写长表、统计 CSV 和 Markdown 报告。"""
    base = Path(base_path)
    base.parent.mkdir(parents=True, exist_ok=True)
    long_path = base.with_name(base.stem + "_long.csv")
    stats_path = base.with_name(base.stem + "_stats.csv")
    report_path = base.with_name(base.stem + "_report.md")
    long.to_csv(long_path, index=False, encoding="utf-8-sig")
    stats.to_csv(stats_path, index=False, encoding="utf-8-sig")
    lines = [
        "# 点位时间分析报告", "",
        f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}",
        f"- 点位数：{long['point_id'].nunique() if not long.empty else 0}",
        f"- 指标数：{long['metric'].nunique() if not long.empty else 0}",
        f"- 长表记录：{len(long)}",
        "",
    ]
    if report_extra:
        lines += ["## 输入设置", ""] + [f"- {k}：{v}" for k, v in report_extra.items()] + [""]
    lines += [
        "## 方法", "",
        "首期和末期取每个点实际有值的最早、最晚一期；变化率=(末期-首期)/首期×100%；",
        "线性斜率使用全部有效时期回归，固定历史时间段时单位为每年；相对窗口仅表示窗口序号趋势。", "",
        "## 缺失值", "",
        f"长表保留原始缺失情况，共 {int(long['value'].isna().sum()) if not long.empty else 0} 个空值未参与统计。",
    ]
    if not stats.empty and "valid_count" in stats.columns:
        missing_metrics = (
            stats.groupby("metric", sort=False)["valid_count"]
            .sum()
            .loc[lambda s: s == 0]
            .index.tolist()
        )
        if missing_metrics:
            lines += [
                "", "## 全部缺失的指标", "",
                "以下指标在所选点位和时间范围内没有任何有效值，已保留在长表中，但不参与趋势统计：",
                "",
                *[f"- `{name}`" for name in missing_metrics],
            ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"long": str(long_path), "stats": str(stats_path), "report": str(report_path)}
