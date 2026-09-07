"""采集器基类。"""
import os
from datetime import datetime


class BaseCollector:
    """数据采集器抽象基类。

    所有采集器继承此类，实现 collect() 方法。
    """

    # 子类覆盖
    collector_name: str = "base"

    def __init__(self, lon, lat, radius, start_date, end_date,
                 output_dir, log, **kwargs):
        self.lon = lon
        self.lat = lat
        self.radius = radius
        self.start_date = start_date
        self.end_date = end_date
        self.output_dir = output_dir
        self.log = log
        self.kwargs = kwargs  # 额外参数（API keys 等）

    def collect(self):
        """执行采集，返回 {file_key: file_path} 字典。

        Returns:
            dict: 文件映射，用于构建 index.json 的 files 字段。
                  返回空 dict 表示无数据。
        """
        raise NotImplementedError

    # ---- 工具方法 ----

    @staticmethod
    def _timestamp():
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _path(self, filename):
        return os.path.join(self.output_dir, filename)

    def _ensure_dir(self, dirname):
        p = self._path(dirname)
        os.makedirs(p, exist_ok=True)
        return p
