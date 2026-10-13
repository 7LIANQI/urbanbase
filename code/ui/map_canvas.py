"""地图画布：基于 matplotlib 的矢量/栅格叠加显示，支持平移、缩放、坐标读数。

所有图层统一重投影到 EPSG:4326 显示。栅格以降采样概览渲染（最长边 ≤ MAX_RASTER_PX）。
"""
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget

MAX_RASTER_PX = 1600
VECTOR_EXT = {".shp", ".geojson", ".json", ".gpkg"}
RASTER_EXT = {".tif", ".tiff"}


@dataclass
class Layer:
    name: str
    path: str
    kind: str                       # "vector" | "raster"
    bounds: tuple                   # (minx, miny, maxx, maxy) EPSG:4326
    visible: bool = True
    style: dict = field(default_factory=dict)
    data: object = None             # vector: GeoDataFrame
    geom_type: str = ""
    artists: list = field(default_factory=list)


def layer_kind(path):
    ext = Path(path).suffix.lower()
    if ext in VECTOR_EXT:
        return "vector"
    if ext in RASTER_EXT:
        return "raster"
    raise ValueError(f"不支持的数据格式: {ext}（支持 shp/geojson/gpkg/tif）")


class MapCanvas(QWidget):
    coord_changed = pyqtSignal(str)
    message = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.layers = []            # 自上而下的图层（索引 0 在最上）
        self.mode = "pan"
        self._press = None

        self.fig = Figure(facecolor="#ffffff")
        self.fig.subplots_adjust(0, 0, 1, 1)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_axis_off()
        self.ax.set_aspect("equal", adjustable="datalim")
        self.canvas = FigureCanvasQTAgg(self.fig)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas)
        self.ax.set_xlim(70, 140)
        self.ax.set_ylim(15, 55)   # 初始显示中国范围

        # 底图：视野变化后 250 ms 去抖再取瓦片
        self._base_key = None
        self._base_img = None
        self._base_credit = None
        self._token = 0
        self._workers = set()        # 持有线程引用，避免运行中被回收
        self._base_warned = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._refresh_basemap)
        self.ax.callbacks.connect("xlim_changed", lambda _a: self._timer.start(250))
        self.ax.callbacks.connect("ylim_changed", lambda _a: self._timer.start(250))

        c = self.canvas
        c.mpl_connect("scroll_event", self._on_scroll)
        c.mpl_connect("button_press_event", self._on_press)
        c.mpl_connect("button_release_event", self._on_release)
        c.mpl_connect("motion_notify_event", self._on_motion)

    # ---------- 图层 ----------
    def add_layer(self, path, name=None, style=None):
        kind = layer_kind(path)
        name = name or Path(path).stem
        if kind == "vector":
            import geopandas as gpd
            gdf = gpd.read_file(path)
            gdf = gdf[~gdf.geometry.isna() & ~gdf.geometry.is_empty]
            if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(4326)
            if gdf.empty:
                raise ValueError("图层没有有效几何")
            gt = gdf.geom_type.iloc[0]
            layer = Layer(name, path, kind, tuple(gdf.total_bounds), data=gdf, geom_type=gt,
                          style=style or {"mode": "single", "color": "#1a73e8"})
        else:
            layer = Layer(name, path, kind, (0, 0, 0, 0),
                          style=style or {"cmap": "viridis"})
        self._draw(layer)
        self.layers.insert(0, layer)
        self._restack()
        if len(self.layers) == 1:
            self.zoom_to(layer.bounds)
        else:
            self.canvas.draw_idle()
        return layer

    def _draw(self, layer):
        ax = self.ax
        n0 = (len(ax.collections), len(ax.lines), len(ax.images))
        if layer.kind == "vector":
            self._draw_vector(layer)
        else:
            self._draw_raster(layer)
        layer.artists = (list(ax.collections[n0[0]:]) + list(ax.lines[n0[1]:])
                         + list(ax.images[n0[2]:]))
        for a in layer.artists:
            a.set_visible(layer.visible)

    def _draw_vector(self, layer):
        st, gdf = layer.style, layer.data
        kw = {}
        if "Polygon" in layer.geom_type:
            kw.update(edgecolor="#5f6368", linewidth=0.3, alpha=0.8)
        elif "Line" in layer.geom_type:
            kw.update(linewidth=0.7)
        else:
            kw.update(markersize=8)
        if st.get("mode") == "graduated" and st.get("field") in gdf.columns:
            gdf.plot(ax=self.ax, column=st["field"], cmap=st.get("cmap", "viridis"), **kw)
        else:
            gdf.plot(ax=self.ax, color=st.get("color", "#1a73e8"), **kw)
        self.ax.set_axis_off()
        self.ax.set_aspect("equal", adjustable="datalim")

    def _draw_raster(self, layer):
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.vrt import WarpedVRT
        src = rasterio.open(layer.path)
        try:
            ds = src
            if src.crs is not None and src.crs.to_epsg() != 4326:
                ds = WarpedVRT(src, crs="EPSG:4326")
            scale = min(1.0, MAX_RASTER_PX / max(ds.width, ds.height))
            shape = (max(1, int(ds.height * scale)), max(1, int(ds.width * scale)))
            arr = ds.read(1, out_shape=shape, masked=True, resampling=Resampling.nearest)
            b = ds.bounds
        finally:
            src.close()
        layer.bounds = (b.left, b.bottom, b.right, b.top)
        vals = arr.compressed()
        vmin, vmax = (np.percentile(vals, [2, 98]) if vals.size else (0, 1))
        self.ax.imshow(arr, extent=(b.left, b.right, b.bottom, b.top), origin="upper",
                       cmap=layer.style.get("cmap", "viridis"), vmin=vmin, vmax=vmax,
                       interpolation="nearest")
        self.ax.set_axis_off()
        self.ax.set_aspect("equal", adjustable="datalim")

    def restyle(self, layer):
        for a in layer.artists:
            a.remove()
        xl, yl = self.ax.get_xlim(), self.ax.get_ylim()
        self._draw(layer)
        self._restack()
        self.ax.set_xlim(xl)
        self.ax.set_ylim(yl)
        self.canvas.draw_idle()

    def remove_layer(self, layer):
        for a in layer.artists:
            a.remove()
        self.layers.remove(layer)
        self.canvas.draw_idle()

    def set_visible(self, layer, visible):
        layer.visible = visible
        for a in layer.artists:
            a.set_visible(visible)
        self.canvas.draw_idle()

    def set_order(self, layers):
        self.layers = list(layers)
        self._restack()
        self.canvas.draw_idle()

    def _restack(self):
        n = len(self.layers)
        for i, lyr in enumerate(self.layers):
            for a in lyr.artists:
                a.set_zorder(n - i)

    # ---------- 视图 ----------
    def zoom_to(self, bounds, pad=0.05):
        x0, y0, x1, y1 = bounds
        dx, dy = (x1 - x0) or 0.01, (y1 - y0) or 0.01
        self.ax.set_xlim(x0 - dx * pad, x1 + dx * pad)
        self.ax.set_ylim(y0 - dy * pad, y1 + dy * pad)
        self.canvas.draw_idle()

    def zoom_full(self):
        vis = [l.bounds for l in self.layers if l.visible] or [l.bounds for l in self.layers]
        if vis:
            a = np.array(vis)
            self.zoom_to((a[:, 0].min(), a[:, 1].min(), a[:, 2].max(), a[:, 3].max()))

    def zoom_by(self, factor, center=None):
        ax = self.ax
        (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
        cx, cy = center or ((x0 + x1) / 2, (y0 + y1) / 2)
        ax.set_xlim(cx - (cx - x0) * factor, cx + (x1 - cx) * factor)
        ax.set_ylim(cy - (cy - y0) * factor, cy + (y1 - cy) * factor)
        self.canvas.draw_idle()

    def set_mode(self, mode):
        self.mode = mode

    def extent(self):
        return list(self.ax.get_xlim()) + list(self.ax.get_ylim())

    def set_extent(self, e):
        self.ax.set_xlim(e[0], e[1])
        self.ax.set_ylim(e[2], e[3])
        self.canvas.draw_idle()

    # ---------- 底图 ----------
    def set_basemap(self, key):
        """key 为 ui.basemap.BASEMAPS 的键，None 表示无底图。"""
        self._base_key = key
        self._token += 1
        if self._base_img is not None:
            self._base_img.remove()
            self._base_img = None
        if self._base_credit is not None:
            self._base_credit.remove()
            self._base_credit = None
        self._base_warned = False
        if key:
            self._refresh_basemap()
        else:
            self.canvas.draw_idle()

    def _refresh_basemap(self):
        if not self._base_key:
            return
        from ui.basemap import TileWorker
        self._token += 1
        w = TileWorker(self._base_key, tuple(self.ax.get_xlim()) + tuple(self.ax.get_ylim()),
                       self.canvas.width(), self._token)
        w.ready.connect(self._on_tiles)
        w.finished.connect(lambda w=w: self._workers.discard(w))
        self._workers.add(w)
        w.start()

    def _on_tiles(self, img, ext, token, failed):
        if token != self._token or not self._base_key:   # 视野已变化或底图已切换，丢弃过期结果
            return
        from ui.basemap import BASEMAPS
        if failed and not self._base_warned:
            self._base_warned = True
            self.message.emit(f"⚠️ 底图有 {failed} 块瓦片下载失败（网络不通？），已留白")
        xl, yl = self.ax.get_xlim(), self.ax.get_ylim()
        lon0, lon1, lat0, lat1 = ext
        if self._base_img is None:
            self._base_img = self.ax.imshow(img, extent=(lon0, lon1, lat0, lat1), origin="upper",
                                            zorder=0, interpolation="bilinear", aspect="equal")
        else:
            self._base_img.set_data(img)
            self._base_img.set_extent((lon0, lon1, lat0, lat1))
        if self._base_credit is None:
            self._base_credit = self.ax.text(0.995, 0.005, "", transform=self.ax.transAxes, ha="right",
                                             va="bottom", fontsize=7, color="#5f6368", zorder=1000,
                                             bbox=dict(fc="white", ec="none", alpha=0.7, pad=1.5))
        self._base_credit.set_text(BASEMAPS[self._base_key][3])
        self.ax.set_axis_off()
        self.ax.set_aspect("equal", adjustable="datalim")
        self.ax.set_xlim(xl, emit=False)       # 不触发 xlim_changed，避免循环取瓦片
        self.ax.set_ylim(yl, emit=False)
        self.canvas.draw_idle()

    # ---------- 交互 ----------
    def _on_scroll(self, ev):
        if ev.inaxes is self.ax:
            self.zoom_by(0.8 if ev.button == "up" else 1.25, (ev.xdata, ev.ydata))

    def _on_press(self, ev):
        if ev.button == 1 and ev.inaxes is self.ax:
            self._press = (ev.x, ev.y, self.ax.get_xlim(), self.ax.get_ylim(), ev.xdata, ev.ydata)

    def _on_motion(self, ev):
        if ev.inaxes is self.ax and ev.xdata is not None:
            self.coord_changed.emit(f"经度 {ev.xdata:.5f}   纬度 {ev.ydata:.5f}")
        if self._press and self.mode == "pan" and ev.x is not None:
            x, y, xl, yl, _, _ = self._press
            inv = self.ax.transData.inverted()
            (px, py), (qx, qy) = inv.transform((x, y)), inv.transform((ev.x, ev.y))
            self.ax.set_xlim(xl[0] + px - qx, xl[1] + px - qx)
            self.ax.set_ylim(yl[0] + py - qy, yl[1] + py - qy)
            self.canvas.draw_idle()

    def _on_release(self, ev):
        if self._press and self.mode == "zoom_box" and ev.xdata is not None:
            x0, y0 = self._press[4], self._press[5]
            if abs(ev.xdata - x0) > 1e-9 and abs(ev.ydata - y0) > 1e-9:
                self.zoom_to((min(x0, ev.xdata), min(y0, ev.ydata),
                              max(x0, ev.xdata), max(y0, ev.ydata)), pad=0)
        self._press = None
