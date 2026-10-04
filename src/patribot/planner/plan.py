"""`plan()`: a PlanRequest → ranked, explained itineraries (API `POST /plan`, docs/api/v1.md). Deterministic: every
train, time and rule comes from the warehouse; nothing is invented (CLAUDE.md)."""

from __future__ import annotations

from datetime import date, timedelta

from patribot.planner.eta import DelayEstimate
from patribot.planner.model import PlannerData
from patribot.planner.places import resolve
from patribot.planner.rank import Assessment, assess, score_all, select
from patribot.planner.schemas import (
    ETA_MODEL,
    Itinerary,
    Leg,
    PlanMeta,
    PlanRequest,
    PlanResponse,
    ScoreBreakdown,
)
from patribot.planner.search import (
    DEFAULT_CONFIG,
    Candidate,
    EtaCache,
    LegOption,
    PlannerConfig,
    date_range,
    direct_options,
    is_overnight,
    split_options,
)

BASIS_TEXT = {
    "train_station_month": "this train's history at this station in the same month",
    "train_station": "this train's history at this station",
    "train_station_shrunk": "this train's short history at this station, blended with its overall delays",
    "train_route_scaled": "this train's average delay, scaled to the distance travelled",
    "corridor_route_scaled": "other trains on the corridor, scaled to the distance travelled",
    "none": "the timetable only",
}
SPLIT_WARNING = (
    "Separate tickets: if leg 1 runs late and you miss leg 2, the leg-2 ticket is not refunded or rebooked "
    "(no through-ticket protection)"
)


class SamePlace(ValueError):
    pass


def fmt_minutes(minutes: int) -> str:
    sign = "-" if minutes < 0 else ""
    h, m = divmod(abs(int(minutes)), 60)
    return f"{sign}{h} h {m:02d} min" if h else f"{sign}{m} min"


def bookable_window(today: date, cfg: PlannerConfig = DEFAULT_CONFIG) -> tuple[date, date]:
    return today, today + timedelta(days=cfg.arp_days)


def plan(data: PlannerData, req: PlanRequest, today: date, cfg: PlannerConfig = DEFAULT_CONFIG) -> PlanResponse:
    """Raises places.UnknownPlace (→ 404) and SamePlace (→ 422)."""
    prefs = req.preferences
    origin, dest = resolve(data, req.origin), resolve(data, req.destination)
    o_set, d_set = frozenset(origin.stations), frozenset(dest.stations)
    if o_set & d_set:
        raise SamePlace("origin and destination are the same place")
    dates = date_range(req.date_from, req.date_to)
    etas = EtaCache(data.delays)

    candidates = [Candidate((leg,)) for leg in direct_options(data, o_set, d_set, dates, etas)]
    if prefs.allow_split:
        candidates += split_options(data, o_set, d_set, dates, etas, cfg)
    kept = [a for a in (assess(c, prefs, cfg) for c in candidates) if a.hard_ok]
    score_all(kept, prefs.objective)
    chosen = select(kept, req.max_results)

    book_from, book_to = bookable_window(today, cfg)
    fastest = min((a.candidate.journey_min_p50 for a in kept), default=0)
    most_reliable = max((a.candidate.reliability for a in kept), default=0.0)
    itineraries = [
        _itinerary(data, a, prefs, cfg, today, book_to, fastest, most_reliable, req.preferences.objective)
        for a in chosen
    ]
    query = req.model_dump(mode="json")
    query.update(
        origin=origin.id,
        destination=dest.id,
        origin_kind=origin.kind,
        destination_kind=dest.kind,
        origin_name=origin.name,
        destination_name=dest.name,
        origin_stations=list(origin.stations),
        destination_stations=list(dest.stations),
    )
    return PlanResponse(
        query=query,
        itineraries=itineraries,
        meta=PlanMeta(
            eta_model=ETA_MODEL,
            data_as_of=data.data_as_of,
            dates_searched=len(dates),
            candidates_considered=len(candidates),
            bookable_from=book_from,
            bookable_to=book_to,
        ),
    )


def make_leg(data: PlannerData, leg: LegOption, cfg: PlannerConfig = DEFAULT_CONFIG) -> Leg:
    t, est = leg.train, leg.eta
    return Leg(
        train_no=t.train_no,
        train_name=t.name,
        train_type=t.train_type,
        run_date=leg.run_date,
        from_code=leg.board.code,
        from_name=leg.board.name or data.station_name(leg.board.code),
        to_code=leg.alight.code,
        to_name=leg.alight.name or data.station_name(leg.alight.code),
        dep_sched=leg.dep,
        arr_sched=leg.arr,
        arr_pred_p50=leg.arr_p50,
        arr_pred_p90=leg.arr_p90,
        journey_min_sched=leg.journey_min_sched,
        journey_min_pred_p50=leg.journey_min_p50,
        reliability=round(est.reliability, 3),
        history_runs=est.history_runs,
        overnight=is_overnight(leg.dep, leg.arr, cfg),
        classes=list(t.classes),
        eta_basis=est.basis,
    )


def _reliability_why(est: DelayEstimate, train_no: str) -> str:
    if est.history_runs > 0:
        return (
            f"Train {train_no}: {round(est.reliability * 100)}% chance of arriving within 30 min of schedule "
            f"({est.history_runs} past runs)"
        )
    return f"Train {train_no}: no delay history yet, so the estimate uses {BASIS_TEXT.get(est.basis, est.basis)}"


def _itinerary(
    data: PlannerData,
    a: Assessment,
    prefs,
    cfg: PlannerConfig,
    today: date,
    bookable_to: date,
    fastest: int,
    most_reliable: float,
    objective: str,
) -> Itinerary:
    c = a.candidate
    why: list[str] = []
    if c.journey_min_p50 <= fastest:
        why.append("Fastest predicted journey in the window")
    else:
        why.append(
            f"Predicted journey {fmt_minutes(c.journey_min_p50)} "
            f"({fmt_minutes(c.journey_min_p50 - fastest)} longer than the fastest)"
        )
    if objective != "fastest" and c.reliability >= most_reliable - 1e-9:
        why.append("Most reliable option found")
    if c.overnight(cfg):
        why.append(f"Overnight: departs {c.first.dep:%H:%M}, arrives ~{c.last.arr_p50:%H:%M}")
    if prefs.arrive_by and a.met.get("arrive_by") == 1.0:
        p90 = c.last.arr_p90
        if prefs.arrive_by_date:
            on = f" on {prefs.arrive_by_date:%d %b}"
            p90_text = f"{p90:%H:%M}" if p90.date() == prefs.arrive_by_date else f"{p90:%d %b %H:%M}"
        else:
            on, p90_text = "", f"{p90:%H:%M}"
        why.append(f"Arrives by {prefs.arrive_by}{on} even when late (P90 ~{p90_text})")
    if c.kind == "split":
        hub = data.station_name(c.hub or "")
        why.append(
            f"Change at {hub}: {fmt_minutes(c.layover_min_sched or 0)} layover, "
            f"{fmt_minutes(c.layover_min_p90 or 0)} to spare after a late (P90) arrival"
        )
    for leg in c.legs:
        why.append(_reliability_why(leg.eta, leg.train.train_no))

    warnings = list(a.warnings)
    if c.kind == "split":
        warnings.append(SPLIT_WARNING)
        warnings.append("Book both legs yourself and check both before you travel")
        if (c.layover_min_p90 or 0) < 60:
            warnings.append("Tight connection: less than an hour to spare if leg 1 arrives late (P90)")
        l1_arr, l2_dep = c.legs[0].arr, c.legs[1].dep
        if l2_dep.date() > l1_arr.date() or l1_arr.hour < 5:
            warnings.append(f"Night-time wait at {data.station_name(c.hub or '')}")
    for leg in c.legs:
        if leg.eta.history_runs == 0:
            warnings.append(
                f"Train {leg.train.train_no} has little or no delay history: predicted times are a fallback estimate"
            )
        if leg.run_date > bookable_to:
            opens = leg.run_date - timedelta(days=cfg.arp_days)
            warnings.append(f"Train {leg.train.train_no}: beyond the {cfg.arp_days}-day booking window, opens {opens}")
        if leg.dep.date() < today:
            warnings.append(f"Train {leg.train.train_no}: this departure is in the past")
        if leg.train.running_days is None:
            warnings.append(f"Train {leg.train.train_no}: running days unknown, check before booking")

    if c.kind == "direct":
        leg = c.first
        iid = f"d-{leg.train.train_no}-{leg.run_date}"
    else:
        l1, l2 = c.legs
        iid = f"s-{l1.train.train_no}-{l1.run_date}-{c.hub}-{l2.train.train_no}-{l2.run_date}"
    return Itinerary(
        id=iid,
        kind=c.kind,
        score=a.score,
        score_breakdown=ScoreBreakdown(**a.components),
        why=why,
        legs=[make_leg(data, leg, cfg) for leg in c.legs],
        layover_min_sched=c.layover_min_sched,
        layover_min_p90=c.layover_min_p90,
        split_kind="split_itinerary" if c.kind == "split" else None,
        warnings=warnings,
    )
