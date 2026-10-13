"""底图：XYZ 瓦片（Web 墨卡托）下载、磁盘缓存、拼接并重投影为经纬度等距图像。"""
import hashlib
import io
import math
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from PIL import Image
from PyQt6.QtCore import QThread, pyqtSignal

CACHE_DIR = Path.home() / ".urbansense" / "tiles"
_ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/{}/MapServer/tile/{{z}}/{{y}}/{{x}}"

# key: (显示名, URL 模板, 最大缩放级别, 版权说明)
BASEMAPS = {
    "esri_terrain": ("Esri 地形（浅色晕渲）", _ESRI.format("World_Terrain_Base"), 9,
                     "Esri, USGS, NOAA"),
    "esri_gray": ("Esri 浅灰画布", _ESRI.format("Canvas/World_Light_Gray_Base"), 16,
                  "Esri, HERE, Garmin, OpenStreetMap contributors"),
    "esri_topo": ("Esri 地形图", _ESRI.format("World_Topo_Map"), 17,
                  "Esri, HERE, Garmin, USGS, NGA"),
    "esri_street": ("Esri 街道图", _ESRI.format("World_Street_Map"), 17,
                    "Esri, HERE, Garmin, OpenStreetMap contributors"),
    "esri_image": ("Esri 卫星影像", _ESRI.format("World_Imagery"), 17,
                   "Esri, Maxar, Earthstar Geographics"),
    "carto_light": ("CARTO 浅色", "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png", 18,
                    "© OpenStreetMap contributors, © CARTO"),
    "osm": ("OpenStreetMap", "https://tile.openstreetmap.org/{z}/{x}/{y}.png", 18,
            "© OpenStreetMap contributors"),
}
DEFAULT = "esri_terrain"
TILE = 256
MAX_TILES = 64


def _lat_of_row(y, z):
    return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / 2 ** z))))


def _merc(lat):
    r = math.radians(max(-85.05, min(85.05, lat)))
    return math.log(math.tan(math.pi / 4 + r / 2))


def pick_tiles(extent, width_px, maxz):
    """按视野与屏幕宽度选缩放级别，返回 (z, x0, x1, y0, y1)。"""
    x0, x1, y0, y1 = extent
    x0, x1 = max(-180.0, min(x0, x1)), min(180.0, max(x0, x1))
    y0, y1 = max(-85.05, min(y0, y1)), min(85.05, max(y0, y1))
    span = max(x1 - x0, 1e-6)
    z = int(round(math.log2(max(width_px, 256) / TILE * 360 / span)))
    z = max(0, min(maxz, z))
    while True:
        n = 2 ** z
        tx0, tx1 = int((x0 + 180) / 360 * n), int((x1 + 180) / 360 * n)
        ty0 = int((1 - math.asinh(math.tan(math.radians(y1))) / math.pi) / 2 * n)
        ty1 = int((1 - math.asinh(math.tan(math.radians(y0))) / math.pi) / 2 * n)
        tx0, tx1 = max(0, tx0), min(n - 1, tx1)
        ty0, ty1 = max(0, ty0), min(n - 1, ty1)
        if (tx1 - tx0 + 1) * (ty1 - ty0 + 1) <= MAX_TILES or z == 0:
            return z, tx0, tx1, ty0, ty1
        z -= 1


def _fetch(url_tpl, key, z, x, y):
    url = url_tpl.format(z=z, x=x, y=y)
    cache = CACHE_DIR / key / str(z) / str(x) / f"{y}.tile"
    try:
        if cache.exists():
            data = cache.read_bytes()
        else:
            r = requests.get(url, timeout=8, headers={"User-Agent": "UrbanSense/1.0"})
            r.raise_for_status()
            data = r.content
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(data)
        return np.asarray(Image.open(io.BytesIO(data)).convert("RGB").resize((TILE, TILE)))
    except Exception:
        return None


def build_mosaic(url_tpl, key, z, tx0, tx1, ty0, ty1):
    """下载并拼接瓦片，重投影为经纬度等距。返回 (RGB 数组, (lon0, lon1, lat0, lat1), 失败瓦片数)。"""
    coords = [(x, y) for y in range(ty0, ty1 + 1) for x in range(tx0, tx1 + 1)]
    with ThreadPoolExecutor(8) as ex:
        tiles = list(ex.map(lambda c: _fetch(url_tpl, key, z, c[0], c[1]), coords))
    nx, ny = tx1 - tx0 + 1, ty1 - ty0 + 1
    mosaic = np.full((ny * TILE, nx * TILE, 3), 255, np.uint8)
    failed = 0
    for (x, y), t in zip(coords, tiles):
        if t is None:
            failed += 1
            continue
        r, c = (y - ty0) * TILE, (x - tx0) * TILE
        mosaic[r:r + TILE, c:c + TILE] = t
    n = 2 ** z
    lon0, lon1 = tx0 / n * 360 - 180, (tx1 + 1) / n * 360 - 180
    lat_top, lat_bot = _lat_of_row(ty0, z), _lat_of_row(ty1 + 1, z)
    # 墨卡托 → 经纬度等距：按纬度均匀取行
    H = mosaic.shape[0]
    lats = np.linspace(lat_top, lat_bot, H)
    mt, mb = _merc(lat_top), _merc(lat_bot)
    src_rows = np.clip(((mt - np.array([_merc(v) for v in lats])) / (mt - mb) * (H - 1)).round().astype(int), 0, H - 1)
    return mosaic[src_rows], (lon0, lon1, lat_bot, lat_top), failed


class TileWorker(QThread):
    ready = pyqtSignal(object, object, int, int)    # 图像, 范围, token, 失败数

    def __init__(self, key, extent, width_px, token):
        super().__init__()
        self.key, self.extent, self.width, self.token = key, extent, width_px, token

    def run(self):
        _, tpl, maxz, _ = BASEMAPS[self.key]
        cache_key = hashlib.md5(tpl.encode()).hexdigest()[:8]
        z, x0, x1, y0, y1 = pick_tiles(self.extent, self.width, maxz)
        img, ext, failed = build_mosaic(tpl, cache_key, z, x0, x1, y0, y1)
        self.ready.emit(img, ext, self.token, failed)
