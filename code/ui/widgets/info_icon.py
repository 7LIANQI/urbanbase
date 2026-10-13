"""圆形小问号：鼠标悬停 1 秒后浮出说明文字，移开立即消失。TitledLabel = 标题 + 问号。"""
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QToolTip, QWidget


class InfoIcon(QWidget):
    DELAY_MS = 1000

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self._text = text
        self._hover = False
        self.setFixedSize(16, 16)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setMouseTracking(True)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._show)

    def setText(self, text):
        self._text = text

    def enterEvent(self, e):
        self._hover = True
        self.update()
        self._timer.start(self.DELAY_MS)

    def leaveEvent(self, e):
        self._hover = False
        self._timer.stop()
        QToolTip.hideText()
        self.update()

    def _show(self):
        QToolTip.showText(self.mapToGlobal(self.rect().bottomRight()), self._text, self)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor("#1a73e8") if self._hover else QColor("#80868b")
        p.setPen(QPen(c, 1.3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        r = QRectF(1.5, 1.5, 13, 13)
        p.drawEllipse(r)
        f = QFont(p.font())
        f.setPixelSize(10)
        f.setBold(True)
        p.setFont(f)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, "?")


class TitledLabel(QWidget):
    """表单行标题：右对齐文字 + 可选的小问号（无说明时占位，保证各行对齐）。"""

    def __init__(self, text, tip="", width=78, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        self.label = QLabel(text)
        self.label.setFixedWidth(width)
        self.label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.icon = InfoIcon(tip)
        sp = self.icon.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        self.icon.setSizePolicy(sp)
        self.icon.setVisible(bool(tip))
        h.addWidget(self.label)
        h.addWidget(self.icon)
        self.setFixedWidth(width + 4 + 16)

    def setText(self, text):
        self.label.setText(text)

    def setTip(self, tip):
        self.icon.setText(tip)
        self.icon.setVisible(bool(tip))
