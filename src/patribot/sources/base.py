"""Source adapter contract (architecture doc §4.1).

The collector stores provider responses *raw* (bronze layer). Parsing provider-specific schemas into the
canonical run/stop model happens downstream (silver), so adapters here only fetch and classify.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Protocol


class FetchStatus(StrEnum):
    OK = "ok"  # HTTP 200 with a parseable body; may still describe a cancelled run (resolved in silver)
    NOT_FOUND = "not_found"  # provider has no data for this train/date (yet); retryable
    ERROR = "error"  # transport, HTTP or parse failure; retryable


RETRYABLE = {FetchStatus.NOT_FOUND, FetchStatus.ERROR}
STOP_HTTP_STATUSES = frozenset({401, 403, 429})  # bad key, inactive key, quota/rate limit: further calls fail too


@dataclass(frozen=True)
class RawResponse:
    source: str
    endpoint: str  # credentials already redacted
    train_no: str
    start_date: date
    status: FetchStatus
    http_status: int | None
    payload: Any
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "source": self.source,
            "endpoint": self.endpoint,
            "train_no": self.train_no,
            "start_date": self.start_date.isoformat(),
            "status": self.status.value,
            "http_status": self.http_status,
            "fetched_at": self.fetched_at.isoformat(),
            "error": self.error,
            "payload": self.payload,
        }


class RunningStatusSource(Protocol):
    name: str

    def fetch_run_status(self, train_no: str, start_date: date) -> RawResponse:
        """Fetch the running status of the run of `train_no` that departed its origin on `start_date`."""
        ...


# ---- timetable (watchlist generation, architecture doc §4.1) ------------------------------------------------
# Unlike running status, timetable data is parsed into these small normalized records right away: it is only used
# to compute corridor membership and the watchlist, and is not stored as bronze data.


class SourceStopped(RuntimeError):
    """The provider refused the key or the quota is exhausted (HTTP 401/403/429); further calls would fail too."""


class CallBudgetExhausted(RuntimeError):
    """The caller's max-calls guard is reached; no further request was sent."""


@dataclass(frozen=True)
class TrainSummary:
    """A train as listed by a station timetable or a between-stations search."""

    train_no: str
    name: str = ""
    train_type: str = ""
    classes: str = ""  # e.g. "1A,2A,3A,SL,GEN"; empty when the provider does not say
    origin: str = ""
    destination: str = ""
    running_days: tuple[str, ...] | None = None  # MON..SUN at origin; None when unknown


@dataclass(frozen=True)
class RouteStop:
    code: str
    arrival: str | None = None  # "HH:MM" local, None at the origin
    departure: str | None = None  # "HH:MM" local, None at the destination
    halt_minutes: int | None = None
    distance_km: float | None = None  # cumulative from origin
    day: int | None = None  # 1 = day of departure from origin
    halts: bool = True  # False for a listed station the train passes without stopping


@dataclass(frozen=True)
class TrainSchedule:
    train_no: str
    name: str = ""
    train_type: str = ""
    origin: str = ""
    destination: str = ""
    dep_time: str | None = None  # "HH:MM" departure from origin
    journey_minutes: int | None = None
    running_days: tuple[str, ...] | None = None
    stops: tuple[RouteStop, ...] = ()


class TimetableSource(Protocol):
    name: str
    calls: int  # requests sent so far (cache hits excluded)

    def list_trains_at(self, station: str) -> list[TrainSummary] | None:
        """All trains scheduled at `station`, or None on a provider error."""
        ...

    def list_trains_between(self, src: str, dst: str) -> list[TrainSummary] | None:
        """Direct trains from `src` to `dst`, or None on a provider error."""
        ...

    def get_schedule(self, train_no: str) -> TrainSchedule | None:
        """Route, times and running days of `train_no`, or None when unknown or on a provider error."""
        ...


def redact(text: str, secrets: list[str]) -> str:
    """Remove credentials from URLs or messages before they are stored or logged."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return re.sub(r"(?i)(api[_-]?key[=/])[^/&?]+", r"\1***", text)
