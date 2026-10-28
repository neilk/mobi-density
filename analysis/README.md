# Mobi bike-share analysis

Two maps of Mobi bike-share riding in Vancouver, from the system's trip data
and the OpenStreetMap street network:

- `output/flow_map.html`: one month of riding, every street segment shaded by
  how many riders passed along it, switchable by rider type, weekday/weekend
  and time of day. Every trip of the month, round trips included, is spread
  over the routes it could have taken (`flood-routing.md`).
- `output/map.html`: the October 2026 forecast with busy street crossings,
  crossroads, stations and voting places.

## Layout

```
data/
  original_data/   Mobi monthly trip exports and GBFS station feeds (the source of truth)
  stations.csv     geocoded station table (name variants -> id, lat, lon)
  osm/             OSM highway extract for routing, plus the attractors extract (waterfront, parks, shops)
                   for round-trip destinations; neither committed, see data/osm/README.md
  elevation/       terrain tiles for slope-aware routing; not committed, run elevation/download.sh
  voting_places_*.csv
analysis/
  common.py            shared paths, time blocks, forecast weights, loaders
  elevation.py         ground elevation from the terrain tiles (pure-Python PNG reader)
  attractors.py        scenic and commercial scores for a point, from the attractors extract
  prep.py              original_data -> data/trips_clean.csv, data/stations_canonical.csv
  station_time.py      -> output/station_time_blocks.csv
  october_forecast.py  -> output/october_trips_forecast.csv (pair forecast; routes.py imports it)
  routes.py            -> output/busy_street_crossings.csv, crossroads.csv, route_flows.json
  build_map.py         -> output/map.html
  corridors.py         the corridor sampler: distance tables, shaken routes, round trips
  flows.py             -> output/flows_YYYY-MM.json, one month's trips spread over the streets
  build_flow_map.py    -> output/flow_map.html
  trip_types.py        -> output/trip_types.json, k-means over a year of trips (see trip-types.md)
  build_trip_types.py  -> output/trip_types.html
  flood_demo.py        -> output/flood_demo.html, corridor-routing demo (see flood-routing.md;
                       street-costs.md explains how bike infrastructure enters the routing)
  tests/               unit tests: uv run python -m unittest discover -s tests -t .
```

`data/trips_clean.csv` is not committed; `prep.py` rebuilds it from
`original_data` in a few seconds. `data/osm/vancouver_highways.json` (50 MB) is not
committed either; `data/osm/download.sh` fetches it from Overpass. `routes.py`
needs it, and since nothing in `output/` is committed, so does any fresh build.

## Build

Needs [`uv`](https://docs.astral.sh/uv/), which reads `.python-version` and
installs Python 3.14 for you. There are no third-party packages. From the repo
root:

```sh
data/osm/download.sh             # OSM street network extract from Overpass, ~50 MB, 10-20 s
data/elevation/download.sh       # terrain tiles for slope (optional; routing ignores slope without them)
data/osm/download_attractors.sh  # waterfront, parks and shops for round-trip destinations (flood_demo.py)
cd analysis
uv sync                          # creates .venv with Python 3.14
uv run python prep.py            # clean trips and canonical station table
uv run python station_time.py    # station x time-block table
uv run python routes.py          # forecast, routing, crossings and crossroads (needs the OSM extract)
uv run python build_map.py       # output/map.html
uv run python flows.py           # one month's trips over corridors -> output/flows_YYYY-MM.json (half an hour the first time)
uv run python build_flow_map.py  # output/flow_map.html
uv run python trip_types.py      # cluster the year's trips -> output/trip_types.json (two minutes; needs the attractors extract)
uv run python build_trip_types.py  # output/trip_types.html
```

`flows.py` takes the latest month in the trip table by default; give it a
`YYYY-MM` for another. It needs all three extracts (OSM, attractors, terrain)
and caches its sampled routes under `output/cache/` after every origin, so an
interrupted run resumes, a rerun is free and a second month only samples what
is new. It uses one worker per core, at most one per 3 GiB of memory
(`--workers N` to override). Tests:

```sh
uv run python -m unittest discover -s tests -t .
```

If the Overpass download fails (504s are common when the server is busy), retry
or point `OVERPASS_URL` at a mirror; the script prints one.

`output/` is gitignored, so a fresh clone has no map until the pipeline above
has been run once.

## View

Each map is a single self-contained HTML file; its data is inlined and the
basemap and Leaflet come from the web. `output/map.html` can be opened
straight from disk, or served over HTTP for a stable localhost URL.
`serve.sh` at the repo root runs Python's built-in server:

```sh
./serve.sh          # http://localhost:8000/analysis/output/map.html
./serve.sh 8080     # another port
```

Any static file server works just as well. For example, from the repo root:

```sh
uv run --project analysis python -m http.server 8000   # then open http://localhost:8000/analysis/output/map.html
npx serve analysis/output        # or: http://localhost:3000/map.html
```
