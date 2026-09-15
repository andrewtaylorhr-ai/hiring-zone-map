import pandas as pd
import pickle
from pyproj import Geod

geod = Geod(ellps="WGS84")

cities = pd.read_csv('../reference_data/us_cities.csv')
cities['CITY_L'] = cities['CITY'].str.lower().str.strip()
city_lookup = {}
for _, r in cities.iterrows():
    key = (r['CITY_L'], r['STATE_CODE'])
    if key not in city_lookup:
        key_val = (r['LATITUDE'], r['LONGITUDE'])
        city_lookup[key] = key_val

RADIUS_MI = 90

# PAM is OTR-only. Domiciles come from the "MNE, SEC & SCS (OTR)" sheet in
# Pam Information 08282026 (1).xlsx, grouped by division; each domicile has a
# 90-mile hiring radius (confirmed via pay-map project, cross-checked against
# the source sheet's domicile lists).
DIVISIONS = {
    'MNE (formerly EVS + MET)': [
        ('Elkridge', 'MD'), ('Williamsport', 'PA'), ('Brook Park', 'OH'),
        ('Columbus', 'OH'), ('Detroit', 'MI'), ('Hammond', 'IN'),
        ('Camp Hill', 'PA'), ('Indianapolis', 'IN'), ('Louisville', 'KY'),
    ],
    'SEC (formerly LKL + CHA)': [
        ('Atlanta', 'GA'), ('Charlotte', 'NC'), ('Duncan', 'SC'),
        ('Orlando', 'FL'), ('Durham', 'NC'),
    ],
    'SCS (formerly DAL + NVS)': [
        ('Dallas', 'TX'), ('El Paso', 'TX'), ('Houston', 'TX'),
        ('Kansas City', 'KS'), ('Laredo', 'TX'), ('Memphis', 'TN'),
        ('Nashville', 'TN'), ('Springdale', 'AR'), ('Birmingham', 'AL'),
    ],
}

HOMETIME_NOTE = (
    'Drivers typically out 1-2 weeks at a time, depending on domicile and '
    'freight. Schedule runs Monday-Saturday with a full 34-hour reset every '
    'Sunday.'
)

def geodesic_circle(lat, lon, radius_miles, n=48):
    r_m = radius_miles * 1609.344
    coords = []
    for i in range(n + 1):
        az = 360.0 * i / n
        lon2, lat2, _ = geod.fwd(lon, lat, az, r_m)
        coords.append((lon2, lat2))
    return coords

records = []
skipped = []

for division, domiciles in DIVISIONS.items():
    for city, state in domiciles:
        key = (city.lower().strip(), state)
        center = city_lookup.get(key)
        if not center:
            skipped.append(f"{city}, {state}")
            continue
        lat, lon = center
        ring = geodesic_circle(lat, lon, RADIUS_MI)
        description = (
            f"Type: OTR\nDivision: {division}\nHiring radius: {RADIUS_MI} miles "
            f"of {city}, {state}\nHome time: {HOMETIME_NOTE}"
        )
        records.append({
            'account': f"PAM - {division} - {city}, {state}",
            'category': 'OTR',
            'geom_type': 'radius_circle',
            'geom_data': ring,
            'description': description,
            'hiring_states': [state],
            'center': (lat, lon),
        })

print(f"Mapped: {len(records)}  Skipped (no geocode match): {len(skipped)}")
if skipped:
    print("Skipped:", skipped)

with open('records_pam.pkl', 'wb') as f:
    pickle.dump(records, f)
