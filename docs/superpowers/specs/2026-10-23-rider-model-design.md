# Rider model: purposes and profiles instead of map shaking

## Intent

Replace the stochastic corridor sampler (`corridors.py`, described in
`flood-routing.md`) with a deterministic model of why a trip was taken and
what kind of rider took it. Every trip is classified by rule into a purpose
(getting there, out for a ride, errand) and spread across a small set of
rider profiles, each of which is a perceived-cost table over the street graph.
Routes are cheapest paths under those tables; the flow map is the weighted sum
of those paths. Nothing is drawn at random.

Two reasons. First, fidelity: shaking perturbs the map, not the rider, and the
variety it produces does not correspond to anything riders do. Riders differ
in whether they avoid hills, traffic and stop signs, and whether they will go
out of their way for the seawall; those are preferences, and preferences are
cost tables. Second, speed: shaking draws up to 30 routes per trip group with
repeated Dijkstra runs and rejection, so a month takes about half an hour on
all cores. Cheapest paths from one origin reach every destination in a single
Dijkstra run, so routing cost depends on the number of stations and profiles,
not the number of trips, so a month routes in minutes and a single day in
well under one.

Companion documents: `analysis/trip-types.md` (the clustering the purposes
rest on), `analysis/street-costs.md` (the cost factors the profiles extend),
`analysis/flood-routing.md` (the sampler this supersedes).

## What we found

The evidence, from the year August 2025 to July 2026 (1,042,291 trips with
usable telemetry; a trip is usable when it lasts 60 s or more, has an
odometer reading under 40 km and averages under 30 km/h).

**Trips split into two kinds along one axis.** k-means on directness, length,
speed, station scenery and hour finds two clusters and nothing better beyond
them: *getting there* (70%: median 1.6 km, 8 min, directness 0.75, 1% round
trips, 20% casual riders) and *out for a ride* (30%: 4.9 km, 29 min,
directness 0.42, 15% round trips, 58% casual). Further splits run along the
clock, not along behaviour. See `trip-types.md`.

**Getting-there trips ride close to the cheapest path.** Odometer over the
metres-shortest street path, one-way trips:

| | median | p10 | p25 | p75 | p90 | within 10% | within 20% |
|---|---|---|---|---|---|---|---|
| getting there | 1.05 | 0.95 | 1.01 | 1.12 | 1.26 | 69% | 86% |
| out for a ride | 1.38 | | | 2.15 | 5.59 | 18% | 32% |

The extra 5% is route preference, not stops: trips with a mid-trip lock are
rare among them (2%), the hour profile is the same in every detour band, and
only the 3% beyond 1.5x slow down. `street-costs.md` reports that pure
shortest paths come out 4.5% short of the median ridden distance and the
current bikeway-weighted costs 2% short.

**The odometer cannot tell parallel streets apart.** For getting-there trips
within 10% of the shortest path, the corridor of streets that fit the
odometer is about eight times the length of the shortest path. Which parallel
street was used is decided by the cost model alone. This is where rider
profiles do their work, and it is also why the result can only be checked
against an independent source of street-level counts, never against the
odometer.

**Out for a ride is route-first.** Round trips from Stanley Park Information
Booth have an odometer mode at 9.0 to 10.0 km (57% of them; 38% in the
9.5 km bin alone), which is one seawall lap; Totem Poles and Second Beach
show the same peak. The waterfront pulls the ride; the cost discount on
waterfront edges (`SCENIC_WAY`) is the right mechanism and stays.

**Same-station trips are mostly seawall laps; the errand slice is small.**
Of 52,541 same-station trips of a minute or more (5.0% of trips), 36,317
start at park or waterfront stations (87% casual, 61% over 6 km). The 16,224
from neighbourhood stations (68% members) break down by duration and
odometer as follows, with the share that had a mid-trip lock in brackets
(lock data from April to July 2026):

| neighbourhood start | under 1 km | 1 to 3 km | 3 to 6 km | over 6 km |
|---|---|---|---|---|
| 1 to 5 min | 899 (1%) | 423 (1%) | 38 | 36 |
| 5 to 15 min | 1,145 (22%) | 2,525 (25%) | 100 (4%) | 7 |
| 15 to 30 min | 390 (50%) | 2,358 (46%) | 1,386 (19%) | 176 (7%) |
| 30 to 60 min | 596 (79%) | 1,430 (63%) | 1,305 (45%) | 1,258 (20%) |
| over 60 min | 149 (32%) | 317 (51%) | 225 (38%) | 1,461 (7%) |

One-way trips lock 2 to 3% of the time, so the nine middle cells (5 to 60
minutes, under 6 km: 11,235 trips, 1.1% of all trips) are errands; the
1 to 5 minute row is bike checks and returns; the over-6-km column and most
of the over-an-hour row are pleasure rides from a home station. Errands are
worth modelling for the local streets around neighbourhood stations and not
much beyond.

**Mid-trip locks are in every month's export.** The 2026 files call them
`Lock duration (sec.)` and `Number of bike locks`; the 2025 files call the
same thing `Stopover duration (sec.)` and `Number of stopovers` (2.8% of
August 2025 trips have one). `prep.py` does not carry them yet.

## Goals

- No randomness anywhere in routing or aggregation. The same inputs and
  settings give the same map, independent of worker count or processing
  order.
- A rule-based classifier that assigns every usable trip a purpose and a
  weight over rider profiles, from the trip row, its stations and the
  profiles' path lengths. Plain functions, unit-tested, no fitting.
- Rider profiles as cost tables: direct, traffic-averse, hill-averse,
  stop-averse, scenic. Each extends the factors in `street-costs.md`.
- A month of trips routed and aggregated in a few minutes on this machine;
  a single day's map in well under a minute. No cache to warm or invalidate.
- Output for a month (the existing 24 slices) and for a particular day
  (whole day, morning commute, evening commute, each by rider type).
- A written check of the 1.1x to 2.0x detour band: which profiles explain
  it and how much is left over.
- `corridors.py`'s shaking, hop sampling, detour sampling and loop sampling
  removed, along with their knobs, tests and the demo page.

## Non-goals

- Machine learning of any kind. Rules and knobs, in code, with the evidence
  for each written next to it.
- Changing the October forecast map (`routes.py`, `build_map.py`,
  `october_forecast.py`) or its crossing tables.
- Loops more complex than two waypoints (no figures of eight).
- A route catalogue for the park loops. The two-waypoint construction
  already produces the seawall lap; a catalogue is a later refinement if a
  comparison against independent counts asks for it.
- Tuning the profile multipliers against independent street-level counts.
  The design makes that possible and names the check; doing it is separate
  work.

## Anti-goals

- Reintroducing variety by sampling. If a split is needed, it is a weighted
  enumeration of named alternatives, never a draw.
- Per-trip Dijkstra. Routing cost must scale with stations × profiles, not
  with trips, or the speed goal is lost.
- Any result that depends on the number of workers or the order in which
  origins are processed.

## Constraints

- Python 3.14, standard library only (`analysis/pyproject.toml`).
- 15 cores and 24 GB; forked workers must stay well under a gigabyte each.
- Inputs as today: `data/trips_clean.csv`, `data/stations_canonical.csv`,
  the OSM highway extract, the attractors extract, the terrain tiles.
  Timestamps in the trip table are rounded to the hour, so time blocks are
  fuzzy by up to an hour at each edge, as they are now.
- Tests with `unittest`, run from `analysis/` with
  `uv run python -m unittest discover -s tests -t .`.
- Commits end with the Co-Authored-By line used elsewhere in this repo.

## The model

### Rider profiles

A profile is a function from a directed edge to a perceived cost, built once
per profile over the whole graph. All five start from the `way_cost()` factors
in `routes.py` (bikeway preference, lane discounts, unpaved and dismount
penalties, signed-route discount) and add one thing each:

| profile | adds | data |
|---|---|---|
| direct | nothing: the validated baseline | |
| quiet | arterials cost more: secondary, primary and trunk factors raised by `QUIET_ARTERIAL` (start 1.5x) unless the way has a protected or painted lane | OSM `highway=`, `cycleway*=` tags, already in `Network` |
| flat | paved edges at grade g cost `1 + FLAT_K * max(0, g - FLAT_FREE)` per metre, both directions (a heavy share bike is slow up and braked down); start `FLAT_K` = 15, `FLAT_FREE` = 0.02 | terrain tiles via `Network.grade()`; today only unpaved slope is priced |
| few-stops | a fixed cost added at every node tagged `highway=stop` or `highway=traffic_signals`, `STOP_M` metres' worth (start 40 m, about twelve seconds at 12 km/h) | `Network.node_tags`, which `routes.py` already reads for its crossing tables |
| scenic | waterfront edges cost `SCENIC_WAY` (0.35) of their length, as the leisure rider does today | `Attractors.scenic(parks=False)` |

A profile's cost is evaluated lazily and memoised per edge, as `Rider`
does now, so building five profiles costs one pass over the edges actually
reached.

Rider type (member, casual) and time of day enter as priors over profiles,
not as separate cost tables:

| | direct | quiet | flat | few-stops | scenic |
|---|---|---|---|---|---|
| member | 1.0 | 1.0 | 1.0 | 1.0 | 0.5 |
| casual | 1.0 | 1.0 | 1.0 | 1.0 | 2.0 |

Priors are knobs (`PROFILE_PRIOR`), start as above, and are the place
"rider personality" lives in the code. The builder may add a time-block
dimension to the prior if the detour check shows commute hours lean direct.

### Per-origin trees

For each origin station and each profile, one bounded Dijkstra over the full
graph under that profile's costs, forward out of the station, bounded by the
longest odometer among the origin's trips plus `SLACK`, capped at
`TREE_LIMIT_M` (15 km). A 15 km tree over this network (127,836 nodes,
259,559 edges) takes a fraction of a second, so 266 origins × 5 profiles is
a few core-minutes and the speed goal is met without persisting anything.
The result is three maps over reached nodes: physical metres along the
cheapest path, perceived cost and predecessor. Cost is kept because the
waypoint scores compare cost per metre. One forward tree answers every
destination from that origin: path length by lookup, path edges by walking
predecessors.

The detour and loop constructions also need trees into a destination
(`in_m`) and trees rooted at waypoints; those are bounded by the trip's
odometer budget, computed in memory while the origin is being processed and
kept in a small bounded memo, as the sampler keeps its destination-side
tables today. Nothing is written to disk: a persisted tree would be a
megabyte or more per station and profile for a saving of a fraction of a
second, and the route cache the sampler needed is pointless when routing is
deterministic and cheaper than reading it back. If a later machine or a
larger network makes the trees expensive, the place to cache is the
per-station-pair paths, not the trees.

### The classifier

Rules, applied in order to each usable trip (same usability cuts as
`trip_types.usable`: 60 s or more, odometer present and under 40 km, under
30 km/h). Thresholds are named constants in one module with their evidence
in a comment.

**Same station.**

1. Duration under `CHECK_MIN` (5 min): *check*. Not routed. Counted in the
   output's unrouted total so nothing goes missing silently.
2. Duration under `ERRAND_MAX_MIN` and odometer under `ERRAND_MAX_M`, and
   either a mid-trip lock recorded or a start station with scenic score
   under `SEAWALL` (0.5): *errand*. Defaults `ERRAND_MAX_MIN` = 60,
   `ERRAND_MAX_M` = 6,000, which is the nine-cell block in the table above
   (11,235 trips a year). The conservative core the brief named (under
   30 min, under 3 km) is 6,418 of those; the wider cut is justified by the
   45% to 79% lock rates in the 30 to 60 minute cells. Lock data is present
   for every month once `prep.py` carries it, so the lock clause applies to
   the whole year; it adds the short locked loops from park stations (a few
   hundred a year). A long same-station ride with a lock is a ride with a
   stop, not an errand, so the length and time gates apply to the lock
   clause too.
3. Otherwise: *out for a ride, loop*.

**Different stations.** Let `L_p` be the physical length of the cheapest
path from origin to destination under profile `p`, from the trees, and
`r_p = odometer / L_p`.

4. If the smallest `r_p` over the five profiles is above `LEISURE_R` (2.0):
   *out for a ride, one-way*. Routed through a waypoint (below).
5. Otherwise *getting there*. The trip's weight is spread over profiles in
   proportion to `prior_p × exp(-((r_p - 1) / FIT_SD)²/2)`, `FIT_SD` = 0.08,
   with profiles whose `r_p` falls outside [`MIN_FILL`, 1 + `SLACK`] (0.85,
   1.05) dropped unless none remain, in which case the nearest profile takes
   the whole trip. A trip 12% longer than the direct path and 2% longer than
   the scenic path goes almost entirely to scenic; a trip that fits several
   profiles equally splits by prior. This is the brief's 1.1x to 2.0x band:
   it is not a class of its own but the region where the profiles disagree
   and the odometer picks between them.

The classifier's output per trip is (purpose, {profile or construction:
weight}) and is pure: trip row, two station records, five path lengths in,
a small dict out. That makes it cheap to unit-test and cheap to report.

### Routing each purpose

**Getting there.** For each profile with weight, the tree path from origin
to destination. No construction, no draws.

**Out for a ride, one-way.** Candidate waypoints `t` from the scenic trees:
nodes where `out_m[t] + in_m[t]` lies within the odometer window and the
scenic path through `t` is cheaper per metre than the direct one. One
candidate per `TURN_CELL` (200 m) grid cell, scored
`gauss(out_m[t] + in_m[t] - odometer, WAYPOINT_SD × odometer) × pleasant(t)`,
the top `DETOUR_N` (12) kept, weights normalised. Route `a → t → b` under the
scenic profile. This is `sample_detour` with its random draw replaced by a
ranked enumeration; `pleasant()` and `waypoint_candidates()` are reused.

**Out for a ride, loop.** Two waypoints `t1`, `t2` at about a third of the
odometer apart, as `sample_loop` does today, but enumerated: the top
`LOOP_N1` (6) first waypoints by the same score, and for each the top
`LOOP_N2` (4) second waypoints, giving at most 24 loops weighted by the
product of their scores, normalised. Legs are cheapest paths under the
scenic profile; the return leg pays `REUSE_PENALTY` on edges the outbound
legs used, so laps come out as laps. The trees rooted at `t1` are bounded by
the odometer and built in memory. For the Stanley Park stations this reproduces the
seawall lap; for a home station it produces an out-and-back along the
nearest pleasant streets.

**Errand.** Candidate destinations `t` from the direct tree at the origin
with `out_m[t]` within a window around half the odometer, one per
`TURN_CELL`, scored
`gauss(out_m[t] - odometer/2, ERRAND_SD × odometer) × (ERRAND_FLOOR +
commercial(t))` with `ERRAND_FLOOR` = 0.15 so residential streets get some
weight and shopping streets most of it. The top `ERRAND_N` (12) kept,
weights normalised; each is routed out and back along the direct tree path
(a shopper returns the way they came). When a lock was recorded the odometer
is the whole trip, so the destination still sits at half of it; the lock
duration is not used for placement because the export does not say where
the lock happened.

### Aggregation and output

Classification is per trip: the classifier is pure and the five path
lengths it needs are per station pair, so this costs nothing, and it is
what makes the purpose counts in the output exact. Routing is per group,
with the group key chosen so that every trip in a group shares its routes:

- *Getting there*: (origin, destination, rider type). The routes are the
  five tree paths, fixed for the pair; what varies by trip is the profile
  weight vector, and weights are additive, so the group payload is a
  slices × profiles matrix of summed weights. No odometer bin.
- *Errand*, *loop*, *one-way ride*: (origin, destination, rider type,
  purpose, 250 m odometer bin), since the constructions depend on the
  odometer. Routed once at the bin's median odometer, as today.
- *Check*: not grouped, counted.

A group's slice counts are credited to the edges of each of its routes in
proportion to the route's weight, into one array per edge. Accumulation
runs in a fixed order (sorted origin, then sorted group key) so output is
byte-identical whatever the worker count.

Two time keys:

- **Month** (`flows.py YYYY-MM`): the existing 24 slices (weekday or
  weekend × six three-hour blocks × rider type), written to
  `output/flows_YYYY-MM.json` in the shape `build_flow_map.py` reads now,
  plus a `purposes` block giving the trip count per purpose and the
  unrouted count by reason.
- **Day** (`flows.py YYYY-MM-DD`): six slices, `all`, `morning`
  (`AM_COMMUTE`, 07:00 to 10:00) and `evening` (`PM_COMMUTE`, 16:00 to
  19:00) × rider type, written to `output/flows_YYYY-MM-DD.json` in the
  same shape. `build_flow_map.py` reads the slice names from the file, so
  it renders either with the switches the file offers.

Both modes print how many trips were classified into
each purpose and how long the run took.

### What goes

- `corridors.py`: `shake`, `legs`, `sample_hop`, `sample_detour`,
  `sample_loop`, `plain_route`, `Corridors.sample`, `Corridors.purposes`,
  and the knobs `SIGMA`, `HOP_TRIES`, `WINDOW_SD`, `HOME_CUT`,
  `RIDER_NUDGE`, `COMMERCIAL_BONUS`, `PLEASANT_K["errand"]`. `metres_table`,
  `cost_table`, `corridor`, `Bounded`, `waypoint_candidates`, `pleasant`,
  `gauss` and the per-station table memo stay, since the constructions
  reuse them. The builder may rename the module if little corridor logic
  survives.
- `leisure_share()` and its station-context knobs: purpose now comes from
  the trip, not from a probability read off the station's surroundings.
- `flows.py`: `MIN_DRAWS`, `MAX_DRAWS`, `draws_for`, `group_seed`,
  `RouteCache` and `output/cache/`; the settings digest stays in the output
  file as a record of the knobs, computed over the profile and classifier
  constants.
- `flood_demo.py`, `output/flood_demo.html` and their tests. The demo
  illustrates shaking and has no other job. `flood-routing.md` stays as the
  record of what was tried, with a note at the top pointing here.
- `tests/test_corridors.py` cases that exercise the removed functions;
  `tests/test_flows.py` cases about draws and seeds.

### Checks before calling it done

1. **Determinism.** Two runs of the same month with different `--workers`
   produce byte-identical output files.
2. **The detour band.** A report, printed by `flows.py` with `--report` and
   recorded in the write-up, over one summer month's one-way getting-there
   trips with `r_direct` between 1.1 and 2.0: the share of weight each
   profile receives, and the share of trips no profile fits within the fill
   window. If the residual is large, the profiles are missing something and
   the write-up says so; the design does not promise the residual is small.
3. **Known shapes.** Stanley Park Information Booth, casual, 9.5 km loop:
   the top-weighted loop follows the seawall. Bute & Barclay to Haro &
   Denman, member, 930 m: the direct profile's path, no detour. 8th & Ontario
   or a comparable neighbourhood station, 2 km errand: the top destinations
   lie on Main Street and Broadway.
4. **Speed.** A run of July 2026 (136,590 trips, 266 origins) under ten
   minutes on this machine; a day under a minute. The numbers go in the
   write-up.
5. **No independent check.** The lateral question (which parallel street)
   can only be settled against independent street-level counts, and this
   project has none, so the write-up says so rather than claiming agreement.
   There is no comparison against the shaken sampler either: no run of it
   exists on disk and producing one is not worth half an hour of machine
   time for a model being removed.
6. Full test suite green; `README.md` build section and layout updated; a
   write-up `analysis/rider-model.md` with Playwright screenshots of the
   month and day maps.

## Open questions

- **Should stations be classified?** The design classifies trips and reads
  a station only through its scenic score, used once in the errand rule.
  The sampler's station-side purpose (`leisure_share`: scenery, cut by
  residential land use, nudged by rider type) goes. A station type
  (scenic, commercial, residential, campus) could still earn its place in
  two spots: as a prior over profiles, raising scenic at waterfront
  stations for the trips the odometer cannot settle, and as a check on the
  errand destinations, which today come from shop density alone. The
  scenic score correlates 0.62 with a station's casual share, so a simple
  typing is well supported by the data. To be answered by the detour
  report: if trips from scenic stations are split by prior more often than
  trips elsewhere, a station prior is worth adding; otherwise the trip
  alone is enough.

## Left to the builder

- Whether the five profiles live in `routes.py` next to `way_cost()` or in
  a new `profiles.py`; whether the classifier is its own module
  (`trip_class.py` is the suggested name) or part of `flows.py`.
- How `prep.py` names the two new columns (suggested `locks`, `lock_s`) and
  how it maps the 2025 stopover names onto them.
- Candidate windows and N values above are starting points; change them if
  the known-shape checks say so, and record what changed.
- Whether `Corridors` survives as a class holding the memos or is folded
  into a tree store.
- The order of implementation. A sensible one: prep columns; profiles and trees with the determinism test; the
  classifier; getting-there routing end to end with the month output (most
  of the trips, most of the speed); then errands, detours and loops; then
  removals, docs and the report.
- `Network.ways` keeps the lane and surface flags the quiet and flat
  profiles need (`way_cost()` consumes them today without retaining them);
  the few-stops cost is applied to edges entering a tagged node.
- `build_flow_map.py` builds its switches from the slice names in the file
  instead of hard-coding day, block and rider, and does not pick a day file
  as the default month.
