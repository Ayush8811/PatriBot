from __future__ import annotations

import gzip
import json
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import httpx
import pytest

from patribot.collector.cli import main
from patribot.collector.config import CollectorSettings, WatchedTrain, load_watchlist
from patribot.collector.planner import DueRun, due_runs, make_plan, remaining_budget, sampled_in, tier_b_rate
from patribot.collector.store import DataStore, RunState
from patribot.sources.base import FetchStatus, redact
from patribot.sources.fixture import FixtureSource
from patribot.sources.indianrailapi import IndianRailApiSource

IST = ZoneInfo("Asia/Kolkata")


def train(no="12301", tier="A", dep="16:50", minutes=1050, days=None):
    kw = {"run_days": days} if days else {}
    return WatchedTrain(train_no=no, tier=tier, dep_time=time.fromisoformat(dep), journey_minutes=minutes, **kw)


# ---- due runs -----------------------------------------------------------------------------------------


def test_run_is_due_only_after_arrival_plus_grace():
    s = CollectorSettings(lookback_days=1, grace_hours=6)
    t = train(dep="16:50", minutes=1050)  # arrives 10:20 next day, due from 16:20
    before = datetime(2026, 10, 5, 16, 0, tzinfo=IST)
    after = datetime(2026, 10, 5, 16, 30, tzinfo=IST)
    assert date(2026, 10, 4) not in {r.start_date for r in due_runs([t], s, before, {})}
    assert date(2026, 10, 4) in {r.start_date for r in due_runs([t], s, after, {})}


def test_lookback_window_and_run_days():
    s = CollectorSettings(lookback_days=3, grace_hours=0)
    t = train(dep="00:00", minutes=60, days=["MON"])  # 2026-10-05 is a Monday
    now = datetime(2026, 10, 8, 12, 0, tzinfo=IST)
    assert [r.start_date for r in due_runs([t], s, now, {})] == [date(2026, 10, 5)]
    later = datetime(2026, 10, 9, 12, 0, tzinfo=IST)  # Monday now outside the 3-day window
    assert due_runs([t], s, later, {}) == []


def test_collected_and_exhausted_runs_are_skipped_retryable_are_not():
    s = CollectorSettings(lookback_days=0, grace_hours=0, max_attempts=3)
    t = train(dep="00:00", minutes=60)
    now = datetime(2026, 10, 5, 12, 0, tzinfo=IST)
    key = ("12301", date(2026, 10, 5))
    assert due_runs([t], s, now, {key: RunState(FetchStatus.OK, 1)}) == []
    assert due_runs([t], s, now, {key: RunState(FetchStatus.ERROR, 3)}) == []
    assert len(due_runs([t], s, now, {key: RunState(FetchStatus.NOT_FOUND, 2)})) == 1


# ---- budget -------------------------------------------------------------------------------------------


def test_remaining_budget_spreads_monthly_cap():
    s = CollectorSettings(max_calls_per_month=3100)
    today = date(2026, 10, 1)  # 31 days left
    assert remaining_budget(s, {}, today) == 100
    assert remaining_budget(s, {"2026-10-01": 40}, today) == 60
    # overspent earlier in the month -> smaller allowance later
    assert remaining_budget(s, {"2026-10-01": 1100}, date(2026, 10, 2)) == 2000 // 30


def test_tier_b_rate_trims_only_as_much_as_needed():
    s = CollectorSettings(max_calls_per_month=3100, max_tier_b_stride=4)  # 100/day, 95 after headroom
    a_trains = [train(f"1{i:04d}", tier="A") for i in range(50)]
    b_trains = [train(f"2{i:04d}", tier="B") for i in range(90)]
    assert tier_b_rate(a_trains + b_trains, s, date(2026, 10, 1)) == pytest.approx(45 / 90)
    assert tier_b_rate(a_trains + b_trains[:47], s, date(2026, 10, 1)) == pytest.approx(45 / 47)  # slight trim
    assert tier_b_rate(a_trains + b_trains[:40], s, date(2026, 10, 1)) == 1.0
    many_a = [train(f"1{i:04d}", tier="A") for i in range(120)]
    assert tier_b_rate(many_a + b_trains, s, date(2026, 10, 1)) == 0.25  # floor = 1 / max_tier_b_stride


def test_tier_b_rate_uses_what_is_left_of_the_month():
    s = CollectorSettings(max_calls_per_month=3100)
    trains = [train(f"2{i:04d}", tier="B") for i in range(90)]
    # half the month gone but most of the budget unused -> more room per remaining day
    assert tier_b_rate(trains, s, date(2026, 10, 16), {"2026-10-01": 100}) == 1.0
    assert tier_b_rate(trains, s, date(2026, 10, 16), {"2026-10-01": 2000}) < 1.0


def test_sampling_is_deterministic_and_proportional():
    runs = [DueRun(f"2{i:04d}", date(2026, 10, 5), "B") for i in range(4000)]
    picked = sum(sampled_in(r, 0.3) for r in runs)
    assert 0.27 * 4000 < picked < 0.33 * 4000
    assert [sampled_in(r, 0.3) for r in runs] == [sampled_in(r, 0.3) for r in runs]
    assert all(sampled_in(r, 1.0) for r in runs)


def test_plan_prioritises_tier_a_and_respects_budget():
    s = CollectorSettings(max_calls_per_month=31 * 2, lookback_days=0, grace_hours=0)  # 2 calls/day
    trains = [
        train("20001", tier="B", dep="00:00", minutes=60),
        train("10001", tier="A", dep="00:00", minutes=60),
        train("10002", tier="A", dep="00:00", minutes=60),
    ]
    plan = make_plan(trains, s, datetime(2026, 10, 1, 12, 0, tzinfo=IST), {}, {})
    assert [r.train_no for r in plan.selected] == ["10001", "10002"]
    assert plan.over_budget + plan.sampled_out == 1


# ---- storage + end to end -----------------------------------------------------------------------------


def test_store_roundtrip(tmp_path):
    store = DataStore(tmp_path)
    src = FixtureSource(missing={("12313", date(2026, 10, 4))})
    rs = [src.fetch_run_status("12301", date(2026, 10, 4)), src.fetch_run_status("12313", date(2026, 10, 4))]
    now = datetime(2026, 10, 5, 6, 0, tzinfo=ZoneInfo("UTC"))
    path = store.write_batch(rs, now, date(2026, 10, 5))
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        lines = [json.loads(x) for x in fh]
    assert {x["train_no"] for x in lines} == {"12301", "12313"}
    m = store.load_manifest()
    assert m[("12301", date(2026, 10, 4))].status is FetchStatus.OK
    assert m[("12313", date(2026, 10, 4))] == RunState(FetchStatus.NOT_FOUND, 1)
    assert store.load_usage(date(2026, 10, 5)) == {"2026-10-05": 2}


def test_cli_run_with_fixture_is_idempotent(tmp_path, capsys):
    args = ["run", "--data-dir", str(tmp_path), "--source", "fixture", "--now", "2026-10-06T12:00:00+05:30"]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["fetched"]["ok"] == first["selected"] > 0
    assert main(args) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["selected"] == 0  # everything already collected


def test_shipped_watchlist_is_valid():
    wl = load_watchlist("config/watchlist.yaml")
    assert wl.trains and all(t.tier in "AB" for t in wl.trains)


# ---- adapter ------------------------------------------------------------------------------------------


def test_indianrailapi_redacts_key_and_classifies():
    key = "SECRETKEY123"

    def handler(request: httpx.Request) -> httpx.Response:
        assert key in request.url.path
        if "12301" in request.url.path:
            return httpx.Response(200, json={"ResponseCode": "200", "Route": []})
        if "12313" in request.url.path:
            return httpx.Response(200, json={"ResponseCode": "204", "Message": "no data"})
        return httpx.Response(500, text="oops")

    src = IndianRailApiSource(key, client=httpx.Client(transport=httpx.MockTransport(handler)))
    ok = src.fetch_run_status("12301", date(2026, 10, 4))
    assert ok.status is FetchStatus.OK and key not in ok.endpoint and "20261004" in ok.endpoint
    assert src.fetch_run_status("12313", date(2026, 10, 4)).status is FetchStatus.NOT_FOUND
    err = src.fetch_run_status("12273", date(2026, 10, 4))
    assert err.status is FetchStatus.ERROR and key not in json.dumps(err.to_record())


def test_indianrailapi_requires_key():
    with pytest.raises(ValueError):
        IndianRailApiSource("")


def test_redact_generic_patterns():
    assert redact("https://x/api_key=abc&y=1", []) == "https://x/api_key=***&y=1"
    assert redact("https://x/apikey/abc/train/1", []) == "https://x/apikey/***/train/1"
