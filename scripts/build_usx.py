import re, json, pickle
import xml.etree.ElementTree as ET
from shapely.geometry import shape, Point, Polygon
from state_abbr import US_STATE_ABBR_TO_NAME

NS = {'k': 'http://www.opengis.net/kml/2.2'}
STATE_NAME_TO_ABBR = {v: k for k, v in US_STATE_ABBR_TO_NAME.items()}

FOLDER_CATEGORY = {
    'Dedicated Home Weekly': 'Dedicated',
    'DEDICATED DAILY/FREQUENTLY/TEAM': 'Dedicated',
    'OTR SOLO COMPANY': 'OTR',
    'OTR TEAM COMPANY': 'OTR',
    'True Up Fleets': 'Dedicated',
    'Specialized Fleets': 'Regional',
    'OTR Regional': 'Regional',
    'Owner Operator-Dedicated': 'Dedicated',
    'Owner Operator-OTR': 'OTR',
    # CLOSED folder intentionally omitted -- those accounts are excluded.
}

with open('../reference_data/us_states.geojson') as f:
    states_gj = json.load(f)
state_shapes = [(feat['properties']['name'], shape(feat['geometry'])) for feat in states_gj['features']]

def html_to_text(desc):
    if desc is None:
        return ''
    t = re.sub(r'<br\s*/?>', '\n', desc)
    t = re.sub(r'<[^>]+>', '', t)
    return t.strip()

def parse_coords(coord_text):
    pts = []
    for tok in coord_text.split():
        parts = tok.split(',')
        lon, lat = float(parts[0]), float(parts[1])
        pts.append((lon, lat))
    return pts

def states_touching(geom):
    names = (name for name, poly in state_shapes if geom.intersects(poly))
    return sorted(STATE_NAME_TO_ABBR.get(n, n) for n in names)

tree = ET.parse('../source_files/usx_hiring_map.kml')
root = tree.getroot()
document = root.find('k:Document', NS)

records = []
skipped = []

for folder in document.findall('k:Folder', NS):
    folder_name = folder.find('k:name', NS).text.strip()
    if folder_name == 'CLOSED':
        continue
    category = FOLDER_CATEGORY.get(folder_name, 'Regional')

    for pm in folder.findall('k:Placemark', NS):
        name_el = pm.find('k:name', NS)
        name = (name_el.text or '').strip() if name_el is not None else ''
        if name.upper().startswith('CLOSED'):
            continue

        desc_el = pm.find('k:description', NS)
        description = html_to_text(desc_el.text if desc_el is not None else '')

        polygon_el = pm.find('.//k:Polygon//k:coordinates', NS)
        point_el = pm.find('k:Point/k:coordinates', NS)

        if polygon_el is not None and polygon_el.text.strip():
            ring = parse_coords(polygon_el.text)
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            geom_type = 'Polygon'
            geom_data = [ring]
            poly = Polygon(ring)
            centroid = poly.centroid
            center = (centroid.y, centroid.x)
            hiring_states = states_touching(poly)
        elif point_el is not None and point_el.text.strip():
            lon, lat = parse_coords(point_el.text)[0]
            geom_type = 'point'
            geom_data = (lat, lon)
            center = (lat, lon)
            hiring_states = states_touching(Point(lon, lat).buffer(0.01))
        else:
            skipped.append(name)
            continue

        records.append({
            'account': f"USX - {name}",
            'category': category,
            'geom_type': geom_type,
            'geom_data': geom_data,
            'description': f"Type: {category}\nDivision: {folder_name}\n{description}",
            'hiring_states': hiring_states,
            'center': center,
        })

print(f"Mapped: {len(records)}  Skipped (no geometry): {len(skipped)}")
if skipped:
    print("Skipped:", skipped)
from collections import Counter
print("By category:", Counter(r['category'] for r in records))
print("By geom type:", Counter(r['geom_type'] for r in records))

with open('records_usx.pkl', 'wb') as f:
    pickle.dump(records, f)
