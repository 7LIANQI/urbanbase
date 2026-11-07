"""数据下载：环境数据采集（点位 → 数据项 → 密钥与输出 → 运行）、定时自动采集。"""
from PyQt6.QtWidgets import (
    QGroupBox, QHBoxLayout, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from core.plugin import Plugin


def _btn(text, slot, primary=False):
    b = QPushButton(text)
    b.clicked.connect(slot)
    if primary:
        b.setProperty("primary", True)
    return b


class CollectPlugin(Plugin):
    id = "download.collect"
    title = "环境数据采集"
    category = "download"
    order = 10
    icon = "download"
    description = "依次设置：① 点位与时间 → ② 数据项 → ③ 密钥与输出，然后点击「开始采集」。"
    size = (900, 720)

    def create(self, ctx):
        eng = ctx.legacy_engine()
        part = ctx.legacy_part
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()
        for title, key in (("① 点位与时间", "input"), ("② 数据项", "options"), ("③ 密钥与输出", "api")):
            holder = QWidget()
            hl = QVBoxLayout(holder)
            hl.addWidget(part(key))
            if key != "options":
                hl.addStretch(1)
            tabs.addTab(holder, title)
        lay.addWidget(tabs, 1)
        lay.addWidget(part("progress"))
        lay.addWidget(part("step"))

        box = QGroupBox("项目与结果")          # 与项目、结果相关的操作放在自己的分组里
        bl = QHBoxLayout(box)
        for b in (_btn("保存项目…", eng._save_project), _btn("加载项目…", eng._load_project),
                  _btn("导出当前数据…", eng._export_current_data), _btn("查看结果", eng.result_dialog.show),
                  _btn("查看日志", ctx.show_log)):
            bl.addWidget(b)
        bl.addStretch()
        lay.addWidget(box)
        body.tool_footer = {"right": [_btn("停止", eng._stop_tasks), _btn("开始采集", eng._start_tasks, primary=True)]}
        return body


class SchedulePlugin(Plugin):
    id = "download.schedule"
    title = "定时自动采集"
    category = "download"
    order = 20
    icon = "clock"
    description = ("按每天、每周或每月的指定时刻重复采集，用于连续监测。"
                   "每周沿用首次启用当天的星期；每月沿用首次启用当天的日期，无该日期时在月末执行。")
    size = (900, 300)

    def create(self, ctx):
        ctx.legacy_engine()
        return ctx.legacy_part("auto")


class ExtractPlugin(Plugin):
    id = "download.extract"
    title = "点位指标提取"
    category = "download"
    order = 15
    icon = "match"
    description = "对一批点位提取遥感、气象、人口、地形等指标。缓冲区、时间窗均可选；数据源在「设置 → GEE 数据源」中统一选择。"
    size = (900, 820)

    def create(self, ctx):
        from ui.pages.extract_widget import ExtractWidget
        return ExtractWidget(ctx)
