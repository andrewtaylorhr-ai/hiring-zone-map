import pickle, sys, itertools
from xml.sax.saxutils import escape
from pyproj import Geod

records_path = sys.argv[1] if len(sys.argv) > 1 else '/home/claude/build/records_my5.pkl'
out_path = sys.argv[2] if len(sys.argv) > 2 else '/home/claude/build/hiring_zones_flat.kml'
map_name = sys.argv[3] if len(sys.argv) > 3 else 'Swift Hiring Zones'

with open(records_path, 'rb') as f:
    records = pickle.load(f)

PALETTE = [
    'A61B4A', 'F4EB37', '009D57', 'F8971B', '795046', '3F5BA9', '4186F0',
    '777777', '7C3592', '0BA9CC', '62AF44', 'EE9C96', 'DB4436', 'CDDC39',
    'FFDD5E', 'D698AD', '000000',
]

def kml_poly_color(hexrgb, alpha='4d'):
    r, g, b = hexrgb[0:2], hexrgb[2:4], hexrgb[4:6]
    return f"{alpha}{b}{g}{r}"

def kml_full_color(hexrgb):
    r, g, b = hexrgb[0:2], hexrgb[2:4], hexrgb[4:6]
    return f"ff{b}{g}{r}"

TRUCK_ICON = "https://www.gstatic.com/mapspro/images/stock/1465-trans-truck.png"

def style_block(used_colors):
    out = []
    for c in used_colors:
        sid = f"poly-{c}"
        out.append(f"""
    <Style id="{sid}">
      <LineStyle><color>{kml_full_color(c)}</color><width>2</width></LineStyle>
      <PolyStyle><color>{kml_poly_color(c)}</color><fill>1</fill><outline>1</outline></PolyStyle>
    </Style>""")
    out.append(f"""
    <Style id="truckIcon">
      <IconStyle>
        <scale>0.8</scale>
        <Icon><href>{TRUCK_ICON}</href></Icon>
      </IconStyle>
      <LabelStyle><scale>0</scale></LabelStyle>
    </Style>""")
    return "".join(out)

def polygon_placemark(name, desc, style_id, ring_lonlat):
    coord_str = " ".join(f"{lon},{lat},0" for lon, lat in ring_lonlat)
    return f"""
    <Placemark>
      <name>{escape(name)}</name>
      <description>{escape(desc)}</description>
      <styleUrl>#{style_id}</styleUrl>
      <Polygon>
        <outerBoundaryIs><LinearRing><coordinates>{coord_str}</coordinates></LinearRing></outerBoundaryIs>
      </Polygon>
    </Placemark>"""

def geodesic_circle_for_kml(lat, lon, radius_miles, n=24):
    geod = Geod(ellps="WGS84")
    r_m = radius_miles * 1609.344
    coords = []
    for i in range(n + 1):
        az = 360.0 * i / n
        lon2, lat2, _ = geod.fwd(lon, lat, az, r_m)
        coords.append((lon2, lat2))
    return coords

def small_dots_placemark(name, desc, style_id, points_lonlat, radius_miles=8):
    parts = []
    for lon, lat in points_lonlat:
        ring = geodesic_circle_for_kml(lat, lon, radius_miles)
        coord_str = " ".join(f"{lo},{la},0" for lo, la in ring)
        parts.append(f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{coord_str}</coordinates></LinearRing></outerBoundaryIs></Polygon>")
    geom = f"<MultiGeometry>{''.join(parts)}</MultiGeometry>"
    return f"""
    <Placemark>
      <name>{escape(name)}</name>
      <description>{escape(desc)}</description>
      <styleUrl>#{style_id}</styleUrl>
      {geom}
    </Placemark>"""

def truck_point_placemark(name, desc, lat, lon):
    return f"""
    <Placemark>
      <name>{escape(name)}</name>
      <description>{escape(desc)}</description>
      <styleUrl>#truckIcon</styleUrl>
      <Point><coordinates>{lon},{lat},0</coordinates></Point>
    </Placemark>"""

placemarks = []
color_cycle = itertools.cycle(PALETTE)

for r in records:
    color = next(color_cycle)
    style_id = f"poly-{color}"
    gt = r['geom_type']
    name = r['account']
    desc = r['description']

    if gt == 'radius_circle':
        placemarks.append(polygon_placemark(name, desc, style_id, r['geom_data']))
    elif gt == 'zip_cluster':
        placemarks.append(polygon_placemark(name, desc, style_id, r['geom_data']))
    elif gt == 'zip_dots':
        placemarks.append(small_dots_placemark(name, desc, style_id, r['geom_data']))

    if r.get('center'):
        clat, clon = r['center']
        placemarks.append(truck_point_placemark(name, desc, clat, clon))

kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{escape(map_name)}</name>
    {style_block(PALETTE)}
    {''.join(placemarks)}
  </Document>
</kml>"""

with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
    f.write(kml)

print("Wrote flat KML, size:", len(kml), "bytes, placemarks:", len(placemarks))
