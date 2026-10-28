"""Do Mobi rides separate into types?

Every usable trip in data/trips_clean.csv is described by how direct it was
(straight line between its stations over the odometer), how long and how
fast, how scenic its two stations are, and when it left; k-means then looks
for groups, and each group is profiled by season, rider type and e-bike use,
which are kept out of the clustering. See trip-types.md.

    uv run python trip_types.py [--k N]      -> output/trip_types.json

Default: k is chosen by silhouette over 2..8.
"""
import json
import random
import sys
import time
from collections import Counter
from math import cos, hypot, log, pi, sin, sqrt
from statistics import mean, median

from attractors import Attractors, project
from common import OUT, day_type, load_stations, load_trips

MIN_DURATION_S = 60        # under a minute with kilometres on the odometer is a telemetry glitch
MAX_SPEED_KMH = 30
MAX_DISTANCE_M = 40_000
SCENIC_NEAR_M = 300        # how far round a station counts as "the station is on the waterfront"
SEAWALL = 0.5              # scenic score at which an end counts as seawall-adjacent for the leisure points
LEISURE = 4                # explorer heuristic: this many points is a leisure trip
MIDDAY = range(11, 15)

FIT_SAMPLE = 100_000       # trips k-means is fitted on
PICK_SAMPLE = 20_000       # trips each candidate k is fitted on
SIL_SAMPLE = 4_000         # trips the silhouette is computed over
KS = range(2, 9)
RESTARTS = 3
SEED = 1

FEATURES = ["log_m", "log_s", "directness", "scenic_dep", "scenic_ret", "hour_sin", "hour_cos", "weekend"]


def straight_m(a, b):
    """Straight-line metres between two station dicts."""
    (x0, y0), (x1, y1) = project(a["lat"], a["lon"]), project(b["lat"], b["lon"])
    return hypot(x1 - x0, y1 - y0)


def station_scenic(stations, attractors):
    return {sid: attractors.scenic_near(*project(s["lat"], s["lon"]), SCENIC_NEAR_M) for sid, s in stations.items()}


def describe(trip, stations, scenic):
    """Everything the analysis knows about one trip, in plain units."""
    a, b = trip["dep_id"], trip["ret_id"]
    m, s = float(trip["distance_m"]), float(trip["duration_s"])
    rt = a == b
    st = 0.0 if rt else straight_m(stations[a], stations[b])
    dep = trip["dep"]
    return {
        "dep_id": a, "ret_id": b, "round": rt,
        "distance_m": m, "duration_s": s, "straight_m": st,
        "speed_kmh": m / s * 3.6 if s > 0 else 0.0,
        "directness": min(1.0, st / m) if m > 0 and not rt else 0.0,
        "scenic_dep": scenic.get(a, 0.0), "scenic_ret": scenic.get(b, 0.0),
        "hour": dep.hour, "weekend": day_type(dep) == "weekend", "month": trip["departure"][:7],
        "rider": trip["rider"], "ebike": trip["ebike"] == "1",
    }


def usable(d):
    """None, or why the trip's telemetry cannot be trusted."""
    if d["duration_s"] < MIN_DURATION_S:
        return "duration under 60 s"
    if d["distance_m"] <= 0:
        return "no odometer"
    if d["speed_kmh"] > MAX_SPEED_KMH:
        return "speed over 30 km/h"
    if d["distance_m"] > MAX_DISTANCE_M:
        return "odometer over 40 km"
    return None


def vector(d):
    h = 2 * pi * d["hour"] / 24
    return [log(d["distance_m"]), log(d["duration_s"]), d["directness"], d["scenic_dep"], d["scenic_ret"],
            sin(h), cos(h), 1.0 if d["weekend"] else 0.0]


def leisure_points(d):
    """mobi-transit-explorer.adnanreza.com's leisure heuristic, applied to our features."""
    p = 3 if d["round"] else 0
    if max(d["scenic_dep"], d["scenic_ret"]) >= SEAWALL:
        p += 2
    minutes = d["duration_s"] / 60
    p += 2 if minutes > 40 else 1 if minutes > 20 else 0
    p += d["weekend"]
    p += d["hour"] in MIDDAY
    if d["straight_m"] >= 300 and 1.8 < d["distance_m"] / d["straight_m"] <= 5:
        p += 1
    return p


def zscore(rows):
    n, dims = len(rows), len(rows[0])
    means = [sum(r[j] for r in rows) / n for j in range(dims)]
    sds = [sqrt(sum((r[j] - means[j]) ** 2 for r in rows) / n) for j in range(dims)]
    z = [[(r[j] - means[j]) / sds[j] if sds[j] else 0.0 for j in range(dims)] for r in rows]
    return means, sds, z


def _nearest(p, centroids):
    best, bi = None, 0
    for i, c in enumerate(centroids):
        d = 0.0
        for a, b in zip(p, c):
            d += (a - b) * (a - b)
        if best is None or d < best:
            best, bi = d, i
    return bi, best


def assign(points, centroids):
    return [_nearest(p, centroids)[0] for p in points]


def _seed(points, k, rng):
    """k-means++: each new centre is drawn with probability proportional to its squared distance from the nearest one."""
    centroids = [list(rng.choice(points))]
    d2 = [sum((a - b) ** 2 for a, b in zip(p, centroids[0])) for p in points]
    while len(centroids) < k:
        r = rng.random() * sum(d2)
        acc = 0.0
        for i, w in enumerate(d2):
            acc += w
            if acc >= r:
                break
        centroids.append(list(points[i]))
        d2 = [min(w, sum((a - b) ** 2 for a, b in zip(p, centroids[-1]))) for p, w in zip(points, d2)]
    return centroids


def _fit_once(points, k, rng, iters):
    centroids = _seed(points, k, rng)
    labels = None
    for _ in range(iters):
        new, inertia = [], 0.0
        for p in points:
            i, d = _nearest(p, centroids)
            new.append(i); inertia += d
        if new == labels:
            break
        labels = new
        sums = [[0.0] * len(points[0]) for _ in range(k)]
        counts = [0] * k
        for p, i in zip(points, labels):
            counts[i] += 1
            s = sums[i]
            for j, v in enumerate(p):
                s[j] += v
        centroids = [[v / counts[i] for v in sums[i]] if counts[i] else centroids[i] for i in range(k)]
    return centroids, labels, inertia


def kmeans(points, k, rng, iters=100, restarts=RESTARTS):
    """(centroids, labels, inertia) of the best of `restarts` k-means++ runs."""
    best = None
    for _ in range(restarts):
        fit = _fit_once(points, k, rng, iters)
        if best is None or fit[2] < best[2]:
            best = fit
    return best


def silhouette(points, labels, rng, sample):
    """Mean silhouette over a random sample of the points, distances within the sample."""
    idx = rng.sample(range(len(points)), min(sample, len(points)))
    pts = [points[i] for i in idx]
    labs = [labels[i] for i in idx]
    by = Counter(labs)
    total = 0.0
    for i, p in enumerate(pts):
        sums = Counter()
        for q, l in zip(pts, labs):
            sums[l] += sqrt(sum((a - b) ** 2 for a, b in zip(p, q)))
        own = labs[i]
        if by[own] < 2:
            continue
        a = sums[own] / (by[own] - 1)
        b = min(sums[l] / by[l] for l in by if l != own)
        total += (b - a) / max(a, b)
    return total / len(pts)


def profile(recs, labels, k, stations):
    """One dict per cluster: size, medians, shares and histograms."""
    out = []
    groups = [[] for _ in range(k)]
    for r, l in zip(recs, labels):
        groups[l].append(r)
    for g in groups:
        n = len(g)
        c = {"n": n, "share": n / len(recs) if recs else 0.0}
        if not n:
            out.append(c); continue
        c["median"] = {f: median(r[f] for r in g) for f in ("distance_m", "duration_s", "speed_kmh", "directness")}
        c["mean"] = {f: mean(r[f] for r in g) for f in ("scenic_dep", "scenic_ret", "directness")}
        for key, flag in (("round_share", "round"), ("weekend_share", "weekend"), ("ebike_share", "ebike")):
            c[key] = sum(r[flag] for r in g) / n
        c["casual_share"] = sum(r["rider"] == "casual" for r in g) / n
        pts = [leisure_points(r) for r in g]
        c["leisure_share"] = sum(p >= LEISURE for p in pts) / n
        c["leisure_points"] = mean(pts)
        hours = [0] * 24
        for r in g:
            hours[r["hour"]] += 1
        c["hours"] = hours
        c["months"] = dict(sorted(Counter(r["month"] for r in g).items()))
        for key, field in (("top_dep", "dep_id"), ("top_ret", "ret_id")):
            c[key] = [{"id": sid, "name": stations[sid]["name"], "n": cnt}
                      for sid, cnt in Counter(r[field] for r in g).most_common(5)]
        out.append(c)
    return out


def histogram2d(recs, labels, k):
    """Counts of directness (20 bins of 0.05) x speed (15 bins of 2 km/h) per cluster, for the report."""
    grid = [[[0] * 15 for _ in range(20)] for _ in range(k)]
    for r, l in zip(recs, labels):
        i = min(19, int(r["directness"] * 20))
        j = min(14, int(r["speed_kmh"] / 2))
        grid[l][i][j] += 1
    return grid


def main(argv):
    k_forced = int(argv[argv.index("--k") + 1]) if "--k" in argv else None
    t0 = time.time()
    stations = load_stations()
    attractors = Attractors()
    if not attractors.available:
        sys.exit("needs data/osm/vancouver_attractors.json (data/osm/download_attractors.sh)")
    scenic = station_scenic(stations, attractors)
    recs, dropped = [], Counter()
    for t in load_trips():
        d = describe(t, stations, scenic)
        why = usable(d)
        if why:
            dropped[why] += 1
        else:
            recs.append(d)
    print(f"{len(recs):,} usable trips, {sum(dropped.values()):,} excluded: {dict(dropped)}  ({time.time() - t0:.0f} s)")

    means, sds, z = zscore([vector(d) for d in recs])
    rng = random.Random(SEED)
    fit_idx = rng.sample(range(len(z)), min(FIT_SAMPLE, len(z)))
    pick = [z[i] for i in fit_idx[:PICK_SAMPLE]]
    selection = []
    for k in KS:
        c, labels, inertia = kmeans(pick, k, rng)
        s = silhouette(pick, labels, rng, SIL_SAMPLE)
        selection.append({"k": k, "silhouette": s, "inertia": inertia / len(pick)})
        print(f"k={k}: silhouette {s:.3f}, inertia/trip {inertia / len(pick):.3f}  ({time.time() - t0:.0f} s)")
    k = k_forced or max(selection, key=lambda s: s["silhouette"])["k"]
    centroids, _, _ = kmeans([z[i] for i in fit_idx], k, rng)
    labels = assign(z, centroids)
    # number clusters by size, biggest first
    order = sorted(range(k), key=lambda i: -labels.count(i))
    remap = {old: new for new, old in enumerate(order)}
    labels = [remap[l] for l in labels]
    centroids = [centroids[i] for i in order]
    print(f"k={k} fitted and assigned  ({time.time() - t0:.0f} s)")

    clusters = profile(recs, labels, k, stations)
    for i, c in enumerate(clusters):
        m = c["median"]
        print(f"cluster {i}: {c['n']:7,} ({c['share']:.0%})  {m['distance_m'] / 1000:.1f} km  {m['duration_s'] / 60:.0f} min  "
              f"{m['speed_kmh']:.1f} km/h  direct {m['directness']:.2f}  round {c['round_share']:.0%}  "
              f"scenic {c['mean']['scenic_dep']:.2f}/{c['mean']['scenic_ret']:.2f}  weekend {c['weekend_share']:.0%}  "
              f"casual {c['casual_share']:.0%}  ebike {c['ebike_share']:.0%}  leisure {c['leisure_share']:.0%}")
    out = {
        "trips": len(recs), "excluded": dict(dropped), "k": k, "features": FEATURES,
        "means": means, "sds": sds,
        "centroids": [[c[j] * sds[j] + means[j] for j in range(len(FEATURES))] for c in centroids],
        "selection": selection, "clusters": clusters,
        "overall": profile(recs, [0] * len(recs), 1, stations)[0],
        "hist2d": histogram2d(recs, labels, k),
        "stations": {sid: {"name": s["name"], "scenic": scenic[sid]} for sid, s in stations.items()},
    }
    OUT.mkdir(exist_ok=True)
    path = OUT / "trip_types.json"
    path.write_text(json.dumps(out), encoding="utf-8")
    print(f"wrote {path}  ({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main(sys.argv[1:])
