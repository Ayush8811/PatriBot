"""In-memory snapshot of the gold tables the planner reads (architecture doc §7). Plain frozen dataclasses: the
planner's search, ETA and ranking functions are pure functions over these."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


@dataclass(frozen=True)
class Station:
    code: str
    name: str | None = None
    cluster: str | None = None
    lat: float | None = None
    lon: float | None = None


@dataclass(frozen=True)
class Stop:
    """A scheduled stop. Minutes are counted from the train's departure from its ORIGIN."""

    seq: int
    code: str
    arr_min: int | None  # None at the origin
    dep_min: int | None  # None at the destination
    name: str | None = None
    arr_time: str | None = None  # "HH:MM" local
    dep_time: str | None = None
    day_offset: int = 0  # 0 = the origin's departure day (the day of the arrival, else of the departure)
    distance_km: float | None = None
    route_fraction: float | None = None  # distance_km / route length, 0..1
    halts: bool = True


@dataclass(frozen=True)
class Train:
    train_no: str
    name: str
    stops: tuple[Stop, ...]
    origin_dep_clock_min: int  # departure from the origin, minutes after local midnight
    running_days: frozenset[str] | None = None  # MON..SUN at the ORIGIN; None = unknown (treated as daily)
    train_type: str | None = None
    origin: str | None = None
    destination: str | None = None
    classes: tuple[str, ...] = ()
    corridors: tuple[str, ...] = ()
    route_km: float | None = None
    is_reserved: bool = True

    def runs_on(self, run_date: date) -> bool:
        return self.running_days is None or WEEKDAYS[run_date.weekday()] in self.running_days


@dataclass(frozen=True)
class Corridor:
    corridor_id: str
    name: str
    cluster_a: str
    cluster_b: str
    split_hubs: tuple[str, ...] = ()
    waypoints: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DelayStat:
    """A delay distribution in minutes. `pct_within` is P(delay <= on-time threshold), 0..1."""

    n_runs: int
    p50: float
    p90: float
    pct_within: float | None = None


@dataclass(frozen=True)
class DelayStats:
    """The ETA baseline's inputs at four levels of detail (gold agg_* tables). Periods are 'YYYY-MM' or 'all'."""

    stop_month: dict[tuple[str, str, str], DelayStat] = field(default_factory=dict)  # (train, station, month)
    stop_all: dict[tuple[str, str], DelayStat] = field(default_factory=dict)  # (train, station)
    train: dict[tuple[str, str], DelayStat] = field(default_factory=dict)  # (train, period): final arrival delay
    corridor: dict[tuple[str, str], DelayStat] = field(default_factory=dict)  # (corridor, period)


@dataclass(frozen=True)
class RunRecord:
    train_no: str
    run_date: date
    run_state: str
    final_delay_min: int | None
    is_delay_target: bool


@dataclass(frozen=True)
class PlannerData:
    stations: dict[str, Station]
    clusters: dict[str, tuple[str, ...]]  # cluster id -> station codes (config order)
    trains: dict[str, Train]  # every known train; one without a cached timetable has no stops
    corridors: dict[str, Corridor]
    delays: DelayStats
    data_as_of: datetime | None = None

    def station_name(self, code: str) -> str:
        st = self.stations.get(code)
        return (st.name if st and st.name else None) or code
