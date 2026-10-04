"""Corridor membership and train classification. Pure functions, no I/O (architecture doc §3.2, D10).

A corridor is a PATH. A reserved train is a member of a corridor path when its route HALTS at two stations of the
path (a waypoint, or any station of the path's end clusters), in either direction, that are
  - >= `min_consecutive_segments` waypoint segments apart, or
  - >= `min_km` apart by the route's cumulative distance.
It may start or end anywhere: on the path, or beyond it. A station the train passes without stopping does not
count. The rule assumes that a train halting at two path stations runs along the path between them. A train is a
member of a corridor when it is a member of any of its paths.

The warehouse uses these same functions (`patribot.transform.timetable` → dbt `dim_train_corridor`), so the watchlist
and the planner can never disagree on membership.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from patribot.sources.base import RouteStop
from patribot.watchlist.corridors import CorridorConfig, MembershipRule

# ---- reserved-train filter ------------------------------------------------------------------------------------
# Indian Railways numbering (5 digits): the first digit identifies most non-reserved services.
NUMBER_PREFIX_EXCLUSIONS = {
    "3": "suburban (3xxxx, Kolkata area)",
    "4": "suburban (4xxxx, Chennai area)",
    "5": "passenger (5xxxx)",
    "6": "MEMU (6xxxx)",
    "7": "DEMU / railcar (7xxxx)",
    "9": "suburban (9xxxx, Mumbai area)",
}
SPECIAL_PREFIX = "0"  # 0xxxx = special trains: temporary, often unreserved; excluded unless asked for
EXTRA_TYPE_TOKENS = ("SUBURBAN", "LOCAL", "PASS")
NAME_EXCLUSION = re.compile(r"\b(MEMU|DEMU|EMU|PASSENGER|PASS|ANTYODAYA|JAN\s?SADHARAN|UNRESERVED|SUBURBAN)\b")
UNRESERVED_CLASSES = {"GEN", "GN", "UR", "GS", "II", "UNRESERVED"}

PREMIUM = re.compile(r"RAJDHANI|RAJDHNI|RJDHNI|SHATABDI|SHATBDI|SHTBDI|DURONTO|DRNTO|VANDE|TEJAS|HUMSAFAR|HMSFR")


def _norm(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


def exclusion_reason(
    train_no: str,
    name: str = "",
    train_type: str = "",
    classes: str = "",
    exclude_types: Iterable[str] = (),
    include_specials: bool = False,
) -> str | None:
    """Why a train is not a reserved corridor train, or None when it is (BRD §5.3)."""
    first = train_no[:1]
    if first in NUMBER_PREFIX_EXCLUSIONS:
        return NUMBER_PREFIX_EXCLUSIONS[first]
    if first == SPECIAL_PREFIX and not include_specials:
        return "special (0xxxx)"
    t = f" {_norm(train_type)} "
    for token in (*(_norm(x) for x in exclude_types), *EXTRA_TYPE_TOKENS):
        if token and f" {token} " in t:
            return f"type {token}"
    if m := NAME_EXCLUSION.search(_norm(name)):
        return f"name {m.group(1)}"
    listed = {c for c in re.split(r"[\s,/]+", classes.upper()) if c}
    if listed and listed <= UNRESERVED_CLASSES:
        return "unreserved classes only"
    return None


def is_premium(name: str = "", train_type: str = "") -> bool:
    """Rajdhani, Shatabdi, Duronto, Vande Bharat, Tejas, Humsafar (incl. common IR name abbreviations)."""
    return bool(PREMIUM.search(_norm(f"{name} {train_type}")))


# ---- path matching ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PathSlots:
    """Station -> position on one corridor path. End-cluster stations map to the path's first or last slot."""

    corridor: str
    path: str
    stations: tuple[str, ...]  # the waypoints, A -> B
    slots: dict[str, int]


@dataclass(frozen=True)
class PathMatch:
    corridor: str
    path: str
    from_code: str  # in the train's direction of travel
    to_code: str
    segments: int  # waypoint segments between the two halts
    km: float | None
    direction: str  # "AB" or "BA" relative to the corridor


def path_slots(cfg: CorridorConfig) -> list[PathSlots]:
    out = []
    for c in cfg.corridors:
        a, b = cfg.clusters[c.a], cfg.clusters[c.b]
        for name, path in c.paths.items():
            slots = {code: i for i, code in enumerate(path)}
            first, last = (a, b) if path[0] in a or path[-1] in b else (b, a)
            for code in first:
                slots.setdefault(code, 0)
            for code in last:
                slots.setdefault(code, len(path) - 1)
            out.append(PathSlots(c.id, name, tuple(path), slots))
    return out


def neighbours(station: str, ps: PathSlots) -> list[str]:
    """Waypoints adjacent to `station` on this path (for a cluster station: next to its end slot)."""
    if station not in ps.slots:
        return []
    i = ps.slots[station]
    return [ps.stations[j] for j in (i - 1, i + 1) if 0 <= j < len(ps.stations) and ps.stations[j] != station]


def distinct_slots(stations: Iterable[str], ps: PathSlots) -> int:
    """How many distinct path positions a set of stations covers (discovery pre-filter)."""
    return len({ps.slots[s] for s in stations if s in ps.slots})


def match_path(stops: Iterable[RouteStop], ps: PathSlots, rule: MembershipRule) -> PathMatch | None:
    """The widest qualifying pair of halts on this path, or None if the train is not a member of it."""
    hits = [(ps.slots[s.code], s) for s in stops if s.halts and s.code in ps.slots]
    best: PathMatch | None = None
    best_key: tuple[int, float] = (-1, -1.0)
    for i, (si, a) in enumerate(hits):
        for sj, b in hits[i + 1 :]:
            segments = abs(sj - si)
            if segments == 0:
                continue
            km = None
            if a.distance_km is not None and b.distance_km is not None:
                km = abs(b.distance_km - a.distance_km)
            if segments < rule.min_consecutive_segments and (km is None or km < rule.min_km):
                continue
            key = (segments, km or 0.0)
            if key > best_key:
                direction = "AB" if sj > si else "BA"
                best, best_key = PathMatch(ps.corridor, ps.path, a.code, b.code, segments, km, direction), key
    return best


def memberships(stops: Iterable[RouteStop], all_slots: list[PathSlots], rule: MembershipRule) -> list[PathMatch]:
    stops = list(stops)
    return [m for ps in all_slots if (m := match_path(stops, ps, rule)) is not None]


def serves_both_ends(stops: Iterable[RouteStop], cfg: CorridorConfig, corridor_id: str) -> bool:
    c = next(c for c in cfg.corridors if c.id == corridor_id)
    halts = {s.code for s in stops if s.halts}
    return bool(halts & set(cfg.clusters[c.a])) and bool(halts & set(cfg.clusters[c.b]))


def serves_end_or_hub(stops: Iterable[RouteStop], cfg: CorridorConfig, corridor_id: str) -> bool:
    """Halts at a station of either end cluster or at a split hub: useful as a direct or split-journey leg."""
    c = next(c for c in cfg.corridors if c.id == corridor_id)
    halts = {s.code for s in stops if s.halts}
    return bool(halts & (set(cfg.clusters[c.a]) | set(cfg.clusters[c.b]) | set(c.split_hubs)))
