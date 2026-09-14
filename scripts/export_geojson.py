"""
Convert carrier record pickles (produced by build_*.py) into a single
GeoJSON FeatureCollection for the Leaflet-based hiring-zone map.

Usage: python export_geojson.py <out_path>
Carrier sources are hardcoded below as (pickle_path, carrier_name) pairs.
"""
import pickle, json, sys
from pyproj import Geod

OUT_PATH = sys.argv[1] if len(sys.argv) > 1 else '../site/data.geojson'

SOURCES = [
    ('records.pkl', 'Swift'),
    ('records_cre2.pkl', 'CR England'),
]

CATEGORY_COLORS = {
    'OTR': '#DB4436',
    'Dedicated': '#3F5BA9',
    'Local': '#009D57',
    'Regional': '#F8971B',
}

geod = Geod(ellps="WGS84")

def geodesic_circle(lat, lon, radius_miles=8, n=24):
    r_m = radius_miles * 1609.344
    coords = []
    for i in range(n + 1):
        az = 360.0 * i / n
        lon2, lat2, _ = geod.fwd(lon, lat, az, r_m)
        coords.append([lon2, lat2])
    return coords

def close_ring(ring):
    ring = [list(pt) for pt in ring]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring

def geometry_coords(geometry):
    if geometry['type'] == 'Polygon':
        return geometry['coordinates'][0]
    if geometry['type'] == 'MultiPolygon':
        pts = []
        for poly in geometry['coordinates']:
            pts.extend(poly[0])
        return pts
    if geometry['type'] == 'Point':
        return [geometry['coordinates']]
    return []

def max_extent_miles(center_latlon, geometry):
    if not center_latlon:
        return 0
    clat, clon = center_latlon
    coords = geometry_coords(geometry)
    if not coords:
        return 0
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    _, _, dists = geod.inv([clon] * len(lons), [clat] * len(lats), lons, lats)
    return round(max(dists) / 1609.344, 1) if dists else 0

features = []
skipped = 0

for pkl_path, carrier in SOURCES:
    with open(pkl_path, 'rb') as f:
        records = pickle.load(f)

    for r in records:
        gt = r['geom_type']
        category = r.get('category') or 'Regional'
        color = CATEGORY_COLORS.get(category, '#777777')
        center = r.get('center')
        props = {
            'carrier': carrier,
            'account': r['account'],
            'category': category,
            'description': r.get('description') or '',
            'hiring_states': r.get('hiring_states') or [],
            'color': color,
            'center': [center[0], center[1]] if center else None,
        }

        if gt in ('radius_circle', 'zip_cluster'):
            ring = close_ring(r['geom_data'])
            geometry = {'type': 'Polygon', 'coordinates': [ring]}
        elif gt == 'zip_dots':
            polys = [[close_ring(geodesic_circle(lat, lon))] for lon, lat in r['geom_data']]
            geometry = {'type': 'MultiPolygon', 'coordinates': polys}
        elif gt == 'point':
            lat, lon = r['geom_data']
            geometry = {'type': 'Point', 'coordinates': [lon, lat]}
        else:
            skipped += 1
            continue

        props['size_mi'] = max_extent_miles(center, geometry)
        features.append({'type': 'Feature', 'geometry': geometry, 'properties': props})

fc = {'type': 'FeatureCollection', 'features': features}

with open(OUT_PATH, 'w', encoding='utf-8', newline='\n') as f:
    json.dump(fc, f, separators=(',', ':'))

print(f"Wrote {len(features)} features ({skipped} skipped) to {OUT_PATH}")
carriers = sorted(set(f['properties']['carrier'] for f in features))
categories = sorted(set(f['properties']['category'] for f in features))
print("Carriers:", carriers)
print("Categories:", categories)
