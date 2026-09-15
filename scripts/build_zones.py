import pandas as pd
import numpy as np
import re, json, math
from pyproj import Geod
from shapely.geometry import Point, MultiPoint, shape, mapping
from shapely.ops import unary_union

from state_abbr import US_STATE_ABBR_TO_NAME

geod = Geod(ellps="WGS84")

# Manually verified coordinates for accounts that have no radius, no zips, and
# no city/state that auto-geocodes cleanly. Andrew asked these be added to OTR
# with city/state shown in the title.
MANUAL_OVERRIDES = {
    "Swift - 56W - 11 Regional Western States - Jurupa Valley": (33.9975, -117.4854, "Jurupa Valley, CA"),
    "Swift - 57X Reefer - Decatur, GA": (33.8044, -84.1908, "Decatur, GA"),
    "Swift - 626 Midwest - Detroit, MI": (42.2539, -83.1627, "Detroit, MI"),
    "Swift - 907 Western Region Comfort Zone - Jurupa Valley, CA": (33.9975, -117.4854, "Jurupa Valley, CA"),
    "Swift - 908 - 11 Western Regional": (37.2539, -119.6144, "California (state centroid - no single hub given)"),
    "Swift - 910 Comfort Zone - Mobile, AL": (30.6673, -88.1568, "Mobile, AL"),
    "Swift - 910 Comfort Zone - Richmond, VA": (37.5361, -77.4870, "Richmond, VA"),
    "Swift - Eastern Regional Fleet - Statesboro": (32.4350, -81.7652, "Statesboro, GA"),
    "Swift - IMOD Regional - IOWA": (41.5640, -90.5957, "Davenport, IA"),
    "Swift - SLC-Express lane": (40.7029, -111.8882, "Salt Lake City, UT"),
    "Swift - Target - Amsterdam, NY": (42.9063, -74.2290, "Amsterdam, NY"),
    "Swift - Walmart - Los Lunas, NM": (34.7658, -106.7123, "Los Lunas, NM"),
    "Swift - Walmart - Temple, TX": (31.0702, -97.4088, "Temple, TX"),
    # "Expeditors / Star Fleet / OTR Dry Teams" intentionally excluded: the
    # account spans ~40 states with no hub city or state at all, so there's
    # no defensible single point to place it at.
}

# ---------- Load reference data ----------
cities = pd.read_csv('../reference_data/us_cities.csv')
cities['CITY_L'] = cities['CITY'].str.lower().str.strip()
city_lookup = {}
for _, r in cities.iterrows():
    key = (r['CITY_L'], r['STATE_CODE'])
    if key not in city_lookup:
        city_lookup[key] = (r['LATITUDE'], r['LONGITUDE'])

zips = pd.read_csv('../reference_data/zips_latlon.csv', dtype={'code': str})
zips['code'] = zips['code'].str.zfill(5)
zip_lookup = dict(zip(zips['code'], zip(zips['lat'], zips['lon'])))

with open('../reference_data/us_states.geojson') as f:
    states_gj = json.load(f)
state_shapes = {}
for feat in states_gj['features']:
    state_shapes[feat['properties']['name']] = shape(feat['geometry'])

# ---------- Load hiring data ----------
df = pd.read_excel('../source_files/Hiring_Data_Base__2_.xlsx')
df = df.dropna(subset=['Account']).copy()
df = df[df['Open or Closed'].astype(str).str.upper().str.strip() == 'OPEN'].copy()

RADIUS_COL = 'Live within "X miles" of Zip Code(s)'
ZIP_COL = 'Hiring City Zip Code(s) (Dedicated Only)'
CITY_COL = 'Hiring City(s)'
STATE_COL = 'Hiring State'
LOB_COL = 'LOB (Line of Business)'

def extract_zips(val):
    if pd.isna(val):
        return []
    return re.findall(r'\d{5}', str(val))

def first_city_state(city_str, state_str):
    """Try to resolve a (lat, lon) from the first plausible city name + a hiring state."""
    if pd.isna(state_str):
        return None
    states = [s.strip() for s in re.split(r'[\n,/]', str(state_str)) if s.strip()]
    if not states:
        return None
    candidates = []
    if not pd.isna(city_str):
        # split on common delimiters, take plausible city tokens (short, alpha)
        parts = re.split(r'[\n,;]', str(city_str))
        for p in parts:
            p = p.strip()
            # strip trailing " ,ST" state abbreviations already embedded sometimes
            p2 = re.sub(r'\b[A-Z]{2}\b$', '', p).strip()
            if 1 < len(p2) < 40:
                candidates.append(p2)
    for st in states:
        for c in candidates:
            key = (c.lower().strip(), st)
            if key in city_lookup:
                return city_lookup[key]
    return None

def category(account, lob, home_time):
    """Category driven by actual Home Time text, per Andrew:
    OTR = out for weeks at a time (2-3 days home)
    Local = home daily
    Dedicated = home weekly
    Regional = everything else / not clearly stated
    """
    if pd.isna(home_time):
        return 'Regional'
    ht = str(home_time).lower()
    if 'daily' in ht:
        return 'Local'
    multiweek = ['every two weeks', 'every three weeks', 'every four weeks', 'every six weeks', '2-3 weeks']
    if any(p in ht for p in multiweek):
        return 'OTR'
    weekly = ['once a week', 'twice a week', '34 hour restart', 'weekend']
    if any(p in ht for p in weekly):
        return 'Dedicated'
    near_daily = ['every other day', 'every two days', 'every three days', 'every four days', '10 hour break']
    if any(p in ht for p in near_daily):
        return 'Local'
    return 'Regional'

def category_group(fine_cat):
    """Kept for compatibility - now fine and group are the same 4-way split."""
    return fine_cat

def miles_to_meters(mi):
    return mi * 1609.344

def geodesic_circle(lat, lon, radius_miles, n=64):
    r_m = miles_to_meters(radius_miles)
    lons, lats = [], []
    for i in range(n + 1):
        az = 360.0 * i / n
        lon2, lat2, _ = geod.fwd(lon, lat, az, r_m)
        lons.append(lon2)
        lats.append(lat2)
    return list(zip(lons, lats))  # exterior ring, lon,lat order for KML

records = []
skipped = []

for _, row in df.iterrows():
    account = "Swift - " + str(row['Account']).strip()
    lob = row[LOB_COL]
    cat = category(account, lob, row.get('Home Time'))
    radius = row[RADIUS_COL]
    radius = float(radius) if isinstance(radius, (int, float)) and not pd.isna(radius) else None
    zips_found = extract_zips(row[ZIP_COL])
    n_zips = len(zips_found)

    def val(col):
        v = row.get(col)
        return None if pd.isna(v) else str(v).strip()

    # Comprehensive description: include every informative column from the
    # file (skip pure admin/metadata columns that aren't useful to a recruiter).
    EXCLUDE_COLS = {
        'Account', 'Open or Closed', 'Create Date', 'Modified Date',
        'Update Request Date', 'Re-evaluation Date', 'Cost Center',
        'Does position need leadership approval', 'ARE YOU SURE ABOUT TRAINEES',
        'Modified by', 'Re-evaluation Alert', 'GL Code', 'Deactivated',
        'Hiring City Zip Code(s) (Dedicated Only)',
    }
    LABELS = {
        'Hiring State': 'Hiring state(s)',
        'Home Time': 'Home time',
        'Experience Requirements': 'Experience required',
        'Live within "X miles" of Zip Code(s)': 'Hiring radius (miles)',
        'Average Earnings per Week': 'Avg weekly pay',
        'Hiring City(s)': 'Hiring city(s)',
        'Trainees OK?': 'Trainees OK',
        'Planning Area(s) Hiring Out Of': 'Planning area(s)',
        'Hub State(s)': 'Hub state(s)',
        'BONUS OFFER': 'Bonus',
        'LOB (Line of Business)': 'LOB',
        'On Site Mgr / Terminal Leader': 'On-site manager',
        'On Site Mgr Contact#': 'Manager contact #',
        'Regional Leader / Director / TL': 'Regional leader',
        'Regional Leader / Director / TL Contact #': 'Regional leader contact #',
        'Driver Leader / DDM': 'Driver leader / DDM',
        'Owner Operators OK?': 'Owner-Ops OK',
        'Teams OK': 'Teams OK',
        'Region(s)': 'Region(s)',
        'Hub City(s)': 'Hub city(s)',
        '# of Drivers Needed (Solo)': 'Drivers needed (solo)',
        '# of Drivers Needed (Team)': 'Drivers needed (team)',
        'Total #of Drivers Needed by State (Dedi Only)': 'Total drivers needed by state',
        'Required Endorsements/Certificates': 'Endorsements/certs required',
        'Specialized Equipment': 'Specialized equipment',
        'Shift': 'Shift',
        'Weekend Work': 'Weekend work',
        'Holiday Work': 'Holiday work',
        'Lane Information': 'Lane info',
        'Favorable Info on Lane': 'Favorable info',
        'Unfavorable Info on Lane': 'Unfavorable info',
        'Trainee Pay': 'Trainee pay',
        'G-Pay  Effective 7/13/26 - 3mo after 1st Solo Disp': 'G-Pay',
        'Linehaul only Starting Mileage Pay': 'Linehaul starting mileage pay',
        'Pay / Salary': 'Pay',
        'Bonus Details': 'Bonus details',
        'Transition Bonus': 'Transition bonus',
        'Weekly Mileage': 'Weekly mileage',
        'Short Haul Pay': 'Short haul pay',
        'Amount for Short Haul Pay': 'Short haul pay amount',
        'Stop Pay': 'Stop pay',
        'Amount of Stop Pay': 'Stop pay amount',
        'Unload Pay': 'Unload pay',
        'Load - Unload': 'Load/unload',
        'Recruiting Leader': 'Recruiting leader',
        'Recruiters / Placement Contact': 'Recruiter/placement contact',
        'Regional Director Dedicated Operations': 'Regional director (dedicated ops)',
        'Total Number of Drivers Needed by State (Dedi Only': 'Total drivers needed by state',
    }

    desc_bits = []
    for col in df.columns:
        if col in EXCLUDE_COLS:
            continue
        v = val(col)
        if v:
            label = LABELS.get(col, col)
            desc_bits.append(f"{label}: {v}")
    description = "\n".join(str(b) for b in desc_bits)

    geom_type = None
    geom_data = None
    center_used = None

    # Case A: zip cluster (many zips) -> convex hull polygon IF the zips are
    # actually a tight local cluster; if they're spread across a wide area
    # (common in "Comfort Zone"/regional accounts), draw small dots per zip
    # instead of a hull that fabricates land area between distant points.
    if n_zips >= 5:
        pts = []
        for z in zips_found:
            if z in zip_lookup:
                lat, lon = zip_lookup[z]
                pts.append((lon, lat))
        pts = list(set(pts))
        if len(pts) >= 3:
            hull = MultiPoint(pts).convex_hull
            if hull.geom_type == 'Polygon':
                xs = [c[0] for c in hull.exterior.coords]
                ys = [c[1] for c in hull.exterior.coords]
                _, _, diag_m = geod.inv(min(xs), min(ys), max(xs), max(ys))
                diag_miles = diag_m / 1609.344
                if diag_miles <= 120:
                    hull_buf = hull.buffer(0.05)
                    if hull_buf.geom_type == 'Polygon':
                        geom_type = 'zip_cluster'
                        geom_data = list(hull_buf.exterior.coords)
                else:
                    # spread out -> small dot per zip, not a connecting hull
                    geom_type = 'zip_dots'
                    geom_data = pts
        elif len(pts) > 0:
            lon, lat = pts[0]
            geom_type = 'point'
            geom_data = (lat, lon)

    # Case B: radius circle around a single zip or city center
    if geom_type is None and radius:
        center = None
        if n_zips >= 1 and zips_found[0] in zip_lookup:
            lat, lon = zip_lookup[zips_found[0]]
            center = (lat, lon)
        if center is None:
            center = first_city_state(row.get(CITY_COL), row.get(STATE_COL))
        if center:
            lat, lon = center
            ring = geodesic_circle(lat, lon, radius)
            geom_type = 'radius_circle'
            geom_data = ring
            center_used = (lat, lon)

    # Case C: no radius, no zips -> mark the hiring city as a plain pin
    # (no radius shape to draw, but still show where the account is)
    if geom_type is None:
        center = first_city_state(row.get(CITY_COL), row.get(STATE_COL))
        if center:
            geom_type = 'point'
            geom_data = center
            center_used = center

    # Case D: still nothing -> manual override for accounts Andrew verified
    # by hand (real hiring hub, just not in the auto-geocoding databases),
    # forced into OTR per his instruction, with city/state added to the title.
    if geom_type is None:
        override = MANUAL_OVERRIDES.get(account)
        if override:
            lat, lon, label = override
            geom_type = 'point'
            geom_data = (lat, lon)
            center_used = (lat, lon)
            account = f"{account} ({label})"
            cat = 'OTR'

    if geom_type is None:
        skipped.append(account)
        continue

    hiring_states = []
    if not pd.isna(row.get(STATE_COL)):
        hiring_states = [s.strip() for s in re.split(r'[\n,/]', str(row.get(STATE_COL))) if s.strip()]

    # resolve a center point for the truck-icon marker
    center = None
    if geom_type == 'radius_circle':
        center = center_used
    elif geom_type == 'zip_cluster':
        ring = geom_data
        clat = sum(c[1] for c in ring) / len(ring)
        clon = sum(c[0] for c in ring) / len(ring)
        center = (clat, clon)
    elif geom_type == 'zip_dots':
        clat = sum(p[1] for p in geom_data) / len(geom_data)
        clon = sum(p[0] for p in geom_data) / len(geom_data)
        center = (clat, clon)
    elif geom_type == 'point':
        center = geom_data

    fine_cat = cat
    grp_cat = category_group(fine_cat)
    description = f"Type: {fine_cat}\n" + description

    records.append({
        'account': account,
        'category': grp_cat,
        'fine_category': fine_cat,
        'geom_type': geom_type,
        'geom_data': geom_data,
        'description': description,
        'hiring_states': hiring_states,
        'center': center,
    })

print(f"Total open accounts: {len(df)}")
print(f"Mapped: {len(records)}  Skipped (no resolvable geometry): {len(skipped)}")
from collections import Counter
print("By geom type:", Counter(r['geom_type'] for r in records))
print("By category:", Counter(r['category'] for r in records))
print("Skipped accounts:", skipped[:20], "..." if len(skipped) > 20 else "")

import pickle
with open('records.pkl', 'wb') as f:
    pickle.dump(records, f)
