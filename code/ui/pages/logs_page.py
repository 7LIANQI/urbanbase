"""日志管理页：级别筛选、搜索、导出、清空、打开日志目录。"""
import html
import os

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLineEdit,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

_RANK = {"INFO": 0, "WARNING": 1, "ERROR": 2}
_COLOR = {"WARNING": "#e37400", "ERROR": "#d93025"}


class LogsPage(QWidget):
    def __init__(self, bus):
        super().__init__()
        self.bus = bus
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        bar = QHBoxLayout()
        self.level = QComboBox()
        self.level.addItems(["全部", "警告及以上", "仅错误"])
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索日志内容…")
        self.autoscroll = QCheckBox("自动滚动")
        self.autoscroll.setChecked(True)
        btn_clear = QPushButton("清空")
        btn_export = QPushButton("导出…")
        btn_dir = QPushButton("打开日志目录")
        bar.addWidget(self.level)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.autoscroll)
        bar.addWidget(btn_clear)
        bar.addWidget(btn_export)
        bar.addWidget(btn_dir)
        lay.addLayout(bar)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(5000)
        self.view.setStyleSheet("font-family: Menlo, Consolas, monospace; font-size: 12px;")
        lay.addWidget(self.view, 1)

        self.level.currentIndexChanged.connect(self._rerender)
        self.search.textChanged.connect(self._rerender)
        btn_clear.clicked.connect(self._clear)
        btn_export.clicked.connect(self._export)
        btn_dir.clicked.connect(self._open_dir)
        bus.record.connect(self._on_record)
        self._rerender()

    def _pass(self, level, msg):
        min_rank = (0, 1, 2)[self.level.currentIndex()]
        kw = self.search.text().strip().lower()
        return _RANK.get(level, 0) >= min_rank and (not kw or kw in msg.lower())

    def _line(self, ts, level, msg):
        text = html.escape(f"{ts} [{level}] {msg}")
        color = _COLOR.get(level)
        return f'<span style="color:{color}">{text}</span>' if color else text

    def _on_record(self, ts, level, msg):
        if self._pass(level, msg):
            self.view.appendHtml(self._line(ts, level, msg))
            if self.autoscroll.isChecked():
                sb = self.view.verticalScrollBar()
                sb.setValue(sb.maximum())

    def _rerender(self):
        self.view.clear()
        for ts, level, msg in self.bus.history:
            if self._pass(level, msg):
                self.view.appendHtml(self._line(ts, level, msg))

    def _clear(self):
        self.bus.history.clear()
        self.view.clear()

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出日志", "urbansense_log.txt", "文本 (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.view.toPlainText())

    def _open_dir(self):
        d = os.path.abspath("logs")
        os.makedirs(d, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(d))
