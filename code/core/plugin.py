"""工具插件接口与发现。

新增工具只需在 modules/（或 ~/.urbansense/plugins/）放一个 .py，
定义 Plugin 子类即可，工具箱、菜单会自动出现入口，点击后在独立工具窗口中打开。
"""
import importlib
import importlib.util
import pkgutil
from pathlib import Path

# 工具分类（顺序即工具箱/菜单顺序）
CATEGORIES = [
    ("download", "数据下载"),
    ("match", "数据匹配"),
    ("analysis", "数据分析"),
    ("manage", "数据管理"),
]
CATEGORY_IDS = [c[0] for c in CATEGORIES]

USER_PLUGIN_DIR = Path.home() / ".urbansense" / "plugins"


class Plugin:
    """工具插件基类。子类覆盖类属性并实现 create()。"""

    id = ""            # 全局唯一，如 "download.collect"
    title = ""         # 工具箱/菜单显示名
    category = ""      # CATEGORIES 中的 id
    order = 100        # 同分类内排序
    icon = "tool"      # core/icons.py 中的图标名
    description = ""   # 工具窗口顶部说明
    size = (900, 700)  # 工具窗口默认尺寸

    def create(self, ctx):
        """返回工具界面 QWidget。首次打开时才调用（懒加载）。"""
        raise NotImplementedError


class AppContext:
    """插件可用的共享资源（由主窗口提供）。"""

    def __init__(self, settings, logbus, shell):
        self.settings = settings
        self.logbus = logbus
        self._shell = shell
        self._legacy = None
        self._parts = None

    # ---- 与主窗口交互 ----
    def add_layer(self, path):
        """把文件作为图层加入地图（工具输出结果常用）。"""
        self._shell.add_layer(path)

    def selected_vector_path(self):
        return self._shell.layers.selected_path("vector")

    def open_settings(self, page="general"):
        self._shell.open_settings(page)

    def show_log(self):
        self._shell.log_dock.show()
        self._shell.log_dock.raise_()

    def run_tool(self, plugin_id):
        self._shell.run_tool(plugin_id)

    # ---- 旧版采集引擎（隐藏控制器，面板拆给各工具复用）----
    def legacy_part(self, name):
        """取旧版 MainWindow 里的面板：api/options/input/progress/step/time/auto/local/history。"""
        if self._parts is None:
            from ui.main_window import MainWindow
            from core.logbus import LogSink
            win = MainWindow()
            sink = LogSink(self.logbus, parent=win)
            win.log_box = sink                 # 旧版所有日志统一进总线
            sink.append("📋 日志文件: " + win.file_logger.log_path)
            tabs = win.main_tabs
            parts = {"time": tabs.widget(1), "auto": tabs.widget(2), "local": tabs.widget(3)}
            for i in (3, 2, 1):
                tabs.removeTab(i)
            for w in parts.values():
                w.setVisible(True)      # removeTab 会把页面隐藏
            parts.update(api=win.grp_api, options=win.grp_options, input=win.grp_input,
                         progress=win.progress, step=win.step_label)
            panel = win.history_panel
            panel.setMinimumWidth(0)
            panel.setMaximumWidth(16777215)
            parts["history"] = panel
            self._parts = parts
            self._legacy = win
        return self._parts[name]

    @property
    def legacy(self):
        """旧版控制器（尚未创建时为 None）。"""
        return self._legacy

    def legacy_engine(self):
        self.legacy_part("api")
        return self._legacy


def _plugins_in(mod):
    for obj in vars(mod).values():
        if (isinstance(obj, type) and issubclass(obj, Plugin)
                and obj is not Plugin and obj.__module__ == mod.__name__):
            yield obj()


def discover(log=print):
    """扫描 modules/ 与用户插件目录，返回排序后的插件实例列表。"""
    import modules
    found = []
    for m in pkgutil.iter_modules(modules.__path__):
        try:
            found.extend(_plugins_in(importlib.import_module(f"modules.{m.name}")))
        except Exception as e:  # 单个插件损坏不影响其他
            log(f"❌ 插件模块 {m.name} 加载失败: {e}")
    if USER_PLUGIN_DIR.is_dir():
        for f in sorted(USER_PLUGIN_DIR.glob("*.py")):
            try:
                spec = importlib.util.spec_from_file_location(f"user_plugin_{f.stem}", f)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                found.extend(_plugins_in(mod))
            except Exception as e:
                log(f"❌ 用户插件 {f.name} 加载失败: {e}")
    ids = set()
    result = []
    for p in found:
        if p.category not in CATEGORY_IDS or not p.id or p.id in ids:
            log(f"⚠️ 忽略无效/重复插件: {p.id or type(p).__name__}")
            continue
        ids.add(p.id)
        result.append(p)
    return sorted(result, key=lambda p: (CATEGORY_IDS.index(p.category), p.order))
