from __future__ import annotations

import json
from datetime import time
from pathlib import Path

import pytest
import yaml

from patribot.collector.config import load_watchlist
from patribot.sources.railkit_timetable import RailKitTimetableSource
from patribot.watchlist import cli

KEY = "rk_secret"
BASE_WATCHLIST = Path(__file__).resolve().parents[1] / "config" / "watchlist.yaml"
CORRIDORS = {
    "membership": {"min_km": 150, "min_consecutive_segments": 2, "exclude_train_types": ["MEMU", "DEMU", "EMU"]},
    "clusters": {"KOL": ["HWH", "SDAH"], "DEL": ["NDLS", "NZM"], "PAT": ["PNBE", "RJPB"]},
    "corridors": [
        {"id": "KOL-DEL", "a": "KOL", "b": "DEL", "paths": {"main": ["HWH", "BWN", "ASN", "DHN", "GAYA", "NDLS"]}},
        {"id": "DEL-PAT", "a": "DEL", "b": "PAT", "paths": {"main": ["NDLS", "CNB", "DDU", "PNBE"]}},
    ],
}


def populate(fake) -> None:  # tests/conftest.py FakeRailKit
    # (code, arrival, departure, halt minutes, km, day)
    fake.add(
        "12301",
        "HWH RAJDHANI",
        "RAJDHANI",
        [
            ("HWH", None, "16:50", 0, 0, 1),
            ("ASN", "18:50", "18:52", 2, 200, 1),
            ("DHN", "19:50", "19:55", 5, 259, 1),
            ("GAYA", "22:00", "22:03", 3, 458, 1),
            ("NDLS", "10:05", None, 0, 1451, 2),
        ],
        travel_time="17:15 hrs",
    )
    fake.add(  # Howrah -> New Delhi via DDU and Kanpur: member of both corridors
        "12381",
        "POORVA EXPRESS",
        "SUPERFAST",
        [
            ("HWH", None, "08:15", 0, 0, 1),
            ("ASN", "10:30", "10:35", 5, 200, 1),
            ("GAYA", "14:00", "14:05", 5, 458, 1),
            ("DDU", "17:00", "17:10", 10, 661, 1),
            ("CNB", "22:00", "22:05", 5, 1010, 1),
            ("NDLS", "05:45", None, 0, 1451, 2),
        ],
        travel_time="21:30 hrs",
    )
    fake.add(  # intermediate origin, three days a week, no travel_time: duration comes from the route
        "13331",
        "DHN NDLS EXP",
        "Mail Express",
        [("DHN", None, "21:00", 0, 0, 1), ("GAYA", "23:30", "23:35", 5, 199, 1), ("NDLS", "15:00", None, 0, 1192, 2)],
        running_days="1010100",
    )
    fake.add(  # one 95 km segment: a candidate after discovery, then not a member
        "13008", "HWH BWN EXP", "Mail Express", [("HWH", None, "07:00", 0, 0, 1), ("BWN", "08:30", None, 0, 95, 1)]
    )
    fake.add(  # reserved-looking number, but the schedule says MEMU
        "13010",
        "ASN DHN SHUTTLE",
        "MEMU",
        [("ASN", None, "06:00", 0, 0, 1), ("DHN", "07:00", "07:02", 2, 59, 1), ("GAYA", "10:00", None, 0, 258, 1)],
    )
    fake.add(  # MEMU by number: excluded during discovery, never costs a schedule call
        "63555", "ASN GAYA MEMU", "", [("ASN", None, "05:00", 0, 0, 1), ("GAYA", "10:00", None, 0, 258, 1)]
    )
    fake.add(  # unreserved only
        "22833",
        "HWH GAYA SF EXP",
        "Superfast",
        [("HWH", None, "05:00", 0, 0, 1), ("GAYA", "12:00", None, 0, 458, 1)],
        classes="GEN",
    )
    fake.add(  # passes the path with a single halt (ASN): never a candidate
        "13009",
        "XYZ ABC EXP",
        "Mail Express",
        [
            ("XYZ", None, "01:00", 0, 0, 1),
            ("ASN", "03:00", "03:05", 5, 120, 1),
            ("DHN", "04:00", "04:00", 0, 179, 1),
            ("ABC", "09:00", None, 0, 400, 1),
        ],
    )


@pytest.fixture
def setup(tmp_path, monkeypatch, fake_railkit):
    populate(fake_railkit)
    corridors = tmp_path / "corridors.yaml"
    corridors.write_text(yaml.safe_dump(CORRIDORS), encoding="utf-8")

    def factory(name, max_calls, cache_dir, run_days_order):
        return RailKitTimetableSource(
            KEY,
            client=fake_railkit.client(),
            sleep=lambda s: None,
            max_calls=max_calls,
            cache_dir=cache_dir,
            run_days_order=run_days_order,
        )

    monkeypatch.setattr(cli, "get_timetable_source", factory)

    def run(*extra: str) -> tuple[int, Path, dict]:
        out, report = tmp_path / "watchlist.yaml", tmp_path / "report.json"
        args = ["build", "--corridors", str(corridors), "--base-watchlist", str(BASE_WATCHLIST)]
        args += ["--out", str(out), "--report", str(report), "--cache-dir", str(tmp_path / "cache"), *extra]
        rc = cli.main(args)
        return rc, out, json.loads(report.read_text())

    return fake_railkit, run


def test_build_generates_collector_watchlist(setup, capsys):
    fake, run = setup
    fake.fail_stations = {"GAYA"}  # timetable fails -> between-stations fallback with DHN and NDLS
    rc, out, report = run()
    assert rc == 0

    wl = load_watchlist(out)  # the collector can load it
    assert wl.collector.max_calls_per_month == load_watchlist(BASE_WATCHLIST).collector.max_calls_per_month
    trains = {t.train_no: t for t in wl.trains}
    assert set(trains) == {"12301", "12381", "13331"}

    raj, poorva, dhn = trains["12301"], trains["12381"], trains["13331"]
    assert raj.corridors == ["KOL-DEL"] and raj.tier == "A" and raj.dep_time == time(16, 50)
    assert raj.journey_minutes == 17 * 60 + 15 and len(raj.run_days) == 7
    assert poorva.corridors == ["KOL-DEL", "DEL-PAT"] and poorva.tier == "A"  # collected once, both corridors
    assert dhn.tier == "B" and dhn.run_days == ["MON", "WED", "FRI"] and dhn.journey_minutes == 18 * 60

    # only discovery candidates cost a schedule call; MEMU-by-number, unreserved and single-halt trains do not
    assert fake.count(r"/info$") == 5
    assert fake.count(r"/between/") == 4
    d = report["discovery"]
    assert d["stations_without_timetable"] == ["GAYA"] and d["between_station_queries"] == 4
    assert d["excluded"] == {"MEMU (6xxxx)": 1, "type MEMU": 1, "unreserved classes only": 1}
    assert d["outcomes"] == {"not a member": 1}
    assert d["api_calls"] == len(fake.requests) and d["candidates"] == 5
    assert report["complete"] and report["trains"] == 3 and report["by_tier"] == {"A": 2, "B": 1}
    assert report["by_corridor"]["KOL-DEL"] == {"total": 3, "A": 2, "B": 1, "by_path": {"main": 3}}
    assert report["by_corridor"]["DEL-PAT"]["total"] == 1 and report["multi_corridor_trains"] == 1
    assert report["estimated_collection_calls_per_month"] == {"A": 60, "B": 13, "total": 73}  # (7+7+3) x 30/7
    assert json.loads(capsys.readouterr().out)["trains"] == 3
    assert "GENERATED" in out.read_text() and KEY not in out.read_text()


def test_rebuild_is_served_from_cache(setup):
    fake, run = setup
    run()
    first = len(fake.requests)
    rc, _, report = run()
    assert rc == 0 and len(fake.requests) == first and report["discovery"]["api_calls"] == 0
    assert report["discovery"]["cache_hits"] > 0 and report["trains"] == 3


def test_max_calls_guard_stops_without_writing(setup, capsys):
    fake, run = setup
    rc, out, report = run("--max-calls", "3")
    assert rc == 1 and not out.exists()
    assert len(fake.requests) == 3 and not report["complete"] and "max calls" in report["stopped"]
    assert "NOT written" in capsys.readouterr().err


def test_partial_build_can_be_written_on_request(setup):
    fake, run = setup
    n_stations = 12  # 9 distinct waypoints + 3 off-path cluster stations (SDAH, NZM, RJPB)
    rc, out, report = run("--max-calls", str(n_stations + 1), "--allow-partial", "--cache-dir", "")
    assert rc == 1 and out.exists() and report["discovery"]["candidates_unchecked"] == 4
    assert [t.train_no for t in load_watchlist(out).trains] == ["12301"]  # premium trains are checked first


def test_quota_exhausted_stops(setup):
    fake, run = setup
    fake.status_override = 429
    rc, out, report = run()
    assert rc == 1 and not out.exists() and len(fake.requests) == 1 and "429" in report["stopped"]


def test_default_collector_settings_without_base(setup, tmp_path):
    _, run = setup
    rc, out, _ = run("--base-watchlist", str(tmp_path / "missing.yaml"))
    assert rc == 0 and load_watchlist(out).collector.max_calls_per_month == 15000


def test_missing_key_is_a_clean_error(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("RAIL_API_KEY", raising=False)
    rc = cli.main(["build", "--out", str(tmp_path / "w.yaml"), "--cache-dir", ""])
    assert rc == 2 and "RAIL_API_KEY" in capsys.readouterr().err and not (tmp_path / "w.yaml").exists()
