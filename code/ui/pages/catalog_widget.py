"""数据目录：编辑 dataset.json、检查目录与文件的一致性。"""
import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core import raster_catalog as RC
from ui.pages.extract_widget import _fix, _grid, _hint, _lab
from ui.widgets.info_icon import InfoIcon

_ROLE = Qt.ItemDataRole.UserRole
_COLOR = {"error": "#d93025", "warn": "#e37400", "info": "#5f6368"}
_LEVEL = {"error": "错误", "warn": "警告", "info": "提示"}


class _CheckWorker(QThread):
    progress = pyqtSignal(int, int)
    done = pyqtSignal(list)

    def __init__(self, root, deep):
        super().__init__()
        self.root, self.deep = root, deep
        self.stop_event = threading.Event()

    def run(self):
        self.done.emit(RC.check(self.root, self.deep, lambda i, n: self.progress.emit(i, n), self.stop_event))


def _categories():
    from plugins import gee_catalog as C
    local = [("admin", "行政区划"), ("rhum", "相对湿度"), ("sunshine", "日照时数"), ("gdp", "GDP"), ("forest", "森林与植被类型"), ("airq", "空气污染物"), ("uv", "紫外线")]
    return [(c.key, c.name) for c in C.CATEGORIES] + local + [("other", "其他")]


class CatalogWidget(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.series, self.cur, self.worker, self.issues = [], None, None, []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        # ① 目录位置
        g = QGroupBox("① 栅格数据目录")
        gl = _grid(g)
        self.root = QLineEdit(ctx.settings.value("paths/raster_root", ""))
        self.root.setPlaceholderText("选择存放栅格数据的根目录（也可在 设置 → 常规 中设置）")
        b = QPushButton("浏览…")
        b.clicked.connect(self._pick_root)
        rb = QPushButton("重新扫描")
        rb.clicked.connect(self.reload)
        gl.addWidget(_lab("根目录"), 0, 0)
        gl.addWidget(self.root, 0, 1)
        gl.addWidget(b, 0, 2)
        gl.addWidget(rb, 0, 3)
        gl.setColumnStretch(1, 1)
        lay.addWidget(g)

        # ② 数据序列：左列表 + 右表单
        g = QGroupBox("② 数据序列")
        v = QVBoxLayout(g)
        split = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(240)
        self.tree.currentItemChanged.connect(self._on_select)
        split.addWidget(self.tree)
        split.addWidget(self._build_form())
        split.setSizes([260, 600])
        v.addWidget(split, 1)
        bl = QHBoxLayout()
        for text, slot in (("新建数据序列", self._new), ("保存修改", self._save),
                           ("用实际范围更新起止", self._fill_range), ("移除登记", self._remove)):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            bl.addWidget(btn)
        bl.addStretch()
        v.addLayout(bl)
        lay.addWidget(g, 2)

        # ③ 检查
        g = QGroupBox("③ 一致性检查")
        gl = _grid(g)
        quick, deep = QPushButton("快速检查（文件名与时间范围）"), QPushButton("深度检查（读取文件头）")
        stop = QPushButton("停止")
        quick.clicked.connect(lambda: self._check(False))
        deep.clicked.connect(lambda: self._check(True))
        stop.clicked.connect(lambda: self.worker and self.worker.stop_event.set())
        self.filter = QComboBox()
        self.filter.addItems(["显示全部", "只看错误和警告", "只看错误"])
        self.filter.currentIndexChanged.connect(self._show_issues)
        self.bar = QProgressBar()
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["级别", "数据序列", "位置", "说明"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(150)
        self.table.cellDoubleClicked.connect(self._goto_series)
        self.summary = _hint("")
        gl.addWidget(quick, 0, 0)
        gl.addWidget(deep, 0, 1)
        gl.addWidget(stop, 0, 2)
        gl.addWidget(self.filter, 0, 3)
        gl.addWidget(self.bar, 1, 0, 1, 4)
        gl.addWidget(self.table, 2, 0, 1, 4)
        gl.addWidget(self.summary, 3, 0, 1, 4)
        gl.setColumnStretch(3, 1)
        lay.addWidget(g, 2)
        self.reload()

    # ---------- 表单 ----------
    def _build_form(self):
        w = QWidget()
        f = QFormLayout(w)
        f.setHorizontalSpacing(12)
        f.setVerticalSpacing(7)
        self.f_id = QLineEdit()
        self.f_id.setReadOnly(True)
        self.f_name, self.f_product, self.f_var, self.f_unit = (QLineEdit() for _ in range(4))
        self.f_cat = QComboBox()
        for k, n in _categories():
            self.f_cat.addItem(n, k)
        self.f_temp = QComboBox()
        for k, n in RC.TEMPORAL.items():
            self.f_temp.addItem(n, k)
        self.f_start, self.f_end = QLineEdit(), QLineEdit()
        self.f_start.setPlaceholderText("2000 或 2000-02")
        self.f_end.setPlaceholderText("2023 或 2023-12")
        self.f_gaps = QCheckBox("检查区间内缺期")
        self.f_gaps.setChecked(True)
        self.f_crs, self.f_res, self.f_nodata, self.f_dtype = (QLineEdit() for _ in range(4))
        self.f_crs.setPlaceholderText("如 EPSG:4326，留空不检查")
        self.f_nodata.setPlaceholderText("如 -9999；留空不检查；none = 不屏蔽任何值")
        self.f_dtype.setPlaceholderText("如 float32，留空不检查")
        self.f_kind = QLabel("栅格")
        self.f_near = QDoubleSpinBox()
        self.f_near.setRange(0, 200000)
        self.f_near.setSuffix(" m")
        self.f_attrs = QLineEdit()
        self.f_attrs.setPlaceholderText('矢量用，JSON，如 {"县": "name", "省代码": "gb[3:5]", "省": "gb[3:5]|cn_province"}')
        self.f_scale, self.f_offset = QDoubleSpinBox(), QDoubleSpinBox()
        for s in (self.f_scale, self.f_offset):
            s.setDecimals(6)
            s.setRange(-1e9, 1e9)
        self.f_scale.setValue(1.0)
        self.f_source, self.f_link, self.f_notes = QLineEdit(), QLineEdit(), QLineEdit()
        self.actual = _hint("")
        gw = QWidget()
        gh = QHBoxLayout(gw)
        gh.setContentsMargins(0, 0, 0, 0)
        gh.addWidget(self.f_gaps)
        gh.addWidget(InfoIcon("8 天、16 天等不规则间隔的数据请取消勾选，否则会被误报缺期"))
        gh.addStretch()
        self.f_cat_ = QCheckBox("分类数据（提取时取众数）")
        cw_ = QWidget()
        ch_ = QHBoxLayout(cw_)
        ch_.setContentsMargins(0, 0, 0, 0)
        ch_.addWidget(self.f_cat_)
        ch_.addWidget(InfoIcon("植被类型、土地利用这类类别编码的数据：缓冲区内和多期合成时取出现最多的类别，不取平均，也不做缩放。"))
        ch_.addStretch()
        self.f_multi = QCheckBox("允许网格变化")
        mw = QWidget()
        mh = QHBoxLayout(mw)
        mh.setContentsMargins(0, 0, 0, 0)
        mh.addWidget(self.f_multi)
        mh.addWidget(InfoIcon("同一序列里不同时期的文件分辨率或范围不同时勾选（如 2018 年前 10 km、之后 1 km）。\n不勾选时，网格不一致会被当作错误。"))
        mh.addStretch()
        for lab, wd in (("id（文件名前缀）", self.f_id), ("名称", self.f_name), ("类别", self.f_cat),
                        ("产品", self.f_product), ("变量", self.f_var), ("单位", self.f_unit),
                        ("时间尺度", self.f_temp), ("起始", self.f_start), ("结束", self.f_end),
                        ("", gw), ("", mw), ("", cw_), ("实际情况", self.actual), ("坐标系", self.f_crs),
                        ("分辨率（说明）", self.f_res), ("无效值", self.f_nodata), ("数据类型", self.f_dtype),
                        ("缩放系数", self.f_scale), ("偏移量", self.f_offset),
                        ("数据类型（栅格/矢量）", self.f_kind), ("就近匹配距离", self.f_near), ("属性映射", self.f_attrs),
                        ("来源", self.f_source), ("链接", self.f_link), ("备注", self.f_notes)):
            f.addRow(lab, wd)
        self.form_widget = w
        w.setEnabled(False)
        from PyQt6.QtWidgets import QScrollArea
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(w)
        return sa

    def _fill(self, s):
        self.f_id.setText(s.id)
        self.f_name.setText(s.name)
        self.f_cat.setCurrentIndex(max(0, self.f_cat.findData(s.category)))
        self.f_product.setText(s.product)
        self.f_var.setText(s.variable)
        self.f_unit.setText(s.unit)
        self.f_temp.setCurrentIndex(max(0, self.f_temp.findData(s.temporal)))
        self.f_start.setText(s.start)
        self.f_end.setText(s.end)
        self.f_gaps.setChecked(s.check_gaps)
        self.f_multi.setChecked(s.multi_grid)
        self.f_cat_.setChecked(s.categorical)
        self.f_kind.setText("矢量" if s.kind == "vector" else "栅格")
        self.f_near.setValue(s.nearest_m)
        import json as _json
        self.f_attrs.setText(_json.dumps(s.attributes, ensure_ascii=False) if s.attributes else "")
        self.f_crs.setText(s.crs)
        self.f_res.setText(s.resolution)
        self.f_nodata.setText(s.nodata)
        self.f_dtype.setText(s.dtype)
        self.f_scale.setValue(s.scale)
        self.f_offset.setValue(s.offset)
        self.f_source.setText(s.source)
        self.f_link.setText(s.link)
        self.f_notes.setText(s.notes)
        files = s.files()
        lo, hi = RC.actual_range(s)
        self.actual.setText(f"{sum(len(v) for v in files.values())} 个文件" +
                            (f"，实际范围 {RC.fmt_key(lo)} ~ {RC.fmt_key(hi)}" if lo else ""))

    def _collect(self):
        s = self.cur
        s.name, s.category = self.f_name.text().strip(), self.f_cat.currentData()
        s.product, s.variable, s.unit = self.f_product.text().strip(), self.f_var.text().strip(), self.f_unit.text().strip()
        s.temporal = self.f_temp.currentData()
        s.start, s.end, s.check_gaps = self.f_start.text().strip(), self.f_end.text().strip(), self.f_gaps.isChecked()
        s.multi_grid = self.f_multi.isChecked()
        s.categorical = self.f_cat_.isChecked()
        s.nearest_m = self.f_near.value()
        import json as _json
        txt = self.f_attrs.text().strip()
        try:
            s.attributes = _json.loads(txt) if txt else {}
        except ValueError:
            raise ValueError("「属性映射」不是有效的 JSON")
        s.crs, s.resolution, s.nodata = self.f_crs.text().strip(), self.f_res.text().strip(), self.f_nodata.text().strip()
        s.dtype, s.scale, s.offset = self.f_dtype.text().strip(), self.f_scale.value(), self.f_offset.value()
        s.source, s.link, s.notes = self.f_source.text().strip(), self.f_link.text().strip(), self.f_notes.text().strip()

    # ---------- 列表 ----------
    def _pick_root(self):
        p = QFileDialog.getExistingDirectory(self, "选择栅格数据根目录", self.root.text())
        if p:
            self.root.setText(p)
            self.ctx.settings.setValue("paths/raster_root", p)
            self.reload()

    def reload(self, select=None):
        self.tree.clear()
        self.cur = None
        self.form_widget.setEnabled(False)
        root = self.root.text().strip()
        if not root or not Path(root).is_dir():
            return
        self.series, errs = RC.load_all(root)
        names = dict(_categories())
        groups = {}
        for s in self.series:
            top = groups.get(s.category)
            if top is None:
                top = QTreeWidgetItem([names.get(s.category, s.category)])
                top.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.tree.addTopLevelItem(top)
                groups[s.category] = top
            it = QTreeWidgetItem([f"{s.id}（{RC.TEMPORAL.get(s.temporal, s.temporal)}）"])
            it.setData(0, _ROLE, s.id)
            top.addChild(it)
            if s.id == select:
                self.tree.setCurrentItem(it)
        self.tree.expandAll()
        if errs:
            self.summary.setText(f"{len(errs)} 个 dataset.json 无法读取，运行检查可看到详情")

    def _on_select(self, item, _prev=None):
        sid = item.data(0, _ROLE) if item else None
        self.cur = next((s for s in self.series if s.id == sid), None)
        self.form_widget.setEnabled(self.cur is not None)
        if self.cur:
            self._fill(self.cur)

    def _new(self):
        root = self.root.text().strip()
        if not root or not Path(root).is_dir():
            return QMessageBox.information(self, "提示", "请先选择栅格数据根目录")
        d = QDialog(self)
        d.setWindowTitle("新建数据序列")
        d.setMinimumWidth(420)
        f = QFormLayout(d)
        sid, cat, temp = QLineEdit(), QComboBox(), QComboBox()
        sid.setPlaceholderText("如 ndvi_mod_month（字母数字下划线）")
        for k, n in _categories():
            cat.addItem(n, k)
        for k, n in RC.TEMPORAL.items():
            temp.addItem(n, k)
        f.addRow("id", sid)
        f.addRow("类别", cat)
        f.addRow("时间尺度", temp)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        f.addRow(bb)
        if not d.exec():
            return
        i = sid.text().strip()
        if not i or any(s.id == i for s in self.series):
            return QMessageBox.warning(self, "提示", "id 为空或已存在")
        s = RC.Series(id=i, name=i, category=cat.currentData(), temporal=temp.currentData(),
                      folder=Path(root) / cat.currentData() / i)
        s.save()
        self.reload(select=i)

    def _save(self):
        if self.cur is None:
            return
        try:
            self._collect()
        except ValueError as e:
            return QMessageBox.warning(self, "无法保存", str(e))
        self.cur.save()
        self.summary.setText(f"已保存 {self.cur.folder / RC.MANIFEST}")
        self.reload(select=self.cur.id)

    def _fill_range(self):
        if self.cur is None:
            return
        lo, hi = RC.actual_range(self.cur)
        if lo:
            self.f_start.setText(RC.fmt_key(lo))
            self.f_end.setText(RC.fmt_key(hi))
            self.summary.setText("已填入实际范围，点「保存修改」后生效")

    def _remove(self):
        if self.cur is None:
            return
        if QMessageBox.question(self, "移除登记", f"只删除 {self.cur.id} 的 dataset.json，栅格文件不会删除。继续？") \
                == QMessageBox.StandardButton.Yes:
            (self.cur.folder / RC.MANIFEST).unlink(missing_ok=True)
            self.reload()

    # ---------- 检查 ----------
    def _check(self, deep):
        root = self.root.text().strip()
        if not root or not Path(root).is_dir():
            return QMessageBox.information(self, "提示", "请先选择栅格数据根目录")
        self.worker = _CheckWorker(root, deep)
        self.worker.progress.connect(lambda i, n: (self.bar.setMaximum(max(n, 1)), self.bar.setValue(i)))
        self.worker.done.connect(self._checked)
        self.summary.setText("检查中…")
        self.worker.start()

    def _checked(self, issues):
        self.issues = issues
        self._show_issues()

    def _show_issues(self, *_):
        mode = self.filter.currentIndex()
        rows = [i for i in self.issues if mode == 0 or (mode == 1 and i.level != "info") or (mode == 2 and i.level == "error")]
        root = self.root.text().strip()
        self.table.setRowCount(len(rows))
        for r, it in enumerate(rows):
            try:
                loc = str(Path(it.path).relative_to(root)) if it.path else ""
            except ValueError:
                loc = it.path
            for c, text in enumerate((_LEVEL[it.level], it.series, loc, it.message)):
                cell = QTableWidgetItem(text)
                cell.setForeground(QBrush(QColor(_COLOR[it.level])))
                self.table.setItem(r, c, cell)
        n = {lv: sum(i.level == lv for i in self.issues) for lv in _LEVEL}
        self.summary.setText("全部通过，没有发现问题" if not self.issues else
                             f"共 {n['error']} 个错误，{n['warn']} 个警告，{n['info']} 个提示")
        self._rows = rows

    def _goto_series(self, row, _col):
        sid = self._rows[row].series
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                if top.child(j).data(0, _ROLE) == sid:
                    self.tree.setCurrentItem(top.child(j))
                    return
