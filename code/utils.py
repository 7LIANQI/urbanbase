"""公共工具函数模块。"""
import functools
import logging
import os
import sys
import time
import traceback
from datetime import datetime


# ---- 控制台编码保护 ----
# Windows 默认控制台常为 GBK，print 含 emoji/生僻字符时可能抛
# UnicodeEncodeError。这里给 stdout/stderr 加上 errors="replace"，
# 让不可编码字符被替换而非崩溃（中文显示不受影响）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass


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


# ==================== 网络重试 ====================

def retry_on_network_error(max_retries=3, base_delay=1.0, backoff=2.0):
    """网络请求重试装饰器。

    在 requests.RequestException 或 ee.EEException 上自动重试，
    使用指数退避策略。重试耗尽后抛出原始异常。

    Args:
        max_retries: 最大重试次数（不含首次调用）
        base_delay: 首次重试等待秒数
        backoff: 退避倍数

    用法:
        @retry_on_network_error(max_retries=3)
        def fetch_data():
            return requests.get(url, timeout=10)
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


# ==================== 密钥混淆存储 ====================

def _get_machine_salt():
    """获取机器相关的盐值（用于密钥混淆）。

    使用计算机名 + 用户名 + 固定应用密钥组合，确保同一台机器上每次
    启动 Python 都能得到相同的盐值。
    不再使用 uuid.getnode()——在某些 Windows 系统上它可能返回随机值。

    注意：这是混淆（obfuscation）而非加密（encryption）。
    任何有权限读取本机文件的人都可以逆向出原始密钥。
    如需真正的安全存储，请使用 Windows 凭据管理器或 keyring 库。
    """
    import hashlib
    import os as _os
    parts = [
        _os.environ.get("COMPUTERNAME", ""),
        _os.environ.get("USERNAME", ""),
        "UrbanAnalysisApp.FixedSalt.2026",  # 固定应用密钥
    ]
    combined = "|".join(parts)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def obfuscate(text):
    """对文本进行简单混淆（Base64 + XOR）。

    警告：仅用于防止明文存储，不提供真正的加密安全。
    """
    import base64
    salt = _get_machine_salt()
    # XOR each character with repeating salt bytes
    salt_bytes = salt.encode("utf-8")
    text_bytes = text.encode("utf-8")
    result = bytearray()
    for i, b in enumerate(text_bytes):
        result.append(b ^ salt_bytes[i % len(salt_bytes)])
    return base64.urlsafe_b64encode(bytes(result)).decode("ascii")


def deobfuscate(encoded):
    """反向解混淆。

    Returns:
        原始文本，或空字符串（解码失败时）。
    """
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
    """安全存储敏感值（混淆后保存到文件）。

    Args:
        key: 键名
        value: 要存储的值（明文）

    Returns:
        混淆后的值（可直接存入 QSettings）
    """
    if not value:
        return ""
    return obfuscate(value)


def secure_load(key, obfuscated_value):
    """从混淆值恢复明文。

    Args:
        key: 键名（保留用于未来扩展）
        obfuscated_value: 混淆后的字符串

    Returns:
        原始明文值
    """
    if not obfuscated_value:
        return ""
    return deobfuscate(obfuscated_value)


def safe_call(func, *args, default=None, log_func=None, **kwargs):
    """安全调用函数，捕获常见异常并记录。

    Args:
        func: 要调用的函数
        *args: 位置参数
        default: 异常时返回的默认值
        log_func: 日志回调
        **kwargs: 关键字参数

    Returns:
        func 的返回值，或 default（发生异常时）
    """
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
