"""栅格转 COG（批量）：命名规则 + 坐标系检查（默认统一为 WGS84）+ 可选入库到数据序列。"""
import threading
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QGroupBox, QHeaderView,
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QRadioButton, QScrollArea,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core import cog
from core import raster_catalog as RC
from ui.pages.extract_widget import _fix, _grid, _hint, _lab


class _Worker(QThread):
    row = pyqtSignal(int, str)
    progress = pyqtSignal(int, int)
    done = pyqtSignal(int, int)

    def __init__(self, jobs, opts):
        super().__init__()
        self.jobs, self.opts = jobs, opts
        self.stop_event = threading.Event()

    def run(self):
        ok = bad = 0
        todo = [(i, j) for i, j in enumerate(self.jobs) if j["status"] == "ready"]
        for n, (i, j) in enumerate(todo):
            if self.stop_event.is_set():
                break
            try:
                if Path(j["dst"]).exists() and not self.opts["overwrite"]:
                    self.row.emit(i, "已存在，跳过")
                elif j["layer"] is None:
                    cog.to_cog(j["src"], j["dst"], **self.opts["cog"])
                    self.row.emit(i, "完成")
                else:
                    cog.nc_layer_to_cog(j["src"], j["var"], j["layer"], j["dst"],
                                        assume_crs=self.opts["assume_crs"], **self.opts["cog"])
                    self.row.emit(i, "完成")
                ok += 1
            except Exception as e:
                self.row.emit(i, f"失败：{str(e)[:90]}")
                bad += 1
            self.progress.emit(n + 1, len(todo))
        self.done.emit(ok, bad)


def _same_crs(a, b):
    from rasterio.crs import CRS
    try:
        return CRS.from_user_input(a) == CRS.from_user_input(b)
    except Exception:
        return False


class CogWidget(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.jobs, self.series, self.worker = [], [], None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        body = QWidget()
        lay = QVBoxLayout(body)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(body)
        root.addWidget(sa, 1)

        # ① 来源
        g = QGroupBox("① 来源")
        gl = _grid(g)
        self.src = QLineEdit()
        self.src.setPlaceholderText("选择包含 GeoTIFF 或 NetCDF 文件的文件夹")
        b = QPushButton("浏览…")
        b.clicked.connect(self._pick_src)
        self.recursive = QCheckBox("包含子文件夹")
        self.recursive.setChecked(True)
        gl.addWidget(_lab("文件夹"), 0, 0)
        gl.addWidget(self.src, 0, 1)
        gl.addWidget(b, 0, 2)
        gl.addWidget(self.recursive, 1, 1)
        self.ncvar = QLineEdit()
        self.ncvar.setPlaceholderText("自动（NetCDF 文件取第一个带经纬度的变量）")
        gl.addWidget(_lab("NC 变量", tip="只对 .nc 文件有效。一个文件里有多个变量时，在这里指定要转换的变量名。\n"
                                       "含多个时间层的文件会按层拆开，每层输出一个 COG。数值、数据类型、无效值保持原样，不做缩放。"), 2, 0)
        gl.addWidget(self.ncvar, 2, 1)
        gl.setColumnStretch(1, 1)
        lay.addWidget(g)

        # ② 目标
        g = QGroupBox("② 目标")
        gl = _grid(g)
        self.r_dir = QRadioButton("只转换（输出到文件夹）")
        self.r_cat = QRadioButton("入库（放进数据序列的文件夹）")
        self.r_dir.setChecked(True)
        self.out = QLineEdit()
        self.out.setPlaceholderText("输出文件夹")
        ob = QPushButton("浏览…")
        ob.clicked.connect(self._pick_out)
        self.ser = QComboBox()
        rb = QPushButton("刷新")
        rb.clicked.connect(self._load_series)
        self.ser_hint = _hint()
        gl.addWidget(self.r_dir, 0, 0, 1, 3)
        gl.addWidget(_lab("输出文件夹"), 1, 0)
        gl.addWidget(self.out, 1, 1)
        gl.addWidget(ob, 1, 2)
        gl.addWidget(self.r_cat, 2, 0, 1, 3)
        gl.addWidget(_lab("数据序列"), 3, 0)
        gl.addWidget(_fix(self.ser, 440), 3, 1)
        gl.addWidget(rb, 3, 2)
        gl.addWidget(self.ser_hint, 4, 1, 1, 2)
        gl.setColumnStretch(1, 1)
        lay.addWidget(g)

        # ③ 命名规则
        g = QGroupBox("③ 命名规则")
        gl = _grid(g)
        self.temporal = QComboBox()
        for k, n in RC.TEMPORAL.items():
            self.temporal.addItem(n, k)
        self.temporal.setCurrentIndex(self.temporal.findData("month"))
        self.dmode = QComboBox()
        self.dmode.addItems(list(cog.DATE_MODES))
        self.regex = QLineEdit()
        self.regex.setPlaceholderText(r"如 (?P<Y>\d{4})_(?P<M>\d{2})  （组名 Y、M、D，或 DOY）")
        self.tmpl = QComboBox()
        self.tmpl.setEditable(True)
        self.tmpl.addItems(cog.TEMPLATE_PRESETS)
        self.example = _hint()
        for r, (t, w, h) in enumerate([
                ("时间尺度", self.temporal, "入库时跟随数据序列；决定文件名里的日期取到年、月还是日"),
                ("日期来源", self.dmode, "从源文件名里读出日期"),
                ("命名模板", self.tmpl, "占位符：{name} 原文件名  {id} 数据序列 id  {date} 自动日期（YYYY / YYYYMM / YYYYMMDD）  {YYYY} {MM} {DD}")]):
            gl.addWidget(_lab(t, tip=h), r, 0)
            gl.addWidget(_fix(w, 360), r, 1)
        gl.addWidget(_lab("正则"), 3, 0)
        gl.addWidget(self.regex, 3, 1, 1, 2)
        gl.addWidget(_lab("示例"), 4, 0)
        gl.addWidget(self.example, 4, 1, 1, 2)
        gl.setColumnStretch(2, 1)
        lay.addWidget(g)

        # ④ 坐标系
        g = QGroupBox("④ 坐标系")
        gl = _grid(g)
        self.tcrs = QComboBox()
        self.tcrs.addItems(list(cog.TARGET_CRS))
        self.tepsg = QLineEdit()
        self.tepsg.setPlaceholderText("如 EPSG:32649")
        self.assign = QLineEdit()
        self.assign.setPlaceholderText("如 EPSG:4326（仅对没有坐标系的文件生效）")
        self.res = QLineEdit()
        self.res.setPlaceholderText("留空 = 自动（单位随目标坐标系：度或米）")
        for r, (t, w, h) in enumerate([
                ("目标坐标系", self.tcrs, "与目标不同的文件会被重投影（有重采样）；CGCS2000 与 WGS84 在米级内一致，只改标签不重采样"),
                ("", self.tepsg, ""),
                ("补坐标系", self.assign, "文件本身没有坐标系时，按这里指定的坐标系解释；不填则该文件不会被转换"),
                ("输出分辨率", self.res, "仅重投影时使用，一般留空")]):
            gl.addWidget(_lab(t, tip=h), r, 0)
            gl.addWidget(_fix(w, 360), r, 1)
        gl.setColumnStretch(2, 1)
        lay.addWidget(g)

        # ⑤ 转换选项
        g = QGroupBox("⑤ 转换选项")
        gl = _grid(g)
        self.compress = QComboBox()
        self.compress.addItems(list(cog.COMPRESS))
        self.block = QComboBox()
        self.block.addItems(["512", "256"])
        self.resamp = QComboBox()
        self.resamp.addItems(list(cog.RESAMPLING))
        self.nod = QLineEdit()
        self.nod.setPlaceholderText("如 -9999（仅对没有无效值的文件生效）")
        self.overwrite = QCheckBox("覆盖已存在的目标文件")
        for r, (t, w, h) in enumerate([
                ("压缩方式", self.compress, "DEFLATE 兼容性最好；ZSTD 更小更快，但需要较新的 GDAL"),
                ("分块大小", self.block, "512 适合大多数情况；256 适合经常读很小的窗口"),
                ("重采样", self.resamp, "同时用于缩略图和重投影。分类数据（土地覆盖等）必须用最近邻"),
                ("补无效值", self.nod, "整型栅格重投影时必须有无效值，用于填充边缘")]):
            gl.addWidget(_lab(t, tip=h), r, 0)
            gl.addWidget(_fix(w, 360), r, 1)
        gl.addWidget(self.overwrite, 4, 1, 1, 2)
        gl.setColumnStretch(2, 1)
        lay.addWidget(g)

        # ⑥ 文件清单
        g = QGroupBox("⑥ 文件清单")
        gl = _grid(g)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["源文件", "源坐标系", "目标文件", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(200)
        pb = QPushButton("生成清单")
        pb.clicked.connect(self._preview)
        self.summary = _hint("")
        gl.addWidget(self.table, 0, 0, 1, 2)
        gl.addWidget(pb, 1, 0)
        gl.addWidget(self.summary, 1, 1)
        gl.setColumnStretch(1, 1)
        lay.addWidget(g)
        lay.addStretch()

        self.bar = QProgressBar()
        root.addWidget(self.bar)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(lambda: self.worker and self.worker.stop_event.set())
        self.run_btn = QPushButton("开始转换")
        self.run_btn.setProperty("primary", True)
        self.run_btn.clicked.connect(self._run)
        self.tool_footer = {"right": [self.stop_btn, self.run_btn]}

        for w in (self.r_dir, self.ser, self.temporal, self.dmode, self.tcrs):
            sig = w.toggled if isinstance(w, QRadioButton) else w.currentIndexChanged
            sig.connect(self._sync)
        self.tmpl.currentTextChanged.connect(self._sync)
        self.regex.textChanged.connect(self._sync)
        self.src.textChanged.connect(self._sync)
        self._load_series()
        self._sync()

    def shutdown(self):
        w = self.worker
        if w is not None and w.isRunning():
            w.stop_event.set()
            if not w.wait(1500):
                w.terminate()
                w.wait(500)

    # ---------- 交互 ----------
    def _cur_series(self):
        return self.series[self.ser.currentIndex()] if self.r_cat.isChecked() and self.series and self.ser.currentIndex() >= 0 else None

    def _sync(self, *_):
        d = self.r_dir.isChecked()
        s = None if d else self._cur_series()
        self.out.setEnabled(d)
        self.ser.setEnabled(not d)
        self.temporal.setEnabled(d)
        self.tmpl.setEnabled(d)
        if not d and s is not None:
            self.temporal.blockSignals(True)
            self.temporal.setCurrentIndex(max(0, self.temporal.findData(s.temporal)))
            self.temporal.blockSignals(False)
            self.tmpl.blockSignals(True)
            self.tmpl.setEditText("{id}_{date}")
            self.tmpl.blockSignals(False)
        self.regex.setEnabled(cog.DATE_MODES[self.dmode.currentText()] == "regex")
        self.tepsg.setEnabled(cog.TARGET_CRS[self.tcrs.currentText()] == "custom")
        self.example.setText(self._example())

    def _target_crs(self):
        v = cog.TARGET_CRS[self.tcrs.currentText()]
        return self.tepsg.text().strip() if v == "custom" else v

    def _name_for(self, p, s, layer_date=None):
        """返回 ((目标文件名, 日期, 时间尺度), 错误说明)。layer_date 是 NetCDF 时间层的 (年,月,日)。"""
        temporal = s.temporal if s else self.temporal.currentData()
        tmpl = "{id}_{date}" if s else (self.tmpl.currentText().strip() or "{name}")
        d = None
        if temporal != "static":
            if layer_date is not None:
                d = layer_date[:{"year": 1, "month": 2, "day": 3}[temporal]]
            else:
                d = cog.find_date(p.name, temporal, cog.DATE_MODES[self.dmode.currentText()], self.regex.text())
            if d is None or any(x is None for x in d):
                return None, "无法识别日期"
        if s is None and "{id}" in tmpl:
            return None, "只转换模式不能用 {id}"
        try:
            name = cog.render_name(tmpl, p.name, s.id if s else "", d, temporal)
        except ValueError as e:
            return None, str(e)
        return (name, d, temporal), ""

    def _example(self):
        srcs = self._sources()
        if not srcs:
            return "选择来源文件夹后显示"
        d0 = None
        if srcs[0].suffix.lower() == ".nc":            # NetCDF：用第一个时间层的日期举例
            try:
                d0 = cog.nc_describe(srcs[0], self.ncvar.text().strip() or None)["dates"][0]
            except Exception:
                d0 = None
        info, err = self._name_for(srcs[0], self._cur_series(), d0)
        return f"{srcs[0].name}  →  {info[0]}" if info else f"{srcs[0].name}：{err}"

    def _pick_src(self):
        p = QFileDialog.getExistingDirectory(self, "选择来源文件夹", self.src.text())
        if p:
            self.src.setText(p)

    def _pick_out(self):
        p = QFileDialog.getExistingDirectory(self, "选择输出文件夹", self.out.text())
        if p:
            self.out.setText(p)

    def _load_series(self):
        root = self.ctx.settings.value("paths/raster_root", "")
        self.ser.clear()
        self.series = []
        if root and Path(root).is_dir():
            self.series, _ = RC.load_all(root)
            for s in self.series:
                self.ser.addItem(f"{s.id}  （{s.name or s.variable or '未命名'}，{RC.TEMPORAL.get(s.temporal, s.temporal)}）")
            self.ser_hint.setText("" if self.series else "数据目录里还没有数据序列，请先在「栅格数据目录」工具里新建")
        else:
            self.ser_hint.setText("尚未设置栅格数据目录：设置 → 选项 → 常规 → 栅格数据目录")

    def _sources(self):
        root = Path(self.src.text())
        if not root.is_dir():
            return []
        it = root.rglob("*") if self.recursive.isChecked() else root.glob("*")
        return sorted(p for p in it if p.suffix.lower() in RC.RASTER_EXT + (".nc",) and not p.name.startswith("._"))

    def _preview(self):
        s = self._cur_series()
        if self.r_cat.isChecked() and s is None:
            return QMessageBox.information(self, "提示", "没有可用的数据序列")
        if self.r_dir.isChecked() and not self.out.text():
            return QMessageBox.information(self, "提示", "请先选择输出文件夹")
        target, assign = self._target_crs(), self.assign.text().strip() or None
        var = self.ncvar.text().strip() or None
        jobs, seen, rows = [], {}, []
        for p in self._sources():
            entries = []                 # (图层序号 或 None, 显示名, 日期 或 None, 坐标系, 状态, 说明)
            if p.suffix.lower() == ".nc":
                try:
                    info = cog.nc_describe(p, var, assume_crs=assign or "EPSG:4326")
                    for i in range(info["n"]):
                        d = info["dates"][i]
                        label = p.name + (f" · 第 {i + 1} 层" if info["tdim"] else "")
                        entries.append((i, label, d, info["crs"], "ready", info["crs_note"], info["var"]))
                except Exception as e:
                    entries.append((0, p.name, None, None, f"无法读取：{str(e)[:50]}", "", None))
            else:
                try:
                    crs = cog.read_crs(p)
                    entries.append((None, p.name, None, crs, "ready", "", None))
                except Exception as e:
                    entries.append((None, p.name, None, None, f"无法打开：{str(e)[:50]}", "", None))
            for layer, label, d, crs, status, cnote, v in entries:
                crs_txt = "?" if status != "ready" else (crs.to_string() if crs else "无")
                if cnote and status == "ready" and "推定" in cnote:
                    crs_txt += "（推定）"
                dst_name, dst, status_note = "", Path(), ""
                if status == "ready":
                    info2, err = self._name_for(p, s, d if (layer is not None and d is not None) else None)
                    if info2 is None:
                        status = err
                    else:
                        name, dd, temporal = info2
                        dst_name = name
                        dst = (s.folder / (f"{dd[0]:04d}" if dd else "") / name) if s else Path(self.out.text()) / name
                        if str(dst) in seen:
                            status = f"目标重复（与 {seen[str(dst)]} 冲突）"
                        else:
                            seen[str(dst)] = label
                if status == "ready":
                    action, note = cog.crs_action(crs, target, assign)
                    if action == "missing":
                        status = "无坐标系：请在「补坐标系」中指定"
                    elif s is not None and s.crs and (target is None and not _same_crs(crs or assign, s.crs)
                                                      or target is not None and not _same_crs(target, s.crs)):
                        status = f"坐标系与数据序列声明的 {s.crs} 不一致，请调整目标坐标系"
                    else:
                        status_note = note
                jobs.append(dict(src=str(p), layer=layer, var=v, dst=str(dst), status=status))
                rows.append((label, crs_txt, dst_name if status == "ready" or status.startswith("目标") else "",
                             ("待转换：" + status_note) if status == "ready" else status))
        self.jobs = jobs
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for c, text in enumerate(r):
                self.table.setItem(i, c, QTableWidgetItem(text))
        n_ok = sum(j["status"] == "ready" for j in jobs)
        n_re = sum("重投影" in r[3] for r in rows)
        self.summary.setText(f"共 {len(jobs)} 个输出：{n_ok} 个可转换（其中 {n_re} 个需重投影），{len(jobs) - n_ok} 个有问题，不会转换")

    def _run(self):
        self._preview()
        if not any(j["status"] == "ready" for j in self.jobs):
            return QMessageBox.information(self, "提示", "没有可转换的文件，请看清单里的状态说明")
        nod = self.nod.text().strip()
        res = self.res.text().strip()
        try:
            opts = dict(overwrite=self.overwrite.isChecked(), assume_crs=self.assign.text().strip() or "EPSG:4326", cog=dict(
                compress=cog.COMPRESS[self.compress.currentText()], blocksize=int(self.block.currentText()),
                resampling=cog.RESAMPLING[self.resamp.currentText()], target_crs=self._target_crs(),
                assign_crs=self.assign.text().strip() or None,
                assign_nodata=float(nod) if nod else None, res=float(res) if res else None))
        except ValueError:
            return QMessageBox.warning(self, "提示", "无效值或输出分辨率不是数字")
        self.worker = _Worker(self.jobs, opts)
        self.worker.row.connect(lambda i, t: self.table.setItem(i, 3, QTableWidgetItem(t)))
        self.worker.progress.connect(lambda d, t: (self.bar.setMaximum(t), self.bar.setValue(d)))
        self.worker.done.connect(self._done)
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.bar.setValue(0)
        self.ctx.logbus.add(f"🚀 批量转 COG 开始：{sum(j['status'] == 'ready' for j in self.jobs)} 个输出")
        self.worker.start()

    def _done(self, ok, bad):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        msg = f"批量转 COG 结束：成功 {ok}，失败 {bad}"
        self.summary.setText(msg)
        self.ctx.logbus.add(("✅ " if not bad else "⚠️ ") + msg)
        if self.r_cat.isChecked() and ok:
            self.ctx.logbus.add("已入库，建议到「栅格数据目录」里点击检查，确认时间范围与缺期")
