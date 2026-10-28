#!/bin/sh
# Download elevation tiles covering the OSM extract, for slope-aware routing.
#
# Fetches Terrarium-encoded PNG tiles at zoom 13 (about 12 m per pixel here)
# from the public AWS terrain tile set into 13/{x}/{y}.png next to this script.
# Two dozen tiles, a few MB. analysis/elevation.py reads them; routes.py uses
# them when present and warns and ignores slope when not.
set -eu
cd "$(dirname "$0")" || exit 1

Z=13
# Bounding box of data/osm/vancouver_highways.json, padded a little.
LAT0=49.19; LAT1=49.35; LON0=-123.28; LON1=-122.96

python3 - "$Z" "$LAT0" "$LAT1" "$LON0" "$LON1" <<'PY' | while read -r x y; do
import math, sys
z, lat0, lat1, lon0, lon1 = int(sys.argv[1]), *map(float, sys.argv[2:])
n = 2 ** z
def tile(lat, lon):
    r = math.radians(lat)
    return int((lon + 180) / 360 * n), int((1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * n)
x0, y1 = tile(lat0, lon0); x1, y0 = tile(lat1, lon1)
for x in range(x0, x1 + 1):
    for y in range(y0, y1 + 1):
        print(x, y)
PY
    mkdir -p "$Z/$x"
    f="$Z/$x/$y.png"
    [ -s "$f" ] && continue
    echo "tile $Z/$x/$y"
    curl --fail --silent --show-error -A "bikepop-analysis/1.0" \
        "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/$Z/$x/$y.png" -o "$f.part" && mv "$f.part" "$f"
done
echo "done: $(find "$Z" -name '*.png' | wc -l | tr -d ' ') tiles"
