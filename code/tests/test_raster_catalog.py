"""栅格目录：命名规则、缺期/多余/重复检查、COG 转换与日期识别。"""
import numpy as np
import rasterio
from rasterio.transform import from_origin

from core import cog
from core import raster_catalog as RC


def _tif(path, crs="EPSG:4326", nodata=-9999.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    kw = dict(driver="GTiff", height=64, width=64, count=1, dtype="float32", transform=from_origin(100, 30, .01, .01))
    if crs:
        kw["crs"] = crs
    if nodata is not None:
        kw["nodata"] = nodata
    with rasterio.open(path, "w", **kw) as d:
        d.write(np.random.rand(64, 64).astype("float32"), 1)


def test_catalog_checks(tmp_path):
    s = RC.Series(id="ndvi_x_month", temporal="month", start="2020-01", end="2020-06", crs="EPSG:4326", folder=tmp_path / "veg" / "ndvi_x_month")
    s.save()
    for ym in ("202001", "202002", "202004", "202007"):               # 缺 03、05、06；多出 07
        _tif(s.folder / ym[:4] / f"ndvi_x_month_{ym}.tif")
    _tif(s.folder / "bad_name.tif")                                    # 命名不符
    _tif(s.folder / "dup" / "ndvi_x_month_202001.tif")                 # 重复
    msgs = [(i.level, i.message) for i in RC.check(tmp_path)]
    text = "\n".join(m for _, m in msgs)
    assert "缺 3 期" in text and "202003" not in text.split("缺 3 期")[0]
    assert "时间范围之外" in text and "同一日期" in text and "文件名不符合规则" in text
    assert RC.load_all(tmp_path)[0][0].id == "ndvi_x_month"
    # 区间取文件
    from datetime import date
    got = s.files_between(date(2020, 2, 1), date(2020, 5, 1))
    assert [p.name for p in got] == ["ndvi_x_month_202002.tif", "ndvi_x_month_202004.tif"]


def test_deep_check_and_cog(tmp_path):
    s = RC.Series(id="dem_a", temporal="static", crs="EPSG:3857", folder=tmp_path / "dem_a")
    s.save()
    _tif(s.folder / "dem_a.tif")
    deep = " ".join(i.message for i in RC.check(tmp_path, deep=True))
    assert "不一致" in deep and "不是 COG" in deep
    # 转 COG，并给缺坐标系的文件补坐标系
    src = tmp_path / "raw_201507.tif"
    _tif(src, crs=None, nodata=None)
    out = cog.to_cog(src, tmp_path / "out.tif", assign_crs="EPSG:4326", assign_nodata=-9999)
    with rasterio.open(out) as ds:
        assert ds.crs.to_epsg() == 4326 and ds.nodata == -9999 and ds.profile["tiled"]
    assert cog.find_date("MOD_NDVI_2015-07.tif", "month") == (2015, 7)
    assert cog.find_date("a_20150715_b.tif", "day") == (2015, 7, 15)
    assert cog.find_date("nodate.tif", "year") is None


def test_naming_and_reproject(tmp_path):
    assert cog.render_name("{id}_{date}", "MOD_2019-07.tif", "ndvi", (2019, 7), "month") == "ndvi_201907.tif"
    assert cog.render_name("{YYYY}{MM}_{name}", "a.tif", "", (2020, 3), "month") == "202003_a.tif"
    assert cog.find_date("x_2019193.tif", "day", "doy") == (2019, 7, 12)
    assert cog.find_date("img_2020_07.tif", "month", "regex", r"(?P<Y>\d{4})_(?P<M>\d{2})") == (2020, 7)
    # UTM 49N 源 → WGS84：应被重投影，输出坐标系为 4326，边缘用 -9999
    src = tmp_path / "utm.tif"
    with rasterio.open(src, "w", driver="GTiff", height=50, width=50, count=1, dtype="float32", crs="EPSG:32649",
                       transform=from_origin(700000, 2600000, 1000, 1000)) as d:
        d.write(np.ones((50, 50), "float32"), 1)
    from rasterio.crs import CRS
    assert cog.crs_action(CRS.from_epsg(32649), "EPSG:4326")[0] == "reproject"
    assert cog.crs_action(CRS.from_epsg(4326), "EPSG:4326")[0] == "same"
    assert cog.crs_action(CRS.from_epsg(4490), "EPSG:4326")[0] == "relabel"
    assert cog.crs_action(None, "EPSG:4326")[0] == "missing"
    out = cog.to_cog(src, tmp_path / "wgs.tif", target_crs="EPSG:4326")
    with rasterio.open(out) as ds:
        assert ds.crs.to_epsg() == 4326 and ds.nodata == -9999 and 110 < ds.bounds.left < 120


def test_multi_grid(tmp_path):
    def tif_size(path, n):
        path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(path, "w", driver="GTiff", height=n, width=n, count=1, dtype="float32", crs="EPSG:4326",
                           transform=from_origin(100, 30, 1 / n, 1 / n)) as d:
            d.write(np.zeros((n, n), "float32"), 1)
    s = RC.Series(id="air_x", temporal="year", start="2018", end="2019", folder=tmp_path / "airq" / "air_x")
    s.save()
    tif_size(s.folder / "air_x_2018.tif", 10)      # 10 km
    tif_size(s.folder / "air_x_2019.tif", 100)     # 1 km
    err = [i for i in RC.check(tmp_path, deep=True) if i.level == "error"]
    assert any("网格应相同" in i.message for i in err)
    s.multi_grid = True
    s.save()
    issues = RC.check(tmp_path, deep=True)
    assert not [i for i in issues if i.level == "error"] and any("2 种不同的网格" in i.message for i in issues)


def test_netcdf_layers(tmp_path):
    import xarray as xr
    lat = np.linspace(40, 30, 20)                  # 北→南
    lon = np.linspace(100, 110, 30)
    data = (np.arange(12 * 20 * 30).reshape(12, 20, 30) % 3000).astype("int16")
    data[0, 0, 0] = -32768
    ds = xr.Dataset({"tmp": (("time", "lat", "lon"), data, {"missing_value": -32768.0})},
                    coords={"time": np.arange(1.0, 13.0), "lat": lat, "lon": lon})
    f = tmp_path / "tmp_2012.nc"
    ds.to_netcdf(f, encoding={"tmp": {"dtype": "int16", "_FillValue": None}})
    info = cog.nc_describe(f)
    assert info["n"] == 12 and info["dates"][2] == (2012, 3, 1) and info["nodata"] == -32768.0 and info["crs"].to_epsg() == 4326
    out = cog.nc_layer_to_cog(f, "tmp", 2, tmp_path / "m3.tif")
    with rasterio.open(out) as d:
        assert np.array_equal(d.read(1), data[2]) and d.dtypes[0] == "int16" and d.nodata == -32768.0 and d.profile["tiled"]
        assert d.bounds.top > 40 and d.bounds.bottom < 30                  # 北在上、范围含半个像元
    # 纬度由南向北：输出翻成北在上，数值一一对应
    ds2 = ds.assign_coords(lat=lat[::-1]).isel(lat=slice(None, None, 1))
    ds2["tmp"] = (("time", "lat", "lon"), data[:, ::-1, :], {"missing_value": -32768.0})
    f2 = tmp_path / "up.nc"
    ds2.to_netcdf(f2, encoding={"tmp": {"dtype": "int16", "_FillValue": None}})
    with rasterio.open(cog.nc_layer_to_cog(f2, "tmp", 0, tmp_path / "up0.tif")) as d:
        assert np.array_equal(d.read(1), data[0])


def test_daily_to_monthly(tmp_path):
    from core.aggregate import daily_to_monthly
    src = RC.Series(id="d_x", temporal="day", folder=tmp_path / "d_x")
    src.save()
    for day in (1, 2, 3):
        a = np.full((4, 4), float(day * 2), "float32")
        a[0, 0] = np.nan                         # 全月无效
        if day == 3:
            a[1, 1] = np.nan                     # 缺一天
        p = src.folder / f"d_x_202001{day:02d}.tif"
        p.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(p, "w", driver="GTiff", height=4, width=4, count=1, dtype="float32", crs="EPSG:4326",
                           transform=from_origin(100, 30, 1, 1), nodata=np.nan) as d:
            d.write(a, 1)
    out = RC.Series(id="m_x", temporal="month", folder=tmp_path / "m_x")
    recs = daily_to_monthly(src, out, "mean", log=lambda *_: None)
    assert recs == [("202001", 3, 31)]
    with rasterio.open(out.folder / "2020" / "m_x_202001.tif") as d:
        r = d.read(1)
        assert r[2, 2] == 4.0 and r[1, 1] == 3.0 and np.isnan(r[0, 0]) and d.profile["tiled"]
