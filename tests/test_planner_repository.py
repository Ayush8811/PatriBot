"""Planner repositories: the DuckDB warehouse (against the synthetic build) and the Postgres `serving` copy (SQL shape
against a recording fake; against a real database when PATRIBOT_TEST_PG_DSN is set and the reverse ETL has run)."""

from __future__ import annotations

import os
from datetime import date

import pytest

from patribot.planner.repository import (
    DuckDBRepository,
    PostgresRepository,
    RepositoryUnavailable,
    repository_from_env,
)
from patribot.planner.service import PlannerService
from patribot.transform.serving import SERVING_TABLES


class _Cursor:
    def __init__(self, log):
        self.log, self.description = log, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self.log.append((sql, params))

    def fetchall(self):
        return []


class _Conn:
    def __init__(self, log):
        self.log = log

    def cursor(self):
        return _Cursor(self.log)

    def close(self):
        pass


def test_postgres_repository_reads_the_serving_schema():
    log: list = []
    repo = PostgresRepository(connect=lambda: _Conn(log))
    data = repo.load()
    assert data.trains == {} and data.data_as_of is None
    repo.runs("12301", since=date(2026, 10, 1))
    published = {t.target for t in SERVING_TABLES}
    for sql, _ in log:
        assert "{" not in sql and " gold." not in sql and " ref." not in sql
        for word in sql.replace(",", " ").split():
            if word.startswith("serving."):
                assert word.removeprefix("serving.") in published, word
    sql, params = log[-1]
    assert "%s" in sql and "?" not in sql and params == ["12301", date(2026, 10, 1)]


def test_postgres_repository_maps_connection_errors():
    def fail():
        raise OSError("connection refused")

    with pytest.raises(RepositoryUnavailable):
        PostgresRepository(connect=fail).load()


def test_repository_from_env(monkeypatch, tmp_path):
    monkeypatch.delenv("PATRIBOT_PG_DSN", raising=False)
    monkeypatch.delenv("PATRIBOT_PLANNER_BACKEND", raising=False)
    monkeypatch.setenv("PATRIBOT_WAREHOUSE_DIR", str(tmp_path))
    repo = repository_from_env()
    assert isinstance(repo, DuckDBRepository) and repo.path == tmp_path / "patribot.duckdb"
    monkeypatch.setenv("PATRIBOT_PG_DSN", "postgresql://u@localhost/x")
    assert isinstance(repository_from_env(), PostgresRepository)


def test_duckdb_repository_and_service_reload(built_warehouse):
    db, _, _ = built_warehouse
    repo = DuckDBRepository(db.parent)
    data = repo.load()
    t = data.trains["12301"]
    assert t.stops[0].code == "HWH" and t.stops[-1].code == "NDLS" and "KOL-DEL" in t.corridors
    assert data.clusters["DELHI"][:2] == ("NDLS", "DLI")
    assert data.corridors["KOL-DEL"].split_hubs and data.delays.stop_all
    svc = PlannerService(repo, today=lambda: date(2026, 12, 15))
    assert svc.data() is svc.data()  # cached while the file is unchanged
    assert repo.runs("12301")[0].run_date >= repo.runs("12301")[-1].run_date


@pytest.mark.skipif(not os.environ.get("PATRIBOT_TEST_PG_DSN"), reason="needs PATRIBOT_TEST_PG_DSN")
def test_postgres_repository_against_a_real_database():  # pragma: no cover - needs Postgres with the serving copy
    data = PostgresRepository(os.environ["PATRIBOT_TEST_PG_DSN"]).load()
    assert data.clusters
