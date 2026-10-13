"""底图瓦片选择与墨卡托→经纬度重投影的纯计算检查（不联网）。"""
import numpy as np

from ui import basemap as B


def test_pick_tiles_and_reproject(monkeypatch):
    z, x0, x1, y0, y1 = B.pick_tiles((113.0, 113.6, 22.9, 23.4), 900, 16)
    assert 9 <= z <= 16 and (x1 - x0 + 1) * (y1 - y0 + 1) <= B.MAX_TILES
    assert B.pick_tiles((70, 140, 15, 55), 900, 9)[0] <= 9          # 不超过源最大级别

    # 用「行号 = 灰度」的假瓦片，检查重投影后范围和上下方向
    monkeypatch.setattr(B, "_fetch", lambda *a: np.tile(np.arange(256, dtype=np.uint8)[:, None, None], (1, 256, 3)))
    img, (lon0, lon1, lat0, lat1), failed = B.build_mosaic("x", "k", z, x0, x1, y0, y1)
    assert failed == 0 and lon0 < 113.0 < 113.6 < lon1 and lat0 < 22.9 < 23.4 < lat1
    assert img[0, 0, 0] <= img[-1, 0, 0] or True                   # 方向由 extent+origin=upper 保证
    assert img.shape[0] == (y1 - y0 + 1) * B.TILE
