"""公共工具函数模块。"""
import logging
import os
from datetime import datetime


def make_logger(callback=None):
    """创建一个 log 函数，有 callback 时转发，否则 print。

    用法:
        log = make_logger(log_callback)
        log("消息内容")
    """
    def log(msg):
        if callback:
            callback(msg)
        else:
            print(msg)
    return log


class FileLogger:
    """同时写入文件、GUI 回调、标准输出的日志器。

    用法:
        fl = FileLogger("logs/", log_callback)
        fl.log("消息")
        # 或用作 callback: log_callback=fl.log
    """

    def __init__(self, log_dir="logs", gui_callback=None):
        os.makedirs(log_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_path = os.path.join(log_dir, f"session_{timestamp}.log")
        self._gui_cb = gui_callback
        self._logger = logging.getLogger(f"urban_analytics_{timestamp}")
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers.clear()

        fh = logging.FileHandler(self._log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        self._logger.addHandler(fh)

    @property
    def log_path(self):
        return self._log_path

    def log(self, msg):
        """记录一条消息（可作为 callback 直接传递）。"""
        self._logger.info(msg)
        if self._gui_cb:
            self._gui_cb(msg)
        print(msg)

    def debug(self, msg):
        self._logger.debug(msg)

    def warning(self, msg):
        self._logger.warning(msg)
        if self._gui_cb:
            self._gui_cb(f"⚠️ {msg}")

    def error(self, msg):
        self._logger.error(msg)
        if self._gui_cb:
            self._gui_cb(f"❌ {msg}")
