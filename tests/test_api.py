"""API v1 (docs/api/v1.md) against a warehouse built from the synthetic sample (conftest `built_warehouse`), plus the
golden BRD queries Q1–Q3 as structural checks."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from patribot.api.app import create_app
from patribot.planner.repository import DuckDBRepository, RepositoryUnavailable
from patribot.planner.service import PlannerService

TODAY = date(2026, 12, 15)  # the sample covers runs starting 2026-12-20 .. 2027-01-02
KOLKATA = {"HWH", "SDAH", "KOAA", "SRC", "SHM"}
DELHI = {"NDLS", "DLI", "NZM", "ANVT", "DEE"}
LEG_FIELDS = {
    "train_no", "train_name", "train_type", "run_date", "from_code", "from_name", "to_code", "to_name", "dep_sched",
    "arr_sched", "arr_pred_p50", "arr_pred_p90", "journey_min_sched", "journey_min_pred_p50", "reliability",
    "history_runs", "overnight", "classes",
}  # fmt: skip
ITINERARY_FIELDS = {
    "id", "kind", "score", "score_breakdown", "why", "legs", "layover_min_sched", "layover_min_p90", "split_kind",
    "warnings", "irctc_url",
}  # fmt: skip


@pytest.fixture(scope="module")
def client(built_warehouse) -> TestClient:
    db, _, _ = built_warehouse
    service = PlannerService(DuckDBRepository(db.parent), today=lambda: TODAY)
    return TestClient(create_app(service))


def ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def post_plan(client: TestClient, **body) -> dict:
    r = client.post("/api/v1/plan", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def check_itinerary(it: dict) -> None:
    assert set(it) >= ITINERARY_FIELDS
    assert set(it["score_breakdown"]) == {"journey_time", "reliability", "preference", "transfer"}
    assert 0 <= it["score"] <= 1 and it["why"]
    for leg in it["legs"]:
        assert set(leg) >= LEG_FIELDS
        dep, arr = ts(leg["dep_sched"]), ts(leg["arr_sched"])
        p50, p90 = ts(leg["arr_pred_p50"]), ts(leg["arr_pred_p90"])
        assert leg["dep_sched"].endswith("+05:30")
        assert dep < arr and dep < p50 <= p90
        assert leg["journey_min_sched"] == round((arr - dep).total_seconds() / 60)
        assert 0 <= leg["reliability"] <= 1 and leg["history_runs"] >= 0


# ---- service endpoints ----------------------------------------------------------------------------------------


def test_health_and_openapi(client):
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok" and body["eta_model"] == "baseline_hist"
    assert body["data_as_of"].endswith("+05:30")
    spec = client.get("/api/v1/openapi.json").json()
    assert {"/api/v1/plan", "/api/v1/places/search", "/api/v1/trains/{train_no}", "/api/v1/chat"} <= set(spec["paths"])


def test_health_without_a_warehouse(tmp_path):
    c = TestClient(create_app(PlannerService(DuckDBRepository(tmp_path), today=lambda: TODAY)))
    r = c.get("/api/v1/health")
    assert r.status_code == 503 and r.json()["status"] == "unavailable"
    r = c.post("/api/v1/plan", json={"origin": "HWH", "destination": "NDLS", "date_from": "2026-12-20",
                                     "date_to": "2026-12-20"})  # fmt: skip
    assert r.status_code == 503


@pytest.mark.parametrize("origin", ["http://localhost:3000", "http://localhost:3100"])
def test_cors_allows_the_web_app(client, origin):
    r = client.options("/api/v1/plan", headers={"Origin": origin, "Access-Control-Request-Method": "POST"})  # preflight
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == origin
    r = client.get("/api/v1/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_places_search(client):
    res = client.get("/api/v1/places/search", params={"q": "kolk"}).json()["results"]
    assert res[0] == {
        "kind": "cluster", "id": "KOLKATA", "name": "Kolkata (all stations)",
        "stations": ["HWH", "SDAH", "KOAA", "SRC", "SHM"],
    }  # fmt: skip
    res = client.get("/api/v1/places/search", params={"q": "HWH"}).json()["results"]
    assert res[0] == {"kind": "station", "id": "HWH", "name": res[0]["name"], "cluster": "KOLKATA"}
    # a station outside every cluster has cluster null (the key is present)
    res = client.get("/api/v1/places/search", params={"q": "GAYA"}).json()["results"]
    gaya = next(r for r in res if r["id"] == "GAYA")
    assert "cluster" in gaya and gaya["cluster"] is None and "stations" not in gaya
    assert client.get("/api/v1/places/search", params={"q": "bombay"}).json()["results"][0]["id"] == "MUMBAI"
    assert client.get("/api/v1/places/search", params={"q": ""}).status_code == 422


def test_train_detail_and_performance(client):
    r = client.get("/api/v1/trains/12301").json()
    assert r["train_no"] == "12301" and r["origin"] == "HWH" and r["destination"] == "NDLS"
    assert "KOL-DEL" in r["corridors"] and r["classes"] == ["1A", "2A", "3A"]
    first, last = r["route"][0], r["route"][-1]
    assert first["arr"] is None and first["dep"] and last["dep"] is None and last["day"] >= 2
    assert last["history_runs"] > 0 and last["delay_p90_min"] >= last["delay_p50_min"]
    # a timetable-only train: no history, delays null
    r = client.get("/api/v1/trains/22999").json()
    assert all(s["delay_p50_min"] is None and s["delay_p90_min"] is None for s in r["route"])
    assert all(s["history_runs"] == 0 for s in r["route"])
    assert client.get("/api/v1/trains/22998").json()["running_days"] == ["MON", "WED", "FRI"]

    p = client.get("/api/v1/trains/12301/performance", params={"months": 3}).json()
    assert p["runs"] > 0 and 0 <= p["on_time_pct"] <= 100
    assert {m["month"] for m in p["by_month"]} <= {"2026-12", "2027-01"}
    assert sum(m["runs"] for m in p["by_month"]) == p["runs"]
    assert p["recent_runs"][0]["run_date"] >= p["recent_runs"][-1]["run_date"]
    assert client.get("/api/v1/trains/99999").status_code == 404
    assert client.get("/api/v1/trains/99999/performance").status_code == 404


def test_plan_errors(client):
    base = {"origin": "KOLKATA", "destination": "DELHI", "date_from": "2026-12-20", "date_to": "2026-12-20"}
    r = client.post("/api/v1/plan", json={**base, "origin": "XYZ"})
    assert r.status_code == 404 and r.json() == {"detail": "unknown place: XYZ"}
    assert client.post("/api/v1/plan", json={**base, "date_to": "2027-01-20"}).status_code == 422  # 32 days
    assert client.post("/api/v1/plan", json={**base, "date_to": "2027-01-19"}).status_code == 200  # 31 days
    assert client.post("/api/v1/plan", json={**base, "destination": "HWH"}).status_code == 422  # same place
    bad = {**base, "preferences": {"arrive_by": "9am"}}
    assert client.post("/api/v1/plan", json=bad).status_code == 422
    bad = {**base, "preferences": {"hard": ["cheapest"]}}
    assert client.post("/api/v1/plan", json=bad).status_code == 422


def test_plan_result_limits(client):
    base = {"origin": "KOLKATA", "destination": "DELHI", "date_from": "2026-12-20", "date_to": "2027-01-01"}
    body = post_plan(client, **base)
    assert body["query"]["max_results"] == 10 and len(body["itineraries"]) == 10
    body = post_plan(client, **base, max_results=500)
    assert body["query"]["max_results"] == 20 and len(body["itineraries"]) == 20


# ---- golden queries (BRD §3) ----------------------------------------------------------------------------------


def test_q1_overnight_kolkata_delhi_fastest(client):
    """Q1: suitable train Kolkata → Delhi over a date range, overnight preferred, least travel time."""
    body = post_plan(
        client, origin="Kolkata", destination="Delhi", date_from="2026-12-20", date_to="2026-12-30",
        preferences={"overnight": True, "objective": "fastest"}, max_results=5,
    )  # fmt: skip
    q, meta, its = body["query"], body["meta"], body["itineraries"]
    assert q["origin"] == "KOLKATA" and set(q["origin_stations"]) == KOLKATA and set(q["destination_stations"]) == DELHI
    assert q["origin_name"] == "Kolkata (all stations)" and q["origin_kind"] == "cluster"
    assert meta["eta_model"] == "baseline_hist" and meta["dates_searched"] == 11
    assert meta["bookable_from"] == "2026-12-15" and meta["bookable_to"] == "2027-02-13"
    assert meta["candidates_considered"] >= len(its) == 5
    for it in its:
        check_itinerary(it)
        assert it["kind"] == "direct" and it["split_kind"] is None and len(it["legs"]) == 1
        leg = it["legs"][0]
        assert leg["from_code"] in KOLKATA and leg["to_code"] in DELHI
        assert "2026-12-20" <= ts(leg["dep_sched"]).date().isoformat() <= "2026-12-30"
        assert it["id"] == f"d-{leg['train_no']}-{leg['run_date']}"
    top = its[0]
    assert top["legs"][0]["overnight"] and top["score_breakdown"]["preference"] == 1.0
    assert top["why"][0] == "Fastest predicted journey in the window"
    assert any(w.startswith("Overnight: departs") for w in top["why"])
    # the top distinct trains come first, best first
    distinct = []
    for it in its:
        if it["legs"][0]["train_no"] not in distinct:
            distinct.append(it["legs"][0]["train_no"])
    assert len(distinct) >= 3


def test_q2_must_reach_new_delhi_by_9am(client):
    """Q2: must reach New Delhi by 09:00 on a given day, from Howrah: judged on the P90 arrival."""
    day = date(2026, 12, 28)
    body = post_plan(
        client, origin="HWH", destination="NDLS", date_from=str(day - timedelta(days=2)), date_to=str(day),
        preferences={"arrive_by": "09:00", "arrive_by_date": str(day), "hard": ["arrive_by"]},
    )  # fmt: skip
    its = body["itineraries"]
    assert its, "the sample has Howrah → New Delhi trains arriving in the morning"
    deadline = datetime.fromisoformat(f"{day}T09:00:00+05:30")
    for it in its:
        check_itinerary(it)
        leg = it["legs"][-1]
        assert leg["from_code"] == "HWH" and leg["to_code"] == "NDLS"
        assert ts(leg["arr_pred_p90"]) <= deadline
        assert ts(leg["arr_sched"]) > deadline - timedelta(hours=24)
        assert any(w.startswith("Arrives by 09:00") for w in it["why"])
    # the same query on the timetable alone would also accept trains that are late at P90
    soft = post_plan(
        client, origin="HWH", destination="NDLS", date_from=str(day - timedelta(days=2)), date_to=str(day),
        preferences={"arrive_by": "09:00", "arrive_by_date": str(day)},
    )  # fmt: skip
    assert len(soft["itineraries"]) >= len(its)


def test_q3_split_journey_via_hubs(client):
    """Q3: plan a break journey on one date (a Wednesday: the sample's Mon/Wed/Fri Howrah train feeds a hub)."""
    body = post_plan(
        client, origin="KOLKATA", destination="DELHI", date_from="2026-12-23", date_to="2026-12-23",
        preferences={"allow_split": True}, max_results=20,
    )  # fmt: skip
    splits = [it for it in body["itineraries"] if it["kind"] == "split"]
    assert splits
    hubs = {"ASN", "DHN", "GAYA", "PNBE", "DDU", "PRYJ", "CNB", "LKO"}  # KOL-DEL split hubs (config/corridors.yaml)
    for it in splits:
        check_itinerary(it)
        l1, l2 = it["legs"]
        assert it["split_kind"] == "split_itinerary"
        assert l1["to_code"] == l2["from_code"] and l1["to_code"] in hubs
        assert l1["train_no"] != l2["train_no"]
        assert l1["from_code"] in KOLKATA and l2["to_code"] in DELHI
        gap_p90 = (ts(l2["dep_sched"]) - ts(l1["arr_pred_p90"])).total_seconds() / 60
        assert gap_p90 >= 45 and it["layover_min_p90"] == round(gap_p90)
        assert (ts(l2["dep_sched"]) - ts(l1["arr_pred_p50"])).total_seconds() / 60 <= 8 * 60
        assert it["layover_min_sched"] == round((ts(l2["dep_sched"]) - ts(l1["arr_sched"])).total_seconds() / 60)
        assert any("Separate tickets" in w for w in it["warnings"])
        assert it["score_breakdown"]["transfer"] < 1
        assert any(w.startswith("Change at") for w in it["why"])


# ---- chat stub ------------------------------------------------------------------------------------------------


def events(text: str) -> list[tuple[str, object]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_chat_stub_streams_tokens_then_itineraries(client):
    msg = "overnight train Kolkata to Delhi Dec 20-24, fastest"
    with client.stream("POST", "/api/v1/chat", json={"session_id": "s1", "message": msg}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        evs = events(r.read().decode())
    names = [e for e, _ in evs]
    assert names[0] == "token" and names[-3:] == ["meta", "itineraries", "done"]
    assert evs[-3][1]["eta_model"] == "baseline_hist" and evs[-3][1]["bookable_from"] == str(TODAY)
    its = evs[-2][1]
    assert its and all(it["legs"][0]["from_code"] in KOLKATA for it in its)
    assert evs[-1][1] == {"usage": {"queries_left_today": 3}}


def test_chat_stub_asks_when_something_is_missing(client):
    r = client.post("/api/v1/chat", json={"message": "train to Delhi"})
    evs = events(r.text)
    assert [e for e, _ in evs] == ["token", "done"] and "?" in evs[0][1]["text"]


def test_chat_stub_error_event_has_a_code(built_warehouse):
    class Broken(DuckDBRepository):
        def load(self):
            raise RepositoryUnavailable("warehouse locked")

    db, _, _ = built_warehouse
    c = TestClient(create_app(PlannerService(Broken(db.parent), today=lambda: TODAY)))
    evs = events(c.post("/api/v1/chat", json={"message": "Kolkata to Delhi Dec 20"}).text)
    assert evs == [("error", {"code": "server_error", "detail": "data unavailable: warehouse locked"})]
