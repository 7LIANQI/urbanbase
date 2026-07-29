"""街景图片展示组件。"""
import json
import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QDialog, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap


class StreetViewWidget(QWidget):
    """显示百度街景全景图片，支持四方向切换和历史对比。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_dir = None
        self.enabled = True
        self._archive_lon = None
        self._archive_lat = None
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

        # 历史对比按钮
        self.compare_btn = QPushButton("📸 历史对比")
        self.compare_btn.setToolTip("查看该位置不同时间的街景对比")
        self.compare_btn.clicked.connect(self._show_history_compare)
        self.compare_btn.setEnabled(False)
        control_layout.addWidget(self.compare_btn)

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

        # 拍摄日期标签
        self.date_label = QLabel("")
        self.date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.date_label.setStyleSheet("color: #888; font-size: 12px; padding: 4px;")
        layout.addWidget(self.date_label)

        self.setLayout(layout)

    def set_enabled(self, enabled):
        self.enabled = enabled
        if not self.enabled:
            self.image_label.setText("街景显示已禁用（采集时未勾选）")

    def set_output_dir(self, output_dir):
        self.current_dir = output_dir
        # 尝试从 meta.json 读取坐标
        self._archive_lon = None
        self._archive_lat = None
        if output_dir:
            meta_path = Path(output_dir) / "meta.json"
            if meta_path.exists():
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    loc = meta.get("location", "")
                    # "Lon:116.3912, Lat:39.9055" → parse
                    if "Lon:" in loc and "Lat:" in loc:
                        parts = loc.replace("Lon:", "").replace("Lat:", "").split(",")
                        if len(parts) >= 2:
                            self._archive_lon = float(parts[0].strip())
                            self._archive_lat = float(parts[1].strip())
                except Exception:
                    pass

        if self.enabled:
            self._load_date()
            self._load_image()
            self._check_archive()
        else:
            self.image_label.setText("街景显示已禁用（采集时未勾选）")
            self.date_label.setText("")
            self.compare_btn.setEnabled(False)

    def _check_archive(self):
        """检查存档中是否有历史对比数据。"""
        if self._archive_lon is None or self._archive_lat is None:
            self.compare_btn.setEnabled(False)
            return
        try:
            from plugins.streetview_archive import StreetViewArchive
            archive = StreetViewArchive()
            pairs = archive.get_comparison_pairs(
                self._archive_lon, self._archive_lat
            )
            self.compare_btn.setEnabled(len(pairs) > 0)
            if pairs:
                self.compare_btn.setToolTip(
                    f"该位置有 {len(pairs)} 组历史对比数据"
                )
        except Exception:
            self.compare_btn.setEnabled(False)

    def _show_history_compare(self):
        """弹出街景历史对比对话框。"""
        if self._archive_lon is None or self._archive_lat is None:
            QMessageBox.information(self, "提示", "无法确定当前位置坐标")
            return

        try:
            from plugins.streetview_archive import StreetViewArchive
            archive = StreetViewArchive()
            pairs = archive.get_comparison_pairs(
                self._archive_lon, self._archive_lat
            )
        except Exception as e:
            QMessageBox.warning(self, "错误", f"查询存档失败: {e}")
            return

        if not pairs:
            QMessageBox.information(
                self, "提示",
                "该位置暂无历史对比数据。\n\n"
                "需要对同一位置在不同时间采集街景，系统会自动存档。"
            )
            return

        # 构建对比对话框
        dlg = QDialog(self)
        dlg.setWindowTitle("📸 街景历史对比")
        dlg.resize(1000, 500)
        dlg_layout = QVBoxLayout(dlg)

        info = QLabel(
            f"<b>位置:</b> Lon={self._archive_lon:.4f}, Lat={self._archive_lat:.4f}  |  "
            f"<b>对比组数:</b> {len(pairs)}"
        )
        dlg_layout.addWidget(info)

        # 方向选择
        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("视角方向:"))
        heading_combo = QComboBox()
        for p in pairs:
            heading_map = {0: "0° (前)", 90: "90° (右)", 180: "180° (后)", 270: "270° (左)"}
            h = p["heading"]
            heading_combo.addItem(heading_map.get(h, f"{h}°"), p)
        dir_row.addWidget(heading_combo)
        dir_row.addStretch()
        dlg_layout.addLayout(dir_row)

        # 对比图像区
        img_row = QHBoxLayout()

        old_layout = QVBoxLayout()
        old_title = QLabel("📅 较早")
        old_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        old_title.setStyleSheet("font-weight: bold; font-size: 14px;")
        old_layout.addWidget(old_title)
        old_img = QLabel("")
        old_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        old_img.setMinimumSize(400, 300)
        old_img.setStyleSheet("border: 2px solid #ccc; background: #f0f0f0;")
        old_layout.addWidget(old_img)
        old_date_lbl = QLabel("")
        old_date_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        old_layout.addWidget(old_date_lbl)
        img_row.addLayout(old_layout)

        vs_label = QLabel("VS")
        vs_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #e74c3c; padding: 0 10px;")
        vs_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_row.addWidget(vs_label)

        new_layout = QVBoxLayout()
        new_title = QLabel("📅 较新")
        new_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        new_title.setStyleSheet("font-weight: bold; font-size: 14px;")
        new_layout.addWidget(new_title)
        new_img = QLabel("")
        new_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        new_img.setMinimumSize(400, 300)
        new_img.setStyleSheet("border: 2px solid #ccc; background: #f0f0f0;")
        new_layout.addWidget(new_img)
        new_date_lbl = QLabel("")
        new_date_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        new_layout.addWidget(new_date_lbl)
        img_row.addLayout(new_layout)

        dlg_layout.addLayout(img_row)

        def update_compare():
            """更新对比图像。"""
            pair = heading_combo.currentData()
            if not pair or len(pair["images"]) < 2:
                return
            imgs = pair["images"]
            # 显示最早和最晚
            oldest = imgs[0]
            newest = imgs[-1]

            def load_pixmap(path, lbl, date_lbl, date_str):
                if os.path.exists(path):
                    pix = QPixmap(path)
                    if not pix.isNull():
                        scaled = pix.scaled(
                            400, 300,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        lbl.setPixmap(scaled)
                    else:
                        lbl.setText("图片损坏")
                else:
                    lbl.setText("文件不存在")
                date_lbl.setText(f"拍摄: {date_str}")

            load_pixmap(oldest["path"], old_img, old_date_lbl, oldest["date_str"])
            load_pixmap(newest["path"], new_img, new_date_lbl, newest["date_str"])

        heading_combo.currentIndexChanged.connect(update_compare)
        update_compare()

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dlg.accept)
        dlg_layout.addWidget(close_btn)

        dlg.exec()

    def _load_date(self):
        """从 streetview_status.txt 读取拍摄日期。"""
        if not self.current_dir:
            self.date_label.setText("")
            return
        status_path = Path(self.current_dir) / "streetview_status.txt"
        if not status_path.exists():
            self.date_label.setText("")
            return
        try:
            with open(status_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("拍摄时间:"):
                        self.date_label.setText(f"📅 {line.strip()}")
                        return
            self.date_label.setText("")
        except Exception:
            self.date_label.setText("")

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
