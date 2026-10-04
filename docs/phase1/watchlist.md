# Phase 1: Generated watchlist

The collector's watchlist (which trains to collect) is generated from RailKit timetable data and the corridor
definition in [`config/corridors.yaml`](../../config/corridors.yaml), replacing the 7-train Phase 0 seed.
Code: [`src/patribot/watchlist/`](../../src/patribot/watchlist) and
[`src/patribot/sources/railkit_timetable.py`](../../src/patribot/sources/railkit_timetable.py).

**Where it lives:** the output is RailKit-derived, so it is never committed to this public repo (D15). The
`watchlist` workflow in the private `patribot-data` repo builds it weekly and commits `watchlist.yaml` at that repo's
root. The `collect` workflow uses that file when it exists, and `config/watchlist.yaml` (the seed) otherwise.

## Algorithm
1. **Discovery (about 80 calls).** Fetch the station timetable (`GET /api/v1/stations/{code}/timetable`, no date, so
   it lists all trains with their running days) at every unique waypoint and end-cluster station. If a station's
   request fails, fall back to between-stations searches (`GET /api/v1/trains/between/{a}/{b}`) with its neighbouring
   waypoints, in both directions.
2. **Pre-filter (free).** Drop trains that are not reserved (below). Keep a train as a **candidate** only if it was
   listed at stations covering at least 2 distinct positions of some corridor path. Premium trains come first.
3. **Schedules (1 call per candidate).** `GET /api/v1/trains/{no}/info` gives the route with halts, cumulative
   distance, times, running days and train type.
4. **Membership (pure, [`membership.py`](../../src/patribot/watchlist/membership.py)).** A train is a member of a
   corridor path if its route **halts** at two stations of the path that are ≥ `min_consecutive_segments` (2)
   waypoint segments apart **or** ≥ `min_km` (150) apart by route distance, in either direction. Path stations are
   the waypoints, plus every station of the two end clusters, which count as the first or last waypoint. Trains can
   start or end anywhere: on the path or beyond it. A station passed without stopping does not count, so a train
   with only one halt on the path is not a member. A train is a member of a corridor if it is a member of any of its
   paths, and appears once in the watchlist with all its corridors.
5. **Tiering.** Tier **A** = serves both end clusters of one of its corridors, or a premium train (Rajdhani,
   Shatabdi, Duronto, Vande Bharat, Tejas, Humsafar, matched on type or name including common abbreviations such as
   SHTBDI). Everything else is tier **B**.
6. **Collector fields.** `dep_time` = departure from origin; `journey_minutes` = `travel_time`, else derived from the
   route's first departure and last arrival and day numbers; `run_days` = running days at origin (daily if unknown,
   counted in the report).

### Reserved-train filter (BRD §5.3)
Applied to discovery data and again to the schedule:
- **Number:** 3xxxx / 4xxxx / 9xxxx suburban (Kolkata / Chennai / Mumbai), 5xxxx passenger, 6xxxx MEMU,
  7xxxx DEMU and railcar. 0xxxx specials are excluded too, being temporary and often unreserved (`--include-specials`
  keeps them).
- **Type:** contains any of `membership.exclude_train_types` (MEMU, DEMU, EMU, PASSENGER, UNRESERVED), or SUBURBAN,
  LOCAL, PASS.
- **Name:** MEMU, DEMU, EMU, PASSENGER, PASS, ANTYODAYA, JAN SADHARAN, UNRESERVED, SUBURBAN.
- **Classes** (station timetable): only unreserved classes listed (GEN, GN, UR, GS, II).

## Call budget
| Item | Calls |
|---|---|
| Discovery: station timetables (cached 6 days) | ~80 per run |
| Schedules: candidates (cached 21–28 days, expiry spread per train) | first run ~1,000–1,500; afterwards about a quarter per week |
| **Monthly, weekly runs** | **~1,500–2,000** (≈ the "timetable refresh" line in architecture §4.2) |

- `--max-calls` (default 2,500) stops the run **before** it sends more requests. A stopped run exits 1, writes the
  report but not the watchlist (unless `--allow-partial`), and the cache lets the next run resume where it stopped.
- HTTP 401/403/429 stops the run immediately as well.
- These calls come out of the same RailKit quota as the collector. On the Advance plan alone (10k), lower
  `max_calls_per_month` in the data repo's `watchlist.yaml` accordingly.
- The report gives `estimated_collection_calls_per_month` (Σ runs/week × 30/7 per tier). If it exceeds
  `max_calls_per_month`, the collector samples tier B, as designed.

## How to run
In the data repo: **Actions → watchlist → Run workflow** (optionally set `max_calls`). It also runs every Sunday at
20:41 UTC and commits `watchlist.yaml`, `state/watchlist-report.json` and `state/timetable-cache/`.

Locally (output is RailKit data: do not commit it here; `/watchlist.yaml` and `.watchlist-cache/` are git-ignored):
```bash
RAIL_API_KEY=... uv run patribot-watchlist build --source railkit --corridors config/corridors.yaml \
  --base-watchlist config/watchlist.yaml --out watchlist.yaml --report watchlist-report.json [--max-calls 2500]
```
The `collector:` block is copied from `--base-watchlist`; the workflow passes the data repo's own `watchlist.yaml`,
so budget settings edited there survive rebuilds.

## To confirm with a real key
The adapter was built from the provider's documented examples without network access to RailKit; parsers are
tolerant of alternative key names. Check the first report and a few cached responses for:
1. **Running-days order.** The 7-character string (e.g. `"1111100"`) is assumed to start with **Monday**. If it starts
   with Sunday, set the data-repo Actions variable `RAIL_RUN_DAYS_ORDER=sun` (CLI `--run-days-order sun`).
2. **Pass-through stations in `route`.** Assumed to list stopping stations only. An intermediate row with a zero
   halt is treated as passing through.
3. **Station timetable without a date** lists all trains with `runningDays`. The documented example shows an empty
   `runningDays`; the schedule's `running_days` is used first anyway.
4. **Train `type` values** for MEMU/DEMU/passenger trains, and whether `classes` appears for unreserved trains.
5. `stations_with_no_trains` in the report: a waypoint with no trains usually means a wrong station code in
   `config/corridors.yaml` (all corridors are still `verified: false`).
