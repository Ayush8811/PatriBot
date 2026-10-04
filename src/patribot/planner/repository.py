"""Read access to the planner's tables: the DuckDB warehouse (local dev, tests) or the Postgres `serving` schema
(the reverse-ETL copy the API reads in deployment, architecture doc §5.3).

Both implementations run the same SQL; only the table names and the driver differ. The planner works on an in-memory
`PlannerData` snapshot (a few MB for the MVP corridors), reloaded when the warehouse changes; run history for the
performance endpoint is queried on demand.

    PATRIBOT_PLANNER_BACKEND   duckdb | postgres   (default: postgres when PATRIBOT_PG_DSN is set, else duckdb)
    PATRIBOT_WAREHOUSE_DIR     DuckDB: <dir>/patribot.duckdb (default ./warehouse)
    PATRIBOT_PG_DSN            Postgres connection string
"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from patribot.planner.model import (
    Corridor,
    DelayStat,
    DelayStats,
    PlannerData,
    RunRecord,
    Station,
    Stop,
    Train,
)

DUCKDB_TABLES = {
    "dim_station": "gold.dim_station",
    "dim_station_cluster": "gold.dim_station_cluster",
    "dim_train": "gold.dim_train",
    "dim_train_schedule": "gold.dim_train_schedule",
    "corridor": "ref.seed_corridor",
    "corridor_split_hub": "ref.seed_corridor_split_hub",
    "corridor_waypoint": "ref.seed_corridor_waypoint",
    "agg_delay_stats": "gold.agg_delay_stats",
    "agg_delay_stats_all": "gold.agg_delay_stats_all",
    "agg_train_delay_stats": "gold.agg_train_delay_stats",
    "agg_corridor_delay_stats": "gold.agg_corridor_delay_stats",
    "fct_run_summary": "gold.fct_run_summary",
}
POSTGRES_TABLES = {k: f"serving.{k}" for k in DUCKDB_TABLES}


class RepositoryUnavailable(RuntimeError):
    """The warehouse or serving database cannot be read (missing, locked, not built yet)."""


class PlannerRepository(Protocol):
    def version(self) -> str | None:
        """Changes whenever the underlying data changes (None: unknown, reload on a timer)."""
        ...

    def load(self) -> PlannerData:
        """Read a full snapshot of the planner's tables."""
        ...

    def runs(self, train_no: str, since: date | None = None) -> list[RunRecord]:
        """Every attempted run of a train (newest first), optionally from `since`."""
        ...


def _split(value: Any) -> tuple[str, ...]:
    return tuple(v.strip() for v in str(value or "").split(",") if v.strip())


def _ist(value: Any) -> datetime | None:
    """A timestamp as an aware IST datetime (the API prints +05:30); naive values are taken as UTC."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(ZoneInfo("Asia/Kolkata"))


def _f(value: Any) -> float | None:
    return float(value) if value is not None else None


class SqlRepository:
    """Shared SQL; subclasses provide `_fetch` and the table-name map."""

    tables: dict[str, str] = DUCKDB_TABLES
    month_expr = "strftime(run_month, '%Y-%m')"  # 'YYYY-MM' of a date column, in the backend's dialect

    def _fetch(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:  # pragma: no cover - abstract
        raise NotImplementedError

    def version(self) -> str | None:
        return None

    def _q(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return self._fetch(sql.format(**self.tables), params)

    def load(self) -> PlannerData:
        stations = {
            r["station_code"]: Station(r["station_code"], r["station_name"], r["cluster_id"], _f(r["lat"]), _f(r["lon"]))
            for r in self._q("select station_code, station_name, cluster_id, lat, lon from {dim_station}")
        }
        clusters: dict[str, list[str]] = defaultdict(list)
        for r in self._q("select cluster_id, station_code from {dim_station_cluster} order by cluster_id, cluster_rank"):
            clusters[r["cluster_id"]].append(r["station_code"])

        stops: dict[str, list[Stop]] = defaultdict(list)
        origin_clock: dict[str, int] = {}
        for r in self._q(
            "select train_no, seq, station_code, station_name, arr_time, dep_time, day_offset, arr_min, dep_min,"
            " origin_dep_clock_min, distance_km, route_fraction, halts from {dim_train_schedule}"
            " order by train_no, seq"
        ):
            stops[r["train_no"]].append(
                Stop(
                    seq=int(r["seq"]),
                    code=r["station_code"],
                    arr_min=int(r["arr_min"]) if r["arr_min"] is not None else None,
                    dep_min=int(r["dep_min"]) if r["dep_min"] is not None else None,
                    name=r["station_name"],
                    arr_time=r["arr_time"],
                    dep_time=r["dep_time"],
                    day_offset=int(r["day_offset"] or 0),
                    distance_km=_f(r["distance_km"]),
                    route_fraction=_f(r["route_fraction"]),
                    halts=bool(r["halts"]),
                )
            )
            if r["origin_dep_clock_min"] is not None:
                origin_clock[r["train_no"]] = int(r["origin_dep_clock_min"])

        trains = {}
        for r in self._q(
            "select train_no, train_name, train_type, origin_code, destination_code, running_days, classes, route_km,"
            " corridor_ids, is_reserved from {dim_train}"
        ):
            no = r["train_no"]
            days = _split(r["running_days"])
            trains[no] = Train(
                train_no=no,
                name=r["train_name"] or no,
                stops=tuple(stops.get(no, ())),
                origin_dep_clock_min=origin_clock.get(no, 0),
                running_days=frozenset(days) if days else None,
                train_type=r["train_type"],
                origin=r["origin_code"],
                destination=r["destination_code"],
                classes=_split(r["classes"]),
                corridors=_split(r["corridor_ids"]),
                route_km=_f(r["route_km"]),
                is_reserved=bool(r["is_reserved"]) if r["is_reserved"] is not None else True,
            )

        hubs: dict[str, list[str]] = defaultdict(list)
        for r in self._q("select corridor_id, station_code from {corridor_split_hub}"):
            hubs[r["corridor_id"]].append(r["station_code"])
        waypoints: dict[str, set[str]] = defaultdict(set)
        for r in self._q("select corridor_id, station_code from {corridor_waypoint}"):
            waypoints[r["corridor_id"]].add(r["station_code"])
        corridors = {
            r["corridor_id"]: Corridor(
                r["corridor_id"],
                r["corridor_name"],
                r["cluster_a"],
                r["cluster_b"],
                tuple(hubs.get(r["corridor_id"], ())),
                frozenset(waypoints.get(r["corridor_id"], ())),
            )
            for r in self._q("select corridor_id, corridor_name, cluster_a, cluster_b from {corridor}")
        }

        def stat(r: dict[str, Any], prefix: str) -> DelayStat:
            pct = r["pct_within_30min"]
            return DelayStat(
                int(r["n_runs"]),
                float(r[f"p50_{prefix}"]),
                float(r[f"p90_{prefix}"]),
                float(pct) / 100 if pct is not None else None,
            )

        delays = DelayStats(
            stop_month={
                (r["train_no"], r["station_code"], r["period"]): stat(r, "arr_delay_min")
                for r in self._q(
                    f"select train_no, station_code, {self.month_expr} as period, n_runs,"
                    " p50_arr_delay_min, p90_arr_delay_min, pct_within_30min from {agg_delay_stats}"
                )
            },
            stop_all={
                (r["train_no"], r["station_code"]): stat(r, "arr_delay_min")
                for r in self._q(
                    "select train_no, station_code, n_runs, p50_arr_delay_min, p90_arr_delay_min, pct_within_30min"
                    " from {agg_delay_stats_all}"
                )
            },
            train={
                (r["train_no"], r["period"]): stat(r, "final_delay_min")
                for r in self._q(
                    "select train_no, period, n_runs, p50_final_delay_min, p90_final_delay_min, pct_within_30min"
                    " from {agg_train_delay_stats}"
                )
            },
            corridor={
                (r["corridor_id"], r["period"]): stat(r, "final_delay_min")
                for r in self._q(
                    "select corridor_id, period, n_runs, p50_final_delay_min, p90_final_delay_min, pct_within_30min"
                    " from {agg_corridor_delay_stats}"
                )
            },
        )
        as_of = self._q("select max(fetched_at) as as_of from {fct_run_summary}")
        return PlannerData(
            stations=stations,
            clusters={k: tuple(v) for k, v in clusters.items()},
            trains=trains,
            corridors=corridors,
            delays=delays,
            data_as_of=_ist(as_of[0]["as_of"]) if as_of else None,
        )

    def runs(self, train_no: str, since: date | None = None) -> list[RunRecord]:
        sql = (
            "select train_no, start_date, run_state, final_arr_delay_min, is_delay_target_eligible"
            " from {fct_run_summary} where train_no = ?"
        )
        params: list[Any] = [train_no]
        if since is not None:
            sql += " and start_date >= ?"
            params.append(since)
        sql += " order by start_date desc"
        return [
            RunRecord(
                r["train_no"],
                r["start_date"],
                r["run_state"],
                int(r["final_arr_delay_min"]) if r["final_arr_delay_min"] is not None else None,
                bool(r["is_delay_target_eligible"]),
            )
            for r in self._q(sql, params)
        ]


class DuckDBRepository(SqlRepository):
    """Reads `<warehouse_dir>/patribot.duckdb` read-only; each call opens and closes its own connection, so the
    file stays free for the next dbt build between calls."""

    tables = DUCKDB_TABLES

    def __init__(self, warehouse_dir: str | Path | None = None):
        wh = warehouse_dir or os.environ.get("PATRIBOT_WAREHOUSE_DIR") or "warehouse"
        self.path = Path(wh) / "patribot.duckdb"

    def version(self) -> str | None:
        try:
            st = self.path.stat()
        except OSError:
            return None
        return f"{st.st_mtime_ns}:{st.st_size}"

    def _fetch(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        import duckdb

        if not self.path.exists():
            raise RepositoryUnavailable(f"warehouse not found: {self.path} (build it with dbt first)")
        try:
            con = duckdb.connect(str(self.path), read_only=True)
        except duckdb.Error as exc:  # locked by a running dbt build, or corrupt
            raise RepositoryUnavailable(f"cannot open {self.path}: {exc}") from exc
        try:
            cur = con.execute(sql, list(params))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
        except duckdb.CatalogException as exc:
            raise RepositoryUnavailable(f"warehouse is missing a table, run dbt build: {exc}") from exc
        finally:
            con.close()


class PostgresRepository(SqlRepository):
    """Reads the reverse-ETL copy in Postgres schema `serving` (`patribot.transform.serving`)."""

    tables = POSTGRES_TABLES
    month_expr = "to_char(run_month, 'YYYY-MM')"

    def __init__(self, dsn: str | None = None, connect: Callable[[], Any] | None = None):
        self.dsn = dsn or os.environ.get("PATRIBOT_PG_DSN")
        if connect is None and not self.dsn:
            raise ValueError("PostgresRepository needs a DSN (PATRIBOT_PG_DSN)")
        self._connect = connect

    def _conn(self) -> Any:
        if self._connect is not None:
            return self._connect()
        import psycopg

        return psycopg.connect(self.dsn)

    def _fetch(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        try:
            conn = self._conn()
        except Exception as exc:  # psycopg.OperationalError and friends
            raise RepositoryUnavailable(f"cannot connect to Postgres: {type(exc).__name__}") from exc
        try:
            with conn.cursor() as cur:
                cur.execute(sql.replace("%", "%%").replace("?", "%s"), list(params))
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
        except Exception as exc:
            if type(exc).__name__ in ("UndefinedTable", "InvalidSchemaName"):
                raise RepositoryUnavailable(f"serving schema incomplete, run the reverse ETL: {exc}") from exc
            raise
        finally:
            conn.close()


def repository_from_env() -> PlannerRepository:
    backend = os.environ.get("PATRIBOT_PLANNER_BACKEND") or ("postgres" if os.environ.get("PATRIBOT_PG_DSN") else "")
    if backend.lower() == "postgres":
        return PostgresRepository()
    return DuckDBRepository()
