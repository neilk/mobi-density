"""Predict the most popular trips (station pairs) for October 2026.

Each pair's share of trips in Sep-Nov 2025 is scaled to October 2025's overall
volume; summer months are left out. Writes output/october_trips_forecast.csv.
Run with --similarity to print the month-vs-October comparison behind that choice.
"""
import csv
import sys
from collections import Counter, defaultdict
from math import sqrt

from common import (AM_COMMUTE, BLOCK_OF_HOUR, MONTHS, OCT_2026_DAYS, OUT, PM_COMMUTE,
                    Forecaster, day_type, load_stations, load_trips)


def pair_forecast(trips, fc, stations):
    """One row per directed station pair with predicted October 2026 volumes."""
    by_month = defaultdict(lambda: defaultdict(Counter))   # pair -> day type -> month -> trips
    n, member, oct25 = Counter(), Counter(), Counter()
    we_n, we_member = Counter(), Counter()
    block = defaultdict(Counter)                           # pair -> weekday block -> trips
    for t in trips:
        pair, dt, m = (t["dep_id"], t["ret_id"]), day_type(t["dep"]), t["departure"][:7]
        by_month[pair][dt][m] += 1
        if m == "2025-10":
            oct25[pair] += 1
        if m in fc.months_for(pair)[0]:
            n[pair] += 1
            member[pair] += t["member"]
            if dt == "weekday":
                block[pair][BLOCK_OF_HOUR[t["dep"].hour]] += 1
            else:
                we_n[pair] += 1
                we_member[pair] += t["member"]

    rows = []
    for pair, counts in by_month.items():
        a, b = stations[pair[0]], stations[pair[1]]
        wd, fallback = fc.rate(counts["weekday"], "weekday", pair)
        we, _ = fc.rate(counts["weekend"], "weekend", pair)
        total = wd * OCT_2026_DAYS["weekday"] + we * OCT_2026_DAYS["weekend"]
        if total == 0:
            continue
        wd_n = sum(block[pair].values())
        peak, peak_n = block[pair].most_common(1)[0] if wd_n else ("", 0)
        notes = [f"{s['name']} not renting on 2026-10-04" for s in {a["id"]: a, b["id"]: b}.values() if not s["active"]]
        if fallback:
            notes.append("new station, based on its latest months")
        rows.append({
            "from_id": a["id"], "from": a["name"], "to_id": b["id"], "to": b["name"],
            "oct_2026_trips": total, "per_weekday": wd, "per_weekend_day": we,
            "weekday_am_commute": wd * block[pair][AM_COMMUTE] / wd_n if wd_n else 0.0,
            "weekday_pm_commute": wd * block[pair][PM_COMMUTE] / wd_n if wd_n else 0.0,
            "member_share": member[pair] / n[pair] if n[pair] else 0.0,
            "weekend_member_share": we_member[pair] / we_n[pair] if we_n[pair] else 0.0,
            "busiest_weekday_block": peak, "busiest_block_share": peak_n / wd_n if wd_n else 0.0,
            "oct_2025_actual": oct25[pair], "round_trip": int(a["id"] == b["id"]),
            "at_ubc": int(a["ubc"] or b["ubc"]), "note": "; ".join(notes),
        })
    rows.sort(key=lambda r: -r["oct_2026_trips"])
    return rows


def similarity(trips):
    """How well each month's pair pattern matches October 2025 (cosine, top-200 overlap)."""
    pair, half = defaultdict(Counter), defaultdict(Counter)
    for t in trips:
        k = (t["dep_id"], t["ret_id"])
        pair[t["departure"][:7]][k] += 1
        if t["departure"][:7] == "2025-10":
            half[t["dep"].day % 2][k] += 1
    cos = lambda a, b: sum(v * b.get(k, 0) for k, v in a.items()) / sqrt(sum(v * v for v in a.values()) * sum(v * v for v in b.values()))
    top = lambda a, b: len({k for k, _ in a.most_common(200)} & {k for k, _ in b.most_common(200)}) / 200
    share = lambda ms: Counter({k: sum(pair[m][k] / sum(pair[m].values()) for m in ms) for m in ms for k in pair[m]})
    octo = pair["2025-10"]
    print("month     trips   cosine  top-200 overlap with Oct 2025")
    for m in MONTHS:
        print(f"{m}  {sum(pair[m].values()):7,}  {cos(pair[m], octo):.3f}   {top(pair[m], octo):.0%}")
    print(f"Oct 2025 odd vs even days  {cos(half[0], half[1]):.3f}   {top(half[0], half[1]):.0%}   (noise ceiling for half a month)")
    for label, ms in (("Sep+Nov 2025", ["2025-09", "2025-11"]), ("Jun+Jul 2026 + Aug 2025", ["2026-06", "2026-07", "2025-08"]),
                      ("Dec-Feb", ["2025-12", "2026-01", "2026-02"]), ("Mar-May 2026", ["2026-03", "2026-04", "2026-05"])):
        s = share(ms)
        print(f"{label:25s}  {cos(s, octo):.3f}   {top(s, octo):.0%}")


def main():
    stations = load_stations()
    trips = list(load_trips())
    if "--similarity" in sys.argv:
        return similarity(trips)
    fc = Forecaster(trips)
    rows = pair_forecast(trips, fc, stations)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    cols = ["rank"] + [c for c in rows[0] if c != "rank"]
    fmt = lambda v: round(v, 2) if isinstance(v, float) else v
    with open(OUT / "october_trips_forecast.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows({k: fmt(v) for k, v in r.items()} for r in rows)

    total = sum(r["oct_2026_trips"] for r in rows)
    print(f"{len(rows):,} pairs, {total:,.0f} predicted trips -> {OUT / 'october_trips_forecast.csv'}")
    print(f"base rate: {fc.base_rate['weekday']:.0f} trips/weekday, {fc.base_rate['weekend']:.0f} trips/weekend day")

    def show(title, keep, by="oct_2026_trips", n=20):
        print(f"\n{title}  (Oct trips | per weekday | per weekend day | member share | Oct 2025 actual)")
        for r in sorted((r for r in rows if keep(r)), key=lambda r: -r[by])[:n]:
            print(f"  {r['oct_2026_trips']:5.0f} {r['per_weekday']:5.1f} {r['per_weekend_day']:5.1f}  {r['member_share']:4.0%} {r['oct_2025_actual']:4d}  "
                  f"{r['from']} -> {r['to']}{' [UBC]' if r['at_ubc'] else ''}  {r['busiest_weekday_block']} {r['note']}")

    show("Top 20 trips", lambda r: True)
    show("Top 20 one-way trips within the city", lambda r: not r["round_trip"] and not r["at_ubc"])
    show("Top 20 one-way trips within the city, mostly members", lambda r: not r["round_trip"] and not r["at_ubc"] and r["member_share"] >= 0.6)
    show("Top 10 weekday AM commute trips", lambda r: not r["round_trip"], by="weekday_am_commute", n=10)
    show("Top 10 weekday PM commute trips", lambda r: not r["round_trip"], by="weekday_pm_commute", n=10)
    show("Top 15 weekend trips", lambda r: True, by="per_weekend_day", n=15)
    show("Top 15 weekend one-way trips in the city, mostly members on weekends",
         lambda r: not r["round_trip"] and not r["at_ubc"] and r["weekend_member_share"] >= 0.6, by="per_weekend_day", n=15)
    print("\nshare of predicted trips: round trips {:.1%}, touching UBC {:.1%}, touching a station not renting today {:.1%}".format(
        sum(r["oct_2026_trips"] for r in rows if r["round_trip"]) / total,
        sum(r["oct_2026_trips"] for r in rows if r["at_ubc"]) / total,
        sum(r["oct_2026_trips"] for r in rows if "not renting" in r["note"]) / total))
    for n in (100, 500, 2000):
        print(f"top {n} pairs carry {sum(r['oct_2026_trips'] for r in rows[:n]) / total:.0%} of predicted trips")


if __name__ == "__main__":
    main()
