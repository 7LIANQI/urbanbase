"""数据分析：时间切片与时间线分析。"""
from core.plugin import Plugin


class TimeAnalysisPlugin(Plugin):
    id = "analysis.time"
    title = "时间分析"
    category = "analysis"
    order = 10
    icon = "chart"
    description = "按时间切片对同一点位做多期对比，生成时间线。"
    size = (900, 400)

    def create(self, ctx):
        ctx.legacy_engine()
        return ctx.legacy_part("time")
