"""One month of Mobi trips spread over the streets they could have used.

Every trip in the month, round trips included, is grouped by origin,
destination, rider type and 250 m odometer bin; each group is sampled over
its corridor (corridors.py) and its trips are credited, in 24 time slices,
to every street segment its sampled routes use. See flood-routing.md,
"Wiring it in: the monthly flow map".

    uv run python flows.py [YYYY-MM] [--workers N]    -> output/flows_YYYY-MM.json

Defaults: the latest month in data/trips_clean.csv; one worker per core, at most one per 3 GiB of memory.
"""
import csv
import hashlib
import json
import multiprocessing
import os
import sqlite3
import sys
import time
from collections import defaultdict
from statistics import median

import corridors
from attractors import Attractors
from common import BLOCK_NAMES, BLOCK_OF_HOUR, OUT, TRIPS_CLEAN, day_type, load_stations, load_trips
from corridors import Corridors, NoRoute
from routes import OSM, Network, rider_way_kind

SNAP_M = 120          # a station further than this from a street node is not routed
KNOBS = ("SIGMA", "SLACK", "REUSE_PENALTY", "WAYPOINT_SD", "MIN_FILL", "PLEASANT_K", "TURN_CELL", "SCENIC_WAY",
         "COMMERCIAL_BONUS", "SCENIC_NEAR_M", "HOME_CUT", "RIDER_NUDGE", "HOP_TRIES", "WINDOW_SD")
WORKER_GIB = 3        # a sampling worker grows to about a gigabyte; leave headroom

DAYS = ("weekday", "weekend")
RIDERS = ("member", "casual")
SLICES = [f"{day}|{block}|{rider}" for day in DAYS for block in BLOCK_NAMES for rider in RIDERS]
SLICE_INDEX = {name: i for i, name in enumerate(SLICES)}

BIN_M = 250           # odometer bin width for grouping trips
MAX_DRAWS = 30        # routes sampled for a big group
MIN_DRAWS = 8         # routes sampled for a tiny group


def slice_of(trip):
    """Index into SLICES for a trip dict with parsed 'dep' and 'rider'."""
    return SLICE_INDEX[f"{day_type(trip['dep'])}|{BLOCK_OF_HOUR[trip['dep'].hour]}|{trip['rider']}"]


def draws_for(n_trips):
    return int(min(MAX_DRAWS, max(MIN_DRAWS, n_trips)))


def latest_month():
    with open(TRIPS_CLEAN, newline="", encoding="utf-8") as f:
        return max(r["departure"][:7] for r in csv.DictReader(f))


def month_trips(month):
    """Trips departing in YYYY-MM that have an odometer reading."""
    return [r for r in load_trips() if r["departure"][:7] == month and float(r["distance_m"]) > 0]


class Group:
    """Trips sharing origin, destination, rider type and odometer bin."""

    def __init__(self, a, b, rider, bin_):
        self.a, self.b, self.rider, self.bin = a, b, rider, bin_
        self.counts = [0.0] * len(SLICES)
        self.distances = []

    def add(self, trip):
        self.counts[slice_of(trip)] += 1
        self.distances.append(float(trip["distance_m"]))

    @property
    def key(self):
        return f"{self.a}|{self.b}|{self.rider}|{self.bin}"

    @property
    def n(self):
        return sum(self.counts)

    @property
    def metres(self):
        return median(self.distances)


def group_trips(trips):
    """key -> Group for every trip."""
    groups = {}
    for trip in trips:
        bin_ = int(float(trip["distance_m"]) // BIN_M)
        key = f"{trip['dep_id']}|{trip['ret_id']}|{trip['rider']}|{bin_}"
        g = groups.get(key)
        if g is None:
            g = groups[key] = Group(trip["dep_id"], trip["ret_id"], trip["rider"], bin_)
        g.add(trip)
    return groups


def accumulate(loads, routes, counts, draws):
    """Credit counts / draws to every undirected edge of every route.
    routes: items whose first element is the node list. loads: (u, v) -> [24 floats]."""
    share = [c / draws for c in counts]
    live = [i for i, c in enumerate(share) if c]
    for route in routes:
        nodes = route[0]
        for u, v in zip(nodes, nodes[1:]):
            edge = loads[(u, v) if u < v else (v, u)]
            for i in live:
                edge[i] += share[i]


def settings_digest():
    """Short digest of every sampler knob plus the OSM extract's size: the cache key's settings part."""
    knobs = {k: getattr(corridors, k) for k in KNOBS}
    knobs.update(BIN_M=BIN_M, MAX_DRAWS=MAX_DRAWS, MIN_DRAWS=MIN_DRAWS, osm=OSM.stat().st_size if OSM.is_file() else 0)
    return hashlib.sha1(repr(sorted(knobs.items())).encode()).hexdigest()[:12]


class RouteCache:
    """Sampled routes per group key, in sqlite, keyed also on settings and draw count."""

    def __init__(self, path):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS routes (key TEXT PRIMARY KEY, settings TEXT, draws INTEGER, routes TEXT)")

    def get(self, key, settings, draws):
        row = self.db.execute("SELECT settings, draws, routes FROM routes WHERE key = ?", (key,)).fetchone()
        if row and row[0] == settings and row[1] == draws:
            return json.loads(row[2])
        return None

    def put(self, key, settings, draws, routes):
        self.db.execute("INSERT OR REPLACE INTO routes VALUES (?, ?, ?, ?)", (key, settings, draws, json.dumps(routes)))

    def commit(self):
        self.db.commit()


def snap_stations(stations, corr):
    """station id -> street node for stations within SNAP_M of one, and the ids of those that are not."""
    snap, far = {}, []
    for sid, s in stations.items():
        node, d = corr.station_node(s["lat"], s["lon"])
        if node is None or d > SNAP_M:
            far.append(sid)
        else:
            snap[sid] = node
    return snap, far


def group_seed(key):
    return int(hashlib.sha1(key.encode()).hexdigest()[:8], 16)


def workers_for(cpus, mem_bytes):
    """Pool size: one per core, but no more than one per WORKER_GIB of physical memory."""
    return max(1, min(cpus or 1, mem_bytes // (WORKER_GIB * 2 ** 30)))


def physical_memory():
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return 2 ** 62


# Set in the parent before the pool forks; read-only in the workers.
_CORR = None


def sample_origin(jobs):
    """Worker: sample every group of one origin. jobs: [(key, a_node, b_node, rider, metres, draws)].
    Returns ([(key, [[nodes, metres], ...])], [failed keys]). Jobs are taken in destination
    order so the destination-side tables the sampler keeps are reused and stay few."""
    done, failed = [], []
    for key, a, b, rider, metres, draws in sorted(jobs, key=lambda j: j[2]):
        try:
            routes = _CORR.sample(a, b, rider, metres, draws, group_seed(key))
            done.append((key, [[nodes, round(m)] for nodes, _, m in routes]))
        except NoRoute:
            failed.append(key)
    _CORR.forget()
    return done, failed


def run(month, workers):
    global _CORR
    t0 = time.time()
    trips = month_trips(month)
    stations = load_stations()
    net = Network()
    _CORR = corr = Corridors(net, Attractors())
    snap, far = snap_stations(stations, corr)
    for sid in far:
        print(f"  station {sid} {stations[sid]['name']} is too far from a street node; its trips are not routed")
    groups = group_trips(trips)
    settings = settings_digest()
    cache = RouteCache(str(OUT / "cache" / "flows.sqlite"))

    loads = defaultdict(lambda: [0.0] * len(SLICES))
    slice_trips = [0.0] * len(SLICES)
    routed_keys, unrouted, hits = set(), [], 0
    jobs_by_origin = defaultdict(list)
    for key, g in groups.items():
        if g.a not in snap or g.b not in snap:
            unrouted.append(key)
            continue
        draws = draws_for(g.n)
        routes = cache.get(key, settings, draws)
        if routes is not None:
            hits += 1
            accumulate(loads, routes, g.counts, draws)
            routed_keys.add(key)
        else:
            jobs_by_origin[g.a].append((key, snap[g.a], snap[g.b], g.rider, g.metres, draws))
    print(f"{month}: {len(trips):,} trips in {len(groups):,} groups; {hits:,} groups cached, "
          f"{sum(map(len, jobs_by_origin.values())):,} to sample over {len(jobs_by_origin)} origins")

    if jobs_by_origin:
        order = sorted(jobs_by_origin.values(), key=len, reverse=True)
        done_origins = 0
        with multiprocessing.get_context("fork").Pool(workers) as pool:
            for done, failed in pool.imap_unordered(sample_origin, order):
                for key, routes in done:
                    g = groups[key]
                    cache.put(key, settings, draws_for(g.n), routes)
                    accumulate(loads, routes, g.counts, draws_for(g.n))
                    routed_keys.add(key)
                unrouted.extend(failed)
                cache.commit()      # every origin: an interrupted run resumes from here
                done_origins += 1
                if done_origins % 10 == 0:
                    print(f"  {done_origins}/{len(order)} origins, {time.time() - t0:,.0f} s", flush=True)

    for key in routed_keys:
        for i, c in enumerate(groups[key].counts):
            slice_trips[i] += c
    way_of = {}
    for u, lst in enumerate(net.adj):
        for v, _, wi in lst:
            way_of.setdefault((u, v) if u < v else (v, u), wi)
    segments = []
    for (u, v), counts in loads.items():
        w = net.ways[way_of[(u, v)]]
        segments.append({"ll": [net.latlon[u], net.latlon[v]], "name": w["name"], "kind": rider_way_kind(w),
                         "n": {str(i): round(c, 3) for i, c in enumerate(counts) if c}})
    used = {groups[k].a for k in routed_keys} | {groups[k].b for k in routed_keys}
    out = {"month": month, "slices": SLICES, "slice_trips": [round(x) for x in slice_trips], "settings": settings,
           "trips": len(trips), "routed": round(sum(slice_trips)), "unrouted_groups": len(unrouted),
           "stations": [{"name": stations[s]["name"], "ll": [stations[s]["lat"], stations[s]["lon"]]} for s in sorted(used)],
           "segments": segments}
    OUT.mkdir(exist_ok=True)
    path = OUT / f"flows_{month}.json"
    path.write_text(json.dumps(out), encoding="utf-8")
    print(f"{month}: {out['routed']:,} of {len(trips):,} trips routed, {len(unrouted):,} groups unrouted "
          f"({sum(groups[k].n for k in unrouted):,.0f} trips), {len(segments):,} segments, {time.time() - t0:,.0f} s -> {path}")
    return out


def main(argv):
    month = next((a for a in argv if not a.startswith("--")), None) or latest_month()
    workers = int(argv[argv.index("--workers") + 1]) if "--workers" in argv else workers_for(os.cpu_count(), physical_memory())
    run(month, workers)


if __name__ == "__main__":
    main(sys.argv[1:])
