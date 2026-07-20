"""OSM 矢量数据插件：路网、建筑、绿地、水体。"""
import os

import geopandas as gpd
import osmnx as ox

from utils import make_logger


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

    # ---- 水体 (通过 osmnx，稳健的重试+缓存机制) ----
    try:
        water_tags = {
            "natural": ["water", "bay", "strait"],
            "waterway": ["river", "riverbank", "canal", "stream"],
            "water": True,
        }
        water = ox.features_from_point(point, tags=water_tags, dist=radius_m)
        if not water.empty:
            water.to_file(os.path.join(output_dir, "water_bodies.geojson"), driver="GeoJSON")
        else:
            log("  未找到水体数据（该区域可能无水域）")
    except Exception as e:
        log(f"  获取水体数据失败: {e}")

    # 清理代理设置
    if proxies:
        try:
            ox.settings.requests_kwargs.pop("proxies", None)
        except Exception:
            pass


def compute_osm_stats(output_dir, radius_m, log_callback=None):
    """基于已下载的 OSM GeoJSON 文件计算统计指标。

    输出 osm_stats.json，包含:
        - 建筑: 数量、总面积(m²)、建筑覆盖率(%)
        - 路网: 总长度(m)、路网密度(km/km²)、交叉口数量
        - 绿地: 总面积(m²)、体积估算(m³)
    """
    import json
    import math
    import geopandas as gpd
    from shapely.geometry import shape

    log = make_logger(log_callback)
    log("  计算 OSM 统计指标...")

    # 圆形缓冲区总面积 (m²)
    buffer_area_m2 = math.pi * (radius_m ** 2)
    buffer_area_km2 = buffer_area_m2 / 1e6

    # 从 GeoJSON 文件推断中心经度以选取合适的 UTM 投影
    center_lon = _guess_center_lon(output_dir)
    utm_crs = _get_utm_crs(center_lon)

    stats = {
        "radius_m": radius_m,
        "buffer_area_m2": round(buffer_area_m2, 1),
        "buffer_area_km2": round(buffer_area_km2, 4),
        "buildings": {},
        "roads": {},
        "green_spaces": {},
    }

    # ---- 建筑统计 ----
    buildings_path = os.path.join(output_dir, "buildings.geojson")
    if os.path.exists(buildings_path):
        try:
            gdf = gpd.read_file(buildings_path)
            if not gdf.empty and gdf.crs is None:
                gdf = gdf.set_crs("EPSG:4326")

            if not gdf.empty:
                # 投影到 UTM 计算精确面积
                gdf_proj = gdf.to_crs(utm_crs)
                building_areas = gdf_proj.geometry.area  # m²
                total_area = building_areas.sum()
                coverage = (total_area / buffer_area_m2) * 100 if buffer_area_m2 > 0 else 0

                stats["buildings"] = {
                    "建筑数量": len(gdf_proj),
                    "建筑总面积_m2": round(total_area, 1),
                    "建筑覆盖率_pct": round(coverage, 2),
                    "平均建筑占地面积_m2": round(total_area / len(gdf_proj), 1) if len(gdf_proj) > 0 else 0,
                }
                log(f"    建筑: {stats['buildings']['建筑数量']} 栋, "
                    f"总面积 {stats['buildings']['建筑总面积_m2']:.0f} m², "
                    f"覆盖率 {stats['buildings']['建筑覆盖率_pct']:.1f}%")
            else:
                log("    建筑数据为空，跳过统计")
        except Exception as e:
            log(f"    建筑统计计算失败: {e}")

    # ---- 路网统计 ----
    roads_path = os.path.join(output_dir, "roads.geojson")
    if os.path.exists(roads_path):
        try:
            gdf = gpd.read_file(roads_path)
            if not gdf.empty and gdf.crs is None:
                gdf = gdf.set_crs("EPSG:4326")

            if not gdf.empty:
                # 投影到 UTM 计算精确长度
                gdf_proj = gdf.to_crs(utm_crs)
                road_lengths = gdf_proj.geometry.length  # m
                total_length_m = road_lengths.sum()
                road_density = (total_length_m / 1000) / buffer_area_km2 if buffer_area_km2 > 0 else 0

                stats["roads"] = {
                    "道路总长度_m": round(total_length_m, 1),
                    "道路总长度_km": round(total_length_m / 1000, 2),
                    "路网密度_km_per_km2": round(road_density, 2),
                    "路段数量": len(gdf_proj),
                }

                # 交叉口数量 —— 通过 osmnx 重新获取图结构来统计
                intersection_count = _count_intersections_from_graph(output_dir)
                stats["roads"]["交叉口数量"] = intersection_count

                log(f"    路网: {stats['roads']['道路总长度_km']:.2f} km, "
                    f"密度 {stats['roads']['路网密度_km_per_km2']:.2f} km/km², "
                    f"交叉口 {intersection_count} 个")
            else:
                log("    路网数据为空，跳过统计")
        except Exception as e:
            log(f"    路网统计计算失败: {e}")

    # ---- 绿地统计 ----
    green_path = os.path.join(output_dir, "green_spaces.geojson")
    if os.path.exists(green_path):
        try:
            gdf = gpd.read_file(green_path)
            if not gdf.empty and gdf.crs is None:
                gdf = gdf.set_crs("EPSG:4326")

            if not gdf.empty:
                gdf_proj = gdf.to_crs(utm_crs)
                green_areas = gdf_proj.geometry.area  # m²
                total_green_area = green_areas.sum()

                # 估算绿地体积：根据 OSM 标签赋予典型植被高度
                estimated_volume = _estimate_green_volume(gdf_proj)

                stats["green_spaces"] = {
                    "绿地总面积_m2": round(total_green_area, 1),
                    "绿地总面积_km2": round(total_green_area / 1e6, 4),
                    "绿地覆盖率_pct": round((total_green_area / buffer_area_m2) * 100, 2) if buffer_area_m2 > 0 else 0,
                    "绿地斑块数量": len(gdf_proj),
                    "绿地体积估算_m3": round(estimated_volume, 1),
                }
                log(f"    绿地: 面积 {stats['green_spaces']['绿地总面积_m2']:.0f} m², "
                    f"覆盖率 {stats['green_spaces']['绿地覆盖率_pct']:.1f}%, "
                    f"体积估算 {stats['green_spaces']['绿地体积估算_m3']:.0f} m³")
            else:
                log("    绿地数据为空，跳过统计")
        except Exception as e:
            log(f"    绿地统计计算失败: {e}")

    # 保存统计结果
    stats_path = os.path.join(output_dir, "osm_stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    log(f"  OSM 统计已保存至 osm_stats.json")

    return stats


def _guess_center_lon(output_dir):
    """从任意已存在的 GeoJSON 文件推断中心经度。"""
    import json
    for name in ["roads.geojson", "buildings.geojson", "green_spaces.geojson"]:
        path = os.path.join(output_dir, name)
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                coords = data.get('features', [{}])[0].get('geometry', {}).get('coordinates', [])
                if coords:
                    # 提取第一个坐标的经度
                    if isinstance(coords[0], (int, float)):
                        return coords[0]
                    elif isinstance(coords[0], list) and len(coords[0]) > 0:
                        first_pt = coords[0]
                        while isinstance(first_pt, list) and len(first_pt) > 0 and isinstance(first_pt[0], list):
                            first_pt = first_pt[0]
                        if isinstance(first_pt, list) and len(first_pt) >= 2:
                            return first_pt[0]
            except Exception:
                continue
    return 116.0  # 默认北京经度


def _get_utm_crs(lon):
    """根据经度获取 WGS84 UTM EPSG 编码（北半球）。"""
    zone = int((lon + 180) // 6) + 1
    # EPSG:32601-32660 = WGS84 UTM Zone 1N-60N
    return f"EPSG:326{zone:02d}"


def _count_intersections_from_graph(output_dir):
    """通过尝试从已保存路网数据或 osmnx 图结构估算交叉口数量。

    交叉口定义：度数 >= 3 的路网节点（即有 >= 3 条道路交汇的点）。
    优先使用已保存的 edges GeoJSON 反推节点度。
    """
    try:
        import networkx as nx
        import geopandas as gpd
        from shapely.geometry import Point

        edges_path = os.path.join(output_dir, "roads.geojson")
        if not os.path.exists(edges_path):
            return 0

        gdf = gpd.read_file(edges_path)

        # 从 edges GeoDataFrame 构建简化图来数交叉口
        G = nx.Graph()
        for _, row in gdf.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            coords = list(geom.coords)
            for i in range(len(coords) - 1):
                u = (round(coords[i][0], 6), round(coords[i][1], 6))
                v = (round(coords[i + 1][0], 6), round(coords[i + 1][1], 6))
                G.add_edge(u, v)

        # 度数 >= 3 的节点为交叉口
        intersections = sum(1 for _, deg in G.degree() if deg >= 3)
        return intersections
    except Exception:
        return 0


def _estimate_green_volume(gdf_proj):
    """根据绿地类型标签估算 3D 体积。

    典型植被高度参考:
        - forest/wood:            12 m
        - park/garden:             6 m
        - nature_reserve:          8 m
        - scrub/heath:             2 m
        - grass/meadow/grassland:  0.5 m
        - 无标签/其他:             3 m
    """
    # 高度映射表（基于 OSM 标签值）
    HEIGHT_MAP = {
        # landuse
        "forest": 12, "wood": 12,
        "grass": 0.5, "meadow": 0.5, "recreation_ground": 1.0,
        "allotments": 1.5,
        # leisure
        "park": 6, "garden": 4, "nature_reserve": 8,
        "golf_course": 1.5, "playground": 1.0,
        # natural
        "grassland": 0.5, "heath": 2, "scrub": 2,
    }
    DEFAULT_HEIGHT = 3.0

    total_volume = 0.0

    # 尝试根据各类标签匹配
    tag_keys = ["landuse", "leisure", "natural"]
    for _, row in gdf_proj.iterrows():
        area = row.geometry.area
        height = DEFAULT_HEIGHT

        # 查找匹配的标签
        for key in tag_keys:
            tag_val = row.get(key, None)
            if tag_val is not None and not (isinstance(tag_val, float) and str(tag_val) == 'nan'):
                if isinstance(tag_val, list):
                    tag_val = tag_val[0] if tag_val else None
                if tag_val and str(tag_val).lower() in HEIGHT_MAP:
                    height = HEIGHT_MAP[str(tag_val).lower()]
                    break

        total_volume += area * height

    return total_volume
