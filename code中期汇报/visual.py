import sys
import os
import json
import time
from datetime import datetime
from pathlib import Path
import glob
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import QPixmap
from PyQt6.QtWebEngineWidgets import QWebEngineView

# ==================== 全局修复 ====================
import matplotlib
matplotlib.use('qtagg')
matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False
matplotlib.rcParams['figure.dpi'] = 80

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

import folium
import pandas as pd
import geopandas as gpd

# ===================================================
from main1 import process_location

# ==================== 1. Worker 类 ====================
class Worker(QThread):
    log = pyqtSignal(str)
    progress = pyqtSignal(int)
    finished = pyqtSignal(list)
    result_ready = pyqtSignal(str)

    def __init__(self, tasks, map_key, rs_key, gee_key_path,
                 enable_air, enable_street, enable_gee, enable_osm):
        super().__init__()
        self.tasks = tasks
        self.map_key = map_key
        self.rs_key = rs_key
        self.gee_key_path = gee_key_path
        self.enable_air = enable_air
        self.enable_street = enable_street
        self.enable_gee = enable_gee
        self.enable_osm = enable_osm
        self._is_running = True  # 用于停止任务的标志位

    def run(self):
        output_dirs = []
        total = len(self.tasks)

        for i, (lon, lat, r, sd, ed) in enumerate(self.tasks, 1):
            if not self._is_running:
                self.log.emit("🛑 任务被用户中断")
                break

            self.log.emit(f"▶ 开始处理：经度 {lon}, 纬度 {lat}")
            try:
                def log_callback(msg):
                    self.log.emit(msg)

                out_dir = process_location(
                    lon, lat, r, sd, ed,
                    baidu_key=self.map_key,
                    openweather_key=self.rs_key,
                    gee_key_path=self.gee_key_path,
                    enable_air_quality=self.enable_air,
                    enable_streetview=self.enable_street,
                    enable_gee=self.enable_gee,
                    enable_osm=self.enable_osm,
                    log_callback=log_callback
                )
                output_dirs.append(out_dir)
                self.result_ready.emit(out_dir)
                self.log.emit(f"✅ 完成，输出目录: {out_dir}")
            except Exception as e:
                self.log.emit(f"❌ 错误: {e}")

            progress_val = int((i / total) * 100)
            self.progress.emit(progress_val)

        self.finished.emit(output_dirs)

    def stop(self):
        self._is_running = False

# ==================== 2. AirQualityWidget 类 ====================
class AirQualityWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_dir = None
        self.enabled = True
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        
        # AQI 显示标签
        self.aqi_label = QLabel("AQI 等级: --")
        self.aqi_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #333; padding: 10px;")
        self.aqi_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.aqi_label)

        # 污染物表格
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["污染物", "浓度 (μg/m³)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers) # 只读
        layout.addWidget(self.table)

        # 提示信息
        self.info_label = QLabel("请先执行数据采集以查看空气质量")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.info_label)

        self.setLayout(layout)

    def set_enabled(self, enabled):
        self.enabled = enabled
        if not self.enabled:
            self.aqi_label.setText("空气质量显示已禁用")
            self.table.setRowCount(0)
            self.info_label.setText("（采集时未勾选空气质量模块）")

    def set_output_dir(self, output_dir):
        self.current_dir = output_dir
        if self.enabled:
            self.load_data()
        else:
            self.aqi_label.setText("空气质量显示已禁用")
            self.table.setRowCount(0)

    def load_data(self):
        if not self.current_dir:
            return

        json_path = Path(self.current_dir) / "air_quality.json"
        if not json_path.exists():
            self.aqi_label.setText("AQI 等级: 未找到数据")
            self.table.setRowCount(0)
            self.info_label.setText("该位置未采集空气质量数据")
            return

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if data.get("code") == "200" and "now" in data:
                now = data["now"]
                aqi = now.get("aqi", "N/A")
                components = now.get("components", {})

                # 设置 AQI 颜色和文字
                aqi_colors = {1: "green", 2: "#DAA520", 3: "orange", 4: "red", 5: "purple"}
                color = aqi_colors.get(aqi, "black")
                self.aqi_label.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {color}; padding: 10px;")
                self.aqi_label.setText(f"AQI 等级: {aqi}")

                # 填充表格
                poll_names = {
                    "co": "CO (一氧化碳)",
                    "no": "NO (一氧化氮)",
                    "no2": "NO2 (二氧化氮)",
                    "o3": "O3 (臭氧)",
                    "so2": "SO2 (二氧化硫)",
                    "pm2_5": "PM2.5",
                    "pm10": "PM10",
                    "nh3": "NH3 (氨气)"
                }
                
                rows = []
                for key, label in poll_names.items():
                    if key in components:
                        rows.append((label, f"{components[key]:.2f}"))

                self.table.setRowCount(len(rows))
                for i, (label, value) in enumerate(rows):
                    self.table.setItem(i, 0, QTableWidgetItem(label))
                    self.table.setItem(i, 1, QTableWidgetItem(value))
                
                self.info_label.setText(f"数据更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                self.aqi_label.setText("数据格式错误或接口调用失败")
        except Exception as e:
            self.aqi_label.setText("读取数据失败")
            self.info_label.setText(f"错误: {str(e)}")
            
# ==================== 3. StreetViewWidget 类 ====================
class StreetViewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_dir = None
        self.enabled = True
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        
        # 控制栏：选择方向
        control_layout = QHBoxLayout()
        control_layout.addWidget(QLabel("选择方向:"))
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(["0° (正前方)", "90° (右方)", "180° (后方)", "270° (左方)"])
        self.direction_combo.currentIndexChanged.connect(self.load_image)
        control_layout.addWidget(self.direction_combo)
        control_layout.addStretch()
        layout.addLayout(control_layout)

        # 图片显示区域
        self.image_label = QLabel("暂无街景图片\n请先执行数据采集")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(600, 400)
        self.image_label.setStyleSheet("""
            QLabel {
                border: 2px solid #cccccc;
                border-radius: 5px;
                background-color: #f0f0f0;
            }
        """)
        layout.addWidget(self.image_label)
        self.setLayout(layout)

    def set_enabled(self, enabled):
        self.enabled = enabled
        if not self.enabled:
            self.image_label.setText("街景显示已禁用（采集时未勾选）")

    def set_output_dir(self, output_dir):
        self.current_dir = output_dir
        if self.enabled:
            self.load_image() # 设置目录后立即加载图片
        else:
            self.image_label.setText("街景显示已禁用（采集时未勾选）")

    def load_image(self):
        if not self.enabled:
            self.image_label.setText("街景显示已禁用")
            return
        if not self.current_dir:
            self.image_label.setText("请先执行数据采集")
            return

        image_dir = Path(self.current_dir) / "streetview_images"
        if not image_dir.exists():
            self.image_label.setText("未找到街景图片目录")
            return

        # 根据下拉框选择对应的角度
        direction_map = {0: "0", 1: "90", 2: "180", 3: "270"}
        angle = direction_map.get(self.direction_combo.currentIndex(), "0")
        image_path = image_dir / f"heading_{angle}.jpg"

        if image_path.exists():
            pixmap = QPixmap(str(image_path))
            if not pixmap.isNull():
                # 缩放图片以适应Label大小
                scaled_pixmap = pixmap.scaled(
                    self.image_label.size(), 
                    Qt.AspectRatioMode.KeepAspectRatio, 
                    Qt.TransformationMode.SmoothTransformation
                )
                self.image_label.setPixmap(scaled_pixmap)
            else:
                self.image_label.setText(f"图片损坏: {image_path.name}")
        else:
            jpg_files = list(image_dir.glob("*.jpg"))
            if jpg_files:
                self.image_label.setText(f"未找到 {angle}° 方向图片\n找到的图片: {[f.name for f in jpg_files[:3]]}")
            else:
                self.image_label.setText("该位置无街景覆盖")
                
# ==================== 4. ChartWidget 类 ====================
class ChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_dir = None
        self.enabled = True
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        
        # 控制栏：选择图表类型
        control_layout = QHBoxLayout()
        control_layout.addWidget(QLabel("选择数据:"))
        self.chart_combo = QComboBox()
        self.chart_combo.addItems(["NDVI 时间序列", "地表温度 时间序列", "夜光强度 时间序列"])
        self.chart_combo.currentTextChanged.connect(self.update_chart)
        control_layout.addWidget(self.chart_combo)
        control_layout.addStretch()
        layout.addLayout(control_layout)

        # Matplotlib 画布
        self.figure = Figure(figsize=(8, 4), dpi=80)
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)
        
        self.setLayout(layout)

    def set_enabled(self, enabled):
        self.enabled = enabled
        if not self.enabled:
            self.figure.clear()
            ax = self.figure.add_subplot(111)
            ax.text(0.5, 0.5, "图表显示已禁用\n（采集时未勾选）",
                    ha='center', va='center', transform=ax.transAxes, fontsize=12)
            self.canvas.draw()

    def set_output_dir(self, output_dir):
        self.current_dir = output_dir
        if self.enabled:
            self.update_chart()
        else:
            self.figure.clear()
            ax = self.figure.add_subplot(111)
            ax.text(0.5, 0.5, "图表显示已禁用\n（采集时未勾选）",
                    ha='center', va='center', transform=ax.transAxes, fontsize=12)
            self.canvas.draw()

    def update_chart(self):
        if not self.enabled or not self.current_dir:
            return

        self.figure.clear()
        ax = self.figure.add_subplot(111)
        chart_type = self.chart_combo.currentText()

        try:
            if chart_type == "NDVI 时间序列":
                csv_path = Path(self.current_dir) / "ndvi_stats.csv"
                if csv_path.exists():
                    df = pd.read_csv(csv_path)
                    ax.plot(df['Date'], df['区域NDVI均值'], marker='o', color='green', linewidth=2)
                    ax.set_title("NDVI 时间序列", fontsize=12)
                    ax.set_ylabel("NDVI 值", fontsize=10)
                    ax.tick_params(axis='x', rotation=45, labelsize=8)
                    ax.tick_params(axis='y', labelsize=8)
                    ax.grid(True, linestyle='--', alpha=0.7)

            elif chart_type == "地表温度 时间序列":
                csv_path = Path(self.current_dir) / "lst_stats.csv"
                if csv_path.exists():
                    df = pd.read_csv(csv_path)
                    ax.plot(df['Date'], df['地表温度均值(℃)'], marker='o', color='red', linewidth=2)
                    ax.set_title("地表温度 时间序列", fontsize=12)
                    ax.set_ylabel("温度 (℃)", fontsize=10)
                    ax.tick_params(axis='x', rotation=45, labelsize=8)
                    ax.tick_params(axis='y', labelsize=8)
                    ax.grid(True, linestyle='--', alpha=0.7)

            elif chart_type == "夜光强度 时间序列":
                csv_path = Path(self.current_dir) / "viirs_stats.csv"
                if csv_path.exists():
                    df = pd.read_csv(csv_path)
                    ax.plot(df['Date'], df['夜光均值'], marker='o', color='orange', linewidth=2)
                    ax.set_title("夜光强度 时间序列", fontsize=12)
                    ax.set_ylabel("夜光强度", fontsize=10)
                    ax.tick_params(axis='x', rotation=45, labelsize=8)
                    ax.tick_params(axis='y', labelsize=8)
                    ax.grid(True, linestyle='--', alpha=0.7)

            self.figure.tight_layout()
            self.canvas.draw()

        except Exception as e:
            ax.text(0.5, 0.5, f"无法加载数据:\n{str(e)}",
                    ha='center', va='center', transform=ax.transAxes, fontsize=10)
            self.canvas.draw()
            
# ==================== 5. MapWidget 类 ====================
class MapWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_dir = None
        self.enabled = True
        self.web_view = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        
        # 控制栏：选择图层
        control_layout = QHBoxLayout()
        control_layout.addWidget(QLabel("图层:"))
        self.layer_combo = QComboBox()
        self.layer_combo.addItems(["路网", "建筑", "绿地", "水体"])
        self.layer_combo.currentTextChanged.connect(self.update_map)
        control_layout.addWidget(self.layer_combo)
        control_layout.addStretch()
        layout.addLayout(control_layout)

        # 地图视图
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
        geojson_path = None

        # 根据选择的图层匹配文件名
        if layer_type == "路网":
            geojson_path = Path(self.current_dir) / "roads.geojson"
        elif layer_type == "建筑":
            geojson_path = Path(self.current_dir) / "buildings.geojson"
        elif layer_type == "绿地":
            geojson_path = Path(self.current_dir) / "green_spaces.geojson"
        elif layer_type == "水体":
            geojson_path = Path(self.current_dir) / "water_bodies.geojson"

        print(f"当前图层: {layer_type}")
        print(f"查找文件: {geojson_path}")
        exists = geojson_path.exists() if geojson_path else False
        print(f"文件存在: {geojson_path.exists() if geojson_path else 'N/A'}")
        if not geojson_path or not exists:
           self.web_view.setHtml(f"<h3>未找到 {layer_type} 数据文件</h3><p>路径: {geojson_path}</p>")
           return 
        
    
        try:
            # 读取 GeoJSON
            with open(geojson_path, 'r', encoding='utf-8') as f:
                geojson_str = f.read()

            # 计算中心点（简单取前几个特征的平均坐标）
            data = json.loads(geojson_str)
            features = data.get('features', [])
            print(f"GeoJSON 长度: {len(geojson_str)}")
            if not features:
                self.web_view.setHtml(f"<h3>{layer_type} 数据为空</h3><p>文件存在但无要素数据</p>")
                return

            print(f"GeoJSON 要素数量: {len(features)}")
            
            lons, lats = [], []
            for feat in features[:50]:  # 只取前50个计算中心，避免卡顿
                geom = feat.get('geometry', {})
                geo_type = geom.get('type')
                coords = geom.get('coordinates', [])

                if geo_type == 'Point':
                    lons.append(coords[0])
                    lats.append(coords[1])
                elif geo_type in ('LineString', 'MultiLineString'):
                    lines = coords if geo_type == 'LineString' else [c for line in coords for c in line]
                    for c in lines:
                        if len(c) >= 2:
                            lons.append(c[0])
                            lats.append(c[1])
                elif geo_type in ('Polygon', 'MultiPolygon'):
                    polys = coords[0] if geo_type == 'Polygon' else [c for poly in coords for c in poly[0]]
                    for c in polys:
                        if len(c) >= 2:
                            lons.append(c[0])
                            lats.append(c[1])
            
            if lons and lats:
                center_lat = sum(lats) / len(lats)
                center_lon = sum(lons) / len(lons)
            else:
                # 如果提取失败，使用查询点
                center_lat, center_lon = 39.9055, 116.3912 
            
            # 生成 Folium 地图
            m = folium.Map(location=[center_lat, center_lon], zoom_start=13)
            folium.GeoJson(geojson_str, name=layer_type).add_to(m)
            m.save(temp_path := Path(self.current_dir) / f"temp_map_{layer_type}.html")
            
            # 在 Qt 中显示
            self.web_view.setUrl(QUrl.fromLocalFile(str(temp_path.absolute())))

        except Exception as e:
            error_html = f"""
            <html><body style="font-family: Arial; padding: 20px;">
                <h3>地图加载失败</h3><p>错误: {str(e)}</p>
            </body></html>
            """
            self.web_view.setHtml(error_html)
            
# ==================== 6. MainWindow 主窗口 ====================
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.output_dirs = []
        self.current_index = 0
        self.settings = QSettings("MyCompany", "UrbanAnalysisApp")
        self.init_ui()
        self.worker = None
        self.load_history() # 初始化时加载历史

    def init_ui(self):
        self.setWindowTitle("面向城市街道环境的大数据采集与分析平台")
        self.resize(1400, 900)

        main_layout = QHBoxLayout(self) # 注意这里的 self

        # ----- 左侧：历史记录面板 -----
        left_panel = QWidget()
        left_panel.setFixedWidth(260)
        left_layout = QVBoxLayout(left_panel)

        history_label = QLabel("📜 历史记录")
        history_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        left_layout.addWidget(history_label)

        self.history_list = QListWidget()
        self.history_list.itemClicked.connect(self.on_history_clicked)
        left_layout.addWidget(self.history_list)

        clean_btn = QPushButton("🗑️ 清理30天前数据")
        clean_btn.clicked.connect(self.clean_old_data)
        left_layout.addWidget(clean_btn)

        left_layout.addStretch()
        main_layout.addWidget(left_panel)

        # ----- 右侧：主内容区 -----
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        # --- 1. API 配置 ---
        api_group = QGroupBox("🔑 API 服务配置")
        api_layout = QGridLayout()
        
        # 这里为了兼容你的 main1.py，我们只保留 OpenWeather 和 GEE 路径，去掉高德等
        self.weather_key_input = QLineEdit()
        self.weather_key_input.setPlaceholderText("OpenWeatherMap Key")
        self.weather_key_input.setText(self.settings.value("keys/weather_key", ""))
        
        self.gee_key_input = QLineEdit()
        self.gee_key_input.setPlaceholderText("GEE JSON 路径 (可选)")
        self.gee_key_input.setText(self.settings.value("keys/gee_key", ""))
        
        self.baidu_key_input = QLineEdit()
        self.baidu_key_input.setPlaceholderText("百度地图 AK (用于街景)")
        self.baidu_key_input.setText(self.settings.value("keys/baidu_key", ""))

        api_layout.addWidget(QLabel("OpenWeather Key:"), 0, 0)
        api_layout.addWidget(self.weather_key_input, 0, 1)
        api_layout.addWidget(QLabel("GEE 密钥路径:"), 1, 0)
        api_layout.addWidget(self.gee_key_input, 1, 1)
        api_layout.addWidget(QLabel("百度地图 AK:"), 2, 0)
        api_layout.addWidget(self.baidu_key_input, 2, 1)
        api_group.setLayout(api_layout)
        right_layout.addWidget(api_group)

        # --- 2. 采集选项 ---
        data_group = QGroupBox("📦 数据采集选项")
        data_layout = QHBoxLayout()
        self.check_air = QCheckBox("空气质量")
        self.check_street = QCheckBox("街景图像")
        self.check_gee = QCheckBox("GEE 遥感")
        self.check_osm = QCheckBox("路网数据")
        self.check_chart = QCheckBox("自动图表")
        for cb in [self.check_air, self.check_street, self.check_gee, self.check_osm, self.check_chart]:
            cb.setChecked(True)
            data_layout.addWidget(cb)
        data_group.setLayout(data_layout)
        right_layout.addWidget(data_group)

        # --- 3. 表格与参数（核心输入区） ---
        input_group = QGroupBox("📍 采集点位与参数")
        input_layout = QVBoxLayout()

        # 日期和半径
        param_layout = QHBoxLayout()
        param_layout.addWidget(QLabel("开始日期:"))
        self.start_date = QDateEdit(calendarPopup=True)
        self.start_date.setDate(datetime.now().replace(year=datetime.now().year - 1))
        param_layout.addWidget(self.start_date)
        
        param_layout.addWidget(QLabel("结束日期:"))
        self.end_date = QDateEdit(calendarPopup=True)
        self.end_date.setDate(datetime.now())
        param_layout.addWidget(self.end_date)
        
        param_layout.addWidget(QLabel("默认半径(m):"))
        self.radius_spin = QSpinBox()
        self.radius_spin.setRange(100, 50000)
        self.radius_spin.setValue(500)
        param_layout.addWidget(self.radius_spin)
        input_layout.addLayout(param_layout)

        # 表格
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["经度", "纬度", "半径(m)", "备注"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        input_layout.addWidget(self.table)

        # 表格按钮
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("添加行")
        add_btn.clicked.connect(self.add_table_row)
        del_btn = QPushButton("删除行")
        del_btn.clicked.connect(self.remove_table_row)
        clr_btn = QPushButton("清空")
        clr_btn.clicked.connect(self.clear_table)
        imp_csv = QPushButton("导入CSV")
        imp_csv.clicked.connect(self.import_csv_data)
        imp_txt = QPushButton("导入TXT")
        imp_txt.clicked.connect(self.import_txt_data)
        for b in [add_btn, del_btn, clr_btn, imp_csv, imp_txt]:
            btn_layout.addWidget(b)
        input_layout.addLayout(btn_layout)
        input_group.setLayout(input_layout)
        right_layout.addWidget(input_group)

        # --- 4. 控制按钮 ---
        ctrl_layout = QHBoxLayout()
        start_btn = QPushButton("▶ 开始采集")
        stop_btn = QPushButton("■ 停止采集")
        export_btn = QPushButton("💾 导出当前数据")
        start_btn.clicked.connect(self.start_tasks)
        stop_btn.clicked.connect(self.stop_tasks)
        export_btn.clicked.connect(self.export_current_data)
        ctrl_layout.addWidget(start_btn)
        ctrl_layout.addWidget(stop_btn)
        ctrl_layout.addStretch()
        ctrl_layout.addWidget(export_btn)
        right_layout.addLayout(ctrl_layout)

        # --- 5. 进度条 ---
        self.progress = QProgressBar()
        right_layout.addWidget(self.progress)

        # --- 6. Tab 展示区 ---
        self.tab_widget = QTabWidget()
        self.street_view = StreetViewWidget()
        self.chart_view = ChartWidget()
        self.map_view = MapWidget()
        self.air_quality_view = AirQualityWidget()
        
        self.tab_widget.addTab(self.street_view, "📸 街景展示")
        self.tab_widget.addTab(self.chart_view, "📊 遥感图表")
        self.tab_widget.addTab(self.map_view, "🗺️ 地图展示")
        self.tab_widget.addTab(self.air_quality_view, "🌬️ 空气质量")
        right_layout.addWidget(self.tab_widget)

        # --- 7. 导航与日志 ---
        nav_layout = QHBoxLayout()
        prev_btn = QPushButton("⬅ 上一条")
        next_btn = QPushButton("下一条 ➡")
        self.result_label = QLabel("暂无结果")
        prev_btn.clicked.connect(self.show_prev)
        next_btn.clicked.connect(self.show_next)
        nav_layout.addWidget(prev_btn)
        nav_layout.addWidget(self.result_label)
        nav_layout.addWidget(next_btn)
        right_layout.addLayout(nav_layout)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(120)
        right_layout.addWidget(QLabel("📝 运行日志"))
        right_layout.addWidget(self.log_box)

        main_layout.addWidget(right_panel)

    # ==================== MainWindow 方法定义 ====================
    
    def add_table_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        # 默认值
        self.table.setItem(row, 0, QTableWidgetItem("116.3912"))
        self.table.setItem(row, 1, QTableWidgetItem("39.9055"))
        self.table.setItem(row, 2, QTableWidgetItem(str(self.radius_spin.value())))
        self.table.setItem(row, 3, QTableWidgetItem("手动输入"))

    def remove_table_row(self):
        if self.table.rowCount() > 0:
            self.table.removeRow(self.table.rowCount() - 1)

    def clear_table(self):
        self.table.setRowCount(0)

    def import_csv_data(self):
        # 这里复用你之前的 CSV 导入逻辑
        file_path, _ = QFileDialog.getOpenFileName(self, "选择CSV文件", "", "CSV Files (*.csv)")
        if not file_path: return
        try:
            df = pd.read_csv(file_path, encoding='utf-8')
            self.table.setRowCount(0)
            for _, row in df.iterrows():
                r = self.table.rowCount()
                self.table.insertRow(r)
                self.table.setItem(r, 0, QTableWidgetItem(str(row.get('lon', ''))))
                self.table.setItem(r, 1, QTableWidgetItem(str(row.get('lat', ''))))
                self.table.setItem(r, 2, QTableWidgetItem(str(row.get('radius', self.radius_spin.value()))))
                self.table.setItem(r, 3, QTableWidgetItem("来自CSV"))
            self.log_box.append(f"✅ 导入 {len(df)} 条")
        except Exception as e:
            self.log_box.append(f"❌ CSV导入失败: {e}")

    def import_txt_data(self):
        # 这里复用你之前的 TXT 导入逻辑
        file_path, _ = QFileDialog.getOpenFileName(self, "选择TXT文件", "", "Text Files (*.txt)")
        if not file_path: return
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            self.table.setRowCount(0)
            count = 0
            for line in lines:
                parts = line.strip().split(',')
                if len(parts) >= 2:
                    r = self.table.rowCount()
                    self.table.insertRow(r)
                    self.table.setItem(r, 0, QTableWidgetItem(parts[0]))
                    self.table.setItem(r, 1, QTableWidgetItem(parts[1]))
                    self.table.setItem(r, 2, QTableWidgetItem(parts[2] if len(parts)>2 else str(self.radius_spin.value())))
                    self.table.setItem(r, 3, QTableWidgetItem("来自TXT"))
                    count += 1
            self.log_box.append(f"✅ 导入 {count} 条")
        except Exception as e:
            self.log_box.append(f"❌ TXT导入失败: {e}")

    def start_tasks(self):
        # 保存设置
        self.settings.setValue("keys/weather_key", self.weather_key_input.text())
        self.settings.setValue("keys/gee_key", self.gee_key_input.text())
        self.settings.setValue("keys/baidu_key", self.baidu_key_input.text())
        # 读取选项
        enable_air = self.check_air.isChecked()
        enable_street = self.check_street.isChecked()
        enable_gee = self.check_gee.isChecked()
        enable_osm = self.check_osm.isChecked()
        enable_chart = self.check_chart.isChecked()

        # 启用/禁用组件
        self.street_view.set_enabled(enable_street)
        self.chart_view.set_enabled(enable_chart and enable_gee)
        self.map_view.set_enabled(enable_osm)
        self.air_quality_view.set_enabled(enable_air)

        # 收集任务
        tasks = []
        for row in range(self.table.rowCount()):
            try:
                lon = float(self.table.item(row, 0).text())
                lat = float(self.table.item(row, 1).text())
                r = int(float(self.table.item(row, 2).text()))
                sd = self.start_date.date().toString("yyyy-MM-dd")
                ed = self.end_date.date().toString("yyyy-MM-dd")
                tasks.append((lon, lat, r, sd, ed))
            except:
                self.log_box.append(f"第 {row+1} 行数据有误")
                return

        if not tasks:
            self.log_box.append("请添加采集点")
            return

        self.output_dirs.clear()
        self.current_index = 0
        self.progress.setValue(0)
        self.log_box.append(f"🚀 开始处理 {len(tasks)} 个任务...")

        # 启动 Worker
        self.worker = Worker(
            tasks, 
            self.baidu_key_input.text(),
            self.weather_key_input.text(),
            self.gee_key_input.text(),
            enable_air, enable_street, enable_gee, enable_osm
        )
        self.worker.log.connect(self.log_box.append)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.result_ready.connect(self.on_result_ready)
        self.worker.finished.connect(self.on_all_finished)
        self.worker.start()

    def stop_tasks(self):
        if self.worker and self.worker.isRunning():
            self.log_box.append("🛑 正在停止...")
            self.worker.stop() # 调用我们之前写的 stop 方法
            self.worker.wait()
            self.log_box.append("✅ 已停止")

    def export_current_data(self):
        if not self.output_dirs:
            QMessageBox.information(self, "提示", "没有可导出的数据")
            return
        # 简单实现：打开文件夹
        current_dir = self.output_dirs[self.current_index]
        QDesktopServices.openUrl(QUrl.fromLocalFile(current_dir))

    def on_result_ready(self, output_dir):
        self.output_dirs.append(output_dir)
        self.current_index = len(self.output_dirs) - 1
        self.update_result_display()

    def on_all_finished(self):
        self.log_box.append("🎉 所有任务完成！")

    def update_result_display(self):
        if not self.output_dirs:
            self.result_label.setText("暂无结果")
            return
        current_dir = self.output_dirs[self.current_index]
        self.result_label.setText(f"结果 {self.current_index+1}/{len(self.output_dirs)}: {Path(current_dir).name}")
        self.street_view.set_output_dir(current_dir)
        self.chart_view.set_output_dir(current_dir)
        self.map_view.set_output_dir(current_dir)
        self.air_quality_view.set_output_dir(current_dir)

    def show_prev(self):
        if self.output_dirs:
            self.current_index = (self.current_index - 1) % len(self.output_dirs)
            self.update_result_display()

    def show_next(self):
        if self.output_dirs:
            self.current_index = (self.current_index + 1) % len(self.output_dirs)
            self.update_result_display()

    def load_history(self):
        self.history_list.clear()
        folders = sorted(glob.glob("output_*"), key=os.path.getmtime, reverse=True)
        for folder in folders:
            item = QListWidgetItem(os.path.basename(folder))
            item.setData(Qt.ItemDataRole.UserRole, folder)
            self.history_list.addItem(item)

    def on_history_clicked(self, item):
        folder = item.data(Qt.ItemDataRole.UserRole)
        if os.path.exists(folder):
            self.output_dirs = [folder]
            self.current_index = 0
            self.update_result_display()
            self.log_box.append(f"📂 加载历史: {folder}")
        else:
            self.log_box.append("❌ 文件夹不存在")

    def clean_old_data(self):
        reply = QMessageBox.question(self, "确认", "确定清理30天前数据？", 
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            # 这里简单实现，你可以完善
            self.log_box.append("🧹 清理完成（待完善具体逻辑）")

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait(3000)
        event.accept()

# ==================== 程序入口 ====================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())