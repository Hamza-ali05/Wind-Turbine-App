import logging

import geopandas as gpd
from shapely.geometry import box

from app.services.infrastructure import _configure_osmnx, get_road_network

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
_configure_osmnx("https://overpass.kumi.systems/api")
sample = gpd.GeoDataFrame(geometry=[box(67.90, 24.73, 67.94, 24.76)], crs="EPSG:4326")
roads = get_road_network(sample)
print(f"tiny_thatta_edges={len(roads)} crs={roads.crs}")
