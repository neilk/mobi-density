"""Illustrate corridor routing: output/flood_demo.html.

Throwaway demo for the design in flood-routing.md. For two example trips, a
short one-way hop and a Stanley Park round trip, it draws the corridor (every
street segment a rider could have used within the odometer distance), labels
each street with its shaken cost multiplier, and highlights the route picked
under that shake. Two shakes per trip, so four map panels in all.

Run from analysis/ after prep.py, with the OSM extract in place:
    uv run python flood_demo.py
then serve the repo (./serve.sh) and open analysis/output/flood_demo.html.
"""
import json
import random
from collections import Counter, defaultdict

from attractors import Attractors
from common import OUT, load_stations
from routes import Network

from corridors import (Bounded, Rider, SLACK, build_graph, corridor, corridor_adj, cost_table, leisure_share, metres_table, sample_hop, sample_loop, shortest)

DRAWS = 30            # routes per example in the "all draws" panel, each drawn at 1/DRAWS opacity

EXAMPLES = [
    {"key": "hop", "title": "One-way hop: Bute & Barclay → Haro & Denman, member, odometer 930 m",
     "from": "0300", "to": "0122", "metres": 930, "rider": "member", "seeds": [1, 2]},
    {"key": "loop", "title": "Round trip: Stanley Park Information Booth and back, casual rider, odometer 9,570 m",
     "from": "0209", "to": "0209", "metres": 9570, "rider": "casual", "seeds": [6, 2]},   # one lap, one Coal Harbour ride
    {"key": "chilco_casual", "title": "Round trip: Chilco & Robson and back, casual rider, odometer 9,660 m (the median there)",
     "from": "0093", "to": "0093", "metres": 9660, "rider": "casual", "seeds": [1, 2]},
    {"key": "chilco_member", "title": "Round trip: Chilco & Robson and back, member, odometer 3,700 m (the median there)",
     "from": "0093", "to": "0093", "metres": 3700, "rider": "member", "seeds": [1, 2]},
    {"key": "jericho", "title": "Round trip: Jericho Beach and back, casual rider, odometer 4,050 m (the median there)",
     "from": "0400", "to": "0400", "metres": 4050, "rider": "casual", "seeds": [1, 2]},
    {"key": "cambie", "title": "Round trip: 10th & Cambie and back, member, odometer 1,900 m (the median there)",
     "from": "0001", "to": "0001", "metres": 1900, "rider": "member", "seeds": [1, 2]},
]

def main():
    stations = load_stations()
    net = Network()
    attractors = Attractors()
    if not attractors.available:
        print("no attractors extract; round-trip waypoints ignore scenery and shops (run data/osm/download_attractors.sh)")
    fwd, rev = build_graph(net)
    snap_grid = defaultdict(list)
    for n in net.snappable:
        snap_grid[(int(net.xy[n][0] // 100), int(net.xy[n][1] // 100))].append(n)

    panels = []
    for ex in EXAMPLES:
        a, _ = net.nearest(stations[ex["from"]]["lat"], stations[ex["from"]]["lon"], snap_grid)
        b, _ = net.nearest(stations[ex["to"]]["lat"], stations[ex["to"]]["lon"], snap_grid)
        budget = ex["metres"] * (1 + SLACK)
        out_m = metres_table(fwd, a, budget)
        in_m = metres_table(rev, b, budget)
        edges = corridor(fwd, out_m, in_m, budget)
        plain = shortest(corridor_adj(edges), a, b, defaultdict(lambda: 1.0), {}) if a != b else None
        print(f"{ex['key']}: {len(out_m):,} nodes within {budget:,.0f} m of A, corridor {len(edges):,} edges, "
              f"{len({wi for _, _, wi, _, _ in edges}):,} ways" + (f", plain shortest {plain[2]:,.0f} m" if plain else ""))
        purposes = None
        if a == b:
            p_leisure = leisure_share(attractors, *net.xy[a], ex["rider"])
            print(f"  leisure share of round trips here for a {ex['rider']} rider: {p_leisure:.2f}")
            purposes = []
            for p, kind in ((p_leisure, "leisure"), (1 - p_leisure, "errand")):
                if p > 0:
                    r = Rider(net, attractors, kind)
                    purposes.append((p, r, cost_table(fwd, a, out_m, r.edge_mult), cost_table(rev, a, in_m, r.edge_mult)))
            adjs = {r.kind: corridor_adj(edges, r.edge_mult) for _, r, _, _ in purposes}
        hop_adj = corridor_adj(edges, Rider(net, attractors, "leisure" if ex["rider"] == "casual" else "errand").edge_mult)
        for seed in ex["seeds"]:
            rng = random.Random(seed)
            if a == b:
                f, route, turn, purpose = sample_loop(net, adjs, a, budget, out_m, in_m, purposes, ex["metres"], rng, Bounded(16))
            else:
                f, route = sample_hop(hop_adj, a, b, budget, ex["metres"], rng)
                turn = None
                purpose = None
            # one label per way, at the midpoint of its longest corridor edge
            longest = {}
            for u, v, wi, m, c in edges:
                if m > longest.get(wi, (0,))[0]:
                    longest[wi] = (m, u, v)
            labels = [{"ll": [(net.latlon[u][0] + net.latlon[v][0]) / 2, (net.latlon[u][1] + net.latlon[v][1]) / 2],
                       "f": round(f[wi], 2)} for wi, (_, u, v) in longest.items()]
            panels.append({
                "title": ex["title"], "seed": seed, "purpose": purpose,
                "turn": [net.latlon[t] for t in turn] if turn else None,
                "a": net.latlon[a], "b": net.latlon[b], "metres": route[2], "budget": budget,
                "edges": [{"ll": [net.latlon[u], net.latlon[v]], "f": round(f[wi], 2),
                           "name": net.ways[wi]["name"] or "(unnamed)", "hw": net.ways[wi]["hw"],
                           "base": round(c / m, 2), "m": round(m)} for u, v, wi, m, c in edges],
                "labels": labels,
                "label_zoom": 15 if len(labels) <= 60 else 16 if len(labels) <= 600 else 17,
                "route": [net.latlon[n] for n in route[0]],
                "plain": [net.latlon[n] for n in plain[0]] if plain else None,
                "streets": street_summary(net, route[1], edges),
            })
            print(f"  seed {seed}: route {route[2]:,.0f} m over {len(route[0])} nodes"
                  + (f", waypoints {[net.latlon[t] for t in turn]}" if turn else ""))
        # every draw at once: the trip spread over DRAWS routes, each carrying 1/DRAWS of it
        routes, purposes_drawn, total = [], Counter(), 0.0
        for seed in range(DRAWS):
            rng = random.Random(1000 + seed)
            if a == b:
                _, route, _, purpose = sample_loop(net, adjs, a, budget, out_m, in_m, purposes, ex["metres"], rng, Bounded(16))
                purposes_drawn[purpose] += 1
            else:
                _, route = sample_hop(hop_adj, a, b, budget, ex["metres"], rng)
            routes.append([net.latlon[n] for n in route[0]])
            total += route[2]
        panels.append({
            "title": ex["title"], "all": routes, "a": net.latlon[a], "b": net.latlon[b],
            "mean_metres": total / DRAWS, "budget": budget,
            "purposes": dict(purposes_drawn),
            "edges": [{"ll": [net.latlon[u], net.latlon[v]]} for u, v, wi, m, c in edges],
        })
        print(f"  {DRAWS} draws: mean route {total / DRAWS:,.0f} m" + (f", purposes {dict(purposes_drawn)}" if purposes_drawn else ""))

    OUT.mkdir(exist_ok=True)
    (OUT / "flood_demo.html").write_text(HTML.replace("__PANELS__", json.dumps(panels)), encoding="utf-8")
    print(f"wrote {OUT / 'flood_demo.html'}")


def street_summary(net, ways, edges):
    """Street names along the route, in order, merged when consecutive."""
    out = []
    for wi in ways:
        w = net.ways[wi]
        name = "" if w["name"] == w["route"] else w["name"]    # skip relation-name fallbacks
        if name and (not out or out[-1] != name):
            out.append(name)
    return out if len(out) <= 14 else out[:7] + ["…"] + out[-6:]


HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Corridor routing demo</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
  body { margin: 0; font: 14px/1.4 system-ui, sans-serif; background: #fff; color: #222; }
  .panel { margin: 24px auto; max-width: 1100px; }
  h2 { font-size: 17px; margin: 0 0 4px; }
  .sub { color: #555; margin: 0 0 8px; }
  .map { height: 620px; border: 1px solid #ccc; }
  .osm-tiles { filter: grayscale(1) brightness(1.06) contrast(.85); opacity: .7; }
  .lbl { background: rgba(255,255,255,.85); border: 1px solid #999; border-radius: 3px; padding: 0 3px;
         font: 11px/1.3 ui-monospace, monospace; white-space: nowrap; }
  .legend { position: absolute; width: 230px; bottom: 12px; left: 12px; z-index: 500; background: rgba(255,255,255,.92);
            padding: 8px 10px; border-radius: 4px; font-size: 12px; box-shadow: 0 1px 4px rgba(0,0,0,.3); }
  .legend i { display: inline-block; width: 22px; height: 4px; vertical-align: middle; margin-right: 6px; }
  .legend .grad { width: 120px; height: 10px; background: linear-gradient(90deg, #1f77b4, #ddd, #d62728); }
</style></head><body>
<script>
const PANELS = __PANELS__;
// shaken multiplier -> colour: blue when the street came out cheaper than usual, red when dearer
function colour(f) {
  const t = Math.max(-1, Math.min(1, Math.log(f) / 0.7));
  const mix = (a, b, k) => a.map((x, i) => Math.round(x + (b[i] - x) * k));
  const c = t < 0 ? mix([221,221,221], [31,119,180], -t) : mix([221,221,221], [214,39,40], t);
  return `rgb(${c.join(",")})`;
}
PANELS.forEach((p, i) => {
  const div = document.createElement("div"); div.className = "panel";
  if (p.all) {
    const k = p.all.length;
    const purp = Object.keys(p.purposes).length ? " (" + Object.entries(p.purposes).map(([a, b]) => b + " " + a).join(", ") + ")" : "";
    div.innerHTML = `<h2>${p.title}</h2><p class="sub">All ${k} draws at once, each drawn at 1/${k} opacity${purp}: mean route
      ${Math.round(p.mean_metres).toLocaleString()} m (budget ${Math.round(p.budget).toLocaleString()} m). A street every draw uses is solid; one used once is barely there.</p><div class="map" id="m${i}"></div>`;
    document.body.appendChild(div);
    const map = L.map("m" + i, { preferCanvas: true }).setView(p.a, 15);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, className: "osm-tiles",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(map);
    p.edges.forEach(e => L.polyline(e.ll, { color: "#9ab", weight: 2, opacity: .35, interactive: false }).addTo(map));
    const all = L.featureGroup();
    p.all.forEach(r => L.polyline(r, { color: "#111", weight: 5, opacity: 1 / k, interactive: false }).addTo(all));
    all.addTo(map);
    L.circleMarker(p.a, { radius: 8, color: "#fff", fillColor: "#2a7", fillOpacity: 1, weight: 2 }).bindTooltip("start").addTo(map);
    L.circleMarker(p.b, { radius: 8, color: "#fff", fillColor: "#e63", fillOpacity: 1, weight: 2 }).bindTooltip("end").addTo(map);
    map.fitBounds(all.getBounds(), { padding: [40, 40] });
    const leg = L.control({ position: "bottomleft" });
    leg.onAdd = () => { const d = L.DomUtil.create("div", "legend"); d.innerHTML =
      `<div><i style="background:#111;height:6px"></i>${k} sampled routes, 1/${k} opacity each</div>
       <div><i style="background:#9ab;height:2px"></i>corridor: every street some route could use</div>`; return d; };
    leg.addTo(map);
    return;
  }
  div.innerHTML = `<h2>${p.title}</h2><p class="sub">Shake ${p.seed}${p.purpose ? " (" + p.purpose + " ride)" : ""}: route picked is ${Math.round(p.metres).toLocaleString()} m
    (budget ${Math.round(p.budget).toLocaleString()} m), via ${p.streets.join(" → ")}</p><div class="map" id="m${i}"></div>`;
  document.body.appendChild(div);
  const map = L.map("m" + i, { preferCanvas: true }).setView(p.a, 15);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, className: "osm-tiles",
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(map);
  const corridor = L.featureGroup().addTo(map);
  p.edges.forEach(e => L.polyline(e.ll, { color: colour(e.f), weight: 3, opacity: .9 })
    .bindTooltip(`${e.name} (${e.hw}) ${e.m} m<br>base factor ${e.base} × shake ${e.f} = ${(e.base * e.f).toFixed(2)}`)
    .addTo(corridor));
  const labels = L.layerGroup();
  p.labels.forEach(l => L.marker(l.ll, { icon: L.divIcon({ className: "lbl", html: "×" + l.f.toFixed(2), iconSize: null }),
    interactive: false }).addTo(labels));
  if (p.plain) L.polyline(p.plain, { color: "#444", weight: 3, dashArray: "6 6", opacity: .8 }).addTo(map);
  L.polyline(p.route, { color: "#111", weight: 6, opacity: .95 }).addTo(map);
  L.circleMarker(p.a, { radius: 8, color: "#fff", fillColor: "#2a7", fillOpacity: 1, weight: 2 }).bindTooltip("start").addTo(map);
  L.circleMarker(p.b, { radius: 8, color: "#fff", fillColor: "#e63", fillOpacity: 1, weight: 2 }).bindTooltip("end").addTo(map);
  (p.turn || []).forEach((t, k) => L.circleMarker(t, { radius: 7, color: "#fff", fillColor: "#a3d", fillOpacity: 1, weight: 2 })
    .bindTooltip("waypoint " + (k + 1)).addTo(map));
  map.fitBounds(L.polyline(p.route).getBounds(), { padding: [60, 60] });
  const showLabels = () => { if (map.getZoom() >= p.label_zoom) labels.addTo(map); else map.removeLayer(labels); };
  map.on("zoomend", showLabels); showLabels();
  const leg = L.control({ position: "bottomleft" });
  leg.onAdd = () => { const d = L.DomUtil.create("div", "legend"); d.innerHTML =
    `<div><i style="background:#111;height:6px"></i>route picked under this shake</div>
     ${p.plain ? '<div><i style="background:repeating-linear-gradient(90deg,#444 0 6px,transparent 6px 12px)"></i>plain shortest path (no shake)</div>' : ""}
     ${p.turn ? '<div><i style="background:#a3d;height:8px;width:8px;border-radius:4px"></i>waypoints drawn for this sample</div>' : ""}
     <div style="margin-top:4px">corridor streets, coloured by shake multiplier</div>
     <div><span class="grad" style="display:inline-block;vertical-align:middle"></span> ×0.5 … ×1 … ×2</div>
     <div style="color:#555">labels (×n) appear when zoomed in; hover a street for its base cost</div>`; return d; };
  leg.addTo(map);
});
</script></body></html>
"""

if __name__ == "__main__":
    main()
