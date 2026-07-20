"""遥感数据图表组件。"""
from pathlib import Path

import pandas as pd

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox,
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class ChartWidget(QWidget):
    """NDVI / 地表温度 / 夜光强度 / ERA5 气候 时间序列图。"""

    CHART_NDVI = "NDVI 时间序列"
    CHART_LST = "地表温度 时间序列"
    CHART_VIIRS = "夜光强度 时间序列"
    CHART_ERA5_TEMP = "气温 时间序列 (ERA5)"
    CHART_ERA5_SOLAR = "太阳辐射 时间序列 (ERA5)"
    CHART_ERA5_SUN = "日照时数 (ERA5)"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_dir = None
        self.enabled = True
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()

        control_layout = QHBoxLayout()
        control_layout.addWidget(QLabel("选择数据:"))
        self.chart_combo = QComboBox()
        self.chart_combo.addItems([
            self.CHART_NDVI, self.CHART_LST, self.CHART_VIIRS,
            self.CHART_ERA5_TEMP, self.CHART_ERA5_SOLAR, self.CHART_ERA5_SUN,
        ])
        self.chart_combo.currentTextChanged.connect(self.update_chart)
        control_layout.addWidget(self.chart_combo)
        control_layout.addStretch()
        layout.addLayout(control_layout)

        self.figure = Figure(figsize=(8, 4), dpi=80)
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)

        self.setLayout(layout)

    def set_enabled(self, enabled):
        self.enabled = enabled
        if not self.enabled:
            self._show_disabled_message()

    def set_output_dir(self, output_dir):
        self.current_dir = output_dir
        if self.enabled:
            self.update_chart()
        else:
            self._show_disabled_message()

    def _show_disabled_message(self):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.text(0.5, 0.5, "图表显示已禁用\n（采集时未勾选）",
                ha='center', va='center', transform=ax.transAxes, fontsize=12)
        self.canvas.draw()

    def update_chart(self):
        if not self.enabled or not self.current_dir:
            return

        self.figure.clear()
        ax = self.figure.add_subplot(111)
        chart_type = self.chart_combo.currentText()

        try:
            if chart_type == self.CHART_NDVI:
                self._plot(ax, "ndvi_stats.csv", 'Date', '区域NDVI均值',
                           "NDVI 时间序列", "NDVI 值", 'green')
            elif chart_type == self.CHART_LST:
                self._plot(ax, "lst_stats.csv", 'Date', '地表温度均值(C)',
                           "地表温度 时间序列", "温度 (C)", 'red')
            elif chart_type == self.CHART_VIIRS:
                self._plot(ax, "viirs_stats.csv", 'Date', '夜光均值',
                           "夜光强度 时间序列", "夜光强度", 'orange')
            elif chart_type == self.CHART_ERA5_TEMP:
                self._plot_era5_temp(ax)
            elif chart_type == self.CHART_ERA5_SOLAR:
                self._plot(ax, "era5_climate_stats.csv", 'Date',
                           '太阳辐射日均_Wm2', "太阳辐射 时间序列",
                           "太阳辐射 (W/m²)", '#e67e22')
            elif chart_type == self.CHART_ERA5_SUN:
                self._plot_bar(ax, "era5_climate_stats.csv", 'Date',
                               '日照时数_h', "日照时数", "小时", '#3498db')

            self.figure.tight_layout()
            self.canvas.draw()
        except Exception as e:
            ax.text(0.5, 0.5, f"无法加载数据:\n{str(e)}",
                    ha='center', va='center', transform=ax.transAxes, fontsize=10)
            self.canvas.draw()

    def _plot(self, ax, filename, x_col, y_col, title, ylabel, color):
        csv_path = Path(self.current_dir) / filename
        if not csv_path.exists():
            raise FileNotFoundError(f"文件不存在: {filename}")

        df = pd.read_csv(csv_path)
        ax.plot(df[x_col], df[y_col], marker='o', color=color, linewidth=2)
        ax.set_title(title, fontsize=12)
        ax.set_ylabel(ylabel, fontsize=10)
        ax.tick_params(axis='x', rotation=45, labelsize=8)
        ax.tick_params(axis='y', labelsize=8)
        ax.grid(True, linestyle='--', alpha=0.7)

    def _plot_era5_temp(self, ax):
        """ERA5 气温：日均/最高/最低 三条线。"""
        csv_path = Path(self.current_dir) / "era5_climate_stats.csv"
        if not csv_path.exists():
            raise FileNotFoundError("era5_climate_stats.csv 不存在")

        df = pd.read_csv(csv_path)
        ax.plot(df['Date'], df['日均气温_C'], marker='o',
                color='#2c3e50', linewidth=2, label='日均气温')
        ax.plot(df['Date'], df['日最高气温_C'], marker='^',
                color='red', linewidth=1, linestyle='--', label='最高气温')
        ax.plot(df['Date'], df['日最低气温_C'], marker='v',
                color='blue', linewidth=1, linestyle='--', label='最低气温')
        ax.fill_between(range(len(df)), df['日最低气温_C'], df['日最高气温_C'],
                        alpha=0.15, color='gray')
        ax.set_title("ERA5 气温 时间序列", fontsize=12)
        ax.set_ylabel("温度 (C)", fontsize=10)
        ax.tick_params(axis='x', rotation=45, labelsize=8)
        ax.tick_params(axis='y', labelsize=8)
        ax.legend(fontsize=8)
        ax.grid(True, linestyle='--', alpha=0.7)

    def _plot_bar(self, ax, filename, x_col, y_col, title, ylabel, color):
        """柱状图（日照时数等）。"""
        csv_path = Path(self.current_dir) / filename
        if not csv_path.exists():
            raise FileNotFoundError(f"文件不存在: {filename}")

        df = pd.read_csv(csv_path)
        ax.bar(df[x_col], df[y_col], color=color, alpha=0.7, edgecolor='white')
        ax.set_title(title, fontsize=12)
        ax.set_ylabel(ylabel, fontsize=10)
        ax.tick_params(axis='x', rotation=45, labelsize=8)
        ax.tick_params(axis='y', labelsize=8)
        ax.grid(True, linestyle='--', alpha=0.7, axis='y')
