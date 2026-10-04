"""Planner unit tests on hand-built timetables: overnight edges, run dates when boarding mid-route, split buffer
maths, hard arrive-by on P90, ETA fallbacks, ranking and the request limits."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from pydantic import ValidationError

from patribot.planner.eta import MIN_RUNS, NO_HISTORY_RELIABILITY, estimate_delay, prob_within
from patribot.planner.model import Corridor, DelayStat, DelayStats, PlannerData, Station, Stop, Train
from patribot.planner.plan import plan
from patribot.planner.rank import assess
from patribot.planner.schemas import MAX_RESULTS, PlanRequest, Preferences
from patribot.planner.search import (
    IST,
    Candidate,
    EtaCache,
    LegOption,
    PlannerConfig,
    direct_options,
    is_overnight,
    run_dates_for,
    split_options,
)
from patribot.planner.trains import train_detail

MON = date(2026, 11, 23)  # a Monday


def ist(d: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(d, time(h, m), IST)


def make_train(
    no: str,
    origin_dep: str,
    stops: list[tuple[str, int | None, int | None]],
    days: tuple[str, ...] | None = None,
    corridors: tuple[str, ...] = ("KOL-DEL",),
    classes: tuple[str, ...] = ("2A", "3A"),
) -> Train:
    """stops: (code, arr_min, dep_min) as minutes after the origin departure (None at the ends)."""
    h, m = map(int, origin_dep.split(":"))
    clock = h * 60 + m
    last = max(a or d or 0 for _, a, d in stops)
    out = []
    for i, (code, arr, dep) in enumerate(stops, 1):
        t = arr if arr is not None else dep or 0
        out.append(
            Stop(
                seq=i,
                code=code,
                arr_min=arr,
                dep_min=dep,
                name=code.title(),
                day_offset=(clock + t) // 1440,
                route_fraction=t / last if last else 0.0,
            )
        )
    return Train(
        train_no=no,
        name=f"Train {no}",
        stops=tuple(out),
        origin_dep_clock_min=clock,
        running_days=frozenset(days) if days else None,
        origin=stops[0][0],
        destination=stops[-1][0],
        classes=classes,
        corridors=corridors,
    )


def make_data(trains: list[Train], delays: DelayStats | None = None, hubs: tuple[str, ...] = ("HUB",)) -> PlannerData:
    clusters = {"AAA": ("A1", "A2"), "BBB": ("B1",)}
    codes = {s.code for t in trains for s in t.stops} | {"A1", "A2", "B1"}
    cluster_of = {c: k for k, v in clusters.items() for c in v}
    return PlannerData(
        stations={c: Station(c, c.title(), cluster_of.get(c)) for c in codes},
        clusters=clusters,
        trains={t.train_no: t for t in trains},
        corridors={"KOL-DEL": Corridor("KOL-DEL", "A ↔ B", "AAA", "BBB", hubs, frozenset({"HUB", "MID"}))},
        delays=delays or DelayStats(),
    )


def stat(n: int, p50: float, p90: float, pct: float | None = None) -> DelayStat:
    return DelayStat(n, p50, p90, pct)


# ---- FR-6 overnight -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dep", "arr", "nights", "expected"),
    [
        ("16:00", "04:00", 1, True),  # both window edges are inclusive
        ("23:59", "11:00", 1, True),
        ("15:59", "08:00", 1, False),  # departs before the evening window
        ("20:00", "11:01", 1, False),  # arrives after the morning window
        ("20:00", "03:59", 1, False),  # arrives before it
        ("20:00", "06:00", 2, True),  # after two nights: still at least one
        ("16:30", "23:00", 0, False),  # same day
    ],
)
def test_overnight_window_edges(dep, arr, nights, expected):
    assert is_overnight(ist(MON, dep), ist(MON + timedelta(days=nights), arr)) is expected


# ---- running days and day offsets -----------------------------------------------------------------------------


def test_intermediate_boarding_uses_the_run_date_of_the_origin():
    # leaves A1 at 22:00 on Mondays only; departs MID at 01:30 (Tuesday), reaches B1 at 06:00 Tuesday
    t = make_train("12345", "22:00", [("A1", None, 0), ("MID", 200, 210), ("B1", 480, None)], days=("MON",))
    mid = t.stops[1]
    assert list(run_dates_for(t, mid, [MON])) == []  # no Sunday run
    assert list(run_dates_for(t, mid, [MON + timedelta(days=1)])) == [MON]
    data = make_data([t])
    opts = direct_options(data, frozenset({"MID"}), frozenset({"B1"}), [MON + timedelta(days=1)], EtaCache(data.delays))
    assert len(opts) == 1
    leg = opts[0]
    assert leg.run_date == MON
    assert leg.dep == ist(MON + timedelta(days=1), "01:30")
    assert leg.arr == ist(MON + timedelta(days=1), "06:00")
    assert leg.journey_min_sched == 270


def test_board_at_the_last_origin_cluster_halt():
    t = make_train("12346", "08:00", [("A1", None, 0), ("A2", 30, 35), ("B1", 600, None)])
    data = make_data([t])
    (leg,) = direct_options(data, frozenset({"A1", "A2"}), frozenset({"B1"}), [MON], EtaCache(data.delays))
    assert leg.board.code == "A2" and leg.dep == ist(MON, "08:35")


def test_wrong_direction_and_non_running_day_are_skipped():
    up = make_train("12347", "08:00", [("B1", None, 0), ("A1", 600, None)])
    weekend = make_train("12348", "08:00", [("A1", None, 0), ("B1", 600, None)], days=("SAT", "SUN"))
    data = make_data([up, weekend])
    assert direct_options(data, frozenset({"A1"}), frozenset({"B1"}), [MON], EtaCache(data.delays)) == []


# ---- FR-7 split buffer maths ----------------------------------------------------------------------------------


def _split_data():
    # leg 1 arrives at HUB at 12:00 with P50 +10 and P90 +60 (from its own history at HUB)
    leg1 = make_train("11111", "08:00", [("A1", None, 0), ("HUB", 240, None)])
    # leg-2 candidates departing HUB at various times (each runs daily, HUB is its origin)
    deps = {"22201": "13:44", "22202": "13:45", "22203": "20:10", "22204": "20:11"}
    leg2 = [make_train(no, d, [("HUB", None, 0), ("B1", 300, None)]) for no, d in deps.items()]
    delays = DelayStats(stop_all={("11111", "HUB"): stat(20, 10, 60, 0.6)})
    return make_data([leg1, *leg2], delays), deps


def test_split_leg2_window_is_p90_plus_buffer_to_p50_plus_max_layover():
    data, _ = _split_data()
    cfg = PlannerConfig(leg2_options_per_leg1=10)
    cands = split_options(data, frozenset({"A1"}), frozenset({"B1"}), [MON], EtaCache(data.delays), cfg)
    got = {c.legs[1].train.train_no for c in cands}
    # lo = 12:00 + 60 (P90) + 45 = 13:45; hi = 12:00 + 10 (P50) + 480 = 20:10
    assert got == {"22202", "22203"}
    c = next(c for c in cands if c.legs[1].train.train_no == "22202")
    assert c.hub == "HUB" and c.kind == "split"
    assert c.layover_min_sched == 105 and c.layover_min_p90 == 45
    assert 0 < c.connect_prob < 1


def test_split_itinerary_is_labelled_and_warned():
    data, _ = _split_data()
    req = PlanRequest(
        origin="AAA", destination="BBB", date_from=MON, date_to=MON, preferences=Preferences(allow_split=True)
    )
    res = plan(data, req, today=MON - timedelta(days=10))
    splits = [it for it in res.itineraries if it.kind == "split"]
    assert splits
    for it in splits:
        assert it.split_kind == "split_itinerary"
        assert any("Separate tickets" in w for w in it.warnings)
        assert it.score_breakdown.transfer < 1.0
        assert it.layover_min_sched is not None and it.layover_min_p90 is not None
        assert it.legs[1].dep_sched >= it.legs[0].arr_pred_p90 + timedelta(minutes=45)
    # without allow_split there is nothing (no direct train)
    req2 = req.model_copy(update={"preferences": Preferences(allow_split=False)})
    assert plan(data, req2, today=MON).itineraries == []


def test_split_drops_legs_whose_train_runs_origin_to_destination_itself():
    data, _ = _split_data()
    # a through train A1 -> HUB -> B1: as leg 1 you would stay on it, as leg 2 you would board it at A1
    through = make_train("12345", "06:00", [("A1", None, 0), ("HUB", 300, 310), ("B1", 600, None)])
    data = make_data([*data.trains.values(), through], data.delays)
    cfg = PlannerConfig(leg2_options_per_leg1=10)
    cands = split_options(data, frozenset({"A1"}), frozenset({"B1"}), [MON], EtaCache(data.delays), cfg)
    assert cands  # the genuine splits (11111 then 2220x) survive
    assert all("12345" not in {leg.train.train_no for leg in c.legs} for c in cands)


# ---- hard and soft constraints --------------------------------------------------------------------------------


def _arrive_by_data():
    # scheduled arrival 08:00 the next morning; history: P50 +30, P90 +70 → P90 arrival 09:10
    late = make_train("12001", "20:00", [("A1", None, 0), ("B1", 720, None)])
    # scheduled 07:00, P90 +20 → 07:20
    early = make_train("12002", "19:00", [("A1", None, 0), ("B1", 720, None)])
    delays = DelayStats(stop_all={("12001", "B1"): stat(30, 30, 70, 0.5), ("12002", "B1"): stat(30, 5, 20, 0.95)})
    return make_data([late, early], delays)


def test_hard_arrive_by_is_judged_on_p90():
    data = _arrive_by_data()
    hard = PlanRequest(
        origin="A1", destination="B1", date_from=MON, date_to=MON,
        preferences=Preferences(arrive_by="09:00", hard=["arrive_by"]),
    )  # fmt: skip
    res = plan(data, hard, today=MON)
    assert [it.legs[0].train_no for it in res.itineraries] == ["12002"]
    assert res.itineraries[0].legs[0].arr_pred_p90 <= ist(MON + timedelta(days=1), "09:00")
    # soft: both are returned, the one late at P90 (on time at P50) scores half on preference
    soft = hard.model_copy(update={"preferences": Preferences(arrive_by="09:00")})
    res = plan(data, soft, today=MON)
    pref = {it.legs[0].train_no: it.score_breakdown.preference for it in res.itineraries}
    assert pref == {"12002": 1.0, "12001": 0.5}


def test_hard_overnight_and_classes_filter():
    data = _arrive_by_data()
    t = make_train("12003", "10:00", [("A1", None, 0), ("B1", 600, None)], classes=("CC",))
    data = make_data([*data.trains.values(), t], data.delays)
    req = PlanRequest(
        origin="A1", destination="B1", date_from=MON, date_to=MON,
        preferences=Preferences(overnight=True, classes=["3A"], hard=["overnight", "classes"]),
    )  # fmt: skip
    nos = {it.legs[0].train_no for it in plan(data, req, today=MON).itineraries}
    assert nos == {"12001", "12002"}


def test_assess_marks_unknown_classes_without_failing_a_hard_filter():
    t = make_train("12004", "20:00", [("A1", None, 0), ("B1", 720, None)], classes=())
    data = make_data([t])
    (leg,) = direct_options(data, frozenset({"A1"}), frozenset({"B1"}), [MON], EtaCache(data.delays))
    a = assess(Candidate((leg,)), Preferences(classes=["3A"], hard=["classes"]), PlannerConfig())
    assert a.hard_ok and a.met["classes"] == 0.5 and a.warnings


# ---- ranking, explanations, ARP -------------------------------------------------------------------------------


def test_ranking_breakdown_why_and_booking_window():
    data = _arrive_by_data()
    req = PlanRequest(
        origin="AAA", destination="BBB", date_from=MON, date_to=MON + timedelta(days=1),
        preferences=Preferences(objective="fastest", overnight=True),
    )  # fmt: skip
    today = MON - timedelta(days=60)  # MON is the last bookable date; MON + 1 is plan-only
    res = plan(data, req, today=today)
    assert res.meta.bookable_from == today and res.meta.bookable_to == today + timedelta(days=60)
    assert res.meta.dates_searched == 2 and res.meta.candidates_considered == 4
    # diversified: the best date of each train first (by score), then the other dates (by score)
    scores = [it.score for it in res.itineraries]
    assert len({it.legs[0].train_no for it in res.itineraries[:2]}) == 2
    assert scores[:2] == sorted(scores[:2], reverse=True) and scores[2:] == sorted(scores[2:], reverse=True)
    for it in res.itineraries:
        assert set(it.score_breakdown.model_dump()) == {"journey_time", "reliability", "preference", "transfer"}
        assert 0 <= it.score <= 1 and it.why
        assert it.legs[0].overnight
        beyond = it.legs[0].run_date > res.meta.bookable_to
        assert beyond == any("booking window" in w for w in it.warnings)
    assert any(it.legs[0].run_date > res.meta.bookable_to for it in res.itineraries)
    # fastest predicted: 12002 (12 h, +5 min P50) beats 12001 (12 h, +30 min)
    assert res.itineraries[0].legs[0].train_no == "12002"
    assert res.itineraries[0].why[0] == "Fastest predicted journey in the window"


def test_unknown_and_same_place():
    from patribot.planner.places import UnknownPlace
    from patribot.planner.plan import SamePlace

    data = _arrive_by_data()
    with pytest.raises(UnknownPlace):
        plan(data, PlanRequest(origin="XYZ", destination="B1", date_from=MON, date_to=MON), today=MON)
    with pytest.raises(SamePlace):
        plan(data, PlanRequest(origin="AAA", destination="A2", date_from=MON, date_to=MON), today=MON)


def test_request_limits():
    assert PlanRequest(origin="A", destination="B", date_from=MON, date_to=MON).max_results == 10
    assert PlanRequest(origin="A", destination="B", date_from=MON, date_to=MON, max_results=50).max_results == 20
    assert MAX_RESULTS == 20
    PlanRequest(origin="A", destination="B", date_from=MON, date_to=MON + timedelta(days=30))  # 31 days: ok
    with pytest.raises(ValidationError):
        PlanRequest(origin="A", destination="B", date_from=MON, date_to=MON + timedelta(days=31))
    with pytest.raises(ValidationError):
        PlanRequest(origin="A", destination="B", date_from=MON, date_to=MON - timedelta(days=1))
    with pytest.raises(ValidationError):
        PlanRequest(origin="A", destination="B", date_from=MON, date_to=MON, max_results=0)


# ---- ETA baseline fallbacks -----------------------------------------------------------------------------------


def test_eta_month_level_wins_when_it_has_enough_runs():
    s = DelayStats(
        stop_month={("1", "X", "2026-11"): stat(MIN_RUNS, 40, 90, 0.4)},
        stop_all={("1", "X"): stat(50, 10, 30, 0.9)},
    )
    e = estimate_delay(s, "1", "X", "2026-11", 1.0)
    assert (e.p50, e.p90, e.reliability, e.history_runs, e.basis) == (40, 90, 0.4, MIN_RUNS, "train_station_month")
    # a thin month falls back to all months
    s2 = DelayStats(
        stop_month={("1", "X", "2026-11"): stat(MIN_RUNS - 1, 40, 90, 0.4)},
        stop_all={("1", "X"): stat(50, 10, 30, 0.9)},
    )
    e = estimate_delay(s2, "1", "X", "2026-11", 1.0)
    assert (e.p50, e.history_runs, e.basis) == (10, 50, "train_station")


def test_eta_shrinks_thin_station_history_toward_the_route_scaled_train_prior():
    s = DelayStats(stop_all={("1", "X"): stat(2, 20, 40, 1.0)}, train={("1", "all"): stat(10, 60, 120, 0.3)})
    prior = estimate_delay(DelayStats(train=s.train), "1", "X", None, 0.5)
    assert prior.basis == "train_route_scaled" and prior.history_runs == 10
    assert (prior.p50, prior.p90) == (30, 60)  # scaled by the route fraction
    e = estimate_delay(s, "1", "X", None, 0.5)
    w = 2 / (2 + 5)
    assert e.basis == "train_station_shrunk" and e.history_runs == 2
    assert e.p50 == pytest.approx(w * 20 + (1 - w) * 30)
    assert e.p90 >= e.p50
    assert e.reliability == pytest.approx(w * 1.0 + (1 - w) * prior.reliability)


def test_eta_corridor_then_zero_fallback():
    s = DelayStats(corridor={("KOL-DEL", "all"): stat(100, 20, 80, 0.7)})
    e = estimate_delay(s, "9", "X", "2026-11", 1.0, ("KOL-DEL",))
    assert e.basis == "corridor_route_scaled" and e.history_runs == 0 and (e.p50, e.p90) == (20, 80)
    # borrowed reliability is pulled halfway to "no evidence"
    assert e.reliability == pytest.approx(0.5 * 0.7 + 0.5 * NO_HISTORY_RELIABILITY)
    e = estimate_delay(DelayStats(), "9", "X", "2026-11", 1.0, ("KOL-DEL",))
    assert (e.p50, e.p90, e.reliability, e.history_runs, e.basis) == (0, 0, NO_HISTORY_RELIABILITY, 0, "none")


def test_prob_within_is_a_normal_fit():
    assert prob_within(30, 30) == 1.0 and prob_within(31, 31) == 0.0
    assert prob_within(30, 60) == pytest.approx(0.5)
    assert 0.7 < prob_within(0, 60) < 0.8  # sigma = 60 / 1.28


def test_leg_predictions_never_precede_departure_and_p90_not_below_p50():
    t = make_train("12005", "08:00", [("A1", None, 0), ("B1", 60, None)])
    s = DelayStats(stop_all={("12005", "B1"): stat(10, -120, -100, 1.0)})  # absurdly early
    leg = LegOption(t, t.stops[0], t.stops[1], MON, estimate_delay(s, "12005", "B1", None, 1.0))
    assert leg.arr_p50 > leg.dep and leg.arr_p90 >= leg.arr_p50


def test_train_detail_has_null_delays_without_history():
    t = make_train("12006", "08:00", [("A1", None, 0), ("B1", 60, None)], days=("MON", "FRI"))
    s = DelayStats(stop_all={("12006", "B1"): stat(10, 5, 15, 0.9)}, corridor={("KOL-DEL", "all"): stat(50, 1, 2)})
    d = train_detail(make_data([t], s), "12006", MON)
    assert d.running_days == ["MON", "FRI"]
    origin, dest = d.route
    assert (dest.delay_p50_min, dest.delay_p90_min, dest.history_runs) == (5, 15, 10)
    # the origin has no history of its own: a corridor fallback estimate exists but is not shown per stop
    assert (origin.delay_p50_min, origin.delay_p90_min, origin.history_runs) == (None, None, 0)
