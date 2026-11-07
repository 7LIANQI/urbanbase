"""时间分析：宽表识别、长表转换、趋势统计和日期记录。"""
from pathlib import Path

import numpy as np
import pandas as pd

from core import time_analysis as TA


def test_fixed_periods_and_summary():
    df = pd.DataFrame({
        "id": ["a", "b"],
        "lon": [113.2, 113.3],
        "lat": [23.1, 23.2],
        "NDVI_P2020": [0.2, 0.4],
        "NDVI_P2021": [0.3, np.nan],
        "NDVI_P2022": [0.5, 0.6],
        "NDVI_P2020_名称": ["x", "y"],
    })
    columns = TA.discover_time_columns(df, "fixed")
    assert [c.period for c in columns] == ["2020", "2021", "2022"]
    long = TA.to_long(df, columns, "id", "lon", "lat")
    stats = TA.summarize(long).set_index("point_id")
    assert stats.loc["a", "first"] == 0.2 and stats.loc["a", "last"] == 0.5
    assert abs(stats.loc["a", "slope_per_year"] - 0.15) < 1e-9
    assert stats.loc["b", "valid_count"] == 2
    assert abs(stats.loc["b", "change"] - 0.2) < 1e-9


def test_relative_windows_are_ordered_not_mixed_with_history():
    df = pd.DataFrame({
        "id": ["a"],
        "NDVI_cur": [0.5],
        "NDVI_y10": [0.1],
        "NDVI_y3": [0.2],
    })
    columns = TA.discover_time_columns(df, "relative")
    assert [c.period for c in columns] == ["cur", "y3", "y10"]
    with np.testing.assert_raises(ValueError):
        TA.discover_time_columns(pd.DataFrame({"a_P2020": [1], "a_cur": [1]}))


def test_date_records_to_long():
    df = pd.DataFrame({
        "id": ["a", "a"],
        "lon": [113.2, 113.2],
        "lat": [23.1, 23.1],
        "obs_time": ["2020-01-01", "2021-01-01"],
        "temperature": [20, 22],
    })
    long = TA.records_to_long(df, "obs_time", ["temperature"], "id", "lon", "lat")
    assert long["period"].tolist() == ["2020-01-01", "2021-01-01"]
    stats = TA.summarize(long)
    assert stats.iloc[0]["change"] == 2


def test_missing_values_are_preserved_in_long_table():
    df = pd.DataFrame({"id": ["a"], "x_P2020": [1.0], "x_P2021": [np.nan]})
    columns = TA.discover_time_columns(df)
    long = TA.to_long(df, columns, "id")
    assert len(long) == 2 and long["value"].isna().sum() == 1
    assert TA.summarize(long).iloc[0]["valid_count"] == 1


def test_all_missing_metric_is_reported_without_crashing():
    df = pd.DataFrame({
        "id": ["a", "b"],
        "good_cur": [1.0, 2.0],
        "good_y1": [1.5, 2.5],
        "good_y3": [2.0, 3.0],
        "empty_cur": [np.nan, np.nan],
        "empty_y1": [np.nan, np.nan],
        "empty_y3": [np.nan, np.nan],
    })
    long = TA.to_long(df, TA.discover_time_columns(df), "id")
    stats = TA.summarize(long)
    empty = stats[stats["metric"] == "empty"]
    assert len(empty) == 2
    assert empty["valid_count"].tolist() == [0, 0]
    assert empty["total_periods"].tolist() == [3, 3]
    assert empty["all_missing"].all()
    assert empty[["first", "last", "mean", "min", "max"]].isna().all().all()
    good = stats[stats["metric"] == "good"]
    assert good["valid_count"].tolist() == [3, 3]


def test_write_outputs(tmp_path):
    df = pd.DataFrame({"id": ["a"], "x_P2020": [1.0], "x_P2021": [2.0]})
    long = TA.to_long(df, TA.discover_time_columns(df), "id")
    paths = TA.write_outputs(long, TA.summarize(long), tmp_path / "result.csv")
    assert all(Path(p).exists() for p in paths.values())
