"""GEE 提取的整体流程（分批、请求、合并、窗口汇总、输出）——用假的 ee 和假的网络，不联网。
这类测试专门防止「流程里漏了一行/变量没定义」这种只有真正联网跑才会暴露的低级错误。"""
import io

import pandas as pd

from plugins import gee_catalog as C
from plugins import gee_extract as G


class _Any:
    """假 ee 对象：任意属性/调用都返回自己，同时把点的行号和下载列（selectors）传下去。"""

    def __init__(self, rows=None):
        self.rows = rows or []

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: _Any(self.rows)

    def apply(self, primary, *a, **k):                # Join.apply：返回主集合（点），行不变
        return primary

    def reduceRegions(self, fc, *a, **k):          # 真实行为：返回带上提取结果的点集合（行不变）
        return fc

    def __call__(self, *a, **k):
        return _Any(self.rows)

    def getDownloadURL(self, fmt, selectors=None):
        _Any.last = (list(self.rows), list(selectors))
        return "http://fake"


class _FakeEE:
    class Feature(_Any):
        def __init__(self, geom=None, props=None):
            super().__init__([props["_row"]] if props and "_row" in props else [])

    class FeatureCollection(_Any):
        def __init__(self, feats=None):
            super().__init__([] if isinstance(feats, str) else [r for f in (feats or []) for r in f.rows])   # 传入表 ID 时没有行

    def __getattr__(self, name):
        return _Any()


class _Resp:
    status_code = 200

    def __init__(self, content):
        self.content = content.encode()
        self.text = content


def _fake_get(url, timeout=0):
    rows, sel = _Any.last
    lines = [",".join(sel)]
    for r in rows:
        lines.append(",".join(str(r) if s == "_row" else str(float(r + 1)) for s in sel))
    return _Resp("\n".join(lines))


def test_gee_flow(tmp_path, monkeypatch):
    fake = _FakeEE()
    monkeypatch.setattr(G, "ee", fake)
    monkeypatch.setattr(C, "ee", fake)
    monkeypatch.setattr(G, "initialize_gee", lambda *a, **k: True)
    monkeypatch.setattr(G.requests, "get", _fake_get)
    ds = [C.SOURCE_BY_KEY["t2m.era5"], C.SOURCE_BY_KEY["lst.aqua8"], C.SOURCE_BY_KEY["urban.smod"]]
    df = pd.DataFrame({"id": ["a", "b", "c"], "lon": [113.2, 75.9, 999.0], "lat": [23.1, 39.4, 23.1],
                       "date": ["2021-06-01", "2020-01-10", "2021-06-01"]})
    info = {}
    out = G.run(df, "lon", "lat", "date", ds, 1000, "rel", ["cur", "y1"], [], "median", "mean",
                str(tmp_path / "o.csv"), batch=2, workers=1, gran="year", log=lambda *_: None, info=info)
    assert out is not None
    res = pd.read_csv(out, encoding="utf-8-sig")
    cols = G.column_names(ds, "rel", ["cur", "y1"], [])
    assert set(cols) <= set(res.columns) and len(res) == 3
    # 假数据里每个单位的值 = 行号 + 1：第 0 行 cur = 1；第 1 行 y1 = 2；坐标无效的第 2 行为空
    assert res.loc[0, cols[0]] == 1.0 and res.loc[1, cols[0]] == 2.0
    assert res.loc[2, cols].isna().all()
    assert info["diag"]["cols"] and not info["bad"]

    # 时间段序列模式同样要走通
    out2 = G.run(df.iloc[:2], "lon", "lat", "date", ds, 0, "seq", [], G.make_periods("2020-01-01", "2021-12-31", "YS"),
                 "median", "mean", str(tmp_path / "s.csv"), batch=5, workers=1, gran="year", log=lambda *_: None)
    seq_cols = G.column_names(ds, "seq", [], G.make_periods("2020-01-01", "2021-12-31", "YS"))
    assert set(seq_cols) <= set(pd.read_csv(out2, encoding="utf-8-sig").columns)


def test_pmap_stops_quickly():
    """收到停止信号后，即使有任务卡在慢请求里，也要在几秒内返回（线程为守护线程，不拖住程序退出）。"""
    import threading
    import time
    stop = threading.Event()
    t0 = time.time()
    threading.Timer(0.3, stop.set).start()
    res = G._pmap(lambda x: (time.sleep(30), x)[1], [1, 2, 3], 3, stop)
    assert time.time() - t0 < 5 and res == [None, None, None]
    assert G._pmap(lambda x: x * 2, [1, 2, 3, 4], 2) == [2, 4, 6, 8]


def test_single_band_gets_pad_band(monkeypatch):
    """reduceRegions 对单波段影像把属性命名成「mean」而不是波段名，整列就取不到（Hansen、时间段序列的单列数据源都因此全空）。
    所有提取路径都要补占位波段，保证至少两个波段。"""
    monkeypatch.setattr(G, "ee", _FakeEE())
    calls = []

    class _Img:
        def addBands(self, other):
            calls.append("pad")
            return self

    G._multi(_Img())
    assert calls == ["pad"]
