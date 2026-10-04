"""End to end on synthetic data: sample bronze → silver input → `dbt build` (models + data tests) → gold checks.
Also loads the Dagster definitions. Takes ~15 s; no network, no Postgres."""

from __future__ import annotations

import gzip
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[1]


def test_sample_generator_is_deterministic(tmp_path, sample_script):
    mod = sample_script
    mod.generate(tmp_path / "a", date(2026, 12, 30), days=3)
    mod.generate(tmp_path / "b", date(2026, 12, 30), days=3)
    files_a = sorted(p.relative_to(tmp_path / "a") for p in (tmp_path / "a").rglob("*.gz"))
    files_b = sorted(p.relative_to(tmp_path / "b") for p in (tmp_path / "b").rglob("*.gz"))
    assert files_a == files_b and files_a
    for rel in files_a:
        assert gzip.decompress((tmp_path / "a" / rel).read_bytes()) == gzip.decompress(
            (tmp_path / "b" / rel).read_bytes()
        )


def test_dbt_build_produces_gold_tables(built_warehouse):
    db, counts, stats = built_warehouse
    assert stats.parse_failures == 0 and stats.bad_lines == 0
    con = duckdb.connect(str(db), read_only=True)
    states = dict(con.sql("select run_state, count(*) from gold.fct_run_summary group by 1").fetchall())
    assert states["not_found"] == counts["cancelled"]
    assert states["complete"] > 0.9 * stats.runs

    # retried runs keep all attempts and end up ok
    assert (
        con.sql("select count(*) from gold.fct_run_summary where n_attempts > 1 and fetch_status = 'ok'").fetchone()[0]
        >= 1
    )

    # the window crosses New Year: arrivals on 1 Jan of runs that start on 31 Dec are in the next year
    nye = con.sql(
        "select sched_arrival, act_arrival from gold.fct_run_summary"
        " where train_no = '12301' and start_date = date '2026-12-31'"
    ).fetchone()
    assert nye[0].year == 2027 and nye[1].year == 2027
    assert con.sql("select max(sched_day_offset) from gold.fct_run_stop_delay").fetchone()[0] <= 2

    # only complete runs feed delay targets; incomplete/cancelled ones are kept but flagged
    bad = con.sql("select count(*) from gold.fct_run_stop_delay where is_delay_target and run_state <> 'complete'")
    assert bad.fetchone()[0] == 0
    assert con.sql("select count(*) from gold.fct_run_stop_delay where run_state = 'incomplete'").fetchone()[0] > 0

    n, p50, p90, pct = con.sql(
        "select sum(n_runs), median(p50_arr_delay_min), median(p90_arr_delay_min), avg(pct_within_30min)"
        " from gold.agg_delay_stats"
    ).fetchone()
    assert n > 0 and p90 >= p50 and 0 <= pct <= 100

    # station/cluster dimensions are populated from the corridor config and the data
    assert con.sql("select cluster_id from gold.dim_station where station_code = 'NDLS'").fetchone()[0] == "DELHI"
    con.close()


def test_timetable_and_calendar_reach_gold(built_warehouse):
    db, _, _ = built_warehouse
    con = duckdb.connect(str(db), read_only=True)
    # every sample train has a schedule; timetable-only trains (no runs) are in dim_train too
    n_trains, n_tt, n_runs_only = con.sql(
        "select count(*), count(*) filter (where has_timetable), count(*) filter (where not has_timetable)"
        " from gold.dim_train"
    ).fetchone()
    assert n_tt == n_trains and n_runs_only == 0
    assert con.sql("select n_runs_attempted from gold.dim_train where train_no = '22999'").fetchone()[0] == 0
    assert con.sql("select running_days from gold.dim_train where train_no = '22998'").fetchone()[0] == "MON,WED,FRI"
    # minutes from the origin departure increase along each route; arrivals after midnight land on day 1+
    bad = con.sql(
        "select count(*) from (select dep_min, lag(dep_min) over (partition by train_no order by seq) as prev"
        " from gold.dim_train_schedule) where dep_min <= prev"
    ).fetchone()[0]
    assert bad == 0
    assert con.sql("select max(day_offset) from gold.dim_train_schedule").fetchone()[0] >= 1
    # corridor membership (D10): the Howrah Rajdhani is an end-to-end KOL-DEL train; Kanpur → Delhi is a member
    # starting mid-path; a train is in a corridor once
    row = con.sql(
        "select direction, serves_both_ends from gold.dim_train_corridor where train_no = '12301'"
        " and corridor_id = 'KOL-DEL'"
    ).fetchone()
    assert row == ("AB", True)
    assert con.sql(
        "select serves_both_ends from gold.dim_train_corridor where train_no = '22999' and corridor_id = 'KOL-DEL'"
    ).fetchone() == (False,)
    # stations carry coordinates from the timetable
    assert con.sql("select lat is not null from gold.dim_station where station_code = 'HWH'").fetchone()[0]
    # calendar: fog season on the northern corridors, festival windows, approximate rows flagged
    fog, corridors, approx = con.sql(
        "select is_fog_season, fog_corridors, any_approximate from gold.dim_date where date_day = date '2027-01-10'"
    ).fetchone()
    assert fog and "KOL-DEL" in corridors and approx
    assert not con.sql("select is_fog_season from gold.dim_date where date_day = date '2027-03-01'").fetchone()[0]
    assert con.sql("select is_festival_window from gold.dim_date where date_day = date '2026-11-08'").fetchone()[0]
    con.close()


def test_dagster_definitions_load(built_warehouse, tmp_path):
    db, _, _ = built_warehouse
    env = {**os.environ, "PATRIBOT_WAREHOUSE_DIR": str(db.parent), "PATRIBOT_DATA_DIR": str(tmp_path)}
    code = (
        "from pipelines.definitions import defs; g = defs.resolve_asset_graph(); "
        "keys = {k.to_user_string() for k in g.get_all_asset_keys()}; "
        "need = {'bronze/running_status', 'silver_input/runs', 'gold/fct_run_stop_delay', 'serving/postgres', "
        "'bronze/timetable_cache', 'silver_input/train_schedule', 'gold/dim_train_corridor'}; "
        "assert need <= keys, keys; "
        "assert g.get(next(k for k in g.get_all_asset_keys() if k.to_user_string() == 'silver/stg_train_run_stop'))"
        ".parent_keys == {next(k for k in g.get_all_asset_keys() if k.to_user_string() == 'silver_input/stops')}; "
        "defs.resolve_job_def('daily_refresh'); print('ok')"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-3000:]
    assert out.stdout.strip().endswith("ok")
