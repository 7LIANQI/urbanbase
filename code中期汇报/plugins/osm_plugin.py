"""OSM 矢量数据插件：路网、建筑、绿地、水体。"""
import os

import requests
import geopandas as gpd
import osmnx as ox
from shapely.geometry import Polygon

from utils import make_logger
from config import OVERPASS_URL


# osmnx 全局代理配置（通过 _config 模块注入）
_osm_proxies = None


def _set_osmnx_proxy(proxies):
    """设置 osmnx 使用的代理（在调用前配置）。"""
    global _osm_proxies
    _osm_proxies = proxies
    if proxies:
        # osmnx 底层用 requests，通过配置注入
        import osmnx._http as ox_http
        # 注入代理到 osmnx 的 requests 会话
        ox.settings.requests_kwargs["proxies"] = proxies


def get_osm_vector_data(center_lon, center_lat, radius_m, output_dir,
                        log_callback=None, proxies=None):
    """获取 OSM 矢量数据（路网、建筑、绿地、水体）。

    Args:
        proxies: 可选，requests 格式的代理字典。
                 注意 osmnx 部分 API 调用会使用此代理。
    """
    log = make_logger(log_callback)
    point = (center_lat, center_lon)

    # 注入代理到 osmnx
    if proxies:
        try:
            ox.settings.requests_kwargs["proxies"] = proxies
        except Exception:
            pass  # 旧版 osmnx 可能不支持

    # ---- 路网 ----
    try:
        G = ox.graph_from_point(point, dist=radius_m, network_type='drive')
        if G.number_of_nodes() > 0:
            _nodes, edges = ox.graph_to_gdfs(G)
            if not edges.empty:
                edges.to_file(os.path.join(output_dir, "roads.geojson"), driver="GeoJSON")
            else:
                log("  路网数据为空，跳过保存")
        else:
            log("  未找到路网数据")
    except Exception as e:
        log(f"  获取路网数据失败: {e}")

    # ---- 建筑 ----
    try:
        buildings = ox.features_from_point(point, tags={"building": True}, dist=radius_m)
        if not buildings.empty:
            buildings.to_file(os.path.join(output_dir, "buildings.geojson"), driver="GeoJSON")
        else:
            log("  未找到建筑物数据")
    except Exception as e:
        log(f"  获取建筑物数据失败: {e}")

    # ---- 绿地 ----
    try:
        green_tags = {
            "landuse": ["grass", "forest", "recreation_ground", "meadow", "allotments"],
            "leisure": ["park", "garden", "nature_reserve", "golf_course", "playground"],
            "natural": ["grassland", "wood", "heath", "scrub"],
        }
        green = ox.features_from_point(point, tags=green_tags, dist=radius_m)
        if not green.empty:
            green.to_file(os.path.join(output_dir, "green_spaces.geojson"), driver="GeoJSON")
        else:
            log("  未找到绿地数据")
    except Exception as e:
        log(f"  获取绿地数据失败: {e}")

    # ---- 水体 (Overpass API) ----
    query = f"""
    [out:json][timeout:25];
    (
      way["natural"="water"](around:{radius_m},{center_lat},{center_lon});
      way["waterway"="river"](around:{radius_m},{center_lat},{center_lon});
      relation["natural"="water"](around:{radius_m},{center_lat},{center_lon});
    );
    out body;
    >;
    out skel qt;
    """
    try:
        resp = requests.get(OVERPASS_URL, params={"data": query},
                            timeout=30, proxies=proxies)
        if resp.status_code == 200:
            data = resp.json()
            features = data.get("elements", [])
            geom_list = []
            for feat in features:
                if feat["type"] == "way" and "geometry" in feat:
                    coords = []
                    valid = True
                    for p in feat["geometry"]:
                        try:
                            coords.append((float(p["lon"]), float(p["lat"])))
                        except (ValueError, TypeError, KeyError):
                            valid = False
                            break
                    if valid and len(coords) >= 3:
                        geom_list.append(Polygon(coords))
            if geom_list:
                gdf = gpd.GeoDataFrame(geometry=geom_list, crs="EPSG:4326")
                gdf.to_file(os.path.join(output_dir, "water_bodies.geojson"), driver="GeoJSON")
            else:
                log("  未找到有效水体数据")
        else:
            log(f"  水体请求失败，状态码: {resp.status_code}")
    except Exception as e:
        log(f"  获取水体数据时出错: {e}")

    # 清理代理设置
    if proxies:
        try:
            ox.settings.requests_kwargs.pop("proxies", None)
        except Exception:
            pass
