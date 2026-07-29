"""城市数据采集插件包。"""

from .air_quality_plugin import get_air_quality_by_lonlat
from .weather_plugin import get_weather_by_lonlat
from .streetview_plugin import get_streetview_metadata, download_streetview_image
from .gee_plugin import (
    initialize_gee,
    get_gee_stats,
    get_era5_climate_stats,
    get_era5_hourly_stats,
    get_elevation_stats,
    get_precipitation_stats,
    get_ndwi_evi_stats,
    get_population_stats,
    get_landcover_stats,
    get_s5p_no2_stats,
    get_jrc_water_stats,
    get_modis_lst_stats,
    get_dynamic_world_stats,
    get_hansen_forest_stats,
    get_canopy_height_stats,
)
from .osm_plugin import get_osm_vector_data, compute_osm_stats

__all__ = [
    "get_air_quality_by_lonlat",
    "get_weather_by_lonlat",
    "get_streetview_metadata",
    "download_streetview_image",
    "initialize_gee",
    "get_gee_stats",
    "get_era5_climate_stats",
    "get_era5_hourly_stats",
    "get_elevation_stats",
    "get_precipitation_stats",
    "get_ndwi_evi_stats",
    "get_population_stats",
    "get_landcover_stats",
    "get_s5p_no2_stats",
    "get_jrc_water_stats",
    "get_modis_lst_stats",
    "get_dynamic_world_stats",
    "get_hansen_forest_stats",
    "get_canopy_height_stats",
    "get_osm_vector_data",
    "compute_osm_stats",
]
