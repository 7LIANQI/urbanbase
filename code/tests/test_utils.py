"""测试 utils.py 工具函数。"""
import os
import tempfile
import pytest
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import make_logger, FileLogger


def _close_logger(fl):
    """安全关闭 FileLogger 的文件句柄（避免 Windows 文件锁）。"""
    for handler in fl._logger.handlers[:]:
        handler.close()
        fl._logger.removeHandler(handler)


class TestMakeLogger:
    """测试 make_logger 函数。"""

    def test_log_with_callback(self):
        """测试带回调的日志函数。"""
        messages = []

        def cb(msg):
            messages.append(msg)

        log = make_logger(cb)
        log("hello")
        log("world")
        assert messages == ["hello", "world"]

    def test_log_without_callback(self, capsys):
        """测试无回调时打印到 stdout。"""
        log = make_logger(None)
        log("test message")
        captured = capsys.readouterr()
        assert "test message" in captured.out

    def test_log_none_callback(self, capsys):
        """测试显式传递 None 作为回调。"""
        log = make_logger()
        log("fallback to print")
        captured = capsys.readouterr()
        assert "fallback to print" in captured.out


class TestFileLogger:
    """测试 FileLogger 类。"""

    def test_creates_log_file(self):
        """测试创建日志文件。"""
        fl = None
        tmpdir = tempfile.mkdtemp()
        try:
            fl = FileLogger(tmpdir)
            fl.log("test message")
            assert os.path.exists(fl.log_path)
            with open(fl.log_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert "test message" in content
        finally:
            if fl:
                _close_logger(fl)

    def test_gui_callback(self):
        """测试 GUI 回调被调用。"""
        fl = None
        tmpdir = tempfile.mkdtemp()
        try:
            calls = []

            def cb(msg):
                calls.append(msg)

            fl = FileLogger(tmpdir, gui_callback=cb)
            fl.log("hello gui")
            assert len(calls) == 1
            assert "hello gui" in calls[0]
        finally:
            if fl:
                _close_logger(fl)

    def test_error_method(self):
        """测试 error 方法添加前缀。"""
        fl = None
        tmpdir = tempfile.mkdtemp()
        try:
            calls = []

            def cb(msg):
                calls.append(msg)

            fl = FileLogger(tmpdir, gui_callback=cb)
            fl.error("something went wrong")
            assert len(calls) == 1
            assert "❌" in calls[0]
            assert "something went wrong" in calls[0]
        finally:
            if fl:
                _close_logger(fl)

    def test_warning_method(self):
        """测试 warning 方法添加前缀。"""
        fl = None
        tmpdir = tempfile.mkdtemp()
        try:
            calls = []

            def cb(msg):
                calls.append(msg)

            fl = FileLogger(tmpdir, gui_callback=cb)
            fl.warning("be careful")
            assert len(calls) == 1
            assert "⚠️" in calls[0]
            assert "be careful" in calls[0]
        finally:
            if fl:
                _close_logger(fl)

    def test_log_path_property(self):
        """测试 log_path 属性。"""
        fl = None
        tmpdir = tempfile.mkdtemp()
        try:
            fl = FileLogger(tmpdir)
            assert fl.log_path.endswith(".log")
            assert fl.log_path.startswith(tmpdir)
        finally:
            if fl:
                _close_logger(fl)
