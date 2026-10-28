"""Shared paths, definitions and loaders for the bike-share analyses."""
import csv
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ORIGINAL = DATA / "original_data"
OUT = ROOT / "analysis" / "output"
TRIPS_CLEAN = DATA / "trips_clean.csv"
STATIONS_CANONICAL = DATA / "stations_canonical.csv"

# Timestamps in the source data are rounded to the hour, so a block is defined by
# hour label and is fuzzy by up to an hour at each edge.
BLOCKS = [
    ("07:00-10:00", range(7, 10)),
    ("10:00-13:00", range(10, 13)),
    ("13:00-16:00", range(13, 16)),
    ("16:00-19:00", range(16, 19)),
    ("19:00-22:00", range(19, 22)),
    ("22:00-07:00", list(range(22, 24)) + list(range(0, 7))),
]
BLOCK_OF_HOUR = {h: name for name, hours in BLOCKS for h in hours}
BLOCK_NAMES = [name for name, _ in BLOCKS]
AM_COMMUTE, PM_COMMUTE = "07:00-10:00", "16:00-19:00"

MONTHS = ["2025-08", "2025-09", "2025-10", "2025-11", "2025-12", "2026-01",
          "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]

# Weights for predicting October 2026: the same month last year plus its two
# neighbours. Pooling Sep+Nov 2025 reproduces October 2025's trip pattern better
# than half of October predicts the other half; summer months are the worst match
# and spring months add nothing (similarity_check in october_forecast.py).
OCTOBER_WEIGHTS = {"2025-10": 2.0, "2025-09": 1.0, "2025-11": 1.0}
BASE_MONTH = "2025-10"  # the month whose overall volume sets the forecast level
OCT_2026_DAYS = {"weekday": 22, "weekend": 9}


def day_type(d):
    return "weekday" if d.weekday() < 5 else "weekend"


def days_in_month(month):
    """Number of weekdays and weekend days in a YYYY-MM month."""
    y, m = map(int, month.split("-"))
    d = date(y, m, 1)
    n = {"weekday": 0, "weekend": 0}
    while d.month == m:
        n[day_type(d)] += 1
        d += timedelta(days=1)
    return n


def load_stations():
    with open(STATIONS_CANONICAL, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["lat"] = float(r["lat"]); r["lon"] = float(r["lon"])
        r["active"] = r["active"] == "1"; r["ubc"] = r["ubc"] == "1"
    return {r["id"]: r for r in rows}


def load_trips():
    """Yield cleaned trips as dicts with parsed datetimes."""
    with open(TRIPS_CLEAN, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["dep"] = datetime.fromisoformat(r["departure"])
            r["ret"] = datetime.fromisoformat(r["return"])
            r["member"] = r["rider"] == "member"
            yield r


class Forecaster:
    """Predicts October 2026 per-day rates from monthly shares of total trips.

    A key's share of all trips is averaged over the weighted months, then scaled
    to October 2025's overall trips per day. Months before a station opened are
    left out of that station's average, and a station with no data in the
    weighted months falls back to the three most recent months it has.
    """

    def __init__(self, trips):
        from collections import Counter, defaultdict
        self.totals = defaultdict(Counter)            # month -> day type -> trips
        self.first, self.last = {}, {}
        self.trips = trips
        for t in trips:
            m = t["departure"][:7]
            self.totals[m][day_type(t["dep"])] += 1
            for s in (t["dep_id"], t["ret_id"]):
                self.first.setdefault(s, m)
                self.last[s] = m
        self.base_rate = {dt: self.totals[BASE_MONTH][dt] / days_in_month(BASE_MONTH)[dt]
                          for dt in ("weekday", "weekend")}

    def months_for(self, stations):
        """(months, fallback?) to average over for a key touching these stations."""
        lo = max(self.first[s] for s in stations)
        hi = min(self.last[s] for s in stations)
        ms = [m for m in OCTOBER_WEIGHTS if lo <= m <= hi]
        if ms:
            return ms, False
        return [m for m in MONTHS if lo <= m <= hi][-3:], True

    def rate(self, counts, dt, stations):
        """October per-day rate. counts: month -> count of this key on day type dt."""
        ms, fallback = self.months_for(stations)
        if not ms:
            return 0.0, True
        w = {m: OCTOBER_WEIGHTS.get(m, 1.0) for m in ms}
        share = sum(w[m] * counts.get(m, 0) / self.totals[m][dt] for m in ms) / sum(w.values())
        return share * self.base_rate[dt], fallback
