"""End to end on synthetic data: sample bronze → silver input → `dbt build` (models + data tests) → gold checks.
Also loads the Dagster definitions. Takes ~15 s; no network, no Postgres."""

from __future__ import annotations

import gzip
import importlib.util
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import duckdb
import pytest

from patribot.transform.bronze import build_silver_input

REPO = Path(__file__).resolve().parents[1]


def _load_sample_script():
    spec = importlib.util.spec_from_file_location("make_sample_bronze", REPO / "scripts" / "make_sample_bronze.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses look their module up while the script executes
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def built_warehouse(tmp_path_factory):
    root = tmp_path_factory.mktemp("e2e")
    data, wh = root / "bronze", root / "warehouse"
    counts = _load_sample_script().generate(data, date(2026, 12, 20), days=14)
    stats = build_silver_input(data, wh)

    # a separate process, so dbt-duckdb's cached connection does not clash with the test's own connection
    args = [sys.executable, "-m", "dbt.cli.main", "build", "--project-dir", str(REPO / "dbt")]
    args += ["--profiles-dir", str(REPO / "dbt"), "--target-path", str(root / "dbt-target")]
    args += ["--log-path", str(root / "dbt-logs")]
    env = {**os.environ, "PATRIBOT_WAREHOUSE_DIR": str(wh)}
    out = subprocess.run(args, env=env, capture_output=True, text=True, timeout=600)
    assert out.returncode == 0, f"dbt build failed:\n{out.stdout[-5000:]}\n{out.stderr[-2000:]}"
    return wh / "patribot.duckdb", counts, stats


def test_sample_generator_is_deterministic(tmp_path):
    mod = _load_sample_script()
    mod.generate(tmp_path / "a", date(2026, 12, 30), days=3)
    mod.generate(tmp_path / "b", date(2026, 12, 30), days=3)
    files_a = sorted(p.relative_to(tmp_path / "a") for p in (tmp_path / "a").rglob("*.jsonl.gz"))
    files_b = sorted(p.relative_to(tmp_path / "b") for p in (tmp_path / "b").rglob("*.jsonl.gz"))
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


def test_dagster_definitions_load(built_warehouse, tmp_path):
    db, _, _ = built_warehouse
    env = {**os.environ, "PATRIBOT_WAREHOUSE_DIR": str(db.parent), "PATRIBOT_DATA_DIR": str(tmp_path)}
    code = (
        "from pipelines.definitions import defs; g = defs.resolve_asset_graph(); "
        "keys = {k.to_user_string() for k in g.get_all_asset_keys()}; "
        "need = {'bronze/running_status', 'silver_input/runs', 'gold/fct_run_stop_delay', 'serving/postgres'}; "
        "assert need <= keys, keys; "
        "assert g.get(next(k for k in g.get_all_asset_keys() if k.to_user_string() == 'silver/stg_train_run_stop'))"
        ".parent_keys == {next(k for k in g.get_all_asset_keys() if k.to_user_string() == 'silver_input/stops')}; "
        "defs.resolve_job_def('daily_refresh'); print('ok')"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-3000:]
    assert out.stdout.strip().endswith("ok")
