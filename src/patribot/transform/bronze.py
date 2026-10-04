"""Bronze loader: raw collector envelopes → Parquet silver input for dbt.

Reads every `raw/<source>/running_status/collected_date=*/*.jsonl.gz` under the data dir (layout in
`patribot.collector.store`), keeps one envelope per run key (source, train_no, start_date) and writes:

  <warehouse_dir>/silver_input/runs.parquet    one row per run key ever attempted (fetch outcome + payload header)
  <warehouse_dir>/silver_input/stops.parquet   canonical stop rows of the chosen `ok` envelope

Choice per run key: the latest `ok` envelope by `fetched_at`; if the run was never fetched successfully, the latest
envelope of any status (so not-found / error runs stay visible and can be flagged downstream).

The rebuild is full, which is fine at POC volume (gzip JSON → Arrow). To make it incremental later, cache the
parsed rows per bronze file: files are immutable once written, so a file's path identifies its content.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from patribot.transform import railkit

log = logging.getLogger(__name__)

Parser = Callable[[dict[str, Any]], railkit.ParsedRun | None]
PARSERS: dict[str, Parser] = {railkit.SOURCE: railkit.parse_envelope}
RunKey = tuple[str, str, date]  # (source, train_no, start_date)

_TS = pa.timestamp("us", tz="Asia/Kolkata")
_TS_UTC = pa.timestamp("us", tz="UTC")

STOP_SCHEMA = pa.schema(
    [
        ("source", pa.string()),
        ("train_no", pa.string()),
        ("start_date", pa.date32()),
        ("seq", pa.int32()),
        ("station_code", pa.string()),
        ("station_name", pa.string()),
        ("distance_km", pa.float64()),
        ("sched_arr", _TS),
        ("act_arr", _TS),
        ("sched_dep", _TS),
        ("act_dep", _TS),
        ("arr_delay_min", pa.int32()),
        ("dep_delay_min", pa.int32()),
        ("platform", pa.string()),
        ("is_origin", pa.bool_()),
        ("is_destination", pa.bool_()),
    ]
)

RUN_SCHEMA = pa.schema(
    [
        ("source", pa.string()),
        ("train_no", pa.string()),
        ("start_date", pa.date32()),
        ("fetch_status", pa.string()),
        ("http_status", pa.int32()),
        ("error", pa.string()),
        ("n_attempts", pa.int32()),
        ("first_fetched_at", _TS_UTC),
        ("fetched_at", _TS_UTC),
        ("bronze_file", pa.string()),
        ("parse_ok", pa.bool_()),
        ("train_name", pa.string()),
        ("journey_date", pa.date32()),
        ("origin_code", pa.string()),
        ("destination_code", pa.string()),
        ("n_stations_raw", pa.int32()),
        ("n_stations_parsed", pa.int32()),
        ("is_cancelled", pa.bool_()),
        ("last_update", _TS),
    ]
)


@dataclass
class Envelope:
    record: dict[str, Any]
    fetched_at: datetime
    file: str


@dataclass
class _Candidates:
    attempts: int = 0
    first_fetched_at: datetime | None = None
    best: Envelope | None = None
    best_ok: Envelope | None = None


@dataclass
class LoadStats:
    files: int = 0
    bad_files: int = 0
    envelopes: int = 0
    bad_lines: int = 0
    skipped_sources: dict[str, int] = field(default_factory=dict)
    runs: int = 0
    runs_ok: int = 0
    stops: int = 0
    parse_failures: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def bronze_files(data_dir: str | Path) -> list[Path]:
    return sorted(Path(data_dir).glob("raw/*/running_status/collected_date=*/*.jsonl.gz"))


def iter_envelopes(files: Iterable[Path], root: Path, stats: LoadStats) -> Iterator[Envelope]:
    for path in files:
        stats.files += 1
        rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                lines = fh.readlines()
        except (OSError, EOFError) as exc:  # truncated gzip from an interrupted commit
            log.warning("unreadable bronze file %s: %s", rel, exc)
            stats.bad_files += 1
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                fetched = datetime.fromisoformat(rec["fetched_at"])
                date.fromisoformat(rec["start_date"])
                if not isinstance(rec.get("train_no"), str) or not isinstance(rec.get("source"), str):
                    raise ValueError("train_no/source missing")
            except (ValueError, KeyError, TypeError):
                stats.bad_lines += 1
                continue
            stats.envelopes += 1
            yield Envelope(rec, fetched, rel)


def select_envelopes(envelopes: Iterable[Envelope], stats: LoadStats) -> dict[RunKey, _Candidates]:
    by_key: dict[RunKey, _Candidates] = {}
    for env in envelopes:
        rec = env.record
        if rec["source"] not in PARSERS:
            stats.skipped_sources[rec["source"]] = stats.skipped_sources.get(rec["source"], 0) + 1
            continue
        key = (rec["source"], rec["train_no"], date.fromisoformat(rec["start_date"]))
        c = by_key.setdefault(key, _Candidates())
        c.attempts += 1
        if c.first_fetched_at is None or env.fetched_at < c.first_fetched_at:
            c.first_fetched_at = env.fetched_at
        if c.best is None or env.fetched_at >= c.best.fetched_at:
            c.best = env
        if rec.get("status") == "ok" and (c.best_ok is None or env.fetched_at >= c.best_ok.fetched_at):
            c.best_ok = env
    return by_key


def build_tables(data_dir: str | Path) -> tuple[pa.Table, pa.Table, LoadStats]:
    root = Path(data_dir)
    stats = LoadStats()
    chosen = select_envelopes(iter_envelopes(bronze_files(root), root, stats), stats)

    runs: list[dict[str, Any]] = []
    stops: list[dict[str, Any]] = []
    for key in sorted(chosen):
        c = chosen[key]
        env = c.best_ok or c.best
        assert env is not None
        rec = env.record
        parsed = PARSERS[key[0]](rec) if c.best_ok else None
        if c.best_ok and parsed is None:
            stats.parse_failures += 1
        row: dict[str, Any] = {
            "source": key[0],
            "train_no": key[1],
            "start_date": key[2],
            "fetch_status": rec.get("status"),
            "http_status": rec.get("http_status") if isinstance(rec.get("http_status"), int) else None,
            "error": rec.get("error"),
            "n_attempts": c.attempts,
            "first_fetched_at": c.first_fetched_at,
            "fetched_at": env.fetched_at,
            "bronze_file": env.file,
            "parse_ok": parsed is not None,
        }
        if parsed is not None:
            h = parsed.header.to_dict()
            for col in RUN_SCHEMA.names:
                if col in h and col not in row:
                    row[col] = h[col]
            stops.extend(s.to_dict() for s in parsed.stops)
            stats.runs_ok += 1
        runs.append(row)

    stats.runs = len(runs)
    stats.stops = len(stops)
    run_table = pa.Table.from_pylist(runs, schema=RUN_SCHEMA)
    stop_table = pa.Table.from_pylist(stops, schema=STOP_SCHEMA)
    return run_table, stop_table, stats


def _write_atomic(table: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, path)


def silver_input_dir(warehouse_dir: str | Path) -> Path:
    return Path(warehouse_dir) / "silver_input"


def build_silver_input(data_dir: str | Path, warehouse_dir: str | Path) -> LoadStats:
    """Rebuild `runs.parquet` and `stops.parquet` from all bronze files. Returns load statistics."""
    runs, stops, stats = build_tables(data_dir)
    out = silver_input_dir(warehouse_dir)
    _write_atomic(runs, out / "runs.parquet")
    _write_atomic(stops, out / "stops.parquet")
    log.info("silver input: %s", stats.as_dict())
    return stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build the Parquet silver input from bronze collector files.")
    p.add_argument("--data-dir", default=os.environ.get("PATRIBOT_DATA_DIR", "data"))
    p.add_argument("--warehouse-dir", default=os.environ.get("PATRIBOT_WAREHOUSE_DIR", "warehouse"))
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stats = build_silver_input(args.data_dir, args.warehouse_dir)
    print(json.dumps(stats.as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
