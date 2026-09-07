"""空气质量展示组件。"""
import json
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
)
from PyQt6.QtCore import Qt

from config import AQI_COLORS, POLLUTANT_NAMES


class AirQualityWidget(QWidget):
    """显示 AQI 等级与污染物浓度表格。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_dir = None
        self.enabled = True
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()

        self.aqi_label = QLabel("AQI 等级: --")
        self.aqi_label.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: #333; padding: 10px;"
        )
        self.aqi_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.aqi_label)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["污染物", "浓度 (μg/m³)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        self.info_label = QLabel("请先执行数据采集以查看空气质量")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.info_label)

        self.setLayout(layout)

    def set_enabled(self, enabled):
        self.enabled = enabled
        if not self.enabled:
            self.aqi_label.setText("空气质量显示已禁用")
            self.table.setRowCount(0)
            self.info_label.setText("（采集时未勾选空气质量模块）")

    def set_output_dir(self, output_dir):
        self.current_dir = output_dir
        if self.enabled:
            self._load_data()
        else:
            self.aqi_label.setText("空气质量显示已禁用")
            self.table.setRowCount(0)

    def _load_data(self):
        if not self.current_dir:
            return

        json_path = Path(self.current_dir) / "air_quality.json"
        if not json_path.exists():
            self.aqi_label.setText("AQI 等级: 未找到数据")
            self.table.setRowCount(0)
            self.info_label.setText("该位置未采集空气质量数据")
            return

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if data.get("code") == "200" and "now" in data:
                now = data["now"]
                aqi = now.get("aqi", "N/A")
                components = now.get("components", {})

                color = AQI_COLORS.get(aqi, "black")
                self.aqi_label.setStyleSheet(
                    f"font-size: 24px; font-weight: bold; color: {color}; padding: 10px;"
                )
                self.aqi_label.setText(f"AQI 等级: {aqi}")

                rows = [
                    (POLLUTANT_NAMES[key], f"{components[key]:.2f}")
                    for key in POLLUTANT_NAMES
                    if key in components
                ]
                self.table.setRowCount(len(rows))
                for i, (label, value) in enumerate(rows):
                    self.table.setItem(i, 0, QTableWidgetItem(label))
                    self.table.setItem(i, 1, QTableWidgetItem(value))

                self.info_label.setText(
                    f"数据更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
            else:
                self.aqi_label.setText("数据格式错误或接口调用失败")
        except Exception as e:
            self.aqi_label.setText("读取数据失败")
            self.info_label.setText(f"错误: {str(e)}")
