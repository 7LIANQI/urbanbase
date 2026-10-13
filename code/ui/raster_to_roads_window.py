"""栅格值路网赋值工具（由 raster_to_roads.py 并入平台，菜单「工具」打开）。
Raster to Road Assignment Tool
Assigns raster values to road segments using length-weighted cell intersection.
"""

import sys
import os
import re
import numpy as np
from pathlib import Path

# Default directory = folder where this script lives
_BASE_DIR = str(Path.home())  # 文件对话框默认目录

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QListWidget, QListWidgetItem,
    QCheckBox, QProgressBar, QGroupBox, QMessageBox, QComboBox,
    QLineEdit, QTextEdit, QDialog, QDialogButtonBox, QFormLayout,
    QAbstractItemView, QFrame, QSizePolicy, QRadioButton, QDoubleSpinBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QIcon



# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

class RasterConfig:
    """Holds configuration for one raster file."""
    def __init__(self, path):
        self.path = path
        self.var_name = None        # nc variable name; None = auto-detect first var
        self.time_idx = -1          # -1 = mean over time, else integer index
        self.field_name = ""        # output shapefile field name (≤10 chars)
        self.algorithm = 'interp'   # 'interp' | 'population'
        self.threshold_km = 2.0     # max distance for population algorithm (km)


# ---------------------------------------------------------------------------
# NC configuration dialog
# ---------------------------------------------------------------------------

class RasterConfigDialog(QDialog):
    """Unified config dialog for both NC and TIF files."""

    def __init__(self, path, parent=None, initial_cfg=None, batch_mode=False):
        super().__init__(parent)
        self.path = path
        self.batch_mode = batch_mode
        is_nc = Path(path).suffix.lower() == '.nc'

        self.setWindowTitle(
            ("NC" if is_nc else "TIF") + " 配置" + ("（批量）" if batch_mode else "")
        )
        self.setMinimumWidth(440)
        self.setMaximumWidth(560)

        # Read NC metadata
        self.vars = []
        self.has_time = False
        self.n_time = 0
        if is_nc:
            try:
                import xarray as xr
                ds = xr.open_dataset(path)
                self.vars = list(ds.data_vars.keys())
                fv = ds[self.vars[0]]
                self.has_time = 'time' in fv.dims
                self.n_time = fv.sizes.get('time', 0) if self.has_time else 0
                ds.close()
            except Exception:
                pass

        cfg = initial_cfg  # may be None on first open

        layout = QFormLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # File name label
        name_lbl = QLabel(f"<b>{Path(path).name}</b>")
        name_lbl.setWordWrap(True)
        layout.addRow("文件:", name_lbl)

        # NC-only: variable + time
        self.var_combo = QComboBox()
        self.time_combo = QComboBox()
        if is_nc:
            self.var_combo.addItems(self.vars or ["(无数据变量)"])
            if cfg and cfg.var_name:
                idx = self.var_combo.findText(cfg.var_name)
                if idx >= 0:
                    self.var_combo.setCurrentIndex(idx)
            layout.addRow("数据变量:", self.var_combo)

            if self.has_time:
                self.time_combo.addItem(f"均值（共 {self.n_time} 时间步）", -1)
                for i in range(self.n_time):
                    self.time_combo.addItem(f"时间步 {i}", i)
                if cfg and cfg.time_idx != -1:
                    self.time_combo.setCurrentIndex(cfg.time_idx + 1)
            else:
                self.time_combo.addItem("无时间维度", -1)
                self.time_combo.setEnabled(False)
            layout.addRow("时间处理:", self.time_combo)

        # Field name
        if batch_mode:
            self.field_edit = QLineEdit()
            hint = QLabel("批量模式：字段名自动按文件名生成")
            hint.setStyleSheet("color:#666;font-size:11px;")
            layout.addRow("字段名:", hint)
        else:
            self.field_edit = QLineEdit()
            self.field_edit.setMaxLength(10)
            self.field_edit.setPlaceholderText("最多 10 字符")
            self.field_edit.setText(
                (cfg.field_name if cfg else None) or Path(path).stem[:10]
            )
            layout.addRow("字段名:", self.field_edit)

        # Algorithm
        self.algo_combo = QComboBox()
        self.algo_combo.addItem("插值均值（长度加权）", "interp")
        self.algo_combo.addItem("人口分配（最近路段）", "population")
        if cfg and cfg.algorithm == 'population':
            self.algo_combo.setCurrentIndex(1)
        self.algo_combo.currentIndexChanged.connect(self._on_algo_changed)
        layout.addRow("算法:", self.algo_combo)

        # Threshold row (shown only for population algorithm)
        self.threshold_widget = QWidget()
        thr_row = QHBoxLayout(self.threshold_widget)
        thr_row.setContentsMargins(0, 0, 0, 0)
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.1, 200.0)
        self.threshold_spin.setValue(cfg.threshold_km if cfg else 2.0)
        self.threshold_spin.setSingleStep(0.5)
        self.threshold_spin.setDecimals(1)
        self.threshold_spin.setSuffix(" km")
        self.threshold_spin.setFixedWidth(100)
        thr_row.addWidget(self.threshold_spin)
        thr_row.addWidget(QLabel("超出阈值的像元不分配"))
        thr_row.addStretch()
        layout.addRow("最大距离:", self.threshold_widget)
        self._on_algo_changed()  # init visibility

        # Buttons
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def _on_algo_changed(self):
        is_pop = self.algo_combo.currentData() == 'population'
        self.threshold_widget.setVisible(is_pop)
        self.adjustSize()

    def get_config(self):
        cfg = RasterConfig(self.path)
        cfg.var_name = self.var_combo.currentText() if self.vars else None
        cfg.time_idx = self.time_combo.currentData() if self.time_combo.count() else -1
        name = self.field_edit.text().strip()
        cfg.field_name = name[:10] if name else Path(self.path).stem[:10]
        cfg.algorithm = self.algo_combo.currentData()
        cfg.threshold_km = self.threshold_spin.value()
        return cfg


# Keep old name as alias for batch mode
NcConfigDialog = RasterConfigDialog


# ---------------------------------------------------------------------------
# Processing worker (runs in background thread)
# ---------------------------------------------------------------------------

class ProcessWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, shapefile, raster_configs, compute_mean, mean_field,
                 output_path, update_mode=False):
        super().__init__()
        self.shapefile = shapefile
        self.raster_configs = raster_configs   # list of RasterConfig
        self.compute_mean = compute_mean
        self.mean_field = mean_field
        self.output_path = output_path
        self.update_mode = update_mode

    def run(self):
        try:
            import geopandas as gpd

            self.progress.emit(0, "正在加载 Shapefile...")
            roads = gpd.read_file(self.output_path if self.update_mode else self.shapefile)
            road_crs = roads.crs
            n_rasters = len(self.raster_configs)
            interp_arrays = {}   # only interp rasters go into mean calculation

            for i, cfg in enumerate(self.raster_configs):
                self.progress.emit(
                    int(i / n_rasters * 90),
                    f"加载栅格 ({i+1}/{n_rasters}): {Path(cfg.path).name}"
                )

                ext = Path(cfg.path).suffix.lower()
                if ext == '.nc':
                    data, transform, raster_crs = self._load_nc(cfg)
                else:
                    data, transform, raster_crs = self._load_tif(cfg.path)

                if cfg.algorithm == 'population':
                    # ---- nearest-road population assignment ----
                    self.progress.emit(
                        int(i / n_rasters * 90 + 1),
                        f"人口分配 ({i+1}/{n_rasters})..."
                    )
                    values = self._process_population(
                        roads, data, transform, raster_crs,
                        threshold_m=cfg.threshold_km * 1000
                    )
                    roads[cfg.field_name] = values
                else:
                    # ---- length-weighted intersection average ----
                    if road_crs and raster_crs and road_crs != raster_crs:
                        self.progress.emit(int(i / n_rasters * 90 + 1), "坐标系对齐中...")
                        roads_r = roads.to_crs(raster_crs)
                    else:
                        roads_r = roads

                    self.progress.emit(
                        int(i / n_rasters * 90 + 2),
                        f"计算路段插值 ({i+1}/{n_rasters})..."
                    )
                    values = self._assign_values(roads_r, data, transform, i, n_rasters)
                    interp_arrays[cfg.field_name] = np.array(values)
                    roads[cfg.field_name] = values

            # Optional mean across interp rasters
            if self.compute_mean and len(interp_arrays) > 1:
                stack = np.stack(list(interp_arrays.values()), axis=0)
                mean_vals = np.nanmean(stack, axis=0)
                roads[self.mean_field[:10] or "rast_mean"] = mean_vals

            self.progress.emit(95, "保存输出文件...")
            roads.to_file(self.output_path, encoding='utf-8')
            self.progress.emit(100, "完成！")
            self.finished.emit(self.output_path)

        except Exception as e:
            import traceback
            self.error.emit(traceback.format_exc())

    # ------------------------------------------------------------------
    def _process_population(self, roads_gdf, data, transform, raster_crs, threshold_m):
        """
        Nearest-road population assignment with max-distance threshold.

        Optimisations vs. original:
          A) Spatial pre-clip  – only extract pixels inside road bbox + buffer
          B) scipy cKDTree     – point-to-point query on densified road vertices
                                 (shapely.segmentize, fully vectorised), multi-core
          C) np.bincount       – replaces np.add.at (10× faster aggregation)
          D) total_bounds      – replaces union_all().centroid for UTM selection
        """
        import rasterio
        from rasterio.transform import rowcol as _rowcol
        from pyproj import CRS, Transformer
        from scipy.spatial import cKDTree
        import shapely

        # ---- D: Determine metric CRS via total_bounds (no union_all) ----
        road_crs = roads_gdf.crs
        if road_crs and road_crs.is_geographic:
            b = roads_gdf.total_bounds           # [minx, miny, maxx, maxy]
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            zone = int((cx + 180) / 6) + 1
            metric_crs = CRS.from_dict({
                'proj': 'utm', 'zone': zone,
                'south': cy < 0, 'datum': 'WGS84'
            })
            roads_m = roads_gdf.to_crs(metric_crs)
        else:
            metric_crs = road_crs
            roads_m = roads_gdf

        # ---- A: Spatial pre-clip ─ transform bbox corners only (fast) ----
        n_rows, n_cols = data.shape
        b = roads_gdf.total_bounds               # road bbox in road CRS
        if road_crs and raster_crs and road_crs != raster_crs:
            # Transform the 4 corners of the road bbox into raster CRS
            tr_bbox = Transformer.from_crs(road_crs, raster_crs, always_xy=True)
            cx_r, cy_r = tr_bbox.transform(
                [b[0], b[2], b[0], b[2]],
                [b[1], b[1], b[3], b[3]]
            )
            rb = [min(cx_r), min(cy_r), max(cx_r), max(cy_r)]
        else:
            rb = list(b)

        # Buffer: threshold_m → raster CRS units
        if raster_crs and raster_crs.is_geographic:
            buf = threshold_m / 100_000.0        # 1° ≈ 100 km (conservative)
        else:
            buf = threshold_m

        # Convert buffered bbox to pixel row/col ranges
        r0, c0 = _rowcol(transform, rb[0] - buf, rb[3] + buf)   # top-left
        r1, c1 = _rowcol(transform, rb[2] + buf, rb[1] - buf)   # bottom-right
        r0 = int(max(0, min(r0, r1)));  r1 = int(min(n_rows - 1, max(r0, r1)))
        c0 = int(max(0, min(c0, c1)));  c1 = int(min(n_cols - 1, max(c0, c1)))

        # Extract valid pixels from clipped sub-array only
        clip = data[r0:r1 + 1, c0:c1 + 1]
        valid_mask = ~np.isnan(clip) & (clip > 0)
        local_r, local_c = np.where(valid_mask)

        n_clipped = int(local_r.size)
        n_total   = int((~np.isnan(data) & (data > 0)).sum())

        if n_clipped == 0:
            self.progress.emit(90, f"路网范围内无有效人口像元（全栅格共 {n_total} 个）")
            return np.zeros(len(roads_gdf))

        ratio = n_total / max(n_clipped, 1)
        self.progress.emit(
            84,
            f"空间裁剪：{n_clipped} 个像元"
            f"（全栅格 {n_total}，压缩 {ratio:.0f}×）"
        )

        xs, ys = rasterio.transform.xy(transform, local_r + r0, local_c + c0)
        xs = np.asarray(xs, dtype=np.float64)
        ys = np.asarray(ys, dtype=np.float64)
        pop_vals = clip[local_r, local_c].astype(np.float64)

        # Reproject pixel centres to metric CRS
        if raster_crs and metric_crs and raster_crs != metric_crs:
            tr = Transformer.from_crs(raster_crs, metric_crs, always_xy=True)
            xs, ys = tr.transform(xs, ys)

        # ---- B: Densify road geometries → cKDTree ----
        # shapely.segmentize ensures no segment > step metres (vectorised, no loop)
        step = float(np.clip(threshold_m / 10.0, 20.0, 200.0))
        self.progress.emit(86, f"路段密化（间距 {step:.0f} m）…")

        dense_geoms  = shapely.segmentize(roads_m.geometry.values,
                                          max_segment_length=step)
        road_pts_xy  = shapely.get_coordinates(dense_geoms)        # (N, 2)
        pts_per_geom = shapely.get_num_coordinates(dense_geoms)    # per-road count
        road_pts_idx = np.repeat(
            np.arange(len(dense_geoms), dtype=np.int32), pts_per_geom
        )

        self.progress.emit(
            88,
            f"KD-Tree 构建：{len(road_pts_xy)} 个采样点…"
        )
        kd = cKDTree(road_pts_xy)

        # Multi-core nearest query (workers=-1 → all CPU cores)
        pixel_xy = np.column_stack([xs, ys])
        dists, nn_idx = kd.query(pixel_xy, workers=-1)
        nearest_road_idx = road_pts_idx[nn_idx]

        # Apply threshold
        within      = dists <= threshold_m
        n_assigned  = int(within.sum())
        n_discarded = int((~within).sum())
        pop_discard = float(pop_vals[~within].sum())

        self.progress.emit(
            92,
            f"人口分配：{n_assigned} 像元已分配，"
            f"{n_discarded} 超阈值丢弃（{pop_discard:.0f} 人）"
        )

        # ---- C: Aggregate with bincount (10× faster than np.add.at) ----
        pop_per_road = np.bincount(
            nearest_road_idx[within],
            weights=pop_vals[within],
            minlength=len(roads_m)
        )

        return pop_per_road

    # ------------------------------------------------------------------
    def _load_nc(self, cfg):
        import xarray as xr
        import rasterio
        from pyproj import CRS

        ds = xr.open_dataset(cfg.path)
        var_name = cfg.var_name or list(ds.data_vars.keys())[0]
        da = ds[var_name]

        if 'time' in da.dims:
            if cfg.time_idx == -1:
                da = da.mean(dim='time')
            else:
                da = da.isel(time=cfg.time_idx)

        # Detect lat/lon names
        lat_name = next((n for n in ['lat', 'latitude', 'Latitude', 'LAT'] if n in ds), None)
        lon_name = next((n for n in ['lon', 'longitude', 'Longitude', 'LON'] if n in ds), None)
        if lat_name is None or lon_name is None:
            raise ValueError(f"Cannot find lat/lon in nc file: {cfg.path}")

        lat = ds[lat_name].values.astype(np.float64)
        lon = ds[lon_name].values.astype(np.float64)

        data = da.values.astype(np.float64)

        # Convert fill values to nan
        fill = getattr(da, '_FillValue', None) or getattr(da, 'missing_value', None)
        if fill is not None:
            data[data == float(fill)] = np.nan
        # Also handle common sentinel values
        data[data > 1e30] = np.nan

        # Ensure lat is top-to-bottom (decreasing)
        if lat[0] < lat[-1]:
            data = np.flipud(data)
            lat = lat[::-1]

        lat_res = abs(lat[0] - lat[1]) if len(lat) > 1 else 0.1
        lon_res = abs(lon[0] - lon[1]) if len(lon) > 1 else 0.1

        transform = rasterio.transform.from_bounds(
            lon.min() - lon_res / 2,
            lat.min() - lat_res / 2,
            lon.max() + lon_res / 2,
            lat.max() + lat_res / 2,
            len(lon),
            len(lat)
        )

        crs = CRS.from_epsg(4326)
        ds.close()
        return data, transform, crs

    def _load_tif(self, path):
        import rasterio
        with rasterio.open(path) as src:
            data = src.read(1).astype(np.float64)
            transform = src.transform
            crs = src.crs
            nodata = src.nodata
            if nodata is not None:
                data[data == nodata] = np.nan
        return data, transform, crs

    def _assign_values(self, roads, data, transform, raster_idx, n_rasters):
        """
        For each road geometry, compute the length-weighted average of
        raster cell values based on intersection length.
        """
        from rasterio.transform import rowcol
        from shapely.geometry import box

        n_rows, n_cols = data.shape
        px_w = transform.a       # pixel width  (positive)
        px_h = abs(transform.e)  # pixel height (positive)

        results = []
        n_roads = len(roads)
        report_every = max(1, n_roads // 200)

        for j, geom in enumerate(roads.geometry):
            if j % report_every == 0:
                road_pct = j / n_roads
                overall = int((raster_idx + road_pct) / n_rasters * 85)
                self.progress.emit(
                    overall,
                    f"栅格 {raster_idx+1}/{n_rasters}: 路段 {j}/{n_roads}"
                )

            if geom is None or geom.is_empty:
                results.append(np.nan)
                continue

            minx, miny, maxx, maxy = geom.bounds

            # Pixel row/col range covering the road bbox
            r0, c0 = rowcol(transform, minx, maxy)  # top-left corner
            r1, c1 = rowcol(transform, maxx, miny)  # bottom-right corner

            r0 = max(0, min(r0, r1))
            r1 = min(n_rows - 1, max(r0, r1))
            c0 = max(0, min(c0, c1))
            c1 = min(n_cols - 1, max(c0, c1))

            weighted_sum = 0.0
            total_len = 0.0

            for row in range(r0, r1 + 1):
                for col in range(c0, c1 + 1):
                    value = data[row, col]
                    if np.isnan(value):
                        continue

                    # Pixel bounding box (in raster CRS coordinates)
                    left  = transform.c + col * px_w
                    top   = transform.f - row * px_h
                    right = left + px_w
                    bottom = top - px_h
                    cell = box(left, bottom, right, top)

                    inter = geom.intersection(cell)
                    if inter.is_empty:
                        continue
                    inter_len = inter.length
                    if inter_len > 0:
                        weighted_sum += inter_len * value
                        total_len += inter_len

            results.append(weighted_sum / total_len if total_len > 0 else np.nan)

        return results


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class RasterToRoadsWindow(QMainWindow):
    output_ready = pyqtSignal(str)   # 计算完成，参数为输出 shp 路径（供主程序加载为图层）

    def __init__(self):
        super().__init__()
        self.setWindowTitle("栅格值路网赋值工具")
        self.setMinimumSize(900, 720)
        self.raster_configs = []   # list of RasterConfig
        self.worker = None
        self._last_dir = _BASE_DIR   # file dialog starting directory
        self._shp_fields = []        # field names already in the active shapefile
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        # ---- Shapefile ----
        self.shp_box = QGroupBox("路网 Shapefile")
        shp_layout = QHBoxLayout(self.shp_box)
        self.shp_edit = QLineEdit()
        self.shp_edit.setPlaceholderText("选择 .shp 文件...")
        self.shp_edit.setReadOnly(True)
        shp_btn = QPushButton("浏览…")
        shp_btn.setFixedWidth(70)
        shp_btn.clicked.connect(self._pick_shapefile)
        shp_layout.addWidget(self.shp_edit)
        shp_layout.addWidget(shp_btn)
        root.addWidget(self.shp_box)

        # ---- Raster files ----
        rast_box = QGroupBox("栅格文件（TIF / NC，可多选）")
        rast_inner = QVBoxLayout(rast_box)
        rast_inner.setContentsMargins(6, 6, 6, 6)

        self.rast_list = QListWidget()
        self.rast_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.rast_list.setMinimumHeight(120)
        self.rast_list.itemDoubleClicked.connect(self._edit_raster_config)
        rast_inner.addWidget(self.rast_list)

        root.addWidget(rast_box)

        # Buttons sit outside the GroupBox so they never overlap the list border
        btn_row = QHBoxLayout()
        add_btn = QPushButton("添加文件…")
        add_btn.clicked.connect(self._add_rasters)
        folder_btn = QPushButton("添加文件夹…")
        folder_btn.clicked.connect(self._add_folder)
        edit_btn = QPushButton("编辑配置")
        edit_btn.clicked.connect(self._edit_raster_config)
        rm_btn = QPushButton("移除选中")
        rm_btn.clicked.connect(self._remove_rasters)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(folder_btn)
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(rm_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # ---- Options ----
        opt_box = QGroupBox("选项")
        opt_layout = QVBoxLayout(opt_box)

        self.mean_check = QCheckBox("计算所有栅格的均值（多个栅格时可用）")
        self.mean_check.setChecked(True)
        self.mean_check.stateChanged.connect(
            lambda: self.mean_field_edit.setEnabled(
                self.mean_check.isChecked() and len(self.raster_configs) > 1
            )
        )
        opt_layout.addWidget(self.mean_check)

        mean_name_row = QHBoxLayout()
        mean_name_row.addWidget(QLabel("均值字段名:"))
        self.mean_field_edit = QLineEdit("rast_mean")
        self.mean_field_edit.setMaxLength(10)
        self.mean_field_edit.setFixedWidth(120)
        mean_name_row.addWidget(self.mean_field_edit)
        mean_name_row.addStretch()
        opt_layout.addLayout(mean_name_row)

        root.addWidget(opt_box)

        # ---- Output ----
        out_box = QGroupBox("输出")
        out_vlayout = QVBoxLayout(out_box)

        mode_row = QHBoxLayout()
        self.radio_new = QRadioButton("新建 Shapefile")
        self.radio_update = QRadioButton("追加字段到上方 SHP")
        self.radio_new.setChecked(True)
        self.radio_new.toggled.connect(self._on_output_mode_changed)
        mode_row.addWidget(self.radio_new)
        mode_row.addWidget(self.radio_update)
        mode_row.addStretch()
        out_vlayout.addLayout(mode_row)

        # New-file row (shown only in 新建 mode)
        self.out_path_row = QWidget()
        path_layout = QHBoxLayout(self.out_path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("选择新建 .shp 路径...")
        self.out_edit.setReadOnly(True)
        out_btn = QPushButton("浏览…")
        out_btn.setFixedWidth(70)
        out_btn.clicked.connect(self._pick_output)
        path_layout.addWidget(self.out_edit)
        path_layout.addWidget(out_btn)
        out_vlayout.addWidget(self.out_path_row)

        # Update-mode hint (shown only in 追加 mode)
        self.out_hint_label = QLabel("新字段将直接追加到上方所选的 SHP 文件中（原地修改）")
        self.out_hint_label.setStyleSheet("color: #555; font-size: 11px;")
        self.out_hint_label.setVisible(False)
        out_vlayout.addWidget(self.out_hint_label)

        root.addWidget(out_box)

        # ---- Progress ----
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        root.addWidget(self.progress_bar)

        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: #555;")
        root.addWidget(self.status_label)

        # ---- Log ----
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setFixedHeight(90)
        self.log_edit.setStyleSheet("font-family: monospace; font-size: 11px;")
        root.addWidget(self.log_edit)

        # ---- Run button ----
        self.run_btn = QPushButton("开始计算")
        self.run_btn.setFixedHeight(36)
        self.run_btn.setFixedWidth(120)
        self.run_btn.setStyleSheet(
            "QPushButton { background: #1a73e8; color: white; border-radius: 6px; font-size: 14px; }"
            "QPushButton:hover { background: #1558b0; }"
            "QPushButton:disabled { background: #aaa; }"
        )
        self.run_btn.clicked.connect(self._run)

    # ------------------------------------------------------------------
    # File picking
    # ------------------------------------------------------------------

    def _on_output_mode_changed(self):
        is_new = self.radio_new.isChecked()
        # Show/hide the appropriate widgets
        self.out_path_row.setVisible(is_new)
        self.out_hint_label.setVisible(not is_new)
        # Update the shapefile groupbox title to hint at dual role
        self.shp_box.setTitle(
            "路网 Shapefile" if is_new else "路网 Shapefile（追加模式：字段将直接写入此文件）"
        )
        if is_new:
            self.out_edit.clear()
        else:
            # In update mode, read existing fields from the already-selected SHP
            shp = self.shp_edit.text().strip()
            if shp:
                self._read_shp_fields(shp)
            else:
                self._shp_fields = []
        self._refresh_raster_list()

    def _read_shp_fields(self, path):
        """Read column names from a shapefile without loading geometry."""
        try:
            import geopandas as gpd
            gdf = gpd.read_file(path, rows=0)
            self._shp_fields = [c for c in gdf.columns if c != 'geometry']
        except Exception:
            self._shp_fields = []

    # macOS native dialog ignores the directory argument, so force Qt's own dialog
    _DIALOG_OPT = QFileDialog.Option.DontUseNativeDialog

    def _pick_shapefile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择路网 Shapefile", self._last_dir,
            "Shapefiles (*.shp)", options=self._DIALOG_OPT
        )
        self.set_shapefile(path)

    def set_shapefile(self, path):
        if path:
            self._last_dir = str(Path(path).parent)
            self.shp_edit.setText(path)
            # Always read fields (needed for both new and update modes)
            self._read_shp_fields(path)
            self._refresh_raster_list()
            # In new mode: auto-suggest an output path
            if self.radio_new.isChecked() and not self.out_edit.text():
                stem = Path(path).stem
                out = str(Path(path).parent / f"{stem}_raster_values.shp")
                self.out_edit.setText(out)

    def _add_rasters(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择栅格文件", self._last_dir,
            "栅格文件 (*.tif *.tiff *.nc);;GeoTIFF (*.tif *.tiff);;NetCDF (*.nc)",
            options=self._DIALOG_OPT
        )
        if not paths:
            return
        self._last_dir = str(Path(paths[0]).parent)

        for path in paths:
            # Skip duplicates
            if path in [c.path for c in self.raster_configs]:
                continue

            smart_name = self._smart_field_name(path)
            pre_cfg = RasterConfig(path)
            pre_cfg.field_name = smart_name

            dlg = RasterConfigDialog(path, self, initial_cfg=pre_cfg)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                continue
            cfg = dlg.get_config()
            cfg.field_name = self._unique_field_name(cfg.field_name)
            self.raster_configs.append(cfg)

        self._refresh_raster_list()

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "选择文件夹", self._last_dir,
            QFileDialog.Option.DontUseNativeDialog | QFileDialog.Option.ShowDirsOnly
        )
        if not folder:
            return
        self._last_dir = folder
        folder_path = Path(folder)

        existing_paths = {c.path for c in self.raster_configs}

        tif_files = sorted(
            p for p in folder_path.iterdir()
            if p.suffix.lower() in ('.tif', '.tiff') and str(p) not in existing_paths
        )
        nc_files = sorted(
            p for p in folder_path.iterdir()
            if p.suffix.lower() == '.nc' and str(p) not in existing_paths
        )

        # TIF: one batch config dialog for ALL TIF files
        if tif_files:
            dlg = RasterConfigDialog(str(tif_files[0]), self, batch_mode=True)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                algo = dlg.algo_combo.currentData()
                thr_km = dlg.threshold_spin.value()
                for p in tif_files:
                    cfg = RasterConfig(str(p))
                    cfg.field_name = self._unique_field_name(self._smart_field_name(str(p)))
                    cfg.algorithm = algo
                    cfg.threshold_km = thr_km
                    self.raster_configs.append(cfg)

        # NC: one config dialog for ALL NC files (same variable / time / algo)
        if nc_files:
            dlg = RasterConfigDialog(str(nc_files[0]), self, batch_mode=True)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                var_name = dlg.var_combo.currentText() if dlg.vars else None
                time_idx = dlg.time_combo.currentData()
                algo = dlg.algo_combo.currentData()
                thr_km = dlg.threshold_spin.value()
                for p in nc_files:
                    cfg = RasterConfig(str(p))
                    cfg.var_name = var_name
                    cfg.time_idx = time_idx
                    cfg.field_name = self._unique_field_name(self._smart_field_name(str(p)))
                    cfg.algorithm = algo
                    cfg.threshold_km = thr_km
                    self.raster_configs.append(cfg)

        self._log(f"从文件夹扫描：{len(tif_files)} TIF，{len(nc_files)} NC（已跳过重复）")
        self._refresh_raster_list()

    def _edit_raster_config(self, item=None):
        # item is the QListWidgetItem when triggered by double-click; ignored
        # when triggered by the "编辑配置" button (selection is used instead).
        rows = [i.row() for i in self.rast_list.selectedIndexes()]
        if not rows:
            QMessageBox.information(self, "提示", "请先选中要编辑的文件")
            return
        for row in rows:
            cfg = self.raster_configs[row]
            dlg = RasterConfigDialog(cfg.path, self, initial_cfg=cfg)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                new_cfg = dlg.get_config()
                new_cfg.field_name = self._unique_field_name(
                    new_cfg.field_name, exclude_idx=row
                )
                self.raster_configs[row] = new_cfg
        self._refresh_raster_list()

    def _remove_rasters(self):
        rows = sorted(
            [i.row() for i in self.rast_list.selectedIndexes()], reverse=True
        )
        for row in rows:
            del self.raster_configs[row]
        self._refresh_raster_list()

    def _refresh_raster_list(self):
        self.rast_list.clear()
        for cfg in self.raster_configs:
            ext = Path(cfg.path).suffix.lower()
            if ext == '.nc':
                nc_info = f"  [变量:{cfg.var_name or 'auto'} 时间:{'均值' if cfg.time_idx == -1 else cfg.time_idx}]"
            else:
                nc_info = ""
            if cfg.algorithm == 'population':
                algo_tag = f"  [人口分配 ≤{cfg.threshold_km}km]"
            else:
                algo_tag = "  [插值均值]"
            text = f"{Path(cfg.path).name}  →  {cfg.field_name}{nc_info}{algo_tag}"
            self.rast_list.addItem(text)

        n = len(self.raster_configs)
        self.mean_check.setEnabled(n > 1)
        self.mean_field_edit.setEnabled(n > 1 and self.mean_check.isChecked())

    def _pick_output(self):
        # Only called in 新建 mode (update mode has no browse button)
        path, _ = QFileDialog.getSaveFileName(
            self, "新建输出 Shapefile", self._last_dir,
            "Shapefiles (*.shp)", options=self._DIALOG_OPT
        )
        if path:
            self._last_dir = str(Path(path).parent)
            if not path.endswith('.shp'):
                path += '.shp'
            self.out_edit.setText(path)

    # ------------------------------------------------------------------
    # Smart & unique field names
    # ------------------------------------------------------------------

    @staticmethod
    def _smart_field_name(path):
        """
        Derive a short (≤10 char), ASCII, shapefile-safe field name from a
        raster filename.  Handles patterns like:
          CHAP_PM2.5_M1K_202401_V4.nc  →  PM25_2401
          CHAP_NO2_M1K_202312_V2.nc    →  NO2_2312
          UV_annual_2023.tif           →  UV_23
          my_raster.tif                →  my_raster
        """
        stem = Path(path).stem

        # Strip common prefixes / suffixes used by CHAP and similar products
        stem = re.sub(r'^CHAP_', '', stem, flags=re.IGNORECASE)
        stem = re.sub(r'_M\d+[KkMmBb]+', '', stem)          # _M1K _M500M …
        stem = re.sub(r'_V\d+', '', stem, flags=re.IGNORECASE)   # _V2 _V3 anywhere

        # Extract date token (prefer YYYYMM > YYYY > YYYYMMDD)
        date_str = ""
        for pattern, slice_ in [
            (r'(?<![0-9])(\d{8})(?![0-9])', slice(4, 8)),   # YYYYMMDD → MMDD
            (r'(?<![0-9])(\d{6})(?![0-9])',  slice(2, 6)),   # YYYYMM   → YYMM
            (r'(?<![0-9])(\d{4})(?![0-9])',  slice(2, 4)),   # YYYY     → YY
        ]:
            m = re.search(pattern, stem)
            if m:
                date_str = m.group(1)[slice_]
                stem = stem[:m.start()] + stem[m.end():]
                break

        # Sanitise variable part: keep alphanumeric, drop punctuation
        var = re.sub(r'[^a-zA-Z0-9]', '', stem)   # PM2.5 → PM25

        if var and date_str:
            name = f"{var}_{date_str}"
        elif var:
            name = var
        else:
            # Fallback for non-ASCII filenames: use first printable chars
            name = re.sub(r'[^a-zA-Z0-9_]', '', Path(path).stem)[:8] or "rast"

        return name[:10]

    def _unique_field_name(self, name, exclude_idx=None):
        # Taken names = other raster configs + fields already in the shapefile
        existing = [
            c.field_name for i, c in enumerate(self.raster_configs)
            if i != exclude_idx
        ] + self._shp_fields
        if name not in existing:
            return name
        for i in range(1, 100):
            candidate = (name + f"_{i}")[:10]
            if candidate not in existing:
                return candidate
        return name

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def _run(self):
        shp = self.shp_edit.text().strip()
        update_mode = self.radio_update.isChecked()

        # In update mode the output IS the input shapefile
        out = shp if update_mode else self.out_edit.text().strip()

        if not shp:
            QMessageBox.warning(self, "缺少输入", "请选择路网 Shapefile。")
            return
        if not self.raster_configs:
            QMessageBox.warning(self, "缺少输入", "请先添加至少一个栅格文件。")
            return
        if not update_mode and not out:
            QMessageBox.warning(self, "缺少输出", "请指定输出文件路径。")
            return

        self.run_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.log_edit.clear()
        mode_str = f"追加到 {Path(out).name}" if update_mode else f"新建 {Path(out).name}"

        n_interp = sum(1 for c in self.raster_configs if c.algorithm == 'interp')
        n_pop    = sum(1 for c in self.raster_configs if c.algorithm == 'population')
        parts = []
        if n_interp:
            parts.append(f"{n_interp} 个插值栅格")
        if n_pop:
            parts.append(f"{n_pop} 个人口栅格")
        self._log(f"开始处理 {' + '.join(parts)} → {mode_str}")

        compute_mean = self.mean_check.isChecked() and len(self.raster_configs) > 1
        mean_field = self.mean_field_edit.text().strip()[:10] or "rast_mean"

        self.worker = ProcessWorker(
            shapefile=shp,
            raster_configs=self.raster_configs,
            compute_mean=compute_mean,
            mean_field=mean_field,
            output_path=out,
            update_mode=update_mode,
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_progress(self, pct, msg):
        self.progress_bar.setValue(pct)
        self.status_label.setText(msg)
        self._log(msg)

    def _on_finished(self, path):
        self.run_btn.setEnabled(True)
        self.progress_bar.setValue(100)
        self.status_label.setText("完成！")
        self._log(f"输出已保存: {path}")
        self.output_ready.emit(path)
        QMessageBox.information(self, "完成", f"处理完成！\n\n输出文件:\n{path}")

    def _on_error(self, tb):
        self.run_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("出错！")
        self._log(f"[错误]\n{tb}")
        QMessageBox.critical(self, "处理出错", f"发生错误:\n\n{tb[:600]}")

    def _log(self, msg):
        self.log_edit.append(msg)
        self.log_edit.verticalScrollBar().setValue(
            self.log_edit.verticalScrollBar().maximum()
        )
