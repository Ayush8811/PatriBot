"""RailKit adapter (decision D15). API shape verified from the provider's open-source docs
(github.com/RAJIV81205/RailKit, web/components/docs/endpointDocs.ts):

  GET https://api.railkit.in/api/v1/trains/{trainNo}/history/{DD-MM-YYYY}     header: x-api-key
  -> 200 {"success": true, "data": {"stations": [{arrival/departure scheduled, actual, delay}, ...]}}
  -> 404 when the train has not completed that journey

`RailKitClient` holds the shared HTTP plumbing (key header, throttling, call counting, redaction). The timetable
endpoints used to build the watchlist live in `railkit_timetable.py`.

Note: RailKit's terms restrict long-term retention of its data. D15 records that the owner accepts this for the POC
only; RailKit-sourced history must be re-sourced before any commercial use.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from patribot.sources.base import FetchStatus, RawResponse, redact

DEFAULT_BASE_URL = "https://api.railkit.in"
# Advance plan: 600 requests / 10 min. 1.1 s spacing stays under that with margin.
DEFAULT_MIN_INTERVAL_S = 1.1


@dataclass(frozen=True)
class HttpResult:
    url: str  # credentials redacted
    http_status: int | None  # None on a transport failure
    payload: Any
    error: str | None = None


class RailKitClient:
    """Shared HTTP plumbing for RailKit endpoints: `x-api-key` header, request spacing and a call counter."""

    name = "railkit"

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        if not api_key:
            raise ValueError("RailKit requires an API key (env RAIL_API_KEY)")
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._min_interval = min_interval_s
        self._client = client or httpx.Client(
            timeout=30.0, headers={"x-api-key": api_key, "accept": "application/json"}
        )
        self._sleep = sleep
        self._clock = clock
        self._last_call: float | None = None
        self.calls = 0  # HTTP requests actually sent; each one counts against the RailKit quota

    def _throttle(self) -> None:
        if self._last_call is not None:
            wait = self._min_interval - (self._clock() - self._last_call)
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._clock()

    def _get(self, path: str, params: dict[str, str] | None = None) -> HttpResult:
        url = f"{self._base}{path}"
        self._throttle()
        self.calls += 1
        try:
            resp = self._client.get(url, params=params, headers={"x-api-key": self._key})
        except httpx.HTTPError as exc:
            return HttpResult(redact(url, [self._key]), None, None, error=redact(str(exc), [self._key]))
        try:
            payload = resp.json()
        except ValueError:
            payload = resp.text[:2000]
        return HttpResult(redact(str(resp.request.url), [self._key]), resp.status_code, payload)


class RailKitSource(RailKitClient):
    def fetch_run_status(self, train_no: str, start_date: date) -> RawResponse:
        r = self._get(f"/api/v1/trains/{train_no}/history/{start_date:%d-%m-%Y}")
        if r.http_status is None:
            return RawResponse(self.name, r.url, train_no, start_date, FetchStatus.ERROR, None, None, error=r.error)
        status = self._classify(r.http_status, r.payload)
        error = None if status is FetchStatus.OK else error_message(r.http_status, r.payload)
        return RawResponse(self.name, r.url, train_no, start_date, status, r.http_status, r.payload, error=error)

    @staticmethod
    def _classify(http_status: int, payload: object) -> FetchStatus:
        if http_status == 404:
            return FetchStatus.NOT_FOUND  # journey not completed (yet), or not run that day
        if http_status != 200 or not isinstance(payload, dict):
            return FetchStatus.ERROR  # 401 bad key, 429 quota/rate limit, 5xx
        if not payload.get("success") or not payload.get("data"):
            return FetchStatus.NOT_FOUND
        return FetchStatus.OK


def error_message(http_status: int, payload: object) -> str:
    if not isinstance(payload, dict):
        return f"HTTP {http_status}: {str(payload)[:200]}".strip()
    detail = payload.get("message") or payload.get("error") or ""
    return f"HTTP {http_status}: {detail}".strip()
