"""Decide which train runs to fetch on this collector run, within the monthly API budget."""

from __future__ import annotations

import calendar
import zlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from patribot.collector.config import WEEKDAYS, CollectorSettings, WatchedTrain
from patribot.collector.store import RunKey, RunState
from patribot.sources.base import RETRYABLE

BUDGET_HEADROOM = 0.95  # leave room for retries and on-demand live calls


@dataclass(frozen=True)
class DueRun:
    train_no: str
    start_date: date
    tier: str


@dataclass(frozen=True)
class Plan:
    selected: list[DueRun]
    due_total: int
    sampled_out: int  # tier-B/C runs skipped by sampling
    over_budget: int  # due runs left for a later collector run because today's allowance is spent
    tier_b_rate: float  # fraction of tier-B runs collected
    tier_c_rate: float
    remaining_budget: int


def due_runs(
    trains: list[WatchedTrain],
    settings: CollectorSettings,
    now_local: datetime,
    manifest: dict[RunKey, RunState],
) -> list[DueRun]:
    """Runs whose scheduled arrival (+ grace) has passed, within the provider's look-back window,
    that are neither collected nor out of retry attempts."""
    today = now_local.date()
    grace = timedelta(hours=settings.grace_hours)
    out: list[DueRun] = []
    for train in trains:
        for back in range(settings.lookback_days, -1, -1):
            start = today - timedelta(days=back)
            if WEEKDAYS[start.weekday()] not in train.run_days:
                continue
            departs = datetime.combine(start, train.dep_time, tzinfo=now_local.tzinfo)
            if departs + timedelta(minutes=train.journey_minutes) + grace > now_local:
                continue
            state = manifest.get((train.train_no, start))
            if state and (state.status not in RETRYABLE or state.attempts >= settings.max_attempts):
                continue
            out.append(DueRun(train.train_no, start, train.tier))
    return out


def remaining_budget(settings: CollectorSettings, usage_by_day: dict[str, int], today: date) -> int:
    """Spread what is left of the monthly cap evenly over the remaining days, including today."""
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    used_before = sum(v for d, v in usage_by_day.items() if d < today.isoformat())
    used_today = usage_by_day.get(today.isoformat(), 0)
    days_left = days_in_month - today.day + 1
    allowance_today = max(0, settings.max_calls_per_month - used_before) // days_left
    return max(0, allowance_today - used_today)


def tier_rates(
    trains: list[WatchedTrain], settings: CollectorSettings, today: date, usage_by_day: dict[str, int] | None = None
) -> tuple[float, float]:
    """Fractions of tier-B and tier-C runs to collect (1.0 = all) so expected daily demand fits what is left of the
    monthly budget. Tier A is always collected; B gets the room left after A, C the room left after B.

    Fractional rather than "1 in n", so a budget that is only slightly short trims only slightly.
    B never drops below 1 / max_tier_b_stride; C never below min_tier_c_rate.
    """
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    used_before = sum(v for d, v in (usage_by_day or {}).items() if d < today.isoformat())
    days_left = days_in_month - today.day + 1
    budget = max(0, settings.max_calls_per_month - used_before) / days_left * BUDGET_HEADROOM

    def per_day(tier: str) -> float:
        return sum(len(t.run_days) / 7 for t in trains if t.tier == tier)

    a, b, c = per_day("A"), per_day("B"), per_day("C")
    rate_b = 1.0 if b == 0 or a + b <= budget else max(1 / settings.max_tier_b_stride, min(1.0, (budget - a) / b))
    left = budget - a - b * rate_b
    rate_c = 1.0 if c == 0 or left >= c else max(settings.min_tier_c_rate, min(1.0, max(0.0, left) / c))
    return rate_b, rate_c


def tier_b_rate(
    trains: list[WatchedTrain], settings: CollectorSettings, today: date, usage_by_day: dict[str, int] | None = None
) -> float:
    return tier_rates(trains, settings, today, usage_by_day)[0]


def sampled_in(run: DueRun, rate: float) -> bool:
    # crc32, not hash(): must be stable across processes so a sampled-out run stays sampled out
    return rate >= 1.0 or zlib.crc32(f"{run.train_no}|{run.start_date}".encode()) % 10_000 < rate * 10_000


def make_plan(
    trains: list[WatchedTrain],
    settings: CollectorSettings,
    now_local: datetime,
    manifest: dict[RunKey, RunState],
    usage_by_day: dict[str, int],
) -> Plan:
    today = now_local.date()
    due = due_runs(trains, settings, now_local, manifest)
    rate_b, rate_c = tier_rates(trains, settings, today, usage_by_day)
    budget = remaining_budget(settings, usage_by_day, today)

    def oldest_first(runs: list[DueRun]) -> list[DueRun]:
        return sorted(runs, key=lambda r: r.start_date)  # closest to falling out of the look-back window first

    tier_a = oldest_first([r for r in due if r.tier == "A"])
    sampled = [r for r in due if r.tier != "A"]
    tier_b = oldest_first([r for r in due if r.tier == "B" and sampled_in(r, rate_b)])
    tier_c = oldest_first([r for r in due if r.tier == "C" and sampled_in(r, rate_c)])
    ordered = tier_a + tier_b + tier_c

    return Plan(
        selected=ordered[:budget],
        due_total=len(due),
        sampled_out=len(sampled) - len(tier_b) - len(tier_c),
        over_budget=max(0, len(ordered) - budget),
        tier_b_rate=round(rate_b, 3),
        tier_c_rate=round(rate_c, 3),
        remaining_budget=budget,
    )
