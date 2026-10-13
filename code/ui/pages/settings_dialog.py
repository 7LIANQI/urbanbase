"""选项对话框：常规（外观、路径）与 GEE 数据源（每类指标选一个全局数据源，右侧显示说明）。"""
from PyQt6.QtCore import Qt

from ui.widgets.info_icon import TitledLabel
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSplitter, QTabWidget,
    QTextBrowser, QVBoxLayout, QWidget,
)

_MODES = [("light", "浅色"), ("dark", "深色"), ("system", "跟随系统")]
_ROLE = Qt.ItemDataRole.UserRole


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None, page="general"):
        super().__init__(parent)
        self.setWindowTitle("选项")
        self.resize(980, 640)
        self.st = settings
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._general(), "常规")
        self.tabs.addTab(self._gee(), "GEE 数据源")
        self.tabs.setCurrentIndex(1 if page == "gee" else 0)
        lay.addWidget(self.tabs)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    # ---------- 常规 ----------
    def _general(self):
        w = QWidget()
        form = QFormLayout(w)
        self.theme = QComboBox()
        for k, label in _MODES:
            self.theme.addItem(label, k)
        cur = self.st.value("ui/theme", "light")
        self.theme.setCurrentIndex([k for k, _ in _MODES].index(cur) if cur in dict(_MODES) else 0)
        form.addRow(TitledLabel("界面主题", width=150), self.theme)

        from core import crs as CR
        self.crs = QComboBox()
        for k, name, _ in CR.CRS_OPTIONS:
            if k != "custom":
                self.crs.addItem(name, k)
        self.crs.setCurrentIndex(max(0, self.crs.findData(self.st.value("crs/default", "wgs84"))))
        self.crs.setMinimumWidth(320)
        form.addRow(TitledLabel("点位文件默认坐标系", "导入点位 CSV 时默认按此坐标系解释经纬度；每次提取时仍可单独更改。", 150), self.crs)

        self.gran = QComboBox()
        self.gran.addItem("年度", "year")
        self.gran.addItem("月度", "month")
        self.gran.setCurrentIndex(1 if self.st.value("extract/granularity", "year") == "month" else 0)
        self.gran.setMinimumWidth(320)
        form.addRow(TitledLabel("GEE 提取默认时间粒度", "年度：按年处理；月度：按月处理（只有年度数据的指标，同一年内各月取值相同）。每次提取时仍可单独更改。", 150), self.gran)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.out_dir = QLineEdit(self.st.value("paths/output_dir", ""))
        self.out_dir.setPlaceholderText("默认: 当前目录")
        btn = QPushButton("浏览…")
        btn.clicked.connect(self._browse)
        row.addWidget(self.out_dir, 1)
        row.addWidget(btn)
        holder = QWidget()
        holder.setLayout(row)
        form.addRow(TitledLabel("默认输出目录", width=150), holder)

        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        self.raster_root = QLineEdit(self.st.value("paths/raster_root", ""))
        self.raster_root.setPlaceholderText("存放栅格数据的根目录（含各数据序列文件夹）")
        b2 = QPushButton("浏览…")
        b2.clicked.connect(lambda: self._browse_to(self.raster_root, "选择栅格数据目录"))
        row2.addWidget(self.raster_root, 1)
        row2.addWidget(b2)
        h2 = QWidget()
        h2.setLayout(row2)
        form.addRow(TitledLabel("栅格数据目录", "存放各数据序列文件夹的根目录，「栅格数据目录」和「栅格转 COG」工具会用到。", 150), h2)
        return w

    def _browse_to(self, edit, title):
        d = QFileDialog.getExistingDirectory(self, title, edit.text())
        if d:
            edit.setText(d)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "选择默认输出目录", self.out_dir.text())
        if d:
            self.out_dir.setText(d)

    # ---------- GEE 数据源 ----------
    def _gee(self):
        from plugins import gee_catalog as C
        self.C = C
        self.sel = {c.key: C.selected_source(c.key, self.st).key for c in C.CATEGORIES}   # 暂存，确定后保存

        split = QSplitter()
        self.cat_list = QListWidget()
        self.cat_list.setMaximumWidth(260)
        theme = None
        for c in C.CATEGORIES:
            if c.theme != theme:
                theme = c.theme
                h = QListWidgetItem(theme)
                h.setFlags(Qt.ItemFlag.NoItemFlags)
                f = h.font()
                f.setBold(True)
                h.setFont(f)
                self.cat_list.addItem(h)
            it = QListWidgetItem("  " + c.name)
            it.setData(_ROLE, c.key)
            self.cat_list.addItem(it)

        mid = QWidget()
        ml = QVBoxLayout(mid)
        self.cat_desc = QTextBrowser()
        self.cat_desc.setMaximumHeight(56)
        self.src_list = QListWidget()
        ml.addWidget(self.cat_desc)
        ml.addWidget(self.src_list, 1)

        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(True)
        split.addWidget(self.cat_list)
        split.addWidget(mid)
        split.addWidget(self.detail)
        split.setSizes([230, 300, 430])

        self.cat_list.currentItemChanged.connect(self._on_cat)
        self.src_list.currentRowChanged.connect(self._on_src)
        for i in range(self.cat_list.count()):
            if self.cat_list.item(i).data(_ROLE):
                self.cat_list.setCurrentRow(i)
                break
        return split

    def _on_cat(self, item, _prev=None):
        key = item.data(_ROLE) if item else None
        if not key:
            return
        cat = self.C.CAT_BY_KEY[key]
        self._cat = cat
        self.cat_desc.setHtml(f"<b>{cat.name}</b><br><span style='color:#5f6368'>{cat.desc}</span>")
        self.src_list.blockSignals(True)
        self.src_list.clear()
        for s in cat.sources:
            it = QListWidgetItem(s.label)
            it.setData(_ROLE, s.key)
            self.src_list.addItem(it)
        self._mark()
        self.src_list.setCurrentRow([s.key for s in cat.sources].index(self.sel[key]))
        self.src_list.blockSignals(False)
        self._show(self.C.SOURCE_BY_KEY[self.sel[key]])

    def _on_src(self, row):
        if row < 0:
            return
        key = self.src_list.item(row).data(_ROLE)
        self.sel[self._cat.key] = key
        self._mark()
        self._show(self.C.SOURCE_BY_KEY[key])

    def _mark(self):
        for i in range(self.src_list.count()):
            it = self.src_list.item(i)
            s = self.C.SOURCE_BY_KEY[it.data(_ROLE)]
            it.setText(("✔ " if self.sel[self._cat.key] == s.key else "    ") + s.label + (" " + s.badge() if s.badge() else ""))

    def _show(self, src):
        self.detail.setHtml(src.html())

    # ---------- 保存 ----------
    def apply(self):
        self.st.setValue("ui/theme", self.theme.currentData())
        self.st.setValue("paths/output_dir", self.out_dir.text())
        self.st.setValue("crs/default", self.crs.currentData())
        self.st.setValue("extract/granularity", self.gran.currentData())
        self.st.setValue("paths/raster_root", self.raster_root.text())
        for cat_key, src_key in self.sel.items():
            self.st.setValue(f"gee_sources/{cat_key}", src_key)
