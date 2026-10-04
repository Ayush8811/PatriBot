"""Reverse ETL against a fake Postgres connection (CI has no Postgres). Set PATRIBOT_TEST_PG_DSN to also run it
against a real database."""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import UTC, date, datetime

import duckdb
import pytest

from patribot.transform.serving import ServingTable, pg_type, psycopg_connect, sync_to_postgres

TABLES = (
    ServingTable("gold.t_one", "t_one", ("id",)),
    ServingTable("ref.t_two", "two", ()),
)


def _sql_text(query) -> str:
    return query.as_string(None) if hasattr(query, "as_string") else str(query)


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query, params=None):
        text = _sql_text(query)
        if self.conn.fail_on and self.conn.fail_on in text:
            raise RuntimeError("boom")
        self.conn.statements.append(text)

    @contextmanager
    def copy(self, query):
        rows: list = []
        self.conn.copies[_sql_text(query)] = rows

        class _Copy:
            def write_row(self, row):
                rows.append(tuple(row))

        yield _Copy()


class FakeConnection:
    def __init__(self, fail_on: str | None = None):
        self.statements: list[str] = []
        self.copies: dict[str, list] = {}
        self.committed = self.rolled_back = self.closed = False
        self.fail_on = fail_on

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


@pytest.fixture
def warehouse(tmp_path):
    path = tmp_path / "w.duckdb"
    con = duckdb.connect(str(path))
    con.execute("create schema gold; create schema ref")
    con.execute(
        "create table gold.t_one"
        " (id varchar, n integer, x double, d date, ts timestamptz, ok boolean, amt decimal(10,2))"
    )
    con.execute(
        "insert into gold.t_one values"
        " ('a', 1, 1.5, date '2026-12-31', timestamptz '2027-01-01 05:10:00+05:30', true, 3.25),"
        " ('b', null, null, null, null, null, null)"
    )
    con.execute("create table ref.t_two (k varchar)")
    con.execute("insert into ref.t_two values ('z')")
    con.close()
    return path


@pytest.mark.parametrize(
    ("duck", "pg"),
    [
        ("VARCHAR", "text"),
        ("INTEGER", "integer"),
        ("BIGINT", "bigint"),
        ("DOUBLE", "double precision"),
        ("BOOLEAN", "boolean"),
        ("DATE", "date"),
        ("TIMESTAMP WITH TIME ZONE", "timestamptz"),
        ("DECIMAL(10,2)", "numeric(10,2)"),
        ("VARCHAR[]", "text"),
        ("STRUCT(a INTEGER)", "text"),
    ],
)
def test_pg_type(duck, pg):
    assert pg_type(duck) == pg


def test_sync_loads_then_swaps_in_one_transaction(warehouse):
    conn = FakeConnection()
    results = sync_to_postgres(warehouse, lambda: conn, TABLES)
    assert [(r.source, r.target, r.rows) for r in results] == [
        ("gold.t_one", "serving.t_one", 2),
        ("ref.t_two", "serving.two", 1),
    ]
    sql = "\n".join(conn.statements)
    assert 'create schema if not exists "serving"' in sql
    assert 'create table "serving"."t_one__load" ("id" text, "n" integer, "x" double precision, "d" date' in sql
    assert '"amt" numeric(10,2)' in sql
    # every load table exists before the first swap, so readers never see a partial schema
    first_swap = next(i for i, s in enumerate(conn.statements) if "rename to" in s)
    assert all("create table" not in s for s in conn.statements[first_swap:])
    assert 'alter table "serving"."t_one" add primary key ("id")' in sql
    assert 'alter table "serving"."two" add primary key' not in sql
    copied = conn.copies['copy "serving"."t_one__load" ("id", "n", "x", "d", "ts", "ok", "amt") from stdin']
    assert copied[0][:4] == ("a", 1, 1.5, date(2026, 12, 31))
    assert copied[0][4] == datetime(2026, 12, 31, 23, 40, tzinfo=UTC)
    assert copied[1] == ("b", None, None, None, None, None, None)
    assert conn.committed and conn.closed and not conn.rolled_back


def test_sync_rolls_back_on_failure(warehouse):
    conn = FakeConnection(fail_on="rename to")
    with pytest.raises(RuntimeError):
        sync_to_postgres(warehouse, lambda: conn, TABLES)
    assert conn.rolled_back and conn.closed and not conn.committed


def test_missing_warehouse_table_is_an_error(warehouse):
    conn = FakeConnection()
    with pytest.raises(LookupError, match="dbt build"):
        sync_to_postgres(warehouse, lambda: conn, (ServingTable("gold.nope", "nope"),))
    assert conn.rolled_back


@pytest.mark.skipif(not os.environ.get("PATRIBOT_TEST_PG_DSN"), reason="set PATRIBOT_TEST_PG_DSN for a real Postgres")
def test_sync_against_real_postgres(warehouse):
    import psycopg

    dsn = os.environ["PATRIBOT_TEST_PG_DSN"]
    for _ in range(2):  # idempotent
        sync_to_postgres(warehouse, psycopg_connect(dsn), TABLES, schema="serving_test")
    with psycopg.connect(dsn) as conn:
        rows = conn.execute("select id, ts, amt from serving_test.t_one order by id").fetchall()
        assert rows[0][0] == "a" and rows[0][1] == datetime(2026, 12, 31, 23, 40, tzinfo=UTC)
        conn.execute("drop schema serving_test cascade")
