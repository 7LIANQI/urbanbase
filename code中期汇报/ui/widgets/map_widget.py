"""OSM 矢量数据 Folium 地图展示组件。"""
import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox,
)
from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings

import folium


class MapWidget(QWidget):
    """基于 Folium 的 OSM 矢量图层地图（路网 / 建筑 / 绿地 / 水体）。"""

    LAYERS = ["路网", "建筑", "绿地", "水体"]
    LAYER_FILES = {
        "路网": "roads.geojson",
        "建筑": "buildings.geojson",
        "绿地": "green_spaces.geojson",
        "水体": "water_bodies.geojson",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_dir = None
        self.enabled = True
        self.web_view = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()

        control_layout = QHBoxLayout()
        control_layout.addWidget(QLabel("图层:"))
        self.layer_combo = QComboBox()
        self.layer_combo.addItems(self.LAYERS)
        self.layer_combo.currentTextChanged.connect(self.update_map)
        control_layout.addWidget(self.layer_combo)
        control_layout.addStretch()
        layout.addLayout(control_layout)

        self.web_view = QWebEngineView()
        self.web_view.setMinimumHeight(400)
        layout.addWidget(self.web_view)

        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

        self.setLayout(layout)

    def set_enabled(self, enabled):
        self.enabled = enabled
        if not self.enabled:
            self.web_view.setHtml("<h3>地图显示已禁用（采集时未勾选 OSM 数据）</h3>")

    def set_output_dir(self, output_dir):
        self.current_dir = output_dir
        if self.enabled:
            self.update_map()
        else:
            self.web_view.setHtml("<h3>地图显示已禁用（采集时未勾选 OSM 数据）</h3>")

    def update_map(self):
        if not self.enabled or not self.current_dir:
            self.web_view.setHtml("<h3>请先执行数据采集</h3>")
            return

        layer_type = self.layer_combo.currentText()
        geojson_path = Path(self.current_dir) / self.LAYER_FILES[layer_type]

        if not geojson_path.exists():
            self.web_view.setHtml(
                f"<h3>未找到 {layer_type} 数据文件</h3>"
                f"<p>路径: {geojson_path}</p>"
            )
            return

        try:
            with open(geojson_path, 'r', encoding='utf-8') as f:
                geojson_str = f.read()

            data = json.loads(geojson_str)
            features = data.get('features', [])
            if not features:
                self.web_view.setHtml(
                    f"<h3>{layer_type} 数据为空</h3>"
                    f"<p>文件存在但无要素数据</p>"
                )
                return

            center_lat, center_lon = self._compute_center(features)

            m = folium.Map(location=[center_lat, center_lon], zoom_start=13)
            folium.GeoJson(geojson_str, name=layer_type).add_to(m)
            temp_path = Path(self.current_dir) / f"temp_map_{layer_type}.html"
            m.save(str(temp_path))

            self.web_view.setUrl(QUrl.fromLocalFile(str(temp_path.absolute())))

        except Exception as e:
            self.web_view.setHtml(
                f"<html><body style='font-family: Arial; padding: 20px;'>"
                f"<h3>地图加载失败</h3><p>错误: {str(e)}</p>"
                f"</body></html>"
            )

    @staticmethod
    def _compute_center(features):
        """从前 50 个要素中提取坐标，计算地图中心点。"""
        lons, lats = [], []
        for feat in features[:50]:
            geom = feat.get('geometry', {})
            geo_type = geom.get('type')
            coords = geom.get('coordinates', [])

            if geo_type == 'Point':
                lons.append(coords[0])
                lats.append(coords[1])
            elif geo_type in ('LineString', 'MultiLineString'):
                lines = coords if geo_type == 'LineString' else [
                    c for line in coords for c in line
                ]
                for c in lines:
                    if len(c) >= 2:
                        lons.append(c[0])
                        lats.append(c[1])
            elif geo_type in ('Polygon', 'MultiPolygon'):
                polys = coords[0] if geo_type == 'Polygon' else [
                    c for poly in coords for c in poly[0]
                ]
                for c in polys:
                    if len(c) >= 2:
                        lons.append(c[0])
                        lats.append(c[1])

        if lons and lats:
            return sum(lats) / len(lats), sum(lons) / len(lons)
        return 39.9055, 116.3912
