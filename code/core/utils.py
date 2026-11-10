"""日志、网络重试和本地设置的辅助函数。"""

import functools
import logging
import os
import sys
import time
import traceback
from datetime import datetime


# Windows 的 GBK 控制台用替代字符显示无法编码的日志内容。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass


def make_logger(callback=None):
    """把消息交给回调，未提供回调时打印到控制台。"""
    def log(msg):
        if callback:
            callback(msg)
        else:
            print(msg)
    return log


class FileLogger:
    """写入会话日志，必要时同步到界面或控制台。"""

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


def retry_on_network_error(max_retries=3, base_delay=1.0, backoff=2.0):
    """请求失败时按指数退避重试，耗尽后抛出最后一次异常。

    max_retries 从首次失败后开始计数。首次等待 base_delay 秒，
    后续等待时间乘以 backoff。
    """
    import requests as _requests
    try:
        import ee as _ee
        _EE_EXCEPTION = _ee.EEException
    except ImportError:
        _EE_EXCEPTION = Exception  # GEE 未安装时回退

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (_requests.RequestException, _EE_EXCEPTION) as e:
                    last_error = e
                    if attempt < max_retries:
                        delay = base_delay * (backoff ** attempt)
                        print(f"⚠️ 网络请求失败 (第{attempt+1}次), "
                              f"{delay:.1f}s 后重试: {e}")
                        time.sleep(delay)
                    else:
                        print(f"❌ 网络请求重试{max_retries}次后仍失败: {e}")
                        raise
            raise last_error  # type: ignore[misc]
        return wrapper
    return decorator


def _get_machine_salt():
    """用计算机名和用户名生成可重复的盐值，供本地设置混淆使用。"""
    import hashlib
    import os as _os
    parts = [
        _os.environ.get("COMPUTERNAME", ""),
        _os.environ.get("USERNAME", ""),
        "UrbanAnalysisApp.FixedSalt.2026",
    ]
    combined = "|".join(parts)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def obfuscate(text):
    """用 XOR 和 Base64 避免明文存储。此格式可逆，不能用于加密。"""
    import base64
    salt = _get_machine_salt()
    salt_bytes = salt.encode("utf-8")
    text_bytes = text.encode("utf-8")
    result = bytearray()
    for i, b in enumerate(text_bytes):
        result.append(b ^ salt_bytes[i % len(salt_bytes)])
    return base64.urlsafe_b64encode(bytes(result)).decode("ascii")


def deobfuscate(encoded):
    """恢复原始文本，解码失败时返回空字符串。"""
    import base64
    try:
        salt = _get_machine_salt()
        salt_bytes = salt.encode("utf-8")
        data = base64.urlsafe_b64decode(encoded.encode("ascii"))
        result = bytearray()
        for i, b in enumerate(data):
            result.append(b ^ salt_bytes[i % len(salt_bytes)])
        return bytes(result).decode("utf-8")
    except Exception:
        return ""


def secure_store(key, value):
    """返回可存入 QSettings 的混淆值，保留 key 参数以兼容调用方。"""
    if not value:
        return ""
    return obfuscate(value)


def secure_load(key, obfuscated_value):
    """恢复 QSettings 中的混淆值，保留 key 参数以兼容调用方。"""
    if not obfuscated_value:
        return ""
    return deobfuscate(obfuscated_value)


def safe_call(func, *args, default=None, log_func=None, **kwargs):
    """调用 func，发生异常时记录错误并返回 default。"""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        msg = f"调用 {getattr(func, '__name__', str(func))} 时出错: {e}"
        if log_func:
            log_func(msg)
        else:
            print(msg)
            traceback.print_exc()
        return default
