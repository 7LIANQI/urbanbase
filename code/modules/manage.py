"""数据管理：采集历史（查看、对比、导出、清理）。"""
from core.plugin import Plugin


class HistoryPlugin(Plugin):
    id = "manage.history"
    title = "采集历史"
    category = "manage"
    order = 10
    icon = "database"
    description = "浏览历史采集结果，支持筛选、对比、时间线与清理。"
    size = (520, 640)

    def create(self, ctx):
        ctx.legacy_engine()
        return ctx.legacy_part("history")


class CatalogPlugin(Plugin):
    id = "manage.catalog"
    title = "栅格数据目录"
    category = "manage"
    order = 20
    icon = "table"
    description = "管理本地栅格数据：编辑每个数据序列的信息（产品、时间尺度、起止年份等），并检查目录与文件是否一致。"
    size = (900, 860)

    def create(self, ctx):
        from ui.pages.catalog_widget import CatalogWidget
        return CatalogWidget(ctx)


class CogPlugin(Plugin):
    id = "manage.cog"
    title = "栅格转 COG（批量）"
    category = "manage"
    order = 30
    icon = "raster"
    description = "把一批 GeoTIFF 或 NetCDF 批量转成 COG（分块 + 压缩 + 缩略图）。NetCDF 按时间层拆开，数值保持原样。可按命名规则重命名、统一坐标系（默认 WGS84），也可直接放进数据序列。"
    size = (900, 900)

    def create(self, ctx):
        from ui.pages.cog_widget import CogWidget
        return CogWidget(ctx)
