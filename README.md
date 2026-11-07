# 城市街道环境大数据采集与分析平台（UrbanSense）

基于 PyQt6 的桌面端多源城市环境数据平台。界面参考 QGIS / ENVI，采用 **插件式架构**，工具箱与菜单里的每个工具都是一个可独立加载的插件。

在原有的数据采集能力之上，本版新增了一条面向环境暴露研究的完整链路：

> **点位表（经纬度 + 观测日期）→ 从 GEE（在线）和本地 COG 栅格库（本地）提取环境暴露指标 → 输出 CSV + GPKG + 一份采集报告**

## 主要功能

### 点位指标提取（本版核心）

- **两种数据来源**，口径完全一致：GEE 在线数据源，以及外置硬盘上的本地 COG 栅格库
- **可配置的提取规则**
  - 缓冲区：不缓冲 / 500 m / 1 km / 自定义
  - 区内合成：均值 / 中值
  - 时间粒度：年 / 月
  - 时间范围：回溯窗口（cur / y1 / y2 / y3 / y5 / y10），或指定时间段序列
  - 时段内合成：中值 / 均值 / 最大 / 最小
  - 坐标系：默认 WGS84（支持 GCJ02 / BD09 输入）
  - **缺期时用最近一期替代**（默认开启，不做插值）
- **追加模式**：输出文件已存在时，原有列不动、新列接在最后，报告按「第 N 次提取」合并
- **输出精简为 3 个文件**：`xxx.csv`、同名 `xxx.gpkg`、`xxx_采集报告.md`
- 采集报告用 Markdown 说明提取设置、缺期替代情况、出错被跳过的数据源、空值占比过高的列及其原因、每个输出字段的含义

### 环境数据采集（原有能力，已并入插件）

- 🌬️ **空气质量** — OpenWeatherMap 实时 AQI 与污染物浓度
- 📸 **街景采集** — 百度全景静态图 API，四个方向
- 🛰️ **GEE 遥感** — VIIRS 夜光、Sentinel-2 NDVI、Landsat 地表温度等时间序列
- 🗺️ **OSM 矢量** — 路网、建筑、绿地、水体
- ☀️ **紫外线** — 本地 netCDF 紫外线年均数据
- 📋 **批量采集** — 支持多点位批量，CSV / TXT 导入坐标

### 数据管理

- **栅格数据目录** — 每个数据序列一个文件夹 + `dataset.json`，支持命名规则、缺期/重复/范围/文件头一致性检查
- **批量转 COG** — tif 与 NetCDF 均可转换，**数值保持原样**（scale / offset 只记在 `dataset.json`）
- **汇总宽表导出** — 指标 × Cur/2y/3y/5y/10y 时间切片，多点合并
- **栅格值路网赋值**、**历史记录查询**

## 系统要求

- Python **3.11+**
- Google Earth Engine 账号（GEE 在线提取需要）
- 可选：本地 PostgreSQL 便携版，用于采集结果落库

## 安装

```bash
git clone https://github.com/7LIANQI/urbanbase.git
cd urbanbase/code

# 使用 uv 安装依赖（推荐）
uv sync

# 或使用 pip
pip install -e .
```

## 配置 API 密钥

启动应用后，在「设置」中填写：

| 服务 | 说明 |
|------|------|
| OpenWeatherMap Key | 在 [openweathermap.org](https://openweathermap.org/api) 注册获取 |
| GEE 密钥路径 | Google Earth Engine 服务账号 JSON 密钥文件路径（可选，默认使用本地凭证） |
| 百度地图 AK | 在 [百度地图开放平台](https://lbsyun.baidu.com/) 申请，用于街景功能 |

密钥会自动保存，下次启动无需重新输入。

## 运行

```bash
cd urbanbase/code
python app.py
```

命令行模式（无需 GUI）：

```bash
python -m collectors.pipeline
```

## 使用流程

界面的组织方式是 **工具箱 + 独立工具窗口**：

1. **环境数据采集** — 在左侧工具箱「数据下载 → 环境数据采集」中配置密钥、添加采集点、开始采集
2. **点位指标提取** — 「数据下载 → 点位指标提取」：选数据源 → 设缓冲区/时间规则 → 选输入点位表 → 开始提取
3. **数据管理** — 「数据管理」分类下做栅格库入库、转 COG、查历史
4. **查看结果** — 地图画布叠加图层，日志面板滚动显示过程

## 项目结构

```
code/
├── app.py                    # 应用入口（Qt 初始化 + 中文 Matplotlib 配置）
├── collectors/              # 多源采集器与命令行采集管线
├── database/                # SQLite 缓存与 PostgreSQL 数据库
├── core/                     # 内核（无界面）
│   ├── config.py             #   API 端点、常量与 PostgreSQL 配置
│   ├── utils.py              #   日志、重试与密钥混淆
│   ├── plugin.py             #   Plugin 基类、自动发现、AppContext
│   ├── theme.py / icons.py   #   Google 极简主题；内置 SVG 图标
│   ├── raster_catalog.py     #   栅格数据目录（Series、dataset.json、一致性检查）
│   ├── cog.py                #   转 COG（tif / NetCDF）
│   ├── crs.py                #   输入坐标系 → WGS84
│   ├── aggregate.py          #   日值 → 月值
│   ├── report.py             #   采集报告（Markdown，可追加合并）
│   └── logbus.py             #   日志总线
├── modules/                  # 工具插件（放入 .py 即自动出现在工具箱）
├── plugins/                  # 采集与提取引擎
│   ├── gee_catalog.py        #   GEE 数据源目录（按指标分组，每类多个来源）
│   ├── gee_extract.py        #   GEE 点位提取引擎
│   ├── local_extract.py      #   本地栅格库提取引擎
│   └── *_plugin.py           #   空气质量 / 天气 / 街景 / GEE / OSM / UV 底层采集
├── ui/
│   ├── shell.py              # 主窗口（菜单 + 工具栏 + 图层面板 + 地图 + 工具箱 + 日志）
│   ├── map_canvas.py         # 地图画布（matplotlib，统一 EPSG:4326）
│   ├── layers_panel.py       # 图层面板（符号化 / 属性表）
│   ├── toolbox.py            # 工具箱
│   ├── tool_dialog.py        # 工具窗口外壳
│   ├── pages/                # 各工具的界面页
│   └── main_window.py        # 旧版主窗口，现作为隐藏的采集引擎
├── scripts/                  # 建 COG 库、整理数据、日转月、GEE 自检
├── tests/                    # 测试
└── uv.lock                   # 依赖锁文件
```

## 数据来源

| 数据 | 来源 | 说明 |
|------|------|------|
| 空气质量 | OpenWeatherMap Air Pollution API | AQI 及 PM2.5、PM10、NO₂ 等 |
| 街景图像 | 百度全景静态图 API | 0°/90°/180°/270° 四个方向 |
| 夜光遥感 | NOAA VIIRS DNB | 月度夜间灯光辐射 |
| NDVI | Sentinel-2 MSI (Harmonized) | 10 m 分辨率植被指数 |
| 地表温度 | Landsat 8/9 Collection 2 | ST_B10 波段反演 |
| 气温 / 降水 / 辐射 | ERA5-Land、TerraClimate | 再分析与融合产品 |
| 土地覆盖 / 树木覆盖 | ESA WorldCover、Hansen GFC | |
| 人口 | WorldPop | |
| 行政区划 | 本地中国省/市/县矢量 | 三级一致，用县代码查表 |
| 矢量地图 | OpenStreetMap + osmnx | 路网 / 建筑 / 绿地 / 水体 |

GEE 数据源目录（`plugins/gee_catalog.py`）按指标分组，每类提供多个可选来源，可在「设置 → GEE 数据源」中全局选择。

## 本地数据 (PostgreSQL)

平台支持把采集结果持久化到本地 PostgreSQL 库，并按坐标查询历史数据。

- **写**：每次采集结束后自动落库（采集记录、数值指标、OSM 矢量、文件引用）
- **读**：「本地数据」工具可按经纬度查询历史采集、手动查询、导入 CSV

### 环境准备

PostgreSQL 采用便携版二进制（免安装、免管理员），默认装在 `D:\PostgreSQL17`：

```bash
# 启动 / 停止
scripts\pg_start.bat
scripts\pg_stop.bat
# 首次初始化（仅当 data 目录不存在时）
scripts\pg_init.bat
```

默认连接（`core/config.py` 中可改，界面也可配置）：`localhost:5432`，库 `urban_analysis`，用户 / 密码 `postgres / postgres`。

首次使用时点「初始化表」创建数据库表。

## 本地栅格库

本地环境数据放在外置硬盘的 `环境数据/` 下：

- `完整数据/` — 原始数据，**不删不改数值**
- `COG库/` — 转换后的库，每个数据序列一个文件夹，内含 `dataset.json` 描述
  （`id name category product variable unit temporal nodata dtype kind attributes` 等字段）

`dataset.json` 里的 `nodata`、`scale`、`offset`、`categorical` 等设置决定数据如何被解释，改动前请确认含义。

## 许可证

本项目仅供学术研究与学习使用。
