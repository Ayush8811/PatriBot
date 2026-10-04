"""Build the collector watchlist: discovery -> schedules -> membership -> tiering -> YAML + report."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from typing import Any

import yaml

from patribot.collector.config import WEEKDAYS, CollectorSettings, WatchedTrain, Watchlist
from patribot.sources.base import CallBudgetExhausted, SourceStopped, TimetableSource, TrainSchedule, TrainSummary
from patribot.watchlist.corridors import CorridorConfig
from patribot.watchlist.discovery import Discovery, candidates, discover
from patribot.watchlist.membership import (
    PathMatch,
    exclusion_reason,
    is_premium,
    memberships,
    path_slots,
    serves_both_ends,
)

DAYS_PER_MONTH = 30


@dataclass
class BuildResult:
    trains: list[WatchedTrain]
    report: dict[str, Any]
    stopped: str | None = None  # why discovery ended early (max-calls guard, bad key, quota); None if complete
    matches: dict[str, list[PathMatch]] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return self.stopped is None


def watched_train(
    sched: TrainSchedule,
    summary: TrainSummary | None,
    matches: list[PathMatch],
    cfg: CorridorConfig,
) -> tuple[WatchedTrain | None, bool]:
    """Collector entry for a member train, and whether its run days were defaulted to daily."""
    corridor_order = [c.id for c in cfg.corridors]
    corridors = sorted({m.corridor for m in matches}, key=corridor_order.index)
    name = sched.name or (summary.name if summary else "")
    train_type = sched.train_type or (summary.train_type if summary else "")
    both_ends = any(serves_both_ends(sched.stops, cfg, c) for c in corridors)
    tier = "A" if both_ends or is_premium(name, train_type) else "B"
    journey = sched.journey_minutes
    if not sched.dep_time or not journey or journey <= 0:
        return None, False
    days = sched.running_days or (summary.running_days if summary else None)
    entry = WatchedTrain(
        train_no=sched.train_no,
        name=name,
        corridors=corridors,
        tier=tier,
        dep_time=time.fromisoformat(sched.dep_time),
        journey_minutes=journey,
        run_days=list(days or WEEKDAYS),
    )
    return entry, days is None


def build(source: TimetableSource, cfg: CorridorConfig, include_specials: bool = False) -> BuildResult:
    all_slots = path_slots(cfg)
    stopped: str | None = None
    d = Discovery()
    cands: list[str] = []
    excluded: Counter[str] = Counter()
    try:
        discover(source, cfg, all_slots, d)
        cands, excluded = candidates(d, cfg, all_slots, include_specials)
    except (CallBudgetExhausted, SourceStopped) as exc:
        stopped = f"discovery: {exc}"

    trains: list[WatchedTrain] = []
    matches_by_train: dict[str, list[PathMatch]] = {}
    outcome: Counter[str] = Counter()
    unchecked = 0
    for i, no in enumerate(cands):
        try:
            sched = source.get_schedule(no)
        except (CallBudgetExhausted, SourceStopped) as exc:
            stopped, unchecked = f"schedules: {exc}", len(cands) - i
            break
        if sched is None or not sched.stops:
            outcome["no schedule"] += 1
            continue
        summary = d.summaries.get(no)
        reason = exclusion_reason(
            no,
            sched.name or (summary.name if summary else ""),
            sched.train_type,
            summary.classes if summary else "",
            cfg.membership.exclude_train_types,
            include_specials,
        )
        if reason:
            excluded[reason] += 1
            continue
        matches = memberships(sched.stops, all_slots, cfg.membership)
        if not matches:
            outcome["not a member"] += 1
            continue
        entry, defaulted = watched_train(sched, summary, matches, cfg)
        if entry is None:
            outcome["member without departure time or duration"] += 1
            continue
        if defaulted:
            outcome["run days defaulted to daily"] += 1
        trains.append(entry)
        matches_by_train[no] = matches

    trains.sort(key=lambda t: t.train_no)
    report = make_report(trains, matches_by_train, cfg, source, d, len(cands), excluded, outcome, unchecked, stopped)
    return BuildResult(trains, report, stopped, matches_by_train)


def monthly_collection_calls(trains: list[WatchedTrain]) -> int:
    """One running-status call per run: sum of runs/week x 30/7."""
    return round(sum(len(t.run_days) for t in trains) * DAYS_PER_MONTH / 7)


def make_report(
    trains: list[WatchedTrain],
    matches: dict[str, list[PathMatch]],
    cfg: CorridorConfig,
    source: TimetableSource,
    d: Discovery,
    n_candidates: int,
    excluded: Counter[str],
    outcome: Counter[str],
    unchecked: int,
    stopped: str | None,
) -> dict[str, Any]:
    by_corridor: dict[str, dict[str, int]] = {}
    for c in cfg.corridors:
        members = [t for t in trains if c.id in t.corridors]
        paths = Counter(m.path for t in members for m in matches.get(t.train_no, []) if m.corridor == c.id)
        by_corridor[c.id] = {
            "total": len(members),
            "A": sum(t.tier == "A" for t in members),
            "B": sum(t.tier == "B" for t in members),
            "by_path": dict(paths),
        }
    tier_a = [t for t in trains if t.tier == "A"]
    tier_b = [t for t in trains if t.tier == "B"]
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": source.name,
        "complete": stopped is None,
        "stopped": stopped,
        "trains": len(trains),
        "by_tier": {"A": len(tier_a), "B": len(tier_b)},
        "by_corridor": by_corridor,
        "multi_corridor_trains": sum(len(t.corridors) > 1 for t in trains),
        "estimated_collection_calls_per_month": {
            "A": monthly_collection_calls(tier_a),
            "B": monthly_collection_calls(tier_b),
            "total": monthly_collection_calls(trains),
        },
        "discovery": {
            "api_calls": source.calls,
            "api_calls_by_endpoint": dict(getattr(source, "calls_by_kind", {})),
            "cache_hits": getattr(source, "cache_hits", 0),
            "stations_queried": d.stations_queried,
            "stations_without_timetable": d.stations_failed,
            "stations_with_no_trains": d.stations_empty,
            "between_station_queries": d.between_queries,
            "trains_seen": len(d.seen),
            "candidates": n_candidates,
            "candidates_unchecked": unchecked,
            "excluded": dict(sorted(excluded.items())),
            "outcomes": dict(sorted(outcome.items())),
            "errors": list(getattr(source, "errors", []))[:20],
        },
    }


# ---- output ----------------------------------------------------------------------------------------------------

HEADER = """\
# Collector watchlist, GENERATED by `patribot-watchlist build` (docs/phase1/watchlist.md). Do not edit by hand:
# change config/corridors.yaml or the `collector:` block of the base watchlist and rebuild.
#
# Derived from RailKit timetable data: keep this file in the PRIVATE data repo, never in the public code repo (D15).
# tier A = every run collected; tier B = sampled when the monthly budget is tight (architecture doc §4.2).
# {summary}
"""


def _q(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)  # a JSON string is a valid YAML double-quoted scalar


def render_watchlist(trains: list[WatchedTrain], collector: dict[str, Any], report: dict[str, Any]) -> str:
    CollectorSettings.model_validate(collector)
    summary = (
        f"Generated {report['generated_at']}: {report['trains']} trains (A {report['by_tier']['A']}, "
        f"B {report['by_tier']['B']}), ~{report['estimated_collection_calls_per_month']['total']} "
        f"running-status calls/month if every run is collected."
    )
    lines = [HEADER.format(summary=summary)]
    lines.append(yaml.safe_dump({"collector": collector}, sort_keys=False, allow_unicode=True).rstrip())
    lines.append("")
    lines.append("trains:" if trains else "trains: []")
    for t in trains:
        fields = [
            f"train_no: {_q(t.train_no)}",
            f"name: {_q(t.name)}",
            f"corridors: [{', '.join(t.corridors)}]",
            f"tier: {t.tier}",
            f'dep_time: "{t.dep_time:%H:%M}"',
            f"journey_minutes: {t.journey_minutes}",
        ]
        if list(t.run_days) != list(WEEKDAYS):
            fields.append(f"run_days: [{', '.join(t.run_days)}]")
        lines.append(f"  - {{{', '.join(fields)}}}")
    text = "\n".join(lines) + "\n"
    Watchlist.model_validate(yaml.safe_load(text))  # never write a file the collector cannot load
    return text
