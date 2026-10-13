"""图层面板：显隐、拖拽排序、缩放至图层、符号化、属性表、移除。"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QMenu, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from core.icons import icon

_CMAPS = ["viridis", "plasma", "YlOrRd", "RdYlBu_r", "coolwarm", "Greens", "Blues", "gray"]
_ROLE = Qt.ItemDataRole.UserRole


class LayersPanel(QTreeWidget):
    def __init__(self, canvas, log):
        super().__init__()
        self.canvas, self.log = canvas, log
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemChanged.connect(self._on_check)
        self.itemDoubleClicked.connect(lambda it, _: self.symbology(it))
        self.model().rowsMoved.connect(self._sync_order)
        self._busy = False

    # ---------- 增删 ----------
    def add(self, path, style=None, visible=True):
        try:
            self.window().setCursor(Qt.CursorShape.WaitCursor)
            layer = self.canvas.add_layer(path, style=style)
        except Exception as e:
            self.log(f"❌ 加载图层失败 {path}: {e}")
            QMessageBox.warning(self, "加载失败", f"{path}\n\n{e}")
            return None
        finally:
            self.window().unsetCursor()
        it = QTreeWidgetItem([layer.name])
        it.setIcon(0, icon(layer.kind))
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        it.setCheckState(0, Qt.CheckState.Checked)
        it.setData(0, _ROLE, layer)
        it.setToolTip(0, layer.path)
        self._busy = True
        self.insertTopLevelItem(0, it)
        self._busy = False
        if not visible:
            it.setCheckState(0, Qt.CheckState.Unchecked)
        self.log(f"已加载图层: {layer.name}")
        return layer

    def remove(self, item):
        layer = item.data(0, _ROLE)
        self.canvas.remove_layer(layer)
        self.takeTopLevelItem(self.indexOfTopLevelItem(item))

    def selected_path(self, kind=None):
        it = self.currentItem()
        if it is None:
            return None
        layer = it.data(0, _ROLE)
        return layer.path if kind in (None, layer.kind) else None

    def layers(self):
        return [self.topLevelItem(i).data(0, _ROLE) for i in range(self.topLevelItemCount())]

    # ---------- 事件 ----------
    def _on_check(self, item, _col):
        if not self._busy:
            self.canvas.set_visible(item.data(0, _ROLE), item.checkState(0) == Qt.CheckState.Checked)

    def _sync_order(self, *_):
        self.canvas.set_order(self.layers())

    def _menu(self, pos):
        it = self.itemAt(pos)
        if it is None:
            return
        m = QMenu(self)
        m.addAction(icon("extent"), "缩放至图层").triggered.connect(
            lambda: self.canvas.zoom_to(it.data(0, _ROLE).bounds))
        m.addAction(icon("palette"), "符号化…").triggered.connect(lambda: self.symbology(it))
        if it.data(0, _ROLE).kind == "vector":
            m.addAction(icon("table"), "属性表…").triggered.connect(lambda: self.attr_table(it))
        m.addSeparator()
        m.addAction(icon("trash"), "移除图层").triggered.connect(lambda: self.remove(it))
        m.exec(self.viewport().mapToGlobal(pos))

    # ---------- 对话框 ----------
    def symbology(self, item):
        layer = item.data(0, _ROLE)
        dlg = SymbologyDialog(layer, self)
        if dlg.exec():
            layer.style = dlg.style()
            self.canvas.restyle(layer)

    def attr_table(self, item):
        layer = item.data(0, _ROLE)
        df = layer.data.drop(columns="geometry")
        n = min(len(df), 5000)
        d = QDialog(self)
        d.setWindowTitle(f"属性表 — {layer.name}（共 {len(df)} 行，显示前 {n} 行）")
        d.resize(900, 520)
        t = QTableWidget(n, len(df.columns))
        t.setHorizontalHeaderLabels([str(c) for c in df.columns])
        t.setAlternatingRowColors(True)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for r in range(n):
            for c in range(len(df.columns)):
                t.setItem(r, c, QTableWidgetItem(str(df.iat[r, c])))
        QVBoxLayout(d).addWidget(t)
        d.exec()


class SymbologyDialog(QDialog):
    def __init__(self, layer, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"符号化 — {layer.name}")
        self.setMinimumWidth(360)
        self.layer = layer
        st = layer.style
        self._color = st.get("color", "#1a73e8")
        form = QFormLayout(self)

        self.cmap = QComboBox()
        self.cmap.addItems(_CMAPS)
        self.cmap.setCurrentText(st.get("cmap", "viridis"))

        if layer.kind == "vector":
            self.mode = QComboBox()
            self.mode.addItems(["单一颜色", "按字段渐变"])
            self.mode.setCurrentIndex(1 if st.get("mode") == "graduated" else 0)
            self.color_btn = QPushButton(self._color)
            self.color_btn.clicked.connect(self._pick)
            self._paint()
            self.field = QComboBox()
            nums = [c for c in layer.data.columns
                    if c != "geometry" and layer.data[c].dtype.kind in "iuf"]
            self.field.addItems(nums)
            if st.get("field") in nums:
                self.field.setCurrentText(st["field"])
            form.addRow("渲染方式", self.mode)
            form.addRow("颜色", self.color_btn)
            form.addRow("字段", self.field)
        form.addRow("色带", self.cmap)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _pick(self):
        c = QColorDialog.getColor(QColor(self._color), self)
        if c.isValid():
            self._color = c.name()
            self._paint()

    def _paint(self):
        self.color_btn.setText(self._color)
        self.color_btn.setStyleSheet(f"border-left: 14px solid {self._color};")

    def style(self):
        st = {"cmap": self.cmap.currentText()}
        if self.layer.kind == "vector":
            graduated = self.mode.currentIndex() == 1 and self.field.count() > 0
            st.update(mode="graduated" if graduated else "single", color=self._color,
                      field=self.field.currentText())
        return st
