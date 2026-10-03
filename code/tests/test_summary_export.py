"""测试 summary_export 汇总导出模块。"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd

from summary_export import _compute_slices, build_summary_csv


class TestComputeSlices:
    """测试时间切片计算。"""

    def test_constant_series(self):
        dates = ["2023-01-01", "2023-06-01", "2023-12-01"]
        vals = [10, 10, 10]
        cur, y2, y3, y5, y10 = _compute_slices(dates, vals)
        assert cur == 10 and y2 == 10 and y10 == 10

    def test_longer_window_lower_mean(self):
        # 数据逐年递增：窗口越长，包含越多早期低值，均值越低
        dates = pd.date_range("2020-01-01", "2023-12-31", freq="YS").strftime("%Y-%m-%d").tolist()
        vals = [10.0, 20.0, 30.0, 40.0]
        cur, y2, y3, y5, y10 = _compute_slices(dates, vals)
        assert cur >= y2 >= y3 >= y5 >= y10

    def test_empty(self):
        assert _compute_slices([], []) == [None] * 5


class TestBuildSummaryCsv:
    """测试宽表 CSV 生成。"""

    def test_basic(self, tmp_path):
        d = tmp_path / "out1"
        d.mkdir()
        (d / "meta.json").write_text(
            json.dumps({"location": "Lon:116.39, Lat:39.90"}), encoding="utf-8",
        )
        pd.DataFrame({
            "Date": ["2021-01-01", "2023-01-01"],
            "precipitation": [1.0, 3.0],
        }).to_csv(d / "precipitation_stats.csv", index=False)

        out = tmp_path / "summary.csv"
        ok, n = build_summary_csv([str(d)], str(out))
        assert ok and n == 1

        df = pd.read_csv(out)
        assert list(df.columns) == ["经度", "纬度", "数据类别", "指标", "Cur", "2y", "3y", "5y", "10y"]
        assert df.iloc[0]["指标"] == "降雨"
        assert df.iloc[0]["Cur"] == 3.0  # 最近1年(2023)的均值

    def test_no_data(self, tmp_path):
        ok, info = build_summary_csv([str(tmp_path / "nonexist")], str(tmp_path / "x.csv"))
        assert ok is False
