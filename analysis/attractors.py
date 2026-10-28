"""Where round-trip riders go: scenic and commercial scores for any point.

Reads data/osm/vancouver_attractors.json (data/osm/download_attractors.sh).

- scenic(x, y): 1.0 within WATER_M of the shoreline or a lake, or inside a park
  or beach polygon, else 0.0. Casual riders' destinations.
- commercial(x, y): shops and amenities within POI_M, capped, scaled 0..1.
  Errand destinations.
- home(x, y): fraction of a HOME_M disc that is residential land use, 0..1.
  Whether anyone lives near a station, so whether its round trips can be
  errands at all.

Coordinates are the projected metres used by routes.Network (x east, y north).
"""
import json
from collections import defaultdict
from math import cos, hypot, log1p, radians

from common import DATA

ATTRACTORS = DATA / "osm" / "vancouver_attractors.json"
LAT0 = 49.27
MX, MY = 111320 * cos(radians(LAT0)), 110540
WATER_M = 150.0      # how close to the water counts as waterfront (the seawall under the Prospect Point cliffs is 140 m from the mapped coastline)
POI_M = 150.0        # radius for counting shops and amenities
POI_CAP = 40         # this many shops nearby saturates the commercial score (log scale, so 10 is about 0.65)
HOME_M = 400.0       # radius for "does anyone live here"
STEP_M = 25.0        # spacing of sample points along shorelines
CELL = 100           # grid cell for the spatial index, metres


def project(lat, lon):
    return (lon + 123.12) * MX, (lat - LAT0) * MY


def _rings_from_relation(rel, ways):
    """Assemble closed rings from a multipolygon relation's outer ways."""
    pieces = [list(ways[m["ref"]]) for m in rel["members"]
              if m["type"] == "way" and m.get("role", "outer") in ("outer", "") and m["ref"] in ways]
    rings = []
    while pieces:
        ring = pieces.pop()
        while ring[0] != ring[-1]:
            for i, p in enumerate(pieces):
                if p[0] == ring[-1]:
                    ring += p[1:]
                elif p[-1] == ring[-1]:
                    ring += p[-2::-1]
                elif p[-1] == ring[0]:
                    ring = p[:-1] + ring
                elif p[0] == ring[0]:
                    ring = p[::-1][:-1] + ring
                else:
                    continue
                pieces.pop(i)
                break
            else:
                break        # open ring: unusable
        if ring[0] == ring[-1] and len(ring) > 3:
            rings.append(ring)
    return rings


def _inside(x, y, ring):
    """Ray casting, ring as [(x, y), ...] with first == last."""
    inside = False
    for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


class Attractors:
    """.available is False when the extract has not been downloaded."""

    def __init__(self):
        self.available = ATTRACTORS.is_file()
        self.water = defaultdict(list)     # grid cell -> sample points on shorelines
        self.pois = defaultdict(list)      # grid cell -> shop/amenity points
        self.parks = defaultdict(list)     # grid cell -> indices of park rings touching the cell
        self.homes = defaultdict(list)     # grid cell -> indices of residential rings touching the cell
        self.rings = []
        if not self.available:
            return
        els = json.load(open(ATTRACTORS))["elements"]
        nodes = {e["id"]: project(e["lat"], e["lon"]) for e in els if e["type"] == "node"}
        way_pts = {e["id"]: [nodes[n] for n in e["nodes"] if n in nodes] for e in els if e["type"] == "way"}
        for e in els:
            tags = e.get("tags", {})
            if e["type"] == "node" and ("shop" in tags or "amenity" in tags):
                self._add_poi(nodes[e["id"]])
            elif e["type"] == "way" and ("shop" in tags or "amenity" in tags):
                pts = way_pts[e["id"]]
                if pts:
                    self._add_poi((sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)))
            elif e["type"] == "way" and tags.get("natural") in ("coastline", "water"):
                self._add_shore(way_pts[e["id"]])
            elif e["type"] == "way" and (tags.get("leisure") == "park" or tags.get("natural") == "beach"):
                pts = way_pts[e["id"]]
                if len(pts) > 3 and pts[0] == pts[-1]:
                    self._add_ring(pts, self.parks)
            elif e["type"] == "way" and tags.get("landuse") == "residential":
                pts = way_pts[e["id"]]
                if len(pts) > 3 and pts[0] == pts[-1]:
                    self._add_ring(pts, self.homes)
            elif e["type"] == "relation":
                for ring in _rings_from_relation(e, way_pts):
                    if tags.get("natural") == "water":
                        self._add_shore(ring)
                    elif tags.get("landuse") == "residential":
                        self._add_ring(ring, self.homes)
                    else:
                        self._add_ring(ring, self.parks)

    def _cell(self, p):
        return int(p[0] // CELL), int(p[1] // CELL)

    def _add_poi(self, p):
        self.pois[self._cell(p)].append(p)

    def _add_shore(self, pts):
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            d = hypot(x1 - x0, y1 - y0)
            n = max(1, int(d // STEP_M))
            for k in range(n + 1):
                p = (x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n)
                self.water[self._cell(p)].append(p)

    def _add_ring(self, ring, index):
        i = len(self.rings)
        self.rings.append(ring)
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        for cx in range(int(min(xs) // CELL), int(max(xs) // CELL) + 1):
            for cy in range(int(min(ys) // CELL), int(max(ys) // CELL) + 1):
                index[(cx, cy)].append(i)

    def _in_any(self, index, x, y):
        return any(_inside(x, y, self.rings[i]) for i in index.get((int(x // CELL), int(y // CELL)), ()))

    def home(self, x, y):
        """Fraction of a HOME_M disc around the point that is residential land use."""
        if not self.available:
            return 0.0
        hits = n = 0
        for dx in range(-4, 5):
            for dy in range(-4, 5):
                px, py = x + dx * HOME_M / 4, y + dy * HOME_M / 4
                if hypot(px - x, py - y) <= HOME_M:
                    n += 1
                    hits += self._in_any(self.homes, px, py)
        return hits / n

    def scenic_near(self, x, y, radius):
        """Fraction of a disc around the point that is scenic (waterfront, park or beach)."""
        if not self.available:
            return 0.0
        hits = n = 0
        for dx in range(-4, 5):
            for dy in range(-4, 5):
                px, py = x + dx * radius / 4, y + dy * radius / 4
                if hypot(px - x, py - y) <= radius:
                    n += 1
                    hits += self.scenic(px, py) > 0
        return hits / n

    def _near(self, grid, x, y, radius):
        cx, cy = int(x // CELL), int(y // CELL)
        r = int(radius // CELL) + 1
        for gx in range(cx - r, cx + r + 1):
            for gy in range(cy - r, cy + r + 1):
                for px, py in grid.get((gx, gy), ()):
                    if hypot(px - x, py - y) <= radius:
                        yield px, py

    def scenic(self, x, y, parks=True):
        """1.0 on the waterfront, or inside a park or beach when parks is True.
        Route costs use waterfront only: a park polygon also contains the
        paths beside the Stanley Park Causeway, which are nobody's idea of scenic."""
        if not self.available:
            return 0.0
        for _ in self._near(self.water, x, y, WATER_M):
            return 1.0
        if parks and self._in_any(self.parks, x, y):
            return 1.0
        return 0.0

    def commercial(self, x, y):
        if not self.available:
            return 0.0
        n = sum(1 for _ in self._near(self.pois, x, y, POI_M))
        return log1p(min(n, POI_CAP)) / log1p(POI_CAP)
