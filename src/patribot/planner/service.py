"""Keeps a `PlannerData` snapshot fresh for the API: reloads when the repository's version changes (DuckDB file
replaced by a new build) or, without a version (Postgres), after `ttl_s`. A failed reload keeps the last snapshot."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from datetime import date, datetime

from patribot.planner.model import PlannerData
from patribot.planner.repository import PlannerRepository, RepositoryUnavailable, repository_from_env
from patribot.planner.search import IST

log = logging.getLogger(__name__)


def today_ist() -> date:
    """Today in IST, or PATRIBOT_TODAY (YYYY-MM-DD) for demos and tests against old or synthetic data."""
    override = os.environ.get("PATRIBOT_TODAY")
    return date.fromisoformat(override) if override else datetime.now(IST).date()


class PlannerService:
    def __init__(
        self,
        repo: PlannerRepository | None = None,
        today: Callable[[], date] = today_ist,
        ttl_s: float = 300.0,
    ):
        self.repo = repo or repository_from_env()
        self.today = today
        self.ttl_s = ttl_s
        self._data: PlannerData | None = None
        self._version: str | None = None
        self._loaded_at = 0.0
        self._lock = threading.Lock()

    def data(self) -> PlannerData:
        """The current snapshot. Raises RepositoryUnavailable when nothing could ever be loaded."""
        with self._lock:
            version = self.repo.version()
            stale = (
                self._data is None
                or (version is not None and version != self._version)
                or (version is None and time.monotonic() - self._loaded_at > self.ttl_s)
            )
            if stale:
                try:
                    self._data = self.repo.load()
                    self._version, self._loaded_at = version, time.monotonic()
                except RepositoryUnavailable:
                    if self._data is None:
                        raise
                    log.warning("planner data reload failed; serving the previous snapshot", exc_info=True)
            assert self._data is not None
            return self._data
