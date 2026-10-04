"""Dagster definitions for the PatriBot data platform (architecture doc §5).

    bronze/running_status  inventory of the collector's raw files (in a checkout of the private patribot-data repo)
      → silver_input/runs, silver_input/stops   provider parsers → Parquet (patribot.transform.bronze)
    bronze/timetable_cache  cached RailKit timetable responses (state/timetable-cache in the data repo)
      → silver_input/train_schedule, train_info, train_corridor   (patribot.transform.timetable)
      → dbt: ref seeds, silver stg_*, gold dim_* / fct_* / agg_*   (dagster-dbt; dbt tests become asset checks)
      → serving/postgres   reverse ETL of gold tables into Postgres schema `serving` (PATRIBOT_PG_DSN)

Run locally:  uv run dagster dev        (reads [tool.dagster] in pyproject.toml)
Environment:  PATRIBOT_DATA_DIR (default ./data), PATRIBOT_WAREHOUSE_DIR (default ./warehouse), PATRIBOT_PG_DSN,
              PATRIBOT_TIMETABLE_DIR (default <data dir>/state/timetable-cache),
              PATRIBOT_FRESHNESS_HOURS (default 36)
"""

import os
from datetime import UTC, datetime
from pathlib import Path

import duckdb
from dagster import (
    AssetCheckResult,
    AssetCheckSeverity,
    AssetExecutionContext,
    AssetKey,
    AssetSelection,
    AssetSpec,
    Definitions,
    MaterializeResult,
    MetadataValue,
    ScheduleDefinition,
    asset,
    asset_check,
    define_asset_job,
    multi_asset,
)
from dagster_dbt import DbtCliResource, DbtProject, dbt_assets, get_asset_key_for_model

from patribot.transform.bronze import bronze_files, build_silver_input, silver_input_dir
from patribot.transform.serving import SERVING_TABLES, psycopg_connect, sync_to_postgres
from patribot.transform.timetable import build_timetable_input, timetable_dir, timetable_files

REPO = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("PATRIBOT_DATA_DIR") or REPO / "data").resolve()
WAREHOUSE_DIR = Path(os.environ.get("PATRIBOT_WAREHOUSE_DIR") or REPO / "warehouse").resolve()
DUCKDB_PATH = WAREHOUSE_DIR / "patribot.duckdb"
FRESHNESS_HOURS = float(os.environ.get("PATRIBOT_FRESHNESS_HOURS", "36"))
TIMETABLE_DIR = timetable_dir(DATA_DIR).resolve()

# dbt reads the warehouse location from the environment (dbt/profiles.yml, dbt/models/staging/_sources.yml);
# make it absolute so it does not depend on the directory dbt runs from.
os.environ["PATRIBOT_WAREHOUSE_DIR"] = str(WAREHOUSE_DIR)

BRONZE_KEY = AssetKey(["bronze", "running_status"])
RUNS_KEY = AssetKey(["silver_input", "runs"])  # = dagster-dbt's key for dbt source silver_input.runs
STOPS_KEY = AssetKey(["silver_input", "stops"])
TIMETABLE_KEY = AssetKey(["bronze", "timetable_cache"])
TT_SCHEDULE_KEY = AssetKey(["silver_input", "train_schedule"])  # = dagster-dbt's keys for the dbt sources
TT_INFO_KEY = AssetKey(["silver_input", "train_info"])
TT_CORRIDOR_KEY = AssetKey(["silver_input", "train_corridor"])

# Dagster keeps its own dbt target dir. A `dbt build --project-dir dbt` run by hand from the repo root leaves a
# partial-parse cache with *relative* seed paths in dbt/target; dagster-dbt would copy that cache into each run (it
# looks in $DBT_TARGET_PATH, default "target") and seed loading would then fail from inside dbt/.
DBT_TARGET = REPO / "dbt" / "target" / "dagster"
os.environ["DBT_TARGET_PATH"] = str(DBT_TARGET)
dbt_project = DbtProject(project_dir=REPO / "dbt", profiles_dir=REPO / "dbt", target_path=DBT_TARGET)


def _manifest_is_stale() -> bool:
    manifest = dbt_project.manifest_path
    if not manifest.exists():
        return True
    sources = [p for d in ("models", "seeds", "macros", "tests") for p in (REPO / "dbt" / d).rglob("*") if p.is_file()]
    sources += [REPO / "dbt" / "dbt_project.yml", REPO / "dbt" / "profiles.yml"]
    return max(p.stat().st_mtime for p in sources) > manifest.stat().st_mtime


dbt_project.prepare_if_dev()  # `dagster dev`: always re-parse so model edits show up
if _manifest_is_stale():  # outside `dagster dev` (job execute, tests, CI): parse when missing or out of date
    dbt_project.preparer.prepare(dbt_project)


@asset(
    key=BRONZE_KEY,
    group_name="bronze",
    description="Raw running-status envelopes written by the collector (read-only inventory of the data dir).",
)
def bronze_running_status(context: AssetExecutionContext) -> MaterializeResult:
    files = bronze_files(DATA_DIR)
    latest = max((f.parent.name.removeprefix("collected_date=") for f in files), default=None)
    if not files:
        context.log.warning(f"no bronze files under {DATA_DIR} (set PATRIBOT_DATA_DIR)")
    return MaterializeResult(
        metadata={"data_dir": str(DATA_DIR), "files": len(files), "latest_collected_date": latest or ""}
    )


@multi_asset(
    specs=[
        AssetSpec(RUNS_KEY, deps=[BRONZE_KEY], group_name="silver", description="One row per attempted run."),
        AssetSpec(STOPS_KEY, deps=[BRONZE_KEY], group_name="silver", description="Canonical stop rows."),
    ],
)
def silver_input(context: AssetExecutionContext):
    stats = build_silver_input(DATA_DIR, WAREHOUSE_DIR)
    out = silver_input_dir(WAREHOUSE_DIR)
    common = {
        "bronze_files": stats.files,
        "envelopes": stats.envelopes,
        "bad_lines": stats.bad_lines,
        "parse_failures": stats.parse_failures,
    }
    yield MaterializeResult(
        asset_key=RUNS_KEY,
        metadata={**common, "rows": stats.runs, "runs_ok": stats.runs_ok, "path": str(out / "runs.parquet")},
    )
    yield MaterializeResult(
        asset_key=STOPS_KEY, metadata={**common, "rows": stats.stops, "path": str(out / "stops.parquet")}
    )


@asset(
    key=TIMETABLE_KEY,
    group_name="bronze",
    description="Cached RailKit timetable responses (train info, station timetables) from the watchlist build.",
)
def bronze_timetable_cache(context: AssetExecutionContext) -> MaterializeResult:
    files = timetable_files(TIMETABLE_DIR)
    if not files:
        context.log.warning(f"no timetable cache under {TIMETABLE_DIR} (set PATRIBOT_TIMETABLE_DIR)")
    return MaterializeResult(metadata={"timetable_dir": str(TIMETABLE_DIR), "files": len(files)})


@multi_asset(
    specs=[
        AssetSpec(TT_SCHEDULE_KEY, deps=[TIMETABLE_KEY], group_name="silver", description="Train × timetable stop."),
        AssetSpec(TT_INFO_KEY, deps=[TIMETABLE_KEY], group_name="silver", description="One row per timetabled train."),
        AssetSpec(TT_CORRIDOR_KEY, deps=[TIMETABLE_KEY], group_name="silver", description="Corridor membership (D10)."),
    ],
)
def silver_timetable(context: AssetExecutionContext):
    stats = build_timetable_input(TIMETABLE_DIR, WAREHOUSE_DIR)
    common = {"cache_files": stats.files, "bad_files": stats.bad_files}
    yield MaterializeResult(asset_key=TT_SCHEDULE_KEY, metadata={**common, "rows": stats.stops})
    yield MaterializeResult(
        asset_key=TT_INFO_KEY, metadata={**common, "rows": stats.trains, "reserved": stats.reserved_trains}
    )
    yield MaterializeResult(
        asset_key=TT_CORRIDOR_KEY,
        metadata={**common, "rows": stats.memberships, "member_trains": stats.member_trains},
    )


@asset_check(asset=RUNS_KEY, description=f"Newest fetched run is at most {FRESHNESS_HOURS:g} h old.")
def silver_input_runs_fresh() -> AssetCheckResult:
    path = silver_input_dir(WAREHOUSE_DIR) / "runs.parquet"
    if not path.exists():
        return AssetCheckResult(passed=False, severity=AssetCheckSeverity.WARN, metadata={"reason": "no runs.parquet"})
    newest = duckdb.sql(f"select max(fetched_at) from read_parquet('{path.as_posix()}')").fetchone()[0]
    if newest is None:
        return AssetCheckResult(passed=False, severity=AssetCheckSeverity.WARN, metadata={"reason": "no runs"})
    age_h = (datetime.now(UTC) - newest).total_seconds() / 3600
    return AssetCheckResult(
        passed=age_h <= FRESHNESS_HOURS,
        severity=AssetCheckSeverity.WARN,
        metadata={"newest_fetched_at": newest.isoformat(), "age_hours": round(age_h, 1)},
    )


@dbt_assets(manifest=dbt_project.manifest_path, project=dbt_project)
def patribot_dbt_assets(context: AssetExecutionContext, dbt: DbtCliResource):
    yield from dbt.cli(["build"], context=context).stream()


SERVING_DEPS = [
    get_asset_key_for_model([patribot_dbt_assets], t.source.split(".", 1)[1])
    for t in SERVING_TABLES
    if t.source.startswith("gold.")
]


@asset(
    key=AssetKey(["serving", "postgres"]),
    deps=SERVING_DEPS,
    group_name="serving",
    description="Reverse ETL: gold tables → Postgres schema `serving` (atomic swap). Skipped without PATRIBOT_PG_DSN.",
)
def serving_postgres(context: AssetExecutionContext) -> MaterializeResult:
    dsn = os.environ.get("PATRIBOT_PG_DSN")
    if not dsn:
        context.log.warning("PATRIBOT_PG_DSN is not set; skipping the reverse ETL to Postgres")
        return MaterializeResult(metadata={"skipped": True})
    results = sync_to_postgres(DUCKDB_PATH, psycopg_connect(dsn))
    return MaterializeResult(
        metadata={
            "skipped": False,
            "tables": MetadataValue.md("\n".join(f"- `{r.target}`: {r.rows} rows" for r in results)),
            "rows": sum(r.rows for r in results),
        }
    )


daily_refresh = define_asset_job("daily_refresh", selection=AssetSelection.all())

defs = Definitions(
    assets=[
        bronze_running_status,
        silver_input,
        bronze_timetable_cache,
        silver_timetable,
        patribot_dbt_assets,
        serving_postgres,
    ],
    asset_checks=[silver_input_runs_fresh],
    jobs=[daily_refresh],
    # after the collector's 00:17 UTC (05:47 IST) run; update the patribot-data checkout before this fires
    schedules=[
        ScheduleDefinition(
            name="daily_refresh_schedule",
            job=daily_refresh,
            cron_schedule="15 6 * * *",
            execution_timezone="Asia/Kolkata",
        )
    ],
    resources={"dbt": DbtCliResource(project_dir=dbt_project)},
)
