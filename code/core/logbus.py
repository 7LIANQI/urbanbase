"""全局日志总线：所有模块的日志汇入这里，日志页订阅显示。"""
import logging
import sys
from collections import deque
from datetime import datetime

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


def guess_level(msg):
    """旧代码只传带 emoji 的字符串，按前缀/关键字推断级别。"""
    s = str(msg).lstrip()
    if s.startswith(("❌", "🛑")) or "Traceback" in s or "失败" in s[:30]:
        return "ERROR"
    if s.startswith("⚠"):
        return "WARNING"
    return "INFO"


class LogBus(QObject):
    record = pyqtSignal(str, str, str)  # 时间, 级别, 内容

    def __init__(self, max_len=5000):
        super().__init__()
        self.history = deque(maxlen=max_len)

    def add(self, msg, level=None):
        level = level or guess_level(msg)
        ts = datetime.now().strftime("%H:%M:%S")
        self.history.append((ts, level, str(msg)))
        self.record.emit(ts, level, str(msg))

    def install_hooks(self):
        """接管 logging 与未捕获异常。"""
        bus = self

        class _H(logging.Handler):
            def emit(self, rec):
                bus.add(self.format(rec), rec.levelname if rec.levelname != "CRITICAL" else "ERROR")

        h = _H()
        h.setLevel(logging.INFO)
        logging.getLogger().addHandler(h)
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger("matplotlib").setLevel(logging.ERROR)   # 画布缩放时的 aspect 警告无需展示

        old = sys.excepthook

        def hook(t, v, tb):
            import traceback
            bus.add("".join(traceback.format_exception(t, v, tb)), "ERROR")
            old(t, v, tb)

        sys.excepthook = hook


class LogSink(QObject):
    """顶替旧版 QTextEdit.append 的接收端（QObject 槽，保证跨线程信号排队到主线程）。"""

    def __init__(self, bus, parent=None):
        super().__init__(parent)
        self._bus = bus

    @pyqtSlot(str)
    def append(self, msg):
        self._bus.add(msg)
