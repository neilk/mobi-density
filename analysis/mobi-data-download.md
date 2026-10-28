# Re-downloading the Mobi data

How `data/original_data/` was obtained and how to refresh it. Everything the
analysis reads lives there (see `README.md`); it is committed byte-for-byte
(`.gitattributes`), so a re-download can be diffed against git.

## What is in `data/original_data/`

| Files | Source | Notes |
|---|---|---|
| `Mobi_System_Data_2025-08.csv` … `2026-03.csv` | Mobi monthly trip exports | older column layout (below) |
| `public-trips-3.0-2026-04.csv` … `2026-07.csv` | Mobi monthly trip exports | newer column layout (below) |
| `mobi_station_information.json`, `mobi_station_status.json` | Mobi's live GBFS 2.2 feed | snapshots from early Oct 2026 |

The period covered is Aug 2025 – Jul 2026 (`MONTHS` in `common.py`).

## 1. Monthly trip CSVs

**Where:** <https://www.mobibikes.ca/en/system-data>. One link per month, newest
first, each pointing at a Google Drive file (`drive.google.com/file/d/<id>/view`).
A few older months are Google Sheets links instead (Feb 2024, Oct 2022); 2017 is
a single "ALL of 2017" file. Mobi says it uploads "on an ongoing basis"; the
July 2026 file was created on Drive on 2026-08-06 and modified 2026-08-24, so
the latest month appears roughly a week after month end and **may be revised
afterwards**. Re-fetch a month if it matters and compare sizes.

**How:**

1. Open the system-data page and note the Drive link for each month wanted.
2. Open each link in a normal browser and use the download button (the files
   are public; no sign-in is needed). Each is about 8–25 MB.
3. Save into `data/original_data/`. The folder holds both naming schemes
   (`Mobi_System_Data_YYYY-MM.csv`, `public-trips-3.0-YYYY-MM.csv`); the
   loader globs `*.csv`, so any name ending `.csv` works. Keep the
   `YYYY-MM` in the name for your own sanity.
4. Check the size against Drive's own figure if you want certainty: the
   Drive file metadata `fileSize` for July 2026 was 25,163,619 bytes, which
   matches the local file.

**What did not work when this was first set up**, so you don't repeat it:

- Fetching from a sandboxed/cloud shell: the egress proxy returned 403 for
  `drive.google.com`.
- Driving the download button from an automated browser pane: Drive opens the
  actual download in a new tab (`drive.usercontent.google.com`), which an
  automated session cannot open; a human click is needed.
- The Drive connector can read metadata, but the files are too large to pull
  through chat.

Untested ideas for scripting it from your own machine: `curl -L` against
`https://drive.google.com/uc?export=download&id=<id>` (large files may need
a confirm token), or `gdown`. Verify the result is CSV, not an HTML interstitial
(`head -c 200 file.csv`).

### Column layouts

Older (`Mobi_System_Data_*`): UTF-8 with BOM.
`Departure, Return, Bike, Electric bike, Departure station, Return station,
Membership type, Covered distance (m), Duration (sec.), Departure temperature (°C),
Return temperature (°C), Stopover duration (sec.), Number of stopovers`

Newer (`public-trips-3.0-*`): no BOM.
`Departure, Return, Bike, Electric bike, Departure station, Return station,
Formula, Covered distance (m), Duration (sec.), Lock duration (sec.),
Number of bike locks, Departure temperature (°C), Return temperature (°C)`

Differences `prep.py` already absorbs: `Membership type` vs `Formula`;
`Electric bike` as `TRUE`/`FALSE` vs `True`/`False`; timestamps with or without
seconds (Aug 2025 has `HH:MM`); BOM (read with `utf-8-sig`). If Mobi changes the
layout again (the "3.0" suggests it might), compare headers first.

### Data notes from Mobi

- Departure and return times are rounded to the nearest hour.
- Accounts are anonymised; operations (rebalancing/maintenance) trips are removed.
- A "stopover"/"lock" is a bike locked with its cable lock rather than at a
  station; the timer keeps running.
- Use is governed by Mobi's Data License Agreement (linked at the bottom of the
  system-data page). Check it before publishing anything derived from the data.

## 2. Station feeds (GBFS)

`mobi_station_information.json` (names, ids, lat/lon, capacity) and
`mobi_station_status.json` (installed/renting/returning, bikes available) are
GBFS 2.2 snapshots (`"version":"2.2"`, `"ttl":60`). `prep.py` uses them for
canonical station names and coordinates and for the `active` flag in
`stations_canonical.csv`.

**The feed URL was not recorded when these were fetched**, and I could not
verify it from here. To refresh: find Mobi's GBFS auto-discovery (`gbfs.json`)
URL (the MobilityData GBFS catalogue, <https://github.com/MobilityData/gbfs>
`systems.csv`, lists it under Vancouver / Mobi), then download
`station_information` and `station_status` from the links inside it.
**Please write the URL here once confirmed:** `TODO`.

Status is a point-in-time snapshot, so a refresh changes which stations count as
active.

## 3. After downloading

1. Add the new months to `MONTHS` in `analysis/common.py`. `prep.py` silently
   drops any trip whose departure month is not in that list.
2. If you are forecasting a different month, revisit `OCTOBER_WEIGHTS`,
   `BASE_MONTH` and `OCT_2026_DAYS` in `common.py`.
3. New stations: `prep.py` maps raw station strings to ids through
   `data/stations.csv` and drops trips at unknown or non-public stations
   ("blank or non-public station"). Add new name variants to `stations.csv`
   (geocoded) or the trips vanish.
4. Rebuild and sanity-check (see `README.md`):
   ```sh
   cd analysis
   uv run python prep.py
   ```
   Read the dropped-row counts (maintenance, missing time, longer than 12 h,
   false starts, unknown stations). A jump in any of them after adding a
   month means a format or station change.
5. Run the rest of the pipeline and commit `data/original_data/` plus the
   regenerated `analysis/output/`.

Trips can start in an earlier month than their file (e.g. the April 2026 file
contains a trip departing 2026-03-17); the month filter uses departure date, so
overlap between adjacent files is handled by that filter, but spot-check for
duplicates if you add files covering the same period twice.
