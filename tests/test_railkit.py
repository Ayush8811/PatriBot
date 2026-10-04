from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from patribot.collector import cli
from patribot.sources.base import FetchStatus, RawResponse
from patribot.sources.railkit import RailKitSource

KEY = "rk_secret"
HISTORY = {
    "success": True,
    "data": {
        "trainNo": "12301",
        "journeyDate": "04-10-2026",
        "stations": [
            {
                "stationCode": "NDLS",
                "arrival": {"scheduled": "10:05 05-Oct", "actual": "10:13 05-Oct", "delay": "8 Min"},
                "departure": {"scheduled": "DSTN", "actual": "DSTN"},
            }
        ],
    },
}


def make_source(handler, **kw) -> RailKitSource:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return RailKitSource(KEY, client=client, sleep=lambda s: None, **kw)


def test_history_request_shape_and_ok():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=HISTORY)

    r = make_source(handler).fetch_run_status("12301", date(2026, 10, 4))
    assert r.status is FetchStatus.OK and r.payload == HISTORY
    req = seen[0]
    assert str(req.url) == "https://api.railkit.in/api/v1/trains/12301/history/04-10-2026"
    assert req.headers["x-api-key"] == KEY
    assert KEY not in json.dumps(r.to_record())  # key is in a header, never in stored records


@pytest.mark.parametrize(
    ("http_status", "body", "expected"),
    [
        (404, {"success": False, "message": "Journey not completed"}, FetchStatus.NOT_FOUND),
        (200, {"success": False, "message": "no data"}, FetchStatus.NOT_FOUND),
        (401, {"success": False, "message": "Invalid API key"}, FetchStatus.ERROR),
        (429, {"success": False, "message": "Monthly quota exceeded"}, FetchStatus.ERROR),
        (500, "upstream down", FetchStatus.ERROR),
    ],
)
def test_classification(http_status, body, expected):
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(body, dict):
            return httpx.Response(http_status, json=body)
        return httpx.Response(http_status, text=body)

    r = make_source(handler).fetch_run_status("12301", date(2026, 10, 4))
    assert r.status is expected and r.http_status == http_status
    if expected is not FetchStatus.OK:
        assert r.error and str(http_status) in r.error


def test_throttle_spaces_calls():
    t = {"now": 100.0}
    sleeps: list[float] = []

    def sleep(s: float) -> None:
        sleeps.append(s)
        t["now"] += s

    src = RailKitSource(
        KEY,
        min_interval_s=1.5,
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=HISTORY))),
        sleep=sleep,
        clock=lambda: t["now"],
    )
    src.fetch_run_status("12301", date(2026, 10, 3))
    t["now"] += 0.5
    src.fetch_run_status("12301", date(2026, 10, 4))
    assert sleeps == [pytest.approx(1.0)]


def test_run_stops_on_quota_exceeded(tmp_path, monkeypatch, capsys):
    calls: list[str] = []

    class QuotaSource:
        name = "railkit"

        def fetch_run_status(self, train_no: str, start_date: date) -> RawResponse:
            calls.append(train_no)
            status, code = (FetchStatus.OK, 200) if len(calls) < 3 else (FetchStatus.ERROR, 429)
            return RawResponse("railkit", "u", train_no, start_date, status, code, {"success": code == 200})

    monkeypatch.setattr(cli, "get_source", lambda name: QuotaSource())
    rc = cli.main(["run", "--data-dir", str(tmp_path), "--source", "railkit", "--now", "2026-10-06T12:00:00+05:30"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1 and len(calls) == 3 and out["stopped"] == "stopped after HTTP 429"
    assert out["fetched"]["ok"] == 2 and out["selected"] > 3  # remaining runs stay due for the next run
