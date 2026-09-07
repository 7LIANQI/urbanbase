"""主窗口 —— 城市街道环境大数据采集与分析平台 GUI。"""
import os
import glob
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QDialog,
    QGroupBox, QLabel, QLineEdit, QCheckBox,
    QDateEdit, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QProgressBar,
    QTabWidget, QTextEdit, QListWidget, QListWidgetItem,
    QFileDialog, QMessageBox, QGridLayout,
    QScrollArea, QFrame, QMenu, QComboBox, QInputDialog, QTimeEdit,
)
from PyQt6.QtCore import Qt, QSettings, QUrl, QPoint, QTimer, QTime
from PyQt6.QtGui import QDesktopServices, QAction
from PyQt6.QtWidgets import QMenu

from .worker import Worker
from .widgets import (
    AirQualityWidget,
    WeatherWidget,
    StreetViewWidget,
    ChartWidget,
    MapWidget,
    StatsWidget,
)
from utils import FileLogger, secure_store, secure_load
from config import PG_HOST, PG_PORT, PG_DBNAME, PG_USER, PG_PASSWORD


class LogDialog(QDialog):
    """采集日志弹窗 —— 点击开始采集时自动弹出。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📝 运行日志")
        self.resize(700, 420)
        self.setMinimumSize(500, 300)

        layout = QVBoxLayout(self)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        layout.addWidget(self.log_box)

        bottom = QHBoxLayout()
        self.status_label = QLabel("等待采集开始...")
        bottom.addWidget(self.status_label)
        bottom.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.hide)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)

    def set_status(self, text):
        self.status_label.setText(text)

    def append_log(self, msg):
        self.log_box.append(msg)
        # 自动滚到底部
        scrollbar = self.log_box.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


class ResultDialog(QDialog):
    """采集结果展示弹窗 —— 数据采集完成后自动弹出。"""

    def __init__(self, on_prev=None, on_next=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📊 采集结果展示")
        self.resize(1100, 750)
        self.setMinimumSize(800, 500)

        layout = QVBoxLayout(self)

        # Tab 展示区
        self.tab_widget = QTabWidget()

        self.street_view = StreetViewWidget()
        self.chart_view = ChartWidget()
        self.map_view = MapWidget()
        self.air_quality_view = AirQualityWidget()
        self.weather_view = WeatherWidget()
        self.stats_view = StatsWidget()

        self.tab_widget.addTab(self.street_view, "📸 街景展示")
        self.tab_widget.addTab(self.chart_view, "📊 遥感图表")
        self.tab_widget.addTab(self.map_view, "🗺️ 地图展示")
        self.tab_widget.addTab(self.air_quality_view, "🌬️ 空气质量")
        self.tab_widget.addTab(self.weather_view, "🌤️ 气象数据")
        self.tab_widget.addTab(self.stats_view, "📋 综合统计")
        layout.addWidget(self.tab_widget)

        # 导航栏
        nav_layout = QHBoxLayout()
        prev_btn = QPushButton("⬅ 上一条")
        next_btn = QPushButton("下一条 ➡")
        self.result_label = QLabel("暂无结果")

        if on_prev:
            prev_btn.clicked.connect(on_prev)
        if on_next:
            next_btn.clicked.connect(on_next)

        nav_layout.addWidget(prev_btn)
        nav_layout.addWidget(self.result_label)
        nav_layout.addWidget(next_btn)

        bottom = QHBoxLayout()
        bottom.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.hide)
        bottom.addWidget(close_btn)

        layout.addLayout(nav_layout)
        layout.addLayout(bottom)


class MainWindow(QWidget):
    """应用主窗口。"""

    def __init__(self):
        super().__init__()
        self.output_dirs = []
        self.current_index = 0
        self.worker = None
        self._stopped_by_user = False
        self.settings = QSettings("MyCompany", "UrbanAnalysisApp")
        self.file_logger = FileLogger("logs")
        self._data_cache = {}  # output_dir -> {widget_key: preloaded_data} (LRU, max 5)

        # 日志弹窗（点击采集时才显示）
        self.log_dialog = LogDialog(self)
        self.log_box = self.log_dialog.log_box

        # 结果弹窗（有结果时显示）
        self.result_dialog = ResultDialog(
            on_prev=self._show_prev,
            on_next=self._show_next,
            parent=self,
        )
        # 将子组件引用映射到 MainWindow 方便访问
        self.street_view = self.result_dialog.street_view
        self.chart_view = self.result_dialog.chart_view
        self.map_view = self.result_dialog.map_view
        self.air_quality_view = self.result_dialog.air_quality_view
        self.weather_view = self.result_dialog.weather_view
        self.stats_view = self.result_dialog.stats_view
        self.result_label = self.result_dialog.result_label

        self._init_ui()
        self._load_history()

        self.log_box.append("📋 日志文件: " + self.file_logger.log_path)

    # ==================== UI 构建 ====================

    def _init_ui(self):
        self.setWindowTitle("面向城市街道环境的大数据采集与分析平台")
        self.resize(1400, 900)

        main_layout = QHBoxLayout(self)

        # ----- 左侧：历史记录面板 -----
        main_layout.addWidget(self._build_left_panel())

        # ----- 右侧：主内容区 -----
        main_layout.addWidget(self._build_right_panel())

    def _build_left_panel(self):
        panel = QWidget()
        panel.setFixedWidth(280)
        layout = QVBoxLayout(panel)

        label = QLabel("📜 历史记录")
        label.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(label)

        # ---- 筛选控件 ----
        filter_row = QHBoxLayout()
        self.history_filter_combo = QComboBox()
        self.history_filter_combo.addItems([
            "全部记录", "最近 7 天", "最近 30 天", "最近 90 天", "本年",
        ])
        self.history_filter_combo.setToolTip("按时间筛选历史记录")
        self.history_filter_combo.currentIndexChanged.connect(self._load_history)
        filter_row.addWidget(self.history_filter_combo)
        layout.addLayout(filter_row)

        self.history_list = QListWidget()
        self.history_list.itemClicked.connect(self._on_history_clicked)
        self.history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_list.customContextMenuRequested.connect(self._on_history_context_menu)
        layout.addWidget(self.history_list)

        # 缓存统计
        self.cache_stats_label = QLabel("")
        self.cache_stats_label.setStyleSheet("color: #888; font-size: 10px; padding: 2px;")
        self.cache_stats_label.setWordWrap(True)
        layout.addWidget(self.cache_stats_label)

        # 对比模式
        compare_row = QHBoxLayout()
        self.compare_cb = QCheckBox("对比模式")
        self.compare_cb.setToolTip("勾选后，点击两个历史记录进行对比")
        compare_row.addWidget(self.compare_cb)
        compare_btn = QPushButton("对比选中")
        compare_btn.clicked.connect(self._compare_selected)
        compare_row.addWidget(compare_btn)
        layout.addLayout(compare_row)

        # 操作按钮行
        btn_row2 = QHBoxLayout()
        timeline_btn = QPushButton("📊 时间线")
        timeline_btn.setToolTip("查看同一位置的所有历史数据时间线")
        timeline_btn.clicked.connect(self._show_timeline_view)
        btn_row2.addWidget(timeline_btn)
        clean_btn = QPushButton("🗑️ 清理")
        clean_btn.clicked.connect(self._clean_data_dialog)
        btn_row2.addWidget(clean_btn)
        layout.addLayout(btn_row2)

        layout.addStretch()
        return panel

    def _build_right_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        self.main_tabs = QTabWidget()

        # ---- Tab 1: 数据采集 ----
        tab_collect = QWidget()
        collect_layout = QVBoxLayout(tab_collect)
        collect_layout.addWidget(self._build_api_group())
        collect_layout.addWidget(self._build_options_group())
        collect_layout.addWidget(self._build_input_group())
        collect_layout.addLayout(self._build_ctrl_buttons())
        self.progress = QProgressBar()
        collect_layout.addWidget(self.progress)
        self.step_label = QLabel("")
        self.step_label.setStyleSheet("color: #666; font-size: 11px;")
        collect_layout.addWidget(self.step_label)
        collect_layout.addStretch()
        self.main_tabs.addTab(tab_collect, "📦 数据采集")

        # ---- Tab 2: 时间分析 ----
        tab_time = QWidget()
        time_layout = QVBoxLayout(tab_time)
        self.time_slice_group = self._build_time_slice_group()
        time_layout.addWidget(self.time_slice_group)
        time_layout.addWidget(self._build_timeline_group())
        time_layout.addStretch()
        self.main_tabs.addTab(tab_time, "🕐 时间分析")

        # ---- Tab 3: 自动监测 ----
        tab_auto = QWidget()
        auto_layout = QVBoxLayout(tab_auto)
        auto_layout.addWidget(self._build_schedule_group())
        auto_layout.addStretch()
        self.main_tabs.addTab(tab_auto, "⏰ 自动监测")

        # ---- Tab 4: 本地数据 ----
        tab_local = QWidget()
        local_layout = QVBoxLayout(tab_local)
        local_layout.addWidget(self._build_local_group())
        self.main_tabs.addTab(tab_local, "🗄️ 本地数据")

        layout.addWidget(self.main_tabs)
        return panel

    def _build_api_group(self):
        group = QGroupBox("🔑 API 服务配置")
        layout = QHBoxLayout()  # 用 QGridLayout 原名但简化

        # 使用表单布局更整齐
        form = QVBoxLayout()

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("OpenWeather Key:"))
        self.weather_key_input = QLineEdit()
        self.weather_key_input.setPlaceholderText("OpenWeatherMap Key")
        self.weather_key_input.setText(
            secure_load("weather_key", self.settings.value("keys/weather_key", ""))
        )
        row1.addWidget(self.weather_key_input)
        form.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("GEE 密钥文件:"))
        self.gee_key_input = QLineEdit()
        self.gee_key_input.setPlaceholderText("点击“导入...”选择 GEE JSON 文件")
        self.gee_key_input.setText(self.settings.value("keys/gee_key", ""))
        self.gee_key_input.setReadOnly(True)
        row2.addWidget(self.gee_key_input)
        import_gee_btn = QPushButton("导入...")
        import_gee_btn.clicked.connect(self._browse_gee_key_file)
        row2.addWidget(import_gee_btn)
        form.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("百度地图 AK:"))
        self.baidu_key_input = QLineEdit()
        self.baidu_key_input.setPlaceholderText("百度地图 AK (浏览器端, 用于街景)")
        self.baidu_key_input.setText(
            secure_load("baidu_key", self.settings.value("keys/baidu_key", ""))
        )
        row3.addWidget(self.baidu_key_input)
        form.addLayout(row3)

        row4 = QHBoxLayout()
        row4.addWidget(QLabel("输出目录:"))
        self.output_dir_input = QLineEdit()
        self.output_dir_input.setPlaceholderText("数据保存目录 (默认: 当前目录)")
        self.output_dir_input.setText(self.settings.value("paths/output_dir", ""))
        row4.addWidget(self.output_dir_input)
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse_output_dir)
        row4.addWidget(browse_btn)
        form.addLayout(row4)

        layout.addLayout(form)
        group.setLayout(layout)
        return group

    # 数据源时间能力速查表
    # 图标: 📅 = 时间序列(受日期范围影响)  ⚡ = 实时快照  📸 = 固定时间快照
    _TIME_INFO = {
        # ---- 天气与空气质量 ----
        "air_quality":        ("⚡", "实时空气质量快照\nOpenWeatherMap 免费 API\n仅返回当前时刻的 AQI 和污染物浓度\n如需历史数据需升级至付费订阅"),
        "weather":            ("⚡", "实时天气快照\nOpenWeatherMap 免费 API\n仅返回当前时刻的气温/湿度/风速等\n如需历史数据需升级至付费订阅"),
        # ---- 街景 ----
        "streetview":         ("📸", "单次街景快照\n百度街景内部 API\n返回该位置最近一次采集的全景图\n拍摄日期取决于百度采集车经过的时间（通常 1-3 年前）"),
        # ---- GEE 遥感基础 ----
        "gee_viirs":          ("📅", "VIIRS 夜间灯光 — 时间序列\n数据集: NOAA/VIIRS/DNB\n时间范围: 2012-04 ~ 至今（月合成）\n受上方日期范围控制"),
        "gee_ndvi":           ("📅", "NDVI 植被指数 — 时间序列\n数据集: Sentinel-2 MSI\n时间范围: 2015-06 ~ 至今（5天重访）\n受上方日期范围控制，自动过滤云量>20%"),
        "gee_lst":            ("📅", "LST 地表温度 — 时间序列\n数据集: Landsat 8 TIRS\n时间范围: 2013-03 ~ 至今（16天重访）\n受上方日期范围控制，自动过滤云量>20%"),
        "gee_elevation":      ("📸", "海拔数据 — 静态\n数据集: SRTM GL1 (30m)\n2000 年测绘，永久不变"),
        "gee_precipitation":  ("📅", "降水量 — 时间序列\n数据集: CHIRPS Daily\n时间范围: 1981-01-01 ~ 至今（日值）\n受上方日期范围控制"),
        "gee_ndwi":           ("📅", "NDWI 水体指数 — 时间序列\n数据集: Sentinel-2 MSI\n时间范围: 2015-06 ~ 至今\n受上方日期范围控制"),
        "gee_evi":            ("📅", "EVI 增强植被指数 — 时间序列\n数据集: Sentinel-2 MSI\n时间范围: 2015-06 ~ 至今\n受上方日期范围控制"),
        "gee_population":     ("📸", "人口密度 — 静态\n数据集: WorldPop (100m, 2020年)\n备选: GPW v4 (1km, 2020年)\n无历史年份数据"),
        "gee_era5_climate":   ("📅", "ERA5 气候逐日 — 时间序列\n数据集: ECMWF/ERA5-Land Hourly\n时间范围: 1950-01 ~ 至今（小时→日聚合）\n受上方日期范围控制，最多 366 天"),
        "gee_era5_hourly":    ("📅", "ERA5 逐时数据 — 单日\n数据集: ECMWF/ERA5-Land Hourly\n时间范围: 1950-01 ~ 至今\n取结束日期的 24 小时逐时值\n注意: ERA5-Land 有 3-5 天发布延迟"),
        # ---- GEE 遥感扩展 ----
        "gee_landcover":      ("📸", "ESA WorldCover 土地覆盖 — 静态\n数据集: ESA/WorldCover/v200\n2021 年快照（10m 分辨率）\n另有 v100 (2020年) 可对比"),
        "gee_s5p_no2":        ("📅", "Sentinel-5P NO₂ — 时间序列\n数据集: Sentinel-5P TROPOMI\n时间范围: 2018-07 ~ 至今（日值）\n受上方日期范围控制"),
        "gee_jrc_water":      ("📸", "JRC 全球地表水 — 长期统计\n数据集: JRC GSW (30m)\n1984-2021 年合成统计图\n非时间序列，为多年平均值"),
        "gee_modis_lst":      ("📅", "MODIS LST — 时间序列\n数据集: MODIS MOD11A2\n时间范围: 2000-02 ~ 至今（8天合成）\n受上方日期范围控制"),
        "gee_dynamic_world":  ("📅", "Dynamic World 土地覆盖 — 时间序列\n数据集: Dynamic World V1\n时间范围: 2016-06 ~ 至今（2-5天重访）\n受上方日期范围控制"),
        "gee_hansen_forest":  ("📸", "Hansen 森林变化 — 长期统计\n数据集: Hansen GFC 2023 v1.11\n2000-2023 年合成图（30m）\n逐年损失数据已输出为 hansen_loss_by_year.csv"),
        "gee_canopy_height":  ("📸", "ETH 全球树冠高度 — 静态\n数据集: ETH Canopy Height 2020\n2020 年快照（10m 分辨率）\n需 GEE 社区数据集权限"),
        # ---- OSM 矢量 ----
        "osm_roads":          ("📸", "OSM 道路网络 — 实时快照\n通过 osmnx 从 OpenStreetMap 拉取\n始终为当前最新数据\n无时间维度，但可本地存档各时点结果"),
        "osm_buildings":      ("📸", "OSM 建筑物 — 实时快照\n始终为当前最新 OSM 数据"),
        "osm_green_spaces":   ("📸", "OSM 绿地 — 实时快照\n始终为当前最新 OSM 数据"),
        "osm_water_bodies":   ("📸", "OSM 水体 — 实时快照\n始终为当前最新 OSM 数据"),
        "osm_stats":          ("📸", "OSM 统计指标 — 实时快照\n基于当前最新 OSM 数据计算"),
        # ---- 本地数据 ----
        "local_data":         ("🗄️", "本地数据 — 查询 PostgreSQL 本地库\n按经纬度/时间范围查询历史采集结果\n及导师导入的本地数据集\n（需在「本地数据」Tab 配置连接）"),
    }

    def _build_options_group(self):
        """构建细粒度数据采集选项面板，每个子功能有独立复选框。"""
        group = QGroupBox("📦 数据采集选项")
        outer_layout = QVBoxLayout()

        # ---- 顶部万能按钮 ----
        btn_row = QHBoxLayout()
        select_all_btn = QPushButton("全选")
        deselect_all_btn = QPushButton("取消全选")
        btn_row.addWidget(select_all_btn)
        btn_row.addWidget(deselect_all_btn)
        btn_row.addStretch()
        outer_layout.addLayout(btn_row)

        # ---- 可滚动区域 ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMaximumHeight(320)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(6)

        # 收集所有子复选框用于全选/取消
        all_checkboxes = []

        def make_group(title, items):
            """items: [(key, label), ...]"""
            g = QGroupBox(title)
            grid = QGridLayout()
            grid.setSpacing(4)
            cbs = {}
            for idx, (key, label) in enumerate(items):
                cb = QCheckBox(label)
                cb.setChecked(True)
                cbs[key] = cb
                all_checkboxes.append(cb)
                grid.addWidget(cb, idx // 3, idx % 3)
            g.setLayout(grid)
            return g, cbs

        # 🌬️ 空气质量与天气
        g_air, self.opt_air = make_group("🌬️ 空气质量与天气", [
            ("air_quality", "空气质量 (AQI/污染物)"),
            ("weather", "实时天气 (气温/湿度)"),
        ])
        scroll_layout.addWidget(g_air)

        # 📸 街景
        g_sv, self.opt_street = make_group("📸 街景图像", [
            ("streetview", "百度街景 (360° 四方向)"),
        ])
        scroll_layout.addWidget(g_sv)

        # 🛰️ GEE 遥感 — 基础
        g_gee, self.opt_gee = make_group("🛰️ GEE 遥感数据 — 基础", [
            ("gee_viirs", "VIIRS 夜间灯光"),
            ("gee_ndvi", "NDVI 植被指数"),
            ("gee_lst", "LST 地表温度"),
            ("gee_elevation", "海拔数据"),
            ("gee_precipitation", "降水量"),
            ("gee_ndwi", "NDWI 水体指数"),
            ("gee_evi", "EVI 增强植被"),
            ("gee_population", "人口密度"),
            ("gee_era5_climate", "ERA5 气候逐日"),
            ("gee_era5_hourly", "ERA5 逐时"),
        ])
        scroll_layout.addWidget(g_gee)

        # 🛰️ GEE 遥感 — 扩展
        g_gee2, self.opt_gee2 = make_group("🛰️ GEE 遥感数据 — 扩展", [
            ("gee_landcover", "土地覆盖 (ESA WorldCover)"),
            ("gee_s5p_no2", "Sentinel-5P NO₂ 污染"),
            ("gee_jrc_water", "JRC 地表水体"),
            ("gee_modis_lst", "MODIS LST (8天合成)"),
            ("gee_dynamic_world", "Dynamic World 地类"),
            ("gee_hansen_forest", "Hansen 森林变化"),
            ("gee_canopy_height", "ETH 树冠高度"),
        ])
        scroll_layout.addWidget(g_gee2)

        # 合并 GEE 复选框字典
        self.opt_gee.update(self.opt_gee2)

        # 🗺️ OSM 矢量
        g_osm, self.opt_osm = make_group("🗺️ OSM 矢量数据", [
            ("osm_roads", "道路网络"),
            ("osm_buildings", "建筑物"),
            ("osm_green_spaces", "绿地"),
            ("osm_water_bodies", "水体"),
            ("osm_stats", "OSM 统计指标"),
        ])
        scroll_layout.addWidget(g_osm)

        # 🗄️ 本地数据
        g_local, self.opt_local = make_group("🗄️ 本地数据 (PostgreSQL)", [
            ("local_data", "本地历史 + 导师数据"),
        ])
        scroll_layout.addWidget(g_local)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        outer_layout.addWidget(scroll)

        # ---- 时间能力标注：为所有 checkbox 设置 tooltip ----
        for opt_dict in [self.opt_air, self.opt_street, self.opt_gee, self.opt_osm, self.opt_local]:
            for key, cb in opt_dict.items():
                info = self._TIME_INFO.get(key)
                if info:
                    _icon, desc = info
                    cb.setToolTip(desc)

        # ---- 全选/取消逻辑 ----
        select_all_btn.clicked.connect(lambda: [cb.setChecked(True) for cb in all_checkboxes])
        deselect_all_btn.clicked.connect(lambda: [cb.setChecked(False) for cb in all_checkboxes])

        group.setLayout(outer_layout)
        return group

    def _build_input_group(self):
        group = QGroupBox("📍 采集点位与参数")
        layout = QVBoxLayout()

        # 日期和半径参数行
        param_layout = QHBoxLayout()
        param_layout.addWidget(QLabel("开始日期:"))
        self.start_date = QDateEdit(calendarPopup=True)
        self.start_date.setDate(datetime.now().replace(year=datetime.now().year - 1))
        param_layout.addWidget(self.start_date)

        param_layout.addWidget(QLabel("结束日期:"))
        self.end_date = QDateEdit(calendarPopup=True)
        self.end_date.setDate(datetime.now())
        param_layout.addWidget(self.end_date)

        param_layout.addWidget(QLabel("默认半径(m):"))
        self.radius_spin = QSpinBox()
        self.radius_spin.setRange(100, 50000)
        self.radius_spin.setValue(500)
        param_layout.addWidget(self.radius_spin)
        layout.addLayout(param_layout)

        # 点位表格
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["经度", "纬度", "半径(m)", "备注"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        # 表格操作按钮
        btn_layout = QHBoxLayout()
        for label, slot in [
            ("添加行", self._add_table_row),
            ("删除行", self._remove_table_row),
            ("清空", self._clear_table),
            ("导入CSV", self._import_csv),
            ("导入TXT", self._import_txt),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            btn_layout.addWidget(btn)
        layout.addLayout(btn_layout)

        group.setLayout(layout)
        return group

    def _build_time_slice_group(self):
        """Tab 2: 时间切片对比面板。"""
        group = QGroupBox("🕐 多时间段对比")
        group.setCheckable(True)
        group.setChecked(False)
        group.setToolTip(
            "勾选后，对同一位置按不同年份分别采集。\n"
            "完成后在左侧历史面板可对比不同年份的数据变化"
        )
        layout = QVBoxLayout()

        # 快捷预设
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("快捷预设:"))
        for years, label in [(3, "近3年"), (5, "近5年"), (10, "近10年")]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, n=years: self._preset_time_slices(n))
            preset_row.addWidget(btn)
        custom_btn = QPushButton("自定义年份...")
        custom_btn.clicked.connect(self._gen_time_slices_from_years)
        preset_row.addWidget(custom_btn)
        preset_row.addStretch()
        layout.addLayout(preset_row)

        # 预览标签
        self.time_slice_preview = QLabel("未设置切片")
        self.time_slice_preview.setStyleSheet(
            "color: #555; font-size: 11px; padding: 4px 8px;"
            "background: #f8f8f8; border-radius: 4px;"
        )
        self.time_slice_preview.setWordWrap(True)
        layout.addWidget(self.time_slice_preview)

        # 隐藏的表格（存储数据，_get_time_slices 从中读取）
        self.time_slice_table = QTableWidget(0, 3)
        self.time_slice_table.setHorizontalHeaderLabels(["开始日期", "结束日期", "标签"])
        self.time_slice_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.time_slice_table.setVisible(False)
        layout.addWidget(self.time_slice_table)

        # 手动操作按钮
        manual_row = QHBoxLayout()
        add_btn = QPushButton("➕ 手动添加")
        add_btn.clicked.connect(lambda: (
            self._add_time_slice(),
            self.time_slice_table.setVisible(True),
        ))
        manual_row.addWidget(add_btn)
        toggle_table_btn = QPushButton("📝 编辑表格")
        toggle_table_btn.clicked.connect(
            lambda: self.time_slice_table.setVisible(
                not self.time_slice_table.isVisible()
            )
        )
        manual_row.addWidget(toggle_table_btn)
        clear_btn = QPushButton("清空全部")
        clear_btn.clicked.connect(self._clear_time_slices)
        manual_row.addWidget(clear_btn)
        manual_row.addStretch()
        layout.addLayout(manual_row)

        group.setLayout(layout)
        return group

    def _build_timeline_group(self):
        """Tab 2: 时间线查询面板。"""
        group = QGroupBox("📊 历史数据时间线")
        layout = QVBoxLayout()

        desc = QLabel(
            "查询指定位置在本地数据库中所有历史采集记录，"
            "观察各项指标随时间的变化趋势"
        )
        desc.setStyleSheet("color: #666; font-size: 11px; padding: 2px 0;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        btn_row = QHBoxLayout()
        timeline_btn = QPushButton("📊 查看时间线")
        timeline_btn.setToolTip(
            "使用点位表格第一行的坐标查询历史采集时间线"
        )
        timeline_btn.clicked.connect(self._show_timeline_view)
        btn_row.addWidget(timeline_btn)

        summary_btn = QPushButton("📋 缓存统计")
        summary_btn.setToolTip("查看本地缓存数据库的统计信息")
        summary_btn.clicked.connect(self._show_cache_stats)
        btn_row.addWidget(summary_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        group.setLayout(layout)
        return group

    def _build_ctrl_buttons(self):
        layout = QHBoxLayout()

        start_btn = QPushButton("▶ 开始采集")
        stop_btn = QPushButton("■ 停止采集")
        export_btn = QPushButton("💾 导出当前数据")
        log_btn = QPushButton("📝 查看日志")
        result_btn = QPushButton("📊 查看结果")
        save_proj_btn = QPushButton("📁 保存项目")
        load_proj_btn = QPushButton("📂 加载项目")

        start_btn.clicked.connect(self._start_tasks)
        stop_btn.clicked.connect(self._stop_tasks)
        export_btn.clicked.connect(self._export_current_data)
        log_btn.clicked.connect(self.log_dialog.show)
        result_btn.clicked.connect(self.result_dialog.show)
        save_proj_btn.clicked.connect(self._save_project)
        load_proj_btn.clicked.connect(self._load_project)

        layout.addWidget(start_btn)
        layout.addWidget(stop_btn)
        layout.addWidget(log_btn)
        layout.addWidget(result_btn)
        layout.addWidget(save_proj_btn)
        layout.addWidget(load_proj_btn)
        layout.addStretch()
        layout.addWidget(export_btn)
        return layout

    # ==================== 定时采集 ====================

    def _build_schedule_group(self):
        """构建定时采集面板。"""
        group = QGroupBox("⏰ 定时采集")
        group.setCheckable(True)
        group.setChecked(False)
        group.setToolTip("启用后按设定频率自动采集数据")
        layout = QVBoxLayout()

        # 频率行
        freq_row = QHBoxLayout()
        freq_row.addWidget(QLabel("采集频率:"))
        self.schedule_freq_combo = QComboBox()
        self.schedule_freq_combo.addItems([
            "每天", "每周", "每月",
        ])
        freq_row.addWidget(self.schedule_freq_combo)
        freq_row.addWidget(QLabel("执行时间:"))
        self.schedule_time_edit = QTimeEdit()
        self.schedule_time_edit.setTime(QTime(8, 0))
        self.schedule_time_edit.setDisplayFormat("HH:mm")
        freq_row.addWidget(self.schedule_time_edit)
        freq_row.addStretch()
        layout.addLayout(freq_row)

        # 模式行
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("时间模式:"))
        self.schedule_mode_combo = QComboBox()
        self.schedule_mode_combo.addItems([
            "近 30 天 (滑动窗口)", "近 90 天", "近 365 天",
        ])
        self.schedule_mode_combo.setToolTip(
            "每次自动采集使用的日期范围"
        )
        mode_row.addWidget(self.schedule_mode_combo)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        # 状态和按钮行
        ctrl_row = QHBoxLayout()
        self.schedule_status_label = QLabel("⏸️ 未启动")
        self.schedule_status_label.setStyleSheet(
            "font-weight: bold; color: #888;"
        )
        ctrl_row.addWidget(self.schedule_status_label)

        self.schedule_next_label = QLabel("")
        self.schedule_next_label.setStyleSheet("color: #666; font-size: 11px;")
        ctrl_row.addWidget(self.schedule_next_label)
        ctrl_row.addStretch()

        self.schedule_start_btn = QPushButton("▶ 启动")
        self.schedule_start_btn.clicked.connect(self._start_schedule)
        ctrl_row.addWidget(self.schedule_start_btn)

        self.schedule_stop_btn = QPushButton("⏹ 停止")
        self.schedule_stop_btn.setEnabled(False)
        self.schedule_stop_btn.clicked.connect(self._stop_schedule)
        ctrl_row.addWidget(self.schedule_stop_btn)

        layout.addLayout(ctrl_row)

        group.setLayout(layout)
        return group

    def _calc_schedule_interval(self):
        """计算定时采集间隔（毫秒）。"""
        freq = self.schedule_freq_combo.currentText()
        if freq == "每天":
            return 24 * 60 * 60 * 1000
        elif freq == "每周":
            return 7 * 24 * 60 * 60 * 1000
        else:  # 每月
            return 30 * 24 * 60 * 60 * 1000

    def _get_schedule_days(self):
        """获取定时采集的日期回溯天数。"""
        mode = self.schedule_mode_combo.currentText()
        if "30 天" in mode:
            return 30
        elif "90 天" in mode:
            return 90
        else:
            return 365

    def _start_schedule(self):
        """启动定时采集。"""
        interval = self._calc_schedule_interval()
        self._schedule_timer = QTimer()
        self._schedule_timer.timeout.connect(self._scheduled_collect)
        self._schedule_timer.start(interval)

        # 计算下次执行时间
        now = datetime.now()
        target_time = self.schedule_time_edit.time()
        target_dt = now.replace(
            hour=target_time.hour(),
            minute=target_time.minute(),
            second=0, microsecond=0,
        )
        if target_dt <= now:
            target_dt = target_dt.replace(day=target_dt.day + 1) if self.schedule_freq_combo.currentText() == "每天" else target_dt

        self.schedule_status_label.setText("▶ 运行中")
        self.schedule_status_label.setStyleSheet("font-weight: bold; color: #27ae60;")
        self.schedule_next_label.setText(
            f"下次: {target_dt.strftime('%m-%d %H:%M')}"
        )
        self.schedule_start_btn.setEnabled(False)
        self.schedule_stop_btn.setEnabled(True)

        # 持久化到 QSettings
        self.settings.setValue("schedule/enabled", True)
        self.settings.setValue("schedule/frequency", self.schedule_freq_combo.currentText())
        self.settings.setValue("schedule/mode", self.schedule_mode_combo.currentText())
        self.settings.setValue("schedule/time", self.schedule_time_edit.time().toString("HH:mm"))
        self.settings.sync()

        self.log_box.append("⏰ 定时采集已启动")

    def _stop_schedule(self):
        """停止定时采集。"""
        if hasattr(self, "_schedule_timer") and self._schedule_timer:
            self._schedule_timer.stop()

        self.schedule_status_label.setText("⏸️ 未启动")
        self.schedule_status_label.setStyleSheet("font-weight: bold; color: #888;")
        self.schedule_next_label.setText("")
        self.schedule_start_btn.setEnabled(True)
        self.schedule_stop_btn.setEnabled(False)

        self.settings.setValue("schedule/enabled", False)
        self.settings.sync()

        self.log_box.append("⏰ 定时采集已停止")

    def _scheduled_collect(self):
        """定时触发一次采集。"""
        from datetime import timedelta

        now = datetime.now()
        days = self._get_schedule_days()
        sd = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        ed = now.strftime("%Y-%m-%d")

        self.log_box.append(f"⏰ 定时采集触发 — {sd} ~ {ed}")

        # 记录执行历史
        try:
            from local_cache import get_cache
            cache = get_cache()
            cache.record_schedule_run("running")
        except Exception:
            pass

        # 复用 _start_tasks 逻辑（简版：直接构建任务并执行）
        tasks = []
        for row in range(self.table.rowCount()):
            try:
                lon = float(self.table.item(row, 0).text())
                lat = float(self.table.item(row, 1).text())
                r = int(float(self.table.item(row, 2).text()))
            except (ValueError, AttributeError):
                continue
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                continue
            tasks.append((lon, lat, r, sd, ed))

        if not tasks:
            self.log_box.append("⚠️ 定时采集：无有效点位，跳过")
            try:
                from local_cache import get_cache
                get_cache().record_schedule_run("failed", error_msg="无有效点位")
            except Exception:
                pass
            return

        # 更新下次执行时间
        self.schedule_next_label.setText(
            f"上次: {now.strftime('%m-%d %H:%M')} | "
            f"下次: {(now + timedelta(milliseconds=self._calc_schedule_interval())).strftime('%m-%d %H:%M')}"
        )

        # 构建选项
        options = {}
        for opt_dict in [self.opt_air, self.opt_street, self.opt_gee, self.opt_osm, self.opt_local]:
            for key, cb in opt_dict.items():
                options[key] = cb.isChecked()

        # 同步 PostgreSQL 连接配置
        try:
            self._get_pg_store()
        except Exception:
            pass

        self.worker = Worker(
            tasks,
            self.baidu_key_input.text(),
            self.weather_key_input.text(),
            self.gee_key_input.text(),
            options,
            file_logger=self.file_logger.log,
            output_base_dir=self.output_dir_input.text().strip() or None,
        )
        self.worker.log.connect(self.log_box.append)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.step_progress.connect(self._on_step_progress)
        self.worker.result_ready.connect(self._on_result_ready)

        def on_schedule_finished(dirs):
            duration = (datetime.now() - now).total_seconds() * 1000
            status = "success" if dirs else "failed"
            try:
                from local_cache import get_cache
                get_cache().record_schedule_run(
                    status,
                    output_dir=dirs[0] if dirs else "",
                    duration_ms=int(duration),
                )
            except Exception:
                pass
            self.log_box.append(
                f"⏰ 定时采集完成 — {len(dirs)} 个结果 ({duration/1000:.1f}s)"
            )
            self._load_history()

        self.worker.finished.connect(on_schedule_finished)
        self.worker.start()

    # ==================== 表格操作 ====================

    def _add_table_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem("116.3912"))
        self.table.setItem(row, 1, QTableWidgetItem("39.9055"))
        self.table.setItem(row, 2, QTableWidgetItem(str(self.radius_spin.value())))
        self.table.setItem(row, 3, QTableWidgetItem("手动输入"))

    def _remove_table_row(self):
        if self.table.rowCount() > 0:
            self.table.removeRow(self.table.rowCount() - 1)

    def _clear_table(self):
        self.table.setRowCount(0)

    def _import_csv(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择CSV文件", "", "CSV Files (*.csv)"
        )
        if not file_path:
            return
        try:
            df = pd.read_csv(file_path, encoding='utf-8')
            self.table.setRowCount(0)
            for _, row in df.iterrows():
                r = self.table.rowCount()
                self.table.insertRow(r)
                self.table.setItem(r, 0, QTableWidgetItem(str(row.get('lon', ''))))
                self.table.setItem(r, 1, QTableWidgetItem(str(row.get('lat', ''))))
                self.table.setItem(r, 2, QTableWidgetItem(
                    str(row.get('radius', self.radius_spin.value()))
                ))
                self.table.setItem(r, 3, QTableWidgetItem("来自CSV"))
            self.log_box.append(f"✅ 导入 {len(df)} 条")
        except Exception as e:
            self.log_box.append(f"❌ CSV导入失败: {e}")

    def _import_txt(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择TXT文件", "", "Text Files (*.txt)"
        )
        if not file_path:
            return
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            self.table.setRowCount(0)
            count = 0
            for line in lines:
                parts = line.strip().split(',')
                if len(parts) >= 2:
                    r = self.table.rowCount()
                    self.table.insertRow(r)
                    self.table.setItem(r, 0, QTableWidgetItem(parts[0]))
                    self.table.setItem(r, 1, QTableWidgetItem(parts[1]))
                    self.table.setItem(r, 2, QTableWidgetItem(
                        parts[2] if len(parts) > 2 else str(self.radius_spin.value())
                    ))
                    self.table.setItem(r, 3, QTableWidgetItem("来自TXT"))
                    count += 1
            self.log_box.append(f"✅ 导入 {count} 条")
        except Exception as e:
            self.log_box.append(f"❌ TXT导入失败: {e}")

    # ==================== 配置 ====================

    def _browse_output_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if folder:
            self.output_dir_input.setText(folder)

    def _browse_gee_key_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择 GEE 密钥 JSON 文件", "", "JSON Files (*.json)"
        )
        if file_path:
            self.gee_key_input.setText(file_path)
            self.settings.setValue("keys/gee_key", file_path)
            self.log_box.append(f"✅ 已导入 GEE 密钥文件: {file_path}")

    # ==================== 时间切片管理 ====================

    def _update_time_slice_preview(self):
        """更新切片预览标签。"""
        slices = self._get_time_slices()
        if not slices:
            self.time_slice_preview.setText("未设置切片 — 点击上方快捷预设或手动添加")
            self.time_slice_preview.setStyleSheet(
                "color: #999; font-size: 11px; padding: 4px 8px;"
                "background: #f8f8f8; border-radius: 4px;"
            )
            return

        lines = [f"将采集 <b>{len(slices)}</b> 个时间段:"]
        for sd, ed, lbl in slices:
            lines.append(f"  • <b>{lbl}</b>（{sd} ~ {ed}）")
        preview = "<br>".join(lines)
        self.time_slice_preview.setText(preview)
        self.time_slice_preview.setStyleSheet(
            "color: #2c3e50; font-size: 11px; padding: 4px 8px;"
            "background: #eaf7ea; border-radius: 4px; border: 1px solid #a3d4a3;"
        )

    def _preset_time_slices(self, n_years):
        """快捷预设：生成近 N 年逐年切片。"""
        from datetime import datetime as dt
        current_year = dt.now().year
        self.time_slice_table.setRowCount(0)
        for y in range(current_year - n_years + 1, current_year + 1):
            self._add_time_slice(
                sd=f"{y}-01-01",
                ed=f"{y}-12-31",
                label=f"{y}年",
            )
        self._update_time_slice_preview()
        self.log_box.append(f"✅ 已生成近 {n_years} 年时间切片（{len(self._get_time_slices())} 个）")

    def _add_time_slice(self, sd=None, ed=None, label=""):
        """添加一个时间切片行。"""
        row = self.time_slice_table.rowCount()
        self.time_slice_table.insertRow(row)

        # 默认使用当前日期选择器的值
        if sd is None:
            sd = self.start_date.date().toString("yyyy-MM-dd")
        if ed is None:
            ed = self.end_date.date().toString("yyyy-MM-dd")
        if not label:
            label = f"切片{row + 1}"

        self.time_slice_table.setItem(row, 0, QTableWidgetItem(sd))
        self.time_slice_table.setItem(row, 1, QTableWidgetItem(ed))
        self.time_slice_table.setItem(row, 2, QTableWidgetItem(label))
        self._update_time_slice_preview()

    def _remove_time_slice(self):
        """删除选中的时间切片行。"""
        rows = set()
        for item in self.time_slice_table.selectedItems():
            rows.add(item.row())
        for row in sorted(rows, reverse=True):
            self.time_slice_table.removeRow(row)
        self._update_time_slice_preview()

    def _clear_time_slices(self):
        """清空所有时间切片。"""
        self.time_slice_table.setRowCount(0)
        self._update_time_slice_preview()

    def _gen_time_slices_from_years(self):
        """从年份列表生成时间切片。"""
        text, ok = QInputDialog.getText(
            self, "自定义年份",
            "输入要对比的年份，用逗号分隔\n\n"
            "例如: 2015,2020,2025\n"
            "将对每个年份生成 1月1日~12月31日 的整年切片",
        )
        if not ok or not text.strip():
            return

        try:
            years = [int(y.strip()) for y in text.split(",") if y.strip()]
        except ValueError:
            QMessageBox.warning(self, "格式错误", "请输入有效的年份数字，用逗号分隔")
            return

        self.time_slice_table.setRowCount(0)
        for year in sorted(set(years)):
            self._add_time_slice(
                sd=f"{year}-01-01",
                ed=f"{year}-12-31",
                label=f"{year}年",
            )
        self._update_time_slice_preview()

    def _get_time_slices(self):
        """读取时间切片表格内容，返回 [(start_date, end_date, label), ...]。"""
        slices = []
        for row in range(self.time_slice_table.rowCount()):
            try:
                sd = self.time_slice_table.item(row, 0).text().strip()
                ed = self.time_slice_table.item(row, 1).text().strip()
                lbl = self.time_slice_table.item(row, 2).text().strip()
                if sd and ed:
                    slices.append((sd, ed, lbl or f"切片{row + 1}"))
            except AttributeError:
                continue
        return slices

    # ==================== 任务控制 ====================

    def _start_tasks(self):
        # 保存设置（敏感密钥加密存储）
        self.settings.setValue(
            "keys/weather_key",
            secure_store("weather_key", self.weather_key_input.text()),
        )
        self.settings.setValue("keys/gee_key", self.gee_key_input.text())
        self.settings.setValue(
            "keys/baidu_key",
            secure_store("baidu_key", self.baidu_key_input.text()),
        )
        self.settings.setValue("paths/output_dir", self.output_dir_input.text())

        # 确保设置立即写入磁盘（Windows 注册表），避免意外退出导致丢失
        self.settings.sync()

        # 同步 PostgreSQL 连接配置（供采集管线写库/读库使用）
        try:
            self._get_pg_store()
        except Exception:
            pass

        # 构建细粒度选项 dict
        options = {}
        for opt_dict in [self.opt_air, self.opt_street, self.opt_gee, self.opt_osm, self.opt_local]:
            for key, cb in opt_dict.items():
                options[key] = cb.isChecked()

        # 更新子组件状态
        self.street_view.set_enabled(options.get("streetview", True))
        self.air_quality_view.set_enabled(options.get("air_quality", True))
        self.weather_view.set_enabled(options.get("weather", True))

        any_gee = any(
            cb.isChecked() for cb in self.opt_gee.values()
        )
        any_osm = any(
            cb.isChecked() for cb in self.opt_osm.values()
        )
        self.chart_view.set_enabled(any_gee)
        self.map_view.set_enabled(any_osm)
        self.stats_view.set_enabled(any_gee or any_osm)

        # 输出目录
        output_base = self.output_dir_input.text().strip() or None

        # 收集任务
        tasks = []
        for row in range(self.table.rowCount()):
            try:
                lon = float(self.table.item(row, 0).text())
                lat = float(self.table.item(row, 1).text())
                r = int(float(self.table.item(row, 2).text()))
            except (ValueError, AttributeError):
                self.log_box.append(f"第 {row + 1} 行数据格式有误")
                return

            # 校验坐标范围
            if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
                self.log_box.append(
                    f"第 {row + 1} 行坐标无效: 经度({lon})需在-180~180之间, "
                    f"纬度({lat})需在-90~90之间"
                )
                return
            if r <= 0 or r > 50000:
                self.log_box.append(
                    f"第 {row + 1} 行半径无效: {r}m（需在 1~50000 之间）"
                )
                return

            # 检查是否启用时间切片模式
            if self.time_slice_group.isChecked():
                time_slices = self._get_time_slices()
                if time_slices:
                    for ts_sd, ts_ed, ts_label in time_slices:
                        tasks.append((lon, lat, r, ts_sd, ts_ed, ts_label))
                else:
                    # 时间切片模式启用但无切片 → 回退到默认日期
                    sd = self.start_date.date().toString("yyyy-MM-dd")
                    ed = self.end_date.date().toString("yyyy-MM-dd")
                    tasks.append((lon, lat, r, sd, ed))
            else:
                sd = self.start_date.date().toString("yyyy-MM-dd")
                ed = self.end_date.date().toString("yyyy-MM-dd")
                tasks.append((lon, lat, r, sd, ed))

        if not tasks:
            self.log_box.append("请添加采集点")
            return

        self._stopped_by_user = False
        self.output_dirs.clear()
        self.current_index = 0
        self.progress.setValue(0)

        # 弹出日志窗口
        self.log_dialog.set_status(f"正在采集 {len(tasks)} 个点位...")
        self.log_dialog.show()
        self.log_dialog.raise_()
        self.log_box.append(f"🚀 开始处理 {len(tasks)} 个任务...")

        self.worker = Worker(
            tasks,
            self.baidu_key_input.text(),
            self.weather_key_input.text(),
            self.gee_key_input.text(),
            options,
            file_logger=self.file_logger.log,
            output_base_dir=output_base,
        )
        self.worker.log.connect(self.log_box.append)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.step_progress.connect(self._on_step_progress)
        self.worker.result_ready.connect(self._on_result_ready)
        self.worker.finished.connect(self._on_all_finished)
        self.worker.start()

    def _stop_tasks(self):
        if self.worker and self.worker.isRunning():
            self._stopped_by_user = True
            self.log_box.append("🛑 正在停止（等待当前任务安全退出）...")
            self.worker.stop()
            # 不调用 wait() —— 在主线程阻塞会导致 GUI 卡死
            # worker.finished 信号触发后 _on_all_finished 会处理后续

    def _export_current_data(self):
        if not self.output_dirs:
            QMessageBox.information(self, "提示", "没有可导出的数据")
            return
        current_dir = self.output_dirs[self.current_index]

        # 询问导出格式
        msg = QMessageBox(self)
        msg.setWindowTitle("选择导出格式")
        msg.setText("请选择导出格式:")
        btn_html = msg.addButton("📄 HTML 报告", QMessageBox.ButtonRole.AcceptRole)
        btn_csv = msg.addButton("📊 CSV 汇总", QMessageBox.ButtonRole.ActionRole)
        btn_geojson = msg.addButton("🗺️ GeoJSON 合并", QMessageBox.ButtonRole.ActionRole)
        msg.setStandardButtons(QMessageBox.StandardButton.Cancel)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked == btn_html:
            self._export_html(current_dir)
        elif clicked == btn_csv:
            self._export_csv(current_dir)
        elif clicked == btn_geojson:
            self._export_geojson(current_dir)

    def _export_html(self, current_dir):

        # 收集可用数据
        report_lines = []
        report_lines.append("<h2>📊 城市环境数据采集报告</h2>")

        # 元数据
        meta_path = os.path.join(current_dir, "meta.json")
        if os.path.exists(meta_path):
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            report_lines.append(f"<p><b>位置:</b> {meta.get('location', 'N/A')}<br>")
            report_lines.append(f"<b>采集时间:</b> {meta.get('readable_time', 'N/A')}</p>")

        # 空气质量
        air_path = os.path.join(current_dir, "air_quality.json")
        if os.path.exists(air_path):
            with open(air_path, 'r', encoding='utf-8') as f:
                air = json.load(f)
            if air.get("code") == "200" and "now" in air:
                n = air["now"]
                report_lines.append("<h3>🌬️ 空气质量</h3>")
                report_lines.append(f"<p>AQI 等级: <b>{n.get('aqi', 'N/A')}</b></p>")
                report_lines.append("<table border='1' cellpadding='4'><tr><th>污染物</th><th>浓度 (μg/m³)</th></tr>")
                from config import POLLUTANT_NAMES
                comps = n.get("components", {})
                for key, label in POLLUTANT_NAMES.items():
                    if key in comps:
                        report_lines.append(f"<tr><td>{label}</td><td>{comps[key]:.2f}</td></tr>")
                report_lines.append("</table>")

        # 街景
        sv_dir = os.path.join(current_dir, "streetview_images")
        if os.path.exists(sv_dir):
            jpgs = glob.glob(os.path.join(sv_dir, "*.jpg"))
            if jpgs:
                report_lines.append("<h3>📸 街景 (存在街景覆盖)</h3>")
                report_lines.append(f"<p>共 {len(jpgs)} 张图片</p>")

        # 遥感数据
        for label, csv_name in [("NDVI", "ndvi_stats.csv"),
                                 ("EVI", "evi_stats.csv"),
                                 ("NDWI", "ndwi_stats.csv"),
                                 ("地表温度", "lst_stats.csv"),
                                 ("夜光强度", "viirs_stats.csv"),
                                 ("降水量", "precipitation_stats.csv")]:
            csv_path = os.path.join(current_dir, csv_name)
            if os.path.exists(csv_path):
                df = pd.read_csv(csv_path)
                report_lines.append(f"<h3>📈 {label}</h3>")
                report_lines.append(df.tail(10).to_html(index=False, border=1))

        # 海拔和人口统计（单行数据）
        for label, csv_name in [("海拔", "elevation_stats.csv"),
                                 ("人口密度", "population_stats.csv"),
                                 ("土地覆盖", "landcover_stats.csv"),
                                 ("地表水", "jrc_water_stats.csv"),
                                 ("森林变化", "hansen_forest_stats.csv"),
                                 ("树冠高度", "canopy_height_stats.csv")]:
            csv_path = os.path.join(current_dir, csv_name)
            if os.path.exists(csv_path):
                df = pd.read_csv(csv_path)
                report_lines.append(f"<h3>📊 {label}</h3>")
                report_lines.append(df.to_html(index=False, border=1))

        # Sentinel-5P NO₂（时间序列）
        s5p_path = os.path.join(current_dir, "s5p_no2_stats.csv")
        if os.path.exists(s5p_path):
            df = pd.read_csv(s5p_path)
            report_lines.append("<h3>📈 对流层 NO₂ (Sentinel-5P)</h3>")
            report_lines.append(df.tail(10).to_html(index=False, border=1))

        # MODIS LST
        modis_path = os.path.join(current_dir, "modis_lst_stats.csv")
        if os.path.exists(modis_path):
            df = pd.read_csv(modis_path)
            report_lines.append("<h3>📈 MODIS 地表温度 (8天合成)</h3>")
            report_lines.append(df.tail(10).to_html(index=False, border=1))

        # Dynamic World
        dw_path = os.path.join(current_dir, "dw_stats.csv")
        if os.path.exists(dw_path):
            df = pd.read_csv(dw_path)
            report_lines.append("<h3>📈 Dynamic World 土地覆盖</h3>")
            report_lines.append(df.tail(10).to_html(index=False, border=1))

        # OSM 统计指标
        osm_stats_path = os.path.join(current_dir, "osm_stats.json")
        if os.path.exists(osm_stats_path):
            with open(osm_stats_path, 'r', encoding='utf-8') as f:
                osm_s = json.load(f)
            report_lines.append("<h3>🏗️ OSM 统计指标</h3>")
            bld = osm_s.get("buildings", {})
            if bld:
                report_lines.append(
                    f"<p>🏠 <b>建筑:</b> {bld.get('建筑数量', 'N/A')} 栋, "
                    f"总面积 {bld.get('建筑总面积_m2', 'N/A'):,.0f} m², "
                    f"覆盖率 {bld.get('建筑覆盖率_pct', 'N/A')}%</p>"
                )
            rd = osm_s.get("roads", {})
            if rd:
                report_lines.append(
                    f"<p>🛣️ <b>路网:</b> 总长 {rd.get('道路总长度_km', 'N/A')} km, "
                    f"密度 {rd.get('路网密度_km_per_km2', 'N/A')} km/km², "
                    f"交叉口 {rd.get('交叉口数量', 'N/A')} 个</p>"
                )
            gr = osm_s.get("green_spaces", {})
            if gr:
                report_lines.append(
                    f"<p>🌿 <b>绿地:</b> 面积 {gr.get('绿地总面积_m2', 'N/A'):,.0f} m², "
                    f"覆盖率 {gr.get('绿地覆盖率_pct', 'N/A')}%, "
                    f"体积估算 {gr.get('绿地体积估算_m3', 'N/A'):,.0f} m³</p>"
                )

        # OSM 数据
        for label, geo_name in [("路网", "roads.geojson"),
                                 ("建筑", "buildings.geojson"),
                                 ("绿地", "green_spaces.geojson"),
                                 ("水体", "water_bodies.geojson")]:
            geo_path = os.path.join(current_dir, geo_name)
            if os.path.exists(geo_path):
                with open(geo_path, 'r', encoding='utf-8') as f:
                    gdata = json.load(f)
                count = len(gdata.get("features", []))
                report_lines.append(f"<p>🗺️ <b>{label}:</b> {count} 个要素</p>")

        report_html = f"""<html><head><meta charset='utf-8'>
        <title>数据采集报告</title>
        <style>body{{font-family:'Microsoft YaHei',sans-serif;padding:20px;max-width:900px;margin:auto}}
        table{{border-collapse:collapse;width:100%}}th{{background:#4CAF50;color:white}}td,th{{padding:6px}}
        h2{{color:#333}}h3{{color:#555;border-bottom:2px solid #4CAF50}}</style></head>
        <body>{''.join(report_lines)}</body></html>"""

        save_path, _ = QFileDialog.getSaveFileName(
            self, "导出报告", f"report_{Path(current_dir).name}.html",
            "HTML Files (*.html)",
        )
        if save_path:
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(report_html)
            QDesktopServices.openUrl(QUrl.fromLocalFile(save_path))
            self.log_box.append(f"📄 报告已保存: {save_path}")

    def _export_csv(self, current_dir):
        """导出为 CSV 汇总（合并多个采集点的统计指标）。"""
        rows = []
        for out_dir in self.output_dirs:
            row = {"目录": Path(out_dir).name}
            # 读取 meta
            meta_path = os.path.join(out_dir, "meta.json")
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                    row["位置"] = meta.get("location", "")
                    row["采集时间"] = meta.get("readable_time", "")
                except Exception:
                    pass

            # 海拔
            elev_path = os.path.join(out_dir, "elevation_stats.csv")
            if os.path.exists(elev_path):
                try:
                    df = pd.read_csv(elev_path)
                    if not df.empty:
                        row["海拔均值_m"] = df.iloc[0].get("海拔均值_m", "")
                except Exception:
                    pass

            # 人口
            pop_path = os.path.join(out_dir, "population_stats.csv")
            if os.path.exists(pop_path):
                try:
                    df = pd.read_csv(pop_path)
                    if not df.empty:
                        row["估算总人口"] = df.iloc[0].get("总人口估算", "")
                except Exception:
                    pass

            # OSM 统计
            osm_path = os.path.join(out_dir, "osm_stats.json")
            if os.path.exists(osm_path):
                try:
                    with open(osm_path, 'r', encoding='utf-8') as f:
                        osm = json.load(f)
                    bld = osm.get("buildings", {})
                    if bld:
                        row["建筑数量"] = bld.get("建筑数量", "")
                        row["建筑覆盖率_pct"] = bld.get("建筑覆盖率_pct", "")
                    rd = osm.get("roads", {})
                    if rd:
                        row["道路总长_km"] = rd.get("道路总长度_km", "")
                        row["路网密度"] = rd.get("路网密度_km_per_km2", "")
                    gr = osm.get("green_spaces", {})
                    if gr:
                        row["绿地覆盖率_pct"] = gr.get("绿地覆盖率_pct", "")
                except Exception:
                    pass

            # 新增：土地覆盖
            lc_path = os.path.join(out_dir, "landcover_stats.csv")
            if os.path.exists(lc_path):
                try:
                    df = pd.read_csv(lc_path)
                    data_rows = df[df['地物类别'] != '【汇总】']
                    for _, r in data_rows.iterrows():
                        row[f"地类_{r['地物类别']}_pct"] = r.get("占比_pct", "")
                except Exception:
                    pass

            # 新增：森林变化
            forest_path = os.path.join(out_dir, "hansen_forest_stats.csv")
            if os.path.exists(forest_path):
                try:
                    df = pd.read_csv(forest_path)
                    if not df.empty:
                        r = df.iloc[0]
                        row["树冠覆盖率2000_pct"] = r.get("2000年树冠覆盖率均值_pct", "")
                        row["森林净变化_km2"] = r.get("净变化_km2", "")
                except Exception:
                    pass

            # 新增：地表水
            water_path = os.path.join(out_dir, "jrc_water_stats.csv")
            if os.path.exists(water_path):
                try:
                    df = pd.read_csv(water_path)
                    if not df.empty:
                        r = df.iloc[0]
                        row["常年水体面积_km2"] = r.get("常年水体面积_km2", "")
                        row["水体出现频率_pct"] = r.get("水体出现频率均值_pct", "")
                except Exception:
                    pass

            rows.append(row)

        if not rows:
            QMessageBox.information(self, "提示", "没有可汇总的数据")
            return

        df = pd.DataFrame(rows)
        save_path, _ = QFileDialog.getSaveFileName(
            self, "导出 CSV 汇总", f"summary_{datetime.now():%Y%m%d_%H%M%S}.csv",
            "CSV Files (*.csv)",
        )
        if save_path:
            df.to_csv(save_path, index=False, encoding='utf-8-sig')
            QDesktopServices.openUrl(QUrl.fromLocalFile(save_path))
            self.log_box.append(f"📊 CSV 汇总已保存: {save_path}")

    def _export_geojson(self, current_dir):
        """导出为合并的 GeoJSON（将所有 OSM 图层合并到一个文件）。"""
        layer_names = {
            "roads.geojson": "路网",
            "buildings.geojson": "建筑",
            "green_spaces.geojson": "绿地",
            "water_bodies.geojson": "水体",
        }
        all_features = []
        for filename, layer_label in layer_names.items():
            geo_path = os.path.join(current_dir, filename)
            if os.path.exists(geo_path):
                try:
                    with open(geo_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    for feat in data.get("features", []):
                        feat["properties"]["_layer"] = layer_label
                        all_features.append(feat)
                except Exception:
                    pass

        if not all_features:
            QMessageBox.information(self, "提示", "没有可导出的 GeoJSON 数据")
            return

        merged = {
            "type": "FeatureCollection",
            "features": all_features,
        }
        save_path, _ = QFileDialog.getSaveFileName(
            self, "导出合并 GeoJSON", f"merged_{Path(current_dir).name}.geojson",
            "GeoJSON Files (*.geojson)",
        )
        if save_path:
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
            self.log_box.append(f"🗺️ GeoJSON 已保存: {save_path}")

    # ==================== 项目保存/加载 ====================

    def _save_project(self):
        """保存当前配置为项目文件。"""
        # 收集表格点位
        points = []
        for row in range(self.table.rowCount()):
            try:
                lon = float(self.table.item(row, 0).text())
                lat = float(self.table.item(row, 1).text())
                r = int(float(self.table.item(row, 2).text()))
                note = self.table.item(row, 3).text() if self.table.item(row, 3) else ""
                points.append({"lon": lon, "lat": lat, "radius": r, "note": note})
            except (ValueError, AttributeError):
                continue

        # 收集选项
        options = {}
        for opt_dict in [self.opt_air, self.opt_street, self.opt_gee, self.opt_osm, self.opt_local]:
            for key, cb in opt_dict.items():
                options[key] = cb.isChecked()

        project = {
            "version": 1,
            "points": points,
            "options": options,
            "start_date": self.start_date.date().toString("yyyy-MM-dd"),
            "end_date": self.end_date.date().toString("yyyy-MM-dd"),
            "default_radius": self.radius_spin.value(),
            "time_slices": self._get_time_slices(),
            "time_slice_enabled": self.time_slice_group.isChecked(),
        }

        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存项目", "project.json", "JSON Files (*.json)",
        )
        if save_path:
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(project, f, ensure_ascii=False, indent=2)
            self.log_box.append(f"📁 项目已保存: {save_path}")

    def _load_project(self):
        """从项目文件加载配置。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "加载项目", "", "JSON Files (*.json)",
        )
        if not file_path:
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                project = json.load(f)
        except Exception as e:
            self.log_box.append(f"❌ 加载项目失败: {e}")
            return

        # 恢复点位
        self.table.setRowCount(0)
        for pt in project.get("points", []):
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(pt.get("lon", ""))))
            self.table.setItem(row, 1, QTableWidgetItem(str(pt.get("lat", ""))))
            self.table.setItem(row, 2, QTableWidgetItem(str(pt.get("radius", ""))))
            self.table.setItem(row, 3, QTableWidgetItem(str(pt.get("note", ""))))

        # 恢复选项
        options = project.get("options", {})
        for opt_dict in [self.opt_air, self.opt_street, self.opt_gee, self.opt_osm, self.opt_local]:
            for key, cb in opt_dict.items():
                cb.setChecked(options.get(key, True))

        # 恢复日期
        if "start_date" in project:
            self.start_date.setDate(
                datetime.strptime(project["start_date"], "%Y-%m-%d")
            )
        if "end_date" in project:
            self.end_date.setDate(
                datetime.strptime(project["end_date"], "%Y-%m-%d")
            )

        # 恢复半径
        if "default_radius" in project:
            self.radius_spin.setValue(project["default_radius"])

        # 恢复时间切片
        self.time_slice_table.setRowCount(0)
        for ts in project.get("time_slices", []):
            if len(ts) >= 3:
                self._add_time_slice(sd=ts[0], ed=ts[1], label=ts[2])
        self.time_slice_group.setChecked(
            project.get("time_slice_enabled", False)
        )

        self.log_box.append(f"📂 项目已加载: {len(project.get('points', []))} 个点位")

    # ==================== 结果回调 ====================

    def _on_step_progress(self, step_name, current, total):
        if total > 0:
            self.step_label.setText(f"📦 {step_name} ({current}/{total})")
        else:
            self.step_label.setText(step_name)

    def _on_result_ready(self, output_dir):
        self.output_dirs.append(output_dir)
        self.current_index = len(self.output_dirs) - 1
        self._update_result_display()
        # 首个结果到达时自动弹出结果窗口
        if len(self.output_dirs) == 1:
            self.result_dialog.show()
            self.result_dialog.raise_()

    def _on_all_finished(self):
        if self._stopped_by_user:
            self.log_box.append("✅ 任务已停止")
            self.log_dialog.set_status("⏹️ 已停止")
            self._stopped_by_user = False
        else:
            self.log_box.append("🎉 所有任务完成！")
            self.log_dialog.set_status("✅ 采集完成")
        # 采集完成后自动刷新历史记录列表
        self._load_history()

    def _update_result_display(self):
        if not self.output_dirs:
            self.result_label.setText("暂无结果")
            return
        current_dir = self.output_dirs[self.current_index]
        self.result_label.setText(
            f"结果 {self.current_index + 1}/{len(self.output_dirs)}: "
            f"{Path(current_dir).name}"
        )
        # 使用内存缓存避免重复读盘
        if current_dir in self._data_cache:
            cached = self._data_cache[current_dir]
            # 移到 LRU 尾部（最近使用）
            del self._data_cache[current_dir]
            self._data_cache[current_dir] = cached
        else:
            # 限制缓存大小
            while len(self._data_cache) >= 5:
                oldest = next(iter(self._data_cache))
                del self._data_cache[oldest]
            self._data_cache[current_dir] = {}

        self.street_view.set_output_dir(current_dir)
        self.chart_view.set_output_dir(current_dir)
        self.map_view.set_output_dir(current_dir)
        self.air_quality_view.set_output_dir(current_dir)
        self.weather_view.set_output_dir(current_dir)
        self.stats_view.set_output_dir(current_dir)

    def _show_prev(self):
        if self.output_dirs:
            self.current_index = (self.current_index - 1) % len(self.output_dirs)
            self._update_result_display()

    def _show_next(self):
        if self.output_dirs:
            self.current_index = (self.current_index + 1) % len(self.output_dirs)
            self._update_result_display()

    # ==================== 历史记录 ====================

    def _get_output_globs(self):
        """在所有可能的位置搜索 output_* 目录。"""
        patterns = ["output_*"]
        out_dir = self.output_dir_input.text().strip()
        if out_dir and os.path.isdir(out_dir):
            patterns.append(os.path.join(out_dir, "output_*"))
        return patterns

    def _load_history(self):
        self.history_list.clear()
        folders = []
        seen = set()
        for pattern in self._get_output_globs():
            for folder in glob.glob(pattern):
                abs_path = os.path.abspath(folder)
                if abs_path not in seen:
                    seen.add(abs_path)
                    folders.append(folder)
        folders.sort(key=os.path.getmtime, reverse=True)

        # 获取时间筛选
        filter_text = self.history_filter_combo.currentText()
        now = datetime.now()
        if filter_text == "最近 7 天":
            cutoff = now.timestamp() - 7 * 86400
        elif filter_text == "最近 30 天":
            cutoff = now.timestamp() - 30 * 86400
        elif filter_text == "最近 90 天":
            cutoff = now.timestamp() - 90 * 86400
        elif filter_text == "本年":
            cutoff = datetime(now.year, 1, 1).timestamp()
        else:
            cutoff = 0  # 全部

        for folder in folders:
            if cutoff > 0 and os.path.getmtime(folder) < cutoff:
                continue
            # 尝试读取 meta.json 获取位置和时间信息
            meta_path = os.path.join(folder, "meta.json")
            display = os.path.basename(folder)
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                    loc = meta.get("location", "")
                    rtime = meta.get("readable_time", "")
                    if loc or rtime:
                        display = f"📍 {loc} | {rtime}" if loc and rtime else (loc or rtime)
                except (json.JSONDecodeError, OSError):
                    pass

            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, folder)
            item.setToolTip(f"路径: {os.path.abspath(folder)}")
            self.history_list.addItem(item)

        # 更新缓存统计
        try:
            from local_cache import get_cache
            cache = get_cache()
            s = cache.get_summary()
            self.cache_stats_label.setText(
                f"📊 共 {s['总采集次数']} 次采集 | {s['独立位置数']} 个位置 | "
                f"最近: {s.get('最近采集', '无')[:16] if s.get('最近采集') else '无'}"
            )
        except Exception:
            self.cache_stats_label.setText("")

    def _on_history_clicked(self, item):
        folder = item.data(Qt.ItemDataRole.UserRole)
        if not os.path.exists(folder):
            self.log_box.append("❌ 文件夹不存在")
            return

        if self.compare_cb.isChecked():
            # 对比模式：累积选中
            if not hasattr(self, '_compare_dirs'):
                self._compare_dirs = []
            if folder in self._compare_dirs:
                self._compare_dirs.remove(folder)
                self.log_box.append(f"📂 取消对比: {Path(folder).name}")
            else:
                self._compare_dirs.append(folder)
                self.log_box.append(f"📂 加入对比 ({len(self._compare_dirs)}/2): {Path(folder).name}")
            # 高亮选中项
            for i in range(self.history_list.count()):
                it = self.history_list.item(i)
                d = it.data(Qt.ItemDataRole.UserRole)
                if d in self._compare_dirs:
                    it.setBackground(Qt.GlobalColor.darkCyan)
                else:
                    it.setBackground(Qt.GlobalColor.transparent)
        else:
            self.output_dirs = [folder]
            self.current_index = 0
            self._update_result_display()
            self.result_dialog.show()
            self.result_dialog.raise_()
            self.log_box.append(f"📂 加载历史: {folder}")

    def _compare_selected(self):
        """弹出对比对话框，并排展示两个采集点的统计指标。"""
        if not hasattr(self, '_compare_dirs') or len(self._compare_dirs) < 2:
            QMessageBox.information(self, "提示", "请先在对比模式下选中两个历史记录")
            return

        dir_a, dir_b = self._compare_dirs[:2]
        stats_a = self._gather_compare_stats(dir_a)
        stats_b = self._gather_compare_stats(dir_b)

        # 构建对比对话框
        dlg = QDialog(self)
        dlg.setWindowTitle("📊 数据对比")
        dlg.resize(800, 500)
        layout = QVBoxLayout(dlg)

        header = QLabel(
            f"<b>{Path(dir_a).name}</b>  ↔  <b>{Path(dir_b).name}</b>"
        )
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["指标", "A", "B", "差值"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        rows = []
        all_keys = sorted(set(list(stats_a.keys()) + list(stats_b.keys())))
        for key in all_keys:
            va = stats_a.get(key, "—")
            vb = stats_b.get(key, "—")
            diff = "—"
            try:
                if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
                    diff = f"{vb - va:+.2f}"
            except Exception:
                pass
            rows.append((key, str(va), str(vb), diff))

        table.setRowCount(len(rows))
        for i, (k, va, vb, diff) in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(k))
            table.setItem(i, 1, QTableWidgetItem(va))
            table.setItem(i, 2, QTableWidgetItem(vb))
            item_diff = QTableWidgetItem(diff)
            if diff != "—":
                try:
                    if float(diff) > 0:
                        item_diff.setForeground(Qt.GlobalColor.red)
                    elif float(diff) < 0:
                        item_diff.setForeground(Qt.GlobalColor.darkGreen)
                except Exception:
                    pass
            table.setItem(i, 3, item_diff)

        layout.addWidget(table)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn)
        dlg.exec()

    @staticmethod
    def _gather_compare_stats(output_dir):
        """从输出目录收集关键统计指标。"""
        stats = {}
        # meta
        meta_path = os.path.join(output_dir, "meta.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                stats["位置"] = meta.get("location", "—")
            except Exception:
                pass

        # 海拔
        elev_path = os.path.join(output_dir, "elevation_stats.csv")
        if os.path.exists(elev_path):
            try:
                df = pd.read_csv(elev_path)
                if not df.empty:
                    row = df.iloc[0]
                    for col in df.columns:
                        stats[col] = row[col]
            except Exception:
                pass

        # 人口
        pop_path = os.path.join(output_dir, "population_stats.csv")
        if os.path.exists(pop_path):
            try:
                df = pd.read_csv(pop_path)
                if not df.empty:
                    row = df.iloc[0]
                    for col in df.columns:
                        if col != "数据来源":
                            stats[col] = row[col]
            except Exception:
                pass

        # OSM 统计
        osm_path = os.path.join(output_dir, "osm_stats.json")
        if os.path.exists(osm_path):
            try:
                with open(osm_path, 'r', encoding='utf-8') as f:
                    osm = json.load(f)
                for section in ["buildings", "roads", "green_spaces"]:
                    for k, v in osm.get(section, {}).items():
                        stats[f"[OSM]{k}"] = v
            except Exception:
                pass

        # 新增：土地覆盖
        lc_path = os.path.join(output_dir, "landcover_stats.csv")
        if os.path.exists(lc_path):
            try:
                df = pd.read_csv(lc_path)
                data_rows = df[df['地物类别'] != '【汇总】']
                for _, r in data_rows.iterrows():
                    stats[f"[地类]{r['地物类别']}_pct"] = r.get("占比_pct", "")
            except Exception:
                pass

        # 新增：森林变化
        forest_path = os.path.join(output_dir, "hansen_forest_stats.csv")
        if os.path.exists(forest_path):
            try:
                df = pd.read_csv(forest_path)
                if not df.empty:
                    r = df.iloc[0]
                    for col in df.columns:
                        stats[f"[森林]{col}"] = r[col]
            except Exception:
                pass

        # 新增：树冠高度
        canopy_path = os.path.join(output_dir, "canopy_height_stats.csv")
        if os.path.exists(canopy_path):
            try:
                df = pd.read_csv(canopy_path)
                if not df.empty:
                    r = df.iloc[0]
                    for col in df.columns:
                        stats[f"[树冠]{col}"] = r[col]
            except Exception:
                pass

        # 新增：地表水
        water_path = os.path.join(output_dir, "jrc_water_stats.csv")
        if os.path.exists(water_path):
            try:
                df = pd.read_csv(water_path)
                if not df.empty:
                    r = df.iloc[0]
                    for col in df.columns:
                        stats[f"[地表水]{col}"] = r[col]
            except Exception:
                pass

        return stats

    def _on_history_context_menu(self, pos: QPoint):
        """历史记录右键菜单：删除单条、导出单条。"""
        item = self.history_list.itemAt(pos)
        if not item:
            return
        folder = item.data(Qt.ItemDataRole.UserRole)

        menu = QMenu(self)

        delete_action = QAction("🗑️ 删除此记录", self)
        delete_action.triggered.connect(lambda: self._delete_single(folder))
        menu.addAction(delete_action)

        export_action = QAction("💾 导出此记录", self)
        export_action.triggered.connect(lambda: self._export_single(folder))
        menu.addAction(export_action)

        open_action = QAction("📂 打开文件夹", self)
        open_action.triggered.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(os.path.abspath(folder))
        ))
        menu.addAction(open_action)

        menu.exec(self.history_list.mapToGlobal(pos))

    def _delete_single(self, folder):
        """删除单条历史记录。"""
        name = Path(folder).name
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定删除此记录？\n\n{name}\n\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                import shutil
                shutil.rmtree(folder)
                self.log_box.append(f"🗑️ 已删除: {name}")
                self._load_history()
            except Exception as e:
                self.log_box.append(f"❌ 删除失败: {e}")

    def _export_single(self, folder):
        """从右键菜单导出单条记录（复用 HTML 导出）。"""
        self._export_html(folder)

    def _show_timeline_view(self):
        """显示指定位置的历史数据时间线视图。"""
        # 从当前表格获取第一个点的坐标
        if self.table.rowCount() == 0:
            QMessageBox.information(self, "提示", "请先在点位表格中添加一个位置")
            return
        try:
            lon = float(self.table.item(0, 0).text())
            lat = float(self.table.item(0, 1).text())
            r = int(float(self.table.item(0, 2).text()))
        except (ValueError, AttributeError):
            QMessageBox.warning(self, "错误", "无法读取第一个点位的坐标")
            return

        try:
            from local_cache import get_cache
            cache = get_cache()
            records = cache.get_timeline(lon, lat, radius=1000)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"查询数据库失败: {e}")
            return

        if not records:
            QMessageBox.information(
                self, "时间线",
                f"位置 ({lon:.4f}, {lat:.4f}) 附近没有历史采集记录。\n\n"
                f"提示：执行一次采集后会自动记录到本地数据库。"
            )
            return

        # 构建时间线对话框
        dlg = QDialog(self)
        dlg.setWindowTitle(f"📊 时间线视图 — ({lon:.4f}, {lat:.4f})")
        dlg.resize(900, 500)
        layout = QVBoxLayout(dlg)

        info = QLabel(
            f"<b>位置:</b> Lon={lon:.4f}, Lat={lat:.4f} | "
            f"<b>半径:</b> {r}m | <b>共 {len(records)} 条记录</b>"
        )
        layout.addWidget(info)

        table = QTableWidget()
        table.setColumnCount(6)
        table.setHorizontalHeaderLabels([
            "采集时间", "时间范围", "标签", "半径(m)", "产出文件数", "输出目录",
        ])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        table.setRowCount(len(records))
        for i, rec in enumerate(records):
            table.setItem(i, 0, QTableWidgetItem(rec.get("collected_at", "")))
            table.setItem(i, 1, QTableWidgetItem(
                f"{rec.get('start_date', '')} ~ {rec.get('end_date', '')}"
            ))
            table.setItem(i, 2, QTableWidgetItem(rec.get("label", "")))
            table.setItem(i, 3, QTableWidgetItem(str(rec.get("radius", ""))))
            table.setItem(i, 4, QTableWidgetItem(str(rec.get("file_count", ""))))
            table.setItem(i, 5, QTableWidgetItem(rec.get("output_dir", "")))

        layout.addWidget(table)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn)
        dlg.exec()

    def _show_cache_stats(self):
        """显示本地缓存数据库统计信息。"""
        try:
            from local_cache import get_cache
            cache = get_cache()
            summary = cache.get_summary()
        except Exception as e:
            QMessageBox.warning(self, "错误", f"读取缓存失败: {e}")
            return

        try:
            from plugins.streetview_archive import StreetViewArchive
            sv = StreetViewArchive()
            sv_stats = sv.count_all()
        except Exception:
            sv_stats = {"总存档数": 0, "独立位置数": 0}

        msg = (
            f"📊 本地缓存统计\n\n"
            f"采集记录: {summary['总采集次数']} 次 "
            f"(成功 {summary['成功次数']} 次)\n"
            f"独立位置: {summary['独立位置数']} 个\n"
            f"最近采集: {summary.get('最近采集', '无')}\n\n"
            f"街景存档: {sv_stats.get('总存档数', 0)} 张 "
            f"({sv_stats.get('独立位置数', 0)} 个位置)"
        )
        QMessageBox.information(self, "📊 缓存统计", msg)

    def _clean_data_dialog(self):
        """打开清理数据对话框，支持自定义时间范围和选择性删除。"""
        import shutil
        import traceback as _tb

        try:
            self._clean_data_dialog_impl()
        except Exception as e:
            _tb.print_exc()
            QMessageBox.critical(
                self, "错误",
                f"打开清理对话框时出错:\n\n{type(e).__name__}: {e}"
            )
            self.log_box.append(f"❌ 清理对话框出错: {e}")

    def _clean_data_dialog_impl(self):
        """清理对话框实现体。"""
        import shutil

        # ---- 收集候选目录 ----
        all_folders = []
        seen = set()
        for pattern in self._get_output_globs():
            for f in glob.glob(pattern):
                abs_path = os.path.abspath(f)
                if abs_path not in seen:
                    seen.add(abs_path)
                    all_folders.append(f)

        if not all_folders:
            QMessageBox.information(self, "提示", "没有可清理的数据")
            return

        # ---- 构建简单列表对话框 ----
        dlg = QDialog(self)
        dlg.setWindowTitle("🗑️ 清理采集数据")
        dlg.resize(700, 450)
        layout = QVBoxLayout(dlg)

        # 时间筛选
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("删除范围:"))
        time_combo = QComboBox()
        time_combo.addItems(["全部", "7天前", "30天前", "60天前", "90天前"])
        time_combo.setCurrentIndex(2)
        filter_row.addWidget(time_combo)
        filter_row.addStretch()
        info_label = QLabel("")
        filter_row.addWidget(info_label)
        layout.addLayout(filter_row)

        # 目录列表
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["", "目录信息"])
        table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(table)

        # ---- 数据准备（快速模式：不递归计算目录大小，避免卡顿） ----
        folder_data = []  # (folder, mtime, meta_text)
        for folder in all_folders:
            mtime = os.path.getmtime(folder)
            meta_text = ""
            meta_path = os.path.join(folder, "meta.json")
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, 'r', encoding='utf-8') as mf:
                        meta = json.load(mf)
                    loc = meta.get("location", "")
                    rtime = meta.get("readable_time", "")
                    meta_text = f"{loc} | {rtime}" if loc or rtime else ""
                except Exception:
                    pass
            folder_data.append((folder, mtime, meta_text))

        folder_data.sort(key=lambda x: x[1], reverse=True)

        # ---- 刷新列表 ----
        days_map = {0: None, 1: 7, 2: 30, 3: 60, 4: 90}

        def refresh(days=None):
            table.setRowCount(0)
            now_ts = datetime.now().timestamp()
            threshold = 0 if days is None else now_ts - days * 24 * 3600
            visible = []
            for fd in folder_data:
                folder, mtime, meta_text = fd
                if days is None or mtime < threshold:
                    visible.append(fd)

            table.setRowCount(len(visible))
            for i, (folder, _mtime, meta_text) in enumerate(visible):
                # 第0列：复选框
                item_cb = QTableWidgetItem("")
                item_cb.setFlags(
                    Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEnabled
                )
                item_cb.setCheckState(Qt.CheckState.Unchecked)
                item_cb.setData(Qt.ItemDataRole.UserRole, folder)
                table.setItem(i, 0, item_cb)
                # 第1列：信息
                display = f"{Path(folder).name}"
                if meta_text:
                    display += f"  —  {meta_text}"
                table.setItem(i, 1, QTableWidgetItem(display))

            info_label.setText(f"共 {len(visible)} 条")

        refresh(days_map[time_combo.currentIndex()])
        time_combo.currentIndexChanged.connect(
            lambda idx: refresh(days_map.get(idx, None))
        )

        # ---- 全选/取消 ----
        def toggle_all(state):
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item:
                    item.setCheckState(state)

        quick_row = QHBoxLayout()
        all_btn = QPushButton("全选")
        none_btn = QPushButton("取消全选")
        all_btn.clicked.connect(
            lambda: toggle_all(Qt.CheckState.Checked))
        none_btn.clicked.connect(
            lambda: toggle_all(Qt.CheckState.Unchecked))
        quick_row.addWidget(all_btn)
        quick_row.addWidget(none_btn)
        quick_row.addStretch()
        layout.addLayout(quick_row)

        # ---- 底部按钮 ----
        def do_delete():
            to_delete = []
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item and item.checkState() == Qt.CheckState.Checked:
                    f = item.data(Qt.ItemDataRole.UserRole)
                    if f:
                        to_delete.append(f)

            if not to_delete:
                QMessageBox.information(dlg, "提示", "请先勾选要删除的数据")
                return

            # 确认（不计算大小，避免卡顿）
            reply = QMessageBox.question(
                dlg, "⚠️ 确认删除",
                f"确定删除选中的 {len(to_delete)} 条记录？\n\n"
                f"此操作不可撤销。",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

            deleted = 0
            for f in to_delete:
                try:
                    shutil.rmtree(f)
                    deleted += 1
                except Exception as e:
                    self.log_box.append(f"❌ 删除失败 {f}: {e}")

            self.log_box.append(f"🧹 已删除 {deleted} 条记录")
            self._load_history()
            dlg.accept()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(dlg.reject)
        btn_row.addWidget(cancel_btn)
        del_btn = QPushButton("🗑️ 删除选中")
        del_btn.setStyleSheet(
            "QPushButton { background-color: #d9534f; color: white;"
            " font-weight: bold; padding: 8px 20px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #c9302c; }"
        )
        del_btn.clicked.connect(do_delete)
        btn_row.addWidget(del_btn)
        layout.addLayout(btn_row)

        dlg.exec()

    # ==================== 本地数据 (PostgreSQL) ====================

    def _build_local_group(self):
        """构建「本地数据」Tab：连接设置 + 查询 + 导入导师数据。"""
        panel = QWidget()
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(6, 6, 6, 6)

        # ---- 连接设置 ----
        conn_group = QGroupBox("🔌 PostgreSQL 连接设置")
        form = QGridLayout()

        self.pg_host_input = QLineEdit()
        self.pg_port_input = QLineEdit()
        self.pg_db_input = QLineEdit()
        self.pg_user_input = QLineEdit()
        self.pg_pwd_input = QLineEdit()
        self.pg_pwd_input.setEchoMode(QLineEdit.EchoMode.Password)

        self.pg_host_input.setText(self.settings.value("pg/host", PG_HOST))
        self.pg_port_input.setText(self.settings.value("pg/port", str(PG_PORT)))
        self.pg_db_input.setText(self.settings.value("pg/dbname", PG_DBNAME))
        self.pg_user_input.setText(self.settings.value("pg/user", PG_USER))
        stored_pwd = self.settings.value("pg/password", "")
        self.pg_pwd_input.setText(
            secure_load("pg_pwd", stored_pwd) if stored_pwd else PG_PASSWORD
        )

        form.addWidget(QLabel("主机:"), 0, 0)
        form.addWidget(self.pg_host_input, 0, 1)
        form.addWidget(QLabel("端口:"), 0, 2)
        form.addWidget(self.pg_port_input, 0, 3)
        form.addWidget(QLabel("数据库:"), 1, 0)
        form.addWidget(self.pg_db_input, 1, 1)
        form.addWidget(QLabel("用户:"), 1, 2)
        form.addWidget(self.pg_user_input, 1, 3)
        form.addWidget(QLabel("密码:"), 2, 0)
        form.addWidget(self.pg_pwd_input, 2, 1, 1, 3)
        conn_group.setLayout(form)
        outer.addWidget(conn_group)

        # ---- 连接操作按钮 ----
        btn_row = QHBoxLayout()
        test_btn = QPushButton("🔍 测试连接")
        test_btn.clicked.connect(self._test_pg_connection)
        btn_row.addWidget(test_btn)
        init_btn = QPushButton("🛠️ 初始化表")
        init_btn.clicked.connect(self._init_pg_schema)
        btn_row.addWidget(init_btn)
        save_btn = QPushButton("💾 保存连接")
        save_btn.clicked.connect(self._save_pg_settings)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        outer.addLayout(btn_row)

        # ---- 查询本地数据 ----
        query_group = QGroupBox("🔎 查询本地数据（按坐标）")
        q = QVBoxLayout()
        qrow = QHBoxLayout()
        qrow.addWidget(QLabel("经度:"))
        self.pg_q_lon = QLineEdit()
        qrow.addWidget(self.pg_q_lon)
        qrow.addWidget(QLabel("纬度:"))
        self.pg_q_lat = QLineEdit()
        qrow.addWidget(self.pg_q_lat)
        qrow.addWidget(QLabel("半径(m):"))
        self.pg_q_radius = QSpinBox()
        self.pg_q_radius.setRange(100, 50000)
        self.pg_q_radius.setValue(1000)
        qrow.addWidget(self.pg_q_radius)
        q.addLayout(qrow)

        qbtn_row = QHBoxLayout()
        fill_btn = QPushButton("用表格第一行坐标")
        fill_btn.clicked.connect(self._fill_query_from_table)
        qbtn_row.addWidget(fill_btn)
        query_btn = QPushButton("🔎 查询")
        query_btn.clicked.connect(self._query_local_data)
        qbtn_row.addWidget(query_btn)
        qbtn_row.addStretch()
        q.addLayout(qbtn_row)

        self.pg_result_label = QLabel("")
        self.pg_result_label.setStyleSheet("color: #666; font-size: 11px;")
        q.addWidget(self.pg_result_label)

        self.pg_result_table = QTableWidget(0, 5)
        self.pg_result_table.setHorizontalHeaderLabels(
            ["类型", "来源", "指标", "值", "时间"]
        )
        self.pg_result_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        q.addWidget(self.pg_result_table)
        query_group.setLayout(q)
        outer.addWidget(query_group)

        # ---- 导入导师数据 ----
        import_group = QGroupBox("📥 导入导师数据 (CSV)")
        il = QVBoxLayout()
        ir = QHBoxLayout()
        import_btn = QPushButton("📥 选择 CSV 导入")
        import_btn.clicked.connect(self._import_local_csv)
        ir.addWidget(import_btn)
        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.clicked.connect(self._refresh_datasets)
        ir.addWidget(refresh_btn)
        ir.addStretch()
        il.addLayout(ir)
        self.pg_dataset_list = QListWidget()
        self.pg_dataset_list.itemClicked.connect(self._on_dataset_clicked)
        il.addWidget(self.pg_dataset_list)
        import_group.setLayout(il)
        outer.addWidget(import_group)

        return panel

    def _get_pg_store(self):
        """按界面连接参数构建/配置 PostgresStore 单例。"""
        from pg_store import get_store
        try:
            port = int(self.pg_port_input.text().strip())
        except ValueError:
            port = PG_PORT
        return get_store(
            host=self.pg_host_input.text().strip() or PG_HOST,
            port=port,
            dbname=self.pg_db_input.text().strip() or PG_DBNAME,
            user=self.pg_user_input.text().strip() or PG_USER,
            password=self.pg_pwd_input.text() or PG_PASSWORD,
        )

    def _save_pg_settings(self):
        self.settings.setValue("pg/host", self.pg_host_input.text().strip())
        self.settings.setValue("pg/port", self.pg_port_input.text().strip())
        self.settings.setValue("pg/dbname", self.pg_db_input.text().strip())
        self.settings.setValue("pg/user", self.pg_user_input.text().strip())
        self.settings.setValue(
            "pg/password", secure_store("pg_pwd", self.pg_pwd_input.text())
        )
        self.settings.sync()
        self.log_box.append("🔌 PostgreSQL 连接设置已保存")

    def _test_pg_connection(self):
        try:
            store = self._get_pg_store()
            if store.is_available():
                QMessageBox.information(self, "连接成功", "✅ PostgreSQL 连接成功")
                self.log_box.append("✅ PostgreSQL 连接成功")
            else:
                QMessageBox.warning(
                    self, "连接失败",
                    "❌ 无法连接 PostgreSQL\n\n请确认服务已启动（双击 scripts/pg_start.bat）",
                )
        except Exception as e:
            QMessageBox.warning(self, "连接失败", f"❌ 连接异常: {e}")

    def _init_pg_schema(self):
        try:
            store = self._get_pg_store()
            ok, err = store.init_schema()
            if ok:
                QMessageBox.information(self, "成功", "✅ 表结构已初始化（6 张表）")
                self.log_box.append("✅ PostgreSQL 表结构已初始化")
            else:
                QMessageBox.warning(self, "失败", f"❌ 初始化失败: {err}")
        except Exception as e:
            QMessageBox.warning(self, "失败", f"❌ 初始化异常: {e}")

    def _fill_query_from_table(self):
        if self.table.rowCount() == 0:
            return
        try:
            self.pg_q_lon.setText(self.table.item(0, 0).text())
            self.pg_q_lat.setText(self.table.item(0, 1).text())
        except AttributeError:
            pass

    def _add_result_row(self, type_, source, metric, value, time_):
        r = self.pg_result_table.rowCount()
        self.pg_result_table.insertRow(r)
        self.pg_result_table.setItem(r, 0, QTableWidgetItem(type_))
        self.pg_result_table.setItem(r, 1, QTableWidgetItem(str(source)))
        self.pg_result_table.setItem(r, 2, QTableWidgetItem(str(metric)))
        self.pg_result_table.setItem(r, 3, QTableWidgetItem(str(value)))
        self.pg_result_table.setItem(r, 4, QTableWidgetItem(str(time_)))

    def _query_local_data(self):
        try:
            lon = float(self.pg_q_lon.text().strip())
            lat = float(self.pg_q_lat.text().strip())
        except ValueError:
            QMessageBox.warning(self, "错误", "请输入有效的经纬度")
            return
        radius = self.pg_q_radius.value()
        try:
            result = self._get_pg_store().query_local(lon, lat, radius)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"查询失败: {e}")
            return

        self.pg_result_label.setText(
            f"📊 历史采集 {len(result['runs'])} 次 | "
            f"指标 {len(result['metrics'])} 条 | "
            f"导师数据 {len(result['local_records'])} 条"
        )
        self.pg_result_table.setRowCount(0)
        for m in result["metrics"][:500]:
            self._add_result_row(
                "指标", m.get("source", ""), m.get("metric", ""),
                m.get("value", ""), m.get("obs_time") or "",
            )
        for rec in result["local_records"][:200]:
            payload = rec.get("payload", {})
            summary = (json.dumps(payload, ensure_ascii=False)[:80]
                       if isinstance(payload, dict) else str(payload))
            self._add_result_row(
                "导师数据", f"数据集{rec.get('dataset_id', '')}", summary,
                "", rec.get("obs_time") or "",
            )

    def _import_local_csv(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择 CSV 文件", "", "CSV Files (*.csv)"
        )
        if not file_path:
            return
        name, ok = QInputDialog.getText(self, "数据集名称", "输入数据集名称:")
        if not ok or not name.strip():
            return
        try:
            dataset_id, count = self._get_pg_store().import_csv(
                file_path, name.strip(), source="导师提供",
            )
        except Exception as e:
            QMessageBox.warning(self, "错误", f"导入失败: {e}")
            return
        if dataset_id is None:
            QMessageBox.warning(self, "错误", "导入失败：请确认 CSV 可读且 PostgreSQL 已连接")
            return
        self.log_box.append(f"📥 已导入导师数据「{name.strip()}」: {count} 条")
        self._refresh_datasets()

    def _refresh_datasets(self):
        self.pg_dataset_list.clear()
        try:
            for d in self._get_pg_store().list_datasets():
                item = QListWidgetItem(
                    f"{d['name']} — {d['record_count']} 条 "
                    f"({d.get('imported_at', '')})"
                )
                item.setData(Qt.ItemDataRole.UserRole, d["id"])
                self.pg_dataset_list.addItem(item)
        except Exception:
            pass

    def _on_dataset_clicked(self, item):
        dataset_id = item.data(Qt.ItemDataRole.UserRole)
        try:
            records = self._get_pg_store().query_dataset(dataset_id)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"查询失败: {e}")
            return
        self.pg_result_table.setRowCount(0)
        for rec in records:
            payload = rec.get("payload", {})
            summary = (json.dumps(payload, ensure_ascii=False)[:80]
                       if isinstance(payload, dict) else str(payload))
            self._add_result_row(
                "导师数据", f"数据集{dataset_id}", summary,
                rec.get("lon") if rec.get("lon") is not None else "",
                rec.get("obs_time") or "",
            )
        self.pg_result_label.setText(f"📥 数据集 {dataset_id} 共 {len(records)} 条记录")

    # ==================== 生命周期 ====================

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait(3000)
        event.accept()
