"""Route the predicted October trips over the OpenStreetMap network and find
where they concentrate.

Every predicted one-way trip is sent along a bike-friendly shortest path through
a local OSM extract (data/osm/vancouver_highways.json). Writes, in output/:
  busy_street_crossings.csv  where routes on bikeways/side streets cross a major road
  crossroads.csv             junctions where flows from three or more directions meet
  route_flows.json           per-segment volumes, used by build_map.py
"""
import csv
import heapq
import json
from collections import Counter, defaultdict
from math import atan2, cos, degrees, hypot, radians

from common import DATA, OUT, Forecaster, load_stations, load_trips
from elevation import Terrain
from october_forecast import pair_forecast

OSM = DATA / "osm" / "vancouver_highways.json"
EXCLUDED = {"motorway", "motorway_link", "steps", "construction", "corridor", "elevator",
            "proposed", "platform", "busway", "services", "bridleway"}
MAJOR = {"trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link"}
# How much longer a metre feels on each kind of way; below 1 attracts riders.
# Checked against the distances members actually rode on 2,800 station pairs:
# pure shortest paths come out 4.5% short of the median ridden distance, these
# weights 2% short, and stronger bikeway preferences fit no better.
BASE_COST = {"cycleway": 0.75, "residential": 1.0, "living_street": 1.0, "unclassified": 1.0,
             "service": 1.5, "track": 1.5, "pedestrian": 2.0,
             "tertiary": 1.2, "tertiary_link": 1.2, "secondary": 1.5, "secondary_link": 1.5,
             "primary": 1.9, "primary_link": 1.9, "trunk": 3.0, "trunk_link": 3.0}
WITH_LANE = {"tertiary": 1.0, "secondary": 1.15, "primary": 1.3, "trunk": 1.8}
BIKE_OK = {"yes", "designated", "permissive"}
# Unpaved bikeways and paths ride like a plain path, not a bikeway: Mobi bikes
# stay off gravel switchbacks such as Avison Trail up to Prospect Point.
UNPAVED = {"gravel", "fine_gravel", "dirt", "ground", "grass", "sand", "unpaved", "mud", "earth", "woodchips"}
# A Mobi bike on a sloping dirt or gravel track is a push, not a ride: edges on
# unpaved ways at or above this grade cost this much more, in either direction.
UNPAVED_SLOPE, UNPAVED_SLOPE_COST = 0.03, 4.0
# OSM ways that exist but that riders do not know or use: local knowledge OSM cannot carry.
OBSCURE_WAYS = {
    975314385: "dirt underpass at the Lions Gate abutment joining the two causeway bike paths; almost nobody knows it",
}
CLUSTER_M = 35
LAT0 = 49.27
MX, MY = 111320 * cos(radians(LAT0)), 110540   # metres per degree of lon / lat


def way_cost(tags, on_route):
    """Cost factor for cycling a way, or None if bikes can't use it."""
    hw, bicycle, access = tags.get("highway"), tags.get("bicycle"), tags.get("access")
    if hw in EXCLUDED or bicycle == "no" or tags.get("area") == "yes":
        return None
    if access in {"private", "no", "customers", "permit"} and bicycle not in BIKE_OK:
        return None
    if hw in ("footway", "path"):
        if bicycle in BIKE_OK:
            cost = 0.8
        elif bicycle == "dismount":
            cost = 1.0             # walk-your-bike link, priced below; the seawall under Lions Gate Bridge is one
        elif hw == "path" and bicycle is None:
            cost = 1.5
        else:
            return None            # plain footways and sidewalks
    elif hw in BASE_COST:
        cost = BASE_COST[hw]
        lane_tags = {v for k, v in tags.items() if k.startswith("cycleway") and ":" not in k[9:]}
        if lane_tags & {"lane", "track", "share_busway"}:
            cost = min(cost, WITH_LANE.get(hw.replace("_link", ""), cost))
        elif "shared_lane" in lane_tags:
            cost *= 0.9
    else:
        return None
    if tags.get("surface") in UNPAVED:
        cost = max(cost, 1.5)
    if bicycle == "dismount":
        # Walk-your-bike stretches stay routable (the seawall has a few) but a
        # short dismount connector, like the underpass at the Lions Gate abutment
        # that joins the two causeway paths, must not come out nearly free.
        cost = max(cost, 10.0)
    if on_route:
        cost = max(0.65, cost * 0.8)
    return cost


def slope_factor(tags, grade):
    """Extra cost for an edge at this grade (rise over run, absolute); 1 when flat or paved."""
    if grade is not None and grade >= UNPAVED_SLOPE and tags.get("surface") in UNPAVED:
        return UNPAVED_SLOPE_COST
    return 1.0


def bikes_both_ways(tags):
    if tags.get("oneway:bicycle") == "no":
        return True
    return any(k.startswith("cycleway") and (str(v).startswith("opposite") or (k.endswith(":oneway") and v in ("-1", "no")))
               for k, v in tags.items())


def rider_way_kind(w):
    if w["hw"] == "cycleway" or w["hw"] in ("path", "footway"):
        return "bike path"
    if w["route"]:
        return "signed bikeway"
    if w["hw"].startswith("tertiary"):
        return "collector street"
    return "local street"


class Network:
    def __init__(self):
        els = json.load(open(OSM))["elements"]
        route_of = {}
        for e in els:
            if e["type"] == "relation":
                for m in e["members"]:
                    if m["type"] == "way":
                        route_of.setdefault(m["ref"], e["tags"].get("name", "bike route"))
        raw_nodes = {e["id"]: e for e in els if e["type"] == "node"}
        terrain = Terrain()
        if not terrain.available:
            print("no elevation tiles in data/elevation; routing ignores slope (run data/elevation/download.sh)")
        self.idx, self.xy, self.latlon, self.node_tags, self.ele = {}, [], [], [], []
        self.ways, self.adj = [], []
        self.major_at = defaultdict(set)      # node -> indices of major ways through it
        self.ways_at = defaultdict(set)       # node -> indices of every usable or major way
        self.snappable = set()

        def node(osm_id):
            i = self.idx.get(osm_id)
            if i is None:
                n = raw_nodes[osm_id]
                i = self.idx[osm_id] = len(self.xy)
                self.xy.append(((n["lon"] + 123.12) * MX, (n["lat"] - LAT0) * MY))
                self.latlon.append((n["lat"], n["lon"]))
                self.node_tags.append(n.get("tags", {}))
                self.ele.append(terrain.ele(n["lat"], n["lon"]))
                self.adj.append([])
            return i

        for e in els:
            if e["type"] != "way":
                continue
            tags = e["tags"]
            hw = tags.get("highway")
            cost = None if e["id"] in OBSCURE_WAYS else way_cost(tags, e["id"] in route_of)
            if cost is None and hw not in MAJOR:
                continue
            try:
                lanes = int(str(tags.get("lanes", "0")).split(";")[0])
            except ValueError:
                lanes = 0
            wi = len(self.ways)
            self.ways.append({"hw": hw, "name": tags.get("name") or route_of.get(e["id"]) or "",
                              "route": route_of.get(e["id"], ""), "lanes": lanes, "major": hw in MAJOR})
            ns = [node(n) for n in e["nodes"]]
            for n in ns:
                self.ways_at[n].add(wi)
                if hw in MAJOR:
                    self.major_at[n].add(wi)
            if cost is None:
                continue
            if hw not in ("service", "trunk", "trunk_link", "track", "pedestrian"):
                self.snappable.update(ns)
            oneway = tags.get("oneway")
            fwd = oneway != "-1"
            back = oneway not in ("yes", "true", "1") and tags.get("junction") != "roundabout" or bikes_both_ways(tags)
            if oneway == "-1":
                back = True
                fwd = bikes_both_ways(tags)
            for a, b in zip(ns, ns[1:]):
                d = self.dist(a, b)
                c = d * cost * slope_factor(tags, self.grade(a, b))
                if fwd:
                    self.adj[a].append((b, c, wi))
                if back:
                    self.adj[b].append((a, c, wi))

    def dist(self, a, b):
        return hypot(self.xy[a][0] - self.xy[b][0], self.xy[a][1] - self.xy[b][1])

    def grade(self, a, b):
        """Absolute rise over run between two nodes, or None without elevation.
        The run is floored at 30 m so DEM noise on short edges does not read as a hill."""
        ea, eb = self.ele[a], self.ele[b]
        if ea is None or eb is None:
            return None
        return abs(eb - ea) / max(self.dist(a, b), 30.0)

    def nearest(self, lat, lon, candidates_grid):
        x, y = (lon + 123.12) * MX, (lat - LAT0) * MY
        gx, gy = int(x // 100), int(y // 100)
        best, best_d = None, 1e9
        for r in range(1, 6):
            for cx in range(gx - r, gx + r + 1):
                for cy in range(gy - r, gy + r + 1):
                    for n in candidates_grid.get((cx, cy), ()):
                        d = hypot(self.xy[n][0] - x, self.xy[n][1] - y)
                        if d < best_d:
                            best, best_d = n, d
            if best is not None and best_d < r * 100:
                break
        return best, best_d

    def shortest_paths(self, src, targets):
        """Dijkstra from src; returns target -> (node path, way index per step)."""
        dist, prev = {src: 0.0}, {}
        todo, heap = set(targets), [(0.0, src)]
        while heap and todo:
            d, u = heapq.heappop(heap)
            if d > dist[u]:
                continue
            todo.discard(u)
            for v, c, wi in self.adj[u]:
                nd = d + c
                if nd < dist.get(v, 1e18):
                    dist[v] = nd
                    prev[v] = (u, wi)
                    heapq.heappush(heap, (nd, v))
        out = {}
        for t in targets:
            if t not in dist:
                continue
            nodes, ways, n = [t], [], t
            while n != src:
                n, wi = prev[n]
                nodes.append(n); ways.append(wi)
            out[t] = (nodes[::-1], ways[::-1])
        return out


def cluster(net, nodes_by_weight):
    """Greedy clustering: the busiest node claims every other node within CLUSTER_M."""
    grid = defaultdict(list)
    for n in nodes_by_weight:
        grid[(int(net.xy[n][0] // CLUSTER_M), int(net.xy[n][1] // CLUSTER_M))].append(n)
    assigned = {}
    for n in sorted(nodes_by_weight, key=lambda n: -nodes_by_weight[n]):
        if n in assigned:
            continue
        gx, gy = int(net.xy[n][0] // CLUSTER_M), int(net.xy[n][1] // CLUSTER_M)
        for cx in (gx - 1, gx, gx + 1):
            for cy in (gy - 1, gy, gy + 1):
                for m in grid[(cx, cy)]:
                    if m not in assigned and net.dist(n, m) <= CLUSTER_M:
                        assigned[m] = n
    return assigned


def control_near(net, tagged_grid, n):
    """Traffic control tagged within 30 m of a node."""
    x, y = net.xy[n]
    found = set()
    for cx in range(int(x // 50) - 1, int(x // 50) + 2):
        for cy in range(int(y // 50) - 1, int(y // 50) + 2):
            for m, kind in tagged_grid.get((cx, cy), ()):
                if hypot(net.xy[m][0] - x, net.xy[m][1] - y) <= 30:
                    found.add(kind)
    return "signal" if "signal" in found else "stop sign" if "stop" in found else "none tagged"


def names_at(net, nodes, limit=3):
    c = Counter()
    for n in nodes:
        for wi in net.ways_at[n]:
            if net.ways[wi]["name"]:
                c[net.ways[wi]["name"]] += 1
    return [name for name, _ in c.most_common(limit)]


def main():
    stations = load_stations()
    trips = list(load_trips())
    forecast = pair_forecast(trips, Forecaster(trips), stations)
    pairs = [r for r in forecast if not r["round_trip"] and "not renting" not in r["note"]]
    routable_total = sum(r["oct_2026_trips"] for r in pairs)
    print(f"routing {len(pairs):,} one-way pairs carrying {routable_total:,.0f} of "
          f"{sum(r['oct_2026_trips'] for r in forecast):,.0f} predicted October trips")

    net = Network()
    print(f"network: {len(net.xy):,} nodes, {sum(map(len, net.adj)):,} directed edges, {len(net.ways):,} ways")
    snap_grid = defaultdict(list)
    for n in net.snappable:
        snap_grid[(int(net.xy[n][0] // 100), int(net.xy[n][1] // 100))].append(n)
    snap = {}
    for sid, s in stations.items():
        snap[sid], d = net.nearest(s["lat"], s["lon"], snap_grid)
        if d > 120:
            print(f"  station {sid} {s['name']} is {d:.0f} m from the nearest street node")

    by_origin = defaultdict(list)
    for r in pairs:
        by_origin[r["from_id"]].append(r)
    # october, weekday am, weekday pm, october by members, per weekend day, per weekend day by members
    vol = lambda r: (r["oct_2026_trips"], r["weekday_am_commute"], r["weekday_pm_commute"],
                     r["oct_2026_trips"] * r["member_share"], r["per_weekend_day"],
                     r["per_weekend_day"] * r["weekend_member_share"])
    add = lambda acc, v: [a + b for a, b in zip(acc, v)]

    paths, unroutable = [], 0            # (forecast row, node path, way per step)
    for sid, rows in by_origin.items():
        found = net.shortest_paths(snap[sid], {snap[r["to_id"]] for r in rows})
        for r in rows:
            p = found.get(snap[r["to_id"]])
            if p and len(p[0]) > 1:
                paths.append((r, p[0], p[1]))
            else:
                unroutable += r["oct_2026_trips"]
    print(f"routed {len(paths):,} pairs; {unroutable:,.0f} trips unroutable or between stations at the same node")

    # sanity check against the distances riders actually covered
    covered = defaultdict(list)
    for t in trips:
        if t["departure"][:7] in ("2025-09", "2025-10", "2025-11"):
            covered[(t["dep_id"], t["ret_id"])].append(int(t["distance_m"]))
    ratios = []
    for r, nodes, _ in paths[:500]:
        ds = sorted(d for d in covered[(r["from_id"], r["to_id"])] if d > 0)
        if len(ds) >= 10:
            ratios.append(sum(net.dist(a, b) for a, b in zip(nodes, nodes[1:])) / ds[len(ds) // 2])
    ratios.sort()
    print(f"routed length / median distance ridden, top pairs: median {ratios[len(ratios) // 2]:.2f}, "
          f"10th-90th pct {ratios[len(ratios) // 10]:.2f}-{ratios[9 * len(ratios) // 10]:.2f} (n={len(ratios)})")

    # ---- segment flows, and candidate nodes for the two searches
    edge_flow = defaultdict(lambda: [0.0] * 6)
    edge_way = {}
    node_flow = Counter()
    nbrs = defaultdict(set)
    crossing_w = Counter()
    for r, nodes, ways in paths:
        v = vol(r)
        for i, (a, b) in enumerate(zip(nodes, nodes[1:])):
            k = (a, b) if a < b else (b, a)
            edge_flow[k] = add(edge_flow[k], v)
            edge_way[k] = ways[i]
            nbrs[a].add(b); nbrs[b].add(a)
        for i in range(1, len(nodes) - 1):
            n = nodes[i]
            node_flow[n] += v[0]
            if n in net.major_at and not net.ways[ways[i - 1]]["major"] and not net.ways[ways[i]]["major"]:
                crossing_w[n] += v[0]

    tagged_grid = defaultdict(list)
    for n, tags in enumerate(net.node_tags):
        kind = ("signal" if "traffic_signals" in (tags.get("highway"), tags.get("crossing")) or tags.get("crossing:signals") == "yes"
                else "stop" if tags.get("highway") == "stop" else None)
        if kind:
            tagged_grid[(int(net.xy[n][0] // 50), int(net.xy[n][1] // 50))].append((n, kind))

    # ---- 1. bikeway / side-street routes crossing a major road
    cross_cluster = cluster(net, crossing_w)
    cx = defaultdict(lambda: {"v": [0.0] * 6, "pairs": 0, "nodes": set(), "rider": Counter(), "rider_way": Counter()})
    for r, nodes, ways in paths:
        v, seen = vol(r), set()
        for i in range(1, len(nodes) - 1):
            n = nodes[i]
            if n in cross_cluster and not net.ways[ways[i - 1]]["major"] and not net.ways[ways[i]]["major"]:
                c = cross_cluster[n]
                cx[c]["nodes"].add(n)
                if c in seen:
                    continue
                seen.add(c)
                cx[c]["v"] = add(cx[c]["v"], v)
                cx[c]["pairs"] += 1
                w = net.ways[ways[i - 1]]
                cx[c]["rider"][rider_way_kind(w)] += v[0]
                cx[c]["rider_way"][w["name"] or net.ways[ways[i]]["name"] or "(unnamed path)"] += v[0]
    crossings = []
    for c, d in cx.items():
        bike_route = d["rider_way"].most_common(1)[0][0]
        majors = [net.ways[wi] for n in d["nodes"] for wi in net.major_at[n]]
        # a bike path usually carries the name of the street it runs along; that street isn't the one crossed
        majors = [w for w in majors if w["name"] != bike_route] or majors
        top = max(majors, key=lambda w: (["secondary", "primary", "trunk"].index(w["hw"].replace("_link", "")), w["lanes"]))
        crossings.append({
            "major_road": " / ".join(sorted({w["name"] for w in majors if w["name"]})) or "(unnamed)",
            "bike_route": bike_route,
            "rider_way_type": d["rider"].most_common(1)[0][0],
            "road_class": top["hw"].replace("_link", ""), "lanes": max(w["lanes"] for w in majors) or "",
            "control": control_near(net, tagged_grid, c),
            "oct_trips": round(d["v"][0]), "per_weekday_07_10": round(d["v"][1], 1),
            "per_weekday_16_19": round(d["v"][2], 1), "member_share": round(d["v"][3] / d["v"][0], 2),
            "per_weekend_day": round(d["v"][4], 1),
            "weekend_member_share": round(d["v"][5] / d["v"][4], 2) if d["v"][4] else 0,
            "station_pairs": d["pairs"], "lat": round(net.latlon[c][0], 6), "lon": round(net.latlon[c][1], 6),
        })
    for r in crossings:
        # a signal on a primary/trunk road or one with 4+ lanes is where riders wait longest
        r["long_wait_likely"] = int(r["control"] == "signal" and (r["road_class"] != "secondary" or (r["lanes"] or 0) >= 4))
    crossings.sort(key=lambda r: -r["oct_trips"])

    # ---- 2. crossroads: junctions where flow arrives on three or more arms
    junction_w = {n: node_flow[n] for n in node_flow if len(nbrs[n]) >= 3}
    j_cluster = cluster(net, junction_w)
    jx = defaultdict(lambda: {"v": [0.0] * 6, "sq": 0.0, "pairs": 0, "arms": Counter(), "nodes": set(), "stations": set()})
    for r, nodes, ways in paths:
        v = vol(r)
        # A path may touch a cluster several times (member junction nodes are
        # interleaved with unclustered nodes inside the same intersection), so
        # count each path once per cluster, from its first entry to its last exit.
        cl = [j_cluster.get(n) for n in nodes]
        visits = {}
        for i in range(1, len(nodes) - 1):
            if cl[i] is not None:
                first, _, ns = visits.setdefault(cl[i], (i, i, set()))
                visits[cl[i]] = (first, i, ns)
                ns.add(nodes[i])
        for c, (i, j, ns) in visits.items():
            if cl[i - 1] == c or j >= len(nodes) - 1:          # starts or ends here rather than passing through
                continue
            d = jx[c]
            d["v"] = add(d["v"], v); d["sq"] += v[0] ** 2; d["pairs"] += 1
            d["nodes"].update(ns)
            d["stations"].update((r["from_id"], r["to_id"]))
            # take each arm's direction from a point 60 m out, past the junction's own geometry
            a, b = i - 1, j + 1
            while a > 0 and net.dist(nodes[a], c) < 60:
                a -= 1
            while b < len(nodes) - 1 and net.dist(nodes[b], c) < 60:
                b += 1
            for outside in (nodes[a], nodes[b]):
                bearing = degrees(atan2(net.xy[outside][0] - net.xy[c][0], net.xy[outside][1] - net.xy[c][1])) % 360
                d["arms"][int(((bearing + 22.5) % 360) // 45)] += v[0]
    compass = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    crossroads = []
    for c, d in jx.items():
        total = sum(d["arms"].values())
        big = [(a, f) for a, f in d["arms"].most_common() if f >= 0.15 * total]
        if len(big) < 3:
            continue
        crossroads.append({
            "location": " / ".join(names_at(net, d["nodes"])) or "(unnamed)",
            "oct_trips_through": round(d["v"][0]), "per_weekday_07_10": round(d["v"][1], 1),
            "per_weekday_16_19": round(d["v"][2], 1), "member_share": round(d["v"][3] / d["v"][0], 2),
            "per_weekend_day": round(d["v"][4], 1),
            "weekend_member_share": round(d["v"][5] / d["v"][4], 2) if d["v"][4] else 0,
            "arms": len(big), "arm_shares": " ".join(f"{compass[a]}:{f / total:.0%}" for a, f in sorted(big)),
            "station_pairs": d["pairs"], "effective_pairs": round(d["v"][0] ** 2 / d["sq"]),
            "stations_linked": len(d["stations"]), "control": control_near(net, tagged_grid, c),
            "on_major_road": int(any(n in net.major_at for n in d["nodes"])),
            "lat": round(net.latlon[c][0], 6), "lon": round(net.latlon[c][1], 6),
        })
    crossroads.sort(key=lambda r: -r["oct_trips_through"])

    for name, rows in (("busy_street_crossings.csv", crossings), ("crossroads.csv", crossroads)):
        for i, r in enumerate(rows, 1):
            r["rank"] = i
        with open(OUT / name, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["rank"] + [k for k in rows[0] if k != "rank"], lineterminator="\n")
            w.writeheader(); w.writerows(rows)
        print(f"{len(rows):,} rows -> {OUT / name}")

    segs = [[*map(lambda x: round(x, 5), net.latlon[a] + net.latlon[b]), round(v[0], 1), round(v[1], 2), round(v[2], 2), round(v[4], 2),
             net.ways[edge_way[(a, b)]]["name"]] for (a, b), v in edge_flow.items() if v[0] >= 20]
    json.dump({"routed_trips": round(routable_total - unroutable), "segments": segs},
              open(OUT / "route_flows.json", "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"{len(segs):,} segments with 20+ trips -> {OUT / 'route_flows.json'}")

    # busiest named corridors, by trip-kilometres
    corridor = Counter()
    for (a, b), v in edge_flow.items():
        corridor[net.ways[edge_way[(a, b)]]["name"] or "(unnamed)"] += v[0] * net.dist(a, b) / 1000
    print("\nbusiest corridors (trip-km in October):", ", ".join(f"{n} {k:,.0f}" for n, k in corridor.most_common(15)))
    print("\nTop 25 busy-street crossings (signalised, primary/trunk or 4+ lanes)")
    for r in [r for r in crossings if r["long_wait_likely"]][:25]:
        print(f"  {r['oct_trips']:5d} am {r['per_weekday_07_10']:5.1f} pm {r['per_weekday_16_19']:5.1f} {r['member_share']:4.0%}  "
              f"{r['bike_route']} x {r['major_road']} [{r['road_class']}, {r['lanes']} lanes, {r['rider_way_type']}]")
    print("\nTop 25 crossroads")
    for r in crossroads[:25]:
        print(f"  {r['oct_trips_through']:5d} am {r['per_weekday_07_10']:5.1f} pm {r['per_weekday_16_19']:5.1f} {r['member_share']:4.0%}  "
              f"{r['location']} | {r['arm_shares']} | {r['station_pairs']} pairs, {r['stations_linked']} stations")


if __name__ == "__main__":
    main()
