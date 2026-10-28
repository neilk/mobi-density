"""Most popular station + time-block combinations.

Counts trip ends (a departure or an arrival) at each station by day type and
three-hour block, and predicts the October 2026 daily rate for each.
Writes output/station_time_blocks.csv.
"""
import csv
from collections import Counter, defaultdict

from common import (AM_COMMUTE, BLOCK_OF_HOUR, PM_COMMUTE, MONTHS, OUT, Forecaster, day_type,
                    days_in_month, load_stations, load_trips)


def main():
    stations = load_stations()
    trips = list(load_trips())
    fc = Forecaster(trips)

    # (station, day type, block) -> month -> trip ends; arrivals use the return time
    ends = defaultdict(Counter)
    dep_n, arr_n, member_n = Counter(), Counter(), Counter()
    for t in trips:
        for sid, when, tally in ((t["dep_id"], t["dep"], dep_n), (t["ret_id"], t["ret"], arr_n)):
            key = (sid, day_type(when), BLOCK_OF_HOUR[when.hour])
            ends[key][when.strftime("%Y-%m")] += 1
            tally[key] += 1
            member_n[key] += t["member"]

    year_days = Counter()
    for m in MONTHS:
        year_days.update(days_in_month(m))

    rows = []
    for key, by_month in ends.items():
        sid, dt, block = key
        rate, fallback = fc.rate(by_month, dt, [sid])
        n = dep_n[key] + arr_n[key]
        s = stations[sid]
        note = "" if s["active"] else "not renting on 2026-10-04"
        if fallback:
            note = (note + "; " if note else "") + "new station, based on its latest months"
        rows.append({
            "station_id": sid, "station": s["name"], "day_type": dt, "block": block,
            "oct_trip_ends_per_day": round(rate, 1),
            "oct_departures_per_day": round(rate * dep_n[key] / n, 1),
            "oct_arrivals_per_day": round(rate * arr_n[key] / n, 1),
            "oct_member_trip_ends_per_day": round(rate * member_n[key] / n, 1),
            "member_share": round(member_n[key] / n, 2),
            "all_year_trip_ends_per_day": round(n / year_days[dt], 1),
            "at_ubc": int(s["ubc"]), "note": note,
        })
    rows.sort(key=lambda r: -r["oct_trip_ends_per_day"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    cols = ["rank"] + [c for c in rows[0] if c != "rank"]
    with open(OUT / "station_time_blocks.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader(); w.writerows(rows)

    print(f"{len(rows)} station/day-type/block combinations -> {OUT / 'station_time_blocks.csv'}")
    def show(title, keep, by, n=15):
        print(f"\n{title}  (October trip ends/day: all | by members)")
        for r in sorted((r for r in rows if keep(r) and not r["note"]), key=lambda r: -r[by])[:n]:
            print(f"  {r['oct_trip_ends_per_day']:6.1f} {r['oct_member_trip_ends_per_day']:6.1f}  "
                  f"{r['station_id']} {r['station']}{' [UBC]' if r['at_ubc'] else ''} | {r['day_type']} {r['block']}")

    wd = lambda block: (lambda r: r["day_type"] == "weekday" and r["block"] == block)
    show("Top 15 overall", lambda r: True, "oct_trip_ends_per_day")
    show("Top 25 by member trip ends", lambda r: True, "oct_member_trip_ends_per_day", 25)
    show("Top 15 weekday 07:00-10:00", wd(AM_COMMUTE), "oct_member_trip_ends_per_day")
    show("Top 15 weekday 16:00-19:00", wd(PM_COMMUTE), "oct_member_trip_ends_per_day")
    show("Top 10 weekend, by members", lambda r: r["day_type"] == "weekend", "oct_member_trip_ends_per_day", 10)

if __name__ == "__main__":
    main()
