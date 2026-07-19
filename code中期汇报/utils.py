"""公共工具函数模块。"""


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
