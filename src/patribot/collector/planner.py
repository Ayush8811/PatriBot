"""Decide which train runs to fetch on this collector run, within the monthly API budget."""

from __future__ import annotations

import calendar
import math
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
    sampled_out: int  # tier-B runs skipped by sampling
    over_budget: int  # due runs left for a later collector run because today's allowance is spent
    tier_b_stride: int
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


def tier_b_stride(trains: list[WatchedTrain], settings: CollectorSettings, today: date) -> int:
    """1 = collect every tier-B run; n = collect roughly 1 in n, so expected demand fits the budget."""
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    daily_budget = settings.max_calls_per_month / days_in_month * BUDGET_HEADROOM
    a = sum(len(t.run_days) / 7 for t in trains if t.tier == "A")
    b = sum(len(t.run_days) / 7 for t in trains if t.tier == "B")
    if b == 0 or a + b <= daily_budget:
        return 1
    room = daily_budget - a
    if room <= 0:
        return settings.max_tier_b_stride
    return min(settings.max_tier_b_stride, math.ceil(b / room))


def sampled_in(run: DueRun, stride: int) -> bool:
    # crc32, not hash(): must be stable across processes so a sampled-out run stays sampled out
    return stride <= 1 or zlib.crc32(f"{run.train_no}|{run.start_date}".encode()) % stride == 0


def make_plan(
    trains: list[WatchedTrain],
    settings: CollectorSettings,
    now_local: datetime,
    manifest: dict[RunKey, RunState],
    usage_by_day: dict[str, int],
) -> Plan:
    today = now_local.date()
    due = due_runs(trains, settings, now_local, manifest)
    stride = tier_b_stride(trains, settings, today)
    budget = remaining_budget(settings, usage_by_day, today)

    tier_a = sorted((r for r in due if r.tier == "A"), key=lambda r: r.start_date)
    tier_b_all = [r for r in due if r.tier == "B"]
    tier_b = sorted((r for r in tier_b_all if sampled_in(r, stride)), key=lambda r: r.start_date)
    ordered = tier_a + tier_b  # oldest first: those are closest to falling out of the look-back window

    return Plan(
        selected=ordered[:budget],
        due_total=len(due),
        sampled_out=len(tier_b_all) - len(tier_b),
        over_budget=max(0, len(ordered) - budget),
        tier_b_stride=stride,
        remaining_budget=budget,
    )
