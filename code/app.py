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

from core import theme
from ui.shell import ShellWindow


def main():
    """应用入口函数（供 pyproject.toml [project.scripts] 调用）。"""
    from PyQt6.QtCore import QSettings
    app = QApplication(sys.argv)
    theme.apply(app, QSettings("MyCompany", "UrbanAnalysisApp").value("ui/theme", "light"))

    win = ShellWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
