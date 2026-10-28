# Rider Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stochastic corridor sampler with a rule-based trip classifier and five rider cost profiles routed as cheapest paths, so a month of Mobi trips becomes a deterministic street-load map in minutes and a single day in under one.

**Architecture:** `routes.Network` keeps the per-way flags the profiles need; `profiles.py` turns the baseline edge cost into five profile costs; `corridors.py` grows bounded Dijkstra trees from a station under a profile and builds routes for each purpose (direct paths, errand out-and-backs, one-way detours, two-waypoint loops) as ranked enumerations; `trip_class.py` is the pure classifier; `flows.py` runs one origin per worker (trees, classify, group, route), accumulates in sorted origin order, and writes month or day files; `build_flow_map.py` renders either from the slice dimensions in the file. Everything stochastic (`shake`, `sample_*`, `RouteCache`, `flood_demo.py`) is removed at the end.

**Tech Stack:** Python 3.14 via `uv`, standard library only, `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-23-rider-model-design.md`

## Global Constraints

- Standard library only (`analysis/pyproject.toml` has `dependencies = []`).
- No randomness anywhere in routing or aggregation; output byte-identical for any `--workers` value.
- Routing cost scales with stations × profiles, never with trips: one tree per (origin, profile), routes by walking predecessors.
- Forked workers stay well under a gigabyte each; 15 cores, 24 GB.
- Scripts run from `analysis/`: `uv run python <script>.py`; tests `cd analysis && uv run python -m unittest discover -s tests -t .`.
- Thresholds are named constants with their evidence in a comment next to them.
- Commits end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Doc screenshots are real Playwright captures into `analysis/img/`, never placeholders.

## Review Focus

1. A station pair with no path under one profile (an island of one-way streets, a UBC station beyond the tree bound): `classify` must treat a missing length as "does not fit", not crash, and if no profile reaches the destination the trip is unrouted with reason `"no route"`. Test in Task 4 and Task 6.
2. A same-station trip from a station whose scenic score is exactly 0.5: the errand rule says "under `SEAWALL`", so 0.5 is a loop. Test in Task 4.
3. An odometer shorter than every profile's path (`r_p` below `MIN_FILL`): the nearest profile takes the whole trip and the report counts it as unfit. Test in Task 4.
4. A day with no trips in a slice (a quiet winter morning): `slice_trips` carries zeros and the page's "all" selection still renders; the legend divides by `Math.max(1e-9, …)`. Test in Task 7.
5. An origin whose longest trip exceeds `TREE_LIMIT_M`: the tree is capped, the far destinations get no length, and those trips are unrouted with a reason rather than silently dropped. Test in Task 6.

---

### Task 1: Lock columns in the cleaned trip table

**Files:**
- Modify: `analysis/prep.py:19-25` (add `lock_fields`), `analysis/prep.py:31` (header), `analysis/prep.py:55-57` (row)
- Test: `analysis/tests/test_prep.py` (create)

**Interfaces:**
- Produces: `prep.lock_fields(row: dict) -> tuple[int, int]` returning `(locks, lock_s)` from either the 2026 names (`Number of bike locks`, `Lock duration (sec.)`) or the 2025 names (`Number of stopovers`, `Stopover duration (sec.)`); `(0, 0)` when both absent or blank.
- Produces: `data/trips_clean.csv` with two new trailing columns `locks`, `lock_s` (integers).

- [ ] **Step 1: Write the failing tests**

```python
# analysis/tests/test_prep.py
import unittest
from prep import lock_fields

class LockFieldTests(unittest.TestCase):
    def test_2026_names(self):
        self.assertEqual(lock_fields({"Number of bike locks": "1", "Lock duration (sec.)": "840"}), (1, 840))

    def test_2025_names(self):
        self.assertEqual(lock_fields({"Number of stopovers": "2", "Stopover duration (sec.)": "121.6"}), (2, 122))

    def test_blank_or_missing_is_zero(self):
        self.assertEqual(lock_fields({"Number of bike locks": "", "Lock duration (sec.)": ""}), (0, 0))
        self.assertEqual(lock_fields({}), (0, 0))
```

- [ ] **Step 2: Run to verify failure**

Run: `cd analysis && uv run python -m unittest tests.test_prep -v`
Expected: FAIL, `ImportError: cannot import name 'lock_fields'`

- [ ] **Step 3: Implement `lock_fields(row)` in `prep.py`; append `"locks", "lock_s"` to the header list and `*lock_fields(r)` to `w.writerow([...])`**

Durations round to the nearest integer second, counts parse through `float` first (the exports write `1.0` in places).

- [ ] **Step 4: Run tests, rebuild the table**

Run: `cd analysis && uv run python -m unittest tests.test_prep -v && uv run python prep.py && head -2 ../data/trips_clean.csv`
Expected: 3 tests PASS; `kept 1,079,820 trips`; header ends `duration_s,locks,lock_s`.

- [ ] **Step 5: Full suite, commit**

Run: `cd analysis && uv run python -m unittest discover -s tests -t .`
Expected: all PASS.

```bash
git add analysis/prep.py analysis/tests/test_prep.py
git commit -m "prep.py: carry mid-trip locks (2025 stopovers) as locks, lock_s"
```

---

### Task 2: Way flags and rider profiles

**Files:**
- Modify: `analysis/routes.py:49-84` (`way_cost` → extract `has_lane`), `analysis/routes.py:143-146` (`Network.ways` entries)
- Modify: `analysis/tests/stub.py` (ways get `lane`, `paved`; add `node_tags`, `ele`)
- Create: `analysis/profiles.py`
- Test: `analysis/tests/test_profiles.py` (create), `analysis/tests/test_routes.py` (create)

**Interfaces:**
- Produces: `routes.has_lane(tags: dict) -> bool` true for `cycleway*` values `lane`, `track`, `share_busway` (same tag selection `way_cost` uses).
- Produces: each `Network.ways[wi]` dict gains `"lane": bool` and `"paved": bool` (`paved` is `tags.get("surface") not in UNPAVED`).
- Produces: `profiles.PROFILES = ("direct", "quiet", "flat", "few-stops", "scenic")`; knobs `QUIET_ARTERIAL = 1.5`, `FLAT_K = 15.0`, `FLAT_FREE = 0.02`, `STOP_M = 40.0`, `SCENIC_WAY = 0.35`, `PROFILE_PRIOR = {"member": {...scenic: 0.5}, "casual": {...scenic: 2.0}}` (others 1.0), `ARTERIAL = {"secondary", "secondary_link", "primary", "primary_link", "trunk", "trunk_link"}`.
- Produces: `profiles.control_nodes(net) -> set[int]` nodes whose tags have `highway` in `{"stop", "traffic_signals"}`.
- Produces: `class profiles.Profile(name, net, attractors)` with `edge_cost(u, v, metres, wi, base) -> float`, memoised per `(u, v)`; `base` is the edge's baseline perceived cost from `net.adj`.
- Produces: `profiles.build(net, attractors) -> dict[str, Profile]` for all of `PROFILES`.

- [ ] **Step 1: Write the failing tests**

```python
# analysis/tests/test_routes.py
import unittest
from routes import has_lane

class WayFlagTests(unittest.TestCase):
    def test_has_lane_reads_cycleway_tags(self):
        self.assertTrue(has_lane({"cycleway:right": "lane"}))
        self.assertTrue(has_lane({"cycleway": "track"}))
        self.assertFalse(has_lane({"cycleway": "shared_lane"}))
        self.assertFalse(has_lane({"cycleway:right:lane": "exclusive"}))   # a sub-key, as way_cost ignores it
        self.assertFalse(has_lane({}))
```

```python
# analysis/tests/test_profiles.py
import unittest
from profiles import FLAT_FREE, FLAT_K, PROFILES, QUIET_ARTERIAL, SCENIC_WAY, STOP_M, Profile, build, control_nodes
from tests.stub import StubAttractors, StubNet

class Scenic(StubAttractors):
    def scenic(self, x, y, parks=True):
        return 1.0 if x >= 100 else 0.0        # nodes 1, 2, 4 are on the water

class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.net = StubNet()
        self.net.ways[0].update(hw="primary", lane=False)
        self.net.ways[1].update(hw="primary", lane=True)
        self.net.ways[2].update(paved=False)
        self.net.ele = [0.0, 0.0, 10.0, 0.0, 0.0]            # node 2 is 10 m up: way 1 climbs 10%, way 2 descends
        self.net.node_tags[1] = {"highway": "traffic_signals"}

    def cost(self, name, u, v, wi, att=None):
        return Profile(name, self.net, att or StubAttractors()).edge_cost(u, v, 100.0, wi, 100.0)

    def test_direct_is_the_baseline(self):
        self.assertEqual(self.cost("direct", 0, 1, 0), 100.0)

    def test_quiet_raises_arterials_without_a_lane(self):
        self.assertAlmostEqual(self.cost("quiet", 0, 1, 0), 100.0 * QUIET_ARTERIAL)
        self.assertEqual(self.cost("quiet", 1, 2, 1), 100.0)               # lane: no penalty
        self.assertEqual(self.cost("quiet", 3, 0, 3), 100.0)               # residential

    def test_flat_prices_paved_grade_both_ways(self):
        up = self.cost("flat", 1, 2, 1)
        self.assertAlmostEqual(up, 100.0 * (1 + FLAT_K * (0.10 - FLAT_FREE)))
        self.assertAlmostEqual(self.cost("flat", 2, 1, 1), up)
        self.assertEqual(self.cost("flat", 2, 3, 2), 100.0)                # unpaved: baseline already priced it
        self.assertEqual(self.cost("flat", 0, 1, 0), 100.0)                # level

    def test_few_stops_adds_a_fixed_cost_entering_a_control(self):
        self.assertAlmostEqual(self.cost("few-stops", 0, 1, 0), 100.0 + STOP_M)
        self.assertEqual(self.cost("few-stops", 1, 0, 0), 100.0)

    def test_scenic_discounts_waterfront_edges(self):
        self.assertAlmostEqual(self.cost("scenic", 0, 1, 0, Scenic()), 100.0 * SCENIC_WAY)
        self.assertEqual(self.cost("scenic", 3, 0, 3, Scenic()), 100.0)

    def test_control_nodes_and_build(self):
        self.assertEqual(control_nodes(self.net), {1})
        self.assertEqual(tuple(build(self.net, StubAttractors())), PROFILES)

    def test_edge_cost_is_memoised(self):
        class Counting(Scenic):
            calls = 0
            def scenic(self, x, y, parks=True):
                self.calls += 1
                return super().scenic(x, y, parks)
        att = Counting()
        p = Profile("scenic", self.net, att)
        p.edge_cost(0, 1, 100.0, 0, 100.0); p.edge_cost(0, 1, 100.0, 0, 100.0)
        self.assertLessEqual(att.calls, 2)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd analysis && uv run python -m unittest tests.test_routes tests.test_profiles -v`
Expected: FAIL with `ImportError` on `has_lane` and `profiles`.

- [ ] **Step 3: Implement `has_lane(tags)` in `routes.py`, call it from `way_cost`, add `"lane"` and `"paved"` to the `Network.ways` dict; update `tests/stub.py` so `StubNet.ways` entries carry `lane=False, paved=True`, and `StubNet` has `node_tags = [{} for _ in XY]` and `ele = [None] * len(XY)`**

- [ ] **Step 4: Implement `profiles.py`**

`Profile.edge_cost` dispatches on `self.name`: `quiet` multiplies when `ways[wi]["hw"] in ARTERIAL and not ways[wi]["lane"]`; `flat` multiplies by `1 + FLAT_K * max(0, net.grade(u, v) - FLAT_FREE)` when `ways[wi]["paved"]` and the grade is not `None`; `few-stops` adds `STOP_M` when `v in self.controls` (computed once from `control_nodes`); `scenic` multiplies by `SCENIC_WAY` when `attractors.scenic(*net.xy[u], parks=False) or attractors.scenic(*net.xy[v], parks=False)`, with the per-node scenic value memoised as `corridors.Rider.scenic` does today.

- [ ] **Step 5: Run tests**

Run: `cd analysis && uv run python -m unittest discover -s tests -t .`
Expected: all PASS (the existing corridor tests still pass with the richer stub).

- [ ] **Step 6: Commit**

```bash
git add analysis/routes.py analysis/profiles.py analysis/tests/stub.py analysis/tests/test_routes.py analysis/tests/test_profiles.py
git commit -m "profiles.py: five rider cost profiles over the baseline street costs"
```

---

### Task 3: Bounded trees and paths

**Files:**
- Modify: `analysis/corridors.py` (add after `build_graph`)
- Test: `analysis/tests/test_trees.py` (create)

**Interfaces:**
- Consumes: `corridors.build_graph(net) -> (fwd, rev)` with adjacency `node -> [(other, metres, way, cost)]`; `Profile.edge_cost(u, v, metres, wi, base)`.
- Produces: `corridors.Tree = namedtuple("Tree", "metres cost pred")`, three dicts over reached nodes; `pred[src]` absent.
- Produces: `corridors.tree(adj, src, limit_m, edge_cost) -> Tree`: Dijkstra ordered by cost, an edge relaxed only when the physical metres through it stay within `limit_m`. `edge_cost(u, v, metres, wi, base)` is any callable with the profile signature.
- Produces: `corridors.path(tree, src, dst) -> list[int]` from `src` to `dst` by walking `pred` back from `dst`; `corridors.path_from(tree, src, dst) -> list[int]` for a tree grown on `rev` adjacency rooted at `dst`, walking `pred` forward from `src`. Both raise `NoRoute` when `dst` (resp. `src`) is not in the tree.
- Produces: `corridors.budget(metres) -> float` = `metres * (1 + SLACK)`.
- Produces: `corridors.TREE_LIMIT_M = 15_000.0`.

- [ ] **Step 1: Write the failing tests**

```python
# analysis/tests/test_trees.py
import unittest
from corridors import NoRoute, SLACK, TREE_LIMIT_M, budget, build_graph, path, path_from, tree
from tests.stub import StubNet

def base(u, v, m, wi, c):
    return c

class TreeTests(unittest.TestCase):
    def setUp(self):
        self.fwd, self.rev = build_graph(StubNet())

    def test_tree_metres_and_pred_follow_the_cheapest_path(self):
        t = tree(self.fwd, 0, 500, base)
        self.assertAlmostEqual(t.metres[2], 200)
        self.assertAlmostEqual(t.metres[4], 200)
        self.assertEqual(path(t, 0, 4), [0, 1, 4])
        self.assertNotIn(0, t.pred)

    def test_tree_stops_at_the_metre_limit(self):
        t = tree(self.fwd, 0, 150, base)
        self.assertEqual(set(t.metres), {0, 1, 3})

    def test_cost_decides_the_route_metres_report_the_distance(self):
        dear = lambda u, v, m, wi, c: c * (5.0 if wi == 0 else 1.0)
        t = tree(self.fwd, 0, 500, dear)
        self.assertEqual(path(t, 0, 2), [0, 3, 2])
        self.assertAlmostEqual(t.metres[2], 200)
        self.assertAlmostEqual(t.cost[2], 200)

    def test_reverse_tree_walks_forward_to_the_root(self):
        t = tree(self.rev, 2, 500, base)
        self.assertEqual(path_from(t, 4, 2), [4, 1, 2])

    def test_missing_node_raises(self):
        with self.assertRaises(NoRoute):
            path(tree(self.fwd, 0, 150, base), 0, 2)

    def test_budget_and_limit(self):
        self.assertAlmostEqual(budget(1000), 1000 * (1 + SLACK))
        self.assertEqual(TREE_LIMIT_M, 15_000.0)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd analysis && uv run python -m unittest tests.test_trees -v`
Expected: FAIL, `ImportError: cannot import name 'tree'`

- [ ] **Step 3: Implement `Tree`, `tree`, `path`, `path_from`, `budget`, `TREE_LIMIT_M` in `corridors.py`**

- [ ] **Step 4: Run tests, commit**

Run: `cd analysis && uv run python -m unittest discover -s tests -t .`
Expected: all PASS.

```bash
git add analysis/corridors.py analysis/tests/test_trees.py
git commit -m "corridors.py: bounded cost trees with metres and predecessors"
```

---

### Task 4: The classifier

**Files:**
- Create: `analysis/trip_class.py`
- Test: `analysis/tests/test_trip_class.py` (create)

**Interfaces:**
- Consumes: `trip_types.MIN_DURATION_S, MAX_SPEED_KMH, MAX_DISTANCE_M, SEAWALL`; `corridors.MIN_FILL, SLACK`; `profiles.PROFILES, PROFILE_PRIOR`.
- Produces: constants `CHECK_MIN = 5`, `ERRAND_MAX_MIN = 60`, `ERRAND_MAX_M = 6_000`, `LEISURE_R = 2.0`, `FIT_SD = 0.08`; purpose names `CHECK = "check"`, `ERRAND = "errand"`, `LOOP = "loop"`, `DETOUR = "detour"`, `DIRECT = "getting there"`, `PURPOSES = (DIRECT, DETOUR, LOOP, ERRAND, CHECK)`.
- Produces: `usable_reason(trip: dict) -> str | None`, same four reasons and order as `trip_types.usable`, reading `duration_s`, `distance_m` strings from a cleaned row.
- Produces: `Classified = namedtuple("Classified", "purpose weights fit")`; `weights` is `{profile: float}` summing to 1 for `DIRECT`, `{}` otherwise; `fit` is False when no profile's `r_p` lay inside `[MIN_FILL, 1 + SLACK]` (always True for other purposes).
- Produces: `profile_weights(metres: float, lengths: dict[str, float | None], rider: str) -> tuple[dict, bool]` implementing rule 5.
- Produces: `classify(trip: dict, scenic_dep: float, lengths: dict[str, float | None]) -> Classified`; raises `NoRoute` (from `corridors`) when the stations differ and every length is `None`.

- [ ] **Step 1: Write the failing tests**

```python
# analysis/tests/test_trip_class.py
import unittest
from corridors import NoRoute
from profiles import PROFILES
from trip_class import (CHECK, DETOUR, DIRECT, ERRAND, LOOP, classify, profile_weights, usable_reason)

def trip(distance_m, duration_s, dep_id="A", ret_id="B", rider="member", locks=0):
    return {"dep_id": dep_id, "ret_id": ret_id, "distance_m": str(distance_m), "duration_s": str(duration_s),
            "rider": rider, "locks": str(locks)}

ALL = {p: 1000.0 for p in PROFILES}

class UsableTests(unittest.TestCase):
    def test_reasons_in_order(self):
        self.assertEqual(usable_reason(trip(500, 30)), "duration under 60 s")
        self.assertEqual(usable_reason(trip(0, 600)), "no odometer")
        self.assertEqual(usable_reason(trip(10000, 600)), "speed over 30 km/h")
        self.assertEqual(usable_reason(trip(41000, 36000)), "odometer over 40 km")
        self.assertIsNone(usable_reason(trip(1000, 600)))

class SameStationTests(unittest.TestCase):
    def test_under_five_minutes_is_a_check(self):
        self.assertEqual(classify(trip(800, 240, "A", "A"), 0.0, {}).purpose, CHECK)

    def test_short_neighbourhood_round_trip_is_an_errand(self):
        self.assertEqual(classify(trip(2200, 1500, "A", "A"), 0.3, {}).purpose, ERRAND)

    def test_scenic_station_round_trip_is_a_loop_unless_locked(self):
        self.assertEqual(classify(trip(2200, 1500, "A", "A"), 0.5, {}).purpose, LOOP)        # exactly SEAWALL: not under
        self.assertEqual(classify(trip(2200, 1500, "A", "A", locks=1), 0.9, {}).purpose, ERRAND)

    def test_long_or_slow_round_trips_are_loops_even_when_locked(self):
        self.assertEqual(classify(trip(9500, 3600, "A", "A", locks=1), 0.9, {}).purpose, LOOP)   # over 6 km
        self.assertEqual(classify(trip(2000, 4000, "A", "A", locks=1), 0.2, {}).purpose, LOOP)   # over 60 min

class OneWayTests(unittest.TestCase):
    def test_direct_trip_takes_the_fitting_profiles(self):
        c = classify(trip(1040, 400), 0.0, ALL)
        self.assertEqual(c.purpose, DIRECT)
        self.assertTrue(c.fit)
        self.assertAlmostEqual(sum(c.weights.values()), 1.0)
        self.assertEqual(set(c.weights), set(PROFILES))               # all fit equally; prior splits them
        self.assertAlmostEqual(c.weights["scenic"], 0.5 / 4.5)         # member prior 0.5 against four 1.0s

    def test_the_odometer_picks_the_profile_whose_length_matches(self):
        lengths = dict(ALL, scenic=1120.0)                             # 1150 m ridden: 15% over direct, 2.7% over scenic
        c = classify(trip(1150, 400), 0.0, lengths)
        self.assertGreater(c.weights["scenic"], 0.9)
        self.assertNotIn("direct", c.weights)                          # r = 1.15 is outside 1 + SLACK

    def test_casual_prior_doubles_scenic(self):
        c = classify(trip(1000, 400, rider="casual"), 0.0, ALL)
        self.assertAlmostEqual(c.weights["scenic"], 2.0 / 6.0)

    def test_nothing_fits_falls_back_to_the_nearest_profile_unfit(self):
        c = classify(trip(1500, 500), 0.0, dict(ALL, scenic=1250.0))   # 1.5x direct, 1.2x scenic: nearest is scenic
        self.assertEqual(c.purpose, DIRECT)
        self.assertEqual(c.weights, {"scenic": 1.0})
        self.assertFalse(c.fit)
        short = classify(trip(800, 300), 0.0, ALL)                     # odometer under every path
        self.assertFalse(short.fit)
        self.assertAlmostEqual(sum(short.weights.values()), 1.0)

    def test_twice_the_shortest_is_a_detour(self):
        self.assertEqual(classify(trip(2100, 900), 0.0, ALL).purpose, DETOUR)
        self.assertEqual(classify(trip(2100, 900), 0.0, dict(ALL, scenic=1100.0)).purpose, DIRECT)   # scenic explains it

    def test_unreachable_profiles_are_skipped_and_all_unreachable_raises(self):
        c = classify(trip(1000, 400), 0.0, dict(ALL, flat=None))
        self.assertNotIn("flat", c.weights)
        with self.assertRaises(NoRoute):
            classify(trip(1000, 400), 0.0, {p: None for p in PROFILES})

    def test_profile_weights_are_normalised(self):
        w, fit = profile_weights(1000.0, ALL, "member")
        self.assertAlmostEqual(sum(w.values()), 1.0)
        self.assertTrue(fit)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd analysis && uv run python -m unittest tests.test_trip_class -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'trip_class'`

- [ ] **Step 3: Implement `trip_class.py`**

`profile_weights`: for each profile with a length, `r = metres / length`; score `PROFILE_PRIOR[rider][p] * exp(-((r - 1) / FIT_SD) ** 2 / 2)`; keep profiles with `MIN_FILL <= r <= 1 + SLACK`; if none, the single profile with the smallest `abs(r - 1)` gets weight 1 and `fit` is False (ties go to the earliest in `PROFILES`); else normalise. `classify`: same-station rules 1 to 3 in the spec's order (minutes from `duration_s`, locks from `int(float(trip.get("locks") or 0))`), then rule 4 (`min(r_p) > LEISURE_R` → `DETOUR`) and rule 5. Every threshold carries its evidence comment (the lock-rate table in the spec).

- [ ] **Step 4: Run tests, commit**

Run: `cd analysis && uv run python -m unittest discover -s tests -t .`
Expected: all PASS.

```bash
git add analysis/trip_class.py analysis/tests/test_trip_class.py
git commit -m "trip_class.py: rule-based trip purpose and rider profile weights"
```

---

### Task 5: Route constructions

**Files:**
- Modify: `analysis/corridors.py` (add constructions; `pleasant` loses its `kind` argument)
- Test: `analysis/tests/test_constructions.py` (create)

**Interfaces:**
- Consumes: `Tree`, `tree`, `path`, `path_from`, `budget`, `waypoint_candidates(net, nodes, score) -> (cands, weights)`, `gauss(x, sd)`, `Bounded`, `NoRoute`, `MIN_FILL`, `SLACK`, `REUSE_PENALTY`, `WAYPOINT_SD`, `TURN_CELL`; `Profile.edge_cost`.
- Produces: `PLEASANT_K = 0.05`; `pleasant(c, m) -> float` = `exp(-(c / m - 1) / PLEASANT_K)`.
- Produces: knobs `DETOUR_N = 12`, `LOOP_N1 = 6`, `LOOP_N2 = 4`, `ERRAND_N = 12`, `ERRAND_SD = 0.1`, `ERRAND_FLOOR = 0.15`, `WINDOW_SD = 3.0` (kept).
- Produces: `top(cands, weights, n) -> list[(node, weight)]`: the `n` largest weights, ties broken by node id, weights renormalised to sum 1; empty list if nothing scores.
- Produces: `direct_routes(trees: dict[str, Tree], a, b, weights: dict[str, float]) -> list[(nodes, weight)]`, one entry per profile with non-zero weight, in `PROFILES` order.
- Produces: `errand_routes(net, attractors, out: Tree, a, metres) -> list[(nodes, weight)]`: candidates `t != a` with `abs(out.metres[t] - metres/2) <= WINDOW_SD * ERRAND_SD * metres`, score `gauss(out.metres[t] - metres/2, ERRAND_SD * metres) * (ERRAND_FLOOR + attractors.commercial(*net.xy[t]))`, one per `TURN_CELL` cell via `waypoint_candidates`, top `ERRAND_N`; route `path(out, a, t) + path(out, a, t)[-2::-1]`.
- Produces: `detour_routes(net, out: Tree, into: Tree, a, b, metres) -> list[(nodes, weight)]`: `into` is grown on `rev` adjacency rooted at `b` under the scenic profile; candidates `t not in (a, b)` with `MIN_FILL * metres <= out.metres[t] + into.metres[t] <= budget(metres)`, score `gauss(out.metres[t] + into.metres[t] - metres, WAYPOINT_SD * metres) * pleasant(out.cost[t], out.metres[t]) * pleasant(into.cost[t], into.metres[t])`, top `DETOUR_N`; route `path(out, a, t) + path_from(into, t, b)[1:]`.
- Produces: `loop_routes(net, fwd, rev, a, metres, edge_cost) -> list[(nodes, weight)]`: `out = tree(fwd, a, budget, edge_cost)`, `into = tree(rev, a, budget, edge_cost)`; first waypoints with `abs(out.metres[t] - metres/3) <= WINDOW_SD * sd` (`sd = WAYPOINT_SD * metres`), score `gauss(out.metres[t] - metres/3, sd) * pleasant(out.cost[t], out.metres[t])`, top `LOOP_N1`; for each `t1`, `m1 = tree(fwd, t1, budget - out.metres[t1], penalised)` where `penalised` multiplies `edge_cost` by `REUSE_PENALTY` on undirected edges of leg 1; second waypoints `t2 not in (a, t1)` with both `abs(m1.metres[t2] - metres/3)` and `abs(into.metres[t2] - metres/3)` within the window, score `gauss(m1.metres[t2] - metres/3, sd) * gauss(into.metres[t2] - metres/3, sd) * pleasant(m1.cost[t2], m1.metres[t2])`, top `LOOP_N2`; leg 3 is `path` on `tree(fwd, t2, budget - out.metres[t1] - m1.metres[t2], penalised2)` penalising legs 1 and 2; a loop whose total metres fall outside `[MIN_FILL * metres, budget(metres)]` is dropped; weights are the product of the two waypoint weights, renormalised. Raises `NoRoute` when nothing survives.

- [ ] **Step 1: Write the failing tests**

```python
# analysis/tests/test_constructions.py
import unittest
from corridors import (NoRoute, build_graph, detour_routes, direct_routes, errand_routes, loop_routes, pleasant, top, tree)
from tests.stub import StubAttractors, StubNet

def base(u, v, m, wi, c):
    return c

class Shops(StubAttractors):
    def commercial(self, x, y):
        return 1.0 if x >= 200 else 0.0          # node 4, the end of the spur, is the shopping street

class ConstructionTests(unittest.TestCase):
    def setUp(self):
        self.net = StubNet()
        self.fwd, self.rev = build_graph(self.net)

    def test_top_ranks_renormalises_and_breaks_ties_by_node(self):
        self.assertEqual(top([3, 1, 2], [0.5, 0.5, 0.25], 2), [(1, 0.5), (3, 0.5)])
        self.assertEqual(top([], [], 3), [])

    def test_pleasant_rewards_cheap_metres(self):
        self.assertAlmostEqual(pleasant(100.0, 100.0), 1.0)
        self.assertGreater(pleasant(50.0, 100.0), 1.0)

    def test_direct_routes_one_path_per_weighted_profile(self):
        trees = {"direct": tree(self.fwd, 0, 500, base), "scenic": tree(self.fwd, 0, 500, lambda u, v, m, wi, c: c * (5.0 if wi == 0 else 1.0))}
        routes = direct_routes(trees, 0, 2, {"direct": 0.75, "scenic": 0.25})
        self.assertEqual(routes, [([0, 1, 2], 0.75), ([0, 3, 2], 0.25)])

    def test_errand_goes_to_the_shops_and_back_the_same_way(self):
        out = tree(self.fwd, 0, 500, base)
        routes = errand_routes(self.net, Shops(), out, 0, 400)          # half of 400 m: node 2 or node 4, both 200 m out
        self.assertEqual(routes[0][0], [0, 1, 4, 1, 0])
        self.assertGreater(routes[0][1], routes[-1][1])                  # the shop outranks the residential corner
        self.assertAlmostEqual(sum(w for _, w in routes), 1.0)

    def test_detour_fills_the_odometer_through_the_spur(self):
        out, into = tree(self.fwd, 0, 420, base), tree(self.rev, 2, 420, base)
        routes = detour_routes(self.net, out, into, 0, 2, 400)
        self.assertEqual(routes, [([0, 1, 4, 1, 2], 1.0)])

    def test_loop_round_the_square(self):
        routes = loop_routes(self.net, self.fwd, self.rev, 0, 400, base)
        nodes, w = routes[0]
        self.assertEqual((nodes[0], nodes[-1]), (0, 0))
        self.assertEqual(sorted(nodes[1:-1]), [1, 2, 3])                 # a lap, not an out-and-back
        self.assertAlmostEqual(sum(w for _, w in routes), 1.0)

    def test_loop_too_short_for_any_waypoint_raises(self):
        with self.assertRaises(NoRoute):
            loop_routes(self.net, self.fwd, self.rev, 0, 50, base)

    def test_constructions_are_deterministic(self):
        self.assertEqual(loop_routes(self.net, self.fwd, self.rev, 0, 400, base),
                         loop_routes(self.net, self.fwd, self.rev, 0, 400, base))
```

- [ ] **Step 2: Run to verify failure**

Run: `cd analysis && uv run python -m unittest tests.test_constructions -v`
Expected: FAIL, `ImportError` on `detour_routes`.

- [ ] **Step 3: Implement the constructions in `corridors.py`; change `pleasant(kind)` to `pleasant(c, m)` and `PLEASANT_K` to the scalar `0.05`, updating `sample_loop` and `sample_detour` call sites minimally (they are deleted in Task 8)**

Candidate pools iterate `sorted(tree.metres)` so cell winners and ties are order-independent.

- [ ] **Step 4: Run tests, commit**

Run: `cd analysis && uv run python -m unittest discover -s tests -t .`
Expected: all PASS.

```bash
git add analysis/corridors.py analysis/tests/test_constructions.py
git commit -m "corridors.py: deterministic direct, errand, detour and loop routes"
```

---

### Task 6: flows.py on the rider model

**Files:**
- Rewrite: `analysis/flows.py`
- Modify: `analysis/corridors.py:334-376` (`Corridors` → `Router`: graph, profiles, snapping, bounded tree memos)
- Modify: `analysis/common.py` (add `DAY_PARTS`)
- Test: `analysis/tests/test_flows.py` (rewrite), `analysis/tests/test_router.py` (create)

**Interfaces:**
- Consumes: `profiles.build`, `trip_class.classify/usable_reason/PURPOSES/DIRECT/...`, the Task 5 constructions, `trip_types.station_scenic`.
- Produces: `common.DAY_PARTS = [("morning", range(7, 10)), ("evening", range(16, 19)), ("other", <the other 18 hours>)]`, `common.DAY_PART_OF_HOUR`.
- Produces: `corridors.Router(net, attractors)` with `.net, .fwd, .rev, .profiles (dict), .station_node(lat, lon) -> (node, metres)`, `.forward(node, profile, limit_m) -> Tree` and `.reverse(node, profile, limit_m) -> Tree`, each memoised in a `Bounded(Router.MEMO)` (`._fwd`, `._rev`; `MEMO = 16`) keyed on `(node, profile, limit rounded up to 500 m)`, and `.forget()`.
- Produces in `flows.py`:
  - `SLICES` (24, unchanged names) and `DIMS = [("day", DAYS), ("block", BLOCK_NAMES), ("rider", RIDERS)]`; `DAY_SLICES = [f"{part}|{rider}" ...]` (6) and `DAY_DIMS = [("hours", [p for p, _ in DAY_PARTS]), ("rider", RIDERS)]`.
  - `period_of(arg: str) -> ("month" | "day", str)`; `slice_of(trip, kind) -> int`; `trips_for(kind, period) -> list` (a day is `departure[:10] == period`).
  - `class Group(a, b, rider, purpose, bin_)` with `.counts` (list per slice), `.weights` (list per slice of `{profile: w}` sums, used by `DIRECT`), `.distances`, `.metres` (median), `.n`, `.key`.
  - `group_key(trip, purpose) -> str`: `f"{a}|{b}|{rider}|{purpose}"` for `DIRECT`, plus `|{bin}` otherwise.
  - `route_origin(a: str) -> OriginResult` where `OriginResult = namedtuple("OriginResult", "origin routes purposes unrouted band")`; `routes` is `[(nodes, [weight per slice])]`, `purposes` and `unrouted` are `Counter`, `band` is `{"trips": n, "unfit": n, "weight": {profile: w}}` over `DIRECT` trips whose `r_direct` lies in `[1.1, 2.0]`. Reads module globals `_ROUTER, _SNAP, _SCENIC, _TRIPS, _KIND` set before the pool forks.
  - `accumulate(loads, routes)`: credits each route's per-slice weights to its undirected edges.
  - `merge(results: list[OriginResult]) -> (loads, purposes, unrouted, band)`: sorts by origin, then accumulates; the only path by which results reach the output.
  - `flows.py` imports `TREE_LIMIT_M` into its own namespace (`from corridors import TREE_LIMIT_M, budget, ...`) so a test can patch `flows.TREE_LIMIT_M`.
  - `settings_digest() -> str` over `profiles` and `trip_class` constants plus `corridors` construction knobs and the OSM file size.
  - `run(kind, period, workers, report=False) -> dict` writing `output/flows_<period>.json` with keys `period, kind, title, slices, dims, slice_trips, settings, trips, routed, purposes, unrouted, stations, segments` (segment shape unchanged); results accumulated in sorted-origin order after the pool finishes.
  - `main(argv)`: `flows.py [YYYY-MM | YYYY-MM-DD] [--workers N] [--report]`.

- [ ] **Step 1: Write the failing tests**

```python
# analysis/tests/test_router.py
import unittest
from corridors import Router
from profiles import PROFILES
from tests.stub import StubAttractors, StubNet

class RouterTests(unittest.TestCase):
    def test_router_builds_profiles_and_trees(self):
        r = Router(StubNet(), StubAttractors())
        self.assertEqual(tuple(r.profiles), PROFILES)
        self.assertAlmostEqual(r.forward(0, "direct", 500).metres[2], 200)
        self.assertAlmostEqual(r.reverse(2, "scenic", 500).metres[0], 200)

    def test_tree_memo_is_bounded_and_keyed_on_the_rounded_limit(self):
        r = Router(StubNet(), StubAttractors())
        self.assertIs(r.forward(0, "direct", 410), r.forward(0, "direct", 480))
        for n in range(Router.MEMO + 3):
            r.forward(n % 5, "direct", 500 + 500 * n)
        self.assertLessEqual(len(r._fwd), Router.MEMO)
```

```python
# analysis/tests/test_flows.py
import unittest
from collections import Counter, defaultdict
from datetime import datetime
from unittest.mock import patch

import flows
from corridors import Router
from flows import (DAY_DIMS, DAY_SLICES, DIMS, SLICES, Group, OriginResult, accumulate, group_key, period_of,
                   route_origin, slice_of)
from tests.stub import StubAttractors, StubNet
from trip_class import CHECK, DETOUR, DIRECT, ERRAND, LOOP

def t(dep_id, ret_id, rider, distance_m, dep, duration_s=600, locks=0):
    return {"dep_id": dep_id, "ret_id": ret_id, "rider": rider, "distance_m": str(distance_m), "dep": dep,
            "departure": dep.isoformat(sep=" "), "duration_s": str(duration_s), "locks": str(locks)}

class SliceTests(unittest.TestCase):
    def test_month_slices_unchanged(self):
        self.assertEqual(len(SLICES), 24)
        self.assertEqual(SLICES[0], "weekday|07:00-10:00|member")
        self.assertEqual([d for d, _ in DIMS], ["day", "block", "rider"])

    def test_day_slices(self):
        self.assertEqual(DAY_SLICES, ["morning|member", "morning|casual", "evening|member", "evening|casual",
                                      "other|member", "other|casual"])
        self.assertEqual(DAY_DIMS[0], ("hours", ["morning", "evening", "other"]))
        trip = {"dep": datetime(2026, 7, 6, 8), "rider": "casual"}
        self.assertEqual(DAY_SLICES[slice_of(trip, "day")], "morning|casual")
        self.assertEqual(SLICES[slice_of(trip, "month")], "weekday|07:00-10:00|casual")

    def test_period_of(self):
        self.assertEqual(period_of("2026-07"), ("month", "2026-07"))
        self.assertEqual(period_of("2026-07-06"), ("day", "2026-07-06"))

class GroupTests(unittest.TestCase):
    def test_direct_groups_ignore_the_odometer_bin(self):
        a = t("A", "B", "member", 900, datetime(2026, 7, 6, 8))
        b = t("A", "B", "member", 1400, datetime(2026, 7, 6, 8))
        self.assertEqual(group_key(a, DIRECT), group_key(b, DIRECT))
        self.assertNotEqual(group_key(a, LOOP), group_key(b, LOOP))
        self.assertEqual(group_key(a, LOOP), "A|B|member|loop|3")

    def test_group_sums_profile_weights_per_slice(self):
        g = Group("A", "B", "member", DIRECT, None)
        g.add(t("A", "B", "member", 900, datetime(2026, 7, 6, 8)), "month", {"direct": 0.5, "scenic": 0.5})
        g.add(t("A", "B", "member", 950, datetime(2026, 7, 6, 8)), "month", {"direct": 1.0})
        i = SLICES.index("weekday|07:00-10:00|member")
        self.assertEqual(g.counts[i], 2)
        self.assertAlmostEqual(g.weights[i]["direct"], 1.5)
        self.assertEqual(g.metres, 925)

class AccumulateTests(unittest.TestCase):
    def test_accumulate_credits_slice_weights_to_undirected_edges(self):
        loads = defaultdict(lambda: [0.0] * 24)
        w = [0.0] * 24; w[0] = 0.5
        accumulate(loads, [([0, 1, 2], w), ([2, 3, 0], w)])
        self.assertAlmostEqual(loads[(0, 1)][0], 0.5)
        self.assertAlmostEqual(loads[(0, 3)][0], 0.5)
        self.assertNotIn((3, 0), loads)

class OriginTests(unittest.TestCase):
    def setUp(self):
        net = StubNet()
        flows._ROUTER = Router(net, StubAttractors())
        flows._SNAP = {"A": 0, "B": 2, "C": 4}
        flows._SCENIC = {"A": 0.0, "B": 0.0, "C": 0.0}
        flows._KIND = "month"
        mon8 = datetime(2026, 7, 6, 8)
        flows._TRIPS = {"A": [
            t("A", "B", "member", 200, mon8),                       # direct, fits every profile
            t("A", "B", "member", 450, mon8),                       # 2.25x the shortest: detour via the spur
            t("A", "A", "member", 400, mon8, duration_s=1500),      # errand: 25 min, 400 m
            t("A", "A", "casual", 400, mon8, duration_s=4000),      # loop: over an hour
            t("A", "A", "member", 300, mon8, duration_s=120),       # check
            t("A", "B", "member", 200, mon8, duration_s=30),        # unusable
            t("A", "Z", "member", 200, mon8),                       # station off the network
        ]}

    def test_route_origin_classifies_routes_and_counts(self):
        r = route_origin("A")
        self.assertIsInstance(r, OriginResult)
        self.assertEqual(r.purposes, Counter({DIRECT: 1, DETOUR: 1, ERRAND: 1, LOOP: 1, CHECK: 1}))
        self.assertEqual(r.unrouted, Counter({"duration under 60 s": 1, "station off network": 1}))
        self.assertGreater(sum(sum(w) for _, w in r.routes), 0)
        for nodes, w in r.routes:
            self.assertEqual(nodes[0], 0)
            self.assertEqual(len(w), len(SLICES))

    def test_route_origin_reports_the_detour_band(self):
        flows._TRIPS = {"A": [t("A", "B", "member", 230, datetime(2026, 7, 6, 8))]}     # 1.15x: in the band, unfit
        r = route_origin("A")
        self.assertEqual(r.band["trips"], 1)
        self.assertEqual(r.band["unfit"], 1)
        self.assertAlmostEqual(sum(r.band["weight"].values()), 1.0)

    def test_destination_beyond_the_tree_limit_is_unrouted_with_a_reason(self):
        with patch("flows.TREE_LIMIT_M", 150.0):
            r = route_origin("A")
        self.assertIn("beyond tree limit", r.unrouted)

class DeterminismTests(unittest.TestCase):
    def test_results_accumulate_in_origin_order_whatever_the_arrival_order(self):
        w = [1.0] + [0.0] * 23
        a = OriginResult("A", [([0, 1], w)], Counter(), Counter(), {})
        b = OriginResult("B", [([1, 2], w)], Counter(), Counter(), {})
        self.assertEqual(flows.merge([a, b]), flows.merge([b, a]))
```

- [ ] **Step 2: Run to verify failure**

Run: `cd analysis && uv run python -m unittest tests.test_router tests.test_flows -v`
Expected: FAIL with `ImportError` on `Router`, `DAY_SLICES`, `route_origin`.

- [ ] **Step 3: Add `DAY_PARTS` and `DAY_PART_OF_HOUR` to `common.py`; replace `Corridors` with `Router` in `corridors.py` (keep `station_node` and the snappable grid; `MEMO = 16`)**

- [ ] **Step 4: Rewrite `flows.py`**

`route_origin(a)`: `limit = min(TREE_LIMIT_M, budget(max odometer of a's trips))`; `trees = {p: _ROUTER.forward(_SNAP[a], p, limit) for p in PROFILES}`; per trip: `usable_reason` → unrouted; destination not in `_SNAP` → `"station off network"`; `lengths = {p: trees[p].metres.get(_SNAP[b])}`; `classify` (a `NoRoute` from it → `"beyond tree limit"` when the trip's budget exceeds `limit`, else `"no route"`); `CHECK` counted, not grouped; `Group.add(trip, _KIND, weights)`. Then per group in sorted key order: `DIRECT` → `direct_routes` with the group's per-slice weights normalised per slice (weight vector per route = `[weights[i][p] for i]`); `ERRAND` → `errand_routes(net, attractors, trees["direct"], ...)`; `DETOUR` → `detour_routes(net, trees["scenic"], _ROUTER.reverse(_SNAP[b], "scenic", budget(g.metres)), ...)`; `LOOP` → `loop_routes(net, _ROUTER.fwd, _ROUTER.rev, _SNAP[a], g.metres, _ROUTER.profiles["scenic"].edge_cost)`; each route's slice vector is `[g.counts[i] * w for i]`; a `NoRoute` adds `g.n` to `unrouted["no route"]`. Call `_ROUTER.forget()` before returning. `run` builds `_TRIPS` by origin, forks a pool over `sorted(_TRIPS)`, collects every `OriginResult`, then `merge` and write. `--report` prints the band table: trips, unfit share, weight share per profile.

- [ ] **Step 5: Run tests**

Run: `cd analysis && uv run python -m unittest discover -s tests -t .`
Expected: all PASS, including the untouched `test_corridors.py` (its sampler imports still exist until Task 8).

- [ ] **Step 6: Commit**

```bash
git add analysis/flows.py analysis/corridors.py analysis/common.py analysis/tests/test_flows.py analysis/tests/test_router.py
git commit -m "flows.py: classify, route and aggregate a month or a day deterministically"
```

---

### Task 7: The map page reads its switches from the file

**Files:**
- Modify: `analysis/build_flow_map.py:17-35` (`month_name` → `title_for`, `render`, `main`), `analysis/build_flow_map.py:70-75, 96-111` (page JS: generic `dims`)
- Test: `analysis/tests/test_build_flow_map.py` (modify)

**Interfaces:**
- Consumes: the Task 6 file shape (`period, kind, title, slices, dims, slice_trips, …`).
- Produces: `build_flow_map.title_for(kind, period) -> str`: `"Mobi flows, July 2026"` for a month, `"Mobi flows, Monday 6 July 2026"` for a day.
- Produces: `render(data) -> str` building one fieldset per entry of `data["dims"]` (an `all` radio plus one per value, labels as in the current page: `members`, `casual`, `weekdays`, `weekends`, block names and day parts verbatim) and selecting slices by splitting on `|`.
- Produces: `main(argv)`: `build_flow_map.py [period]`; default is the latest month file (`flows_YYYY-MM.json`), never a day file; writes `output/flow_map.html` for a month and `output/flow_map_<period>.html` for a day.

- [ ] **Step 1: Write the failing tests**

Replace `data()` in `tests/test_build_flow_map.py` so it builds the new shape (`period="2026-07", kind="month", title=title_for("month", "2026-07"), dims=DIMS, slices=SLICES, slice_trips=[1]*24, purposes={"getting there": 10}, unrouted={}`), keep the three existing tests, and add:

```python
    def test_title_for(self):
        self.assertEqual(title_for("month", "2026-07"), "Mobi flows, July 2026")
        self.assertEqual(title_for("day", "2026-07-06"), "Mobi flows, Monday 6 July 2026")

    def test_day_file_renders_day_controls_and_survives_empty_slices(self):
        html = render(data(period="2026-07-06", kind="day", title=title_for("day", "2026-07-06"),
                           dims=DAY_DIMS, slices=DAY_SLICES, slice_trips=[0] * 6, segments=[]))
        for word in ("morning", "evening", "other", "Monday 6 July 2026"):
            self.assertIn(word, html)
        self.assertNotIn("weekday", html)
        self.assertIn("Math.max(1e-9", html)

    def test_default_period_skips_day_files(self):
        self.assertEqual(latest_period(["flows_2026-07-06.json", "flows_2026-06.json", "flows_2026-07.json"]), "2026-07")
```

(`latest_period(names: list[str]) -> str` is the pure helper `main` uses; add it to Produces.)

- [ ] **Step 2: Run to verify failure**

Run: `cd analysis && uv run python -m unittest tests.test_build_flow_map -v`
Expected: FAIL, `ImportError` on `title_for`.

- [ ] **Step 3: Implement**

The JS keeps `sel` as `{dim: "all"}` per dim name and `chosen()` compares `parts[i][k]` against `sel[dims[k].name]`; `__BLOCKS__` goes, the fieldsets are generated in Python from `dims`.

- [ ] **Step 4: Run tests, commit**

Run: `cd analysis && uv run python -m unittest discover -s tests -t .`
Expected: all PASS.

```bash
git add analysis/build_flow_map.py analysis/tests/test_build_flow_map.py
git commit -m "build_flow_map.py: switches from the file's slice dimensions; month or day"
```

---

### Task 8: Remove shaking

**Files:**
- Modify: `analysis/corridors.py` (delete `SIGMA, HOP_TRIES, HOME_CUT, RIDER_NUDGE, COMMERCIAL_BONUS, shake, legs, plain_route, sample_hop, sample_loop, sample_detour, leisure_share, Rider, metres_table, cost_table, corridor, corridor_adj, corridor_ways, shortest`; rewrite the module docstring)
- Delete: `analysis/flood_demo.py`
- Modify: `analysis/tests/test_corridors.py` (keep only `Bounded` test; move it to `test_trees.py` and delete the file)
- Modify: `analysis/flood-routing.md:1-7` (superseded note), `analysis/README.md` (layout, build, the flows paragraph), `analysis/street-costs.md:78-90` (slope, stops and traffic now priced by profiles)
- Modify: `.gitignore` (nothing; `analysis/output` already covers the removed cache)

- [ ] **Step 1: Delete the listed symbols and `flood_demo.py`; make `tests/test_corridors.py` go away**

Run: `cd analysis && rg -n "shake|sample_hop|sample_loop|sample_detour|leisure_share|RouteCache|flood_demo|SIGMA|draws_for" --glob '!output' --glob '!*.md' .`
Expected: no matches.

- [ ] **Step 2: Run the suite**

Run: `cd analysis && uv run python -m unittest discover -s tests -t .`
Expected: all PASS.

- [ ] **Step 3: Docs**

`flood-routing.md` gets, above its title, a one-paragraph note: superseded on 2026-10-23 by the rider model (link to the spec and to `rider-model.md`); kept as the record of the corridor sampler. `README.md`: `corridors.py` line reads "trees and route constructions for the rider model", `flood_demo.py` line removed, `profiles.py` and `trip_class.py` added, the `flows.py` paragraph rewritten (month or day argument, no cache, deterministic, workers), build section updated (`flows.py` "a few minutes"; `flows.py 2026-07-06` example). `street-costs.md` "What the factors do not capture": slope on paved ways, stops and signals, and arterial traffic now enter through `profiles.py`; note which bullets this retires.

- [ ] **Step 4: Commit**

```bash
git add -A analysis docs
git commit -m "Remove map shaking: sampler, demo, route cache and their knobs"
```

---

### Task 9: Run it, check it, write it up

**Files:**
- Create: `analysis/rider-model.md`, `analysis/img/rider-model-{month,day,errand}.png`
- Modify: `docs/superpowers/specs/2026-10-23-rider-model-design.md` (fill the open question's answer line if the report settles it)

- [ ] **Step 1: Month run with the report, timed**

Run: `cd analysis && time uv run python flows.py 2026-07 --report`
Expected: completes in under 10 minutes; prints trips per purpose summing with `unrouted` to the month's trip count; the band table shows trips, unfit share and weight per profile. Record every figure.

- [ ] **Step 2: Determinism**

Run: `cd analysis && uv run python flows.py 2026-07 --workers 2 && shasum -a 256 output/flows_2026-07.json && cp output/flows_2026-07.json /tmp/a.json && uv run python flows.py 2026-07 --workers 7 && shasum -a 256 output/flows_2026-07.json`
Expected: identical digests.

- [ ] **Step 3: A day**

Run: `cd analysis && time uv run python flows.py 2026-07-06 && uv run python build_flow_map.py 2026-07-06 && uv run python build_flow_map.py`
Expected: the day run under a minute; `output/flow_map_2026-07-06.html` and `output/flow_map.html` written.

- [ ] **Step 4: Known shapes**

Run from `analysis/`, in a scratch script using `Router`, `loop_routes`, `direct_routes`, `errand_routes`, `routes.names_at`, with station ids `0209` (Stanley Park Information Booth), `0300` → `0122` (Bute & Barclay → Haro & Denman), and the neighbourhood station nearest 8th & Ontario (find it in `data/stations_canonical.csv`):
- loop from `0209`, 9,570 m, casual: the top route's street names include the seawall (`names_at` contains "Seawall" or "Stanley Park Drive" and no downtown street).
- `0300` → `0122`, 930 m, member: `classify` gives `DIRECT`, the direct profile path has no waypoint, length within 5% of 930 m.
- errand from the 8th & Ontario station, 2,000 m: the top three destinations lie within 150 m of Main Street or Broadway (check with `names_at` on the destination node).
Record pass or fail for each; a failure is reported in the write-up and fixed only if it is a code defect rather than a knob.

- [ ] **Step 5: Screenshots**

Serve the repo (`python3 -m http.server 8765` from the repo root) and capture with the Playwright tools at 1280×900: `output/flow_map.html` all riders all hours (`img/rider-model-month.png`), `output/flow_map_2026-07-06.html` morning (`img/rider-model-day.png`), and the month map zoomed to Main & Broadway with members selected (`img/rider-model-errand.png`). Stop the server.

- [ ] **Step 6: Write `analysis/rider-model.md`**

Sections: what changed and why (two paragraphs, linking the spec); the classifier rules as a table with the July 2026 counts per purpose; the profiles table with the band report (weight share per profile, unfit share, and what that says about the 1.1x to 2.0x question); the three known-shape results; timings (month, day, workers used); the three screenshots; limitations (lateral ambiguity decided by the cost model; loops are two waypoints; stations not classified, with the open question's status).

- [ ] **Step 7: Full suite, commit**

Run: `cd analysis && uv run python -m unittest discover -s tests -t .`
Expected: all PASS.

```bash
git add analysis/rider-model.md analysis/img/rider-model-month.png analysis/img/rider-model-day.png analysis/img/rider-model-errand.png docs/superpowers/specs/2026-10-23-rider-model-design.md
git commit -m "rider-model.md: July 2026 on the rider model, with checks and timings"
```
