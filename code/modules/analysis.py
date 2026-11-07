"""数据分析：点位多期指标趋势。"""
from core.plugin import Plugin


class TimeAnalysisPlugin(Plugin):
    id = "analysis.time"
    title = "时间分析"
    category = "analysis"
    order = 10
    icon = "chart"
    description = ("读取点位指标提取结果 CSV/GPKG 或 PostgreSQL，自动识别固定历史时间段"
                   "和相对窗口，生成趋势图、逐点变化统计、长表和报告。")
    size = (820, 760)

    def create(self, ctx):
        from ui.pages.time_analysis_widget import TimeAnalysisWidget
        return TimeAnalysisWidget(ctx)
