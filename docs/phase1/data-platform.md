# Phase 1: Data platform

How the collector's raw files become the gold tables the planner and ETA model use, and how to run it locally.
Design context: [solution architecture §5](../02-solution-architecture.md#5-data-platform).

```
patribot-data checkout (bronze)          warehouse/ (git-ignored)                                Postgres
raw/railkit/running_status/…jsonl.gz ──► silver_input/{runs,stops}.parquet ──► patribot.duckdb ──► schema serving
        collector (Phase 0)               patribot.transform.bronze            dbt: ref, silver,   reverse ETL
                                          (provider parsers, Python)           gold (+ data tests)
state/timetable-cache/*.json.gz ───────► silver_input/{train_schedule,
        watchlist build (weekly)            train_info,train_corridor}.parquet
                                          patribot.transform.timetable
```

Dagster orchestrates all steps (`pipelines/definitions.py`) and runs them daily at 06:15 IST, after the
collector's 05:47 IST run.

## Run it locally

```bash
uv sync

# 1. Bronze: point at your patribot-data checkout, or generate synthetic data (git-ignored samples/)
uv run python scripts/make_sample_bronze.py --out samples/bronze      # 7 seed trains × 30 days from 2026-12-15
export PATRIBOT_DATA_DIR=samples/bronze                               # default: data/
                                                                      # (+ a synthetic timetable cache, 9 trains)

# 2. Bronze → silver input (Parquet in warehouse/silver_input/), running data and timetable
uv run python -m patribot.transform.bronze
uv run python -m patribot.transform.timetable                         # reads <data dir>/state/timetable-cache

# 3. dbt: seeds, models and data tests (DuckDB file warehouse/patribot.duckdb). Run from the repo root.
uv run dbt build --project-dir dbt --profiles-dir dbt

# 4. Optional: Postgres + pgvector for the serving copy
cp .env.example .env                                                  # set POSTGRES_PASSWORD and PATRIBOT_PG_DSN
docker compose -f infra/docker-compose.yml --env-file .env up -d
```

Or let Dagster run all of it:

```bash
uv run dagster dev                                       # UI on http://localhost:3000; reads .env in the repo root
uv run dagster job execute -m pipelines.definitions -j daily_refresh   # one run, no UI (this is what CI runs)
```

Under `dagster dev` the dbt manifest is re-parsed on every load. Outside it (`job execute`, tests) it is re-parsed when
any file under `dbt/` is newer than the manifest. Dagster keeps its own dbt artefacts in `dbt/target/dagster/`.

| Variable | Default | Meaning |
|---|---|---|
| `PATRIBOT_DATA_DIR` | `data` | Bronze root (contains `raw/`) |
| `PATRIBOT_WAREHOUSE_DIR` | `warehouse` | Parquet silver input + `patribot.duckdb`. dbt reads it too, so run dbt from the repo root or set it absolute |
| `PATRIBOT_PG_DSN` | unset | Reverse-ETL target. Unset → the `serving/postgres` asset skips itself |
| `PATRIBOT_FRESHNESS_HOURS` | `36` | Asset check: warn when the newest fetched run is older |
| `PATRIBOT_TIMETABLE_DIR` | `<PATRIBOT_DATA_DIR>/state/timetable-cache` | Cached RailKit timetable responses (from the watchlist build) |

Keep the corridor seeds in sync after editing `config/corridors.yaml`:
`uv run python -m patribot.transform.seeds`. A test (`--check` in CI) fails if they drift.

## Parsing RailKit history (`src/patribot/transform/railkit.py`)

- Times come as `"HH:MM DD-Mon"` in IST with no year. The year is the one that puts the time closest to the run's start
  date, so a run starting on 31 Dec that arrives on `"05:10 01-Jan"` lands in the next year.
- `SRC` / `DSTN` mark the origin's arrival and the destination's departure. A trailing `*` on an actual time
  (provisional) is stripped.
- Delay = actual − scheduled when both times parse. The provider's text ("On Time", "16 Min", "1 Hr 5 Min") is a
  fallback only.
- Bad station rows are skipped, never fatal. A stop's `seq` is its position among the kept rows. If a payload can't be
  parsed, the run is kept with `parse_ok = false`.
- **Choosing an envelope per run** (`bronze.py`): the latest `ok` envelope by `fetched_at`. If the run never succeeded,
  its latest envelope of any status is used, so not-found and error runs stay visible downstream.

The parser was written from the provider's documented examples. The first real bronze files (October 2026) parse
without failures; cancelled runs have not been seen yet (see below).

## Timetable (`src/patribot/transform/timetable.py`)

The weekly watchlist build ([watchlist.md](watchlist.md)) caches every RailKit timetable response it fetches in the
data repo, `state/timetable-cache/*.json.gz` (`{"fetched_at", "path", "data"}`). The loader reads that cache, with no
API calls, and writes three Parquet files next to the running data:

| File | Grain | From |
|---|---|---|
| `train_schedule` | train × route stop | `/trains/{no}/info` `route[]`: "HH:MM" times, 0-based day offset of the arrival and of the departure, cumulative km, halt, platform, lat/lon |
| `train_info` | train | `trainInfo` (name, coarse type, origin/destination, `running_days` **Monday-first**, confirmed) plus the station timetables' finer type ("Vande Bharat") and reserved classes; the reserved-train filter's verdict |
| `train_corridor` | train × corridor path | Corridor membership from the **same** `patribot.watchlist.membership` functions the watchlist uses (D10), so the two cannot disagree |

**Day offsets.** RailKit's `day` is the departure day when a halt crosses midnight. The loader places each time at the
earliest day that keeps the route's times increasing, with the provider's `day` as a floor, so both conventions give
the same answer. When a train has several cached schedules the newest `fetched_at` wins.

It is RailKit-derived (D15): it lives only in the git-ignored warehouse. CI uses the synthetic cache written by
`scripts/make_sample_bronze.py` (same shape, made-up times and coordinates, two timetable-only trains).

## Calendar (`dbt/seeds/calendar_events.csv` → `gold.dim_date`)

Hand-kept seed for 2025-12 … 2028-02: national holidays, festival travel-rush windows (Durga Puja, Diwali, Chhath,
Holi, Eid, Christmas–New Year) and the North India **fog season** (15 Dec – 15 Feb, corridors KOL-DEL, DEL-PAT,
MUM-DEL). Lunar festivals and the fog window are marked `approximate = true`; check the dates against the official
holiday list each year. `gold.dim_date` has one row per day of 2026–2027 with day of week, holiday, festival window and
peak, fog season and its corridors. These are features for the Phase 5 model (FR-14); the baseline ETA does not use them.

**Weather is out of scope for now:** no free source with the needed history has been chosen. It joins as a separate
bronze source when the ETA model needs it.

## Tables

Schemas in `warehouse/patribot.duckdb`: `ref` (seeds), `silver`, `gold`. Every row keeps its `source` (D15:
RailKit-derived data must stay identifiable and is never redistributed).

| Table | Grain | What it holds |
|---|---|---|
| `ref.seed_station_cluster` | station | City clusters from `config/corridors.yaml` |
| `ref.seed_corridor`, `…_waypoint`, `…_split_hub`, `…_membership_param` | corridor / path waypoint | Corridor paths, split hubs and membership thresholds from the same file |
| `silver.stg_train_run` | run attempted (source, train, start date) | Fetch outcome (`ok` / `not_found` / `error`), attempt count, payload header, cancelled flag |
| `silver.stg_train_run_stop` | run × stop | Scheduled and actual arr/dep (TIMESTAMPTZ, IST), delays, distance, platform, day offset, halt minutes |
| `ref.calendar_events` | event | Holidays, festival windows, fog season (see Calendar) |
| `silver.stg_train_schedule` | train × timetable stop | Clock times, clock minutes, day offsets, distance, halt, lat/lon |
| `silver.stg_train_info` | train | Timetable attributes, running days, classes, `is_reserved` |
| `gold.dim_station` | station | Every station seen in data, in the timetable or named in the config: most common name, cluster, waypoint/split-hub roles, lat/lon, first and last seen |
| `gold.dim_station_cluster` | station | Station → cluster mapping, with whether the station has appeared in data |
| `gold.dim_train` | train | Every train with runs or a timetable: name, display type, origin and destination, running days, classes, route km, `corridor_ids`, `is_reserved`, runs attempted and complete |
| `gold.dim_train_schedule` | train × stop | Scheduled times as **minutes from the origin departure** (`arr_min`, `dep_min`), cluster, route fraction: the planner's timetable |
| `gold.dim_train_corridor` | train × corridor | Widest matching path, its halts, segments, km, direction, `serves_both_ends` (D10) |
| `gold.dim_date` | date | Day of week and calendar flags (see Calendar) |
| `gold.fct_run_summary` | run | Origin departure delay, final arrival delay, scheduled vs actual journey minutes, `run_state`, `is_disruption`, `is_delay_target_eligible` |
| `gold.fct_run_stop_delay` | run × stop | Arrival and departure delay, segment run times, delay gained since the previous stop, `is_delay_target` |
| `gold.agg_delay_stats` | train × station × month | `n_runs`, mean, P50, P90, min and max arrival delay, `pct_within_30min` (0–100), mean departure delay. Baseline B2 for the planner |
| `gold.agg_delay_stats_all` | train × station | The same over all months (B1) |
| `gold.agg_train_delay_stats` | train × month, and `all` | Final-arrival delay distribution: the planner's fallback when a station has little history |
| `gold.agg_corridor_delay_stats` | corridor × month, and `all` | The same over the corridor's member trains: the fallback for a train with no history |

**`run_state`** decides whether a run may feed delay targets:

| State | Meaning |
|---|---|
| `complete` | Origin departure and destination arrival both have actual times |
| `incomplete` | Fetched, but one of those actual times is missing |
| `cancelled` | The payload says so (status note or flag) |
| `diverted` | The last stop is not the scheduled destination (diverted or short-terminated) |
| `not_found` | Never fetched successfully; the provider had no history (cancelled, not run, or not available yet) |
| `fetch_error` | Never fetched successfully because of HTTP or transport errors |
| `unparseable` | Fetched `ok`, but the payload could not be parsed |

Only `complete` runs whose worst stop delay is ≤ `delay_outlier_min` (dbt var, default 720) are delay targets. Other
runs stay in the fact tables, flagged. The RailKit history endpoint probably answers 404 for a cancelled run, so most
cancellations will show up as `not_found`.

**Data tests** (`dbt build` runs 128 of them): uniqueness and not-null on every key, relationships (stops → runs, stops →
`dim_station`, corridor seeds → clusters), accepted values for `fetch_status` and `run_state`, accepted ranges for
delays, distances, day offsets, halts and journey minutes, plus invariants: delay targets only come from complete runs,
P90 ≥ P50, and `journey_date = start_date` (warn only). dagster-dbt turns these into asset checks. Dagster adds a
freshness check on `silver_input/runs`.

## Reverse ETL (`src/patribot/transform/serving.py`)

The asset copies the gold tables (the six above plus, for the planner, `dim_train_schedule`, `dim_train_corridor`,
`agg_delay_stats_all`, `agg_train_delay_stats`, `agg_corridor_delay_stats` and `dim_date`) and `corridor`,
`corridor_waypoint` and `corridor_split_hub` into Postgres schema `serving` (`SERVING_TABLES`):
1. Each table is loaded with `COPY` into `<name>__load`.
2. All tables are swapped in by rename inside one transaction, and primary keys are added.

The API therefore never sees a half-loaded schema. Don't build views on `serving` tables: the swap drops and recreates
them.

## CI

The `data-platform` job in `.github/workflows/ci.yml` runs these steps with no network beyond package install and no
Postgres:
1. Check the seeds against the config.
2. Generate synthetic bronze and the synthetic timetable cache.
3. Build the silver input (running data, then timetable).
4. Run `dbt build`.
5. Run the Dagster `daily_refresh` job; the reverse-ETL asset skips itself.

`tests/test_pipeline_e2e.py` does the same in pytest (the warehouse fixture in `tests/conftest.py` is shared with the
API tests). The reverse ETL is tested against a fake connection, and against a real database when
`PATRIBOT_TEST_PG_DSN` is set.

## Not done yet

- **Weather** (see Calendar).
- **Timetable history:** the latest cached schedule wins (no validity periods, `dim_train` is not SCD-2).
- **Incremental bronze parsing:** the silver input is rebuilt in full each run, which is fine at POC volume. Bronze files
  never change once written, so a per-file cache is the natural next step.
- **Pulling the data repo:** the Dagster schedule doesn't update the `patribot-data` checkout; do that before it fires.
