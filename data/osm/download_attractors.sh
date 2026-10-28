#!/bin/sh
# Download the attractors extract (waterfront, parks, shops) that
# analysis/attractors.py scores round-trip destinations with. Same shape as
# download.sh: query attractors.ql, check the result, then move it into place.
set -eu
cd "$(dirname "$0")" || exit 1
URL="${OVERPASS_URL:-https://overpass-api.de/api/interpreter}"
OUT=vancouver_attractors.json
TMP="$OUT.part"
trap 'rm -f "$TMP"' EXIT
echo "Querying $URL with attractors.ql ..."
if ! curl --fail --silent --show-error -A "bikepop-analysis/1.0" \
     --data-urlencode "data@attractors.ql" "$URL" -o "$TMP"; then
    echo "Download failed; retry or set OVERPASS_URL to a mirror" >&2
    exit 1
fi
python3 - "$TMP" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
if "remark" in data:
    sys.exit(f"Overpass reported a problem: {data['remark']}")
counts = {}
for el in data.get("elements", []):
    counts[el["type"]] = counts.get(el["type"], 0) + 1
print("  " + ", ".join(f"{v:,} {k}s" for k, v in sorted(counts.items())))
if counts.get("way", 0) < 500 or counts.get("node", 0) < 5000:
    sys.exit("Far fewer elements than expected; the download looks incomplete")
PY
mv "$TMP" "$OUT"
echo "Saved $(pwd)/$OUT"
