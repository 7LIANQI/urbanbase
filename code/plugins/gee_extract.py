"""从 Earth Engine 提取点位或缓冲区的指标，缺失值在 CSV 中留空。"""

import hashlib
import io
import os
import shutil
import threading
import time

import ee
import pandas as pd
import requests

from core.crs import to_wgs84
from plugins.gee_plugin import initialize_gee

GRANULARITY = {"年度": "year", "月度": "month"}
WINDOW_YEARS = {"cur": 0, "y1": 1, "y2": 2, "y3": 3, "y5": 5, "y10": 10}
TEMPORAL = {"中值（推荐）": "median", "均值": "mean", "最大值": "max", "最小值": "min"}
SPATIAL = {"均值（推荐）": "mean", "中值": "median"}


def window_label(key, gran):
    if key == "cur":
        return "当前（观测日所在" + ("月" if gran == "month" else "年") + "）"
    return f"前 {WINDOW_YEARS[key]} 年" + ("（12×%d 个月）" % WINDOW_YEARS[key] if gran == "month" else "")


def window_units(key, gran):
    """当前窗口取观测所在的年或月，回溯窗口取此前的 N 年。"""
    return 1 if key == "cur" else WINDOW_YEARS[key] * (12 if gran == "month" else 1)


def make_periods(start, end, step):
    """step: 'MS' 月 / 'YS' 年（也支持 'QS' 季）。返回 [(label, start, end)]，end 不含。"""
    offset = {"MS": pd.DateOffset(months=1), "QS": pd.DateOffset(months=3), "YS": pd.DateOffset(years=1)}[step]
    out = []
    for s in pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq=step):
        label = {"MS": s.strftime("%Y%m"), "QS": f"{s.year}Q{(s.month - 1) // 3 + 1}", "YS": str(s.year)}[step]
        out.append((f"P{label}", s.strftime("%Y-%m-%d"), (s + offset).strftime("%Y-%m-%d")))
    return out


def column_names(datasets, mode, windows, periods):
    cols = []
    for d in datasets:
        if d.mode == "static":
            cols += d.columns
        else:
            labels = windows if mode == "rel" else [p[0] for p in periods]
            cols += [f"{c}_{lab}" for lab in labels for c in d.columns]
    return cols


def add_label_columns(res, datasets):
    """为城乡分类等编码字段补充中文名称列，返回新增列名。"""
    added_columns = []
    for dataset in datasets:
        for code, mapping in dataset.labels.items():
            matching_columns = [col for col in res.columns if col == code or col.startswith(f"{code}_")]
            for column in matching_columns:
                label_column = f"{column}_名称"
                res[label_column] = pd.to_numeric(res[column], errors="coerce").round().map(mapping)
                added_columns.append(label_column)
    return added_columns


def _pmap(fn, items, workers, stop=None):
    """并行执行 fn(item)。线程是守护线程：收到停止信号后最多再等 2 秒就返回，
    正在等 GEE 响应的请求不会拖住程序退出。返回与 items 等长的结果列表（未完成的为 None）。"""
    import queue
    q = queue.Queue()
    for i, it in enumerate(items):
        q.put((i, it))
    results = [None] * len(items)

    def work():
        while True:
            if stop is not None and stop.is_set():
                return
            try:
                i, it = q.get_nowait()
            except queue.Empty:
                return
            results[i] = fn(it)

    ts = [threading.Thread(target=work, daemon=True) for _ in range(max(1, workers))]
    for t in ts:
        t.start()
    waited = 0.0
    while any(t.is_alive() for t in ts):
        for t in ts:
            t.join(0.2)
        if stop is not None and stop.is_set():
            waited += 0.2 * len(ts)
            if waited > 2.0:
                break
    return results


class _Ctx:
    def __init__(self, df, lon, lat, log=print):
        self.log = log
        pad = 0.2
        self.region = ee.Geometry.Rectangle([df[lon].min() - pad, df[lat].min() - pad,
                                             df[lon].max() + pad, df[lat].max() + pad])


def _point(f):
    """由属性里的原始经纬度重建点。链式 reduceRegions 会把要素的几何换成缓冲区，不能在它上面再缓冲。"""
    return ee.Geometry.Point([ee.Number(f.get("_lon")), ee.Number(f.get("_lat"))])


def _geom_for(f, ds, buffer_m):
    g = _point(f)
    # 缓冲半径小于半个像元时，缓冲区取不到像元中心 → 直接取点所在像元
    return g if buffer_m < ds.scale / 2 else g.buffer(buffer_m)


def _label(kind, y, m):
    return f"{y}{m:02d}" if kind == "month" else f"{y}"


def units_needed(dates, windows, gran):
    """这批点的所有窗口一共用到哪些时间单位 [(年, 月)]。"""
    from plugins.local_extract import units_for
    need = set()
    for d in dates:
        for w in windows:
            for _k, y, m in units_for(gran, d.year, d.month, w, gran):
                need.add((y, m if gran == "month" else 1))
    return sorted(need)


FILL_PAD_YEARS = 2


def pad_units(units_ym, gran, years=FILL_PAD_YEARS):
    """在窗口两端各多取 years 年的数据，供缺期时就近替代。"""
    if not units_ym:
        return units_ym
    monthly = gran == "month"
    padding = years * (12 if monthly else 1)
    indices = [year * 12 + month - 1 if monthly else year for year, month in units_ym]
    first, last = min(indices), max(indices)
    extra_indices = [*range(first - padding, first), *range(last + 1, last + padding + 1)]
    if monthly:
        extra_units = {(index // 12, index % 12 + 1) for index in extra_indices}
    else:
        extra_units = {(index, 1) for index in extra_indices}
    return sorted(set(units_ym) | extra_units)


def unit_columns(ds, labels, gran):
    if ds.kind == "vector" or ds.mode == "static":
        return list(ds.columns)
    return [f"{c}__{lab}" for lab in labels for c in ds.columns]


def _vector_props(fc, ds, comps, region):
    return comps[ds.key](fc, region, _point)


def _multi(img):
    """reduceRegions 对单波段影像会把结果属性命名为归约器名（如 mean）而不是波段名，于是整列取不到。
    补一个占位波段，保证至少两个波段，属性才按波段名输出（占位波段不会被导出）。"""
    return img.addBands(ee.Image.constant(0).rename("padband"))


def _table(fc, ds, comps, units, gran, buffer_m, temporal, spatial, region, crs=None):
    """把各年或月的合成影像叠成多波段，一次提取整批点。"""
    if ds.kind == "vector":
        return _vector_props(fc, ds, comps, region)
    sp = getattr(ee.Reducer, ds.spatial or spatial)()
    red = ds.temporal or temporal
    if ds.mode == "static":
        img = comps[ds.key](None, None, red, region)
    else:
        imgs = []
        for y, m, lab, rename in units:
            st = ee.Date.fromYMD(y, m, 1)
            imgs.append(comps[ds.key](st, st.advance(1, gran if gran in ("year", "month") else "year"), red, region)
                        .rename([f"{c}{rename}" for c in ds.columns]))
        img = ee.Image.cat(imgs)
    fcg = fc.map(lambda f: f.setGeometry(_geom_for(f, ds, buffer_m)))
    kw = {"crs": crs} if crs else {}
    return _multi(img).reduceRegions(fcg, sp, ds.scale, tileScale=16, **kw)


def _rel_units(units_ym, gran):
    units = []
    for year, month in units_ym:
        label = _label(gran, year, month)
        units.append((year, month, label, f"__{label}"))
    return units


def _apply_seq(fc, datasets, comps, buffer_m, periods, temporal, spatial, region, crs=None):
    for ds in datasets:
        if ds.mode == "static" or ds.kind == "vector":
            fc = _table(fc, ds, comps, None, "year", buffer_m, temporal, spatial, region, crs)
            continue
        sp = getattr(ee.Reducer, ds.spatial or spatial)()
        red = ds.temporal or temporal
        imgs = [comps[ds.key](ee.Date(st), ee.Date(en), red, region).rename([f"{c}_{label}" for c in ds.columns])
                for label, st, en in periods]
        fcg = fc.map(lambda f, ds=ds: f.setGeometry(_geom_for(f, ds, buffer_m)))
        kw = {"crs": crs} if crs else {}
        fc = _multi(ee.Image.cat(imgs)).reduceRegions(fcg, sp, ds.scale, tileScale=16, **kw)
    return fc


def _lab_idx(gran, lab):
    return int(lab[:4]) * 12 + int(lab[4:6]) - 1 if gran == "month" else int(lab)


def windows_from_units(res, work, datasets, windows, gran, temporal, cols, fill=True):
    """把「每点每单位的值」汇总成各窗口的值。返回 (DataFrame[_row + cols], 诊断 dict)。
    窗口内缺失的单位不参与；整个窗口都没有值时（fill=True）改用离窗口最近的一期（前后等距取较早），
    诊断里记下 sub（是否替代）和 gap（相差几年）。"""
    import warnings
    import numpy as np
    from plugins.local_extract import _mode, units_for
    res = res.drop_duplicates("_row").reset_index(drop=True)
    rows = res["_row"].to_numpy()
    dts = pd.to_datetime(work.set_index("_row")["_date"]).reindex(rows)
    num = {c: pd.to_numeric(res[c], errors="coerce").to_numpy(float) for c in res.columns if c != "_row"}
    red_f = {"median": np.nanmedian, "mean": np.nanmean, "max": np.nanmax, "min": np.nanmin}
    out = {"_row": rows}
    used, expected, subd, gapd = {}, {}, {}, {}
    n = len(rows)
    for ds in datasets:
        red = ds.temporal or temporal
        if ds.kind == "vector" or ds.mode == "static":
            for c in ds.columns:
                out[c] = res[c].to_numpy() if c in res.columns else np.full(n, np.nan)
                used[c], expected[c] = np.zeros(n, int), np.zeros(n, int)
                subd[c], gapd[c] = np.zeros(n, bool), np.zeros(n)
            continue
        for c in ds.columns:
            have = sorted((_lab_idx(gran, k.split("__", 1)[1]), num[k]) for k in num if k.startswith(c + "__"))
            for w in windows:
                col = f"{c}_{w}"
                vals, us, ex = np.full(n, np.nan), np.zeros(n, int), np.zeros(n, int)
                sb, gp = np.zeros(n, bool), np.zeros(n)
                for i in range(n):
                    d = dts.iloc[i]
                    if pd.isna(d):
                        continue
                    labs = [_label(gran, y, m) for _k, y, m in units_for(gran, d.year, d.month, w, gran)]
                    ex[i] = len(labs)
                    v = np.array([num[f"{c}__{lab}"][i] for lab in labs if f"{c}__{lab}" in num], float)
                    v = v[~np.isnan(v)]
                    us[i] = v.size
                    if v.size:
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            vals[i] = _mode(v) if red == "mode" else float(red_f[red](v))
                    elif fill and labs and have:                  # 整个窗口都没有值：取离窗口最近的一期
                        wi = [_lab_idx(gran, l) for l in labs]
                        lo, hi = min(wi), max(wi)
                        below = [(lo - ix, 0, a[i]) for ix, a in have if ix < lo and not np.isnan(a[i])]
                        above = [(ix - hi, 1, a[i]) for ix, a in have if ix > hi and not np.isnan(a[i])]
                        pick = min(max(below, key=lambda t: -t[0]) if below else (1e9, 0, 0),
                                   min(above, key=lambda t: t[0]) if above else (1e9, 1, 0), key=lambda t: (t[0], t[1]))
                        if pick[0] < 1e9:
                            vals[i], us[i], sb[i], gp[i] = pick[2], 1, True, pick[0] / (12.0 if gran == "month" else 1.0)
                out[col], used[col], expected[col], subd[col], gapd[col] = vals, us, ex, sb, gp
    fin = pd.DataFrame(out)
    diag_cols = [c for c in cols if c in used]
    stack = lambda d, z: np.column_stack([d[c] for c in diag_cols]) if diag_cols else np.zeros((n, 0), z)
    return fin, dict(cols=diag_cols, rows=rows, used=stack(used, int), expected=stack(expected, int),
                     sub=stack(subd, bool), gap=stack(gapd, float))


def run(df, lon_col, lat_col, date_col, datasets, buffer_m, mode, windows, periods,
        temporal, spatial, out_csv, key=None, batch=100, workers=3, crs="wgs84", epsg=None, gran="year",
        log=print, progress=lambda done, total: None, stop=None, info=None, fill=True):
    """返回输出 CSV 路径；被停止或有批次失败返回 None（重新运行可断点续跑）。"""
    if not initialize_gee(key, log):
        return None
    df = df.reset_index(drop=True).copy()
    df["_row"] = df.index
    x = pd.to_numeric(df[lon_col], errors="coerce")
    y = pd.to_numeric(df[lat_col], errors="coerce")
    try:
        df["_lon"], df["_lat"] = to_wgs84(x, y, crs, epsg)
    except Exception as e:
        log(f"❌ 坐标转换失败（坐标系 {crs} {epsg or ''}）: {e}")
        return None
    ok = df["_lon"].between(-180, 180) & df["_lat"].between(-90, 90)
    if ok.sum() == 0 or (crs != "wgs84" and (~ok).all()):
        log("❌ 转换后坐标超出经纬度范围，请检查「坐标系」设置和经纬度列是否选反")
        return None
    if mode == "rel":
        df["_date"] = pd.to_datetime(df[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
        ok &= df["_date"].notna()
    else:
        df["_date"] = ""
    if (~ok).any():
        log(f"⚠️ {int((~ok).sum())} 行坐标或日期无效，对应结果留空")
    work = df[ok]
    if work.empty:
        log("❌ 没有可处理的点")
        return None

    ctx = _Ctx(work, "_lon", "_lat", log)
    log("准备数据源…")
    comps = {d.key: d.build(ctx) for d in datasets}
    cols = column_names(datasets, mode, windows, periods)

    sig = repr((sorted(d.key for d in datasets), crs, epsg, gran, buffer_m, mode, windows, periods, temporal, spatial,
                batch, len(work), float(work["_lon"].sum()), float(work["_lat"].sum()), "pad" if fill else ""))
    # 断点续跑的批次缓存放在用户目录里（不污染输出文件夹），完整跑完后删除
    cache = os.path.join(os.path.expanduser("~/.urbansense/cache"),
                         f"{os.path.basename(os.path.splitext(out_csv)[0])}_{hashlib.md5((sig + out_csv).encode()).hexdigest()[:8]}")
    os.makedirs(cache, exist_ok=True)

    chunks = [(i, work.iloc[i:i + batch]) for i in range(0, len(work), batch)]
    done = [0]

    bad = {}                                   # 被判定有问题的数据源：key -> 错误信息
    lock = threading.Lock()
    state = {"probed": False, "event": threading.Event()}

    def active():
        return [d for d in datasets if d.key not in bad]

    def fetch(chunk, ds_list):
        """请求一批点的结果，返回 DataFrame；GEE 的错误原因（超时、内存不足等）写在响应内容里，一并带出来。"""
        fc = ee.FeatureCollection([
            ee.Feature(ee.Geometry.Point([float(lo), float(la)]), {"_row": int(rw), "_date": dt, "_lon": float(lo), "_lat": float(la)})
            for lo, la, rw, dt in zip(chunk["_lon"], chunk["_lat"], chunk["_row"], chunk["_date"])])
        pad = 0.3                                   # 本批点的外包范围（景级数据源只在这个范围里找影像）
        region = ee.Geometry.Rectangle([float(chunk["_lon"].min()) - pad, float(chunk["_lat"].min()) - pad,
                                        float(chunk["_lon"].max()) + pad, float(chunk["_lat"].max()) + pad])
        if mode == "rel":
            units_ym = units_needed(pd.to_datetime(chunk["_date"]), windows, gran)
            if fill:
                units_ym = pad_units(units_ym, gran)
            units = _rel_units(units_ym, gran)
            labels = [u[2] for u in units]
            for d in ds_list:
                fc = _table(fc, d, comps, units, gran, buffer_m, temporal, spatial, region, state.get("crs"))
            sel = ["_row"] + [c for d in ds_list for c in unit_columns(d, labels, gran)]
        else:
            fc = _apply_seq(fc, ds_list, comps, buffer_m, periods, temporal, spatial, region, state.get("crs"))
            sel = ["_row"] + column_names(ds_list, mode, windows, periods)
        url = fc.getDownloadURL("csv", selectors=sel)
        resp = requests.get(url, timeout=900)
        if resp.status_code != 200:
            detail = resp.text.strip().replace("\n", " ")[:600]
            raise RuntimeError(f"HTTP {resp.status_code}：{detail}")
        return pd.read_csv(io.BytesIO(resp.content))

    def probe(chunk):
        """某批失败后，逐个数据源用少量点单独请求一次，找出到底是哪个数据源出问题。"""
        with lock:
            first = not state["probed"]
            state["probed"] = True
        if not first:                           # 别的线程正在定位，等它做完再继续，避免重复请求
            state["event"].wait(600)
            return
        sample = chunk.iloc[:3]
        log("🔎 逐个数据源单独测试，定位出问题的数据源…")
        for d in list(datasets):
            try:
                fetch(sample, [d])
                log(f"   ✓ {d.label}：单独请求正常")
            except Exception as e:
                bad[d.key] = str(e)
                log(f"   ❌ 数据源「{d.label}」（{d.gee_id}）单独请求也失败：{e}")
        if bad:
            log(f"⚠️ 以下数据源将被跳过，其输出列留空：{'、'.join(d.label for d in datasets if d.key in bad)}")
        else:
            log("各数据源单独请求都正常，问题出在同时计算太多（内存或时间），将自动拆小批次重试")
        state["event"].set()

    def fetch_adaptive(chunk, tag):
        """失败时先重试一次；仍失败就定位出问题的数据源，必要时对半拆开分别请求。"""
        last = None
        for attempt in (1, 2):
            if stop is not None and stop.is_set():
                return None
            if not active():
                return pd.DataFrame({"_row": chunk["_row"].values})
            try:
                return fetch(chunk, active())
            except Exception as e:
                last = e
                log(f"⚠️ {tag}（{len(chunk)} 点，{len(active())} 个数据源）第 {attempt} 次失败: {e}")
                if "Unable to transform geometry" in str(e) and not state.get("crs"):
                    state["crs"] = "EPSG:4326"          # 几何投影变换失败：改为显式指定提取用的坐标系再试
                    log("↪ 改用显式坐标系 EPSG:4326 重新提取")
                    continue
                if attempt == 1:
                    probe(chunk)
        if len(chunk) > 5:
            mid = len(chunk) // 2
            log(f"↪ {tag} 拆成 {mid} + {len(chunk) - mid} 个点重试")
            a = fetch_adaptive(chunk.iloc[:mid], tag + "a")
            b = fetch_adaptive(chunk.iloc[mid:], tag + "b")
            return None if a is None or b is None else pd.concat([a, b])
        log(f"❌ {tag} 无法完成：{last}")
        return None

    def one(item):
        i, chunk = item
        path = os.path.join(cache, f"batch_{i:06d}.csv")
        if os.path.exists(path):
            done[0] += 1
            progress(done[0], len(chunks))
            return path
        t0 = time.time()
        log(f"→ 批次 {i // batch + 1}/{len(chunks)}：提交 {len(chunk)} 个点 × {len(active())} 个数据源，等待 GEE 计算…")
        df_ = fetch_adaptive(chunk, f"批次 {i // batch + 1}")
        if df_ is None:
            return None
        df_.to_csv(path, index=False)
        done[0] += 1
        progress(done[0], len(chunks))
        log(f"批次 {i // batch + 1}/{len(chunks)} 完成（用时 {time.time() - t0:.0f} 秒）")
        return path

    paths = _pmap(one, chunks, workers, stop)
    if any(p is None for p in paths):
        log("⚠️ 未全部完成（被停止或部分批次失败），重新运行同样设置即可续跑")
        return None
    res = pd.concat(pd.read_csv(p) for p in paths)
    diag = None
    if mode == "rel":
        log("按窗口汇总（先逐年/月提取，再在本地计算窗口值）…")
        fin, diag = windows_from_units(res, work, datasets, windows, gran, temporal, cols, fill)
        res = fin
    for c in cols:                      # 某列全空时 GEE 可能不输出，补空列保持列齐全
        if c not in res.columns:
            res[c] = pd.NA
    cols += add_label_columns(res, datasets)
    if crs not in ("wgs84", "cgcs2000"):          # 非 WGS84 输入时，附上转换后的坐标便于核对
        df["LON_WGS84"], df["LAT_WGS84"] = df["_lon"], df["_lat"]
    dup = [c for c in cols if c in df.columns]
    if dup:
        log(f"⚠️ 输入表里已有 {len(dup)} 个同名列（如 {dup[0]}），将被本次结果覆盖（移到表尾）")
    out = df.drop(columns=["_lon", "_lat", "_date"] + dup).merge(res[["_row"] + cols], on="_row", how="left").drop(columns="_row")
    out.to_csv(out_csv, index=False, encoding="utf-8-sig")
    meta = {"时间粒度": {"year": "年度", "month": "月度"}[gran], "模式": "回溯窗口" if mode == "rel" else "时间段序列",
            "窗口": windows if mode == "rel" else [p[0] for p in periods], "缓冲区(m)": buffer_m,
            "处理方式": "先按年/月合成并在每个点提取，再在点上汇总各窗口（空间聚合在前，时间聚合在后）",
            "时间聚合": temporal, "空间聚合": spatial, "输入坐标系": f"{crs} {epsg or ''}".strip(),
            "失败的数据源": {k: v for k, v in bad.items()},
            "数据源": {d.key: {"名称": d.label, "GEE": d.gee_id, "列": d.columns,
                          "数据性质": {"model": "模式数据（再分析）", "blend": "插值融合"}.get(d.origin, "观测或遥感反演")}
                      for d in datasets}}
    if info is not None:
        info["meta"] = meta                          # 提取设置并入采集报告，不再单独写 json
    shutil.rmtree(cache, ignore_errors=True)         # 已完整跑完，批次缓存不再需要
    if info is not None and diag is not None:       # 对齐到全部输入行，供采集报告使用
        import numpy as np
        pos = {r: k for k, r in enumerate(diag["rows"])}
        n_all = len(df)
        shp = (n_all, len(diag["cols"]))
        full_u, full_e, full_s, full_g = np.zeros(shp, int), np.zeros(shp, int), np.zeros(shp, bool), np.zeros(shp)
        for r, k in pos.items():
            full_u[r], full_e[r], full_s[r], full_g[r] = diag["used"][k], diag["expected"][k], diag["sub"][k], diag["gap"][k]
        reason = np.where((full_e > 0) & (full_u == 0), "窗口内没有有效值（无影像、被云或质量标记剔除，或超出数据覆盖时间）", "").astype(object)
        info["diag"] = dict(cols=diag["cols"], used=full_u, expected=full_e, reason=reason, sub=full_s, gap=full_g)
    if info is not None:
        info["bad"] = {d.key: (d.label, bad[d.key]) for d in datasets if d.key in bad}
    log(f"✅ 已保存: {out_csv}（{len(out)} 行，新增 {len(cols)} 列）" + (f"；{len(bad)} 个数据源因出错被跳过" if bad else ""))
    return out_csv
