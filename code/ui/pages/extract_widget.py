"""点位指标提取：选点位 → 选数据源 → 设缓冲区与时间 → 运行。"""
import os
import tempfile
import threading

import pandas as pd
from PyQt6.QtCore import QDate, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox, QComboBox, QDateEdit, QFileDialog, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
    QRadioButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ui.widgets.info_icon import InfoIcon, TitledLabel

_COLS = {"id": ("id", "编号", "点位", "name", "序号"), "lon": ("lon", "lng", "longitude", "经度", "x"),
         "lat": ("lat", "latitude", "纬度", "y"), "date": ("date", "time", "日期", "时间")}


def guess_column(cols, key):
    """按列名猜：先找名称完全匹配的，再找名称里包含关键词的（如「 经度_wgs84」）。找不到返回 -1。"""
    names = [c.strip().lower() for c in cols]
    for i, c in enumerate(names):
        if c in _COLS[key]:
            return i
    for i, c in enumerate(names):
        if any(len(k) >= 2 and k in c for k in _COLS[key]):
            return i
    return -1


class _Worker(QThread):
    progress = pyqtSignal(int, int)
    log = pyqtSignal(str)
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def _write_gpkg(self):
        """同名的 .gpkg（点图层，WGS84），GIS 软件可直接打开。"""
        try:
            import geopandas as gpd
            df = pd.read_csv(self.out_csv, encoding="utf-8-sig")
            lon, lat = (("LON_WGS84", "LAT_WGS84") if "LON_WGS84" in df.columns else self.geo_cols)
            x, y = pd.to_numeric(df[lon], errors="coerce"), pd.to_numeric(df[lat], errors="coerce")
            ok = x.between(-180, 180) & y.between(-90, 90)       # 坐标缺失或超范围的行不进图层（否则图层范围无效）
            gdf = gpd.GeoDataFrame(df[ok], geometry=gpd.points_from_xy(x[ok], y[ok]), crs=4326)
            gdf.to_file(os.path.splitext(self.out_csv)[0] + ".gpkg", driver="GPKG")
        except Exception as e:                           # 失败不影响 CSV
            self.log.emit(f"⚠️ GPKG 生成失败: {e}")

    def _report(self, gee_info, diag):
        try:
            _write_report(self, gee_info, diag)
        except Exception as e:                      # 报告失败不影响提取结果
            self.log.emit(f"⚠️ 采集报告生成失败: {e}")

    def __init__(self, gee_kw, local_kw, out_csv, append=False):
        super().__init__()
        self.gee_kw, self.local_kw, self.out_csv, self.append = gee_kw, local_kw, out_csv, append
        self.geo_cols = ("", "")
        self.stop_event = threading.Event()

    def _save(self, base, input_df):
        """写最终 CSV。追加模式：在已有的输出表后面接上本次的新列（同名列原位更新），其余列和行不动。"""
        new_cols = [c for c in base.columns if c not in input_df.columns]
        if self.append and os.path.exists(self.out_csv):
            old = pd.read_csv(self.out_csv, encoding="utf-8-sig")
            if len(old) != len(base):
                raise ValueError(f"已有的输出表有 {len(old)} 行，本次的点位有 {len(base)} 行，行数不同，无法追加。请取消「追加」或换一个输出文件。")
            same = [c for c in new_cols if c in old.columns]
            if same:
                self.log.emit(f"⚠️ 已有表里有 {len(same)} 个同名列（如 {same[0]}），用本次结果更新")
            for c in new_cols:
                old[c] = base[c].values
            base = old
            self.log.emit(f"↪ 追加到已有结果：新增/更新 {len(new_cols)} 列，现共 {len(base.columns)} 列")
        base.to_csv(self.out_csv, index=False, encoding="utf-8-sig")

    def run(self):
        import traceback
        try:
            prog = lambda d, t: self.progress.emit(d, t)
            gee_info, diag = {}, {}
            kw0 = self.gee_kw or self.local_kw
            base = None
            if self.gee_kw:
                self.log.emit("第 1 步：GEE 提取")
                out = gee_extract_run(self.gee_kw, self.log.emit, self.stop_event, prog, gee_info)
                if not out:
                    return self.failed.emit("未完成")
                base = pd.read_csv(out, encoding="utf-8-sig")
                if os.path.abspath(out) != os.path.abspath(self.out_csv):
                    os.remove(out)                       # 中间文件（GEE 结果）已读入
            if self.local_kw:
                from plugins import local_extract
                self.log.emit("本地栅格库提取" if not self.gee_kw else "第 2 步：本地栅格库提取")
                args = self.local_kw
                res, cols = local_extract.run(**args, log=self.log.emit, stop=self.stop_event, progress=prog, diag=diag)
                if self.stop_event.is_set():
                    return self.failed.emit("未完成")
                if base is None:
                    base = args["df"].copy()
                for c in cols:
                    base[c] = res[c].values
            self._save(base, kw0["df"])
            self.log.emit(f"✅ 已保存: {self.out_csv}")
            self._write_gpkg()
            self._report(gee_info, diag)
            self.finished_ok.emit(self.out_csv)
        except Exception:
            self.failed.emit(traceback.format_exc())


def _write_report(worker, gee_info, diag):
    import pandas as pd
    from core.report import write_report
    from plugins import gee_extract
    df = pd.read_csv(worker.out_csv, encoding="utf-8-sig")
    groups = {}
    if worker.gee_kw:
        kw = worker.gee_kw
        for d in kw["datasets"]:
            groups[d.label] = gee_extract.column_names([d], kw["mode"], kw["windows"], kw["periods"])
    from plugins import local_extract
    local = (worker.local_kw or {}).get("series") or []
    for x in local:
        groups[f"{x.name or x.id}（本地）"] = local_extract.series_columns(x, diag.get("cols") or [])
    import numpy as np
    parts = [d for d in (gee_info.get("diag"), diag or None) if d]
    merged = None
    if parts:                                   # GEE 与本地的诊断合并成一份（行都对齐到输入点）
        merged = {k: np.hstack([p[k] for p in parts]) for k in ("used", "expected", "reason", "sub", "gap")}
        merged["cols"] = sum([list(p["cols"]) for p in parts], [])
    from plugins import gee_catalog
    vdesc = {}
    for x in local:
        for c, e in (x.attributes.items() if x.kind == "vector" else []):
            vdesc[c] = f"{x.name or x.id} 的属性 {c}"
    ldesc = {c: f"{x.name}" + (f"（{x.unit}）" if x.unit else "") for x in local if x.kind != "vector" for c in local_extract.series_columns(x, diag.get("cols") or [])}
    kw = worker.gee_kw or worker.local_kw
    tl = {"median": "中值", "mean": "均值", "max": "最大值", "min": "最小值"}
    settings = {"时间粒度": {"year": "年度", "month": "月度"}[kw["gran"]],
                "时间范围": ("回溯窗口 " + "、".join(kw["windows"])) if kw["mode"] == "rel" else "时间段序列 " + "、".join(p[0] for p in kw["periods"]),
                "缓冲区": "不做缓冲区（取点所在像元）" if kw["buffer_m"] <= 0 else f"半径 {kw['buffer_m']:g} m",
                "时段内合成": tl[kw["temporal"]], "区内合成": tl[kw["spatial"]], "输入坐标系": f"{kw['crs']}" + (f" EPSG:{kw['epsg']}" if kw['crs'] not in ("wgs84", "cgcs2000", "gcj02", "bd09", "epsg3857") else ""),
                "缺期时用最近一期替代": "是（详见下一节）" if kw.get("fill", True) else "否"}
    if worker.gee_kw:
        settings["在线数据（GEE）"] = {d.label: f"{d.gee_id}；{ {'model': '模式数据（再分析）', 'blend': '插值融合'}.get(d.origin, '观测或遥感反演') }" for d in worker.gee_kw["datasets"]}
    if local:
        settings["本地数据"] = {(x.name or x.id): (f"{x.folder}；矢量，按点所在面取属性" if x.kind == "vector" else f"{x.folder}；缩放 {x.scale:g}，偏移 {x.offset:g}" + ("；分类数据取众数" if x.categorical else "")) for x in local}
    path = write_report(worker.out_csv, df, groups, merged, gee_info.get("bad"), local,
                        desc=lambda c: vdesc.get(c) or ldesc.get(c) or gee_catalog.describe(c), settings=settings, append=worker.append)
    worker.log.emit(f"📋 采集报告: {path}")


def gee_extract_run(kw, log, stop, progress, info=None):
    from plugins import gee_extract
    return gee_extract.run(**kw, log=log, stop=stop, progress=progress, info=info)


_LABEL_W = 78
_SPATIAL_HINT = {"mean": "把缓冲区内所有像元取平均，反映整体水平（最常用）",
                 "median": "取排序后居中的值，不受个别极端像元影响"}
_BUF_TIP = ("不做缓冲区：只取点所在的那个像元，最快、最省内存。\n做缓冲区：取圆形范围内所有像元，再合成一个值。\n"
            "缓冲半径小于数据半个像元时，自动改为取点所在像元。")
_BATCH_TIP = "点多时分批请求。超时就减小每批点数，被限流就减小并行数。\n已完成的批次会缓存，重新运行同样设置可断点续跑。"
_GRAN_HINT = {
    "year": "按「年」处理：当前 = 观测日所在年；前 N 年 = 之前的 N 个年份。每年先合成一景，再对窗口内各年合成。"
            "只有年度数据的指标直接取该年的值。",
    "month": "按「月」处理：当前 = 观测日所在月；前 N 年 = 之前的 12×N 个月，逐月合成后再汇总。"
             "只有年度数据的指标（如年度夜光、人口）每个月取所在年份的值，所以同一年内各月相同。计算量比年度大，长窗口较慢。"}
_TEMPORAL_HINT = {"median": "取各期排序后居中的值，不受云、雾等异常值影响（年合成最常用）",
                  "mean": "取各期平均值，反映平均水平，但会受异常值拉动",
                  "max": "取各期最大值（如植被指数的最盛时期）",
                  "min": "取各期最小值"}



def _badge(online):
    l = QLabel("在线" if online else "本地")
    l.setObjectName("badgeOnline" if online else "badgeLocal")
    l.setFixedWidth(40)
    l.setAlignment(Qt.AlignmentFlag.AlignCenter)
    l.setToolTip("数据来自 Google Earth Engine（需要联网和 GEE 账号）" if online else "数据来自本地栅格数据目录（不联网）")
    return l



def _lab(text, w=_LABEL_W, tip=""):
    return TitledLabel(text, tip, w)


def _hint(text=""):
    l = QLabel(text)
    l.setObjectName("pageDesc")
    l.setWordWrap(True)
    return l


def _fix(w, width):
    w.setFixedWidth(width)
    return w


def _grid(group):
    g = QGridLayout(group)
    g.setHorizontalSpacing(10)
    g.setVerticalSpacing(8)
    return g


class ExtractWidget(QWidget):
    def __init__(self, ctx):
        super().__init__()
        from plugins import gee_catalog as C
        from plugins import gee_extract as G
        from core import crs as CR
        self.G, self.C, self.CR, self.ctx = G, C, CR, ctx
        self.df = None
        self.worker = None
        self.checks = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        body = QWidget()
        lay = QVBoxLayout(body)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(body)
        root.addWidget(sa, 1)

        # ---- ① 点位文件 ----
        g = QGroupBox("① 点位文件")
        gl = _grid(g)
        self.path = QLineEdit()
        self.path.setReadOnly(True)
        self.path.setPlaceholderText("选择 CSV 文件")
        b = QPushButton("浏览…")
        b.clicked.connect(self._pick)
        gl.addWidget(_lab("文件"), 0, 0)
        gl.addWidget(self.path, 0, 1, 1, 4)
        gl.addWidget(b, 0, 5)

        self.crs = QComboBox()
        for k, name, _ in CR.CRS_OPTIONS:
            self.crs.addItem(name, k)
        dk = ctx.settings.value("crs/default", "wgs84")
        self.crs.setCurrentIndex(max(0, self.crs.findData(dk)))
        self.epsg = QSpinBox()
        self.epsg.setRange(1000, 999999)
        self.epsg.setValue(int(ctx.settings.value("crs/custom_epsg", 4326)))
        self.epsg.setPrefix("EPSG:")
        self.epsg.setFixedWidth(120)
        self.crs.currentIndexChanged.connect(self._sync)
        self.lab_crs = _lab("坐标系")
        gl.addWidget(self.lab_crs, 1, 0)
        gl.addWidget(_fix(self.crs, 330), 1, 1, 1, 3)
        gl.addWidget(self.epsg, 1, 4)

        self.c_id, self.c_lon, self.c_lat, self.c_date = (QComboBox() for _ in range(4))
        self.lbl_lon, self.lbl_lat = _lab("经度"), _lab("纬度", 78)
        for c in (self.c_id, self.c_lon, self.c_lat, self.c_date):
            c.setFixedWidth(170)
        gl.addWidget(_lab("编号列"), 2, 0)
        gl.addWidget(self.c_id, 2, 1)
        gl.addWidget(self.lbl_lon, 2, 2)
        gl.addWidget(self.c_lon, 2, 3)
        self.lbl_date = _lab("观测日期列")
        gl.addWidget(self.lbl_date, 3, 0)
        gl.addWidget(self.c_date, 3, 1)
        gl.addWidget(self.lbl_lat, 3, 2)
        gl.addWidget(self.c_lat, 3, 3)
        self.n_label = _hint("")
        gl.addWidget(self.n_label, 4, 1, 1, 5)
        gl.setColumnStretch(1, 0)
        gl.setColumnStretch(4, 1)
        lay.addWidget(g)

        # ---- ② 指标 ----
        g = QGroupBox("② 要提取的指标")
        v = QVBoxLayout(g)
        top = QHBoxLayout()
        top.addWidget(QLabel("在线数据库"))
        top.addWidget(InfoIcon("来自 Google Earth Engine（需要联网和 GEE 账号）。\n批量勾选：按住 Shift 点击复选框，会把「上一次点击的行」到「这一行」之间的所有行一次性勾选（或取消）。"))
        top.addStretch()
        for text, slot in (("全选", lambda: [c.setChecked(True) for c in self.checks.values()]),
                           ("清空", lambda: [c.setChecked(False) for c in self.checks.values()]),
                           ("数据源设置…", lambda: ctx.open_settings("gee"))):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            top.addWidget(btn)
        tw = QWidget()                                  # 与下面「本地栅格库」标题行用同一套样式
        tw.setLayout(top)
        tw.setStyleSheet("font-weight:600; color:#5f6368;")
        v.addWidget(tw)
        self.src_labels, self.src_icons = {}, {}
        theme = None
        rows = QGridLayout()
        rows.setHorizontalSpacing(10)
        rows.setVerticalSpacing(5)
        r = 0
        for cat in C.CATEGORIES:
            if cat.theme != theme:
                theme = cat.theme
                hh = QHBoxLayout()
                hh.setContentsMargins(0, 6, 0, 0)
                h = QLabel(theme)
                h.setStyleSheet("font-weight:600; color:#5f6368;")
                hh.addWidget(h)
                hh.addStretch()
                hw = QWidget()
                hw.setLayout(hh)
                rows.addWidget(hw, r, 0, 1, 4)
                r += 1
            cb = QCheckBox(cat.name)
            cb.clicked.connect(lambda _=False, c=cb: self._row_clicked(c))
            self.checks[cat.key] = cb
            lab = _hint()
            lab.setWordWrap(False)
            ic = InfoIcon("")
            self.src_labels[cat.key], self.src_icons[cat.key] = lab, ic
            rows.addWidget(_badge(True), r, 0)
            rows.addWidget(cb, r, 1)
            rows.addWidget(lab, r, 2)
            rows.addWidget(ic, r, 3)
            r += 1
        rows.setColumnMinimumWidth(1, 270)
        rows.setColumnStretch(2, 1)
        v.addLayout(rows)
        hl_ = QHBoxLayout()
        hl_.addWidget(QLabel("本地栅格库"))
        hl_.addWidget(InfoIcon("来自「栅格数据目录」里的各数据序列（COG）。与上面的 GEE 指标可以同时勾选，结果合并在同一个 CSV 里。\n"
                               "数值 = 原始值 × 缩放系数 + 偏移量（在目录工具里编辑每个序列的这两项）；逐日序列请先转成月序列。"))
        hl_.addStretch()
        for text_, on_ in (("全选", True), ("清空", False)):
            b_ = QPushButton(text_)
            b_.clicked.connect(lambda _=False, o=on_: [x[0].setChecked(o) for x in self.local_checks.values()])
            hl_.addWidget(b_)
        rb_ = QPushButton("刷新")
        rb_.clicked.connect(self.refresh_local)
        hl_.addWidget(rb_)
        hw_ = QWidget()
        hw_.setLayout(hl_)
        hw_.setStyleSheet("font-weight:600; color:#5f6368;")
        v.addWidget(hw_)
        self.local_grid = QGridLayout()
        self.local_grid.setHorizontalSpacing(10)
        self.local_grid.setVerticalSpacing(5)
        self.local_grid.setColumnMinimumWidth(1, 270)
        self.local_grid.setColumnStretch(2, 1)
        v.addLayout(self.local_grid)
        self.local_checks = {}
        self.refresh_sources()
        self.refresh_local()
        lay.addWidget(g)

        # ---- ③ 空间范围 ----
        g = QGroupBox("③ 空间范围")
        gl = _grid(g)
        self.buf = QComboBox()
        self.buf.addItems(["不做缓冲区（取点所在像元）", "500 m 缓冲区", "1000 m 缓冲区", "自定义半径"])
        self.buf.setCurrentIndex(2)
        self.buf_m = QSpinBox()
        self.buf_m.setRange(1, 50000)
        self.buf_m.setValue(1500)
        self.buf_m.setSuffix(" m")
        self.buf_m.setFixedWidth(100)
        self.buf.currentIndexChanged.connect(self._sync)
        self.lab_buf = _lab("缓冲区", tip=_BUF_TIP)
        gl.addWidget(self.lab_buf, 0, 0)
        gl.addWidget(_fix(self.buf, 230), 0, 1)
        gl.addWidget(self.buf_m, 0, 2)
        self.spatial = QComboBox()
        self.spatial.addItems(list(G.SPATIAL))
        self.spatial.currentIndexChanged.connect(self._sync)
        self.lab_sp = _lab("区内合成")
        gl.addWidget(self.lab_sp, 1, 0)
        gl.addWidget(_fix(self.spatial, 230), 1, 1)
        gl.setColumnStretch(3, 1)
        lay.addWidget(g)

        # ---- ④ 时间范围 ----
        g = QGroupBox("④ 时间范围")
        v = QVBoxLayout(g)
        v.setSpacing(8)
        gg = QGridLayout()
        gg.setHorizontalSpacing(10)
        self.gran = QComboBox()
        self.gran.addItems(list(G.GRANULARITY))
        dg = ctx.settings.value("extract/granularity", "year")
        self.gran.setCurrentIndex(0 if dg != "month" else 1)
        self.gran.currentIndexChanged.connect(self._sync)
        self.lab_gran = _lab("时间粒度")
        gg.addWidget(self.lab_gran, 0, 0)
        gg.addWidget(_fix(self.gran, 230), 0, 1)
        gg.setColumnStretch(2, 1)
        v.addLayout(gg)
        self.r_rel = QRadioButton("回溯窗口（相对每个点自己的观测日期）")
        self.r_seq = QRadioButton("时间段序列（所有点使用同一组时间段）")
        self.r_rel.setChecked(True)
        v.addWidget(self.r_rel)
        self.win_checks = {}
        wg = QGridLayout()
        wg.setContentsMargins(24, 0, 0, 0)
        for i, k in enumerate(G.WINDOW_YEARS):
            cb = QCheckBox()
            cb.setChecked(k in ("y1", "y3"))
            self.win_checks[k] = cb
            wg.addWidget(cb, i // 3, i % 3)
        for c_ in range(3):
            wg.setColumnMinimumWidth(c_, 230)
        wg.setColumnStretch(3, 1)
        self.win_row = QWidget()
        self.win_row.setLayout(wg)
        v.addWidget(self.win_row)
        v.addWidget(self.r_seq)
        self.d0, self.d1 = QDateEdit(QDate(2020, 1, 1)), QDateEdit(QDate(2023, 12, 31))
        for d in (self.d0, self.d1):
            d.setCalendarPopup(True)
            d.setFixedWidth(120)
        sg = QHBoxLayout()
        sg.setContentsMargins(24, 0, 0, 0)
        sg.setSpacing(8)
        for w in (QLabel("从"), self.d0, QLabel("到"), self.d1):
            sg.addWidget(w)
        sg.addStretch()
        self.seq_row = QWidget()
        self.seq_row.setLayout(sg)
        v.addWidget(self.seq_row)
        tg = QGridLayout()
        tg.setHorizontalSpacing(10)
        self.temporal = QComboBox()
        self.temporal.addItems(list(G.TEMPORAL))
        self.temporal.currentIndexChanged.connect(self._sync)
        self.lab_tp = _lab("时段内合成")
        tg.addWidget(self.lab_tp, 0, 0)
        tg.addWidget(_fix(self.temporal, 230), 0, 1)
        tg.setColumnStretch(2, 1)
        v.addSpacing(4)
        v.addLayout(tg)
        fr = QHBoxLayout()
        self.fill = QCheckBox("缺期时用最近一期数据替代")
        self.fill.setChecked(True)
        fr.addWidget(self.fill)
        fr.addWidget(InfoIcon("窗口内有数据的年/月照常平均，缺的不参与；只有整个窗口都没有数据时，才改用离窗口最近的一期"
                              "（前后等距取较早的），不做插值。用了几个点、偏差几年，都写在采集报告里。\n"
                              "关闭后，缺期的点留空。GEE 数据只在窗口前后各 2 年内找最近一期；本地数据不设上限。"))
        fr.addStretch()
        v.addLayout(fr)
        lay.addWidget(g)
        self.r_rel.toggled.connect(self._sync)

        # ---- ⑤ 输出与运行 ----
        g = QGroupBox("⑤ 输出与运行")
        gl = _grid(g)
        self.key = QLineEdit(ctx.settings.value("keys/gee_key", ""))
        self.key.setPlaceholderText("GEE 服务账号 JSON（留空使用本机默认凭证）")
        kb = QPushButton("浏览…")
        kb.clicked.connect(self._pick_key)
        gl.addWidget(_lab("GEE 密钥"), 0, 0)
        gl.addWidget(self.key, 0, 1, 1, 4)
        gl.addWidget(kb, 0, 5)
        self.out = QLineEdit()
        self.out.setPlaceholderText("结果 CSV 保存位置")
        ob = QPushButton("浏览…")
        ob.clicked.connect(self._pick_out)
        gl.addWidget(_lab("输出 CSV"), 1, 0)
        gl.addWidget(self.out, 1, 1, 1, 4)
        gl.addWidget(ob, 1, 5)
        self.batch = QSpinBox()
        self.batch.setRange(10, 1000)
        self.batch.setValue(50)
        self.batch.setSuffix(" 个点")
        self.workers = QSpinBox()
        self.workers.setRange(1, 8)
        self.workers.setValue(3)
        for sb_ in (self.batch, self.workers):
            sb_.setFixedWidth(110)
        gl.addWidget(_lab("每批点数", tip=_BATCH_TIP), 2, 0)
        gl.addWidget(self.batch, 2, 1)
        gl.addWidget(_lab("并行数"), 2, 2)
        gl.addWidget(self.workers, 2, 3)
        self.append = QCheckBox("追加到已有的输出文件")
        self.append.setChecked(False)
        gl.addWidget(self.append, 3, 0, 1, 2)
        gl.addWidget(InfoIcon("输出文件已存在时，不覆盖：把本次提取的新列接在原有列后面，点位文件（.gpkg）和说明（采集报告）也一起合并，"
                              "报告里按「第 N 次提取」依次记录。\n点位的行数必须和已有输出一致；同名的列用本次结果更新。"), 3, 2)
        self.add_map = QCheckBox("完成后把结果作为点图层加载到地图")
        self.add_map.setChecked(True)
        gl.addWidget(self.add_map, 4, 0, 1, 5)
        gl.setColumnStretch(4, 1)
        lay.addWidget(g)
        lay.addStretch()

        # ---- 底部 ----
        self.bar = QProgressBar()
        self.status = _hint("")
        root.addWidget(self.bar)
        root.addWidget(self.status)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        self.run_btn = QPushButton("开始提取")
        self.run_btn.setProperty("primary", True)
        self.run_btn.clicked.connect(self._run)
        self.tool_footer = {"right": [self.stop_btn, self.run_btn]}      # 由工具窗口移入统一底栏
        self._sync()

    def refresh_sources(self):
        if hasattr(self, "local_grid"):
            self.refresh_local()
        """按全局设置刷新每个指标当前使用的数据源（设置对话框关闭后调用）。"""
        for cat in self.C.CATEGORIES:
            src = self.C.selected_source(cat.key, self.ctx.settings)
            badge = f" <b style='color:#d93025'>{src.badge()}</b>" if src.badge() else ""
            self.src_labels[cat.key].setText(f"· {src.label}{badge}")
            self.src_icons[cat.key].setText(src.text() + "\n\n在 设置 → GEE 数据源 中可更换。")

    def refresh_local(self):
        """按「栅格数据目录」重新列出本地数据序列（跳过逐日序列和只有 NetCDF 的序列）。"""
        from core import raster_catalog as RC
        while self.local_grid.count():
            w = self.local_grid.takeAt(0).widget()
            if w is not None:
                w.setParent(None)          # 立刻摘下，避免新旧控件叠在一起
                w.deleteLater()
        self.local_checks = {}
        root = self.ctx.settings.value("paths/raster_root", "")
        if not root or not os.path.isdir(root):
            self.local_grid.addWidget(_hint("尚未设置栅格数据目录（设置 → 选项 → 常规）"), 0, 0, 1, 4)
            return
        series, _ = RC.load_all(root)
        r = 0
        for ser in sorted(series, key=lambda x: (x.category, x.id)):
            is_vec = ser.kind == "vector"
            if not is_vec and (ser.temporal == "day" or not any(f.suffix.lower() in (".tif", ".tiff") for ps in ser.files().values() for f in ps)):
                continue
            cb = QCheckBox(ser.name or ser.id)
            cb.clicked.connect(lambda _=False, c=cb: self._row_clicked(c))
            kind = "矢量" if is_vec else RC.TEMPORAL.get(ser.temporal, ser.temporal)
            lab = _hint(f"· {ser.id} · {kind}" + (f" · {ser.start}–{ser.end}" if ser.start and not is_vec else ""))
            lab.setWordWrap(False)
            tip = InfoIcon(f"{ser.name}\n序列 id: {ser.id}\n" +
                           (f"输出列: {', '.join(ser.attributes)}；不在任何面内时取 {ser.nearest_m:g} m 内最近的面\n" if is_vec else
                            f"缩放系数 {ser.scale}、偏移量 {ser.offset}") +
                           ("\n分类数据：取众数" if ser.categorical else "") + (f"\n{ser.notes}" if ser.notes else ""))
            self.local_checks[ser.id] = (cb, ser)
            self.local_grid.addWidget(_badge(False), r, 0)
            self.local_grid.addWidget(cb, r, 1)
            self.local_grid.addWidget(lab, r, 2)
            self.local_grid.addWidget(tip, r, 3)
            r += 1
        if not r:
            self.local_grid.addWidget(_hint("栅格数据目录里没有可用的数据序列"), 0, 0, 1, 4)

    def _all_checks(self):
        return list(self.checks.values()) + [c for c, _ in self.local_checks.values()]

    def _row_clicked(self, cb):
        """Shift+点击：把上一次点击的行到这一行之间的所有行统一成这一行的状态。"""
        order = self._all_checks()
        last = getattr(self, "_last_click", None)
        if (QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier) and last in order and cb in order:
            i, j = order.index(cb), order.index(last)
            for x in order[min(i, j):max(i, j) + 1]:
                x.setChecked(cb.isChecked())
        self._last_click = cb

    def selected_local(self):
        return [ser for cb, ser in self.local_checks.values() if cb.isChecked()]

    def selected_sources(self):
        return [self.C.selected_source(k, self.ctx.settings) for k, c in self.checks.items() if c.isChecked()]

    # ---------- 交互 ----------
    def _sync(self, *_):
        G = self.G
        rel = self.r_rel.isChecked()
        self.win_row.setEnabled(rel)
        self.seq_row.setEnabled(not rel)
        self.c_date.setEnabled(rel)
        self.lbl_date.setEnabled(rel)
        has_buf = self.buf.currentIndex() != 0
        self.buf_m.setVisible(self.buf.currentIndex() == 3)
        self.spatial.setEnabled(has_buf)
        self.lab_sp.setTip(_SPATIAL_HINT[G.SPATIAL[self.spatial.currentText()]] if has_buf
                           else "不做缓冲区时只有一个像元，无需合成")
        self.lab_tp.setTip(_TEMPORAL_HINT[G.TEMPORAL[self.temporal.currentText()]])
        gran = G.GRANULARITY[self.gran.currentText()]
        for k, cb in self.win_checks.items():
            cb.setText(G.window_label(k, gran))
        self.lab_gran.setTip(_GRAN_HINT[gran] + ("\n时间段序列模式下，每个时间段就是 1 个" + ("月" if gran == "month" else "年") + "。"))
        key = self.crs.currentData()
        self.epsg.setVisible(key == "custom")
        self.lab_crs.setTip(self.CR.HINTS[key])
        proj = key in ("epsg3857", "custom")
        self.lbl_lon.setText("X 列" if proj else "经度列")
        self.lbl_lat.setText("Y 列" if proj else "纬度列")

    def _pick(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择点位 CSV", self.ctx.settings.value("paths/last", ""),
                                           "CSV (*.csv);;所有文件 (*)")
        if not p:
            return
        try:
            df = pd.read_csv(p, encoding="utf-8-sig", dtype=str)
        except Exception:
            df = pd.read_csv(p, encoding="gbk", dtype=str)
        self.df, cols = df, list(df.columns)
        self.path.setText(p)
        if not self.out.text():
            self.out.setText(os.path.splitext(p)[0] + "_extract.csv")
        for box, key in ((self.c_id, "id"), (self.c_lon, "lon"), (self.c_lat, "lat"), (self.c_date, "date")):
            box.clear()
            box.addItems(cols)
            i = guess_column(cols, key)
            if i >= 0:
                box.setCurrentIndex(i)
        self.n_label.setText(f"{len(df)} 个点，{len(cols)} 列")

    def _pick_key(self):
        p, _ = QFileDialog.getOpenFileName(self, "GEE 服务账号 JSON", "", "JSON (*.json)")
        if p:
            self.key.setText(p)

    def _pick_out(self):
        p, _ = QFileDialog.getSaveFileName(self, "输出 CSV", self.out.text() or "extract.csv", "CSV (*.csv)")
        if p:
            self.out.setText(p)

    def _stop(self):
        if self.worker:
            self.worker.stop_event.set()
            self.status.setText("正在停止（等待当前批次结束）…")

    def _run(self):
        G = self.G
        from plugins import local_extract as LE
        if self.df is None:
            return QMessageBox.information(self, "提示", "请先选择点位文件")
        ds = self.selected_sources()
        loc = self.selected_local()
        if not ds and not loc:
            return QMessageBox.information(self, "提示", "请至少勾选一个指标或本地数据序列")
        lon_c, lat_c = self.c_lon.currentText(), self.c_lat.currentText()
        if lon_c == lat_c:
            return QMessageBox.warning(self, "提示", f"经度列和纬度列选成了同一列（{lon_c}），请在「① 点位」里重新选择。")
        for name, col, lim in (("经度", lon_c, 180), ("纬度", lat_c, 90)):
            v = pd.to_numeric(self.df[col], errors="coerce")
            bad = float(((v.abs() > lim) | v.isna()).mean())
            if bad > 0.2:
                return QMessageBox.warning(self, "提示", f"「{col}」作为{name}列不对：{bad:.0%} 的值不是有效的{name}（空值或超出 ±{lim}）。\n请在「① 点位」里重新选择{name}列。")
        rel = self.r_rel.isChecked()
        windows = [k for k, c in self.win_checks.items() if c.isChecked()]
        gran = G.GRANULARITY[self.gran.currentText()]
        periods = [] if rel else G.make_periods(self.d0.date().toString("yyyy-MM-dd"),
                                               self.d1.date().toString("yyyy-MM-dd"), "MS" if gran == "month" else "YS")
        only_static = all(d.mode == "static" for d in ds) and all(x.temporal == "static" for x in loc)
        if (rel and not windows and not only_static) or (not rel and not periods):
            return QMessageBox.information(self, "提示", "请选择时间窗口或设置有效的时间段")
        if not self.out.text():
            return QMessageBox.information(self, "提示", "请设置输出 CSV 路径")
        buffer_m = (0, 500, 1000, self.buf_m.value())[self.buf.currentIndex()]
        mode = "rel" if rel else "seq"
        ncols = len(G.column_names(ds, mode, windows, periods)) + len(LE.column_names(loc, mode, windows, periods))
        self.ctx.settings.setValue("keys/gee_key", self.key.text())
        self.ctx.settings.setValue("crs/custom_epsg", self.epsg.value())
        self.ctx.settings.setValue("extract/granularity", gran)
        common = dict(df=self.df, lon_col=self.c_lon.currentText(), lat_col=self.c_lat.currentText(),
                      date_col=self.c_date.currentText(), buffer_m=buffer_m, mode=mode, windows=windows, periods=periods,
                      temporal=G.TEMPORAL[self.temporal.currentText()], spatial=G.SPATIAL[self.spatial.currentText()],
                      crs=self.crs.currentData(), epsg=self.epsg.value(), gran=gran, fill=self.fill.isChecked())
        # GEE 需要的输出路径：只有 GEE 时直接写最终文件；两者都选时先写中间文件再由本地结果补列
        gee_out = self.out.text() if not (loc or self.append.isChecked()) else os.path.join(tempfile.gettempdir(), f"urbansense_gee_{os.getpid()}.csv")
        gee_kw = dict(common, datasets=ds, out_csv=gee_out, key=self.key.text() or None,
                      batch=self.batch.value(), workers=self.workers.value()) if ds else None
        local_kw = dict(common, series=loc, workers=4) if loc else None
        self.worker = _Worker(gee_kw, local_kw, self.out.text(), self.append.isChecked())
        self.worker.geo_cols = (self.c_lon.currentText(), self.c_lat.currentText())
        self.worker.log.connect(self.ctx.logbus.add)
        self.worker.progress.connect(lambda d, t: (self.bar.setMaximum(t), self.bar.setValue(d),
                                                   self.status.setText(f"已完成 {d}/{t}")))
        self.worker.finished_ok.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.bar.setValue(0)
        self.status.setText(f"开始：{len(self.df)} 个点 × {ncols} 个输出列")
        names = [d.label for d in ds] + [x.id for x in loc]
        self.ctx.logbus.add(f"🚀 点位指标提取开始：GEE {len(ds)} 个、本地 {len(loc)} 个（{'、'.join(names)}），缓冲 {buffer_m} m，输出 {ncols} 列")
        self.worker.start()

    def shutdown(self):
        """关闭程序时调用：通知停止，最多等 1.5 秒，仍在运行就强制结束后台线程。"""
        w = self.worker
        if w is not None and w.isRunning():
            w.stop_event.set()
            if not w.wait(1500):
                w.terminate()
                w.wait(500)

    def _finish_ui(self):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _done(self, path):
        self._finish_ui()
        self.status.setText(f"完成: {path}")
        gp = os.path.splitext(path)[0] + ".gpkg"
        if self.add_map.isChecked() and os.path.exists(gp):
            try:
                self.ctx.add_layer(gp)
            except Exception as e:
                self.ctx.logbus.add(f"⚠️ 结果已保存，但加载到地图失败: {e}")
        QMessageBox.information(self, "完成", f"提取完成\n\n结果：{path}\n点图层：{os.path.splitext(path)[0]}.gpkg\n说明：{os.path.splitext(path)[0]}_采集报告.md")

    def _failed(self, msg):
        self._finish_ui()
        self.status.setText("未完成，可重新运行续跑")
        if msg != "未完成":
            self.ctx.logbus.add(f"❌ 点位指标提取出错\n{msg}")
            QMessageBox.warning(self, "出错", msg.strip().splitlines()[-1])
