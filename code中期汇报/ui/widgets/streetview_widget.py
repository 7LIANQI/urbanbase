"""街景图片展示组件。"""
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap


class StreetViewWidget(QWidget):
    """显示百度街景全景图片，支持四方向切换。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_dir = None
        self.enabled = True
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()

        control_layout = QHBoxLayout()
        control_layout.addWidget(QLabel("选择方向:"))
        self.direction_combo = QComboBox()
        self.direction_combo.addItems([
            "0° (正前方)", "90° (右方)", "180° (后方)", "270° (左方)",
        ])
        self.direction_combo.currentIndexChanged.connect(self._load_image)
        control_layout.addWidget(self.direction_combo)
        control_layout.addStretch()
        layout.addLayout(control_layout)

        self.image_label = QLabel("暂无街景图片\n请先执行数据采集")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(600, 400)
        self.image_label.setStyleSheet("""
            QLabel {
                border: 2px solid #cccccc;
                border-radius: 5px;
                background-color: #f0f0f0;
            }
        """)
        layout.addWidget(self.image_label)
        self.setLayout(layout)

    def set_enabled(self, enabled):
        self.enabled = enabled
        if not self.enabled:
            self.image_label.setText("街景显示已禁用（采集时未勾选）")

    def set_output_dir(self, output_dir):
        self.current_dir = output_dir
        if self.enabled:
            self._load_image()
        else:
            self.image_label.setText("街景显示已禁用（采集时未勾选）")

    def _load_image(self):
        if not self.enabled:
            self.image_label.setText("街景显示已禁用")
            return
        if not self.current_dir:
            self.image_label.setText("请先执行数据采集")
            return

        image_dir = Path(self.current_dir) / "streetview_images"
        if not image_dir.exists():
            self.image_label.setText("未找到街景图片目录")
            return

        direction_map = {0: "0", 1: "90", 2: "180", 3: "270"}
        angle = direction_map.get(self.direction_combo.currentIndex(), "0")
        image_path = image_dir / f"heading_{angle}.jpg"

        if image_path.exists():
            pixmap = QPixmap(str(image_path))
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(
                    self.image_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.image_label.setPixmap(scaled_pixmap)
            else:
                self.image_label.setText(f"图片损坏: {image_path.name}")
        else:
            jpg_files = list(image_dir.glob("*.jpg"))
            if jpg_files:
                self.image_label.setText(
                    f"未找到 {angle}° 方向图片\n"
                    f"找到的图片: {[f.name for f in jpg_files[:3]]}"
                )
            else:
                self.image_label.setText("该位置无街景覆盖")
