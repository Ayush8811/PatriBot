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


def redact(text: str, secrets: list[str]) -> str:
    """Remove credentials from URLs or messages before they are stored or logged."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return re.sub(r"(?i)(api[_-]?key[=/])[^/&?]+", r"\1***", text)
