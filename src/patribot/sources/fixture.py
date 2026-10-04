"""Deterministic offline source for tests and dry runs. Never calls the network."""

from __future__ import annotations

import zlib
from datetime import date

from patribot.sources.base import FetchStatus, RawResponse


class FixtureSource:
    name = "fixture"

    def __init__(self, missing: set[tuple[str, date]] | None = None):
        self.missing = missing or set()
        self.calls: list[tuple[str, date]] = []

    def fetch_run_status(self, train_no: str, start_date: date) -> RawResponse:
        self.calls.append((train_no, start_date))
        if (train_no, start_date) in self.missing:
            return RawResponse(self.name, "fixture://", train_no, start_date, FetchStatus.NOT_FOUND, 404, None)
        delay = zlib.crc32(f"{train_no}{start_date}".encode()) % 240
        payload = {"train_no": train_no, "start_date": start_date.isoformat(), "final_delay_min": delay}
        return RawResponse(self.name, "fixture://", train_no, start_date, FetchStatus.OK, 200, payload)
