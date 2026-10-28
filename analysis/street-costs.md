# Street costs: how the routing sees bike infrastructure

`routes.py` routes every trip over a street graph in which each directed edge
carries its physical length and a **perceived cost**: length times a factor
for how a Mobi rider experiences that kind of street. Routing minimises cost,
not metres, so the factor is where bike paths, lanes and signed routes enter
the model. The corridor routing design (`flood-routing.md`) uses the same
factors.

## The factors

`way_cost()` in `routes.py` assigns one factor per OSM way:

| Street class (`highway=`) | Base factor |
|---|---|
| cycleway | 0.75 |
| footway or path, where bikes are allowed | 0.8 |
| residential, living_street, unclassified | 1.0 |
| tertiary | 1.2 |
| service, track, plain path | 1.5 |
| secondary | 1.5 |
| primary | 1.9 |
| pedestrian | 2.0 |
| trunk | 3.0 |
| motorway, steps, construction, and anything tagged no bikes | impassable |

Then, in order:

- **Painted or protected lane** on an arterial (`cycleway=lane`, `track` or
  `share_busway`): the factor drops to a lower table value, tertiary 1.0,
  secondary 1.15, primary 1.3, trunk 1.8.
- **Sharrows** (`cycleway=shared_lane`): 10% off.
- **Unpaved surface** (gravel, dirt, grass and so on): at least 1.5, the same
  as a plain path.
- **Walk-your-bike** (`bicycle=dismount`): at least 10 (8 on a signed route,
  since the route discount is applied last).
- **Signed bicycle route**: membership in a `route=bicycle` relation takes
  20% off, with a floor of 0.65. This is how the City's named bikeways
  (Heather, Yukon, Ontario, 10th Avenue, Off-Broadway and the rest) are
  recognised.

Two further adjustments are per edge rather than per way:

- **Slope on unpaved ways**: an unpaved edge at 3% grade or steeper costs
  four times more. Grade comes from terrain tiles (`data/elevation/`); without
  them routing ignores slope.
- **Hand-kept exclusions**: `OBSCURE_WAYS` lists ways that exist but riders
  do not know or use, each with a comment.

The base factors were checked against the distances members actually rode on
2,800 station pairs: pure shortest paths come out 4.5% short of the median
ridden distance, these weights 2% short, and stronger bikeway preferences fit
no better.

## A worked neighbourhood: 10th & Cambie

What the model sees around the 10th & Cambie station, from the OSM extract:

| Street | OSM class | Bike facility | Cost per metre |
|---|---|---|---|
| Cambie Street | primary | none | 1.9 |
| West Broadway | primary | none; stretches closed for subway works | 1.9 or impassable |
| Heather Street | residential, Heather Bikeway | signed route, sharrows on some blocks | 0.72 to 0.8 |
| Yukon Street | residential, Yukon Bikeway | signed route, painted lane on some blocks | 0.8 |
| West 10th Avenue | residential, 10th Avenue Bikeway | signed route, separate path on some blocks | 0.65 to 0.8 |
| Ontario Street | residential, Ontario Greenway | signed route, separate path in places | 0.65 to 0.8 |
| Ash Street | residential, partly Off-Broadway Bikeway | lane on the bikeway blocks | 0.72 to 1.2 |

A metre of Cambie costs about two and a half times a metre of Heather, so
routes from 10th & Cambie climb the hill on Heather and Yukon and never on
Cambie, which matches how people ride there. The all-draws overlay for that
station in `flood-routing.md` shows it.

Where OSM maps a bike path as its own way beside the road (`cycleway=separate`
on the road), the road keeps its plain factor and the separate cycleway way
gets 0.75, or 0.65 on a signed route. The routing picks the path.

## What the factors do not capture

- A protected lane and a painted lane on the same class of road get the same
  value.
- Traffic volume, signal timing and stop signs are not in it. The crossing
  analysis in `routes.py` looks at controls separately, after routing.
- A quiet residential street and a residential cut-through cost the same.
- Slope only matters on unpaved ways. Paved hills are free, which is wrong
  for a heavy bike but has not been tuned.
- OSM tagging dates. Broadway reads partly impassable today because of
  construction tags from the subway works; that will need refreshing when
  the works end. The extract's date is printed by `data/osm/download.sh`.

Tuning the factors further would need an independent source of street-level
cycling counts to check against; this project has none.
