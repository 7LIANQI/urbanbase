"""主窗口：QGIS / ENVI 风格 —— 菜单 + 工具栏 + 图层面板 + 地图画布 + 工具箱 + 日志面板。"""
import json
import traceback
from pathlib import Path

from PyQt6.QtCore import QSettings, QSize, Qt
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import (
    QWidget, QApplication, QInputDialog, QMenu, QToolButton, QDockWidget, QFileDialog, QLabel, QMainWindow,
    QMessageBox, QToolBar,
)

from core.icons import icon
from core.logbus import LogBus
from core.plugin import CATEGORIES, AppContext, discover
from ui.basemap import BASEMAPS, DEFAULT
from ui.layers_panel import LayersPanel
from ui.map_canvas import RASTER_EXT, VECTOR_EXT, MapCanvas
from ui.pages.logs_page import LogsPage
from ui.pages.settings_dialog import SettingsDialog
from ui.toolbox import Toolbox
from ui.tool_dialog import ToolDialog

_DATA_FILTER = "地理数据 (*.shp *.geojson *.json *.gpkg *.tif *.tiff);;所有文件 (*)"


class ShellWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UrbanSense · 城市街道环境大数据平台")
        self.resize(1440, 900)
        self.setAcceptDrops(True)

        self.bus = LogBus()
        self.bus.install_hooks()
        self.settings = QSettings("MyCompany", "UrbanAnalysisApp")
        self.ctx = AppContext(self.settings, self.bus, self)
        self.plugins = discover(self.bus.add)
        self._dialogs = {}
        self._project_path = None

        self.canvas = MapCanvas()
        self.setCentralWidget(self.canvas)
        self.layers = LayersPanel(self.canvas, self.bus.add)
        self._build_docks()
        self._build_actions()
        self._build_basemap_menu()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()
        self.canvas.message.connect(self.bus.add)
        saved = self.settings.value("map/basemap", DEFAULT)
        self.set_basemap(saved if saved in BASEMAPS else (None if saved == "" else DEFAULT))
        self.bus.add("UrbanSense 已启动")
        schedule_enabled = str(self.settings.value("schedule/enabled", False)).strip().lower()
        if schedule_enabled in ("1", "true", "yes", "on"):
            try:
                self.ctx.legacy_engine()       # 创建隐藏控制器并恢复定时任务
            except Exception as e:
                self.bus.add(f"⚠️ 定时采集恢复失败：{e}")

    # ---------- 构建 ----------
    def _dock(self, title, widget, area, name):
        d = QDockWidget(title, self)
        d.setObjectName(name)
        d.setWidget(widget)
        self.addDockWidget(area, d)
        return d

    def _build_docks(self):
        self.layer_dock = self._dock("图层", self.layers, Qt.DockWidgetArea.LeftDockWidgetArea, "layers")
        self.tool_dock = self._dock("工具箱", Toolbox(self.plugins, self.run_tool),
                                    Qt.DockWidgetArea.RightDockWidgetArea, "toolbox")
        self.log_dock = self._dock("日志", LogsPage(self.bus), Qt.DockWidgetArea.BottomDockWidgetArea, "log")
        self.layer_dock.setMinimumWidth(240)
        self.tool_dock.setMinimumWidth(240)
        self.log_dock.setMinimumHeight(140)
        self.resizeDocks([self.layer_dock, self.tool_dock], [260, 280], Qt.Orientation.Horizontal)
        self.resizeDocks([self.log_dock], [190], Qt.Orientation.Vertical)

    def _act(self, text, icon_name, slot, tip=None, shortcut=None, checkable=False):
        a = QAction(icon(icon_name), text, self)
        a.setToolTip(tip or text)
        a.setCheckable(checkable)
        if shortcut:
            a.setShortcut(shortcut)
        a.triggered.connect(slot)
        return a

    def _build_actions(self):
        self.a_vec = self._act("添加矢量图层…", "vector", lambda: self._add_dialog("vector"), shortcut="Ctrl+Shift+V")
        self.a_ras = self._act("添加栅格图层…", "raster", lambda: self._add_dialog("raster"), shortcut="Ctrl+Shift+R")
        self.a_pan = self._act("平移", "pan", lambda: self.canvas.set_mode("pan"), "平移（拖动 / 滚轮缩放）", checkable=True)
        self.a_box = self._act("框选放大", "search", lambda: self.canvas.set_mode("zoom_box"), "拉框放大", checkable=True)
        self.a_zin = self._act("放大", "zoom_in", lambda: self.canvas.zoom_by(0.5), shortcut="Ctrl+=")
        self.a_zout = self._act("缩小", "zoom_out", lambda: self.canvas.zoom_by(2.0), shortcut="Ctrl+-")
        self.a_full = self._act("全图", "extent", self.canvas.zoom_full, "缩放至全部图层", shortcut="Ctrl+0")
        grp = QActionGroup(self)
        for a in (self.a_pan, self.a_box):
            grp.addAction(a)
        self.a_pan.setChecked(True)

    def _build_basemap_menu(self):
        self.basemap_menu = QMenu("底图", self)
        self.basemap_menu.setIcon(icon("layers"))
        grp = QActionGroup(self)
        self._base_actions = {}
        for key, label in [(None, "无底图")] + [(k, v[0]) for k, v in BASEMAPS.items()]:
            a = QAction(label, self, checkable=True)
            a.triggered.connect(lambda _=False, k=key: self.set_basemap(k))
            grp.addAction(a)
            self.basemap_menu.addAction(a)
            self._base_actions[key] = a
        self.basemap_menu.addSeparator()
        self.basemap_menu.addAction("自定义 XYZ 瓦片地址…", self._custom_basemap)

    def set_basemap(self, key):
        if key in self._base_actions:
            self._base_actions[key].setChecked(True)
        self.settings.setValue("map/basemap", key or "")
        self.canvas.set_basemap(key)

    def _custom_basemap(self):
        url, ok = QInputDialog.getText(
            self, "自定义底图", "XYZ 瓦片地址（含 {z} {x} {y}）：",
            text=self.settings.value("map/custom_url", "https://tile.openstreetmap.org/{z}/{x}/{y}.png"))
        if ok and all(t in url for t in ("{z}", "{x}", "{y}")):
            self.settings.setValue("map/custom_url", url)
            BASEMAPS["custom"] = ("自定义", url, 18, "自定义底图")
            self.set_basemap("custom")

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("文件")
        m.addAction("新建工程", "Ctrl+N", self._new_project)
        m.addAction("打开工程…", "Ctrl+O", self._open_project)
        m.addAction("保存工程", "Ctrl+S", self._save_project)
        m.addAction("工程另存为…", "Ctrl+Shift+S", lambda: self._save_project(True))
        m.addSeparator()
        m.addAction(self.a_vec)
        m.addAction(self.a_ras)
        m.addSeparator()
        m.addAction("退出", "Ctrl+Q", self.close)

        m = mb.addMenu("视图")
        for a in (self.a_pan, self.a_box, self.a_zin, self.a_zout, self.a_full):
            m.addAction(a)
        m.addSeparator()
        m.addMenu(self.basemap_menu)
        m.addSeparator()
        for d in (self.layer_dock, self.tool_dock, self.log_dock):
            m.addAction(d.toggleViewAction())

        for cat_id, name in CATEGORIES:
            items = [p for p in self.plugins if p.category == cat_id]
            if not items:
                continue
            m = mb.addMenu(name)
            for p in items:
                a = QAction(icon(p.icon), p.title, self)
                a.triggered.connect(lambda _=False, i=p.id: self.run_tool(i))
                m.addAction(a)

        m = mb.addMenu("设置")
        m.addAction("选项…", self._options)
        m = mb.addMenu("帮助")
        m.addAction("关于", lambda: QMessageBox.about(
            self, "关于 UrbanSense",
            "UrbanSense 城市街道环境大数据采集与分析平台\n工具以插件形式加载（modules/）。"))

    def _build_toolbar(self):
        tb = QToolBar("主工具栏")
        tb.setObjectName("main")
        tb.setMovable(False)
        tb.setIconSize(QSize(20, 20))
        self.addToolBar(tb)
        for a in (self.a_vec, self.a_ras):
            tb.addAction(a)
        tb.addSeparator()
        for a in (self.a_pan, self.a_box, self.a_zin, self.a_zout, self.a_full):
            tb.addAction(a)
        btn = QToolButton()
        btn.setIcon(icon("layers"))
        btn.setToolTip("底图")
        btn.setMenu(self.basemap_menu)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        tb.addWidget(btn)
        tb.addSeparator()
        for p in self.plugins:           # 常用工具快捷入口
            a = QAction(icon(p.icon), p.title, self)
            a.setToolTip(p.title)
            a.triggered.connect(lambda _=False, i=p.id: self.run_tool(i))
            tb.addAction(a)

    def _build_statusbar(self):
        sb = self.statusBar()
        self.coord_label = QLabel("经度 —   纬度 —")
        self.coord_label.setMinimumWidth(260)
        sb.addPermanentWidget(self.coord_label)
        sb.addPermanentWidget(QLabel("EPSG:4326"))
        self.canvas.coord_changed.connect(self.coord_label.setText)
        self.bus.record.connect(lambda ts, lv, msg: sb.showMessage(msg.splitlines()[0][:140], 6000))

    # ---------- 工具 ----------
    def run_tool(self, plugin_id):
        p = next((x for x in self.plugins if x.id == plugin_id), None)
        if p is None:
            return
        dlg = self._dialogs.get(plugin_id)
        if dlg is None:
            try:
                dlg = ToolDialog(p, p.create(self.ctx), self)
            except Exception:
                tb = traceback.format_exc()
                self.bus.add(f"❌ 工具「{p.title}」加载失败\n{tb}")
                QMessageBox.warning(self, "工具加载失败", f"{p.title}\n\n{tb.splitlines()[-1]}")
                return
            self._dialogs[plugin_id] = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    # ---------- 图层 ----------
    def add_layer(self, path, **kw):
        return self.layers.add(str(path), **kw)

    def _add_dialog(self, kind):
        exts = VECTOR_EXT if kind == "vector" else RASTER_EXT
        flt = ("矢量数据 (" if kind == "vector" else "栅格数据 (") + " ".join(f"*{e}" for e in sorted(exts)) + ")"
        paths, _ = QFileDialog.getOpenFileNames(self, "添加图层", self.settings.value("paths/last", ""), flt)
        for p in paths:
            self.settings.setValue("paths/last", str(Path(p).parent))
            self.add_layer(p)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            self.add_layer(u.toLocalFile())

    # ---------- 工程 ----------
    def _new_project(self):
        for it in [self.layers.topLevelItem(i) for i in range(self.layers.topLevelItemCount())]:
            self.layers.remove(it)
        self._project_path = None

    def _save_project(self, as_new=False):
        path = self._project_path
        if as_new or not path:
            path, _ = QFileDialog.getSaveFileName(self, "保存工程", "project.usproj", "UrbanSense 工程 (*.usproj)")
            if not path:
                return
        data = {"extent": self.canvas.extent(), "basemap": self.settings.value("map/basemap", ""),
                "layers": [{"path": l.path, "visible": l.visible, "style": l.style}
                           for l in self.layers.layers()]}
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        self._project_path = path
        self.bus.add(f"📁 工程已保存: {path}")

    def _open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开工程", "", "UrbanSense 工程 (*.usproj)")
        if not path:
            return
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self._new_project()
        for d in reversed(data["layers"]):      # 保存时自上而下，加载需自下而上
            if Path(d["path"]).exists():
                self.add_layer(d["path"], style=d["style"], visible=d["visible"])
            else:
                self.bus.add(f"⚠️ 图层文件缺失，已跳过: {d['path']}")
        if "basemap" in data and (data["basemap"] in BASEMAPS or not data["basemap"]):
            self.set_basemap(data["basemap"] or None)
        self.canvas.set_extent(data["extent"])
        self._project_path = path
        self.bus.add(f"📂 工程已打开: {path}")

    # ---------- 其他 ----------
    def _options(self):
        self.open_settings("general")

    def open_settings(self, page="general"):
        from core import theme
        dlg = SettingsDialog(self.settings, self, page)
        if dlg.exec():
            dlg.apply()
            theme.apply(QApplication.instance(), self.settings.value("ui/theme", "light"))
            eng = self.ctx.legacy
            if eng is not None:
                eng.output_dir_input.setText(self.settings.value("paths/output_dir", ""))
            ext = self._dialogs.get("download.extract")
            if ext is not None:        # 采集工具已打开时刷新其「当前数据源」显示
                for w in ext.findChildren(QWidget):
                    if hasattr(w, "refresh_sources"):
                        w.refresh_sources()

    def closeEvent(self, event):
        for dlg in self._dialogs.values():              # 先停掉各工具的后台任务，避免关闭时被长请求卡住
            for w in dlg.findChildren(QWidget):
                if hasattr(w, "shutdown"):
                    w.shutdown()
        eng = self.ctx.legacy
        if eng is not None:
            eng.closeEvent(event)
        else:
            event.accept()
