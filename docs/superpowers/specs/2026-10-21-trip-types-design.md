# Trip types: do Mobi rides separate into kinds?

## Intent

Find out whether the year of Mobi trips (Aug 2025 - Jul 2026, `data/trips_clean.csv`)
falls into distinct types of ride, and if so what they look like: how direct
the ride was (odometer distance against time and against the straight line
between its stations), when it happened (hour, weekday/weekend, season), how
long it was, and whether it started or ended somewhere with tourist appeal.

Prior art, used for heuristics rather than copied:

- lgeo.co, "Mobi bike share data": Stanley Park and beachfront stations as the
  recreational layer; round trips as leisure; directness as odometer over a
  routed estimate (Stanley Park routes 1.22x distance, 1.49x time; everything
  else about 1.0x and 0.90x).
- mobi-transit-explorer.adnanreza.com: a points heuristic for "leisure":
  round trip +3, seawall endpoint +2, over 40 min +2 (over 20 min +1),
  weekend +1, midday departure +1, detour above 1.8x +1; four points is
  leisure. Detour is odometer over straight-line station distance, only where
  the ratio is 1-5x and the ends are 300 m or more apart.

## Goals

- Per-trip features, computed from the cleaned table plus the station table
  and the OSM attractors extract (`attractors.py`):
  - `distance_m` (odometer), `duration_s` (new column, see below), speed km/h
  - directness: straight-line station distance / odometer, 0..1; round trips 0
  - scenic score of the start and end station: `Attractors.scenic_near`
    at 300 m, the share of a disc around the station that is waterfront,
    park or beach. Stanley Park, Granville Island and seawall stations score
    0.9-1.0; downtown office stations near 0.
  - departure hour (hour-rounded at source), weekend flag, month
- Unsupervised clustering (k-means, standard library only) on the behaviour
  and time-of-day features; season, rider type and e-bike are kept out of the
  clustering and used to profile the clusters, so the question "do rides
  separate into types?" is answered by the ride, not by who or when.
- A profile of each cluster and a comparison with the explorer's leisure
  points, so the clusters can be read against a known heuristic.
- An HTML report with charts and a markdown write-up of what was found.

## Non-goals

- Routing. Directness uses the straight line, not a routed estimate.
- A classifier or a per-trip "truth" label.
- Changing `routes.py`, `flows.py` or the maps.

## Data decisions

- `prep.py` gains a `duration_s` column, the source "Duration (sec.)". The
  cleaned table's timestamps are hour-rounded, so duration from timestamps
  is useless for speed; the source column is exact and agrees with the
  timestamps to within the hour for 99.5% of trips.
- Bad telemetry is excluded from the feature table and counted: duration
  under 60 s, speed over 30 km/h, odometer over 40 km. About 35,000 trips
  have a duration under a minute against kilometres of odometer.
- Low speed is kept: a 2 km/h trip is a bike locked mid-ride, which is a
  real leisure signal.

## Method decisions (the builder's)

- Features for clustering, each z-scored: log odometer, log duration,
  directness, scenic start, scenic end, sin/cos of departure hour, weekend.
- k-means++ on a seeded random sample of 100,000 usable trips, k chosen by
  silhouette on a 5,000-trip subsample over k = 2..8, then every usable trip
  assigned to its nearest centroid.
- Outputs: `output/trip_types.json` (profiles, histograms, centroids),
  `output/trip_types.html` (report), stdout summary. `analysis/trip-types.md`
  records the findings with screenshots in `analysis/img/`.
