"""主窗口 —— 城市街道环境大数据采集与分析平台 GUI。"""
import os
import glob
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel, QLineEdit, QCheckBox,
    QDateEdit, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QProgressBar,
    QTabWidget, QTextEdit, QListWidget, QListWidgetItem,
    QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt, QSettings, QUrl
from PyQt6.QtGui import QDesktopServices

from .worker import Worker
from .widgets import (
    AirQualityWidget,
    StreetViewWidget,
    ChartWidget,
    MapWidget,
)


class MainWindow(QWidget):
    """应用主窗口。"""

    def __init__(self):
        super().__init__()
        self.output_dirs = []
        self.current_index = 0
        self.worker = None
        self.settings = QSettings("MyCompany", "UrbanAnalysisApp")

        self._init_ui()
        self._load_history()

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
        layout.addWidget(self._build_options_group())
        layout.addWidget(self._build_input_group())
        layout.addLayout(self._build_ctrl_buttons())

        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        layout.addWidget(self._build_tabs())
        layout.addLayout(self._build_nav_bar())

        layout.addWidget(QLabel("📝 运行日志"))
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(120)
        layout.addWidget(self.log_box)

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
        row2.addWidget(QLabel("GEE 密钥路径:"))
        self.gee_key_input = QLineEdit()
        self.gee_key_input.setPlaceholderText("GEE JSON 路径 (可选)")
        self.gee_key_input.setText(self.settings.value("keys/gee_key", ""))
        row2.addWidget(self.gee_key_input)
        form.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("百度地图 AK:"))
        self.baidu_key_input = QLineEdit()
        self.baidu_key_input.setPlaceholderText("百度地图 AK (用于街景)")
        self.baidu_key_input.setText(self.settings.value("keys/baidu_key", ""))
        row3.addWidget(self.baidu_key_input)
        form.addLayout(row3)

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

        start_btn.clicked.connect(self._start_tasks)
        stop_btn.clicked.connect(self._stop_tasks)
        export_btn.clicked.connect(self._export_current_data)

        layout.addWidget(start_btn)
        layout.addWidget(stop_btn)
        layout.addStretch()
        layout.addWidget(export_btn)
        return layout

    def _build_tabs(self):
        tabs = QTabWidget()

        self.street_view = StreetViewWidget()
        self.chart_view = ChartWidget()
        self.map_view = MapWidget()
        self.air_quality_view = AirQualityWidget()

        tabs.addTab(self.street_view, "📸 街景展示")
        tabs.addTab(self.chart_view, "📊 遥感图表")
        tabs.addTab(self.map_view, "🗺️ 地图展示")
        tabs.addTab(self.air_quality_view, "🌬️ 空气质量")
        return tabs

    def _build_nav_bar(self):
        layout = QHBoxLayout()

        prev_btn = QPushButton("⬅ 上一条")
        next_btn = QPushButton("下一条 ➡")
        self.result_label = QLabel("暂无结果")

        prev_btn.clicked.connect(self._show_prev)
        next_btn.clicked.connect(self._show_next)

        layout.addWidget(prev_btn)
        layout.addWidget(self.result_label)
        layout.addWidget(next_btn)
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

    # ==================== 任务控制 ====================

    def _start_tasks(self):
        # 保存设置
        self.settings.setValue("keys/weather_key", self.weather_key_input.text())
        self.settings.setValue("keys/gee_key", self.gee_key_input.text())
        self.settings.setValue("keys/baidu_key", self.baidu_key_input.text())

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

        # 收集任务
        tasks = []
        for row in range(self.table.rowCount()):
            try:
                lon = float(self.table.item(row, 0).text())
                lat = float(self.table.item(row, 1).text())
                r = int(float(self.table.item(row, 2).text()))
                sd = self.start_date.date().toString("yyyy-MM-dd")
                ed = self.end_date.date().toString("yyyy-MM-dd")
                tasks.append((lon, lat, r, sd, ed))
            except (ValueError, AttributeError):
                self.log_box.append(f"第 {row + 1} 行数据有误")
                return

        if not tasks:
            self.log_box.append("请添加采集点")
            return

        self.output_dirs.clear()
        self.current_index = 0
        self.progress.setValue(0)
        self.log_box.append(f"🚀 开始处理 {len(tasks)} 个任务...")

        self.worker = Worker(
            tasks,
            self.baidu_key_input.text(),
            self.weather_key_input.text(),
            self.gee_key_input.text(),
            enable_air, enable_street, enable_gee, enable_osm,
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
        QDesktopServices.openUrl(QUrl.fromLocalFile(current_dir))

    # ==================== 结果回调 ====================

    def _on_result_ready(self, output_dir):
        self.output_dirs.append(output_dir)
        self.current_index = len(self.output_dirs) - 1
        self._update_result_display()

    def _on_all_finished(self):
        self.log_box.append("🎉 所有任务完成！")

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

    def _show_prev(self):
        if self.output_dirs:
            self.current_index = (self.current_index - 1) % len(self.output_dirs)
            self._update_result_display()

    def _show_next(self):
        if self.output_dirs:
            self.current_index = (self.current_index + 1) % len(self.output_dirs)
            self._update_result_display()

    # ==================== 历史记录 ====================

    def _load_history(self):
        self.history_list.clear()
        folders = sorted(glob.glob("output_*"), key=os.path.getmtime, reverse=True)
        for folder in folders:
            item = QListWidgetItem(os.path.basename(folder))
            item.setData(Qt.ItemDataRole.UserRole, folder)
            self.history_list.addItem(item)

    def _on_history_clicked(self, item):
        folder = item.data(Qt.ItemDataRole.UserRole)
        if os.path.exists(folder):
            self.output_dirs = [folder]
            self.current_index = 0
            self._update_result_display()
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
            for folder in glob.glob("output_*"):
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
