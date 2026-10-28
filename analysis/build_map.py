"""Build output/map.html: routed flows, busy-street crossings, crossroads and
stations on one interactive map. Run after station_time.py and routes.py."""
import csv
import json
from collections import defaultdict

from common import AM_COMMUTE, DATA, OCT_2026_DAYS, OUT, PM_COMMUTE, load_stations

# Polling places, one list per voting period, kept next to the project folder
VOTING_PLACES = {"advance": DATA / "voting_places_advance.csv",
                 "election_day": DATA / "voting_places_election_day.csv"}

TOP_CROSSINGS = TOP_CROSSROADS = 60
# Hand-picked spots: (label, major road, bike route) looks up the crossings
# table, (label, location) the crossroads table, and (label, lat, lon) is a
# point taken from the OSM extract for places outside the Mobi tables.
# Final locations with their teams. "where" is (major road, bike route) for the
# crossings table, (location,) for the crossroads table, or (lat, lon).
LOCATIONS = [
    {"name": "Ontario & 2nd", "where": ("East 2nd Avenue / West 2nd Avenue", "Ontario Street"),
     "candidates": "Jarrett Hagglund, Dominic Denofrio", "volunteers": "Neil, Tavis"},
    {"name": "8th & MacDonald", "where": (49.264968, -123.168438),
     "candidates": "John Irwin", "volunteers": "Margie, Noah"},
    {"name": "Rupert Station", "where": (49.260666, -123.033774),
     "candidates": "Iona Bonamis, Frances Bula", "volunteers": "Geoff"},
    {"name": "Dunsmuir & Richards", "where": ("Dunsmuir Street", "Richards Street"),
     "candidates": "Tyler Petersen, Caitlin Stockwell", "volunteers": "Andrew"},
]


def read(name):
    with open(OUT / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    flows = json.load(open(OUT / "route_flows.json"))

    crossings = [{
        "name": f"{r['bike_route']} × {r['major_road']}",
        "detail": f"{r['rider_way_type']} crossing a {r['road_class']} road"
                  + (f", {r['lanes']} lanes" if r["lanes"] else "") + f"; {round(float(r['member_share']) * 100)}% members",
        "v": [float(r["oct_trips"]), float(r["per_weekday_07_10"]), float(r["per_weekday_16_19"]), float(r["per_weekend_day"])],
        "ll": [float(r["lat"]), float(r["lon"])],
    } for r in read("busy_street_crossings.csv") if r["long_wait_likely"] == "1"][:TOP_CROSSINGS]

    crossroads = [{
        "name": r["location"],
        "detail": f"{r['arms']} arms ({r['arm_shares']}); links {r['stations_linked']} stations; "
                  f"{round(float(r['member_share']) * 100)}% members",
        "v": [float(r["oct_trips_through"]), float(r["per_weekday_07_10"]), float(r["per_weekday_16_19"]), float(r["per_weekend_day"])],
        "ll": [float(r["lat"]), float(r["lon"])],
    } for r in read("crossroads.csv")][:TOP_CROSSROADS]

    crossing_rows, crossroad_rows = read("busy_street_crossings.csv"), read("crossroads.csv")
    locations = []
    for loc in LOCATIONS:
        key = loc["where"]
        if isinstance(key[0], float):
            ll = list(key)
        else:
            row = (next(r for r in crossing_rows if (r["major_road"], r["bike_route"]) == key) if len(key) == 2
                   else next(r for r in crossroad_rows if r["location"] == key[0]))
            ll = [float(row["lat"]), float(row["lon"])]
        locations.append({"name": loc["name"], "ll": ll, "candidates": loc["candidates"], "volunteers": loc["volunteers"]})

    stations = load_stations()
    st = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0.0])   # october, weekday am, weekday pm, member october, weekend day
    for r in read("station_time_blocks.csv"):
        days = OCT_2026_DAYS[r["day_type"]]
        s = st[r["station_id"]]
        s[0] += float(r["oct_trip_ends_per_day"]) * days
        s[3] += float(r["oct_member_trip_ends_per_day"]) * days
        if r["day_type"] == "weekend":
            s[4] += float(r["oct_trip_ends_per_day"])
        if r["day_type"] == "weekday" and r["block"] == AM_COMMUTE:
            s[1] = float(r["oct_trip_ends_per_day"])
        if r["day_type"] == "weekday" and r["block"] == PM_COMMUTE:
            s[2] = float(r["oct_trip_ends_per_day"])
    station_rows = [{
        "name": stations[sid]["name"],
        "detail": f"Mobi station {sid}; {round(100 * v[3] / v[0])}% members" + (" (UBC campus)" if stations[sid]["ubc"] else ""),
        "v": [round(v[0]), v[1], v[2], round(v[4], 1)],
        "ll": [stations[sid]["lat"], stations[sid]["lon"]],
    } for sid, v in st.items() if stations[sid]["active"] and v[0] > 0]

    data = {"segments": flows["segments"], "routed": flows["routed_trips"],
            "crossings": crossings, "crossroads": crossroads, "stations": station_rows, "locations": locations,
            "voting": {}}
    for key, path in VOTING_PLACES.items():
        with open(path, newline="", encoding="utf-8-sig") as f:
            data["voting"][key] = [{"name": r["Name"], "address": r["Address"].replace(", Canada", ""),
                                    "ll": [float(r["Latitude"]), float(r["Longitude"])]} for r in csv.DictReader(f)]
    html = TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
    (OUT / "map.html").write_text(html, encoding="utf-8")
    print(f"{len(flows['segments']):,} segments, {len(crossings)} crossings, {len(crossroads)} crossroads, "
          f"{len(station_rows)} stations, {', '.join(f'{len(v)} {k} voting places' for k, v in data['voting'].items())} -> {OUT / 'map.html'} ({len(html) / 1e6:.1f} MB)")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OCV26 Oct 13 Bikestreeting</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
  :root {
    color-scheme: light;
    --surface-1: #fcfcfb; --surface-2: #f3f2ef; --hairline: #dddcd7;
    --text-primary: #0b0b0b; --text-secondary: #52514e;
    --flow: #eda100;
    --crossing: #eb6834; --crossroad: #2a78d6; --station: #1baf7a; --location: #d1242f;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body { background: var(--surface-1); color: var(--text-primary);
         font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; display: flex; }
  #map { flex: 1; min-width: 0; height: 100%; background: var(--surface-2); }
  .osm-tiles { filter: grayscale(1) brightness(1.06) contrast(.85); opacity: .7; }  /* keep the basemap behind the data */
  #panel { width: 370px; height: 100%; overflow-y: auto; padding: 16px; border-left: 1px solid var(--hairline); }
  h1 { font-size: 18px; margin: 0 0 4px; }
  h2 { font-size: 13px; margin: 20px 0 6px; display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; }
  p { margin: 0 0 10px; color: var(--text-secondary); }
  fieldset { border: 0; padding: 0; margin: 12px 0 0; }
  legend { padding: 0; font-weight: 600; margin-bottom: 4px; }
  .seg { display: flex; border: 1px solid var(--hairline); border-radius: 6px; overflow: hidden; }
  .seg label { flex: 1; text-align: center; padding: 6px 2px; font-size: 13px; cursor: pointer; border-left: 1px solid var(--hairline); }
  .seg label:first-child { border-left: 0; }
  .seg input { position: absolute; opacity: 0; }
  .seg input:checked + span { font-weight: 700; }
  .seg label:has(input:checked) { background: var(--surface-2); }
  .seg label:has(input:focus-visible) { outline: 2px solid var(--text-primary); outline-offset: -2px; }
  .layers label { display: flex; align-items: center; gap: 8px; padding: 3px 0; cursor: pointer; }
  .key { width: 14px; height: 14px; flex: none; display: inline-block; }
  .key.crossing { background: var(--crossing); transform: rotate(45deg) scale(.8); }
  .key.crossroad { background: var(--crossroad); border-radius: 50%; }
  .key.station { background: var(--station); border-radius: 3px; }
  .key.location { border: 3px solid var(--location); border-radius: 50%; position: relative; }
  .key.location::before, .key.location::after, .xh::before, .xh::after {
    content: ""; position: absolute; background: var(--location); left: 50%; top: 50%; transform: translate(-50%, -50%); }
  .key.location::before { width: 6px; height: 1px; } .key.location::after { width: 1px; height: 6px; }
  .team { color: var(--text-secondary); font-size: 12px; }
  .pop b { font-size: 14px; } .pop div { margin-top: 4px; }
  /* .xh is the crosshair at the centre of each ring; Leaflet positions it absolutely */
  .xh::before { width: 18px; height: 1.5px; } .xh::after { width: 1.5px; height: 18px; }
  .key.voting { background: var(--surface-1); border: 3px solid var(--text-secondary); border-radius: 50%; }
  .key.buffer { background: var(--text-secondary); opacity: .25; border-radius: 50%; }
  .mk.voting i { background: var(--surface-1); border: 3px solid var(--text-secondary); border-radius: 50%; width: 12px; height: 12px; }
  .key.flow { height: 4px; background: var(--flow); border-radius: 2px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  td { padding: 4px 0; border-top: 1px solid var(--hairline); vertical-align: top; }
  td.n { text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; padding-left: 8px; white-space: nowrap; }
  td.r { color: var(--text-secondary); width: 22px; font-variant-numeric: tabular-nums; }
  td button { all: unset; cursor: pointer; }
  td button:hover, td button:focus-visible { text-decoration: underline; }
  .unit { color: var(--text-secondary); font-weight: 400; margin-left: auto; font-size: 12px; }
  .mk { display: flex; align-items: center; justify-content: center; }
  .mk i { display: block; border: 2px solid var(--surface-1); opacity: .92; }
  .mk:hover i, .mk:focus i { outline: 2px solid var(--text-primary); opacity: 1; }
  .mk.crossing i { background: var(--crossing); transform: rotate(45deg); }
  .mk.crossroad i { background: var(--crossroad); border-radius: 50%; }
  .mk.station i { background: var(--station); border-radius: 3px; }
  .tip b { font-size: 14px; } .tip span { display: block; color: var(--text-secondary); max-width: 260px; white-space: normal; }
  .note { font-size: 12px; margin-top: 18px; }
  @media (max-width: 760px) { body { flex-direction: column; } #map { height: 60%; flex: none; }
    #panel { width: 100%; height: auto; border-left: 0; border-top: 1px solid var(--hairline); } }
</style>
</head>
<body>
<div id="map"></div>
<div id="panel">
  <h1>OCV26 Oct 13 Bikestreeting</h1>
  <p>Mobi bike-share trips only, not all riders. Predicted for October 2026 from Sep&ndash;Nov 2025 trips, routed over OpenStreetMap.</p>
  <fieldset>
    <legend>Show volumes for (AM = 07:00&ndash;10:00, PM = 16:00&ndash;19:00)</legend>
    <div class="seg" id="metric">
      <label><input type="radio" name="m" value="0" checked><span>October</span></label>
      <label><input type="radio" name="m" value="1"><span>Weekday AM</span></label>
      <label><input type="radio" name="m" value="2"><span>Weekday PM</span></label>
      <label><input type="radio" name="m" value="3"><span>Weekend</span></label>
    </div>
  </fieldset>
  <fieldset class="layers">
    <legend>Layers</legend>
    <label><input type="checkbox" data-layer="locations" checked><span class="key location"></span>Locations</label>
    <label><input type="checkbox" data-layer="crossings" checked><span class="key crossing"></span>Bike route crossing a busy street</label>
    <label><input type="checkbox" data-layer="crossroads" checked><span class="key crossroad"></span>Crossroads of many routes</label>
    <label><input type="checkbox" data-layer="stations" checked><span class="key station"></span>Mobi stations</label>
    <label><input type="checkbox" data-layer="flows" checked><span class="key flow"></span>Imputed Mobi trips (thicker = more)</label>
  </fieldset>
  <fieldset class="layers">
    <legend>Voting places</legend>
    <label><input type="checkbox" data-layer="advance" checked><span class="key voting"></span>Advance polling (Oct 13)</label>
    <label><input type="checkbox" data-layer="election_day"><span class="key voting"></span>Election day voting places</label>
    <label><span class="key buffer"></span>Keep-away distance around each shown place</label>
    <div class="seg" id="buffer">
      <label><input type="radio" name="b" value="0"><span>None</span></label>
      <label><input type="radio" name="b" value="100" checked><span>100 m</span></label>
      <label><input type="radio" name="b" value="200"><span>200 m</span></label>
    </div>
  </fieldset>
  <h2><span class="key location"></span>Locations</h2>
  <table id="t-locations"></table>
  <h2><span class="key crossing"></span>Busy-street crossings <span class="unit" data-unit="trips"></span></h2>
  <table id="t-crossings"></table>
  <h2><span class="key crossroad"></span>Crossroads <span class="unit" data-unit="trips"></span></h2>
  <table id="t-crossroads"></table>
  <h2><span class="key station"></span>Stations <span class="unit" data-unit="trip ends"></span></h2>
  <table id="t-stations"></table>
  <p class="note">Counts are Mobi bike-share trips only, a small sample of everyone cycling. Routes are modelled
  shortest bike-friendly paths, not GPS traces, so volumes pile onto the single best route more than real riders do.
  Weekday figures are trips per weekday inside the three-hour block; weekend figures are trips per whole weekend day.</p>
</div>
<script>
const DATA = __DATA__;
const UNITS = ["in October", "per weekday, 07:00–10:00", "per weekday, 16:00–19:00", "per weekend day"];
const fmt = v => v >= 100 ? Math.round(v).toLocaleString() : v >= 10 ? v.toFixed(0) : v.toFixed(1);
const map = L.map("map", { preferCanvas: true }).setView([49.2745, -123.122], 14);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19, className: "osm-tiles",
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(map);
["buffers", "flows", "stations", "crossroads", "crossings", "locations", "voting"].forEach((p, i) => { map.createPane(p).style.zIndex = 400 + i * 10; });
const canvas = L.canvas({ pane: "flows", tolerance: 6 });
const layers = { flows: L.layerGroup(), stations: L.layerGroup(), crossroads: L.layerGroup(), crossings: L.layerGroup(), locations: L.layerGroup(),
                 advance: L.layerGroup(), election_day: L.layerGroup() };
let metric = 0;

function tip(title, value, unit, detail) {
  const el = document.createElement("div"); el.className = "tip";
  const b = document.createElement("b"); b.textContent = value + " ";
  const u = document.createElement("small"); u.textContent = unit;
  const t = document.createElement("div"); t.textContent = title;
  el.append(b, u, t);
  if (detail) { const s = document.createElement("span"); s.textContent = detail; el.append(s); }
  return el;
}

const flowMax = [4, 5, 6, 7].map(i => Math.max(...DATA.segments.map(s => s[i])));
const flowLines = DATA.segments.map(s => {
  const line = L.polyline([[s[0], s[1]], [s[2], s[3]]], { renderer: canvas, color: "#eda100", opacity: 0.7, lineCap: "round" });
  line.bindTooltip(() => tip(s[8] || "Unnamed path", fmt(s[4 + metric]), "Mobi trips " + UNITS[metric]), { sticky: true });
  return line.addTo(layers.flows);
});

const KIND = { crossings: "crossing", crossroads: "crossroad", stations: "station" };
const NOUN = { crossings: "trips", crossroads: "trips", stations: "trip ends" };
const markers = {};
for (const key of Object.keys(KIND)) {
  markers[key] = DATA[key].map(d => {
    const m = L.marker(d.ll, { pane: key, keyboard: true, title: "" });
    m.bindTooltip(() => tip(d.name, fmt(d.v[metric]), NOUN[key] + " " + UNITS[metric], d.detail), { direction: "top" });
    m.d = d;
    return m.addTo(layers[key]);
  });
}

// rings 1.6x the radius of the largest icon (icons run 8-28 px across)
const RING = 1.6 * 28 / 2;
// each location is a ring with a crosshair; clicking it (or its table row) pops up the team
const ringRenderer = L.svg({ pane: "locations" });
DATA.locations.forEach((d, i) => {
  const pop = document.createElement("div"); pop.className = "pop";
  const title = document.createElement("b"); title.textContent = `Location ${i + 1}: ${d.name}`;
  const cand = document.createElement("div"); cand.textContent = "Candidates: " + d.candidates;
  const vol = document.createElement("div"); vol.textContent = "Volunteers: " + d.volunteers;
  pop.append(title, cand, vol);
  const ring = L.circleMarker(d.ll, { renderer: ringRenderer, radius: RING, color: "#d1242f", weight: 3, fill: true, fillOpacity: 0 })
    .bindPopup(pop).addTo(layers.locations);
  L.marker(d.ll, { pane: "locations", interactive: false, keyboard: false, icon: L.divIcon({ className: "xh", iconSize: [18, 18] }) }).addTo(layers.locations);
  const tr = document.getElementById("t-locations").insertRow();
  const r = tr.insertCell(); r.className = "r"; r.textContent = i + 1;
  const cell = tr.insertCell();
  const btn = document.createElement("button"); btn.textContent = d.name;
  btn.onclick = () => { if (!map.hasLayer(layers.locations)) toggle("locations", true); map.flyTo(d.ll, 17, { duration: 0.6 }); ring.openPopup(); };
  const team = document.createElement("div"); team.className = "team"; team.textContent = `${d.candidates} · ${d.volunteers}`;
  cell.append(btn, team);
});

function render() {
  DATA.segments.forEach((s, i) => {
    const v = s[4 + metric];
    flowLines[i].setStyle({ weight: v > 0 ? 0.5 + 8 * Math.sqrt(v / flowMax[metric]) : 0, opacity: v > 0 ? 0.6 : 0 });
  });
  for (const key of Object.keys(KIND)) {
    const max = Math.max(...DATA[key].map(d => d.v[metric]));
    const ranked = [...markers[key]].sort((a, b) => b.d.v[metric] - a.d.v[metric]);
    ranked.forEach((m, i) => {
      const size = Math.round(8 + 20 * Math.sqrt(m.d.v[metric] / max));
      const box = Math.max(24, size + 6);
      m.setIcon(L.divIcon({ className: "mk " + KIND[key], iconSize: [box, box],
        html: `<i style="width:${size}px;height:${size}px"></i>` }));
      m.setZIndexOffset(1000 - i);
    });
    const table = document.getElementById("t-" + key); table.replaceChildren();
    ranked.slice(0, 12).forEach((m, i) => {
      const tr = table.insertRow();
      const r = tr.insertCell(); r.className = "r"; r.textContent = i + 1;
      const btn = document.createElement("button"); btn.textContent = m.d.name;
      btn.onclick = () => { if (!map.hasLayer(layers[key])) toggle(key, true); map.flyTo(m.d.ll, 17, { duration: 0.6 }); m.openTooltip(); };
      tr.insertCell().append(btn);
      const n = tr.insertCell(); n.className = "n"; n.textContent = fmt(m.d.v[metric]);
    });
  }
  document.querySelectorAll("[data-unit]").forEach(el => { el.textContent = el.dataset.unit + " " + UNITS[metric]; });
}

// voting places: a marker per place, plus a grey keep-away disc whose radius follows the buffer
// control. Most places are in both lists, so discs are shared by place and drawn once.
const bufferRenderer = L.svg({ pane: "buffers" });
const discs = L.layerGroup().addTo(map);
const buffers = new Map();                       // place name -> { circle, lists }
let bufferMetres = 100;
for (const key of ["advance", "election_day"]) {
  DATA.voting[key].forEach(d => {
    const m = L.marker(d.ll, { pane: "voting", keyboard: true, title: "",
      icon: L.divIcon({ className: "mk voting", iconSize: [24, 24], html: "<i></i>" }) });
    m.bindTooltip(() => tip(d.name, key === "advance" ? "Advance polling (Oct 13)" : "Election day", "voting place", d.address), { direction: "top" });
    m.addTo(layers[key]);
    const b = buffers.get(d.name) || buffers.set(d.name, { lists: new Set(),
      circle: L.circle(d.ll, { renderer: bufferRenderer, radius: 100, stroke: false, fillColor: "#52514e", fillOpacity: 0.2, interactive: false }) }).get(d.name);
    b.lists.add(key);
  });
}
function updateBuffers() {
  buffers.forEach(b => {
    const show = bufferMetres > 0 && [...b.lists].some(k => map.hasLayer(layers[k]));
    if (show) { b.circle.setRadius(bufferMetres); b.circle.addTo(discs); } else { discs.removeLayer(b.circle); }
  });
}
document.getElementById("buffer").onchange = e => { bufferMetres = +e.target.value; updateBuffers(); };

function toggle(key, on) {
  on ? layers[key].addTo(map) : layers[key].remove();
  document.querySelector(`[data-layer="${key}"]`).checked = on;
  updateBuffers();
}
document.querySelectorAll("[data-layer]").forEach(cb => { toggle(cb.dataset.layer, cb.checked); cb.onchange = () => toggle(cb.dataset.layer, cb.checked); });
document.getElementById("metric").onchange = e => { metric = +e.target.value; render(); };
render();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
