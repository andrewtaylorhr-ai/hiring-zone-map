import pandas as pd
import re, json, pickle
from shapely.geometry import shape
from state_abbr import US_STATE_ABBR_TO_NAME

with open('../reference_data/us_states.geojson') as f:
    states_gj = json.load(f)
state_centroid = {}
for feat in states_gj['features']:
    name = feat['properties']['name']
    abbr = {v: k for k, v in US_STATE_ABBR_TO_NAME.items()}.get(name)
    if abbr:
        c = shape(feat['geometry']).centroid
        state_centroid[abbr] = (c.y, c.x)

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

STATE_NAME_TO_ABBR = {v.lower(): k for k, v in US_STATE_ABBR_TO_NAME.items()}

CITY_STATE_RE = re.compile(r"([A-Za-z][A-Za-z .'\-]*?),?\s+([A-Z]{2})\b")

# Position Name segments that don't carry a clean "City, ST" or full-state-name
# token in the field itself -- resolved by hand from context elsewhere in the
# same sheet (e.g. the same account listed with a state on another row), or
# are misspelled/abbreviated versions of a real town not in the geocode DB.
MANUAL_LOCATION = {
    '3RD PARTY ONLY - Ahold - Chester - E Brunswick Support fleet - Weekend Wrap - Local - 25658': ('Chester', 'NY'),
    '3RD PARTY ONLY - Intermodal - Kansas City/Edgerton - Nights - Local - EFA - 26193': ('Kansas City', 'KS'),
    '3rd PARTY ONLY - P&G Support Mehoopany - Pittston - (Tues - Sat)- Regional - 26441': ('Pittston', 'PA'),
    "3RD PARTY ONLY - Macy's - Tukwila WA - Sun-Thurs- 11AM Starts- Semi Local - 26399": ('Seattle', 'WA'),
    '3RD PARTY ONLY - Tarter Gate CO - Corinne UT - Mon-Fri - 5AM-9AM Starts - Regional - 26253': ('Corinne', 'UT'),
    "3rd Party Only - C&S Westfield - E Granbury CT - Shuttle - Local - Sun-Thurs PM - 26373": ('East Granby', 'CT'),
    "3rd PARTY ONLY - C&S - Support Westfied - East Ganby CT - Local - (NYC, LI, NJ)AM - 26371": ('East Granby', 'CT'),
    "3rd Party Only - C&S - Support Westfield - E Granby CT - Non NYC - Tues - Sat - PM -Local - 25687": ('East Granby', 'CT'),
    "3rd Party Only - C&S - Support Westfield - E Granby CT - Non NYC - Sun - Thurs - PM -Local - 25686": ('East Granby', 'CT'),
    "3rd PARTY ONLY - C&S - Support Westfield - E Granbury CT - Shuttle - Local - (Mon - Fri)PM - 26372": ('East Granby', 'CT'),
    '3RD PARTY ONLY - JBI Transload - Commerce CA - Mon-Fri - 5PM Starts -\xa0 Local - EFA - 26554': ('Los Angeles', 'CA'),
    "3rd PARTY ONLY - Ahold - Schodock Landing NY - Local - (Tues - Sat) - 26347": ('Schodack Landing', 'NY'),
    '3RD PARTY ONLY - Bridgestone -Portland, OR - 6AM Starts - Floater - Semi Local - 25196': ('Portland', 'OR'),
    '3RD PARTY ONLY Home Depot RDC - OH Fleet (St Louis MO/Monroe OH) - Regional - 26331': ('Monroe', 'OH'),
    '3RD PARTY - Mission Foods - Fife WA - Sat-Weds - 12PM-4PM Starts - Semi Local - 26598': ('Tacoma', 'WA'),
    '3RD PARTY ONLY - Aarons Inc - Obetz OH - Semi-Local - 26280': ('Columbus', 'OH'),
}

# Nationwide / multi-state programs with no defensible single hub city.
SKIP_ACCOUNTS = {
    '3RD PARTY ONLY - JBT - IC - Express - 360 Box Network - 25787',
}

def geocode(city, state):
    variants = [city]
    if re.match(r'st\.?\s', city, re.I):
        variants.append(re.sub(r'^st\.?\s', 'Saint ', city, flags=re.I))
    for c in variants:
        key = (c.lower().strip(), state.upper().strip())
        if key in city_lookup:
            return city_lookup[key]
        if key in zip_city_lookup:
            return zip_city_lookup[key]
    return None

def find_city_state(name):
    if name in MANUAL_LOCATION:
        return MANUAL_LOCATION[name]
    state_only = None
    for seg in re.split(r'-', name):
        seg = seg.strip().strip(',').strip()
        m = CITY_STATE_RE.search(seg)
        if m and m.group(2) in US_STATE_ABBR_TO_NAME:
            city = m.group(1).strip()
            if 1 < len(city) < 40:
                return city, m.group(2)
        if seg.lower() in STATE_NAME_TO_ABBR:
            state_only = (None, STATE_NAME_TO_ABBR[seg.lower()])
    return state_only

def category(name):
    n = name.lower()
    if 'local' in n:
        return 'Local'
    if 'regional' in n:
        return 'Regional'
    if 'otr' in n:
        return 'OTR'
    if 'dedicated' in n:
        return 'Dedicated'
    return 'Regional'

def clean_title(name):
    t = re.sub(r'^3rd party only\s*-\s*', '', name, flags=re.I).strip()
    t = re.sub(r'\s*-\s*\d{5}$', '', t).strip()
    return t

def val(row, col):
    v = row.get(col)
    return None if pd.isna(v) else v

df = pd.read_excel('../source_files/JBH_Information_09102026.xlsx', sheet_name='Open Positions 9-10-2026')

records = []
skipped = []

for _, row in df.iterrows():
    name = str(row['Position Name']).strip()
    if name in SKIP_ACCOUNTS:
        skipped.append(name)
        continue

    loc = find_city_state(name)
    center = None
    if loc:
        city, state = loc
        if city:
            center = geocode(city, state)
        if center is None:
            # state-only mention (e.g. "Intermodal - Minnesota - Regional") ->
            # no city hub given, use the state's geographic centroid instead.
            center = state_centroid.get(state)

    state_list_raw = val(row, 'State List')
    if state_list_raw:
        hiring_states = [s.strip() for s in str(state_list_raw).split(',') if s.strip()]
    elif loc:
        hiring_states = [loc[1]]
    else:
        hiring_states = []

    if center is None:
        skipped.append(name)
        continue

    lat, lon = center
    cat = category(name)

    desc_bits = [f"Type: {cat}"]
    pay_tier = val(row, 'Recruiter Pay')
    if pay_tier:
        desc_bits.append(f"Recruiter pay tier: {pay_tier}")
    needed = val(row, 'Drivers Needed')
    if needed is not None:
        desc_bits.append(f"Drivers needed: {int(needed)}")
    exp = val(row, 'Months of Experience Required')
    if exp is not None:
        desc_bits.append(f"Experience required: {int(exp)} months")
    gross = val(row, 'Average Yearly Gross')
    if gross is not None:
        desc_bits.append(f"Average yearly gross: ${int(gross):,}")
    interview = val(row, 'Interview Needed')
    if interview:
        desc_bits.append(f"Interview needed: {interview}")
    bonus = val(row, 'Sign On Bonus')
    if bonus is not None:
        desc_bits.append(f"Sign-on bonus: ${int(bonus):,}")
    bonus_detail = val(row, 'Sign On Bonus.1')
    if bonus_detail:
        desc_bits.append(f"Sign-on bonus schedule: {bonus_detail}")

    records.append({
        'account': f"J.B. Hunt - {clean_title(name)}",
        'category': cat,
        'geom_type': 'point',
        'geom_data': (lat, lon),
        'description': "\n".join(desc_bits),
        'hiring_states': hiring_states,
        'center': (lat, lon),
        'sign_on_bonus': int(bonus) if bonus is not None else None,
    })

print(f"Total rows: {len(df)}")
print(f"Mapped: {len(records)}  Skipped (no resolvable location): {len(skipped)}")
from collections import Counter
print("By category:", Counter(r['category'] for r in records))
if skipped:
    print("Skipped:", skipped)

with open('records_jbh.pkl', 'wb') as f:
    pickle.dump(records, f)
