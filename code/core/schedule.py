"""定时采集的时间计算。

每周按首次启用当天的星期重复；每月按首次启用当天的日期重复，
当月没有该日期时使用当月最后一天。
"""
import math
from calendar import monthrange
from datetime import datetime, time, timedelta


FREQUENCIES = ("每天", "每周", "每月")
# Qt 的 QTimer 间隔上限约 24.8 天。用分块等待即可安全覆盖每月任务。
TIMER_CHUNK_MS = 12 * 60 * 60 * 1000


def _at(day, hour, minute):
    return datetime.combine(day, time(hour=hour, minute=minute))


def next_run(now, frequency, hour, minute, anchor):
    """返回严格晚于 now 的下一次执行时间。"""
    if frequency not in FREQUENCIES:
        raise ValueError(f"不支持的采集频率：{frequency}")
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("执行时间无效")

    if frequency == "每天":
        target = _at(now.date(), hour, minute)
        return target if target > now else target + timedelta(days=1)

    if frequency == "每周":
        days = (anchor.weekday() - now.weekday()) % 7
        target = _at(now.date() + timedelta(days=days), hour, minute)
        return target if target > now else target + timedelta(days=7)

    year, month = now.year, now.month
    for _ in range(3):
        day = min(anchor.day, monthrange(year, month)[1])
        target = _at(datetime(year, month, day).date(), hour, minute)
        if target > now:
            return target
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    raise RuntimeError("无法计算下一次每月执行时间")


def timer_delay_ms(now, target, chunk_ms=TIMER_CHUNK_MS):
    """把等待时间限制在 Qt 计时器可接受的范围内。"""
    remaining = max(0.0, (target - now).total_seconds() * 1000)
    return int(min(math.ceil(remaining), chunk_ms))
