"""数据采集 Worker 线程。"""
from PyQt6.QtCore import QThread, pyqtSignal

from main1 import process_location


class Worker(QThread):
    """后台执行多点位数据采集的工作线程。"""

    log = pyqtSignal(str)
    progress = pyqtSignal(int)
    finished = pyqtSignal(list)
    result_ready = pyqtSignal(str)

    def __init__(self, tasks, map_key, rs_key, gee_key_path,
                 enable_air, enable_street, enable_gee, enable_osm):
        super().__init__()
        self.tasks = tasks
        self.map_key = map_key
        self.rs_key = rs_key
        self.gee_key_path = gee_key_path
        self.enable_air = enable_air
        self.enable_street = enable_street
        self.enable_gee = enable_gee
        self.enable_osm = enable_osm
        self._is_running = True

    def run(self):
        output_dirs = []
        total = len(self.tasks)

        for i, (lon, lat, r, sd, ed) in enumerate(self.tasks, 1):
            if not self._is_running:
                self.log.emit("🛑 任务被用户中断")
                break

            self.log.emit(f"▶ 开始处理：经度 {lon}, 纬度 {lat}")
            try:
                def log_callback(msg):
                    self.log.emit(msg)

                out_dir = process_location(
                    lon, lat, r, sd, ed,
                    baidu_key=self.map_key,
                    openweather_key=self.rs_key,
                    gee_key_path=self.gee_key_path,
                    enable_air_quality=self.enable_air,
                    enable_streetview=self.enable_street,
                    enable_gee=self.enable_gee,
                    enable_osm=self.enable_osm,
                    log_callback=log_callback,
                )
                output_dirs.append(out_dir)
                self.result_ready.emit(out_dir)
                self.log.emit(f"✅ 完成，输出目录: {out_dir}")
            except Exception as e:
                self.log.emit(f"❌ 错误: {e}")

            progress_val = int((i / total) * 100)
            self.progress.emit(progress_val)

        self.finished.emit(output_dirs)

    def stop(self):
        self._is_running = False
