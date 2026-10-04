# Phase 1: Data platform

How the collector's raw files become the gold tables the planner and ETA model use, and how to run it locally.
Design context: [solution architecture §5](../02-solution-architecture.md#5-data-platform).

```
patribot-data checkout (bronze)          warehouse/ (git-ignored)                                Postgres
raw/railkit/running_status/…jsonl.gz ──► silver_input/{runs,stops}.parquet ──► patribot.duckdb ──► schema serving
        collector (Phase 0)               patribot.transform.bronze            dbt: ref, silver,   reverse ETL
                                          (provider parsers, Python)           gold (+ data tests)
```

Dagster orchestrates all four steps (`pipelines/definitions.py`) and runs them daily at 06:15 IST, after the
collector's 05:47 IST run.

## Run it locally

```bash
uv sync

# 1. Bronze: point at your patribot-data checkout, or generate synthetic data (git-ignored samples/)
uv run python scripts/make_sample_bronze.py --out samples/bronze      # 7 seed trains × 30 days from 2026-12-15
export PATRIBOT_DATA_DIR=samples/bronze                               # default: data/

# 2. Bronze → silver input (Parquet in warehouse/silver_input/)
uv run python -m patribot.transform.bronze

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

The parser is written from the provider's documented examples only; no real RailKit response has been seen yet. Check
it against the first real bronze files (cancelled runs especially, see below).

## Tables

Schemas in `warehouse/patribot.duckdb`: `ref` (seeds), `silver`, `gold`. Every row keeps its `source` (D15:
RailKit-derived data must stay identifiable and is never redistributed).

| Table | Grain | What it holds |
|---|---|---|
| `ref.seed_station_cluster` | station | City clusters from `config/corridors.yaml` |
| `ref.seed_corridor`, `…_waypoint`, `…_split_hub`, `…_membership_param` | corridor / path waypoint | Corridor paths, split hubs and membership thresholds from the same file |
| `silver.stg_train_run` | run attempted (source, train, start date) | Fetch outcome (`ok` / `not_found` / `error`), attempt count, payload header, cancelled flag |
| `silver.stg_train_run_stop` | run × stop | Scheduled and actual arr/dep (TIMESTAMPTZ, IST), delays, distance, platform, day offset, halt minutes |
| `gold.dim_station` | station | Every station seen in data or named in the config: most common name, cluster, waypoint/split-hub roles, first and last seen |
| `gold.dim_station_cluster` | station | Station → cluster mapping, with whether the station has appeared in data |
| `gold.dim_train` | train | Latest name, origin and destination, runs attempted and complete |
| `gold.fct_run_summary` | run | Origin departure delay, final arrival delay, scheduled vs actual journey minutes, `run_state`, `is_disruption`, `is_delay_target_eligible` |
| `gold.fct_run_stop_delay` | run × stop | Arrival and departure delay, segment run times, delay gained since the previous stop, `is_delay_target` |
| `gold.agg_delay_stats` | train × station × month | `n_runs`, mean, P50, P90, min and max arrival delay, `pct_within_30min` (0–100), mean departure delay. Baseline B2 for the planner |

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

**Data tests** (`dbt build` runs 73 of them): uniqueness and not-null on every key, relationships (stops → runs, stops →
`dim_station`, corridor seeds → clusters), accepted values for `fetch_status` and `run_state`, accepted ranges for
delays, distances, day offsets, halts and journey minutes, plus invariants: delay targets only come from complete runs,
P90 ≥ P50, and `journey_date = start_date` (warn only). dagster-dbt turns these into asset checks. Dagster adds a
freshness check on `silver_input/runs`.

## Reverse ETL (`src/patribot/transform/serving.py`)

The asset copies the six gold tables plus `corridor`, `corridor_waypoint` and `corridor_split_hub` into Postgres
schema `serving`:
1. Each table is loaded with `COPY` into `<name>__load`.
2. All tables are swapped in by rename inside one transaction, and primary keys are added.

The API therefore never sees a half-loaded schema. Don't build views on `serving` tables: the swap drops and recreates
them.

## CI

The `data-platform` job in `.github/workflows/ci.yml` runs these steps with no network beyond package install and no
Postgres:
1. Check the seeds against the config.
2. Generate synthetic bronze.
3. Build the silver input.
4. Run `dbt build`.
5. Run the Dagster `daily_refresh` job; the reverse-ETL asset skips itself.

`tests/test_pipeline_e2e.py` does the same in pytest. The reverse ETL is tested against a fake connection, and against
a real database when `PATRIBOT_TEST_PG_DSN` is set.

## Not done yet (later in Phase 1)

- **Timetable source:** `dim_train_corridor` (corridor membership, D10) and `stg_train_schedule` need it.
- **Weather and calendar sources.**
- **Incremental bronze parsing:** the silver input is rebuilt in full each run, which is fine at POC volume. Bronze files
  never change once written, so a per-file cache is the natural next step.
- **Pulling the data repo:** the Dagster schedule doesn't update the `patribot-data` checkout; do that before it fires.
