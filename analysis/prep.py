"""Build the cleaned trip table and canonical station table used by every analysis.

Reads the monthly source files (they carry distance and pass type, which
all_trips.csv does not) and writes data/trips_clean.csv and
data/stations_canonical.csv.
"""
import csv
import json
import re
from collections import Counter
from datetime import datetime

from common import DATA, MONTHS, ORIGINAL, STATIONS_CANONICAL, TRIPS_CLEAN

CASUAL = re.compile(r"pay as you go|(?<!365 )day pass|match day|hat trick", re.I)
UBC_LON = -123.225  # stations west of this are on the UBC campus, outside city limits


def parse_ts(s):
    d, t = s.strip().split(" ")
    p = t.split(":")
    return datetime.fromisoformat(f"{d} {int(p[0]):02d}:{p[1]}:00")


def main():
    # every raw station string -> station id, from the geocoded table
    name_to_id, coords = {}, {}
    with open(DATA / "stations.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["Station ID"] and r["Latitude"]:
                name_to_id[r["Station"]] = r["Station ID"]
                coords.setdefault(r["Station ID"], (float(r["Latitude"]), float(r["Longitude"])))

    feed = {s["station_id"]: s for s in json.load(open(ORIGINAL / "mobi_station_information.json"))["data"]["stations"]}
    status = {s["station_id"]: s for s in json.load(open(ORIGINAL / "mobi_station_status.json"))["data"]["stations"]}

    dropped, kept, rider_types = Counter(), 0, Counter()
    names = {}
    with open(TRIPS_CLEAN, "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out, lineterminator="\n")
        w.writerow(["departure", "return", "dep_id", "ret_id", "distance_m", "ebike", "rider", "duration_s"])
        for path in sorted(ORIGINAL.glob("*.csv")):
            with open(path, newline="", encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    pass_type = r.get("Membership type") or r.get("Formula") or ""
                    if "maintenance" in pass_type.lower():
                        dropped["maintenance"] += 1; continue
                    if not r["Departure"].strip() or not r["Return"].strip():
                        dropped["missing time"] += 1; continue
                    dep, ret = parse_ts(r["Departure"]), parse_ts(r["Return"])
                    if dep.strftime("%Y-%m") not in MONTHS:
                        dropped["outside Aug 2025-Jul 2026"] += 1; continue
                    if not 0 <= (ret - dep).total_seconds() <= 12 * 3600:
                        dropped["longer than 12 h"] += 1; continue
                    a, b = name_to_id.get(r["Departure station"]), name_to_id.get(r["Return station"])
                    if not a or not b:
                        dropped["blank or non-public station"] += 1; continue
                    dist = float(r["Covered distance (m)"] or 0)
                    if a == b and dist < 200:
                        dropped["false start (same station, <200 m)"] += 1; continue
                    rider = "casual" if CASUAL.search(pass_type) else "member"
                    rider_types[(rider, pass_type)] += 1
                    for sid, raw in ((a, r["Departure station"]), (b, r["Return station"])):
                        names.setdefault(sid, Counter())[raw] += 1
                    w.writerow([dep.isoformat(sep=" "), ret.isoformat(sep=" "), a, b, round(dist),
                                int(r["Electric bike"].upper() == "TRUE"), rider,
                                round(float(r["Duration (sec.)"] or 0))])
                    kept += 1

    with open(STATIONS_CANONICAL, "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out, lineterminator="\n")
        w.writerow(["id", "name", "lat", "lon", "active", "ubc"])
        for sid in sorted(names):
            if sid in feed:
                name, lat, lon = feed[sid]["name"], feed[sid]["lat"], feed[sid]["lon"]
            else:
                raw = names[sid].most_common(1)[0][0]
                name = re.sub(r"\s*-\s*Removed.*$", "", re.sub(r"^\d{4} ", "", raw.strip()))
                lat, lon = coords[sid]
            active = sid in status and status[sid]["is_installed"] and status[sid]["is_renting"]
            w.writerow([sid, name, f"{lat:.6f}", f"{lon:.6f}", int(bool(active)), int(lon < UBC_LON)])

    print(f"kept {kept:,} trips; dropped {sum(dropped.values()):,}")
    for k, v in dropped.most_common():
        print(f"  {v:8,}  {k}")
    print("pass types counted as casual:")
    for (rider, t), v in sorted(rider_types.items(), key=lambda kv: -kv[1]):
        if rider == "casual":
            print(f"  {v:8,}  {t}")
    print("member pass types:", sum(1 for (rd, _) in rider_types if rd == "member"),
          "types,", sum(v for (rd, _), v in rider_types.items() if rd == "member"), "trips")
    print([t for (rd, t) in rider_types if rd == "member"])
    inactive = [sid for sid in names if not (sid in status and status[sid]["is_renting"])]
    print("stations in trips but not renting today:", sorted(inactive))


if __name__ == "__main__":
    main()
