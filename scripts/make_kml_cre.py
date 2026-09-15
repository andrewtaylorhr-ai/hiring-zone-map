import pickle, sys
from xml.sax.saxutils import escape
from pyproj import Geod

records_path = sys.argv[1]
out_path = sys.argv[2]
map_name = sys.argv[3] if len(sys.argv) > 3 else 'CR England'

with open(records_path, 'rb') as f:
    records = pickle.load(f)

# CR England gets ONE consistent color (gold) instead of Swift's rotating
# rainbow palette, so it reads as a distinct carrier at a glance.
CRE_COLOR = 'F4B400'  # gold/yellow
DOLLAR_ICON = "https://maps.google.com/mapfiles/kml/shapes/dollar.png"

def kml_poly_color(hexrgb, alpha='4d'):
    r, g, b = hexrgb[0:2], hexrgb[2:4], hexrgb[4:6]
    return f"{alpha}{b}{g}{r}"

def kml_full_color(hexrgb):
    r, g, b = hexrgb[0:2], hexrgb[2:4], hexrgb[4:6]
    return f"ff{b}{g}{r}"

def style_block():
    return f"""
    <Style id="crePoly">
      <LineStyle><color>{kml_full_color(CRE_COLOR)}</color><width>2</width></LineStyle>
      <PolyStyle><color>{kml_poly_color(CRE_COLOR)}</color><fill>1</fill><outline>1</outline></PolyStyle>
    </Style>
    <Style id="creIcon">
      <IconStyle>
        <scale>0.9</scale>
        <Icon><href>{DOLLAR_ICON}</href></Icon>
      </IconStyle>
      <LabelStyle><scale>0</scale></LabelStyle>
    </Style>"""

def polygon_placemark(name, desc, ring_lonlat):
    coord_str = " ".join(f"{lon},{lat},0" for lon, lat in ring_lonlat)
    return f"""
    <Placemark>
      <name>{escape(name)}</name>
      <description>{escape(desc)}</description>
      <styleUrl>#crePoly</styleUrl>
      <Polygon>
        <outerBoundaryIs><LinearRing><coordinates>{coord_str}</coordinates></LinearRing></outerBoundaryIs>
      </Polygon>
    </Placemark>"""

def marker_placemark(name, desc, lat, lon):
    return f"""
    <Placemark>
      <name>{escape(name)}</name>
      <description>{escape(desc)}</description>
      <styleUrl>#creIcon</styleUrl>
      <Point><coordinates>{lon},{lat},0</coordinates></Point>
    </Placemark>"""

placemarks = []
for r in records:
    name = r['account']
    desc = r['description']
    if r['geom_type'] == 'radius_circle':
        placemarks.append(polygon_placemark(name, desc, r['geom_data']))
    if r.get('center'):
        clat, clon = r['center']
        placemarks.append(marker_placemark(name, desc, clat, clon))

kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{escape(map_name)}</name>
    {style_block()}
    {''.join(placemarks)}
  </Document>
</kml>"""

with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
    f.write(kml)

print("Wrote KML, size:", len(kml), "bytes, placemarks:", len(placemarks))
