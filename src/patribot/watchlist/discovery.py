"""Find candidate corridor trains cheaply, before paying for one schedule call per train.

1. Station timetable at every unique waypoint and end-cluster station (~85 calls for the 5 MVP corridors).
2. If a station's timetable request fails, fall back to between-stations searches with its neighbouring
   waypoints, in both directions.
3. A train is a candidate if it is not excluded by number/type/name/classes and was seen at stations covering
   >= 2 distinct positions of some corridor path. Only candidates get a (more expensive in total) schedule call.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, fields, replace

from patribot.sources.base import TimetableSource, TrainSummary
from patribot.watchlist.corridors import CorridorConfig
from patribot.watchlist.membership import PathSlots, distinct_slots, exclusion_reason, is_premium, neighbours


def merge_summary(old: TrainSummary | None, new: TrainSummary) -> TrainSummary:
    """Keep the first non-empty value of each field."""
    if old is None:
        return new
    updates = {f.name: getattr(new, f.name) for f in fields(TrainSummary) if not getattr(old, f.name)}
    return replace(old, **{k: v for k, v in updates.items() if v})


@dataclass
class Discovery:
    seen: dict[str, set[str]] = field(default_factory=dict)  # train_no -> queried stations it was listed at
    summaries: dict[str, TrainSummary] = field(default_factory=dict)
    stations_queried: int = 0
    stations_failed: list[str] = field(default_factory=list)  # timetable request failed -> between fallback
    stations_empty: list[str] = field(default_factory=list)  # no trains listed: check the station code
    between_queries: int = 0

    def add(self, stations: tuple[str, ...], train: TrainSummary) -> None:
        self.seen.setdefault(train.train_no, set()).update(stations)
        self.summaries[train.train_no] = merge_summary(self.summaries.get(train.train_no), train)


def discover(
    source: TimetableSource, cfg: CorridorConfig, all_slots: list[PathSlots], d: Discovery | None = None
) -> Discovery:
    """Fill `d` (pass one in to keep partial results if the source raises)."""
    d = d if d is not None else Discovery()
    pairs_done: set[tuple[str, str]] = set()
    for station in cfg.all_stations():
        trains = source.list_trains_at(station)
        d.stations_queried += 1
        if trains is not None:
            for t in trains:
                d.add((station,), t)
            if not trains:
                d.stations_empty.append(station)
            continue
        d.stations_failed.append(station)
        for nb in dict.fromkeys(n for ps in all_slots for n in neighbours(station, ps)):
            for src, dst in ((station, nb), (nb, station)):
                if (src, dst) in pairs_done:
                    continue
                pairs_done.add((src, dst))
                d.between_queries += 1
                for t in source.list_trains_between(src, dst) or []:
                    d.add((src, dst), t)
    return d


def candidates(
    d: Discovery, cfg: CorridorConfig, all_slots: list[PathSlots], include_specials: bool = False
) -> tuple[list[str], Counter[str]]:
    """Candidate train numbers (premium trains first, then by path coverage) and exclusion counts by reason."""
    excluded: Counter[str] = Counter()
    ranked: list[tuple[int, int, str]] = []
    for no, stations in d.seen.items():
        s = d.summaries[no]
        reason = exclusion_reason(
            no, s.name, s.train_type, s.classes, cfg.membership.exclude_train_types, include_specials
        )
        if reason:
            excluded[reason] += 1
            continue
        score = max((distinct_slots(stations, ps) for ps in all_slots), default=0)
        if score >= 2:
            ranked.append((0 if is_premium(s.name, s.train_type) else 1, -score, no))
    return [no for *_, no in sorted(ranked)], excluded
