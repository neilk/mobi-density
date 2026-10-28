# OSM street network extract

This directory holds the OpenStreetMap data that `analysis/routes.py` routes
station-to-station trips over, and the tooling to fetch it.

| File | What it is |
|------|------------|
| `query.ql` | The Overpass QL query: every `highway=*` way in a bounding box around Vancouver, the nodes of those ways, and the bicycle route relations (used for bikeway names). The box is the City of Vancouver plus UBC, with a margin into Burnaby and the North Shore so routes near the edges have somewhere to go. |
| `download.sh` | Sends `query.ql` to the Overpass API and saves the answer as `vancouver_highways.json`. It writes to a temporary file first and only moves it into place after checking that the result is valid JSON, carries no Overpass error remark, and has roughly the expected number of ways, nodes and relations. Set `OVERPASS_URL` to use a mirror. |
| `vancouver_highways.json` | The extract itself, about 50 MB. **Not committed** (see `.gitignore`); `routes.py` is the only script that reads it. |

The routing outputs built from the extract (`analysis/output/route_flows.json`,
`busy_street_crossings.csv`, `crossroads.csv`) are committed, so you only need
the extract to rerun `routes.py`.

## Getting the extract

From the repo root:

```sh
data/osm/download.sh
```

It takes about 10-20 seconds. If `overpass-api.de` is busy, retry or point the
script at a mirror:

```sh
OVERPASS_URL=https://overpass.kumi.systems/api/interpreter data/osm/download.sh
```

A good download has roughly 78,000 ways, 250,000 nodes and 200 relations; the
script prints the counts and the OSM data timestamp.

## Reproducibility

The committed outputs were built from an extract with OSM data as of
`2026-10-04T23:08:06Z`. A fresh download picks up later edits, so rerunning
`routes.py` on it will shift the outputs slightly.

The query was reconstructed from the original extract by matching way sets; a
download on 2026-10-12 reproduced 99.98% of its ways and all of its relations.
The original was run with a west bound of -123.275 (confirmed from the session
that made it); no way in the extract lies only in the strip between -123.275
and -123.27, so the missing 0.02% is OSM edits made after 2026-10-04.

OSM data is © OpenStreetMap contributors, ODbL.
