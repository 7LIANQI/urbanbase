"""时间分析：从点位宽表或日期记录生成趋势统计与图表。"""
from pathlib import Path

import pandas as pd
from PyQt6.QtCore import QSettings, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from core import time_analysis as TA
from core.utils import secure_load
from core.config import PG_HOST, PG_PORT, PG_DBNAME, PG_USER, PG_PASSWORD


def _guess(columns, names):
    lowered = [str(c).strip().lower() for c in columns]
    for target in names:
        if target in lowered:
            return columns[lowered.index(target)]
    for i, value in enumerate(lowered):
        if any(target in value for target in names):
            return columns[i]
    return None


class _Worker(QThread):
    done = pyqtSignal(object, object)
    failed = pyqtSignal(str)

    def __init__(self, df, organization, id_col, lon_col, lat_col, date_col,
                 time_mode, metrics):
        super().__init__()
        self.df, self.organization = df, organization
        self.id_col, self.lon_col, self.lat_col = id_col, lon_col, lat_col
        self.date_col, self.time_mode, self.metrics = date_col, time_mode, metrics

    def run(self):
        try:
            if self.organization == "wide":
                columns = TA.discover_time_columns(self.df, self.time_mode, self.metrics)
                long = TA.to_long(
                    self.df, columns, self.id_col, self.lon_col, self.lat_col
                )
            else:
                long = TA.records_to_long(
                    self.df, self.date_col, self.metrics,
                    self.id_col, self.lon_col, self.lat_col,
                )
            if long.empty:
                raise ValueError("选中范围内没有有效的时间数值")
            self.done.emit(long, TA.summarize(long))
        except Exception as e:
            self.failed.emit(str(e))


class TimeAnalysisWidget(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.df = None
        self.long = None
        self.stats = None
        self.worker = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        body = QWidget()
        lay = QVBoxLayout(body)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        data = QGroupBox("① 数据")
        grid = QGridLayout(data)
        self.path = QLineEdit()
        self.path.setReadOnly(True)
        self.path.setPlaceholderText("点位指标提取结果 CSV / GPKG")
        browse = QPushButton("打开文件…")
        browse.clicked.connect(self._open_file)
        grid.addWidget(QLabel("文件"), 0, 0)
        grid.addWidget(self.path, 0, 1, 1, 4)
        grid.addWidget(browse, 0, 5)

        self.pg_dataset = QComboBox()
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self._refresh_pg)
        load_pg = QPushButton("从 PostgreSQL 加载")
        load_pg.clicked.connect(self._load_pg)
        grid.addWidget(QLabel("本地数据集"), 1, 0)
        grid.addWidget(self.pg_dataset, 1, 1, 1, 3)
        grid.addWidget(refresh, 1, 4)
        grid.addWidget(load_pg, 1, 5)
        lay.addWidget(data)

        mapping = QGroupBox("② 列与时间口径")
        grid = QGridLayout(mapping)
        self.organization = QComboBox()
        self.organization.addItem("宽表时间列（指标_P2020 / 指标_y3）", "wide")
        self.organization.addItem("按日期列组织（每行一个观测）", "long")
        self.organization.currentIndexChanged.connect(self._refresh_metrics)
        self.time_mode = QComboBox()
        self.time_mode.addItem("自动", "auto")
        self.time_mode.addItem("固定历史时间段（P2017、P2018…）", "fixed")
        self.time_mode.addItem("相对观测窗口（cur、y1、y3…）", "relative")
        self.id_col, self.lon_col, self.lat_col, self.date_col = (QComboBox() for _ in range(4))
        for row, (label, widget) in enumerate((
            ("数据组织", self.organization), ("时间口径", self.time_mode),
            ("点位 ID", self.id_col), ("经度", self.lon_col),
            ("纬度", self.lat_col), ("观测日期", self.date_col),
        )):
            grid.addWidget(QLabel(label), row // 2, (row % 2) * 2)
            grid.addWidget(widget, row // 2, (row % 2) * 2 + 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        lay.addWidget(mapping)

        metrics_box = QGroupBox("③ 指标")
        ml = QVBoxLayout(metrics_box)
        bar = QHBoxLayout()
        for text, checked in (("全选", True), ("清空", False)):
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, v=checked: self._check_all(v))
            bar.addWidget(button)
        bar.addStretch()
        self.metric_count = QLabel("尚未加载数据")
        bar.addWidget(self.metric_count)
        ml.addLayout(bar)
        self.metrics = QListWidget()
        self.metrics.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.metrics.setMaximumHeight(170)
        ml.addWidget(self.metrics)
        lay.addWidget(metrics_box)

        result_box = QGroupBox("④ 结果")
        rl = QVBoxLayout(result_box)
        chart_bar = QHBoxLayout()
        chart_bar.addWidget(QLabel("趋势指标"))
        self.chart_metric = QComboBox()
        self.chart_metric.currentIndexChanged.connect(self._plot)
        chart_bar.addWidget(self.chart_metric, 1)
        self.show_points = QPushButton("显示前 20 个点")
        self.show_points.setCheckable(True)
        self.show_points.toggled.connect(self._plot)
        chart_bar.addWidget(self.show_points)
        rl.addLayout(chart_bar)
        self.figure = Figure(figsize=(7, 3.6), tight_layout=True)
        self.chart = FigureCanvasQTAgg(self.figure)
        self.chart.setMinimumHeight(260)
        rl.addWidget(self.chart)
        self.tabs = QTabWidget()
        self.long_table = QTableWidget()
        self.stats_table = QTableWidget()
        self.tabs.addTab(self.long_table, "时间序列长表")
        self.tabs.addTab(self.stats_table, "趋势统计")
        rl.addWidget(self.tabs)
        lay.addWidget(result_box)
        lay.addStretch()

        # 下拉框不能按整段数据库错误信息或超长列名自动撑宽窗口。
        for combo in (
            self.pg_dataset, self.organization, self.time_mode,
            self.id_col, self.lon_col, self.lat_col, self.date_col,
            self.chart_metric,
        ):
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setMinimumContentsLength(12)

        self.status = QLabel("")
        root.addWidget(self.status)
        self.export_btn = QPushButton("导出结果")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export)
        self.run_btn = QPushButton("开始分析")
        self.run_btn.setProperty("primary", True)
        self.run_btn.clicked.connect(self._run)
        self.tool_footer = {"right": [self.export_btn, self.run_btn]}
        self._refresh_pg()

    @staticmethod
    def _fill_combo(combo, columns, selected=None):
        combo.clear()
        combo.addItem("不使用", None)
        for col in columns:
            combo.addItem(str(col), col)
        if selected is not None:
            combo.setCurrentIndex(max(0, combo.findData(selected)))

    def _set_data(self, df, source):
        self.df = df
        self.path.setText(source)
        cols = list(df.columns)
        self._fill_combo(self.id_col, cols, _guess(cols, ("point_id", "id", "编号", "name", "点位")))
        self._fill_combo(self.lon_col, cols, _guess(cols, ("lon", "lng", "经度", "x")))
        self._fill_combo(self.lat_col, cols, _guess(cols, ("lat", "纬度", "y")))
        self._fill_combo(self.date_col, cols, _guess(cols, ("obs_time", "datetime", "date", "time", "日期", "时间")))
        wide = TA.metric_names(df)
        self.organization.setCurrentIndex(0 if wide else 1)
        self._refresh_metrics()

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "打开分析数据", "", "数据 (*.csv *.gpkg)"
        )
        if not path:
            return
        try:
            if Path(path).suffix.lower() == ".gpkg":
                import geopandas as gpd
                df = pd.DataFrame(gpd.read_file(path).drop(columns="geometry", errors="ignore"))
            else:
                try:
                    df = pd.read_csv(path, encoding="utf-8-sig")
                except UnicodeDecodeError:
                    df = pd.read_csv(path, encoding="gbk")
            self._set_data(df, path)
        except Exception as e:
            QMessageBox.warning(self, "读取失败", str(e))

    def _pg_store(self):
        from database.pg_store import get_store
        s = QSettings("MyCompany", "UrbanAnalysisApp")
        stored = s.value("pg/password", "")
        password = secure_load("pg_pwd", stored) if stored else PG_PASSWORD
        store = get_store(
            host=s.value("pg/host", PG_HOST), port=int(s.value("pg/port", PG_PORT)),
            dbname=s.value("pg/dbname", PG_DBNAME), user=s.value("pg/user", PG_USER),
            password=password or PG_PASSWORD,
        )
        if stored and password != PG_PASSWORD and not store.is_available():
            store = get_store(
                host=s.value("pg/host", PG_HOST), port=int(s.value("pg/port", PG_PORT)),
                dbname=s.value("pg/dbname", PG_DBNAME), user=s.value("pg/user", PG_USER),
                password=PG_PASSWORD,
            )
        return store

    def _refresh_pg(self):
        self.pg_dataset.clear()
        try:
            datasets = self._pg_store().list_datasets()
            for item in datasets:
                self.pg_dataset.addItem(
                    f"{item['name']}（{item['record_count']} 条）", item["id"]
                )
            if not datasets:
                self.pg_dataset.addItem("暂无本地数据集", None)
        except Exception as e:
            self.pg_dataset.addItem(f"数据库不可用：{e}", None)

    def _load_pg(self):
        dataset_id = self.pg_dataset.currentData()
        if dataset_id is None:
            return QMessageBox.information(self, "提示", "请选择 PostgreSQL 数据集")
        try:
            rows = self._pg_store().query_dataset(dataset_id, limit=10_000_000)
            records = []
            for row in rows:
                payload = dict(row.get("payload") or {})
                payload.update({
                    "dataset_record_id": row.get("id"),
                    "lon": row.get("lon"), "lat": row.get("lat"),
                    "obs_time": row.get("obs_time"),
                })
                if "id" not in payload and "point_id" not in payload:
                    payload["point_id"] = f"{row.get('lon')},{row.get('lat')}"
                records.append(payload)
            if not records:
                raise ValueError("数据集没有记录")
            name = self.pg_dataset.currentText()
            self._set_data(pd.DataFrame(records), f"PostgreSQL：{name}")
        except Exception as e:
            QMessageBox.warning(self, "加载失败", str(e))

    def _refresh_metrics(self, *_):
        self.metrics.clear()
        if self.df is None:
            return
        if self.organization.currentData() == "wide":
            names = TA.metric_names(self.df)
            self.date_col.setEnabled(False)
            self.time_mode.setEnabled(True)
        else:
            excluded = {
                self.id_col.currentData(), self.lon_col.currentData(),
                self.lat_col.currentData(), self.date_col.currentData(),
            }
            names = [c for c in self.df.columns if c not in excluded
                     and pd.to_numeric(self.df[c], errors="coerce").notna().any()]
            self.date_col.setEnabled(True)
            self.time_mode.setEnabled(False)
        for name in names:
            from PyQt6.QtCore import Qt
            item = QListWidgetItem(str(name))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.metrics.addItem(item)
        self.metric_count.setText(f"{len(names)} 个可用指标")

    def _check_all(self, checked):
        from PyQt6.QtCore import Qt
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.metrics.count()):
            self.metrics.item(i).setCheckState(state)

    def _selected_metrics(self):
        from PyQt6.QtCore import Qt
        return [self.metrics.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.metrics.count())
                if self.metrics.item(i).checkState() == Qt.CheckState.Checked]

    def _run(self):
        if self.df is None:
            return QMessageBox.information(self, "提示", "请先加载数据")
        metrics = self._selected_metrics()
        if not metrics:
            return QMessageBox.information(self, "提示", "请至少选择一个指标")
        if self.organization.currentData() == "long" and self.date_col.currentData() is None:
            return QMessageBox.information(self, "提示", "按日期分析时必须选择观测日期列")
        self.run_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.status.setText("正在分析…")
        self.worker = _Worker(
            self.df, self.organization.currentData(),
            self.id_col.currentData(), self.lon_col.currentData(),
            self.lat_col.currentData(), self.date_col.currentData(),
            self.time_mode.currentData(), metrics,
        )
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _done(self, long, stats):
        self.long, self.stats = long, stats
        self._fill_table(self.long_table, long, 5000)
        self._fill_table(self.stats_table, stats, 5000)
        self.chart_metric.clear()
        valid_counts = (
            stats.groupby("metric", sort=False)["valid_count"].sum()
            if not stats.empty else {}
        )
        for name in long["metric"].drop_duplicates():
            label = f"{name}（全部缺失）" if valid_counts.get(name, 0) == 0 else str(name)
            self.chart_metric.addItem(label, name)
        self._plot()
        self.run_btn.setEnabled(True)
        self.export_btn.setEnabled(True)
        missing_count = int(sum(
            valid_counts.get(name, 0) == 0
            for name in long["metric"].drop_duplicates()
        ))
        missing_note = f"，其中 {missing_count} 个指标全部缺失" if missing_count else ""
        self.status.setText(
            f"完成：{long['point_id'].nunique()} 个点，{long['metric'].nunique()} 个指标，"
            f"{len(long)} 条长表记录{missing_note}"
        )

    def _failed(self, msg):
        self.run_btn.setEnabled(True)
        self.status.setText("分析失败")
        QMessageBox.warning(self, "分析失败", msg)

    @staticmethod
    def _fill_table(table, df, limit):
        view = df.head(limit)
        table.setRowCount(len(view))
        table.setColumnCount(len(view.columns))
        table.setHorizontalHeaderLabels([str(c) for c in view.columns])
        for r in range(len(view)):
            for c, column in enumerate(view.columns):
                table.setItem(r, c, QTableWidgetItem(str(view.iloc[r, c])))

    def _plot(self, *_):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        metric = self.chart_metric.currentData()
        if self.long is None or metric is None:
            self.chart.draw_idle()
            return
        part = self.long[self.long["metric"] == metric]
        if part["value"].notna().sum() == 0:
            ax.set_title(f"{metric}：全部缺失")
            ax.text(
                0.5, 0.5, "所选点在该时间范围内均无有效值",
                ha="center", va="center", transform=ax.transAxes,
            )
            ax.set_xticks([])
            ax.set_yticks([])
            self.chart.draw_idle()
            return
        order = part.groupby("period")["axis_value"].first().sort_values()
        periods = list(order.index)
        if self.show_points.isChecked():
            for i, (_, point) in enumerate(part.groupby("_row")):
                if i >= 20:
                    break
                values = point.set_index("period")["value"].reindex(periods)
                ax.plot(range(len(periods)), values, alpha=.25, linewidth=.8)
        mean = part.groupby("period")["value"].mean().reindex(periods)
        low = part.groupby("period")["value"].min().reindex(periods)
        high = part.groupby("period")["value"].max().reindex(periods)
        ax.plot(range(len(periods)), mean, marker="o", linewidth=2)
        ax.fill_between(range(len(periods)), low, high, alpha=.15)
        step = max(1, len(periods) // 10)
        ax.set_xticks(range(0, len(periods), step), periods[::step], rotation=30, ha="right")
        ax.set_title(f"{metric}：均值与最小–最大范围")
        ax.grid(alpha=.25)
        self.chart.draw_idle()

    def _export(self):
        if self.long is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出时间分析", "time_analysis.csv", "结果基名 (*.csv)"
        )
        if not path:
            return
        try:
            paths = TA.write_outputs(
                self.long, self.stats, path,
                {"数据来源": self.path.text(), "组织方式": self.organization.currentText(),
                 "时间口径": self.time_mode.currentText()},
            )
            if self.lon_col.currentData() and self.lat_col.currentData():
                import geopandas as gpd
                from shapely.geometry import Point
                part = self.long.dropna(subset=["lon", "lat"])
                if not part.empty:
                    gdf = gpd.GeoDataFrame(
                        part, geometry=[Point(x, y) for x, y in zip(part["lon"], part["lat"])],
                        crs=4326,
                    )
                    gpkg = str(Path(path).with_suffix(".gpkg"))
                    gdf.to_file(gpkg, driver="GPKG")
                    paths["gpkg"] = gpkg
            self.status.setText("已导出：" + "；".join(paths.values()))
            QMessageBox.information(self, "完成", "导出完成：\n\n" + "\n".join(paths.values()))
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def shutdown(self):
        if self.worker and self.worker.isRunning():
            self.worker.wait(1500)
