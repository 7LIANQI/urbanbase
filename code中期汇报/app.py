#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""城市街道环境大数据采集与分析平台 —— 启动入口。"""
import sys

from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
