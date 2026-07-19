#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""城市街道环境大数据采集与分析平台 —— 启动入口。"""
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

# Qt6 要求：QWebEngineView 导入前必须先设置此属性，否则会报
# "QtWebEngineWidgets must be imported or Qt.AA_ShareOpenGLContexts
#  must be set before a QCoreApplication instance is created"
QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

from ui.main_window import MainWindow


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
