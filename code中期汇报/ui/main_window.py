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
)
from PyQt6.QtCore import Qt, QSettings, QUrl
from PyQt6.QtGui import QDesktopServices

from .worker import Worker
from .widgets import (
    AirQualityWidget,
    WeatherWidget,
    StreetViewWidget,
    ChartWidget,
    MapWidget,
    StatsWidget,
)
from utils import FileLogger


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
        self.settings = QSettings("MyCompany", "UrbanAnalysisApp")
        self.file_logger = FileLogger("logs")

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
        panel.setFixedWidth(260)
        layout = QVBoxLayout(panel)

        label = QLabel("📜 历史记录")
        label.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(label)

        self.history_list = QListWidget()
        self.history_list.itemClicked.connect(self._on_history_clicked)
        layout.addWidget(self.history_list)

        clean_btn = QPushButton("🗑️ 清理30天前数据")
        clean_btn.clicked.connect(self._clean_old_data)
        layout.addWidget(clean_btn)

        layout.addStretch()
        return panel

    def _build_right_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)

        layout.addWidget(self._build_api_group())
        layout.addWidget(self._build_proxy_group())
        layout.addWidget(self._build_options_group())
        layout.addWidget(self._build_input_group())
        layout.addLayout(self._build_ctrl_buttons())

        self.progress = QProgressBar()
        layout.addWidget(self.progress)

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
        self.weather_key_input.setText(self.settings.value("keys/weather_key", ""))
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
        self.baidu_key_input.setPlaceholderText("百度地图 AK (用于街景)")
        self.baidu_key_input.setText(self.settings.value("keys/baidu_key", ""))
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

    def _build_options_group(self):
        group = QGroupBox("📦 数据采集选项")
        layout = QHBoxLayout()

        self.check_air = QCheckBox("空气质量")
        self.check_street = QCheckBox("街景图像")
        self.check_gee = QCheckBox("GEE 遥感")
        self.check_osm = QCheckBox("路网数据")
        self.check_chart = QCheckBox("自动图表")

        for cb in [self.check_air, self.check_street, self.check_gee,
                    self.check_osm, self.check_chart]:
            cb.setChecked(True)
            layout.addWidget(cb)

        group.setLayout(layout)
        return group

    def _build_proxy_group(self):
        group = QGroupBox("🔗 代理设置（国内环境：被墙服务走代理，百度直连）")
        layout = QVBoxLayout()

        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("代理地址:"))
        self.proxy_url_input = QLineEdit()
        self.proxy_url_input.setPlaceholderText("如 http://127.0.0.1:7890（留空则不使用代理）")
        self.proxy_url_input.setText(self.settings.value("proxy/url", ""))
        url_row.addWidget(self.proxy_url_input)
        layout.addLayout(url_row)

        cb_row = QHBoxLayout()
        cb_row.addWidget(QLabel("服务开关:"))
        self.proxy_air_cb = QCheckBox("OpenWeatherMap")
        self.proxy_gee_cb = QCheckBox("GEE")
        self.proxy_osm_cb = QCheckBox("OSM")
        self.proxy_street_cb = QCheckBox("百度街景")

        # 默认：百度不走代理（走了会被拒），其余走代理
        self.proxy_air_cb.setChecked(True)
        self.proxy_gee_cb.setChecked(True)
        self.proxy_osm_cb.setChecked(True)
        self.proxy_street_cb.setChecked(False)
        self.proxy_street_cb.setToolTip("百度地图检测海外 IP，走代理会导致请求被拒")

        cb_row.addWidget(self.proxy_air_cb)
        cb_row.addWidget(self.proxy_gee_cb)
        cb_row.addWidget(self.proxy_osm_cb)
        cb_row.addWidget(self.proxy_street_cb)
        cb_row.addStretch()
        layout.addLayout(cb_row)

        hint = QLabel("提示：使用 Clash/V2Ray 等工具时，请确保百度走直连规则，其余走代理")
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)

        group.setLayout(layout)
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

    def _build_ctrl_buttons(self):
        layout = QHBoxLayout()

        start_btn = QPushButton("▶ 开始采集")
        stop_btn = QPushButton("■ 停止采集")
        export_btn = QPushButton("💾 导出当前数据")
        log_btn = QPushButton("📝 查看日志")
        result_btn = QPushButton("📊 查看结果")

        start_btn.clicked.connect(self._start_tasks)
        stop_btn.clicked.connect(self._stop_tasks)
        export_btn.clicked.connect(self._export_current_data)
        log_btn.clicked.connect(self.log_dialog.show)
        result_btn.clicked.connect(self.result_dialog.show)

        layout.addWidget(start_btn)
        layout.addWidget(stop_btn)
        layout.addWidget(log_btn)
        layout.addWidget(result_btn)
        layout.addStretch()
        layout.addWidget(export_btn)
        return layout

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

    # ==================== 任务控制 ====================

    def _start_tasks(self):
        # 保存设置
        self.settings.setValue("keys/weather_key", self.weather_key_input.text())
        self.settings.setValue("keys/gee_key", self.gee_key_input.text())
        self.settings.setValue("keys/baidu_key", self.baidu_key_input.text())
        self.settings.setValue("paths/output_dir", self.output_dir_input.text())
        self.settings.setValue("proxy/url", self.proxy_url_input.text())

        enable_air = self.check_air.isChecked()
        enable_street = self.check_street.isChecked()
        enable_gee = self.check_gee.isChecked()
        enable_osm = self.check_osm.isChecked()
        enable_chart = self.check_chart.isChecked()

        # 更新子组件状态
        self.street_view.set_enabled(enable_street)
        self.chart_view.set_enabled(enable_chart and enable_gee)
        self.map_view.set_enabled(enable_osm)
        self.air_quality_view.set_enabled(enable_air)
        self.weather_view.set_enabled(enable_air)
        self.stats_view.set_enabled(enable_gee or enable_osm)

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

            sd = self.start_date.date().toString("yyyy-MM-dd")
            ed = self.end_date.date().toString("yyyy-MM-dd")
            tasks.append((lon, lat, r, sd, ed))

        if not tasks:
            self.log_box.append("请添加采集点")
            return

        self.output_dirs.clear()
        self.current_index = 0
        self.progress.setValue(0)

        # 弹出日志窗口
        self.log_dialog.set_status(f"正在采集 {len(tasks)} 个点位...")
        self.log_dialog.show()
        self.log_dialog.raise_()
        self.log_box.append(f"🚀 开始处理 {len(tasks)} 个任务...")

        # 代理配置
        proxy_url = self.proxy_url_input.text().strip()
        proxy_config = {
            "url": proxy_url,
            "air": self.proxy_air_cb.isChecked(),
            "street": self.proxy_street_cb.isChecked(),
            "gee": self.proxy_gee_cb.isChecked(),
            "osm": self.proxy_osm_cb.isChecked(),
        } if proxy_url else None

        self.worker = Worker(
            tasks,
            self.baidu_key_input.text(),
            self.weather_key_input.text(),
            self.gee_key_input.text(),
            enable_air, enable_street, enable_gee, enable_osm,
            file_logger=self.file_logger.log,
            output_base_dir=output_base,
            proxy_config=proxy_config,
        )
        self.worker.log.connect(self.log_box.append)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.result_ready.connect(self._on_result_ready)
        self.worker.finished.connect(self._on_all_finished)
        self.worker.start()

    def _stop_tasks(self):
        if self.worker and self.worker.isRunning():
            self.log_box.append("🛑 正在停止...")
            self.worker.stop()
            self.worker.wait()
            self.log_box.append("✅ 已停止")

    def _export_current_data(self):
        if not self.output_dirs:
            QMessageBox.information(self, "提示", "没有可导出的数据")
            return
        current_dir = self.output_dirs[self.current_index]

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
                                 ("人口密度", "population_stats.csv")]:
            csv_path = os.path.join(current_dir, csv_name)
            if os.path.exists(csv_path):
                df = pd.read_csv(csv_path)
                report_lines.append(f"<h3>📊 {label}</h3>")
                report_lines.append(df.to_html(index=False, border=1))

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

    # ==================== 结果回调 ====================

    def _on_result_ready(self, output_dir):
        self.output_dirs.append(output_dir)
        self.current_index = len(self.output_dirs) - 1
        self._update_result_display()
        # 首个结果到达时自动弹出结果窗口
        if len(self.output_dirs) == 1:
            self.result_dialog.show()
            self.result_dialog.raise_()

    def _on_all_finished(self):
        self.log_box.append("🎉 所有任务完成！")
        self.log_dialog.set_status("✅ 采集完成")

    def _update_result_display(self):
        if not self.output_dirs:
            self.result_label.setText("暂无结果")
            return
        current_dir = self.output_dirs[self.current_index]
        self.result_label.setText(
            f"结果 {self.current_index + 1}/{len(self.output_dirs)}: "
            f"{Path(current_dir).name}"
        )
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

        for folder in folders:
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
                        display = f"{loc} | {rtime}" if loc and rtime else (loc or rtime)
                except (json.JSONDecodeError, OSError):
                    pass

            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, folder)
            item.setToolTip(f"路径: {os.path.abspath(folder)}")
            self.history_list.addItem(item)

    def _on_history_clicked(self, item):
        folder = item.data(Qt.ItemDataRole.UserRole)
        if os.path.exists(folder):
            self.output_dirs = [folder]
            self.current_index = 0
            self._update_result_display()
            self.result_dialog.show()
            self.result_dialog.raise_()
            self.log_box.append(f"📂 加载历史: {folder}")
        else:
            self.log_box.append("❌ 文件夹不存在")

    def _clean_old_data(self):
        reply = QMessageBox.question(
            self, "确认", "确定清理30天前数据？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            threshold = datetime.now().timestamp() - 30 * 24 * 3600
            cleaned = 0
            for pattern in self._get_output_globs():
                for folder in glob.glob(pattern):
                    try:
                        if os.path.getmtime(folder) < threshold:
                            import shutil
                            shutil.rmtree(folder)
                            cleaned += 1
                    except Exception as e:
                        self.log_box.append(f"清理失败 {folder}: {e}")
            self.log_box.append(f"🧹 清理完成，已删除 {cleaned} 个目录")
            self._load_history()

    # ==================== 生命周期 ====================

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait(3000)
        event.accept()
