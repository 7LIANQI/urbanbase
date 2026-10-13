"""工具窗口外壳：说明条 / 内容 / 统一底栏。

所有工具窗口结构一致：
    ┌ 内容（工具自己的界面）─────────────────┐
    ├ 底栏 ───────────────────────────────┤
    │ ?  [次要操作…]         [关闭][停止][主操作] │
    └─────────────────────────────────────┘
工具在返回的界面对象上设置 tool_footer = {"left": [按钮...], "right": [按钮...]}，
按钮会被移入底栏；右侧顺序固定：关闭、（右侧自带按钮，如 停止、主操作）。
"""
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget

from core.polish import polish
from ui.widgets.info_icon import InfoIcon

_BTN_W = 96


def _style_btn(b):
    b.setMinimumSize(_BTN_W, 0)
    b.setMaximumSize(16777215, 16777215)
    b.setFixedHeight(28)
    b.style().unpolish(b)
    b.style().polish(b)


class ToolDialog(QDialog):
    def __init__(self, plugin, body, parent=None):
        super().__init__(parent)
        self.setWindowTitle(plugin.title)
        self.resize(*plugin.size)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(16, 14, 16, 12)
        polish(body)
        inner = body.centralWidget() if isinstance(body, QMainWindow) else body
        if inner.layout() is not None:
            inner.layout().setContentsMargins(0, 0, 0, 0)     # 内容左右边距统一由外壳控制
        hl.addWidget(body)
        lay.addWidget(holder, 1)

        foot = QWidget()
        foot.setObjectName("toolFooter")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(16, 10, 16, 10)
        fl.setSpacing(8)
        spec = getattr(body, "tool_footer", {})
        fl.addWidget(InfoIcon(plugin.description))        # 工具说明收在底栏左侧的小问号里
        for b in spec.get("left", []):
            fl.addWidget(b)
            _style_btn(b)
        fl.addStretch()
        close = QPushButton("关闭")
        close.clicked.connect(self.hide)
        fl.addWidget(close)
        _style_btn(close)
        for b in spec.get("right", []):
            fl.addWidget(b)
            _style_btn(b)
        lay.addWidget(foot)
