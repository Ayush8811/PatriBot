# Phase 2: Planner and API

The deterministic itinerary planner (architecture doc [§7](../02-solution-architecture.md#7-planner-engine-deterministic))
and the FastAPI service that serves it. The HTTP contract is [docs/api/v1.md](../api/v1.md); this page explains how
the answers are computed and how to run it.

```
gold tables (DuckDB warehouse, or Postgres schema serving)
   │  patribot.planner.repository   DuckDBRepository | PostgresRepository → PlannerData snapshot (in memory)
   ▼
patribot.planner  places (FR-2) → search (FR-5..FR-7) → eta baseline_hist (FR-10, FR-12, FR-13) → rank (FR-9)
   ▼
patribot.api      FastAPI /api/v1: health, places/search, plan, trains/{no}, trains/{no}/performance, chat (stub)
```

Everything the planner returns comes from the warehouse: trains, times, running days and delays. Nothing is invented
(CLAUDE.md), and the planner makes no LLM calls.

## Run it

```bash
# a warehouse first: synthetic (docs/phase1/data-platform.md) or your patribot-data checkout
uv run patribot-api                                  # 127.0.0.1:8000, Swagger UI at /api/v1/docs
uv run uvicorn patribot.api.main:app --reload        # the same, with auto-reload
```

| Variable | Default | Meaning |
|---|---|---|
| `PATRIBOT_PLANNER_BACKEND` | `postgres` if `PATRIBOT_PG_DSN` is set, else `duckdb` | Which repository to read |
| `PATRIBOT_WAREHOUSE_DIR` | `warehouse` | DuckDB backend: reads `<dir>/patribot.duckdb` read-only |
| `PATRIBOT_PG_DSN` | unset | Postgres backend: reads schema `serving` (the reverse-ETL copy) |
| `PATRIBOT_API_HOST` / `PATRIBOT_API_PORT` | `127.0.0.1` / `8000` | `patribot-api` bind address |
| `PATRIBOT_API_RELOAD` | unset | `1` = uvicorn auto-reload |
| `PATRIBOT_CORS_ORIGINS` | `http://localhost:3000,http://localhost:3100` | Allowed browser origins |
| `PATRIBOT_TODAY` | today in IST | Pins "today" (`YYYY-MM-DD`) for demos and tests on old or synthetic data. Moves the booking window too |

**Snapshot reloads.** The planner works on an in-memory snapshot of the gold tables (a few MB for the MVP corridors).
With DuckDB it reloads when the warehouse file changes (a new `dbt build`); each read opens and closes its own
read-only connection, so dbt can rebuild between requests. With Postgres it reloads every 5 minutes. A failed reload
keeps serving the previous snapshot; with no snapshot at all the endpoints answer `503`.

**Tables read** (DuckDB name → serving name): `gold.dim_station`, `gold.dim_station_cluster`, `gold.dim_train`,
`gold.dim_train_schedule`, `gold.agg_delay_stats`, `gold.agg_delay_stats_all`, `gold.agg_train_delay_stats`,
`gold.agg_corridor_delay_stats`, `gold.fct_run_summary`, `ref.seed_corridor`, `ref.seed_corridor_split_hub`,
`ref.seed_corridor_waypoint` → `serving.<same name>` (seeds as `corridor`, `corridor_split_hub`,
`corridor_waypoint`). The reverse ETL (`patribot.transform.serving`) publishes all of them, plus
`dim_train_corridor` and `dim_date`.

## Places (FR-2)

`origin` / `destination` accept a cluster id (`KOLKATA`), a station code (`HWH`), a city alias (`Calcutta`,
`Bombay`, `Bangalore`, `Madras`, `Dilli`) or an exact station name (`Howrah Jn`, also without `Jn`). A cluster expands
to its stations from `config/corridors.yaml`; a station overrides the cluster (single-station search).

## Direct search (FR-5, FR-6)

Times are kept as **minutes after the train's departure from its origin** (`gold.dim_train_schedule.arr_min` /
`dep_min`). A run is named by its **run date**, the origin departure date; running days apply at the origin.

1. For each reserved train (`dim_train.is_reserved`) with a schedule: board at the **last** halt in the origin set
   that comes before the **first** later halt in the destination set (a train calling at two origin-cluster stations
   is boarded at the later one: the shorter ride). Trains running the other way never match.
2. For each requested date D (a departure date **from the boarding station**), the run date is D − k, where k is the
   number of midnights between the origin departure and the boarding departure. The run must operate on that run
   date. Example: a Monday-only train leaving its origin at 22:00 and a mid-route station at 01:30 is found for a
   Tuesday departure from that station, with `run_date` Monday.
3. **Overnight** (FR-6) is judged on the timetable: departure 16:00–23:59 and arrival 04:00–11:00 (both inclusive) on
   a later calendar day (one night or more).

## ETA baseline `baseline_hist` (FR-10, FR-12, FR-13)

Predicted arrival = scheduled arrival + a delay estimate for that train at that station in the run's month. The first
level with enough data wins (`MIN_RUNS` = 5 runs):

| # | Level | Source table | `eta_basis` | `history_runs` |
|---|---|---|---|---|
| 1 | train × station × month (n ≥ 5) | `agg_delay_stats` | `train_station_month` | n |
| 2 | train × station, all months (n ≥ 5) | `agg_delay_stats_all` | `train_station` | n |
| 3 | 1–4 runs at the station: shrunk toward level 4, weight n / (n + 5) | both | `train_station_shrunk` | n |
| 4 | the train's final-arrival delay (that month if n ≥ 5, else all months) × route fraction to the station | `agg_train_delay_stats` | `train_route_scaled` | n |
| 5 | the same over the corridor's member trains (largest sample among the train's corridors) × route fraction | `agg_corridor_delay_stats` | `corridor_route_scaled` | 0 |
| 6 | no history: delay 0 | — | `none` | 0 |

**Reliability** = P(arrival delay ≤ 30 min): the empirical share at levels 1–2 (and blended at level 3); at levels 4–5
a normal distribution fitted to the scaled P50/P90 (the train's own share when the station is ≥ 95 % of the way). At
level 5 it is pulled halfway toward 0.5, so a train with no history cannot outrank a measured one on borrowed numbers;
at level 6 it is 0.5. Predicted P50 is never before the departure and P90 never below P50. Only delay-target runs
(complete, not disrupted: docs/phase1/data-platform.md) feed these tables.

Phase 5 replaces this with the LightGBM quantile model (`meta.eta_model` changes; the contract does not).

## Split itineraries (FR-7, FR-8)

For every corridor whose end clusters or waypoints contain both the origin and the destination, and each of its
`split_hubs` (config, e.g. KOL-DEL: ASN, DHN, GAYA, PNBE, DDU, PRYJ, CNB, LKO):
- **Leg 1** origin → hub on the requested dates, **leg 2** hub → destination on a different train, both drawn from the
  corridor's member trains (`dim_train_corridor`).
- Leg 2 must depart **≥ leg-1 P90 arrival + 45 min** and **≤ leg-1 P50 arrival + 8 h** (`PlannerConfig.min_buffer_min`,
  `max_layover_min`). The best two leg-2 options per leg 1 are kept (earliest P50 arrival).
- P(connection) = P(leg-1 delay leaves ≥ 15 min to change trains), normal fit to leg 1's P50/P90.
- Every split is labelled **`split_itinerary`** (separate tickets) and warns: no refund or rebooking for a missed leg 2,
  book both legs, a tight (< 60 min at P90) connection, a night-time wait at the hub. Official **break journeys**
  (one ticket, IR rules) need fare-rule data and are not generated yet.

## Constraints and ranking (FR-9, NFR-7, architecture §7.3)

**Hard** constraints (`preferences.hard`) filter; everything else is a soft preference that scores:

| Preference | Met when | Hard |
|---|---|---|
| `overnight` | FR-6 above (first departure, last scheduled arrival) | filter |
| `depart_after` / `depart_before` | first departure's clock time | filter |
| `arrive_by` | **P90** arrival ≤ deadline (soft: 1.0 at P90, 0.5 when only P50 makes it) | filter on P90 |
| `classes` | every leg lists one of the classes (unknown classes: 0.5 and a warning, never filtered out) | filter |

The deadline is `arrive_by` on `arrive_by_date` when given (itineraries more than 24 h early do not count), else on
each itinerary's own scheduled arrival day.

Each score component is 0..1, higher is better, and returned as `score_breakdown`:

| Component | Definition |
|---|---|
| `journey_time` | exp(−(t − t_fastest) / (0.25 × t_fastest)), t = predicted P50 door-to-door minutes over the candidate set: 1 for the fastest, 1/e for one 25 % slower |
| `reliability` | product of the legs' reliability × P(connection) |
| `preference` | share of the requested soft preferences met (1 when none) |
| `transfer` | 1 for direct; 0.6 × P(connection) for a split |

`score = Σ weight × component`:

| objective | journey_time | reliability | preference | transfer |
|---|---|---|---|---|
| `fastest` | 0.6 | 0.1 | 0.2 | 0.1 |
| `most_reliable` | 0.2 | 0.5 | 0.2 | 0.1 |
| `balanced` (default) | 0.35 | 0.35 | 0.2 | 0.1 |

**Diversified top N:** the best date of each distinct train (or train pair and hub) first, by score, then further
dates by score. **`why`** lists, in order: fastest or how much slower, most reliable (unless the objective is fastest),
overnight times, arrive-by met at P90, the change at the hub, then each leg's reliability and history (or which
fallback was used). **Warnings** add: fallback ETA, beyond the booking window (with the opening date), departure in
the past, unknown running days, unknown classes, and the split warnings above.

**Booking window (ARP):** `meta.bookable_from/to` = today .. today + 60 days (IST). Later run dates are planned, not
hidden ("plan only"), with a warning.

## Train endpoints (FR-16, FR-17)

- `/trains/{no}`: route from `dim_train_schedule` with the baseline's per-stop delay for the current month;
  `delay_p50_min` / `delay_p90_min` are `null` when the train has no history there (`history_runs` 0).
- `/trains/{no}/performance?months=3`: from `fct_run_summary`, anchored on the latest collected run. Delay figures use
  delay-target runs only; `recent_runs` shows every attempted run with its `run_state`.

## Chat stub (`POST /chat`)

Until Phase 4 the endpoint parses the message with rules (`patribot.api.chat`: places with "from"/"to", dates such as
"Nov 20-30" / "25 November" / ISO / "tomorrow", "overnight", "fastest", "reliable", "split" / "break journey" /
"full", "reach … by 9 AM" → hard `arrive_by` on P90 with the date as `arrive_by_date`, classes such as "3AC"), runs
the same `plan()` and streams `token` events, one `meta` and one `itineraries` event and `done`. If something essential is missing
it asks a question instead (FR-3). Errors carry `code` (`server_error` only, until quotas exist) and `detail`. No
quota is metered and no LLM is called.

## Web app contract notes (docs/phase3/web-app.md), as answered in docs/api/v1.md

| # | Note | Answer |
|---|---|---|
| 1 | Chat `itineraries` has no `meta` | New `event: meta` before `itineraries` (additive) |
| 2 | No quota endpoint | Open: comes with accounts and metering in Phase 4 (FR-22, FR-23) |
| 3 | Chat errors have no code | `error` carries `code`: `quota_exhausted` \| `spend_guard` \| `server_error` (note the spelling: `quota_exhausted`) |
| 4 | `query` shape | Pinned: resolved ids, kinds, display names and station lists |
| 5 | Limits | Window ≤ 31 days (422 beyond); `max_results` default 10, capped at 20 |
| 6 | Nullability | Per-stop delays `null` when `history_runs` is 0; station `cluster` may be `null` |
| 7 | `on_time_pct` | Same definition as `pct_within_30min` (within 30 min), over the whole window |
| 8 | ARP and `run_date` | Judged on each leg's `run_date` (the origin date), as the web app assumes |
| 9 | CORS | `http://localhost:3000` and `http://localhost:3100` by default |

## Tests

| File | What |
|---|---|
| `tests/test_planner.py` | Overnight window edges, run date when boarding mid-route, wrong direction and non-running days, split buffer maths (P90 + 45 min .. P50 + 8 h), hard arrive-by on P90, hard filters, ranking/`why`/ARP, request limits, every ETA fallback level |
| `tests/test_api.py` | All endpoints with `TestClient` on a warehouse built from the synthetic sample (`conftest.built_warehouse`), CORS, 404/422/503, chat SSE, and the golden queries **Q1** (overnight, fastest), **Q2** (reach by 09:00 on P90) and **Q3** (split via a hub) as structural checks |
| `tests/test_chat_parse.py` | The BRD Q1–Q3 phrasings through the rule parser |
| `tests/test_planner_repository.py` | DuckDB repository and reloads; Postgres SQL shape via a fake connection (a real database with `PATRIBOT_TEST_PG_DSN`) |

## Known limits

- **Timetable = latest cached schedule.** No validity periods or SCD-2: a schedule change applies to past and future
  dates alike. Trains without a cached schedule (only running history) are not searchable.
- **Classes and availability:** classes come from station timetables and can be empty; seat availability and fares are
  not known (no booking, BRD scope), so "all trains are full" (Q3) is answered by offering splits, not by checking.
- **Splits** are limited to curated hubs and two legs; the Connection Scan Algorithm (architecture §7.2) comes later.
- **Weather** is not a planner or ETA input yet (calendar flags exist in `gold.dim_date` for the Phase 5 model).
- With little history most trains use the corridor fallback, so early rankings lean on the timetable.
