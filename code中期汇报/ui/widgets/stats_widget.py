"""综合统计指标展示组件 —— 海拔 / 人口密度 / OSM 统计。"""
import json
from pathlib import Path

import pandas as pd

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
)
from PyQt6.QtCore import Qt


class StatsWidget(QWidget):
    """显示海拔、人口密度、OSM 建筑/路网/绿地统计。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_dir = None
        self.enabled = True
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()

        # ---- 海拔 ----
        elev_group = QGroupBox("⛰️ 海拔 (SRTM)")
        elev_layout = QVBoxLayout()
        self.elev_label = QLabel("暂无数据")
        self.elev_label.setStyleSheet("font-size: 14px; padding: 8px;")
        self.elev_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        elev_layout.addWidget(self.elev_label)
        elev_group.setLayout(elev_layout)
        layout.addWidget(elev_group)

        # ---- 人口密度 ----
        pop_group = QGroupBox("👥 人口密度 (WorldPop / GPW)")
        pop_layout = QVBoxLayout()
        self.pop_label = QLabel("暂无数据")
        self.pop_label.setStyleSheet("font-size: 14px; padding: 8px;")
        self.pop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pop_layout.addWidget(self.pop_label)
        pop_group.setLayout(pop_layout)
        layout.addWidget(pop_group)

        # ---- 土地覆盖 ----
        lc_group = QGroupBox("🏞️ 土地覆盖 (ESA WorldCover)")
        lc_layout = QVBoxLayout()
        self.landcover_label = QLabel("暂无数据")
        self.landcover_label.setStyleSheet("font-size: 13px; padding: 6px;")
        self.landcover_label.setWordWrap(True)
        lc_layout.addWidget(self.landcover_label)
        lc_group.setLayout(lc_layout)
        layout.addWidget(lc_group)

        # ---- JRC 地表水 ----
        water_group = QGroupBox("💧 地表水 (JRC GSW, 1984-2021)")
        water_layout = QVBoxLayout()
        self.water_label = QLabel("暂无数据")
        self.water_label.setStyleSheet("font-size: 13px; padding: 6px;")
        self.water_label.setWordWrap(True)
        water_layout.addWidget(self.water_label)
        water_group.setLayout(water_layout)
        layout.addWidget(water_group)

        # ---- Hansen 森林变化 ----
        forest_group = QGroupBox("🌲 森林变化 (Hansen, 2000-2023)")
        forest_layout = QVBoxLayout()
        self.forest_label = QLabel("暂无数据")
        self.forest_label.setStyleSheet("font-size: 13px; padding: 6px;")
        self.forest_label.setWordWrap(True)
        forest_layout.addWidget(self.forest_label)
        forest_group.setLayout(forest_layout)
        layout.addWidget(forest_group)

        # ---- 树冠高度 ----
        canopy_group = QGroupBox("🌳 树冠高度 (ETH, 2020)")
        canopy_layout = QVBoxLayout()
        self.canopy_label = QLabel("暂无数据")
        self.canopy_label.setStyleSheet("font-size: 13px; padding: 6px;")
        self.canopy_label.setWordWrap(True)
        canopy_layout.addWidget(self.canopy_label)
        canopy_group.setLayout(canopy_layout)
        layout.addWidget(canopy_group)

        # ---- OSM 统计 ----
        osm_group = QGroupBox("🏗️ OSM 建成环境统计")
        osm_layout = QVBoxLayout()
        self.osm_label = QLabel("暂无数据")
        self.osm_label.setStyleSheet("font-size: 13px; padding: 6px;")
        self.osm_label.setWordWrap(True)
        osm_layout.addWidget(self.osm_label)
        osm_group.setLayout(osm_layout)
        layout.addWidget(osm_group)

        # 汇总表
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["指标", "数值"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        layout.addStretch()
        self.setLayout(layout)

    def set_enabled(self, enabled):
        self.enabled = enabled
        if not self.enabled:
            self.elev_label.setText("（采集时未勾选 GEE / OSM 模块）")
            self.pop_label.setText("")
            self.landcover_label.setText("")
            self.water_label.setText("")
            self.forest_label.setText("")
            self.canopy_label.setText("")
            self.osm_label.setText("")
            self.table.setRowCount(0)

    def set_output_dir(self, output_dir):
        self.current_dir = output_dir
        if self.enabled:
            self._load_data()
        else:
            self.table.setRowCount(0)

    def _load_data(self):
        if not self.current_dir:
            return

        base = Path(self.current_dir)
        stats_rows = []

        # ---- 海拔 ----
        elev_path = base / "elevation_stats.csv"
        if elev_path.exists():
            try:
                df = pd.read_csv(elev_path)
                if not df.empty:
                    row = df.iloc[0]
                    text = (
                        f"均值: {row.get('海拔均值_m', 'N/A')} m  |  "
                        f"范围: {row.get('海拔最小值_m', 'N/A')} – "
                        f"{row.get('海拔最大值_m', 'N/A')} m  |  "
                        f"中位数: {row.get('海拔中位数_m', 'N/A')} m"
                    )
                    self.elev_label.setText(text)
                    for col in df.columns:
                        stats_rows.append((col, str(row[col])))
                else:
                    self.elev_label.setText("海拔数据为空")
            except Exception as e:
                self.elev_label.setText(f"读取失败: {e}")
        else:
            self.elev_label.setText("未采集海拔数据")

        # ---- 人口密度 ----
        pop_path = base / "population_stats.csv"
        if pop_path.exists():
            try:
                df = pd.read_csv(pop_path)
                if not df.empty:
                    row = df.iloc[0]
                    total_pop = row.get('总人口估算', 'N/A')
                    avg_density = row.get('平均人口密度_人每平方千米', 'N/A')
                    max_density = row.get('最大人口密度_人每平方千米', 'N/A')
                    area = row.get('ROI面积_km2', 'N/A')
                    text = (
                        f"估算总人口: {total_pop} 人  |  "
                        f"平均密度: {avg_density} 人/km²  |  "
                        f"最大密度: {max_density} 人/km²  |  "
                        f"区域面积: {area} km²"
                    )
                    self.pop_label.setText(text)
                    for col in df.columns:
                        stats_rows.append((col, str(row[col])))
                else:
                    self.pop_label.setText("人口数据为空")
            except Exception as e:
                self.pop_label.setText(f"读取失败: {e}")
        else:
            self.pop_label.setText("未采集人口密度数据")

        # ---- 土地覆盖 (ESA WorldCover) ----
        lc_path = base / "landcover_stats.csv"
        if lc_path.exists():
            try:
                df = pd.read_csv(lc_path)
                # 找汇总行和主要类别
                summary_row = df[df['地物类别'] == '【汇总】']
                data_rows = df[df['地物类别'] != '【汇总】']
                if not data_rows.empty:
                    # 取占比最大的前 4 类
                    top4 = data_rows.nlargest(4, '占比_pct')
                    lines = []
                    for _, r in top4.iterrows():
                        lines.append(
                            f"  {r['地物类别']}: {r['占比_pct']:.1f}% "
                            f"({r['面积_km2']:.3f} km²)"
                        )
                    if len(data_rows) > 4:
                        other_pct = data_rows.iloc[4:]['占比_pct'].sum()
                        if other_pct > 0.1:
                            lines.append(f"  其他: {other_pct:.1f}%")
                    self.landcover_label.setText("\n".join(lines) if lines else "无数据")
                    for _, r in data_rows.iterrows():
                        stats_rows.append(
                            (f"[土地覆盖] {r['地物类别']}",
                             f"{r['占比_pct']:.1f}%")
                        )
                else:
                    self.landcover_label.setText("土地覆盖数据为空")
            except Exception as e:
                self.landcover_label.setText(f"读取失败: {e}")
        else:
            self.landcover_label.setText("未采集土地覆盖数据")

        # ---- JRC 地表水 ----
        water_path = base / "jrc_water_stats.csv"
        if water_path.exists():
            try:
                df = pd.read_csv(water_path)
                if not df.empty:
                    row = df.iloc[0]
                    text = (
                        f"常年水体面积: {row.get('常年水体面积_km2', 'N/A')} km²  |  "
                        f"季节性水体: {row.get('季节性水体面积_km2', 'N/A')} km²  |  "
                        f"水体出现频率: {row.get('水体出现频率均值_pct', 'N/A')}%  |  "
                        f"季节性均值: {row.get('季节性均值_月', 'N/A')} 月"
                    )
                    self.water_label.setText(text)
                    for col in df.columns:
                        stats_rows.append((f"[JRC 地表水] {col}", str(row[col])))
                else:
                    self.water_label.setText("地表水数据为空")
            except Exception as e:
                self.water_label.setText(f"读取失败: {e}")
        else:
            self.water_label.setText("未采集 JRC 地表水数据")

        # ---- Hansen 森林变化 ----
        forest_path = base / "hansen_forest_stats.csv"
        if forest_path.exists():
            try:
                df = pd.read_csv(forest_path)
                if not df.empty:
                    row = df.iloc[0]
                    text = (
                        f"2000年树冠覆盖率: {row.get('2000年树冠覆盖率均值_pct', 'N/A')}%  |  "
                        f"损失面积: {row.get('2000-2023损失总面积_km2', 'N/A')} km²  |  "
                        f"增长面积: {row.get('2000-2012增长总面积_km2', 'N/A')} km²  |  "
                        f"净变化: {row.get('净变化_km2', 'N/A')} km²"
                    )
                    self.forest_label.setText(text)
                    for col in df.columns:
                        stats_rows.append((f"[森林变化] {col}", str(row[col])))
                else:
                    self.forest_label.setText("森林变化数据为空")
            except Exception as e:
                self.forest_label.setText(f"读取失败: {e}")
        else:
            self.forest_label.setText("未采集 Hansen 森林变化数据")

        # ---- 树冠高度 ----
        canopy_path = base / "canopy_height_stats.csv"
        if canopy_path.exists():
            try:
                df = pd.read_csv(canopy_path)
                if not df.empty:
                    row = df.iloc[0]
                    text = (
                        f"树木区域平均树高: {row.get('树木区域平均树高_m', 'N/A')} m  |  "
                        f"最大树高: {row.get('树木区域最大树高_m', 'N/A')} m  |  "
                        f"树冠覆盖率: {row.get('树冠覆盖率_pct', 'N/A')}%  |  "
                        f"树冠面积: {row.get('树冠面积_ha', 'N/A')} ha"
                    )
                    self.canopy_label.setText(text)
                    for col in df.columns:
                        stats_rows.append((f"[树冠高度] {col}", str(row[col])))
                else:
                    self.canopy_label.setText("树冠高度数据为空")
            except Exception as e:
                self.canopy_label.setText(f"读取失败: {e}")
        else:
            self.canopy_label.setText("未采集树冠高度数据")

        # ---- OSM 统计 ----
        osm_path = base / "osm_stats.json"
        if osm_path.exists():
            try:
                with open(osm_path, 'r', encoding='utf-8') as f:
                    osm = json.load(f)

                lines = []
                bld = osm.get("buildings", {})
                if bld:
                    lines.append(
                        f"🏠 建筑: {bld.get('建筑数量', 'N/A')} 栋, "
                        f"总面积 {bld.get('建筑总面积_m2', 0):,.0f} m², "
                        f"覆盖率 {bld.get('建筑覆盖率_pct', 'N/A')}%"
                    )
                rd = osm.get("roads", {})
                if rd:
                    lines.append(
                        f"🛣️ 路网: 总长 {rd.get('道路总长度_km', 'N/A')} km, "
                        f"密度 {rd.get('路网密度_km_per_km2', 'N/A')} km/km², "
                        f"交叉口 {rd.get('交叉口数量', 'N/A')} 个"
                    )
                gr = osm.get("green_spaces", {})
                if gr:
                    lines.append(
                        f"🌿 绿地: 面积 {gr.get('绿地总面积_m2', 0):,.0f} m², "
                        f"覆盖率 {gr.get('绿地覆盖率_pct', 'N/A')}%"
                    )
                wb = osm.get("water_bodies", {})
                if wb:
                    lines.append(
                        f"💧 水体: 面积 {wb.get('水体总面积_m2', 0):,.0f} m², "
                        f"覆盖率 {wb.get('水体覆盖率_pct', 'N/A')}%"
                    )

                self.osm_label.setText("\n".join(lines) if lines else "OSM 统计为空")
                for section_name, section_data in osm.items():
                    if isinstance(section_data, dict):
                        for k, v in section_data.items():
                            if isinstance(v, float):
                                stats_rows.append((f"[OSM] {k}", f"{v:.2f}"))
                            else:
                                stats_rows.append((f"[OSM] {k}", str(v)))
            except Exception as e:
                self.osm_label.setText(f"读取 OSM 统计失败: {e}")
        else:
            self.osm_label.setText("未采集 OSM 统计数据")

        # ---- 填充汇总表 ----
        self.table.setRowCount(len(stats_rows))
        for i, (label, value) in enumerate(stats_rows):
            self.table.setItem(i, 0, QTableWidgetItem(label))
            self.table.setItem(i, 1, QTableWidgetItem(value))
