import pandas as pd
import re, json, pickle
from pyproj import Geod
from state_abbr import US_STATE_ABBR_TO_NAME

geod = Geod(ellps="WGS84")

cities = pd.read_csv('../reference_data/us_cities.csv')
cities['CITY_L'] = cities['CITY'].str.lower().str.strip()
city_lookup = {}
for _, r in cities.iterrows():
    key = (r['CITY_L'], r['STATE_CODE'])
    if key not in city_lookup:
        city_lookup[key] = (r['LATITUDE'], r['LONGITUDE'])

zips_df = pd.read_csv('../reference_data/zips_latlon.csv')
zips_df['city_l'] = zips_df['city'].str.lower().str.strip()
zip_city_lookup = {}
for (city_l, st), grp in zips_df.groupby(['city_l', 'state']):
    zip_city_lookup[(city_l, st)] = (grp['lat'].mean(), grp['lon'].mean())

RADIUS_RE = re.compile(r'(\d+)\s*-?\s*miles?\s+of\s+([A-Za-z .\'-]+?),\s*([A-Z]{2})\b', re.I)
# alt phrasing seen in some sheets: "Fort Collins 50 miles, CO" (city then radius, no "of")
RADIUS_RE_ALT = re.compile(r'([A-Za-z .\'-]+?)\s+(\d+)\s*-?\s*miles?,\s*([A-Z]{2})\b', re.I)

LABELS_KEEP = [
    'Job title', 'Driver type', 'Experience', 'Status', 'Hometime', 'Openings',
    'Average weekly', 'Average annualized', 'Top weekly', 'Top annualized',
    'Overview', 'Operations', 'Responsibilities', 'Freight', 'Load type',
    'Delivery locations', 'Workload', 'Schedule', 'Compensation', 'Equipment',
    'Transportation', 'Safety', 'Position',
]

def geocode(city, state):
    key = (city.lower().strip(), state.upper().strip())
    if key in city_lookup:
        return city_lookup[key]
    if key in zip_city_lookup:
        return zip_city_lookup[key]
    return None

def geodesic_circle(lat, lon, radius_miles, n=48):
    r_m = radius_miles * 1609.344
    coords = []
    for i in range(n + 1):
        az = 360.0 * i / n
        lon2, lat2, _ = geod.fwd(lon, lat, az, r_m)
        coords.append((lon2, lat2))
    return coords

def category(hometime):
    if not hometime:
        return 'Regional'
    ht = hometime.lower()
    if 'daily' in ht:
        return 'Local'
    if 'weekly' in ht:
        return 'Dedicated'
    return 'OTR'  # every 2 weeks, once a month, etc.

xl = pd.ExcelFile('../source_files/CR_England_Driver_Needs_09182026.xlsx')
sheet_names = [s for s in xl.sheet_names if s != 'Open Positions']

records = []
unresolved = []

for sheet in sheet_names:
    df = pd.read_excel(xl, sheet_name=sheet, header=None)
    label_val = {}
    for _, row in df.iterrows():
        lbl = row[0]
        val = row[1] if len(row) > 1 else None
        if isinstance(lbl, str) and lbl.strip() in LABELS_KEEP and pd.notna(val):
            label_val[lbl.strip()] = str(val).strip()

    hometime = label_val.get('Hometime')
    cat = category(hometime)

    # find every radius+city match anywhere in the sheet
    text_cells = []
    for col in df.columns:
        text_cells.extend(df[col].dropna().astype(str).tolist())
    radius_matches = []
    for t in text_cells:
        radius_matches.extend(RADIUS_RE.findall(t))
        for city, radius_str, state in RADIUS_RE_ALT.findall(t):
            radius_matches.append((radius_str, city, state))

    account = f"CR England - {sheet}"

    desc_lines = [f"Type: {cat}"]
    for lbl in LABELS_KEEP:
        if lbl in label_val:
            desc_lines.append(f"{lbl}: {label_val[lbl]}")
    description = "\n".join(desc_lines)

    circles = []
    centers = []
    for radius_str, city, state in radius_matches:
        coords = geocode(city, state)
        if coords:
            lat, lon = coords
            circles.append(geodesic_circle(lat, lon, float(radius_str)))
            centers.append((lat, lon))

    if circles:
        # one record per circle so each hiring sub-area is its own shape,
        # but all share the same account name/description/category
        for i, ring in enumerate(circles):
            suffix = f" (zone {i+1}/{len(circles)})" if len(circles) > 1 else ""
            records.append({
                'account': account + suffix,
                'category': cat,
                'geom_type': 'radius_circle',
                'geom_data': ring,
                'description': description,
                'hiring_states': [],
                'center': centers[i],
                '_base_account': sheet,
                '_circle_key': tuple(sorted(round(c[0], 3) for c in centers)) + tuple(sorted(round(c[1], 3) for c in centers)),
            })
    else:
        unresolved.append(sheet)

# ---- Deduplicate sheets that share the exact same terminal network ----
from collections import defaultdict
groups = defaultdict(list)
for r in records:
    groups[r['_circle_key']].append(r)

deduped = []
for key, recs in groups.items():
    base_accounts = sorted(set(r['_base_account'] for r in recs))
    n_shapes = len(set((r['center'], tuple(r['geom_data'][:1])) for r in recs)) if recs else 0
    # unique shapes for this key (recs may include repeats across sheets)
    unique_shapes = {}
    for r in recs:
        unique_shapes[r['center']] = r  # last one wins, they're identical anyway
    if len(base_accounts) > 1:
        # shared network across multiple sheets -> merge into ONE account
        label = f"CR England - OTR Network (shared: {', '.join(base_accounts)})"
        for center, r in unique_shapes.items():
            deduped.append({
                'account': label,
                'category': r['category'],
                'geom_type': 'radius_circle',
                'geom_data': r['geom_data'],
                'description': r['description'] + f"\nShared network - eligible home states/fleets: {', '.join(base_accounts)}",
                'hiring_states': [],
                'center': center,
            })
    else:
        deduped.extend(recs)

for r in deduped:
    r.pop('_base_account', None)
    r.pop('_circle_key', None)

# Per account request: exclude CR England Local-only offers from the map,
# but keep shared "OTR Network" merged records even if their category tag
# says Local (those shapes represent a location shared by an OTR/Condo sheet
# and a Local sheet, so dropping them would also remove real OTR listings).
n_before = len(deduped)
deduped = [
    r for r in deduped
    if r['category'] != 'Local' or 'OTR Network' in r['account']
]
print(f"Excluded {n_before - len(deduped)} CR England Local-only record(s) per request.")

with open('records_cre2.pkl', 'wb') as f:
    pickle.dump(deduped, f)

from collections import Counter
print("Total shapes:", len(deduped))
print("Distinct account labels:", len(set(r['account'] for r in deduped)))
print(Counter(r['category'] for r in deduped))
print("Unresolved sheets (no radius/city found):", unresolved)
