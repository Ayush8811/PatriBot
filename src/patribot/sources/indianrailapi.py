"""IndianRailAPI.com adapter (Phase 0 primary candidate, docs/phase0/01-api-provider-spike.md).

Endpoint shape is taken from the provider's public docs and is NOT yet verified against a live key; run
`patribot-collector probe` after sign-up and adjust `_classify` once real responses are seen.
"""

from __future__ import annotations

from datetime import date

import httpx

from patribot.sources.base import FetchStatus, RawResponse, redact

DEFAULT_BASE_URL = "https://indianrailapi.com/api/v2"


class IndianRailApiSource:
    name = "indianrailapi"

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, client: httpx.Client | None = None):
        if not api_key:
            raise ValueError("IndianRailAPI requires an API key (env RAIL_API_KEY)")
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=30.0)

    def fetch_run_status(self, train_no: str, start_date: date) -> RawResponse:
        url = f"{self._base}/livetrainstatus/apikey/{self._key}/trainnumber/{train_no}/date/{start_date:%Y%m%d}/"
        safe_url = redact(url, [self._key])
        try:
            resp = self._client.get(url)
        except httpx.HTTPError as exc:
            return RawResponse(
                self.name,
                safe_url,
                train_no,
                start_date,
                FetchStatus.ERROR,
                None,
                None,
                error=redact(str(exc), [self._key]),
            )
        try:
            payload = resp.json()
        except ValueError:
            return RawResponse(
                self.name,
                safe_url,
                train_no,
                start_date,
                FetchStatus.ERROR,
                resp.status_code,
                resp.text[:2000],
                error="non-JSON response",
            )
        return RawResponse(
            self.name,
            safe_url,
            train_no,
            start_date,
            self._classify(resp.status_code, payload),
            resp.status_code,
            payload,
        )

    @staticmethod
    def _classify(http_status: int, payload: object) -> FetchStatus:
        if http_status == 404:
            return FetchStatus.NOT_FOUND
        if http_status != 200 or not payload:
            return FetchStatus.ERROR
        # The provider wraps results with a ResponseCode field; anything other than "200" means no usable data.
        if isinstance(payload, dict) and str(payload.get("ResponseCode", "200")) != "200":
            return FetchStatus.NOT_FOUND
        return FetchStatus.OK
