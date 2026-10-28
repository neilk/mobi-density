#!/bin/sh
# Download the OSM street network extract that analysis/routes.py routes over.
#
# Sends query.ql to the Overpass API and saves the result as
# vancouver_highways.json next to this script (about 50 MB, 10-20 seconds).
#
#   data/osm/download.sh                      use overpass-api.de
#   OVERPASS_URL=<mirror> data/osm/download.sh   use a mirror, e.g.
#       https://overpass.kumi.systems/api/interpreter
#
# The result is written to a temporary file and only moved into place once it
# parses as JSON and has roughly the expected number of ways, nodes and
# relations, so a failed or truncated download never replaces a good extract.
set -eu

cd "$(dirname "$0")" || exit 1

URL="${OVERPASS_URL:-https://overpass-api.de/api/interpreter}"
QUERY=query.ql
OUT=vancouver_highways.json
TMP="$OUT.part"

trap 'rm -f "$TMP"' EXIT

echo "Querying $URL with $QUERY ..."
# The user agent is required: overpass-api.de answers a bare curl request
# with 406 Not Acceptable.
if ! curl --fail --silent --show-error \
     -A "bikepop-analysis/1.0" \
     --data-urlencode "data@$QUERY" \
     "$URL" \
     -o "$TMP"; then
    echo "Download failed. The server may be busy (504 is common); retry, or use a mirror:" >&2
    echo "  OVERPASS_URL=https://overpass.kumi.systems/api/interpreter $0" >&2
    exit 1
fi

echo "Checking the result ..."
python3 - "$TMP" <<'PY'
import json, sys
path = sys.argv[1]
try:
    data = json.load(open(path))
except ValueError as e:
    sys.exit(f"{path} is not valid JSON ({e}); the server probably returned an error page")
if "remark" in data:
    # Overpass puts timeouts and memory errors here and still returns 200.
    sys.exit(f"Overpass reported a problem: {data['remark']}")
counts = {}
for el in data.get("elements", []):
    counts[el["type"]] = counts.get(el["type"], 0) + 1
ways, nodes, rels = counts.get("way", 0), counts.get("node", 0), counts.get("relation", 0)
print(f"  {ways:,} ways, {nodes:,} nodes, {rels:,} relations"
      f" (OSM data as of {data.get('osm3s', {}).get('timestamp_osm_base', 'unknown')})")
# Expected roughly 78,000 ways, 250,000 nodes and 200 relations; allow for OSM edits.
if ways < 60000 or nodes < 200000 or rels < 100:
    sys.exit("Far fewer elements than expected; the download looks incomplete")
PY

mv "$TMP" "$OUT"
echo "Saved $(pwd)/$OUT"
