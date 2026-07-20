"""OSM 矢量数据 Folium 地图展示组件 + 统计指标面板。"""
import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QGroupBox, QGridLayout, QTextEdit,
)
from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings

import folium


class MapWidget(QWidget):
    """基于 Folium 的 OSM 矢量图层地图 + 统计指标面板。"""

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

        # ---- 图层控制 ----
        control_layout = QHBoxLayout()
        control_layout.addWidget(QLabel("图层:"))
        self.layer_combo = QComboBox()
        self.layer_combo.addItems(self.LAYERS)
        self.layer_combo.currentTextChanged.connect(self.update_map)
        control_layout.addWidget(self.layer_combo)
        control_layout.addStretch()
        layout.addLayout(control_layout)

        # ---- Folium 地图 ----
        self.web_view = QWebEngineView()
        self.web_view.setMinimumHeight(320)
        layout.addWidget(self.web_view)

        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

        # ---- OSM 统计指标面板 ----
        self.stats_group = QGroupBox("📊 OSM 统计指标")
        stats_layout = QGridLayout()

        # 建筑
        stats_layout.addWidget(QLabel("🏠 建筑数量:"), 0, 0)
        self.bld_count = QLabel("--")
        self.bld_count.setStyleSheet("font-weight: bold;")
        stats_layout.addWidget(self.bld_count, 0, 1)
        stats_layout.addWidget(QLabel("建筑总面积:"), 0, 2)
        self.bld_area = QLabel("--")
        self.bld_area.setStyleSheet("font-weight: bold;")
        stats_layout.addWidget(self.bld_area, 0, 3)
        stats_layout.addWidget(QLabel("建筑覆盖率:"), 0, 4)
        self.bld_coverage = QLabel("--")
        self.bld_coverage.setStyleSheet("font-weight: bold;")
        stats_layout.addWidget(self.bld_coverage, 0, 5)

        # 路网
        stats_layout.addWidget(QLabel("🛣️ 道路总长度:"), 1, 0)
        self.road_length = QLabel("--")
        self.road_length.setStyleSheet("font-weight: bold;")
        stats_layout.addWidget(self.road_length, 1, 1)
        stats_layout.addWidget(QLabel("路网密度:"), 1, 2)
        self.road_density = QLabel("--")
        self.road_density.setStyleSheet("font-weight: bold;")
        stats_layout.addWidget(self.road_density, 1, 3)
        stats_layout.addWidget(QLabel("交叉口数量:"), 1, 4)
        self.intersection_count = QLabel("--")
        self.intersection_count.setStyleSheet("font-weight: bold;")
        stats_layout.addWidget(self.intersection_count, 1, 5)

        # 绿地
        stats_layout.addWidget(QLabel("🌿 绿地面积:"), 2, 0)
        self.green_area = QLabel("--")
        self.green_area.setStyleSheet("font-weight: bold;")
        stats_layout.addWidget(self.green_area, 2, 1)
        stats_layout.addWidget(QLabel("绿地覆盖率:"), 2, 2)
        self.green_coverage = QLabel("--")
        self.green_coverage.setStyleSheet("font-weight: bold;")
        stats_layout.addWidget(self.green_coverage, 2, 3)
        stats_layout.addWidget(QLabel("绿地体积估算:"), 2, 4)
        self.green_volume = QLabel("--")
        self.green_volume.setStyleSheet("font-weight: bold;")
        stats_layout.addWidget(self.green_volume, 2, 5)

        self.stats_group.setLayout(stats_layout)
        self.stats_group.hide()  # 默认隐藏，有数据时才显示
        layout.addWidget(self.stats_group)

        self.setLayout(layout)

    def set_enabled(self, enabled):
        self.enabled = enabled
        if not self.enabled:
            self.web_view.setHtml("<h3>地图显示已禁用（采集时未勾选 OSM 数据）</h3>")
            self.stats_group.hide()

    def set_output_dir(self, output_dir):
        self.current_dir = output_dir
        if self.enabled:
            self.update_map()
            self._update_stats_panel()
        else:
            self.web_view.setHtml("<h3>地图显示已禁用（采集时未勾选 OSM 数据）</h3>")
            self.stats_group.hide()

    def _update_stats_panel(self):
        """读取 osm_stats.json 并更新统计指标面板。"""
        stats_path = Path(self.current_dir) / "osm_stats.json"
        if not stats_path.exists():
            self.stats_group.hide()
            return

        try:
            with open(stats_path, 'r', encoding='utf-8') as f:
                stats = json.load(f)

            has_data = False

            # 建筑
            bld = stats.get("buildings", {})
            if bld:
                has_data = True
                self.bld_count.setText(str(bld.get("建筑数量", "--")))
                area = bld.get("建筑总面积_m2", 0)
                if area and area > 10000:
                    self.bld_area.setText(f"{area / 10000:.2f} 万 m²")
                else:
                    self.bld_area.setText(f"{area:,.0f} m²" if area else "--")
                cov = bld.get("建筑覆盖率_pct", None)
                self.bld_coverage.setText(f"{cov:.2f}%" if cov is not None else "--")

            # 路网
            roads = stats.get("roads", {})
            if roads:
                has_data = True
                length_km = roads.get("道路总长度_km", 0)
                self.road_length.setText(f"{length_km:.2f} km" if length_km else "--")
                density = roads.get("路网密度_km_per_km2", None)
                self.road_density.setText(f"{density:.2f} km/km²" if density is not None else "--")
                intersections = roads.get("交叉口数量", None)
                self.intersection_count.setText(str(intersections) if intersections is not None else "--")

            # 绿地
            green = stats.get("green_spaces", {})
            if green:
                has_data = True
                area = green.get("绿地总面积_m2", 0)
                if area and area > 10000:
                    self.green_area.setText(f"{area / 10000:.2f} 万 m²")
                else:
                    self.green_area.setText(f"{area:,.0f} m²" if area else "--")
                cov = green.get("绿地覆盖率_pct", None)
                self.green_coverage.setText(f"{cov:.2f}%" if cov is not None else "--")
                vol = green.get("绿地体积估算_m3", 0)
                if vol and vol > 10000:
                    self.green_volume.setText(f"{vol / 10000:.2f} 万 m³")
                else:
                    self.green_volume.setText(f"{vol:,.0f} m³" if vol else "--")

            if has_data:
                self.stats_group.show()
            else:
                self.stats_group.hide()

        except Exception:
            self.stats_group.hide()

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
