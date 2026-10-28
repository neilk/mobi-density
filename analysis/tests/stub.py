"""A five-node street network for the corridor tests: a 100 m square (nodes
0-3, ways 0-3) with a 100 m dead-end spur from node 1 to node 4 (way 4).
Every way costs its length (factor 1.0) and runs both directions."""
from math import cos, radians

from routes import Network

LAT0, LON0 = 49.27, -123.12
MX, MY = 111320 * cos(radians(LAT0)), 110540
XY = [(0, 0), (100, 0), (100, 100), (0, 100), (200, 0)]
LINKS = [(0, 1), (1, 2), (2, 3), (3, 0), (1, 4)]          # way index = position


class StubNet(Network):
    def __init__(self):                       # no super().__init__: no OSM file
        self.xy = list(XY)
        self.latlon = [(LAT0 + y / MY, LON0 + x / MX) for x, y in XY]
        self.ways = [{"hw": "residential", "name": f"way {i}", "route": "", "lanes": 0, "major": False}
                     for i in range(len(LINKS))]
        self.adj = [[] for _ in XY]
        for wi, (a, b) in enumerate(LINKS):
            d = self.dist(a, b)
            self.adj[a].append((b, d, wi))
            self.adj[b].append((a, d, wi))
        self.snappable = set(range(len(XY)))
        self.ways_at = {}


class StubAttractors:
    available = True

    def scenic(self, x, y, parks=True):
        return 0.0

    def scenic_near(self, x, y, radius):
        return 0.0

    def home(self, x, y):
        return 0.0

    def commercial(self, x, y):
        return 0.0
