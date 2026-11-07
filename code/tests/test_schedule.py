"""定时采集时间计算：指定时刻、每周锚点、月末和 Qt 长间隔限制。"""
from datetime import datetime

from core.schedule import TIMER_CHUNK_MS, next_run, timer_delay_ms


def test_daily_uses_selected_clock_time():
    now = datetime(2026, 10, 27, 14, 0)
    assert next_run(now, "每天", 8, 0, now.date()) == datetime(2026, 10, 28, 8, 0)
    assert next_run(now, "每天", 20, 0, now.date()) == datetime(2026, 10, 27, 20, 0)


def test_weekly_keeps_anchor_weekday():
    anchor = datetime(2026, 10, 27, 8, 0)          # 周二
    assert next_run(datetime(2026, 10, 27, 9, 0), "每周", 8, 0, anchor) == datetime(2026, 11, 3, 8, 0)
    assert next_run(datetime(2026, 10, 30, 9, 0), "每周", 8, 0, anchor) == datetime(2026, 11, 3, 8, 0)


def test_monthly_uses_anchor_day_and_month_end():
    anchor = datetime(2026, 1, 31, 8, 0)
    assert next_run(datetime(2026, 2, 1, 0, 0), "每月", 8, 0, anchor) == datetime(2026, 2, 28, 8, 0)
    assert next_run(datetime(2026, 2, 28, 8, 0, 1), "每月", 8, 0, anchor) == datetime(2026, 3, 31, 8, 0)


def test_timer_delay_is_capped_for_qt():
    now = datetime(2026, 10, 1, 8, 0)
    target = datetime(2026, 10, 31, 8, 0)
    delay = timer_delay_ms(now, target)
    assert 0 < delay <= TIMER_CHUNK_MS < 2**31 - 1


def test_timer_delay_never_negative():
    now = datetime(2026, 10, 31, 8, 0)
    assert timer_delay_ms(now, datetime(2026, 10, 30, 8, 0)) == 0
