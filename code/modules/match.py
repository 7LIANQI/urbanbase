"""数据匹配：栅格值赋给路网、本地数据按点位匹配。"""
from core.plugin import Plugin


class RasterToRoadsPlugin(Plugin):
    id = "match.raster_to_roads"
    title = "栅格值路网赋值"
    category = "match"
    order = 10
    icon = "raster"
    description = "把 TIF / NC 栅格的值按长度加权或最近路段分配到路网；结果自动加入地图。"
    size = (900, 780)

    def create(self, ctx):
        from ui.raster_to_roads_window import RasterToRoadsWindow
        w = RasterToRoadsWindow()
        w.setMinimumSize(0, 0)
        shp = ctx.selected_vector_path()      # 图层面板里选中的矢量图层作为默认路网
        if shp and shp.lower().endswith(".shp"):
            w.set_shapefile(shp)
        w.output_ready.connect(ctx.add_layer)
        w.tool_footer = {"right": [w.run_btn]}
        return w


class LocalMatchPlugin(Plugin):
    id = "match.local"
    title = "本地数据匹配"
    category = "match"
    order = 20
    icon = "match"
    description = "导入本地数据集（PostgreSQL），按坐标查询或批量匹配。"
    size = (900, 700)

    def create(self, ctx):
        ctx.legacy_engine()
        return ctx.legacy_part("local")
