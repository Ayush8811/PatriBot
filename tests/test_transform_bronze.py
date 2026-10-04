from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq

from patribot.transform.bronze import RUN_SCHEMA, STOP_SCHEMA, build_silver_input, build_tables

STATIONS = [
    {
        "stationCode": "HWH",
        "arrival": {"scheduled": "SRC", "actual": "SRC"},
        "departure": {"scheduled": "16:50 11-Jun", "actual": "16:55 11-Jun", "delay": "5 Min"},
    },
    {
        "stationCode": "NDLS",
        "distanceKm": "1449",
        "arrival": {"scheduled": "10:05 12-Jun", "actual": "10:13 12-Jun", "delay": "8 Min"},
        "departure": {"scheduled": "DSTN", "actual": "DSTN"},
    },
]


def env(
    train="12301", start="2026-06-11", status="ok", fetched="2026-06-12T12:00:00+00:00", payload=None, source="railkit"
):
    if payload is None and status == "ok":
        payload = {"success": True, "data": {"trainNo": train, "stations": STATIONS}}
    return {
        "schema_version": 1,
        "source": source,
        "endpoint": "x",
        "train_no": train,
        "start_date": start,
        "status": status,
        "http_status": {"ok": 200, "not_found": 404, "error": 429}[status],
        "fetched_at": fetched,
        "error": None,
        "payload": payload,
    }


def write(root: Path, name: str, records: list, source: str = "railkit", day: str = "2026-06-12") -> Path:
    path = root / "raw" / source / "running_status" / f"collected_date={day}" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for r in records:
            fh.write((r if isinstance(r, str) else json.dumps(r)) + "\n")
    return path


def test_dedupe_keeps_latest_ok_envelope_per_run(tmp_path):
    later_payload = {"success": True, "data": {"trainNo": "12301", "trainName": "LATER", "stations": STATIONS}}
    write(
        tmp_path,
        "060000Z.jsonl.gz",
        [
            env("12301", status="not_found", fetched="2026-06-12T06:00:00+00:00"),
            env("12313", fetched="2026-06-12T06:00:00+00:00"),
            env("12273", status="not_found", fetched="2026-06-12T06:00:00+00:00"),
        ],
    )
    write(
        tmp_path,
        "090000Z.jsonl.gz",
        [
            env("12301", fetched="2026-06-12T09:00:00+00:00"),  # ok after a 404
            env("12313", fetched="2026-06-12T09:00:00+00:00", payload=later_payload),  # newer ok wins
            env("12273", status="error", fetched="2026-06-12T09:00:00+00:00"),  # never ok
        ],
    )
    write(
        tmp_path,
        "120000Z.jsonl.gz",
        [env("12301", status="error", fetched="2026-06-12T12:00:00+00:00")],  # a later error does not undo ok
    )
    runs, stops, stats = build_tables(tmp_path)
    by_train = {r["train_no"]: r for r in runs.to_pylist()}

    assert by_train["12301"]["fetch_status"] == "ok" and by_train["12301"]["n_attempts"] == 3
    assert by_train["12301"]["bronze_file"].endswith("090000Z.jsonl.gz")
    assert by_train["12313"]["train_name"] == "LATER" and by_train["12313"]["n_attempts"] == 2
    assert by_train["12273"]["fetch_status"] == "error" and not by_train["12273"]["parse_ok"]
    assert by_train["12273"]["n_stations_parsed"] is None
    assert str(by_train["12301"]["first_fetched_at"]).startswith("2026-06-12 06:00")

    assert stats.runs == 3 and stats.runs_ok == 2 and stats.envelopes == 7
    assert stops.num_rows == 4  # 2 stops × 2 ok runs
    assert sorted(set(stops.column("train_no").to_pylist())) == ["12301", "12313"]


def test_bad_lines_unknown_sources_and_unparseable_payloads(tmp_path):
    write(
        tmp_path,
        "060000Z.jsonl.gz",
        [
            "{not json",
            json.dumps({"train_no": "12301"}),  # missing fields
            env("12841", payload={"success": True, "data": "oops"}),  # ok but unusable
            env("12951"),
        ],
    )
    write(tmp_path, "060000Z.jsonl.gz", [env("12301", source="fixture")], source="fixture")
    (tmp_path / "raw" / "railkit" / "running_status" / "collected_date=2026-06-12" / "070000Z.jsonl.gz").write_bytes(
        b"\x1f\x8b truncated"
    )
    runs, stops, stats = build_tables(tmp_path)
    assert stats.bad_lines == 2 and stats.bad_files == 1
    assert stats.skipped_sources == {"fixture": 1}
    assert stats.parse_failures == 1
    rows = {r["train_no"]: r for r in runs.to_pylist()}
    assert rows["12841"]["fetch_status"] == "ok" and rows["12841"]["parse_ok"] is False
    assert rows["12951"]["parse_ok"] is True
    assert stops.num_rows == 2


def test_writes_parquet_with_stable_schema_even_when_empty(tmp_path):
    out = tmp_path / "warehouse"
    stats = build_silver_input(tmp_path / "no-data", out)
    assert stats.runs == 0
    assert pq.read_schema(out / "silver_input" / "runs.parquet").equals(RUN_SCHEMA)
    assert pq.read_schema(out / "silver_input" / "stops.parquet").equals(STOP_SCHEMA)


def test_written_stops_round_trip_with_ist_timestamps(tmp_path):
    write(tmp_path, "060000Z.jsonl.gz", [env()])
    build_silver_input(tmp_path, tmp_path / "wh")
    table = pq.read_table(tmp_path / "wh" / "silver_input" / "stops.parquet")
    row = table.to_pylist()[1]
    assert row["station_code"] == "NDLS" and row["start_date"] == date(2026, 6, 11)
    assert row["act_arr"].isoformat() == "2026-06-12T10:13:00+05:30"
    assert row["arr_delay_min"] == 8 and row["is_destination"]
