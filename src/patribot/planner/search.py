"""Direct and split itinerary search over the timetable (architecture doc §7.1–§7.2, BRD FR-5–FR-8). Pure functions.

Times: a train's stop times are minutes from its departure from its ORIGIN. A run is identified by its run date (the
origin departure date), and running days apply to the origin. Boarding at an intermediate station on date D therefore
means run date D − k, where k is the number of midnights between the origin departure and the boarding departure.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from patribot.planner.eta import DelayEstimate, estimate_delay, prob_within
from patribot.planner.model import Corridor, DelayStats, PlannerData, Stop, Train

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class PlannerConfig:
    # FR-6 overnight: departure in the evening window, arrival in the morning window, at least one night later
    overnight_depart: tuple[time, time] = (time(16, 0), time(23, 59))
    overnight_arrive: tuple[time, time] = (time(4, 0), time(11, 0))
    # FR-7 split journeys: leg 2 departs >= leg-1 P90 arrival + buffer and <= leg-1 P50 arrival + max layover
    min_buffer_min: int = 45
    max_layover_min: int = 8 * 60
    min_transfer_min: int = 15  # time needed to change trains; used for the connection probability
    leg2_options_per_leg1: int = 2
    arp_days: int = 60  # advance reservation period: bookable today .. today + arp_days


DEFAULT_CONFIG = PlannerConfig()


def at(train: Train, run_date: date, minutes: int) -> datetime:
    """Wall-clock IST time `minutes` after the origin departure of the run that starts on `run_date`."""
    return datetime.combine(run_date, time(0), IST) + timedelta(minutes=train.origin_dep_clock_min + minutes)


def dep_day_offset(train: Train, stop: Stop) -> int:
    """Midnights between the origin departure and the departure from `stop`."""
    return (train.origin_dep_clock_min + (stop.dep_min or 0)) // 1440


def month_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def is_overnight(dep: datetime, arr: datetime, cfg: PlannerConfig = DEFAULT_CONFIG) -> bool:
    """FR-6: departs in the evening window and arrives in the morning window after at least one night."""
    d0, d1 = cfg.overnight_depart
    a0, a1 = cfg.overnight_arrive
    return d0 <= dep.time() <= d1 and a0 <= arr.time() <= a1 and arr.date() > dep.date()


@dataclass(frozen=True)
class LegOption:
    """One concrete ride: a run of a train from a boarding stop to an alighting stop."""

    train: Train
    board: Stop
    alight: Stop
    run_date: date
    eta: DelayEstimate

    @property
    def dep(self) -> datetime:
        return at(self.train, self.run_date, self.board.dep_min or 0)

    @property
    def arr(self) -> datetime:
        return at(self.train, self.run_date, self.alight.arr_min or 0)

    @property
    def arr_p50(self) -> datetime:
        return max(self.arr + timedelta(minutes=round(self.eta.p50)), self.dep + timedelta(minutes=1))

    @property
    def arr_p90(self) -> datetime:
        return max(self.arr + timedelta(minutes=round(self.eta.p90)), self.arr_p50)

    @property
    def journey_min_sched(self) -> int:
        return (self.alight.arr_min or 0) - (self.board.dep_min or 0)

    @property
    def journey_min_p50(self) -> int:
        return round((self.arr_p50 - self.dep).total_seconds() / 60)


@dataclass(frozen=True)
class Candidate:
    """A direct itinerary (one leg) or a split itinerary (two legs on separate tickets, changing at `hub`)."""

    legs: tuple[LegOption, ...]
    hub: str | None = None
    connect_prob: float = 1.0  # P(leg 1 arrives in time to make leg 2)

    @property
    def kind(self) -> str:
        return "direct" if len(self.legs) == 1 else "split"

    @property
    def first(self) -> LegOption:
        return self.legs[0]

    @property
    def last(self) -> LegOption:
        return self.legs[-1]

    @property
    def journey_min_p50(self) -> int:
        return round((self.last.arr_p50 - self.first.dep).total_seconds() / 60)

    @property
    def reliability(self) -> float:
        r = self.connect_prob
        for leg in self.legs:
            r *= leg.eta.reliability
        return r

    @property
    def layover_min_sched(self) -> int | None:
        if len(self.legs) < 2:
            return None
        return round((self.legs[1].dep - self.legs[0].arr).total_seconds() / 60)

    @property
    def layover_min_p90(self) -> int | None:
        if len(self.legs) < 2:
            return None
        return round((self.legs[1].dep - self.legs[0].arr_p90).total_seconds() / 60)

    def overnight(self, cfg: PlannerConfig = DEFAULT_CONFIG) -> bool:
        return is_overnight(self.first.dep, self.last.arr, cfg)

    @property
    def signature(self) -> tuple:
        """Same trains between the same stations (any date): used to diversify the result list."""
        return tuple((leg.train.train_no, leg.board.code, leg.alight.code) for leg in self.legs)


@dataclass
class EtaCache:
    """Memoises `estimate_delay` per (train, station, month) during one search."""

    stats: DelayStats
    _cache: dict[tuple[str, str, str], DelayEstimate] = field(default_factory=dict)

    def get(self, train: Train, stop: Stop, run_date: date) -> DelayEstimate:
        key = (train.train_no, stop.code, month_of(run_date))
        if key not in self._cache:
            self._cache[key] = estimate_delay(
                self.stats, train.train_no, stop.code, key[2], stop.route_fraction, train.corridors
            )
        return self._cache[key]


def board_alight(train: Train, origins: frozenset[str], dests: frozenset[str]) -> tuple[Stop, Stop] | None:
    """The first halt in `dests` that follows a halt in `origins`, boarding at the LAST such origin halt before it
    (a train calling at two origin-cluster stations is boarded at the later one: the shorter ride)."""
    board: Stop | None = None
    for s in train.stops:
        if not s.halts:
            continue
        if s.code in dests and board is not None and s.arr_min is not None:
            return board, s
        if s.code in origins and s.dep_min is not None:
            board = s
    return None


def run_dates_for(train: Train, board: Stop, dates: Iterable[date]) -> Iterator[date]:
    """Run dates of the runs that depart `board` on one of `dates` (running days apply at the origin)."""
    k = dep_day_offset(train, board)
    for d in dates:
        run_date = d - timedelta(days=k)
        if train.runs_on(run_date):
            yield run_date


def runs_departing_between(train: Train, board: Stop, lo: datetime, hi: datetime) -> Iterator[date]:
    """Run dates whose departure from `board` falls within [lo, hi]."""
    d = lo.date()
    while d <= hi.date():
        for run_date in run_dates_for(train, board, (d,)):
            if lo <= at(train, run_date, board.dep_min or 0) <= hi:
                yield run_date
        d += timedelta(days=1)


def date_range(d0: date, d1: date) -> list[date]:
    return [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]


def _usable(train: Train) -> bool:
    return train.is_reserved and len(train.stops) >= 2


def direct_options(
    data: PlannerData,
    origins: frozenset[str],
    dests: frozenset[str],
    dates: list[date],
    etas: EtaCache,
    trains: Iterable[Train] | None = None,
) -> list[LegOption]:
    """FR-5: every run of every reserved train that departs an origin station on one of `dates` and later halts at a
    destination station."""
    out = []
    for train in trains if trains is not None else data.trains.values():
        if not _usable(train) or not (pair := board_alight(train, origins, dests)):
            continue
        board, alight = pair
        for run_date in run_dates_for(train, board, dates):
            out.append(LegOption(train, board, alight, run_date, etas.get(train, alight, run_date)))
    return out


def corridors_between(data: PlannerData, origins: frozenset[str], dests: frozenset[str]) -> list[Corridor]:
    """Corridors whose end clusters or path cover both the origin and the destination stations."""
    out = []
    for c in data.corridors.values():
        reach = set(data.clusters.get(c.cluster_a, ())) | set(data.clusters.get(c.cluster_b, ())) | c.waypoints
        if origins & reach and dests & reach:
            out.append(c)
    return out


def connection_probability(leg1: LegOption, leg2_dep: datetime, min_transfer_min: int) -> float:
    """P(leg 1's arrival delay leaves at least `min_transfer_min` before leg 2 departs), normal approximation."""
    slack = (leg2_dep - leg1.arr).total_seconds() / 60 - min_transfer_min
    return prob_within(leg1.eta.p50, leg1.eta.p90, threshold=slack)


def split_options(
    data: PlannerData,
    origins: frozenset[str],
    dests: frozenset[str],
    dates: list[date],
    etas: EtaCache,
    cfg: PlannerConfig = DEFAULT_CONFIG,
) -> list[Candidate]:
    """FR-7: two-leg itineraries via each corridor's split hubs. Leg 2 must depart the hub no earlier than leg 1's
    P90 arrival + `min_buffer_min` and no later than its P50 arrival + `max_layover_min`. Legs use the corridor's
    member trains (all trains when the corridor has no membership data) and must be different trains."""
    out: list[Candidate] = []
    seen_hubs: set[str] = set()
    for corridor in corridors_between(data, origins, dests):
        members = [t for t in data.trains.values() if corridor.corridor_id in t.corridors]
        pool = members or list(data.trains.values())
        for hub in corridor.split_hubs:
            if hub in origins or hub in dests or hub in seen_hubs:
                continue
            seen_hubs.add(hub)
            hub_set = frozenset({hub})
            leg1s = direct_options(data, origins, hub_set, dates, etas, pool)
            if not leg1s:
                continue
            leg2_trains = [
                (t, pair) for t in pool if _usable(t) and (pair := board_alight(t, hub_set, dests)) is not None
            ]
            for l1 in leg1s:
                lo = l1.arr_p90 + timedelta(minutes=cfg.min_buffer_min)
                hi = l1.arr_p50 + timedelta(minutes=cfg.max_layover_min)
                options = []
                for t2, (b2, a2) in leg2_trains:
                    if t2.train_no == l1.train.train_no:
                        continue
                    for run_date in runs_departing_between(t2, b2, lo, hi):
                        l2 = LegOption(t2, b2, a2, run_date, etas.get(t2, a2, run_date))
                        p = connection_probability(l1, l2.dep, cfg.min_transfer_min)
                        options.append(Candidate((l1, l2), hub, p))
                options.sort(key=lambda c: (c.last.arr_p50, -c.reliability))
                out.extend(options[: cfg.leg2_options_per_leg1])
    return out
