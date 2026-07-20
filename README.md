# 面向城市街道环境的大数据采集与分析平台

基于多源城市大数据的街道环境采集、分析与可视化平台。整合空气质量、百度街景、GEE 遥感影像和 OpenStreetMap 矢量数据，提供一站式的城市环境数据采集与展示功能。

## 功能特性

- 🌬️ **空气质量** — 通过 OpenWeatherMap API 获取实时 AQI 与污染物浓度
- 📸 **街景采集** — 调用百度全景静态图 API 下载四方向街景图片
- 🛰️ **GEE 遥感** — 获取 VIIRS 夜光、Sentinel-2 NDVI、Landsat 8 地表温度时间序列
- 🗺️ **OSM 矢量** — 下载路网、建筑、绿地、水体等 OpenStreetMap 矢量数据
- 📊 **交互式可视化** — 时间序列图表、Folium 地图图层、街景浏览、空气质量面板
- 📋 **批量采集** — 支持多点位批量采集，CSV/TXT 导入坐标
- 📝 **日志与导出** — 自动记录日志文件，支持导出 HTML 综合数据报告

## 系统要求

- Python 3.10+
- Google Earth Engine 账号（遥感数据采集需要）

## 安装

```bash
# 克隆仓库
git clone <repo-url>
cd code中期汇报

# 使用 uv 安装依赖（推荐）
uv sync

# 或使用 pip
pip install -r requirements.txt
```

## 配置 API 密钥

启动应用后，在 "API 服务配置" 区域填写：

| 服务 | 说明 |
|------|------|
| OpenWeatherMap Key | 在 [openweathermap.org](https://openweathermap.org/api) 注册获取 |
| GEE 密钥路径 | Google Earth Engine 服务账号 JSON 密钥文件路径（可选，默认使用本地凭证） |
| 百度地图 AK | 在 [百度地图开放平台](https://lbsyun.baidu.com/) 申请，用于街景功能 |

密钥会自动保存，下次启动无需重新输入。

## 运行

```bash
cd code中期汇报
python app.py
```

### 命令行模式（无需 GUI）

```bash
cd code中期汇报
python pipeline.py
```

在 `pipeline.py` 底部的 `__main__` 块中修改测试坐标和 API 密钥后即可直接运行采集管线。

## 使用流程

1. **配置 API 密钥** — 填入所需服务的 API Key
2. **设置采集选项** — 勾选需要采集的数据类型
3. **添加采集点** — 手动输入经纬度，或通过 CSV/TXT 导入
4. **开始采集** — 点击"开始采集"，等待数据下载完成
5. **浏览结果** — 切换 Tab 查看街景、图表、地图、空气质量
6. **导出报告** — 点击"导出当前数据"生成 HTML 报告

## 项目结构

```
code中期汇报/
├── app.py                 # 应用入口
├── pipeline.py            # 核心采集管线
├── config.py              # 全局配置常量
├── utils.py               # 工具函数（日志、文件）
├── pyproject.toml         # 项目元数据与依赖
├── ui/
│   ├── __init__.py
│   ├── main_window.py     # 主窗口
│   ├── worker.py          # 后台采集线程
│   └── widgets/
│       ├── air_quality_widget.py   # 空气质量面板
│       ├── chart_widget.py         # 遥感图表
│       ├── map_widget.py           # OSM 地图
│       └── streetview_widget.py    # 街景展示
├── plugins/
│   ├── air_quality_plugin.py  # OpenWeatherMap 空气质量
│   ├── gee_plugin.py          # GEE 遥感数据
│   ├── osm_plugin.py          # OSM 矢量数据
│   └── streetview_plugin.py   # 百度街景
├── logs/                  # 运行日志（自动生成）
└── output_*/              # 采集数据输出（自动生成）
```

## 数据来源

| 数据 | 来源 | 说明 |
|------|------|------|
| 空气质量 | OpenWeatherMap Air Pollution API | AQI 及 PM2.5、PM10、NO₂ 等 |
| 街景图像 | 百度全景静态图 API | 0°/90°/180°/270° 四个方向 |
| 夜光遥感 | NOAA VIIRS DNB | 月度夜间灯光辐射 |
| NDVI | Sentinel-2 MSI (Harmonized) | 10m 分辨率植被指数 |
| 地表温度 | Landsat 8 Collection 2 Tier 1 | ST_B10 波段反演 |
| 矢量地图 | OpenStreetMap + osmnx | 路网/建筑/绿地/水体 |

## 许可证

本项目仅供学术研究与学习使用。
