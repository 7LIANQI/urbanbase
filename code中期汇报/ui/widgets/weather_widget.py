"""实时天气与气候概况展示组件。

支持三种视图切换：
  - 实时天气: OpenWeatherMap 当前气温/湿度/气压/风速
  - 24小时逐时: ERA5 最近一天逐时折线图
  - 近15天逐日: ERA5 每日统计折线图
"""
import json
from pathlib import Path

import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QGroupBox, QGridLayout, QComboBox,
)
from PyQt6.QtCore import Qt

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class WeatherWidget(QWidget):
    """展示实时天气 + ERA5 气候统计，可切换逐时/逐日视图。"""

    VIEW_LIVE = "实时天气 (OpenWeatherMap)"
    VIEW_HOURLY = "24小时逐时 (ERA5)"
    VIEW_DAILY = "近15天逐日 (ERA5)"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_dir = None
        self.enabled = True
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()

        # ---- 视图切换 ----
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("视图:"))
        self.view_combo = QComboBox()
        self.view_combo.addItems([self.VIEW_LIVE, self.VIEW_HOURLY, self.VIEW_DAILY])
        self.view_combo.currentTextChanged.connect(self._on_view_changed)
        ctrl.addWidget(self.view_combo)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        # ---- 实时天气卡片（仅在 LIVE 视图可见） ----
        self.live_group = QGroupBox("🌤️ 实时天气 (OpenWeatherMap)")
        live_layout = QGridLayout()

        self.temp_label = self._val("-- C")
        self.hum_label = self._val("-- %")
        self.press_label = self._val("-- hPa")
        self.wind_label = self._val("-- m/s")
        self.cloud_label = self._val("-- %")
        self.weather_desc = QLabel("等待数据...")
        self.weather_desc.setStyleSheet("font-size: 18px; font-weight: bold;")

        live_layout.addWidget(QLabel("天气:"), 0, 0)
        live_layout.addWidget(self.weather_desc, 0, 1)
        live_layout.addWidget(QLabel("气温:"), 1, 0)
        live_layout.addWidget(self.temp_label, 1, 1)
        live_layout.addWidget(QLabel("湿度:"), 2, 0)
        live_layout.addWidget(self.hum_label, 2, 1)
        live_layout.addWidget(QLabel("气压:"), 3, 0)
        live_layout.addWidget(self.press_label, 3, 1)
        live_layout.addWidget(QLabel("风速:"), 4, 0)
        live_layout.addWidget(self.wind_label, 4, 1)
        live_layout.addWidget(QLabel("云量:"), 5, 0)
        live_layout.addWidget(self.cloud_label, 5, 1)
        self.live_group.setLayout(live_layout)
        layout.addWidget(self.live_group)

        # ---- ERA5 图表（逐时/逐日视图共用） ----
        self.chart_group = QGroupBox("📈 ERA5 气候数据")
        chart_layout = QVBoxLayout()
        self.figure = Figure(figsize=(8, 4), dpi=80)
        self.canvas = FigureCanvas(self.figure)
        chart_layout.addWidget(self.canvas)
        self.chart_info = QLabel("")
        self.chart_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chart_layout.addWidget(self.chart_info)
        self.chart_group.setLayout(chart_layout)
        layout.addWidget(self.chart_group)

        # ---- 逐日统计摘要（仅在 DAILY 视图可见） ----
        self.summary_group = QGroupBox("📊 周期统计 (ERA5-Land)")
        sum_layout = QGridLayout()
        self.era5_temp_avg = self._val("-- C")
        self.era5_temp_max = self._val("-- C")
        self.era5_temp_min = self._val("-- C")
        self.era5_hum_avg = self._val("-- %")
        self.era5_solar_avg = self._val("-- W/m2")
        self.era5_sun_hours = self._val("-- h")
        self.era5_days_label = QLabel("统计天数: --")

        sum_layout.addWidget(QLabel("日均气温:"), 0, 0)
        sum_layout.addWidget(self.era5_temp_avg, 0, 1)
        sum_layout.addWidget(QLabel("最高气温:"), 0, 2)
        sum_layout.addWidget(self.era5_temp_max, 0, 3)
        sum_layout.addWidget(QLabel("最低气温:"), 1, 0)
        sum_layout.addWidget(self.era5_temp_min, 1, 1)
        sum_layout.addWidget(QLabel("日均湿度:"), 1, 2)
        sum_layout.addWidget(self.era5_hum_avg, 1, 3)
        sum_layout.addWidget(QLabel("日均辐射:"), 2, 0)
        sum_layout.addWidget(self.era5_solar_avg, 2, 1)
        sum_layout.addWidget(QLabel("累计日照:"), 2, 2)
        sum_layout.addWidget(self.era5_sun_hours, 2, 3)
        sum_layout.addWidget(self.era5_days_label, 3, 0, 1, 4)
        self.summary_group.setLayout(sum_layout)
        layout.addWidget(self.summary_group)

        layout.addStretch()
        self.setLayout(layout)

        # 初始可见性
        self.live_group.show()
        self.chart_group.hide()
        self.summary_group.hide()

    @staticmethod
    def _val(text):
        label = QLabel(text)
        label.setStyleSheet("font-size: 16px; font-weight: bold; color: #2c3e50;")
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return label

    def set_enabled(self, enabled):
        self.enabled = enabled
        if not enabled:
            self.weather_desc.setText("天气显示已禁用")

    def set_output_dir(self, output_dir):
        self.current_dir = output_dir
        if self.enabled:
            self._on_view_changed(self.view_combo.currentText())
        else:
            self.weather_desc.setText("天气显示已禁用")

    # ==================== 视图切换 ====================

    def _on_view_changed(self, view):
        if not self.current_dir:
            return

        if view == self.VIEW_LIVE:
            self.live_group.show()
            self.chart_group.hide()
            self.summary_group.hide()
            self._load_live()
        elif view == self.VIEW_HOURLY:
            self.live_group.hide()
            self.chart_group.show()
            self.summary_group.hide()
            self._plot_hourly()
        elif view == self.VIEW_DAILY:
            self.live_group.hide()
            self.chart_group.show()
            self.summary_group.show()
            self._plot_daily()
            self._load_summary()

    # ==================== 实时天气 ====================

    def _load_live(self):
        weather_path = Path(self.current_dir) / "weather.json"
        if not weather_path.exists():
            self.weather_desc.setText("未找到天气数据")
            return
        try:
            with open(weather_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data.get("code") == "200" and "now" in data:
                w = data["now"]
                self.weather_desc.setText(w.get("weather", "N/A"))
                self.temp_label.setText(f"{w.get('temp_c', '--')} C")
                self.hum_label.setText(f"{w.get('humidity', '--')} %")
                self.press_label.setText(f"{w.get('pressure_hpa', '--')} hPa")
                self.wind_label.setText(f"{w.get('wind_speed_ms', '--')} m/s")
                self.cloud_label.setText(f"{w.get('clouds', '--')} %")
        except Exception:
            self.weather_desc.setText("读取失败")

    # ==================== 逐时图 ====================

    def _show_chart_error(self, msg):
        """在图表区域显示错误信息，避免闪退。"""
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.text(0.5, 0.5, msg, ha='center', va='center',
                transform=ax.transAxes, fontsize=12, color='#888')
        ax.set_xticks([])
        ax.set_yticks([])
        self.canvas.draw()
        self.chart_info.setText("")

    def _plot_hourly(self):
        csv_path = Path(self.current_dir) / "era5_hourly.csv"
        if not csv_path.exists():
            self._show_chart_error("逐时数据未采集\n(需启用 GEE 遥感模块)")
            return

        try:
            df = pd.read_csv(csv_path)
            required = ['Hour', '气温_C', '太阳辐射_Wm2']
            if not all(c in df.columns for c in required):
                self._show_chart_error(
                    f"CSV 列名不匹配\n需要: {required}\n实际: {list(df.columns)}")
                return
            if df.empty:
                self._show_chart_error("逐时数据为空")
                return

            self.figure.clear()
            ax = self.figure.add_subplot(111)
            hours = df['Hour'].astype(int)
            ax.plot(hours, df['气温_C'], marker='o', color='#e74c3c',
                    linewidth=2, label='气温 (C)')
            ax.set_xlabel('小时', fontsize=10)
            ax.set_ylabel('气温 (C)', fontsize=10, color='#e74c3c')
            ax.tick_params(axis='y', labelcolor='#e74c3c')

            ax2 = ax.twinx()
            ax2.fill_between(hours, df['太阳辐射_Wm2'], alpha=0.3, color='orange')
            ax2.plot(hours, df['太阳辐射_Wm2'], color='orange',
                     linewidth=1.5, label='辐射 (W/m2)')
            ax2.set_ylabel('太阳辐射 (W/m2)', fontsize=10, color='orange')
            ax2.tick_params(axis='y', labelcolor='orange')

            ax.set_title("ERA5 24小时逐时气象", fontsize=12)
            ax.grid(True, linestyle='--', alpha=0.5)
            self.figure.tight_layout()
            self.canvas.draw()

            self.chart_info.setText(
                f"日均气温: {df['气温_C'].mean():.1f}C  |  "
                f"最高: {df['气温_C'].max():.1f}C  |  "
                f"峰值辐射: {df['太阳辐射_Wm2'].max():.0f} W/m2"
            )
        except Exception as e:
            self._show_chart_error(f"加载逐时数据失败:\n{str(e)[:100]}")

    # ==================== 逐日图 ====================

    def _plot_daily(self):
        csv_path = Path(self.current_dir) / "era5_climate_stats.csv"
        if not csv_path.exists():
            self._show_chart_error("气候逐日数据未采集\n(需启用 GEE 遥感模块)")
            return

        try:
            df = pd.read_csv(csv_path)

            # 兼容旧版 CSV（℃ 列名 → C 列名）
            rename_map = {}
            for col in df.columns:
                if '℃' in col:
                    rename_map[col] = col.replace('℃', 'C')
            if rename_map:
                df = df.rename(columns=rename_map)

            required = ['Date', '日均气温_C', '日最高气温_C', '日最低气温_C',
                        '日照时数_h', '太阳辐射日均_Wm2']
            if not all(c in df.columns for c in required):
                self._show_chart_error(
                    f"CSV 列名不匹配，请重新采集\n需要: {required}\n实际: {list(df.columns)}")
                return
            if df.empty:
                self._show_chart_error("气候数据为空")
                return

            df = df.tail(15)

            self.figure.clear()
            ax = self.figure.add_subplot(111)
            ax.plot(df['Date'], df['日均气温_C'], marker='o',
                    color='#e74c3c', linewidth=2, label='日均气温')
            ax.fill_between(range(len(df)), df['日最低气温_C'], df['日最高气温_C'],
                            alpha=0.2, color='#e74c3c', label='气温范围')
            ax.set_ylabel('气温 (C)', fontsize=10)
            ax.tick_params(axis='x', rotation=45, labelsize=8)
            ax.grid(True, linestyle='--', alpha=0.5)

            ax2 = ax.twinx()
            ax2.bar(range(len(df)), df['日照时数_h'], alpha=0.4,
                    color='#3498db', label='日照时数')
            ax2.set_ylabel('日照时数 (h)', fontsize=10, color='#3498db')
            ax2.tick_params(axis='y', labelcolor='#3498db')

            ax.set_title("近15天 气温与日照 (ERA5)", fontsize=12)
            lines1, labels1 = ax.get_legend_handles_labels()
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax.legend(lines1 + lines2, labels1 + labels2, fontsize=8, loc='upper left')
            self.figure.tight_layout()
            self.canvas.draw()

            self.chart_info.setText(
                f"日均气温: {df['日均气温_C'].mean():.1f}C  |  "
                f"总日照: {df['日照时数_h'].sum():.1f}h  |  "
                f"日均辐射: {df['太阳辐射日均_Wm2'].mean():.0f} W/m2"
            )
        except Exception as e:
            self._show_chart_error(f"加载逐日数据失败:\n{str(e)[:100]}")

    # ==================== 摘要统计 ====================

    def _load_summary(self):
        csv_path = Path(self.current_dir) / "era5_climate_stats.csv"
        if not csv_path.exists():
            return
        try:
            df = pd.read_csv(csv_path)
            # 兼容旧版 ℃ 列名
            rename_map = {col: col.replace('℃', 'C') for col in df.columns if '℃' in col}
            if rename_map:
                df = df.rename(columns=rename_map)
            required = ['日均气温_C', '日最高气温_C', '日最低气温_C',
                        '日均相对湿度_pct', '太阳辐射日均_Wm2', '日照时数_h']
            if not all(c in df.columns for c in required) or df.empty:
                return
            self.era5_temp_avg.setText(f"{df['日均气温_C'].mean():.1f} C")
            self.era5_temp_max.setText(f"{df['日最高气温_C'].max():.1f} C")
            self.era5_temp_min.setText(f"{df['日最低气温_C'].min():.1f} C")
            self.era5_hum_avg.setText(f"{df['日均相对湿度_pct'].mean():.1f} %")
            self.era5_solar_avg.setText(f"{df['太阳辐射日均_Wm2'].mean():.1f} W/m2")
            self.era5_sun_hours.setText(f"{df['日照时数_h'].sum():.1f} h")
            self.era5_days_label.setText(f"统计天数: {len(df)} 天")
        except Exception:
            pass
