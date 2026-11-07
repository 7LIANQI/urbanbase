# CLAUDE.md — 城市街道环境大数据采集与分析平台

## 项目概述

基于 PyQt6 的桌面端多源城市环境数据采集与分析平台。整合空气质量（OpenWeatherMap）、百度街景、GEE 遥感（VIIRS/Sentinel-2/Landsat/ERA5/CHIRPS/SRTM/WorldPop）和 OSM 矢量数据。

## 技术栈

- **语言**: Python ≥3.11
- **GUI**: PyQt6 + PyQt6-WebEngine（Folium 地图嵌入）
- **地理空间**: geopandas, shapely, osmnx, folium
- **遥感**: Google Earth Engine Python API (`earthengine-api`)
- **数据处理**: pandas, matplotlib, requests
- **包管理**: uv (锁文件: `uv.lock`)
- **构建**: hatchling

## 架构

```
app.py              → 入口，Qt 初始化 + Matplotlib 中文配置，启动 ui/shell.py 的 ShellWindow
core/               → 内核：plugin.py（Plugin 基类/发现/AppContext）、logbus.py（日志总线）、theme.py（Google 风格主题）、icons.py（内置 SVG 图标）
modules/            → 工具插件（download/match/analysis/manage 四类），每个 Plugin 子类自动出现在「工具箱」与菜单，点击后在独立工具窗口打开；
                      也可在 ~/.urbansense/plugins/ 放 .py 作为用户插件
ui/shell.py         → 主窗口（QGIS/ENVI 风格）：菜单+工具栏+图层面板+地图画布+工具箱+日志面板，工程(.usproj)存取
ui/map_canvas.py    → 地图画布（matplotlib，统一 EPSG:4326，矢量/GeoTIFF，平移缩放）；ui/layers_panel.py 图层面板（符号化/属性表）
plugins/gee_catalog.py → GEE 数据源目录（按指标类别分组，每类多个可选来源，含说明与链接；设置 → GEE 数据源 中全局选择）
plugins/local_extract.py → 本地栅格库点位提取引擎（窗口读取 COG，口径与 GEE 提取一致；序列的 scale/offset/nodata/categorical 在 dataset.json 里设置）
plugins/gee_extract.py → 点位指标提取引擎（无界面，分批请求 GEE 并合并 CSV）
core/raster_catalog.py → 栅格数据目录（每个数据序列一个文件夹 + dataset.json；命名规则、缺期/重复/范围/文件头一致性检查）
core/cog.py → 批量转 COG（含从文件名识别日期、补坐标系/无效值）
ui/toolbox.py、tool_dialog.py、pages/ → 工具箱、工具窗口外壳、日志页与选项对话框
                      旧版 ui/main_window.py 的 MainWindow 作为隐藏的采集引擎，面板由 ctx.legacy_part() 拆给各工具复用
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
  raster_to_roads_window.py → 栅格值路网赋值工具（菜单「工具」打开，独立窗口）
  widgets/          → 6 个展示组件
core/config.py      → API 端点 / LST 常量 / AQI 颜色 / 污染物名称
core/utils.py       → 日志器 / 重试装饰器 / 密钥混淆 / 安全调用
ui/styles.py        → 暗色/亮色主题样式表
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
python collectors/pipeline.py

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
