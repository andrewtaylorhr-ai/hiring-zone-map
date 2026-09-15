import json, pickle
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
from pyproj import Geod
from state_abbr import US_STATE_ABBR_TO_NAME

geod = Geod(ellps="WGS84")
STATE_NAME_TO_ABBR = {v: k for k, v in US_STATE_ABBR_TO_NAME.items()}

# TransAm's "Hiring Map" sheet is a single embedded image (xl/media/image1.png,
# extracted to outputs/transam_extract/hiring_map.png) showing one shaded
# nationwide hiring area. Excluded (unshaded) states, read off that image:
# Alaska/Hawaii/Puerto Rico aren't depicted at all on the source image (a
# CONUS-only map), so they're excluded alongside the states explicitly shown
# unshaded (Washington, Oregon, Idaho, Montana, North/South Dakota, California).
EXCLUDED_STATES = {
    'Washington', 'Oregon', 'Idaho', 'Montana', 'North Dakota', 'South Dakota', 'California',
    'Alaska', 'Hawaii', 'Puerto Rico',
}

with open('../reference_data/us_states.geojson') as f:
    states_gj = json.load(f)

included_shapes = [
    shape(feat['geometry'])
    for feat in states_gj['features']
    if feat['properties']['name'] not in EXCLUDED_STATES
]
hiring_states = sorted(
    STATE_NAME_TO_ABBR[feat['properties']['name']]
    for feat in states_gj['features']
    if feat['properties']['name'] not in EXCLUDED_STATES
)

union = unary_union(included_shapes)
geom = mapping(union)  # {'type': 'Polygon'|'MultiPolygon', 'coordinates': [...]}
centroid = union.centroid

description = (
    "Type: OTR\n"
    "Nationwide company/independent-contractor OTR hiring area (per TransAm's "
    "internal Hiring Map), excluding WA, OR, ID, MT, ND, SD, CA.\n"
    "Independent contractor: 70% of linehaul revenue + 100% of fuel surcharge, "
    "avg gross $2,500-$6,000/week."
)

record = {
    'account': 'TransAm - Nationwide OTR Hiring Area',
    'category': 'OTR',
    'geom_type': geom['type'],
    'geom_data': geom['coordinates'],
    'description': description,
    'hiring_states': hiring_states,
    'center': (centroid.y, centroid.x),
}

with open('records_transam.pkl', 'wb') as f:
    pickle.dump([record], f)

print(f"Mapped: 1 record, {len(hiring_states)} states, geom type {geom['type']}")
