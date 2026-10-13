"""本地提取引擎：用合成栅格库核对窗口、粒度、缓冲区、缩放、众数、缺期。"""
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin

from core import raster_catalog as RC
from plugins import local_extract as LE


def _tif(path, arr, nodata=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1, dtype=arr.dtype,
                       crs="EPSG:4326", transform=from_origin(100, 30, 0.01, 0.01), nodata=nodata) as d:
        d.write(arr, 1)


def _lib(root):
    # 月序列：值 = 月序号（2019-01 为 1）；2020-03 缺失
    m = RC.Series(id="t_m", temporal="month", scale=0.1, folder=root / "t2m" / "t_m")
    m.save()
    for i, (y, mo) in enumerate((y, mo) for y in (2019, 2020, 2021) for mo in range(1, 13)):
        if (y, mo) != (2020, 3):
            _tif(m.folder / str(y) / f"t_m_{y}{mo:02d}.tif", np.full((20, 20), i + 1, "int16"), -9999)
    # 年序列：值 = 年份差
    y_ = RC.Series(id="p_y", temporal="year", folder=root / "airq" / "p_y")
    y_.save()
    for y in (2019, 2020, 2021):
        _tif(y_.folder / f"p_y_{y}.tif", np.full((20, 20), float(y - 2000), "float32"), np.nan)
    # 静态分类：左半 1，右半 2
    c = np.ones((20, 20), "uint8")
    c[:, 10:] = 2
    s_ = RC.Series(id="c_s", temporal="static", categorical=True, folder=root / "forest" / "c_s")
    s_.save()
    _tif(s_.folder / "c_s.tif", c, 0)
    return [m, y_, s_]


def test_local_extract(tmp_path):
    ser = _lib(tmp_path)
    df = pd.DataFrame({"lon": [100.05, 100.15], "lat": [29.95, 29.95], "date": ["2021-05-15", "2021-05-15"]})
    kw = dict(df=df, lon_col="lon", lat_col="lat", date_col="date", series=ser, buffer_m=0, mode="rel",
              windows=["cur", "y1"], periods=[], temporal="median", spatial="mean", workers=1)
    res, cols = LE.run(**kw, gran="month")
    assert cols == ["t_m_cur", "t_m_y1", "p_y_cur", "p_y_y1", "c_s"]
    # 月度：cur = 2021-05 → 序号 29，×0.1；y1 = 前 12 个月 2020-05..2021-04 的中值（序号 17..28，中值 22.5）
    assert abs(res.loc[0, "t_m_cur"] - 2.9) < 1e-9 and abs(res.loc[0, "t_m_y1"] - 2.25) < 1e-9
    # 年度数据在月度粒度下，每个月取所在年份：cur = 2021 → 21；y1 = 前 12 个月（2020 年 5–12 月共 8 个月、2021 年 1–4 月共 4 个月）→ 中值 20
    assert res.loc[0, "p_y_cur"] == 21.0 and res.loc[0, "p_y_y1"] == 20.0
    # 分类静态数据取点所在像元：左点=1，右点=2
    assert res["c_s"].tolist() == [1.0, 2.0]
    # 年度粒度：cur = 2021 年的月序列合成（12 个月中值 = 30.5×0.1）；y1 = 2020 年（缺 3 月，其余 11 个月中值）
    res2, _ = LE.run(**kw, gran="year")
    assert abs(res2.loc[0, "t_m_cur"] - 3.05) < 1e-9
    v2020 = np.median([i for i in range(13, 25) if i != 15]) * 0.1
    assert abs(res2.loc[0, "t_m_y1"] - v2020) < 1e-9 and res2.loc[0, "p_y_y1"] == 20.0
    # 缓冲区：跨左右两个类别的点，分类取众数；半径小于半个像元时取点所在像元
    df3 = pd.DataFrame({"lon": [100.10], "lat": [29.95], "date": ["2021-05-15"]})
    k3 = dict(kw, df=df3, series=[ser[2]], windows=["cur"], buffer_m=3000)
    r3, _ = LE.run(**k3, gran="year")
    assert r3.loc[0, "c_s"] in (1.0, 2.0)
    # 超出时间覆盖（2025 年）：关闭「最近一期替代」时全部为空
    df4 = pd.DataFrame({"lon": [100.05], "lat": [29.95], "date": ["2025-05-15"]})
    r4, _ = LE.run(**dict(kw, df=df4, series=ser[:2]), gran="month", fill=False)
    assert r4.isna().all().all()
    # 打开时：cur 用最近的一期（月序列 2021-12，序号 36；年序列 2021 → 21），并在 diag 里记下替代和偏差
    dg = {}
    r5, c5 = LE.run(**dict(kw, df=df4, series=ser[:2]), gran="month", diag=dg)
    assert abs(r5.loc[0, "t_m_cur"] - 3.6) < 1e-9 and r5.loc[0, "p_y_cur"] == 21.0
    k = dg["cols"].index("t_m_cur")
    assert dg["sub"][0, k] and abs(dg["gap"][0, k] - 41 / 12) < 1e-9   # 2025-05 到 2021-12 差 41 个月
    assert dg["sub"][0, dg["cols"].index("p_y_cur")] and dg["gap"][0, dg["cols"].index("p_y_cur")] == 4.0


def test_nearest_fill_rules(tmp_path):
    """年序列只有 2010、2015、2020：窗口里有数据就只平均已有的；整个窗口都没有才取最近一期（前后等距取较早）。"""
    s = RC.Series(id="g", temporal="year", folder=tmp_path / "gdp" / "g")
    s.save()
    for y in (2010, 2015, 2020):
        _tif(s.folder / f"g_{y}.tif", np.full((5, 5), float(y), "float32"), np.nan)
    df = pd.DataFrame({"lon": [100.02] * 4, "lat": [29.98] * 4, "date": ["2018-06-01", "2022-06-01", "2012-06-01", "2025-06-01"]})
    kw = dict(df=df, lon_col="lon", lat_col="lat", date_col="date", series=[s], buffer_m=0, mode="rel",
              windows=["cur", "y3"], periods=[], temporal="mean", spatial="mean", workers=1, gran="year")
    dg = {}
    r, cols = LE.run(**kw, diag=dg)
    # 2018：cur 无 → 最近 2020（差 2）而不是 2015（差 3）；y3 = 2015–2017 里只有 2015 → 2015
    assert r["g_cur"].tolist() == [2020.0, 2020.0, 2010.0, 2020.0]
    assert r.loc[0, "g_y3"] == 2015.0
    # 2022：y3 = 2019–2021 里只有 2020；2025：y3 = 2022–2024 整个都没有 → 2020（差 2）
    assert r.loc[1, "g_y3"] == 2020.0 and r.loc[3, "g_y3"] == 2020.0
    # 2012：cur 无，2010 差 2、2015 差 3 → 2010
    kc, k3 = dg["cols"].index("g_cur"), dg["cols"].index("g_y3")
    assert dg["sub"][:, kc].tolist() == [True, True, True, True] and dg["gap"][:, kc].tolist() == [2.0, 2.0, 2.0, 5.0]
    assert dg["sub"][:, k3].tolist() == [False, False, False, True] and dg["gap"][3, k3] == 2.0


def test_vector_point_in_polygon(tmp_path):
    """矢量面（行政区划）：点在面内、就近匹配、超出距离留空；省名查表、代码切片。"""
    import geopandas as gpd
    from shapely.geometry import box
    g = gpd.GeoDataFrame({"name": ["甲县", "乙区"], "gb": ["156440904", "156110101"]},
                         geometry=[box(110, 21, 111, 22), box(116, 39, 117, 40)], crs=4490)
    folder = tmp_path / "admin" / "cn"
    folder.mkdir(parents=True)
    g.to_file(folder / "cn.geojson", driver="GeoJSON")
    s = RC.Series(id="cn", kind="vector", temporal="static", nearest_m=5000.0, folder=folder,
                  attributes={"县": "name", "县代码": "gb[3:9]", "省": "gb[3:5]|cn_province"})
    s.save()
    pd.DataFrame({"code": ["44"], "name": ["广东省"]}).to_csv(folder / "lookup_prov.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame({"code": ["4409"], "name": ["茂名市"]}).to_csv(folder / "lookup_city.csv", index=False, encoding="utf-8-sig")
    s.attributes.update({"省表": "gb[3:5]|table:prov", "市表": "gb[3:7]|table:city"})
    s.save()
    lon = np.array([110.5, 111.02, 113.0, np.nan])
    lat = np.array([21.5, 21.5, 30.0, 30.0])
    v = LE.vector_values(RC.Series.load(folder), lon, lat)
    assert v.loc[0, "县"] == "甲县" and v.loc[0, "省"] == "广东省" and v.loc[0, "县代码"] == "440904"
    assert v.loc[0, "cn_match"] == "点在面内"        # vector_values 仍返回匹配方式，供诊断
    assert v.loc[0, "省表"] == "广东省" and v.loc[0, "市表"] == "茂名市"                                   # |table: 查 lookup_*.csv
    assert v.loc[1, "县"] == "甲县" and v.loc[1, "cn_match"] == "就近匹配" and 1500 < v.loc[1, "cn_dist_m"] < 2500   # 约 2 km
    assert v.loc[2, "县"] is None and v.loc[3, "县"] is None                                              # 太远 / 坐标无效
    # 通过 run() 走完整流程，列名与 column_names 一致
    df = pd.DataFrame({"lon": lon[:3], "lat": lat[:3], "date": ["2020-01-01"] * 3})
    res, cols = LE.run(df, "lon", "lat", "date", [RC.Series.load(folder)], 0, "rel", ["cur"], [], "median", "mean", workers=1)
    assert cols == ["县", "县代码", "省", "省表", "市表"] and res.loc[0, "县"] == "甲县"


def test_append_runs(tmp_path):
    """追加模式：第二次提取的新列接在第一次的输出后面；报告按「第 N 次」合并；gpkg 含全部列；行数不同则拒绝。"""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication([])
    from ui.pages.extract_widget import _Worker
    import geopandas as gpd
    ser = _lib(tmp_path)
    df = pd.DataFrame({"lon": [100.05, 100.15], "lat": [29.95, 29.95], "date": ["2021-05-15", "2021-05-15"], "备注": ["甲", "乙"]})
    out = str(tmp_path / "res.csv")
    base = dict(lon_col="lon", lat_col="lat", date_col="date", buffer_m=0, mode="rel", windows=["cur"], periods=[],
                temporal="median", spatial="mean", crs="wgs84", epsg=4326, gran="year", fill=True, workers=1)

    def run(series, append, d=df):
        w = _Worker(None, dict(base, df=d, series=series), out, append)
        w.geo_cols = ("lon", "lat")
        errs = []
        w.failed.connect(errs.append)
        w.run()
        return errs

    assert run([ser[1]], False) == []
    assert run([ser[0]], True) == []
    r = pd.read_csv(out, encoding="utf-8-sig")
    assert r.columns.tolist() == ["lon", "lat", "date", "备注", "p_y_cur", "t_m_cur"]          # 原有列在前，新列依次接在后面
    assert r["p_y_cur"].notna().all() and r["t_m_cur"].notna().all()
    g = gpd.read_file(str(tmp_path / "res.gpkg"))
    assert {"p_y_cur", "t_m_cur"} <= set(g.columns) and len(g) == 2
    md = open(str(tmp_path / "res_采集报告.md"), encoding="utf-8").read()
    assert "## 第 1 次提取" in md and "## 第 2 次提取" in md and "共 2 次提取" in md and md.count("## 缺期处理规则") == 1
    # 同名列：再追加同一个序列只更新，不重复
    assert run([ser[0]], True) == []
    assert pd.read_csv(out, encoding="utf-8-sig").columns.tolist() == ["lon", "lat", "date", "备注", "p_y_cur", "t_m_cur"]
    # 行数不一致：报错，原文件不动
    errs = run([ser[0]], True, df.iloc[:1])
    assert errs and "行数不同" in errs[0]
    assert len(pd.read_csv(out, encoding="utf-8-sig")) == 2
    # 不追加：覆盖成只有本次的列
    assert run([ser[1]], False) == []
    assert pd.read_csv(out, encoding="utf-8-sig").columns.tolist() == ["lon", "lat", "date", "备注", "p_y_cur"]
