"""数据采集 Worker 线程。"""
from PyQt6.QtCore import QThread, pyqtSignal

from pipeline import process_location


class Worker(QThread):
    """后台执行多点位数据采集的工作线程。"""

    log = pyqtSignal(str)
    progress = pyqtSignal(int)
    finished = pyqtSignal(list)
    result_ready = pyqtSignal(str)
    step_progress = pyqtSignal(str, int, int)  # (step_name, current, total)

    def __init__(self, tasks, map_key, rs_key, gee_key_path,
                 options, file_logger=None, output_base_dir=None):
        super().__init__()
        self.tasks = tasks
        self.map_key = map_key
        self.rs_key = rs_key
        self.gee_key_path = gee_key_path
        self.options = options       # 细粒度选项 dict
        self._file_logger = file_logger
        self._output_base_dir = output_base_dir
        self._is_running = True

    def _emit_log(self, msg):
        """将日志消息转发到 GUI 和文件日志。"""
        self.log.emit(msg)
        if self._file_logger:
            self._file_logger(msg)

    def run(self):
        output_dirs = []
        total = len(self.tasks)

        for i, task in enumerate(self.tasks, 1):
            # 支持 5 元组 (lon, lat, r, sd, ed) 和 6 元组 (lon, lat, r, sd, ed, label)
            if len(task) == 6:
                lon, lat, r, sd, ed, slice_label = task
            else:
                lon, lat, r, sd, ed = task
                slice_label = None
            if not self._is_running:
                self.log.emit("🛑 任务被用户中断")
                break

            self.log.emit(f"▶ 开始处理：经度 {lon}, 纬度 {lat}")
            self.step_progress.emit(f"点位 {i}/{total}", i - 1, total)

            # 使用带步骤回调的日志器
            collector_count = [0]
            collector_total = [0]

            def step_callback(name, current, _total):
                collector_total[0] = _total
                collector_count[0] = current
                self.step_progress.emit(name, current, _total)

            try:
                out_dir = process_location(
                    lon, lat, r, sd, ed,
                    baidu_key=self.map_key,
                    openweather_key=self.rs_key,
                    gee_key_path=self.gee_key_path,
                    log_callback=self._emit_log,
                    output_base_dir=self._output_base_dir,
                    options=self.options,
                    step_callback=step_callback,
                    label=slice_label,
                )
                output_dirs.append(out_dir)
                self.result_ready.emit(out_dir)
                self.log.emit(f"✅ 完成，输出目录: {out_dir}")
            except Exception as e:
                self.log.emit(f"❌ 错误: {e}")

            progress_val = int((i / total) * 100)
            self.progress.emit(progress_val)

        self.step_progress.emit("完成", total, total)
        self.finished.emit(output_dirs)

    def stop(self):
        self._is_running = False
