# CLAUDE.md — 城市街道环境大数据采集与分析平台

## 项目概述

基于 PyQt6 的桌面端多源城市环境数据采集与分析平台。整合空气质量（OpenWeatherMap）、百度街景、GEE 遥感（VIIRS/Sentinel-2/Landsat/ERA5/CHIRPS/SRTM/WorldPop）和 OSM 矢量数据。

## 技术栈

- **语言**: Python ≥3.10
- **GUI**: PyQt6 + PyQt6-WebEngine（Folium 地图嵌入）
- **地理空间**: geopandas, shapely, osmnx, folium
- **遥感**: Google Earth Engine Python API (`earthengine-api`)
- **数据处理**: pandas, matplotlib, requests
- **包管理**: uv (锁文件: `uv.lock`)
- **构建**: hatchling

## 架构

```
app.py              → 入口，Qt 初始化 + Matplotlib 中文配置
pipeline.py         → 核心采集编排器（轻量，遍历 Collector 列表）
collectors/         → 采集器类（每种数据源一个）── NEW
  base.py           → BaseCollector 抽象基类
  air_quality.py    → 空气质量
  weather.py        → 实时天气
  streetview.py     → 百度街景
  gee.py            → GEE 遥感（7 个子模块）
  osm.py            → OSM 矢量数据
plugins/            → 底层数据采集函数（被 collectors 调用）
  air_quality_plugin.py
  weather_plugin.py
  streetview_plugin.py  → 内部 API (mapsv0.bdimg.com)，纯 Python 坐标转换
  gee_plugin.py         → 所有 GEE 数据集
  osm_plugin.py         → osmnx 下载 + 统计计算
ui/
  main_window.py    → 主窗口（1400行，含 API 配置/点位表格/结果弹窗/历史面板）
  worker.py         → QThread 后台采集线程
  widgets/          → 6 个展示组件
config.py           → API 端点 / LST 常量 / AQI 颜色 / 污染物名称
utils.py            → 日志器 / 重试装饰器 / 密钥混淆 / 安全调用
styles.py           → 暗色/亮色主题样式表 ── NEW
```

## 代码风格

- **注释**: 所有注释和用户界面文本使用**中文**
- **命名**: 函数/变量 `snake_case`，类 `PascalCase`，私有函数 `_leading_underscore`
- **日志**: 统一使用 `utils.make_logger(callback)` 创建 log 函数
- **异常**: 网络请求用 `requests.RequestException`，GEE 用 `ee.EEException`，避免裸 `except Exception`
- **重试**: 网络请求使用 `@retry_on_network_error` 装饰器
- **类型标注**: 随加随补，不强制完整覆盖

## 常用命令

```bash
# 运行应用
cd code中期汇报 && python app.py

# 命令行模式（无需 GUI）
python pipeline.py

# 运行测试
python -m pytest tests/ -v

# 安装依赖
uv sync
# 或
pip install -r requirements.txt
```

## 关键约定

- `process_location()` 的签名**不可改变**（向后兼容）
- 采集器通过 `BaseCollector` 基类统一接口: `collect() -> dict`
- 敏感密钥通过 `utils.secure_store/secure_load` 混淆存储
- `QSettings` 组织名 `"MyCompany"`，应用名 `"UrbanAnalysisApp"`
- 输出目录命名: `output_{lon}_{lat}_{radius}m_{YYYYMMDD_HHMMSS}/`
- 街景内部 API 坐标转换链: WGS84 → GCJ02 → BD09 → BD09MC
