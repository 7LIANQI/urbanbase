#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""城市街道环境大数据采集与分析平台 —— 启动入口。"""
import sys

# ---- Matplotlib 全局配置（必须在 QApplication 创建前设置） ----
import matplotlib
matplotlib.use('qtagg')
matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False
matplotlib.rcParams['figure.dpi'] = 80

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

# Qt6 要求：QWebEngineView 导入前必须先设置此属性，否则会报
# "QtWebEngineWidgets must be imported or Qt.AA_ShareOpenGLContexts
#  must be set before a QCoreApplication instance is created"
QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

from ui.main_window import MainWindow


def main():
    """应用入口函数（供 pyproject.toml [project.scripts] 调用）。"""
    app = QApplication(sys.argv)

    # 检测系统主题并应用
    try:
        from styles import apply_theme, get_current_mpl_rcparams
        is_dark = apply_theme(app, get_current_mpl_rcparams())
        if is_dark:
            print("🌙 已启用暗色模式")
    except ImportError:
        pass  # styles.py 不存在时跳过

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
