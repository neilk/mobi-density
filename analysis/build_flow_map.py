"""Build output/flow_map.html from output/flows_<month>.json (flows.py).

One month of Mobi riding, every street segment shaded by how many riders
passed along it, with switches for rider type, weekday/weekend and time
block. See flood-routing.md, "Wiring it in: the monthly flow map".

    uv run python build_flow_map.py [YYYY-MM]     default: the latest flows_*.json
"""
import html
import json
import sys
from datetime import date

from common import BLOCK_NAMES, OUT

INK = "#1b2a49"


def month_name(month):
    y, m = map(int, month.split("-"))
    return date(y, m, 1).strftime("%B %Y")


def render(data):
    """The complete HTML page for one month's flows."""
    title = f"Mobi flows, {month_name(data['month'])}"
    blocks = "".join(f'<label><input type="radio" name="block" value="{b}"> {b}</label>' for b in BLOCK_NAMES)
    return PAGE.replace("__TITLE__", html.escape(title)).replace("__BLOCKS__", blocks) \
               .replace("__INK__", INK).replace("__DATA__", json.dumps(data, separators=(",", ":")).replace("</", "<\\/"))


def main(argv):
    month = argv[0] if argv else max(p.stem.split("_", 1)[1] for p in OUT.glob("flows_*.json"))
    data = json.loads((OUT / f"flows_{month}.json").read_text(encoding="utf-8"))
    path = OUT / "flow_map.html"
    path.write_text(render(data), encoding="utf-8")
    print(f"wrote {path}: {len(data['segments']):,} segments, {data['routed']:,} trips")


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>__TITLE__</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
  html, body, #map { height: 100%; margin: 0; }
  body { font: 13px/1.4 system-ui, sans-serif; color: #222; background: #e8e8e8; }
  .osm-tiles { filter: grayscale(1) brightness(1.06) contrast(.85); opacity: .7; }
  .panel { background: rgba(255,255,255,.94); border-radius: 6px; box-shadow: 0 1px 4px rgba(0,0,0,.3); padding: 10px 12px; }
  .controls { width: 230px; }
  .controls h1 { font-size: 16px; margin: 0 0 6px; }
  .controls fieldset { border: 0; padding: 0; margin: 6px 0 0; }
  .controls legend { font-weight: 600; margin-bottom: 2px; }
  .controls label { display: block; cursor: pointer; }
  .legend { width: 230px; color: #444; }
  .legend .bar { height: 10px; margin: 6px 0 2px; background: linear-gradient(90deg, rgba(27,42,73,.06), __INK__); border-radius: 2px; }
  .legend .ends { display: flex; justify-content: space-between; font-size: 11px; }
  .legend b { color: #222; }
  .leaflet-tooltip { font: 12px system-ui, sans-serif; }
</style></head><body>
<div id="map"></div>
<script>
const DATA = __DATA__;
const INK = "__INK__";
const map = L.map("map", { preferCanvas: true }).setView([49.2745, -123.122], 13);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, className: "osm-tiles",
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(map);

// Slice names are "day|block|rider"; a selection is one value or "all" per part.
const parts = DATA.slices.map(s => s.split("|"));
const sel = { rider: "all", day: "all", block: "all" };
const chosen = () => parts.map((p, i) => (sel.day === "all" || p[0] === sel.day) &&
  (sel.block === "all" || p[1] === sel.block) && (sel.rider === "all" || p[2] === sel.rider) ? i : -1).filter(i => i >= 0);

let layer = null;
function draw() {
  const idx = chosen();
  const loads = DATA.segments.map(s => idx.reduce((t, i) => t + (s.n[i] || 0), 0));
  const max = Math.max(1e-9, ...loads);
  if (layer) map.removeLayer(layer);
  layer = L.layerGroup();
  DATA.segments.forEach((s, k) => {
    const load = loads[k];
    if (load <= 0) return;
    const r = Math.sqrt(load / max);
    L.polyline(s.ll, { color: INK, opacity: Math.max(0.06, r), weight: 1.5 + 3 * r })
      .bindTooltip(`${s.name || "(unnamed path)"} · ${s.kind} · ${Math.round(load).toLocaleString()} riders`, { sticky: true })
      .addTo(layer);
  });
  layer.addTo(map);
  const trips = idx.reduce((t, i) => t + DATA.slice_trips[i], 0);
  const words = [sel.rider === "all" ? "all riders" : sel.rider + "s", sel.day === "all" ? "all days" : sel.day + "s",
                 sel.block === "all" ? "all hours" : sel.block].join(", ");
  document.getElementById("sel").innerHTML = `<b>${words}</b><br>${trips.toLocaleString()} trips, busiest segment ${Math.round(max).toLocaleString()} riders`;
}

const controls = L.control({ position: "topright" });
controls.onAdd = () => {
  const d = L.DomUtil.create("div", "panel controls");
  d.innerHTML = `<h1>__TITLE__</h1>
    <fieldset><legend>Riders</legend>
      <label><input type="radio" name="rider" value="all" checked> all</label>
      <label><input type="radio" name="rider" value="member"> members</label>
      <label><input type="radio" name="rider" value="casual"> casual</label></fieldset>
    <fieldset><legend>Days</legend>
      <label><input type="radio" name="day" value="all" checked> all</label>
      <label><input type="radio" name="day" value="weekday"> weekdays</label>
      <label><input type="radio" name="day" value="weekend"> weekends</label></fieldset>
    <fieldset><legend>Hours</legend>
      <label><input type="radio" name="block" value="all" checked> all</label>__BLOCKS__</fieldset>`;
  L.DomEvent.disableClickPropagation(d);
  d.addEventListener("change", e => { sel[e.target.name] = e.target.value; draw(); });
  return d;
};
controls.addTo(map);

const legend = L.control({ position: "bottomleft" });
legend.onAdd = () => {
  const d = L.DomUtil.create("div", "panel legend");
  d.innerHTML = `<div id="sel"></div><div class="bar"></div><div class="ends"><span>few riders</span><span>busiest</span></div>
    <div style="margin-top:6px">Shade and width follow the square root of riders relative to the busiest segment.
    Every Mobi trip of the month, round trips included, spread over the routes it could have taken.</div>`;
  return d;
};
legend.addTo(map);

DATA.stations.forEach(s => L.circleMarker(s.ll, { radius: 3, color: "#999", weight: 1, fillColor: "#fff", fillOpacity: .9 })
  .bindTooltip(s.name).addTo(map));
draw();
</script></body></html>
"""

if __name__ == "__main__":
    main(sys.argv[1:])
