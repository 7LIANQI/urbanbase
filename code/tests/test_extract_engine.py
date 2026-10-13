"""提取引擎中不依赖 GEE 联网的部分：时间粒度、窗口单位数、输出列名、时间段序列。"""
from plugins import gee_catalog as C
from plugins import gee_extract as G


def test_granularity_and_columns():
    assert G.window_units("cur", "year") == 1 and G.window_units("cur", "month") == 1
    assert G.window_units("y3", "year") == 3 and G.window_units("y3", "month") == 36
    assert G.window_units("y10", "month") == 120
    ds = [C.SOURCE_BY_KEY[k] for k in ("pop.ghs", "dem.srtm", "ntl.blackmarble")]
    # 逐年数据（人口）也按窗口输出；静态数据（DEM）只有一列
    cols = G.column_names(ds, "rel", ["cur", "y3"], [])
    assert cols == ["POPD_GHS_cur", "POPD_GHS_y3", "ELEV_SRTM", "SLOPE_SRTM", "NTL_BM_cur", "NTL_BM_y3"]
    per = G.make_periods("2020-01-01", "2020-03-31", "MS")
    assert [p[0] for p in per] == ["P202001", "P202002", "P202003"]
    seq = G.column_names(ds[:2], "seq", [], per)
    assert seq.count("ELEV_SRTM") == 1 and "POPD_GHS_P202002" in seq     # 年度数据在月度序列里每月一列（值相同）


def test_new_sources_and_labels():
    import pandas as pd
    ur = C.SOURCE_BY_KEY["urban.smod"]
    assert "admin.gaul" not in C.SOURCE_BY_KEY            # 在线行政区划已移除，行政区划改用本地矢量
    assert ur.temporal == "mode" and ur.spatial == "mode" and ur.mode == "nearest"
    # 窗口列 + 代码转名称
    res = pd.DataFrame({"_row": [0, 1], "SMOD_GHS_y3": [30.0, None], "DEGURBA1_GHS_y3": [3.0, 1.0]})
    new = G.add_label_columns(res, [ur])
    assert new == ["SMOD_GHS_y3_名称", "DEGURBA1_GHS_y3_名称"]
    assert res["SMOD_GHS_y3_名称"][0] == "城市中心" and pd.isna(res["SMOD_GHS_y3_名称"][1]) and res["DEGURBA1_GHS_y3_名称"][1] == "乡村"
    # 主题顺序：区域与城乡不应被拆开
    assert [c.theme for c in C.CATEGORIES].count("区域与城乡") == 1
    themes = [c.theme for c in C.CATEGORIES]
    assert themes == sorted(themes, key=lambda t: list(dict.fromkeys(themes)).index(t))


def test_units_and_windows():
    """GEE 提取的新流程中不依赖联网的部分：需要哪些时间单位、如何从「点×单位」表汇总窗口。"""
    import numpy as np
    import pandas as pd
    dates = pd.to_datetime(["2021-05-15", "2020-01-10"])
    need = G.units_needed(dates, ["cur", "y1"], "month")
    assert (2021, 5) in need and (2020, 5) in need and (2019, 1) in need and (2018, 12) not in need   # 2020-01 的前 12 个月是 2019-01..2019-12
    assert G.units_needed(dates, ["y3"], "year") == [(2017, 1), (2018, 1), (2019, 1), (2020, 1)]
    # 年度粒度：点 0 观测年 2021，前 3 年 = 2018、2019、2020；2019 缺值
    ds = C.SOURCE_BY_KEY["ntl.viirs_annual"]
    col = ds.columns[0]
    res = pd.DataFrame({"_row": [0], f"{col}__2018": [1.0], f"{col}__2019": [np.nan], f"{col}__2020": [5.0], f"{col}__2021": [9.0]})
    work = pd.DataFrame({"_row": [0], "_date": ["2021-06-01"]})
    fin, diag = G.windows_from_units(res, work, [ds], ["cur", "y3"], "year", "median", [f"{col}_cur", f"{col}_y3"])
    assert fin.loc[0, f"{col}_cur"] == 9.0 and fin.loc[0, f"{col}_y3"] == 3.0          # (1, 5) 的中值
    assert diag["used"][0].tolist() == [1, 2] and diag["expected"][0].tolist() == [1, 3]   # 窗口只用到 2 个有值的年份


def test_gee_nearest_fill():
    """GEE 逐年值：窗口内有值只平均已有的；整个窗口都没有时取最近一期（前后等距取较早），记下偏差。"""
    import numpy as np
    import pandas as pd
    ds = C.SOURCE_BY_KEY["ntl.viirs_annual"]
    col = ds.columns[0]
    # 观测 2025：本批最多补到 2022–2027 的单位；只有 2023、2024 有值
    res = pd.DataFrame({"_row": [0], f"{col}__2023": [4.0], f"{col}__2024": [6.0], f"{col}__2025": [np.nan], f"{col}__2022": [np.nan]})
    work = pd.DataFrame({"_row": [0], "_date": ["2025-06-01"]})
    cols = [f"{col}_cur", f"{col}_y1", f"{col}_y3"]
    fin, dg = G.windows_from_units(res, work, [ds], ["cur", "y1", "y3"], "year", "mean", cols)
    assert fin.loc[0, cols[0]] == 6.0 and fin.loc[0, cols[1]] == 6.0 and fin.loc[0, cols[2]] == 5.0   # cur 取 2024；y1=2024；y3=2022–2024 只平均 2023、2024
    assert dg["sub"][0].tolist() == [True, False, False] and dg["gap"][0].tolist() == [1.0, 0.0, 0.0]
    fin2, dg2 = G.windows_from_units(res, work, [ds], ["cur"], "year", "mean", [cols[0]], fill=False)
    assert np.isnan(fin2.loc[0, cols[0]]) and not dg2["sub"].any()
    assert (2024, 1) in G.pad_units([(2025, 1)], "year") and (2027, 1) in G.pad_units([(2025, 1)], "year")
