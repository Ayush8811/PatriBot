"""Pydantic models of the API v1 contract (docs/api/v1.md). The planner produces them directly, so the contract has
one definition. Field names are snake_case; datetimes carry the +05:30 offset; dates are YYYY-MM-DD."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"
MAX_WINDOW_DAYS = 31  # date_from..date_to inclusive; longer windows are a 422
DEFAULT_RESULTS = 10
MAX_RESULTS = 20

Objective = Literal["fastest", "most_reliable", "balanced"]
HardConstraint = Literal["overnight", "arrive_by", "depart_after", "depart_before", "classes"]
ETA_MODEL = "baseline_hist"


class Preferences(BaseModel):
    overnight: bool | None = Field(None, description="Prefer overnight trains (soft unless 'overnight' is in `hard`).")
    depart_after: str | None = Field(None, pattern=HHMM, description="HH:MM local, departure from the origin.")
    depart_before: str | None = Field(None, pattern=HHMM)
    arrive_by: str | None = Field(
        None, pattern=HHMM, description="HH:MM local on the arrival day; judged on P90 when hard, on P50 when soft."
    )
    arrive_by_date: date | None = Field(
        None,
        description="Optional (addition to v1): the date `arrive_by` applies to. Default: each itinerary's "
        "scheduled arrival date.",
    )
    classes: list[str] | None = Field(None, description="Travel classes, e.g. ['3A', '2A'].")
    objective: Objective = "balanced"
    allow_split: bool = False
    hard: list[HardConstraint] = []

    @field_validator("classes")
    @classmethod
    def _upper(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return [c.strip().upper() for c in v if c.strip()] or None


class PlanRequest(BaseModel):
    origin: str = Field(min_length=1, max_length=64, description="Cluster id or station code.")
    destination: str = Field(min_length=1, max_length=64)
    date_from: date = Field(description="Departure-date window, inclusive.")
    date_to: date
    preferences: Preferences = Preferences()
    max_results: int = Field(
        DEFAULT_RESULTS, ge=1, description=f"Default {DEFAULT_RESULTS}; values above {MAX_RESULTS} are capped."
    )

    @field_validator("max_results")
    @classmethod
    def _cap(cls, v: int) -> int:
        return min(v, MAX_RESULTS)

    @model_validator(mode="after")
    def _window(self) -> PlanRequest:
        if self.date_to < self.date_from:
            raise ValueError("date_to must not be before date_from")
        if self.date_to - self.date_from > timedelta(days=MAX_WINDOW_DAYS - 1):
            raise ValueError(f"the date window is limited to {MAX_WINDOW_DAYS} days")
        return self


class ScoreBreakdown(BaseModel):
    journey_time: float
    reliability: float
    preference: float
    transfer: float


class Leg(BaseModel):
    train_no: str
    train_name: str
    train_type: str | None
    run_date: date = Field(description="Departure date from the train's origin.")
    from_code: str
    from_name: str
    to_code: str
    to_name: str
    dep_sched: datetime
    arr_sched: datetime
    arr_pred_p50: datetime
    arr_pred_p90: datetime
    journey_min_sched: int
    journey_min_pred_p50: int
    reliability: float = Field(description="P(arrival delay <= 30 min), 0..1.")
    history_runs: int = Field(description="Runs behind the prediction (0 = fallback estimate).")
    overnight: bool
    classes: list[str]
    eta_basis: str = Field(
        description="Addition to v1: which history level the prediction came from (train_station_month, "
        "train_station, train_station_shrunk, train_route_scaled, corridor_route_scaled, none)."
    )


class Itinerary(BaseModel):
    id: str
    kind: Literal["direct", "split"]
    score: float
    score_breakdown: ScoreBreakdown
    why: list[str]
    legs: list[Leg]
    layover_min_sched: int | None = None
    layover_min_p90: int | None = None
    split_kind: Literal["split_itinerary", "break_journey"] | None = None
    warnings: list[str] = []
    irctc_url: str = "https://www.irctc.co.in/nget/train-search"


class PlanMeta(BaseModel):
    eta_model: str = ETA_MODEL
    data_as_of: datetime | None
    dates_searched: int
    candidates_considered: int
    bookable_from: date
    bookable_to: date


class PlanResponse(BaseModel):
    query: dict[str, Any]
    itineraries: list[Itinerary]
    meta: PlanMeta


# ---- places, trains -------------------------------------------------------------------------------------------


class PlaceResult(BaseModel):
    kind: Literal["cluster", "station"]
    id: str
    name: str
    stations: list[str] | None = None  # clusters only
    cluster: str | None = None  # stations only

    def model_dump_contract(self) -> dict[str, Any]:
        d = self.model_dump()
        d.pop("stations" if self.kind == "station" else "cluster")
        return d


class RouteStop(BaseModel):
    seq: int
    code: str
    name: str
    arr: str | None
    dep: str | None
    day: int
    distance_km: float | None
    delay_p50_min: int | None = Field(description="Predicted arrival delay (P50); null when history_runs is 0.")
    delay_p90_min: int | None = Field(description="Predicted arrival delay (P90); null when history_runs is 0.")
    history_runs: int


class TrainDetail(BaseModel):
    train_no: str
    train_name: str
    train_type: str | None
    origin: str | None
    destination: str | None
    running_days: list[str]
    classes: list[str]
    corridors: list[str]
    route: list[RouteStop]


class MonthPerformance(BaseModel):
    month: str
    runs: int
    final_delay_p50: int | None
    final_delay_p90: int | None
    pct_within_30min: float | None


class RecentRun(BaseModel):
    run_date: date
    final_delay_min: int | None
    run_state: str


class TrainPerformance(BaseModel):
    train_no: str
    runs: int
    on_time_pct: float | None
    by_month: list[MonthPerformance]
    recent_runs: list[RecentRun]
