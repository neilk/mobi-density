"""Build output/trip_types.html from output/trip_types.json (trip_types.py).

One page: the clusters k-means found in a year of Mobi trips, each with its
hour-of-day and month profiles against the whole year, its directness x speed
heatmap, and its composition. See trip-types.md.

    uv run python build_trip_types.py
"""
import json

from common import OUT


# Names for the clusters of a run, biggest cluster first; other k's are numbered on the page.
NAMES = {2: ["Getting there", "Out for a ride"]}


def render(data):
    names = json.dumps(NAMES.get(data["k"], [f"Type {i + 1}" for i in range(data["k"])]))
    return PAGE.replace("__NAMES__", names) \
               .replace("__DATA__", json.dumps(data, separators=(",", ":")).replace("</", "<\\/"))


def main():
    data = json.loads((OUT / "trip_types.json").read_text(encoding="utf-8"))
    path = OUT / "trip_types.html"
    path.write_text(render(data), encoding="utf-8")
    print(f"wrote {path}: {data['k']} clusters, {data['trips']:,} trips")


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Mobi trip types</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {
    color-scheme: light;
    --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
    --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,.10);
    --blue: #2a78d6; --gray: #c3c2b7;
    --seq-1: #cde2fb; --seq-2: #9ec5f4; --seq-3: #6da7ec; --seq-4: #3987e5; --seq-5: #256abf; --seq-6: #184f95; --seq-7: #0d366b;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      color-scheme: dark;
      --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
      --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,.10);
      --blue: #3987e5; --gray: #383835;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,.10);
    --blue: #3987e5; --gray: #383835;
  }
  html { background: var(--page); }
  body { margin: 0; padding: 24px 16px 48px; font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; color: var(--ink); background: var(--page); max-width: 1180px; margin-inline: auto; }
  h1 { font-size: 24px; margin: 0 0 4px; }
  h2 { font-size: 17px; margin: 36px 0 4px; }
  p.lede, p.note { color: var(--ink-2); margin: 0 0 12px; max-width: 72ch; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin: 16px 0; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }
  .card .name { font-weight: 600; display: flex; align-items: center; gap: 8px; }
  .card .swatch { width: 12px; height: 12px; border-radius: 3px; background: var(--blue); display: inline-block; }
  .card .big { font-size: 28px; line-height: 1.1; margin: 6px 0 2px; }
  .card .sub { color: var(--ink-2); font-size: 12px; }
  .card dl { display: grid; grid-template-columns: auto auto; gap: 2px 10px; margin: 10px 0 0; font-size: 12px; }
  .card dt { color: var(--muted); } .card dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; }
  .multiples { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
  .panel { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px 6px; }
  .panel h3 { font-size: 13px; font-weight: 600; margin: 0 0 2px; }
  .panel .sub { color: var(--muted); font-size: 11px; margin-bottom: 4px; }
  svg { display: block; width: 100%; height: auto; overflow: visible; }
  svg text { font: 11px system-ui, sans-serif; fill: var(--muted); }
  .gridline { stroke: var(--grid); stroke-width: 1; } .baseline { stroke: var(--axis); stroke-width: 1; }
  .legend { display: flex; gap: 16px; font-size: 12px; color: var(--ink-2); margin: 6px 0 10px; flex-wrap: wrap; }
  .legend span::before { content: ""; display: inline-block; width: 14px; height: 3px; border-radius: 2px; margin: 0 6px 3px 0; vertical-align: middle; }
  .legend .c::before { background: var(--blue); } .legend .o::before { background: var(--gray); }
  .legend .seq::before { height: 10px; width: 56px; background: linear-gradient(90deg, var(--seq-1), var(--seq-7)); }
  table { border-collapse: collapse; width: 100%; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; font-size: 13px; }
  th, td { padding: 6px 10px; text-align: right; border-top: 1px solid var(--grid); font-variant-numeric: tabular-nums; }
  th { color: var(--ink-2); font-weight: 600; border-top: 0; } th:first-child, td:first-child { text-align: left; }
  td.bar { padding: 6px 4px 6px 10px; min-width: 110px; }
  td.bar i { display: inline-block; height: 10px; background: var(--blue); border-radius: 0 4px 4px 0; vertical-align: middle; margin-right: 6px; }
  .tip { position: fixed; pointer-events: none; background: var(--surface); color: var(--ink); border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; font-size: 12px; box-shadow: 0 2px 8px rgba(0,0,0,.18); display: none; z-index: 2; white-space: nowrap; }
  .hit { fill: transparent; }
</style></head>
<body>
<h1>Mobi trip types</h1>
<p class="lede" id="lede"></p>
<div class="cards" id="cards"></div>

<h2>Composition</h2>
<p class="note">Who rides each type and how. Scenic is the share of a 300 m disc around the station that is waterfront, park or beach; "leisure" is the share of trips scoring 4+ points on the transit explorer's heuristic (round trip +3, waterfront end +2, over 40 min +2 or over 20 min +1, weekend +1, midday +1, detour above 1.8x +1).</p>
<div id="composition"></div>

<h2>Time of day</h2>
<p class="note">Share of the cluster's trips leaving in each hour, against the whole year in gray. Timestamps are rounded to the hour at source.</p>
<div class="legend"><span class="c">this cluster</span><span class="o">all trips</span></div>
<div class="multiples" id="hours"></div>

<h2>Season</h2>
<p class="note">Share of the cluster's trips in each month, against the whole year in gray. Months are kept out of the clustering, so a cluster that leans on summer does so because of how its rides look.</p>
<div class="legend"><span class="c">this cluster</span><span class="o">all trips</span></div>
<div class="multiples" id="months"></div>

<h2>Directness and speed</h2>
<p class="note">Each cell is the share of the cluster's trips with that directness (straight line between stations over odometer, 0 for round trips) and average speed. Darker is more trips.</p>
<div class="legend"><span class="seq">fewer &rarr; more trips</span></div>
<div class="multiples" id="directness"></div>

<h2>How many types</h2>
<p class="note">Silhouette of each candidate k on a 20,000-trip sample: how much closer trips sit to their own cluster than to the next one. The k used is the highest.</p>
<div class="panel" id="selection" style="max-width: 420px"></div>
<div class="tip" id="tip"></div>

<script>
const DATA = __DATA__;
const SEQ = ["--seq-1","--seq-2","--seq-3","--seq-4","--seq-5","--seq-6","--seq-7"].map(v => `var(${v})`);
const fmt = (x, d = 0) => x.toLocaleString("en-CA", {maximumFractionDigits: d, minimumFractionDigits: d});
const pct = x => fmt(100 * x) + "%";
const tip = document.getElementById("tip");
function showTip(e, html) { tip.innerHTML = html; tip.style.display = "block"; moveTip(e); }
function moveTip(e) { tip.style.left = (e.clientX + 14) + "px"; tip.style.top = (e.clientY + 14) + "px"; }
function hideTip() { tip.style.display = "none"; }
function tag(c) {
  const m = c.median;
  return `${fmt(m.distance_m / 1000, 1)} km · ${fmt(m.duration_s / 60)} min · ${fmt(m.speed_kmh, 1)} km/h · directness ${fmt(m.directness, 2)}`;
}
const NAMES = __NAMES__;
const names = DATA.clusters.map((c, i) => NAMES[i]);

document.getElementById("lede").textContent =
  `${fmt(DATA.trips)} trips from August 2025 to July 2026 with usable telemetry, clustered into ${DATA.k} types by k-means on ` +
  `log distance, log duration, directness, scenic score of both stations, hour of day and weekend. Rider type, e-bike and month are not ` +
  `clustering inputs. ${fmt(Object.values(DATA.excluded).reduce((a, b) => a + b, 0))} trips were excluded for bad telemetry.`;

document.getElementById("cards").innerHTML = DATA.clusters.map((c, i) => `
  <div class="card"><div class="name"><span class="swatch"></span>${names[i]}</div>
  <div class="big">${pct(c.share)}</div><div class="sub">${fmt(c.n)} trips</div>
  <dl><dt>median length</dt><dd>${fmt(c.median.distance_m / 1000, 1)} km</dd>
      <dt>median time</dt><dd>${fmt(c.median.duration_s / 60)} min</dd>
      <dt>median speed</dt><dd>${fmt(c.median.speed_kmh, 1)} km/h</dd>
      <dt>median directness</dt><dd>${fmt(c.median.directness, 2)}</dd>
      <dt>round trips</dt><dd>${pct(c.round_share)}</dd>
      <dt>scenic start / end</dt><dd>${fmt(c.mean.scenic_dep, 2)} / ${fmt(c.mean.scenic_ret, 2)}</dd></dl></div>`).join("");

// composition table with inline bars
const cols = [["casual_share", "casual riders"], ["weekend_share", "weekend"], ["round_share", "round trip"],
              ["ebike_share", "e-bike"], ["leisure_share", "leisure (heuristic)"]];
document.getElementById("composition").innerHTML = `<table><thead><tr><th>type</th>${cols.map(c => `<th>${c[1]}</th>`).join("")}<th>top start station</th></tr></thead><tbody>` +
  DATA.clusters.map((c, i) => `<tr><td>${names[i]}<br><span class="sub" style="color:var(--muted);font-size:11px">${tag(c)}</span></td>` +
    cols.map(([k]) => `<td class="bar"><i style="width:${Math.round(60 * c[k])}px"></i>${pct(c[k])}</td>`).join("") +
    `<td style="text-align:left">${c.top_dep.map(s => `${s.name} (${pct(s.n / c.n)})`).slice(0, 2).join("<br>")}</td></tr>`).join("") +
  `<tr><td>all trips</td>${cols.map(([k]) => `<td class="bar"><i style="width:${Math.round(60 * DATA.overall[k])}px"></i>${pct(DATA.overall[k])}</td>`).join("")}<td></td></tr></tbody></table>`;

// shared small-multiple profile: cluster share per bin (bars) vs overall (gray bars behind)
function profilePanel(title, sub, labels, mine, all, tipFn) {
  const W = 300, H = 120, L = 28, B = 18, T = 6;
  const n = labels.length, bw = (W - L) / n;
  const ymax = Math.max(...mine, ...all) * 1.05 || 1;
  const y = v => T + (H - B - T) * (1 - v / ymax);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${title}">`;
  for (const g of [0.5, 1]) {
    const v = ymax * g;
    s += `<line class="gridline" x1="${L}" x2="${W}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 4}" y="${y(v) + 4}" text-anchor="end">${fmt(100 * v, v < .05 ? 1 : 0)}%</text>`;
  }
  for (let i = 0; i < n; i++) {
    const x = L + i * bw;
    s += `<rect x="${x + 1}" y="${y(all[i])}" width="${Math.max(1, bw - 2)}" height="${H - B - y(all[i])}" fill="var(--gray)" rx="2"/>`;
    s += `<rect x="${x + bw * 0.3}" y="${y(mine[i])}" width="${Math.max(1, bw * 0.4)}" height="${H - B - y(mine[i])}" fill="var(--blue)" rx="2"/>`;
    s += `<rect class="hit" x="${x}" y="${T}" width="${bw}" height="${H - B - T}" data-i="${i}"/>`;
    if (labels[i] !== "") s += `<text x="${x + bw / 2}" y="${H - 4}" text-anchor="middle">${labels[i]}</text>`;
  }
  s += `<line class="baseline" x1="${L}" x2="${W}" y1="${H - B}" y2="${H - B}"/></svg>`;
  const div = document.createElement("div");
  div.className = "panel";
  div.innerHTML = `<h3>${title}</h3><div class="sub">${sub}</div>${s}`;
  div.querySelectorAll(".hit").forEach(r => {
    r.addEventListener("mouseenter", e => showTip(e, tipFn(+r.dataset.i)));
    r.addEventListener("mousemove", moveTip);
    r.addEventListener("mouseleave", hideTip);
  });
  return div;
}
const share = (hist, n) => hist.map(v => v / n);
const hourLabels = [...Array(24).keys()].map(h => h % 3 ? "" : String(h));
const allHours = share(DATA.overall.hours, DATA.overall.n);
const monthKeys = Object.keys(DATA.overall.months);
const monthLabels = monthKeys.map(m => "JFMAMJJASOND"[+m.slice(5) - 1]);
const allMonths = share(monthKeys.map(m => DATA.overall.months[m]), DATA.overall.n);
DATA.clusters.forEach((c, i) => {
  const mine = share(c.hours, c.n);
  document.getElementById("hours").appendChild(profilePanel(names[i], tag(c), hourLabels, mine, allHours,
    h => `<b>${h}:00</b><br>${names[i]}: ${pct(mine[h])}<br>all trips: ${pct(allHours[h])}`));
  const mm = share(monthKeys.map(m => c.months[m] || 0), c.n);
  document.getElementById("months").appendChild(profilePanel(names[i], `${pct(c.weekend_share)} weekend`, monthLabels, mm, allMonths,
    j => `<b>${monthKeys[j]}</b><br>${names[i]}: ${pct(mm[j])}<br>all trips: ${pct(allMonths[j])}`));
});

// directness x speed heatmaps
DATA.hist2d.forEach((grid, ci) => {
  const c = DATA.clusters[ci];
  const W = 300, H = 180, L = 30, B = 20, T = 4;
  const nx = 15, ny = 20, cw = (W - L) / nx, ch = (H - B - T) / ny;
  const max = Math.max(...grid.flat()) / c.n || 1;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${names[ci]} directness by speed">`;
  for (let i = 0; i < ny; i++) for (let j = 0; j < nx; j++) {
    const v = grid[i][j] / c.n;
    if (v < max * 0.02) continue;                       // below 2% of the peak cell: leave the surface
    const step = Math.min(6, Math.floor(7 * Math.sqrt(v / max)));
    s += `<rect class="cell" x="${L + j * cw + 1}" y="${T + (ny - 1 - i) * ch + 1}" width="${cw - 2}" height="${ch - 2}" rx="1" fill="${SEQ[step]}" data-i="${i}" data-j="${j}"/>`;
  }
  for (const d of [0, 0.5, 1]) s += `<text x="${L - 4}" y="${T + (1 - d) * (H - B - T) + 4}" text-anchor="end">${d}</text>`;
  for (const v of [0, 10, 20]) s += `<text x="${L + v / 2 * cw}" y="${H - 5}" text-anchor="middle">${v}</text>`;
  s += `<text x="${W}" y="${H - 5}" text-anchor="end">km/h</text>`;
  s += `<text transform="translate(8 ${(H - B) / 2}) rotate(-90)" text-anchor="middle">directness</text></svg>`;
  const div = document.createElement("div");
  div.className = "panel";
  div.innerHTML = `<h3>${names[ci]}</h3><div class="sub">${tag(c)}</div>${s}`;
  div.querySelectorAll(".cell").forEach(r => {
    r.addEventListener("mouseenter", e => { const i = +r.dataset.i, j = +r.dataset.j;
      showTip(e, `directness ${fmt(i / 20, 2)}–${fmt((i + 1) / 20, 2)}, ${j * 2}–${j * 2 + 2} km/h<br>${pct(grid[i][j] / c.n)} of ${names[ci]} (${fmt(grid[i][j])} trips)`); });
    r.addEventListener("mousemove", moveTip);
    r.addEventListener("mouseleave", hideTip);
  });
  document.getElementById("directness").appendChild(div);
});

// silhouette by k
{
  const sel = DATA.selection, W = 400, H = 140, L = 34, B = 20, T = 8;
  const ymax = Math.max(...sel.map(s => s.silhouette)) * 1.15 || 1;
  const bw = (W - L) / sel.length;
  const y = v => T + (H - B - T) * (1 - v / ymax);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="silhouette by k">`;
  sel.forEach((p, i) => {
    const x = L + i * bw + bw * 0.3;
    s += `<rect x="${x}" y="${y(p.silhouette)}" width="${bw * 0.4}" height="${H - B - y(p.silhouette)}" fill="${p.k === DATA.k ? "var(--blue)" : "var(--gray)"}" rx="2"/>`;
    s += `<text x="${L + i * bw + bw / 2}" y="${H - 5}" text-anchor="middle">k=${p.k}</text>`;
    s += `<text x="${L + i * bw + bw / 2}" y="${y(p.silhouette) - 4}" text-anchor="middle" fill="var(--ink-2)">${fmt(p.silhouette, 2)}</text>`;
  });
  s += `<line class="baseline" x1="${L}" x2="${W}" y1="${H - B}" y2="${H - B}"/></svg>`;
  document.getElementById("selection").innerHTML = `<h3>Silhouette by k</h3>${s}`;
}
</script>
</body></html>
"""

if __name__ == "__main__":
    main()
