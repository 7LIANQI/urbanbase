"""栅格值路网赋值：单位换算、人口密度、安全输出和停止。"""
import importlib.util
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString
from PyQt6.QtCore import QCoreApplication

_SPEC = importlib.util.spec_from_file_location(
    "road_assignment_tool",
    Path(__file__).resolve().parents[1] / "ui" / "raster_to_roads_window.py",
)
ROAD_TOOL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ROAD_TOOL)


def _qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


def _write_raster(path, values, scale=1.0, offset=0.0):
    with rasterio.open(
        path, "w", driver="GTiff", height=values.shape[0], width=values.shape[1],
        count=1, dtype="float32", crs="EPSG:3857",
        transform=from_origin(0, 100, 10, 10), nodata=-9999,
    ) as ds:
        ds.write(values.astype("float32"), 1)
        ds.scales = (scale,)
        ds.offsets = (offset,)


def _write_roads(path):
    gpd.GeoDataFrame(
        {"name": ["test"]},
        geometry=[LineString([(0, 50), (100, 50)])],
        crs="EPSG:3857",
    ).to_file(path)


def _run(worker):
    finished, errors, cancelled = [], [], []
    worker.finished.connect(finished.append)
    worker.error.connect(errors.append)
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.run()
    return finished, errors, cancelled


def test_interpolation_applies_scale_offset_and_gpkg(tmp_path):
    _qt_app()
    roads = tmp_path / "roads.gpkg"
    _write_roads(roads)
    raster = tmp_path / "value.tif"
    _write_raster(raster, np.ones((10, 10)), scale=0.1, offset=5.0)
    cfg = ROAD_TOOL.RasterConfig(str(raster))
    cfg.field_name = "地表温度_℃"
    cfg.unit = "℃"
    output = tmp_path / "result.gpkg"

    finished, errors, cancelled = _run(ROAD_TOOL.ProcessWorker(
        str(roads), [cfg], False, "", str(output)
    ))
    assert not errors and not cancelled and finished == [str(output)]
    result = gpd.read_file(output)
    assert abs(float(result["地表温度_℃"].iloc[0]) - 5.1) < 1e-6
    assert (tmp_path / "result_processing.json").exists()


def test_population_density_is_converted_by_pixel_area(tmp_path):
    _qt_app()
    roads = tmp_path / "roads.shp"
    _write_roads(roads)
    values = np.zeros((10, 10), dtype="float32")
    values[4, 2] = 1000.0                    # 人/km²；10 m 像元面积为 0.0001 km²
    raster = tmp_path / "density.tif"
    _write_raster(raster, values)
    cfg = ROAD_TOOL.RasterConfig(str(raster))
    cfg.field_name = "pop"
    cfg.algorithm = "population"
    cfg.value_kind = "density"
    cfg.threshold_km = 0.1

    output = tmp_path / "population.shp"
    _, errors, cancelled = _run(ROAD_TOOL.ProcessWorker(
        str(roads), [cfg], False, "", str(output)
    ))
    assert not errors and not cancelled
    result = gpd.read_file(output)
    assert abs(float(result["pop"].iloc[0]) - 0.1) < 1e-8


def test_mean_rejects_unknown_or_different_units(tmp_path):
    _qt_app()
    roads = tmp_path / "roads.shp"
    _write_roads(roads)
    first, second = tmp_path / "a.tif", tmp_path / "b.tif"
    _write_raster(first, np.ones((10, 10)))
    _write_raster(second, np.ones((10, 10)))
    configs = []
    for path, field, unit in ((first, "a", "℃"), (second, "b", "mm")):
        cfg = ROAD_TOOL.RasterConfig(str(path))
        cfg.field_name, cfg.unit = field, unit
        configs.append(cfg)
    output = tmp_path / "mean.shp"
    _, errors, cancelled = _run(ROAD_TOOL.ProcessWorker(
        str(roads), configs, True, "mean", str(output)
    ))
    assert errors and "单位不一致" in errors[0]
    assert not cancelled and not output.exists()


def test_update_mode_creates_backup(tmp_path):
    _qt_app()
    roads = tmp_path / "roads.shp"
    _write_roads(roads)
    raster = tmp_path / "value.tif"
    _write_raster(raster, np.ones((10, 10)))
    cfg = ROAD_TOOL.RasterConfig(str(raster))
    cfg.field_name = "value"

    _, errors, cancelled = _run(ROAD_TOOL.ProcessWorker(
        str(roads), [cfg], False, "", str(roads), update_mode=True
    ))
    assert not errors and not cancelled
    backups = list(tmp_path.glob("roads_backup_*.shp"))
    assert len(backups) == 1 and backups[0].exists()
    assert "value" in gpd.read_file(roads).columns


def test_stop_does_not_write_partial_output(tmp_path):
    _qt_app()
    roads = tmp_path / "roads.shp"
    _write_roads(roads)
    raster = tmp_path / "value.tif"
    _write_raster(raster, np.ones((10, 10)))
    cfg = ROAD_TOOL.RasterConfig(str(raster))
    cfg.field_name = "value"
    output = tmp_path / "stopped.shp"
    worker = ROAD_TOOL.ProcessWorker(str(roads), [cfg], False, "", str(output))
    worker.stop_event.set()

    finished, errors, cancelled = _run(worker)
    assert not finished and not errors and cancelled == [True]
    assert not output.exists()
