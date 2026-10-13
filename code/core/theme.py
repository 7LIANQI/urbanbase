"""Google Material 风格主题：白底、灰线、单一蓝色强调。"""

LIGHT = dict(bg="#ffffff", surface="#f8f9fa", border="#dadce0", text="#202124",
             sub="#5f6368", primary="#1a73e8", primary_hover="#1765cc",
             tint="#e8f0fe", danger="#d93025", on_primary="#ffffff", ok="#137333", ok_bg="#e6f4ea")
DARK = dict(bg="#202124", surface="#292a2d", border="#3c4043", text="#e8eaed",
            sub="#9aa0a6", primary="#8ab4f8", primary_hover="#aecbfa",
            tint="#394457", danger="#f28b82", on_primary="#202124", ok="#81c995", ok_bg="#2d3b30")

_QSS = """
* { font-family: "Helvetica Neue", "PingFang SC", "Microsoft YaHei", Arial, sans-serif; font-size: 12px; }
QWidget { background: %(bg)s; color: %(text)s; }
QMainWindow, QDialog { background: %(bg)s; }
QToolTip { background: %(text)s; color: %(bg)s; border: none; padding: 4px 8px; }

QMenuBar { background: %(bg)s; border-bottom: 1px solid %(border)s; padding: 2px 6px; }
QMenuBar::item { padding: 6px 12px; border-radius: 4px; background: transparent; }
QMenuBar::item:selected { background: %(tint)s; color: %(primary)s; }
QMenu { background: %(bg)s; border: 1px solid %(border)s; padding: 6px 0; }
QMenu::item { padding: 7px 28px; }
QMenu::item:selected { background: %(tint)s; color: %(primary)s; }
QMenu::separator { height: 1px; background: %(border)s; margin: 4px 0; }

QStatusBar { background: %(surface)s; border-top: 1px solid %(border)s; color: %(sub)s; }
QStatusBar QLabel { background: transparent; color: %(sub)s; }

QToolBar { background: %(bg)s; border: none; border-bottom: 1px solid %(border)s; padding: 3px 6px; spacing: 2px; }
QToolBar::separator { background: %(border)s; width: 1px; margin: 4px 6px; }
QToolButton { background: transparent; border: 1px solid transparent; border-radius: 4px; padding: 4px; }
QToolButton:hover { background: %(tint)s; }
QToolButton:checked { background: %(tint)s; border: 1px solid %(primary)s; }

QDockWidget { font-weight: 600; }
QDockWidget::title { background: %(surface)s; border-bottom: 1px solid %(border)s; padding: 7px 10px; text-align: left; color: %(sub)s; }
QMainWindow::separator { background: %(border)s; width: 1px; height: 1px; }

QWidget#toolFooter { background: %(surface)s; border-top: 1px solid %(border)s; }
QWidget#toolFooter QPushButton { background: %(bg)s; }
QWidget#toolFooter QPushButton[primary="true"] { background: %(primary)s; }
QLabel#toolHeader { background: %(tint)s; color: %(text)s; padding: 10px 14px; border-bottom: 1px solid %(border)s; }

QGroupBox { border: 1px solid %(border)s; border-radius: 8px; margin-top: 14px; padding: 14px 10px 10px 10px; background: %(bg)s; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: %(sub)s; font-weight: 600; background: %(bg)s; }

QPushButton { background: %(bg)s; color: %(primary)s; border: 1px solid %(border)s; border-radius: 4px; padding: 4px 14px; min-height: 20px; }
QPushButton:hover { background: %(tint)s; }
QPushButton:pressed { background: %(border)s; }
QPushButton:disabled { color: %(sub)s; background: %(surface)s; }
QPushButton[primary="true"] { background: %(primary)s; color: %(on_primary)s; border: none; }
QPushButton[primary="true"]:hover { background: %(primary_hover)s; }

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit, QTimeEdit {
    background: %(bg)s; border: 1px solid %(border)s; border-radius: 4px; padding: 3px 8px; min-height: 20px;
    selection-background-color: %(tint)s; selection-color: %(text)s; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QDateEdit:focus, QTimeEdit:focus { border: 1px solid %(primary)s; }
QComboBox::drop-down, QDateEdit::drop-down, QTimeEdit::drop-down { border: none; width: 24px; }
QComboBox::down-arrow, QDateEdit::down-arrow { image: url(%(down)s); width: 12px; height: 12px; }
QSpinBox::up-button, QDoubleSpinBox::up-button, QTimeEdit::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 20px; border: none; background: transparent; }
QSpinBox::down-button, QDoubleSpinBox::down-button, QTimeEdit::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 20px; border: none; background: transparent; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QTimeEdit::up-arrow { image: url(%(up)s); width: 10px; height: 10px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QTimeEdit::down-arrow { image: url(%(down)s); width: 10px; height: 10px; }
QComboBox QAbstractItemView { background: %(bg)s; border: 1px solid %(border)s; selection-background-color: %(tint)s; selection-color: %(primary)s; }

QCheckBox, QRadioButton { background: transparent; spacing: 8px; }
QGroupBox::indicator { width: 16px; height: 16px; border: 2px solid %(sub)s; border-radius: 3px; background: %(bg)s; }
QGroupBox::indicator:checked { background: %(primary)s; border-color: %(primary)s; image: url(%(check)s); }
QCheckBox::indicator { width: 16px; height: 16px; border: 2px solid %(sub)s; border-radius: 3px; background: %(bg)s; }
QCheckBox::indicator:checked { background: %(primary)s; border-color: %(primary)s; image: url(%(check)s); }
QRadioButton::indicator { width: 16px; height: 16px; border: 2px solid %(sub)s; border-radius: 10px; background: %(bg)s; }
QRadioButton::indicator:checked { border-color: %(primary)s; background: qradialgradient(cx:.5, cy:.5, radius:.5, fx:.5, fy:.5, stop:0 %(primary)s, stop:.5 %(primary)s, stop:.6 %(bg)s, stop:1 %(bg)s); }

QTabWidget::pane { border: none; border-top: 1px solid %(border)s; top: -1px; }
QTabBar::tab { padding: 8px 16px; border: none; border-bottom: 2px solid transparent; color: %(sub)s; background: transparent; }
QTabBar::tab:selected { color: %(primary)s; border-bottom: 2px solid %(primary)s; }
QTabBar::tab:hover { color: %(text)s; }

QTableWidget, QListWidget, QTreeWidget { outline: 0; background: %(bg)s; border: 1px solid %(border)s; border-radius: 4px; gridline-color: %(border)s; alternate-background-color: %(surface)s; }
QListWidget::item:selected, QTableWidget::item:selected, QTreeWidget::item:selected { background: %(tint)s; color: %(text)s; }
QTreeWidget::item { padding: 3px 0; }
QHeaderView::section { background: %(surface)s; color: %(sub)s; border: none; border-bottom: 1px solid %(border)s; padding: 6px 8px; font-weight: 600; }

QProgressBar { max-height: 6px; border: none; background: %(border)s; border-radius: 3px; height: 6px; text-align: center; color: transparent; }
QProgressBar::chunk { background: %(primary)s; border-radius: 3px; }

QScrollArea { border: none; }
QScrollBar:vertical { width: 10px; background: transparent; margin: 0; }
QScrollBar::handle:vertical { background: %(border)s; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: %(sub)s; }
QScrollBar:horizontal { height: 10px; background: transparent; margin: 0; }
QScrollBar::handle:horizontal { background: %(border)s; border-radius: 5px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
"""


def _png(name, color, draw):
    """生成小图标 PNG（QSS 只能引用文件）。"""
    import os
    import tempfile
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
    path = os.path.join(tempfile.gettempdir(), f"urbansense_{name}_{color.lstrip('#')}.png")
    if not os.path.exists(path):
        pm = QPixmap(32, 32)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(color), 4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        draw(p)
        p.end()
        pm.save(path)
    return path.replace("\\", "/")


def _icons(t):
    from PyQt6.QtCore import QPoint
    return dict(
        check=_png("check", "#ffffff", lambda p: p.drawPolyline([QPoint(7, 17), QPoint(13, 23), QPoint(25, 9)])),
        down=_png("down", t["sub"], lambda p: p.drawPolyline([QPoint(7, 12), QPoint(16, 21), QPoint(25, 12)])),
        up=_png("up", t["sub"], lambda p: p.drawPolyline([QPoint(7, 21), QPoint(16, 12), QPoint(25, 21)])))


def build_qss(dark=False):
    t = DARK if dark else LIGHT
    return _QSS % dict(t, **_icons(t))


def apply(app, mode="light"):
    """mode: light / dark / system。返回是否暗色。"""
    if mode == "system":
        try:
            from styles import _detect_system_dark
            dark = _detect_system_dark()
        except ImportError:
            dark = False
    else:
        dark = mode == "dark"
    app.setStyle("Fusion")
    app.setStyleSheet(build_qss(dark))
    return dark
