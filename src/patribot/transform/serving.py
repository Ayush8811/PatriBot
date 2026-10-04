"""Reverse ETL: copy gold (and reference) tables from the DuckDB warehouse into Postgres, schema `serving`.

Every table is loaded into `<name>__load`, then all tables are swapped in by rename inside ONE transaction, so the API
never sees a half-loaded or mixed-version serving schema. RailKit-derived rows keep their `source` column (D15).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import duckdb
from psycopg import sql

log = logging.getLogger(__name__)

SERVING_SCHEMA = "serving"
BATCH_ROWS = 10_000


@dataclass(frozen=True)
class ServingTable:
    source: str  # "<duckdb schema>.<table>"
    target: str  # table name in the serving schema
    primary_key: tuple[str, ...] = ()


SERVING_TABLES: tuple[ServingTable, ...] = (
    ServingTable("gold.dim_station", "dim_station", ("station_code",)),
    ServingTable("gold.dim_station_cluster", "dim_station_cluster", ("station_code",)),
    ServingTable("gold.dim_train", "dim_train", ("train_no",)),
    ServingTable("gold.fct_run_summary", "fct_run_summary", ("run_id",)),
    ServingTable("gold.fct_run_stop_delay", "fct_run_stop_delay", ("run_stop_id",)),
    ServingTable("gold.agg_delay_stats", "agg_delay_stats", ("delay_stat_id",)),
    # planner (Phase 2): timetable, corridor membership and the ETA baseline's fallback levels
    ServingTable("gold.dim_train_schedule", "dim_train_schedule", ("train_stop_id",)),
    ServingTable("gold.dim_train_corridor", "dim_train_corridor", ("train_corridor_id",)),
    ServingTable("gold.agg_delay_stats_all", "agg_delay_stats_all", ("delay_stat_id",)),
    ServingTable("gold.agg_train_delay_stats", "agg_train_delay_stats", ("train_delay_stat_id",)),
    ServingTable("gold.agg_corridor_delay_stats", "agg_corridor_delay_stats", ("corridor_delay_stat_id",)),
    ServingTable("gold.dim_date", "dim_date", ("date_day",)),
    ServingTable("ref.seed_corridor", "corridor", ("corridor_id",)),
    ServingTable("ref.seed_corridor_waypoint", "corridor_waypoint", ("corridor_id", "path_name", "waypoint_seq")),
    ServingTable("ref.seed_corridor_split_hub", "corridor_split_hub", ("corridor_id", "station_code")),
)

_SIMPLE_TYPES = {
    "VARCHAR": "text",
    "BOOLEAN": "boolean",
    "TINYINT": "smallint",
    "SMALLINT": "smallint",
    "INTEGER": "integer",
    "BIGINT": "bigint",
    "HUGEINT": "numeric",
    "UTINYINT": "smallint",
    "USMALLINT": "integer",
    "UINTEGER": "bigint",
    "UBIGINT": "numeric",
    "FLOAT": "real",
    "DOUBLE": "double precision",
    "DATE": "date",
    "TIME": "time",
    "TIMESTAMP": "timestamp",
    "TIMESTAMP WITH TIME ZONE": "timestamptz",
    "INTERVAL": "interval",
    "UUID": "uuid",
    "JSON": "jsonb",
}


def pg_type(duck_type: str) -> str:
    """Map a DuckDB column type to a Postgres type. Unknown or nested types fall back to text."""
    t = duck_type.upper().strip()
    if t in _SIMPLE_TYPES:
        return _SIMPLE_TYPES[t]
    if m := re.fullmatch(r"DECIMAL\((\d+),\s*(\d+)\)", t):
        return f"numeric({m[1]},{m[2]})"
    if t.startswith("TIMESTAMP_") or t.startswith("TIMESTAMP("):
        return "timestamp"
    return "text"


class PgConnection(Protocol):
    """The subset of `psycopg.Connection` used here (lets tests pass a fake)."""

    def cursor(self) -> Any: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


@dataclass
class TableSync:
    source: str
    target: str
    rows: int


def _columns(duck: duckdb.DuckDBPyConnection, schema: str, table: str) -> list[tuple[str, str]]:
    rows = duck.execute(
        "select column_name, data_type from information_schema.columns "
        "where table_schema = ? and table_name = ? order by ordinal_position",
        [schema, table],
    ).fetchall()
    return [(name, dtype) for name, dtype in rows]


def sync_to_postgres(
    duckdb_path: str | Path,
    connect: Callable[[], PgConnection],
    tables: tuple[ServingTable, ...] = SERVING_TABLES,
    schema: str = SERVING_SCHEMA,
) -> list[TableSync]:
    """Copy `tables` from the DuckDB file into Postgres `schema`, swapping them in atomically."""
    duck = duckdb.connect(str(duckdb_path), read_only=True)
    pg = connect()
    results: list[TableSync] = []
    try:
        with pg.cursor() as cur:
            cur.execute(sql.SQL("create schema if not exists {}").format(sql.Identifier(schema)))
            for t in tables:
                src_schema, src_name = t.source.split(".", 1)
                cols = _columns(duck, src_schema, src_name)
                if not cols:
                    raise LookupError(f"warehouse table {t.source} not found; run dbt build first")
                load = f"{t.target}__load"
                cur.execute(sql.SQL("drop table if exists {}.{}").format(sql.Identifier(schema), sql.Identifier(load)))
                col_defs = sql.SQL(", ").join(
                    sql.SQL("{} {}").format(sql.Identifier(c), sql.SQL(pg_type(t))) for c, t in cols
                )
                cur.execute(
                    sql.SQL("create table {}.{} ({})").format(sql.Identifier(schema), sql.Identifier(load), col_defs)
                )
                copy_stmt = sql.SQL("copy {}.{} ({}) from stdin").format(
                    sql.Identifier(schema),
                    sql.Identifier(load),
                    sql.SQL(", ").join(sql.Identifier(c) for c, _ in cols),
                )
                n = 0
                # identifiers come from SERVING_TABLES (code), never from user input
                result = duck.execute(f'select * from "{src_schema}"."{src_name}"')
                with cur.copy(copy_stmt) as copy:
                    while batch := result.fetchmany(BATCH_ROWS):
                        for row in batch:
                            copy.write_row(row)
                        n += len(batch)
                results.append(TableSync(t.source, f"{schema}.{t.target}", n))
                log.info("loaded %s → %s.%s (%d rows)", t.source, schema, load, n)

            for t in tables:
                name, pk = t.target, t.primary_key
                cur.execute(sql.SQL("drop table if exists {}.{}").format(sql.Identifier(schema), sql.Identifier(name)))
                cur.execute(
                    sql.SQL("alter table {}.{} rename to {}").format(
                        sql.Identifier(schema), sql.Identifier(f"{name}__load"), sql.Identifier(name)
                    )
                )
                if pk:
                    cur.execute(
                        sql.SQL("alter table {}.{} add primary key ({})").format(
                            sql.Identifier(schema),
                            sql.Identifier(name),
                            sql.SQL(", ").join(sql.Identifier(c) for c in pk),
                        )
                    )
        pg.commit()
    except Exception:
        pg.rollback()
        raise
    finally:
        pg.close()
        duck.close()
    return results


def psycopg_connect(dsn: str) -> Callable[[], PgConnection]:
    import psycopg

    return lambda: psycopg.connect(dsn)
