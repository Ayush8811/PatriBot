"""Constraints and ranking (architecture doc §7.3, BRD FR-9, NFR-7). Every score component is in 0..1 (higher is
better) and returned to the client:

  journey_time  exp(−(t − t_fastest) / (JOURNEY_SCALE × t_fastest)), t = predicted (P50) door-to-door minutes:
                1 for the fastest in the candidate set, 1/e for one 25 % slower
  reliability   P(arrival within 30 min of schedule) of each leg, times P(making the connection) for splits
  preference    share of the requested SOFT preferences met (overnight, depart window, arrive-by on P50/P90, classes)
  transfer      1 for a direct train; SPLIT_TRANSFER_BASE × P(connection) for a split (separate tickets)

score = Σ weight × component, with weights from the objective. Hard constraints filter instead of scoring:
arrive_by is judged on the P90 arrival, the rest on the timetable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from patribot.planner.schemas import Preferences
from patribot.planner.search import IST, Candidate, PlannerConfig

WEIGHTS: dict[str, dict[str, float]] = {
    "fastest": {"journey_time": 0.6, "reliability": 0.1, "preference": 0.2, "transfer": 0.1},
    "most_reliable": {"journey_time": 0.2, "reliability": 0.5, "preference": 0.2, "transfer": 0.1},
    "balanced": {"journey_time": 0.35, "reliability": 0.35, "preference": 0.2, "transfer": 0.1},
}
SPLIT_TRANSFER_BASE = 0.6
JOURNEY_SCALE = 0.25
# With `arrive_by_date`, an itinerary must arrive (scheduled) within this many hours before the deadline.
ARRIVE_BY_DATE_WINDOW_H = 24


def hhmm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


@dataclass
class Assessment:
    candidate: Candidate
    hard_ok: bool = True
    preference: float = 1.0
    met: dict[str, float] = field(default_factory=dict)  # preference -> 0..1
    warnings: list[str] = field(default_factory=list)
    components: dict[str, float] = field(default_factory=dict)
    score: float = 0.0


def arrive_deadline(c: Candidate, prefs: Preferences) -> datetime | None:
    if not prefs.arrive_by:
        return None
    day = prefs.arrive_by_date or c.last.arr.date()
    return datetime.combine(day, hhmm(prefs.arrive_by), IST)


def assess(c: Candidate, prefs: Preferences, cfg: PlannerConfig) -> Assessment:
    """Check hard constraints and score the soft ones."""
    a = Assessment(c)
    hard = set(prefs.hard)
    met: dict[str, float] = {}
    if prefs.overnight:
        met["overnight"] = 1.0 if c.overnight(cfg) else 0.0
    dep = c.first.dep.time()
    if prefs.depart_after:
        met["depart_after"] = 1.0 if dep >= hhmm(prefs.depart_after) else 0.0
    if prefs.depart_before:
        met["depart_before"] = 1.0 if dep <= hhmm(prefs.depart_before) else 0.0
    if (deadline := arrive_deadline(c, prefs)) is not None:
        if prefs.arrive_by_date and c.last.arr <= deadline - timedelta(hours=ARRIVE_BY_DATE_WINDOW_H):
            met["arrive_by"] = 0.0  # a day or more early: not an answer to "reach X by 09:00 on the 25th"
        elif c.last.arr_p90 <= deadline:
            met["arrive_by"] = 1.0
        elif "arrive_by" not in hard and c.last.arr_p50 <= deadline:
            met["arrive_by"] = 0.5  # on time in a typical run, not in a late one
        else:
            met["arrive_by"] = 0.0
    if prefs.classes:
        wanted = set(prefs.classes)
        unknown = [leg.train.train_no for leg in c.legs if not leg.train.classes]
        if unknown:
            met["classes"] = 0.5
            a.warnings.append(f"Class availability unknown for train {', '.join(unknown)}")
        else:
            met["classes"] = 1.0 if all(wanted & set(leg.train.classes) for leg in c.legs) else 0.0
    a.met = met
    for name, value in met.items():
        if name in hard and value < 1.0 and not (name == "classes" and value == 0.5):
            a.hard_ok = False
    soft = [v for k, v in met.items() if k not in hard]
    a.preference = sum(soft) / len(soft) if soft else 1.0
    return a


def score_all(assessments: list[Assessment], objective: str) -> None:
    """Fill components and score in place (journey time is normalised over the given set)."""
    if not assessments:
        return
    weights = WEIGHTS[objective]
    fastest = min(max(1, a.candidate.journey_min_p50) for a in assessments)
    for a in assessments:
        c = a.candidate
        a.components = {
            "journey_time": round(math.exp(-(c.journey_min_p50 - fastest) / (JOURNEY_SCALE * fastest)), 3),
            "reliability": round(c.reliability, 3),
            "preference": round(a.preference, 3),
            "transfer": 1.0 if c.kind == "direct" else round(SPLIT_TRANSFER_BASE * c.connect_prob, 3),
        }
        a.score = round(sum(weights[k] * v for k, v in a.components.items()), 3)


def select(assessments: list[Assessment], max_results: int) -> list[Assessment]:
    """Top `max_results`, diversified: first the best date of each distinct train (or train pair) by score, then
    further dates of the same trains by score if slots remain. Ties go to the earlier departure."""
    ordered = sorted(assessments, key=lambda a: (-a.score, a.candidate.first.dep))
    picked: list[Assessment] = []
    seen: set[tuple] = set()
    for a in ordered:
        if a.candidate.signature not in seen:
            seen.add(a.candidate.signature)
            picked.append(a)
    if len(picked) < max_results:
        chosen = {id(a) for a in picked}
        picked += [a for a in ordered if id(a) not in chosen][: max_results - len(picked)]
    return picked[:max_results]
