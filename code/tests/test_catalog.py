"""数据源目录：key 唯一、输出列名全局不冲突、设置读取有默认值。"""
from plugins import gee_catalog as C


class _S(dict):
    def value(self, k, d=""):
        return self.get(k, d)


def test_catalog():
    keys = [s.key for c in C.CATEGORIES for s in c.sources]
    assert len(keys) == len(set(keys))
    for c in C.CATEGORIES:
        assert c.sources and all(s.category == c.key and s.mode in ("series", "nearest", "static") for s in c.sources)
    # 同类别的不同来源列名互不相同，不同类别之间也不冲突（允许同类别内部来源互斥，所以只查跨类别）
    seen = {}
    for c in C.CATEGORIES:
        for s in c.sources:
            for col in s.columns:
                assert seen.setdefault(col, c.key) == c.key, col
    assert C.selected_source("pop", _S()).key == "pop.worldpop"
    assert C.selected_source("pop", _S({"gee_sources/pop": "pop.ghs"})).key == "pop.ghs"
    assert C.selected_source("pop", _S({"gee_sources/pop": "dem.srtm"})).key == "pop.worldpop"   # 非法值回退默认


def test_origin_badges():
    S = C.SOURCE_BY_KEY
    for k in ("t2m.era5", "t2m.era5m", "precip.era5", "precip.era5m", "srad.era5", "lst.era5"):
        assert S[k].origin == "model" and "模式" in S[k].badge() and "模式" in S[k].html() and "模式" in S[k].text(), k
    assert S["precip.terra"].origin == "blend" and S["t2m.terra"].origin == "blend"
    assert S["precip.chirps"].origin == "" and S["precip.chirps"].badge() == ""
    assert S["precip.era5m"].temporal == "mean" and S["t2m.era5m"].columns == ["TAVG_ERA5M", "TMAX_ERA5M", "TMIN_ERA5M"]
    assert "2024-12" in S["precip.terra"].coverage
