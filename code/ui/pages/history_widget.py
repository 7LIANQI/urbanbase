"""统一采集历史：输出文件夹、SQLite 和 PostgreSQL。"""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import shutil

import pandas as pd
from PyQt6.QtCore import QSettings, Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.config import PG_DBNAME, PG_HOST, PG_PASSWORD, PG_PORT, PG_USER
from core import collection_history as CH
from core.utils import secure_load


class HistoryWidget(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.records = []
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("时间范围"))
        self.period = QComboBox()
        self.period.addItems(["全部", "最近 7 天", "最近 30 天", "最近 90 天", "本年"])
        self.period.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.period)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh)
        bar.addWidget(refresh)
        bar.addStretch()
        self.summary = QLabel("")
        bar.addWidget(self.summary)
        lay.addLayout(bar)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "来源", "采集时间", "位置", "时间范围", "标签", "状态", "文件数",
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.cellDoubleClicked.connect(lambda *_: self.show_detail())
        lay.addWidget(self.table, 1)

        actions = QHBoxLayout()
        for text, slot in (
            ("查看详情", self.show_detail),
            ("打开文件夹", self.open_folder),
            ("对比选中", self.compare),
            ("导出选中", self.export_selected),
            ("删除选中", self.delete_selected),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            actions.addWidget(button)
        actions.addStretch()
        lay.addLayout(actions)
        self.errors = QLabel("")
        self.errors.setWordWrap(True)
        lay.addWidget(self.errors)

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

    def _patterns(self):
        settings = QSettings("MyCompany", "UrbanAnalysisApp")
        patterns = ["output_*"]
        out_dir = settings.value("paths/output_dir", "")
        if out_dir and Path(out_dir).is_dir():
            patterns.append(str(Path(out_dir) / "output_*"))
        return patterns

    def _start_time(self):
        now = datetime.now()
        index = self.period.currentIndex()
        if index == 0:
            return None
        if index == 4:
            return datetime(now.year, 1, 1).strftime("%Y-%m-%d %H:%M:%S")
        return (now - timedelta(days=(7, 30, 90)[index - 1])).strftime("%Y-%m-%d %H:%M:%S")

    def refresh(self, *_):
        from database.local_cache import get_cache
        pg = None
        try:
            pg = self._pg_store()
        except Exception:
            pass
        records, errors = CH.collect(
            self._patterns(), get_cache(), pg, start_time=self._start_time()
        )
        self.records = records
        self.table.setRowCount(len(records))
        for row, rec in enumerate(records):
            values = (
                rec.source_label, rec.collected_at, rec.location(),
                f"{rec.start_date or '—'} ~ {rec.end_date or '—'}",
                rec.label or "—",
                "可用" if rec.available or rec.pg_id is not None else
                ("失败" if rec.success is False else "仅记录"),
                str(rec.file_count or 0),
            )
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, rec)
                self.table.setItem(row, col, item)
            if not rec.available and rec.pg_id is None:
                self.table.item(row, 0).setToolTip("只有元数据，原始文件已不存在")
        self.table.resizeColumnsToContents()
        source_counts = {}
        for rec in records:
            source_counts[rec.source_label] = source_counts.get(rec.source_label, 0) + 1
        self.summary.setText(
            f"{len(records)} 条 | " + "，".join(f"{k} {v}" for k, v in source_counts.items())
        )
        self.errors.setText(
            "；".join(f"{source}读取失败：{msg}" for source, _path, msg in errors)
        )

    def selected(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def show_detail(self):
        rec = self.selected()
        if rec is None:
            return QMessageBox.information(self, "提示", "请先选择一条历史记录")
        rows = [
            ("来源", rec.source_label), ("采集时间", rec.collected_at),
            ("位置", rec.location()), ("半径(m)", rec.radius or ""),
            ("采集时间范围", f"{rec.start_date or '—'} ~ {rec.end_date or '—'}"),
            ("标签", rec.label), ("输出目录", rec.output_dir or "数据库记录，无本地目录"),
            ("文件数", rec.file_count), ("状态", "成功" if rec.success else "失败"),
            ("错误", rec.error_msg),
        ]
        if rec.pg_id is not None:
            try:
                metrics, files = self._pg_store().query_run_details(rec.pg_id)
                rows += [
                    (f"指标:{m.get('source')}/{m.get('metric')}", m.get("value"))
                    for m in metrics
                ]
                rows += [(f"文件:{f.get('file_key')}", f.get("file_path")) for f in files]
            except Exception as e:
                rows.append(("数据库详情读取失败", str(e)))
        if rec.available:
            for path in list(Path(rec.output_dir).rglob("*"))[:300]:
                if path.is_file():
                    rows.append(("本地文件", str(path.relative_to(rec.output_dir))))
        dlg = QDialog(self)
        dlg.setWindowTitle(f"历史详情 — {rec.collected_at}")
        dlg.resize(900, 650)
        lay = QVBoxLayout(dlg)
        table = QTableWidget(len(rows), 2)
        table.setHorizontalHeaderLabels(["项目", "内容"])
        for i, (key, value) in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(str(key)))
            table.setItem(i, 1, QTableWidgetItem(str(value)))
        table.resizeColumnsToContents()
        lay.addWidget(table)
        close = QPushButton("关闭")
        close.clicked.connect(dlg.accept)
        lay.addWidget(close)
        dlg.exec()

    def open_folder(self):
        rec = self.selected()
        if rec is None:
            return QMessageBox.information(self, "提示", "请先选择一条历史记录")
        if not rec.available:
            return QMessageBox.information(self, "提示", "该记录没有可用的本地输出文件夹")
        QDesktopServices.openUrl(QUrl.fromLocalFile(rec.output_dir))

    def _stats(self, rec):
        result = {}
        if rec.pg_id is not None:
            try:
                metrics, _ = self._pg_store().query_run_details(rec.pg_id)
                result.update({f"{m['source']}/{m['metric']}": m.get("value") for m in metrics})
            except Exception:
                pass
        if rec.available:
            for path in Path(rec.output_dir).glob("*.csv"):
                try:
                    df = pd.read_csv(path)
                    if not df.empty:
                        for col in df.select_dtypes("number").columns:
                            result[f"{path.stem}/{col}"] = df[col].iloc[-1]
                except Exception:
                    continue
        return result

    def compare(self):
        rec = self.selected()
        if rec is None:
            return QMessageBox.information(self, "提示", "请选择一条记录，再选择另一条对比")
        if not hasattr(self, "_compare") or not self._compare:
            self._compare = [rec]
            return QMessageBox.information(self, "已加入对比", "请再选择另一条记录并点击“对比选中”")
        if rec is self._compare[0]:
            return QMessageBox.information(self, "提示", "请选择另一条记录")
        a, b = self._compare[0], rec
        self._compare = []
        sa, sb = self._stats(a), self._stats(b)
        keys = sorted(set(sa) | set(sb))
        dlg = QDialog(self)
        dlg.setWindowTitle("历史对比")
        dlg.resize(900, 600)
        lay = QVBoxLayout(dlg)
        table = QTableWidget(len(keys), 4)
        table.setHorizontalHeaderLabels(["指标", a.collected_at, b.collected_at, "差值"])
        for i, key in enumerate(keys):
            va, vb = sa.get(key), sb.get(key)
            diff = ""
            try:
                diff = f"{float(vb) - float(va):+.6g}"
            except (TypeError, ValueError):
                pass
            for col, value in enumerate((key, va, vb, diff)):
                table.setItem(i, col, QTableWidgetItem("—" if value is None else str(value)))
        table.resizeColumnsToContents()
        lay.addWidget(table)
        close = QPushButton("关闭")
        close.clicked.connect(dlg.accept)
        lay.addWidget(close)
        dlg.exec()

    def export_selected(self):
        rec = self.selected()
        if rec is None:
            return QMessageBox.information(self, "提示", "请先选择一条历史记录")
        path, _ = QFileDialog.getSaveFileName(self, "导出历史记录", "history.json", "JSON (*.json)")
        if not path:
            return
        stats = self._stats(rec)
        data = {
            "source": rec.source_label, "collected_at": rec.collected_at,
            "location": {"lon": rec.lon, "lat": rec.lat},
            "time_range": [rec.start_date, rec.end_date], "label": rec.label,
            "output_dir": rec.output_dir, "stats": stats,
        }
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        QMessageBox.information(self, "完成", f"已导出：\n{path}")

    def delete_selected(self):
        rec = self.selected()
        if rec is None:
            return QMessageBox.information(self, "提示", "请先选择一条历史记录")
        if QMessageBox.question(
            self, "确认删除",
            "将删除这条历史的数据库记录；如果本地输出文件夹存在，也会删除。是否继续？",
        ) != QMessageBox.StandardButton.Yes:
            return
        errors = []
        if rec.pg_id is not None:
            ok, msg = self._pg_store().delete_collection_run(rec.pg_id)
            if not ok:
                errors.append("PostgreSQL：" + msg)
        if rec.available:
            try:
                shutil.rmtree(rec.output_dir)
            except Exception as e:
                errors.append("文件夹：" + str(e))
        if rec.sqlite_id is not None:
            try:
                from database.local_cache import get_cache
                get_cache().delete_collection(rec.sqlite_id)
            except Exception as e:
                errors.append("SQLite：" + str(e))
        self.refresh()
        if errors:
            QMessageBox.warning(self, "部分删除失败", "\n".join(errors))
