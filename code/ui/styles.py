"""应用主题样式表（亮色/暗色模式）。

通过检测 Windows 系统主题自动切换，
也可手动调用 apply_theme() 覆盖。
"""
import sys

from PyQt6.QtCore import Qt


def _detect_system_dark() -> bool:
    """检测系统是否使用暗色主题。

    Windows: 查询注册表 Personalize 设置。
    macOS: 暂不支持，返回 False。
    Linux: 暂不支持，返回 False。
    """
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return value == 0
    except Exception:
        return False


# ==================== 暗色主题样式表 ====================

DARK_STYLESHEET = """
QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-size: 13px;
}

QGroupBox {
    border: 1px solid #45475a;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 16px;
    font-weight: bold;
    color: #89b4fa;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox, QDateEdit {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 8px;
    selection-background-color: #89b4fa;
    selection-color: #1e1e2e;
}

QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}

QComboBox QAbstractItemView {
    background-color: #313244;
    color: #cdd6f4;
    selection-background-color: #45475a;
}

QPushButton {
    background-color: #45475a;
    color: #cdd6f4;
    border: 1px solid #585b70;
    border-radius: 4px;
    padding: 6px 16px;
    min-height: 28px;
}

QPushButton:hover {
    background-color: #585b70;
    border-color: #89b4fa;
}

QPushButton:pressed {
    background-color: #313244;
}

QTableWidget {
    background-color: #313244;
    color: #cdd6f4;
    gridline-color: #45475a;
    border: 1px solid #45475a;
    border-radius: 4px;
}

QTableWidget::item:selected {
    background-color: #45475a;
    color: #cdd6f4;
}

QHeaderView::section {
    background-color: #1e1e2e;
    color: #89b4fa;
    padding: 6px;
    border: none;
    border-bottom: 2px solid #45475a;
    font-weight: bold;
}

QProgressBar {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 4px;
    text-align: center;
    color: #cdd6f4;
}

QProgressBar::chunk {
    background-color: #89b4fa;
    border-radius: 3px;
}

QTabWidget::pane {
    border: 1px solid #45475a;
    border-radius: 4px;
    background-color: #1e1e2e;
}

QTabBar::tab {
    background-color: #313244;
    color: #a6adc8;
    padding: 8px 16px;
    border: 1px solid #45475a;
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}

QTabBar::tab:selected {
    background-color: #1e1e2e;
    color: #89b4fa;
    font-weight: bold;
}

QScrollBar:vertical {
    background-color: #313244;
    width: 10px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background-color: #585b70;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}

QListWidget {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
}

QListWidget::item:selected {
    background-color: #45475a;
    color: #89b4fa;
}

QLabel {
    color: #cdd6f4;
}

QCheckBox {
    color: #cdd6f4;
    spacing: 6px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #585b70;
    border-radius: 3px;
    background-color: #313244;
}

QCheckBox::indicator:checked {
    background-color: #89b4fa;
    border-color: #89b4fa;
}

QScrollArea {
    background-color: transparent;
    border: none;
}
"""

# ==================== 亮色主题样式表 ====================

LIGHT_STYLESHEET = """
/* 默认亮色主题 —— 基本为 Qt 默认样式，微调细节 */
QGroupBox {
    font-weight: bold;
    color: #2c3e50;
}

QPushButton {
    min-height: 28px;
    padding: 6px 16px;
}

QHeaderView::section {
    font-weight: bold;
    padding: 6px;
}

QTableWidget {
    gridline-color: #ddd;
}
"""

# ==================== Matplotlib 暗色风格 ====================

DARK_MPL_RCPARAMS = {
    "figure.facecolor": "#1e1e2e",
    "axes.facecolor": "#313244",
    "axes.edgecolor": "#585b70",
    "axes.labelcolor": "#cdd6f4",
    "text.color": "#cdd6f4",
    "xtick.color": "#a6adc8",
    "ytick.color": "#a6adc8",
    "grid.color": "#45475a",
    "grid.alpha": 0.5,
    "legend.facecolor": "#313244",
    "legend.edgecolor": "#45475a",
}

LIGHT_MPL_RCPARAMS = {
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.edgecolor": "#333333",
    "axes.labelcolor": "#333333",
    "text.color": "#333333",
    "xtick.color": "#555555",
    "ytick.color": "#555555",
    "grid.color": "#cccccc",
    "grid.alpha": 0.7,
    "legend.facecolor": "white",
    "legend.edgecolor": "#cccccc",
}

# Folium 地图 tiles
FOLIUM_DARK_TILES = "CartoDB dark_matter"
FOLIUM_LIGHT_TILES = "OpenStreetMap"


def get_current_stylesheet():
    """获取当前系统主题对应的样式表。"""
    return DARK_STYLESHEET if _detect_system_dark() else LIGHT_STYLESHEET


def get_current_mpl_rcparams():
    """获取当前系统主题对应的 matplotlib rcParams。"""
    return DARK_MPL_RCPARAMS if _detect_system_dark() else LIGHT_MPL_RCPARAMS


def get_folium_tiles():
    """获取当前系统主题对应的 Folium 地图 tiles。"""
    return FOLIUM_DARK_TILES if _detect_system_dark() else FOLIUM_LIGHT_TILES


def apply_theme(app, mpl_rcparams=None):
    """应用主题到 QApplication 和 matplotlib。

    Args:
        app: QApplication 实例
        mpl_rcparams: 如提供则设置 matplotlib.rcParams
    """
    stylesheet = get_current_stylesheet()
    app.setStyleSheet(stylesheet)
    if mpl_rcparams:
        import matplotlib
        for key, value in mpl_rcparams.items():
            matplotlib.rcParams[key] = value
    return _detect_system_dark()
