"""Train facts and historical performance (API `GET /trains/{no}` and `/trains/{no}/performance`, BRD FR-16/FR-17).
Answers come from gold tables only."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date

from patribot.planner.eta import ON_TIME_MIN, estimate_delay
from patribot.planner.model import WEEKDAYS, PlannerData, RunRecord
from patribot.planner.schemas import MonthPerformance, RecentRun, RouteStop, TrainDetail, TrainPerformance
from patribot.planner.search import month_of

RECENT_RUNS = 10


def train_detail(data: PlannerData, train_no: str, today: date) -> TrainDetail | None:
    """Route with the baseline's delay estimate per stop for runs in the current month (None if unknown)."""
    t = data.trains.get(train_no)
    if t is None:
        return None
    month = month_of(today)
    route = []
    for s in t.stops:
        est = estimate_delay(data.delays, t.train_no, s.code, month, s.route_fraction, t.corridors)
        route.append(
            RouteStop(
                seq=s.seq,
                code=s.code,
                name=s.name or data.station_name(s.code),
                arr=s.arr_time,
                dep=s.dep_time,
                day=s.day_offset + 1,
                distance_km=s.distance_km,
                delay_p50_min=round(est.p50) if est.history_runs else None,
                delay_p90_min=round(est.p90) if est.history_runs else None,
                history_runs=est.history_runs,
            )
        )
    return TrainDetail(
        train_no=t.train_no,
        train_name=t.name,
        train_type=t.train_type,
        origin=t.origin,
        destination=t.destination,
        running_days=[d for d in WEEKDAYS if t.running_days is None or d in t.running_days] if t.stops else [],
        classes=list(t.classes),
        corridors=list(t.corridors),
        route=route,
    )


def quantile(values: list[float], q: float) -> float:
    """Linear interpolation between closest ranks (DuckDB quantile_cont, numpy's default)."""
    xs = sorted(values)
    pos = (len(xs) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def month_start(d: date, months_back: int) -> date:
    y, m = d.year, d.month - months_back
    while m <= 0:
        y, m = y - 1, m + 12
    return date(y, m, 1)


def performance(train_no: str, runs: list[RunRecord], months: int) -> TrainPerformance:
    """Statistics over the last `months` calendar months of data, anchored on the train's latest run (data can lag
    the calendar). Only complete, non-disrupted runs (delay targets) count toward delay figures; recent_runs lists
    every attempted run, whatever its state."""
    runs = sorted(runs, key=lambda r: r.run_date, reverse=True)
    if not runs:
        return TrainPerformance(train_no=train_no, runs=0, on_time_pct=None, by_month=[], recent_runs=[])
    since = month_start(runs[0].run_date, months - 1)
    window = [r for r in runs if r.run_date >= since]
    scored = [r for r in window if r.is_delay_target and r.final_delay_min is not None]
    by_month: dict[str, list[int]] = defaultdict(list)
    for r in scored:
        by_month[month_of(r.run_date)].append(r.final_delay_min)  # type: ignore[arg-type]

    def pct(xs: list[int]) -> float | None:
        return round(100 * sum(x <= ON_TIME_MIN for x in xs) / len(xs), 1) if xs else None

    return TrainPerformance(
        train_no=train_no,
        runs=len(scored),
        on_time_pct=pct([r.final_delay_min for r in scored]),  # type: ignore[misc]
        by_month=[
            MonthPerformance(
                month=m,
                runs=len(xs),
                final_delay_p50=round(quantile(xs, 0.5)),
                final_delay_p90=round(quantile(xs, 0.9)),
                pct_within_30min=pct(xs),
            )
            for m, xs in sorted(by_month.items(), reverse=True)
        ],
        recent_runs=[
            RecentRun(run_date=r.run_date, final_delay_min=r.final_delay_min, run_state=r.run_state)
            for r in window[:RECENT_RUNS]
        ],
    )
