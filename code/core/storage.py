"""应用数据目录与默认栅格库。"""
import os
from pathlib import Path


def default_raster_root():
    configured = os.environ.get("URBANSENSE_RASTER_ROOT", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "环境数据" / "COG库"


def ensure_raster_root(settings):
    """读取栅格根目录；首次使用时自动创建默认目录并写回设置。"""
    text = str(settings.value("paths/raster_root", "") or "").strip()
    root = Path(text) if text else default_raster_root()
    root.mkdir(parents=True, exist_ok=True)
    if not text:
        settings.setValue("paths/raster_root", str(root))
        settings.sync()
    return str(root)
