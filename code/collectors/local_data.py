"""本地数据采集器 —— 查询 PostgreSQL 本地库。"""
import json
import os

from .base import BaseCollector


class LocalDataCollector(BaseCollector):
    """从本地 PostgreSQL 库查询历史采集结果 + 导师导入的本地数据。

    与其他采集器（调外部 API）不同，本采集器读取本地库，
    把附近位置/时间范围内的历史记录与外部数据落成文件。
    """

    collector_name = "local_data"

    def collect(self):
        try:
            from pg_store import get_store
        except ImportError:
            self.log("⚠️ pg_store 模块不可用，跳过本地数据")
            return {}

        store = get_store()
        try:
            # 查询该位置附近的全部历史采集（不受本次分析时间窗限制）
            result = store.query_local(self.lon, self.lat, self.radius)
        except Exception as e:
            self.log(f"⚠️ 本地库查询失败: {e}")
            return {}

        files = {}

        # 历史采集记录 + 指标（写入一份完整 JSON）
        if result["runs"] or result["metrics"]:
            history_path = self._path("local_history.json")
            with open(history_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2, default=str)
            files["local_history"] = history_path
            self.log(
                f"  本地历史: {len(result['runs'])} 次采集, "
                f"{len(result['metrics'])} 条指标"
            )

        # 指标导出为 CSV（便于表格浏览）
        if result["metrics"]:
            csv_path = self._write_metrics_csv(result["metrics"])
            if csv_path:
                files["local_metrics"] = csv_path

        # 导师导入的本地数据
        if result["local_records"]:
            records_path = self._path("local_records.json")
            with open(records_path, "w", encoding="utf-8") as f:
                json.dump(result["local_records"], f,
                          ensure_ascii=False, indent=2, default=str)
            files["local_records"] = records_path
            self.log(f"  导师本地数据: {len(result['local_records'])} 条")

        if not files:
            self.log(
                f"  该位置 ({self.lon:.4f}, {self.lat:.4f}) 附近暂无本地数据"
            )

        return files

    def _write_metrics_csv(self, metrics):
        try:
            import pandas as pd
        except ImportError:
            return None
        if not metrics:
            return None
        df = pd.DataFrame(metrics)
        path = self._path("local_metrics.csv")
        df.to_csv(path, index=False, encoding="utf-8-sig")
        return path
