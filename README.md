# Hiring Zone Map Pipeline

Scripts that turn carrier driver-hiring spreadsheets into KML files for
import into Google My Maps, building CDL-A recruiter hiring-zone maps
(coverage by carrier, categorized OTR / Local / Dedicated / Regional).

Live demo: **https://andrewtaylorhr-ai.github.io/hiring-zone-map/**

## How it works

1. A carrier's hiring spreadsheet is parsed by a carrier-specific `build_*.py`
   script, which geocodes each account's hiring area (radius circle / zip
   cluster / city pin) using the lookups in `reference_data/`, classifies it
   into OTR / Local / Dedicated / Regional based on the account's Home Time
   field, and writes a `records*.pkl` file.
2. A `make_kml_*.py` script turns that `records*.pkl` into a flat (no-folder)
   KML file, with a carrier-specific color/icon style so multiple carriers
   stay visually distinct on the same My Maps layer.
3. `scripts/export_geojson.py` exports the combined data as GeoJSON for the
   `docs/` demo site (served via GitHub Pages).

## Folder structure

- `scripts/` — the pipeline
  - `build_zones.py` — Swift (columnar hiring-area format)
  - `build_cre2.py` — CR England (one worksheet tab per account, `"NNN-miles
    of City, ST"` text field; also dedupes CR England's repeated shared
    terminal-network sheets)
  - `build_pam.py`, `build_transam.py`, `build_usx.py`, `build_jbh.py` —
    PAM, Trans AM, US Express, J.B. Hunt
  - `make_kml_flat.py` — Swift-style KML (rotating color palette, truck icons)
  - `make_kml_cre.py` — CR England-style KML (uniform gold, dollar-sign icons)
  - `export_geojson.py` — exports combined data for the `docs/` demo
  - `state_abbr.py` — state abbreviation ↔ full name helper
- `reference_data/` — geocoding lookups used by the `build_*` scripts
  - `us_cities.csv` — ~30k US cities with lat/lon
  - `zips_latlon.csv` — ~42k US zip codes with lat/lon (fallback for small
    towns not in `us_cities.csv`)
  - `us_states.geojson` — state boundary polygons (last-resort fallback for
    computing a state centroid)
- `docs/` — static demo site (served via GitHub Pages)

Carrier source spreadsheets and generated KML outputs are not included in
this repo (kept local — see `.gitignore`).

## Known limitations

- **Google My Maps doesn't reliably reapply KML inline styling on "Reimport
  and merge."** If a layer already has an established style, a new import's
  colors/icons are often ignored. Reliable fixes: delete and re-import the
  layer fresh (not merge), or manually set "Uniform style" in the My Maps UI.
- **My Maps caps every map at 10 layers.** Each carrier is consolidated down
  to at most 4 layers (OTR / Local / Dedicated / Regional), and KML files are
  flat (no folders) so they can be merged into existing layers.
- Accounts with no location data at all (no city, no state, no radius) are
  intentionally excluded rather than guessed at.
