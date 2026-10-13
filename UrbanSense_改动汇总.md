# UrbanSense 改动汇总（相对最原始版本）

> 写给接手的 AI：这份文档说明 **我们改了什么、为什么改、中间踩过哪些坑**。
> 最原始版本 = `urbanbase-main.zip`（2026-10-03，一个单体 PyQt6 程序）。现在的版本在 `urbanbase/code/`。
> 用户是眼科研究者，不是程序员；所有界面文字和代码注释用**中文**。

---

## 1. 一句话概括

把一个单体的“街景/空气质量/GEE 采集”桌面程序，改造成 **插件式、QGIS/ENVI 风格** 的平台，并围绕用户的研究需求新增了一条完整的链路：

**点位表（经纬度 + 观测日期）→ 从 GEE（在线）和本地 COG 栅格库（本地）提取环境暴露指标 → 输出 CSV + GPKG + 一份采集报告。**

研究背景：眼健康地图论文，研究点在中国（广州、喀什等），约 8586 + 501 个点，观测年份 2017–2025，缓冲区 1 km。需要气象、辐射、空气污染、植被、社会经济、地形与城乡属性共 130 多个字段（见用户的《环境暴露数据匹配需求表》）。

---

## 2. 文件级改动总览

### 2.1 原有文件（几乎没动）
| 文件 | 改动 |
|---|---|
| `ui/main_window.py`（2988 行） | **改动极小（净增 4 行）**：把四个面板存成属性（`history_panel`、`grp_api`、`grp_options`、`grp_input`），让新界面能把它们拆出来复用。它现在是**隐藏的“采集引擎”**，由 `ctx.legacy_part()` 提供面板 |
| `app.py` | 入口改为 `ShellWindow` + `core.theme.apply()` |
| `pyproject.toml` | `requires-python >=3.11`；新增依赖 `rasterio`、`xarray`、`netCDF4` |
| `CLAUDE.md` | 更新了架构说明 |
| `collectors/`、`plugins/*_plugin.py`、`pipeline.py`、`pg_store.py` 等 | **未改** |

### 2.2 新增（约 50 个文件）
```
core/               内核（无界面或通用）
  plugin.py           Plugin 基类、discover()、AppContext
  logbus.py           日志总线
  theme.py            Google 极简配色 QSS（亮/暗）
  icons.py polish.py  内置 SVG 图标；把旧控件“抹平”成统一样式
  crs.py              输入坐标系 → WGS84（含 GCJ02/BD09）
  cog.py              转 COG（tif + NetCDF 都支持，数值不变）
  raster_catalog.py   栅格数据目录：Series 数据结构、命名规则、一致性检查
  aggregate.py        日值→月值
  report.py           采集报告（Markdown，可追加合并）
  admin_cn.py         省级代码→名称
modules/            工具插件（download/match/analysis/manage 各一个 .py）
ui/
  shell.py            QGIS 风格主窗口（菜单+工具栏+图层面板+地图画布+工具箱+日志）
  map_canvas.py basemap.py layers_panel.py   地图、底图、图层
  toolbox.py tool_dialog.py                  工具箱、工具窗口外壳
  raster_to_roads_window.py                  合并进来的 raster_to_roads（1017 行）
  pages/extract_widget.py   点位指标提取界面（核心）
  pages/catalog_widget.py cog_widget.py settings_dialog.py logs_page.py
  widgets/info_icon.py      “?” 悬停提示控件
plugins/
  gee_catalog.py      GEE 数据源目录（按指标分组，每类多个可选来源）
  gee_extract.py      GEE 点位提取引擎（无界面）
  local_extract.py    本地栅格库提取引擎（无界面）
scripts/              build_cog_library.py organize_env_data.py daily_to_monthly.py diag_gee.py
tests/                8 个测试文件
```

---

## 3. 架构变化

### 3.1 插件化
- 新增一个工具 = 在 `modules/`（或 `~/.urbansense/plugins/`）放一个 `.py`，定义 `Plugin` 子类（`id/title/category/order/icon/description/size/create(ctx)`）。
- `discover()` 自动发现，工具箱和菜单自动出现入口，点击后在**独立工具窗口**打开（懒加载 `create`）。
- 四个分类：数据下载 / 数据匹配 / 数据分析 / 数据管理。现有插件：
  `download.collect`（环境数据采集，复用旧面板）、`download.schedule`、`download.extract`（**点位指标提取**）、`match.raster_to_roads`、`match.local`、`analysis.time`、`manage.history`、`manage.catalog`（栅格数据目录）、`manage.cog`（批量转 COG）。
- `AppContext` 提供：`settings`、`logbus`、`add_layer(path)`、`selected_vector_path()`、`open_settings(page)`、`legacy_part(...)`。

### 3.2 界面约定（用户明确要求过）
- 参考 QGIS/ENVI，**Google 极简风，配色少**。
- 每个工具窗口：按钮放在分组框（QGroupBox）里；底部页脚固定为 **关闭 / 停止 / 主操作**。
- **不用说明性 label**，需要提示就在标题后放一个小的 “?”（`InfoIcon`），鼠标悬停约 1 秒出浮动文字。
- “在线（GEE）/ 本地”用小标签区分；批量勾选：Shift 点击选范围，另有 全选/清空（在线、本地各一组）。
- 关闭程序时后台线程要能快速退出（守护线程 + `shutdown()`），曾出现过关闭卡很久。

---

## 4. 点位指标提取（核心功能）

### 4.1 用户可选项（界面 `extract_widget.py`）
数据源（GEE 指标按类别勾选；本地序列按行勾选）、缓冲区（不缓冲 / 500 m / 1 km / 自定义）、区内合成（均值/中值）、时间粒度（年/月）、时间范围（**回溯窗口** cur/y1/y2/y3/y5/y10，或**时间段序列**）、时段内合成（中值/均值/最大/最小）、坐标系（默认 WGS84）、**缺期时用最近一期替代**（默认开）、**追加到已有的输出文件**。

### 4.2 GEE 引擎设计（`plugins/gee_extract.py`）
- 性能关键：**先把整个数据源按年/月合成成“单位影像”（每个单位只算一次，所有点共用）→ `ee.Image.cat` 叠成多波段 → 每个数据源一次 `reduceRegions` → 在本地按窗口汇总**。旧做法是每个点每个窗口各自合成，会超时/爆内存。
- `tileScale=16`；每批 50 点；批次失败先重试，再**定位出问题的数据源**（逐个单独请求，记入 `info["bad"]`，报告里显示是哪个数据源错了），再对半拆批。
- 点用 `_lon/_lat` 属性重建（`_point(f)`），避免缓冲区在串联 `reduceRegions` 时逐步变大。
- 批次缓存放 `~/.urbansense/cache/`，完整跑完删除；`_pmap` 用守护线程，停止后最多再等 2 秒。
- 数据源目录 `gee_catalog.py`：每类多个来源（植被/水体/地表温度/气温/降水/太阳辐射/夜光/人口/土地覆盖/树木覆盖/DEM/城乡分类）。ERA5-Land 标“模式数据”，TerraClimate 标“融合”。已删除：在线行政区划（FAO GAUL 与中国海岸线不符，改用本地矢量）、土壤温度、NO₂/AOD/地表水。
- `FIELD_DESC` + `describe(col)`：每个输出字段一句话中文说明（给报告用）。

### 4.3 本地库引擎（`plugins/local_extract.py`）
- 语义与 GEE **完全一致**：窗口内各年/月先合成、再跨期合成、最后空间聚合；`nodata`、`scale/offset`、分类数据（取众数）都按序列的 `dataset.json` 处理。
- 读取一律用 **窗口读 COG**，不整图读入；点在栅格外、窗口内全是无效值、无数据文件，会分别记入诊断（`reason`）。
- 矢量序列（`kind: vector`）：`geopandas.sjoin` 点在面内；不在面内且设了 `nearest_m` 时取就近面（用 pyproj `Geod` 算实际距离）。

### 4.4 缺期处理：最近一期替代（用户的明确决定）
- 窗口内有数据的单位照常平均，**缺的单位不参与**（例：前 3 年 2022–2024 只有 2022、2023，就只平均这两年）。
- **整个窗口一个单位都没有时**，改用离窗口最近的一期（前后等距取较早的），**不插值**；记录“替代点数、偏差年数”，写入报告。
- 本地：`nearest_unit()`，不设上限。GEE：`pad_units()` 在窗口范围前后各多取 2 年单位，`windows_from_units(..., fill=True)` 里挑最近的；超出的仍为空。
- 起因：用户先说“不做插值”，后来说“缺失的直接用最近的数据代替，这样就彻底消除缺失”。

### 4.5 输出文件（用户嫌太多后精简）
现在一次提取只产生 **3 个文件**：`xxx.csv`、同名 `xxx.gpkg`、`xxx_采集报告.md`。
- 去掉了：`_gee.csv` 中间文件（放系统临时目录）、`_提取设置.json`（并入报告）、`_采集报告.csv`、输出目录里的 `_cache_*`（移到 `~/.urbansense/cache` 且自动清理）。
- **追加模式**：输出文件已存在时，原有列不动，新列接在最后（同名列原位更新）；gpkg 每次从合并后的 CSV 重生成；报告按“第 N 次提取”合并（`report_blocks / merge_reports`）；行数不一致则拒绝。
- 原有输入列顺序保持；输入表里已有同名列时 GEE 路径会覆盖（避免 `_x/_y`）。

### 4.6 采集报告（`core/report.py`）
Markdown：提取设置 → 缺期处理规则（只写一遍）→ 每次提取一节（替代情况表、出错被跳过的数据源、空值>50% 的列及原因、各列有值/空值、字段说明、本地序列覆盖范围）。

---

## 5. 数据层（外置硬盘 `/Volumes/My Passport/环境数据/`）

### 5.1 目录
- `完整数据/`：用户原始数据（已按序列整理命名；`_压缩包备份`、`_整理记录` 里有可回滚日志）。**原始数据不删、不改数值。**
- `COG库/`：转换后的库，每个**数据序列一个文件夹 + `dataset.json`**。分类目录：`admin airq forest gdp precip rhum sunshine t2m uv`。`_整理记录/` 记录每次入库的旧路径→新路径；根目录有 `数据清单.csv`、`README.md`。

### 5.2 命名与 `dataset.json`（`core/raster_catalog.py`）
- 文件名 `<id>_<YYYY|YYYYMM|YYYYMMDD>.<ext>`；静态为 `<id>.<ext>`。
- `Series` 字段：`id name category product variable unit temporal(static/year/month/day) start end check_gaps kind(raster/vector) attributes nearest_m categorical multi_grid crs resolution nodata dtype scale offset source link notes`。
- `nodata`：空串=用文件自带；`"none"`=不屏蔽；否则为数值。`attributes`：输出列→表达式，如 `gb[3:9]`、`gb[3:5]|table:province`（查同目录 `lookup_*.csv`）。
- 一致性检查 `RC.check(root, deep)`：缺期/重复/范围/文件头与声明不一致。

### 5.3 COG 转换（`core/cog.py`、`scripts/build_cog_library.py`）
- **数值保持原样**（用户说“先不改数值”）：不缩放、不换单位；scale/offset 只记在 `dataset.json`。
- tif 与 NetCDF 都支持；NetCDF 用 `xarray(mask_and_scale=False)`，纬度升序翻转；默认目标坐标系 WGS84。
- exFAT 注意：大小写不敏感（`GDP`/`gdp` 曾冲突）、会产生 `._xxx` AppleDouble 文件（入库后要清理）。

### 5.4 已入库的序列
空气污染 CHAP/ECHAP 11 个；气温、降水（月，≈1 km）；相对湿度 CMFD（年）；日照时数（月，由日值平均）；GDP（年份不连续：2010、2015、2020–2024）；中国森林覆盖/森林增减/PFT（China Forest Dataset v1.0）；中国省/市/县行政区划矢量（用户提供，CGCS2000）；紫外线年均（2010–2023，0.1°）。

### 5.5 行政区划（省/市/县/县代码）
- 县级矢量 `china_county` 的字段只有 `name`、`gb`（9 位）。输出 `CN_PROV`、`CN_CITY`、`CN_COUNTY`、`CN_COUNTY_GB`。
- 省名、市名**不重新做空间匹配**，而是用县代码查表（`lookup_province.csv`：`gb[3:5]`；`lookup_city.csv`：`gb[3:7]`），保证三级一致。
- 直辖市的“市”取市名；省直辖县级单位（济源、仙桃、海南各县市等）的“市”写“省直辖县级行政区划”。

### 5.6 数据里已发现的问题（别当成 bug 重复排查）
- `pre_cn1km` 1996 年 11–12 月源文件为 0（不完整，转换时跳过）。
- 日照时数日值源数据缺 21 天；范围 80–135°E，**不含喀什**。
- GDP 各年网格/类型不同（2010 float32，之后 int32），已开 `multi_grid`。
- 森林增加/损失里 **0 表示“没发生”**，但 `nodata` 设成了 0，导致整列几乎全空（**待改为 `"none"`，用户尚未确认**）。
- PFT 只含森林类型，非森林像元为 −128，城区点为空是真实情况。
- 气温/降水/日照的单位（0.1 ℃ / 0.1 mm 等）**用户确认不乘 0.1，保持原值**（scale=1.0）。
- 紫外线 tif 无 nodata，海域/境外为 0（已在 COG 头标 nodata=0）；来源/单位按推断，待数据提供方确认。

---

## 6. 踩过的坑（及原因）

| 现象 | 原因 | 处理 |
|---|---|---|
| GEE `User memory limit exceeded` | 每点每窗口各自合成 | 改为“先按年/月合成单位影像再提取”，`tileScale=16`，自适应拆批 |
| GEE 400 / 不知哪个数据源出错 | 一次请求混了多个数据源 | `probe()` 逐个数据源定位，报告显示出错的数据源 |
| 缓冲区越串越大 | 串联 `reduceRegions` 后几何变成了缓冲区 | `_point(f)` 从 `_lon/_lat` 重建点 |
| 某些数据源整列为空且不报错 | **`reduceRegions` 对单波段影像把属性命名为 `mean`（归约器名），不是波段名** | `_multi()` 补占位波段 `padband`（注意：波段名不能以下划线开头）。Hansen 树冠覆盖、时间段序列的单列数据源都因此全空 |
| 本地提取月序列特别慢（每序列 ~90 s） | 每线程只缓存 48 个已打开文件，月序列一个点要用几十个文件 → 缓存抖动，外置硬盘上反复打开 | 缓存上限 200，并调高系统文件描述符上限（`_fd_limit()`）。518 点 × 25 个序列从 ~210 s 降到 ~42 s |
| 全部结果为空，地图加载 `aspect must be finite` | 经纬度列没自动识别（列名 `" 经度_wgs84"` 带空格和后缀），默认选成了第一列“序号”，点被放到 (1,1) | `guess_column()` 子串匹配；运行前校验经纬度列（同列/有效值<80% 拦截）；gpkg 过滤无效坐标 |
| 报告生成 `cannot convert float NaN to integer` | 无诊断的列（GEE 时间段序列）整列为空时 `int(NaN)` | 报告里先判断 `pd.notna` |
| 在线 FAO GAUL 与中国海岸线不符、点判定出错 | 境外边界数据与中国实际不一致 | 删掉在线行政区划，改用用户提供的本地中国省/市/县矢量 |
| PyQt 测试挂起 | `QMessageBox` 阻塞 offscreen 测试 | 测试里替换掉 `QMessageBox` |

---

## 7. 运行与测试

```bash
cd urbanbase/code
.venv/bin/python app.py            # 用户终端里没有 uv 命令时用这个
uv sync                            # 安装依赖（有 uv 时）
```
- `.venv` 里**没有 pytest**。测试是直接调用 `test_*` 函数（带 `tmp_path` 的传一个临时目录；用 `monkeypatch` 的 `test_gee_flow` 需要一个简单替身）。
- 无界面测试加 `QT_QPA_PLATFORM=offscreen`；`ui` 包导入前必须先 `QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)`（WebEngine 要求）。
- GEE 联网自检：`.venv/bin/python scripts/diag_gee.py <服务账号 JSON>`（对比时间段序列与回溯窗口两种取法）。
- `tests/test_gee_flow.py` 用**假的 ee 对象**跑完整流程，专门防“变量没定义”这类只有联网才暴露的低级错误。

---

## 8. 目前未完成 / 待用户确认

1. 森林增加/损失 4 个序列的 `nodata` 改为 `"none"`（让 0 表示“没发生”）。
2. PFT 非森林是否输出一个“非森林”编码（现在为空）。
3. 时间窗口：需求表要 `Cur/2y/3y/5y/10y`，目前提取的是 `cur/y1/y3/y5`（没有 10 年，第二个是 1 年）。是否补提。
4. 紫外线数据的准确出处与单位。
5. `Hansen` 树冠覆盖已因“单波段”问题修复，但修复后**还没有单独在 GEE 上验证**（WorldPop 已验证）。
6. 用户的两批提取（`第一批` 8586 点、`第二批` 501 点）的报告已手工合并；之后用“追加”模式即可。

---

## 9. 给后续 AI 的约定

- **不要使用用户的 GEE 服务账号密钥**，除非用户明确要求并运行（本项目里它放在 `数据需求1001/ee-*.json`）。
- **不要删除用户数据**；整理/入库只做移动、改名、转换，并在 `_整理记录/` 留回滚记录。删除任何东西前先列出清单并等用户确认。
- 数值保持原样（除非用户明确要求缩放/换算）。
- 先“问清再动”的事：改变数据含义的设置（nodata、scale、替代规则）。
- 用户偏好：回答简短、先说结论；界面少文字、多用“?”提示；报告要说明数据缺失的原因和处理方式。
- 代码风格：中文注释与界面文本；私有函数 `_leading_underscore`；`process_location()` 签名不可变。
