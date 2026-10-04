"""RailKit timetable adapter, used to generate the collector watchlist (docs/phase1/watchlist.md).

Endpoints, from the provider's docs (web/components/docs/endpointDocs.ts and README.md in RAJIV81205/RailKit):

  GET /api/v1/stations/{code}/timetable           all trains scheduled at a station, with running days
      -> {"success": true, "data": {"station": "ASN", "totalTrains": 168, "trains": [{"trainNo", "trainName",
          "source", "destination", "trainType", "classes", "runningDays", "arrival", "departure"}]}}
  GET /api/v1/trains/between/{from}/{to}          direct trains between two stations
      -> {"success": true, "data": [{"train_no", "train_name", "source_stn_code", "dstn_stn_code",
          "from_time", "to_time", "travel_time", "running_days", "distance", "halts"}]}
  GET /api/v1/trains/{trainNo}/info               route with halts, cumulative distance and times
      -> {"success": true, "data": {"trainInfo": {"train_no", "train_name", "from_stn_code", "to_stn_code",
          "from_time", "to_time", "travel_time": "17:35 hrs", "running_days": "1111111", "type"},
          "route": [{"stnCode", "arrival": "--", "departure": "16:05", "halt": "0 min", "haltMinutes": 0,
          "distance": "0", "day": "1"}]}}

These shapes have not been seen with a live key yet (the sandbox that built this has no network access to RailKit),
so every parser below is tolerant: alternative key spellings, numbers as strings, missing fields. Two things to
confirm with a real key are flagged as ASSUMPTIONs: the day order of the 7-character `running_days` string and
whether `route` lists stations the train passes without stopping.

Successful responses can be cached on disk (gzipped JSON, keyed by endpoint) so a stopped or repeated build does
not pay for the same request twice. Cache hits do not count as calls.
"""

from __future__ import annotations

import gzip
import json
import re
import time
import zlib
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from patribot.collector.config import WEEKDAYS
from patribot.sources.base import (
    STOP_HTTP_STATUSES,
    CallBudgetExhausted,
    RouteStop,
    SourceStopped,
    TrainSchedule,
    TrainSummary,
)
from patribot.sources.railkit import RailKitClient, error_message

# ASSUMPTION: a 7-character running-days string such as "1111100" starts with Monday. Override with
# `run_days_order="SUN"` (CLI: --run-days-order sun) if a real response shows it starts with Sunday.
DEFAULT_RUN_DAYS_ORDER = "MON"

DAY = 86400.0
# Station lists change with every timetable revision, so they are refreshed on each (weekly) build. Train schedules
# change rarely; they are kept for about 4 weeks, with per-train jitter so refreshes spread over the month.
DEFAULT_TTL_S = {"station": 6 * DAY, "between": 6 * DAY, "schedule": 28 * DAY}


class RailKitTimetableSource(RailKitClient):
    """RailKit timetable endpoints with a max-calls guard and an optional on-disk response cache."""

    def __init__(
        self,
        api_key: str,
        *,
        max_calls: int | None = None,
        cache_dir: str | Path | None = None,
        ttl_s: dict[str, float] | None = None,
        run_days_order: str = DEFAULT_RUN_DAYS_ORDER,
        wall_clock: Callable[[], float] = time.time,
        **kw: Any,
    ):
        super().__init__(api_key, **kw)
        self.max_calls = max_calls
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.ttl_s = DEFAULT_TTL_S | (ttl_s or {})
        self.run_days_order = run_days_order.upper()
        self._now = wall_clock
        self.calls_by_kind: Counter[str] = Counter()
        self.cache_hits = 0
        self.errors: list[str] = []

    # ---- endpoints -------------------------------------------------------------------------------------------

    def list_trains_at(self, station: str) -> list[TrainSummary] | None:
        data = self._fetch("station", f"/api/v1/stations/{station}/timetable")
        if data is None:
            return None
        return [s for s in (parse_summary(t, self.run_days_order) for t in _train_list(data)) if s]

    def list_trains_between(self, src: str, dst: str) -> list[TrainSummary] | None:
        data = self._fetch("between", f"/api/v1/trains/between/{src}/{dst}")
        if data is None:
            return None
        return [s for s in (parse_summary(t, self.run_days_order) for t in _train_list(data)) if s]

    def get_schedule(self, train_no: str) -> TrainSchedule | None:
        data = self._fetch("schedule", f"/api/v1/trains/{train_no}/info")
        if data is None:
            return None
        return parse_schedule(data, train_no, self.run_days_order)

    # ---- plumbing --------------------------------------------------------------------------------------------

    def _fetch(self, kind: str, path: str) -> Any:
        """Return the `data` member of a successful response, or None. Raises SourceStopped on 401/403/429 and
        CallBudgetExhausted when the max-calls guard is reached."""
        cached = self._cache_get(kind, path)
        if cached is not None:
            self.cache_hits += 1
            return cached
        if self.max_calls is not None and self.calls >= self.max_calls:
            raise CallBudgetExhausted(f"max calls ({self.max_calls}) reached before {path}")
        self.calls_by_kind[kind] += 1
        r = self._get(path)
        if r.http_status is None:
            self.errors.append(f"{path}: {r.error}")
            return None
        if r.http_status in STOP_HTTP_STATUSES:
            raise SourceStopped(f"{path}: {error_message(r.http_status, r.payload)}")
        if r.http_status == 404:
            return None
        ok = r.http_status == 200 and isinstance(r.payload, dict) and r.payload.get("success") is not False
        data = r.payload.get("data") if isinstance(r.payload, dict) else None
        if not ok or data is None:
            self.errors.append(f"{path}: {error_message(r.http_status, r.payload)}")
            return None
        self._cache_put(path, data)
        return data

    def _cache_file(self, path: str) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / (re.sub(r"[^A-Za-z0-9]+", "_", path.strip("/")) + ".json.gz")

    def _cache_get(self, kind: str, path: str) -> Any:
        f = self._cache_file(path)
        if f is None or not f.exists():
            return None
        try:
            entry = json.loads(gzip.decompress(f.read_bytes()))
        except (OSError, ValueError):
            return None
        ttl = self.ttl_s.get(kind, 0.0)
        if kind == "schedule":  # spread refreshes: each train expires between 75% and 100% of the TTL
            ttl *= 0.75 + 0.25 * (zlib.crc32(path.encode()) % 1000) / 1000
        if self._now() - float(entry.get("fetched_at", 0)) > ttl:
            return None
        return entry.get("data")

    def _cache_put(self, path: str, data: Any) -> None:
        f = self._cache_file(path)
        if f is None:
            return
        f.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps({"fetched_at": self._now(), "path": path, "data": data}, ensure_ascii=False)
        f.write_bytes(gzip.compress(body.encode("utf-8"), mtime=0))


# ---- tolerant parsing ----------------------------------------------------------------------------------------

_DAY_NAMES = {d: i for i, d in enumerate(WEEKDAYS)}
_TIME = re.compile(r"(\d{1,2}):(\d{2})")


def _pick(d: dict, *keys: str) -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


def _train_list(data: Any) -> list[dict]:
    if isinstance(data, dict):
        data = _pick(data, "trains", "data", "results") or []
    return [t for t in data if isinstance(t, dict)] if isinstance(data, list) else []


def normalize_train_no(value: Any) -> str | None:
    s = str(value or "").strip()
    return s if re.fullmatch(r"\d{5}", s) else None


def parse_hhmm(value: Any) -> str | None:
    """'16:05' / '6:05' / '16:05 05-Oct' -> '16:05'; '--', 'SRC', 'DSTN' -> None."""
    m = _TIME.search(str(value or ""))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def parse_duration_minutes(value: Any) -> int | None:
    """'17:35 hrs' -> 1055, '17h 35m' -> 1055, 1055 -> 1055."""
    if isinstance(value, int | float) and value > 0:
        return int(value)
    s = str(value or "")
    m = re.search(r"(\d+)\s*:\s*(\d{2})", s) or re.search(r"(\d+)\s*h\D*?(\d+)\s*m", s, re.I)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.search(r"(\d+)\s*h", s, re.I)
    return int(m.group(1)) * 60 if m else None


def parse_number(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    m = re.search(r"-?\d+(?:\.\d+)?", str(value or ""))
    return float(m.group()) if m else None


def parse_running_days(value: Any, order: str = DEFAULT_RUN_DAYS_ORDER) -> tuple[str, ...] | None:
    """Return MON..SUN codes, or None when the value carries no usable information.

    Accepts "1111100" / "YYYYYNN" (7 flags starting with `order`), "Daily", "Mon,Wed,Fri", a list of flags or day
    names, or a {"mon": true, ...} mapping."""
    start = 6 if order.upper().startswith("SUN") else 0

    def from_flags(flags: list[bool]) -> tuple[str, ...] | None:
        days = {WEEKDAYS[(start + i) % 7] for i, on in enumerate(flags) if on}
        return tuple(d for d in WEEKDAYS if d in days) or None

    def from_names(text: str) -> tuple[str, ...] | None:
        found = {m.upper() for m in re.findall(r"(?i)\b(mon|tue|wed|thu|fri|sat|sun)", text)}
        return tuple(d for d in WEEKDAYS if d in found) or None

    if isinstance(value, dict):
        return from_names(" ".join(str(k) for k, v in value.items() if v and str(v).lower() not in ("0", "n", "false")))
    if isinstance(value, list | tuple):
        if len(value) == 7 and all(isinstance(v, bool | int) for v in value):
            return from_flags([bool(v) for v in value])
        return from_names(" ".join(map(str, value)))
    s = str(value or "").strip()
    if not s:
        return None
    if re.fullmatch(r"[01]{7}", s) or re.fullmatch(r"(?i)[YN]{7}", s):
        return from_flags([c in "1Yy" for c in s])
    if re.search(r"(?i)\b(daily|all\s*days)\b", s):
        return WEEKDAYS
    return from_names(s)


def parse_summary(t: dict, order: str = DEFAULT_RUN_DAYS_ORDER) -> TrainSummary | None:
    no = normalize_train_no(_pick(t, "trainNo", "train_no", "trainNumber", "number"))
    if no is None:
        return None
    return TrainSummary(
        train_no=no,
        name=str(_pick(t, "trainName", "train_name", "name") or "").strip(),
        train_type=str(_pick(t, "trainType", "train_type", "type") or "").strip(),
        classes=str(_pick(t, "classes", "class", "classList") or "").strip(),
        origin=str(_pick(t, "source", "source_stn_code", "from_stn_code", "sourceCode") or "").strip().upper(),
        destination=str(_pick(t, "destination", "dest", "dstn_stn_code", "to_stn_code") or "").strip().upper(),
        running_days=parse_running_days(_pick(t, "runningDays", "running_days", "runDays", "days"), order),
    )


def parse_stop(s: dict, is_end: bool) -> RouteStop | None:
    code = str(_pick(s, "stnCode", "stationCode", "station_code", "code", "stn_code") or "").strip().upper()
    if not code:
        return None
    halt = _pick(s, "haltMinutes", "halt_minutes")
    halt_min = parse_number(halt if halt is not None else s.get("halt"))
    explicit = _pick(s, "isHalt", "is_halt", "stop", "isStop")
    # ASSUMPTION: `route` lists stopping stations only. If it also lists pass-through stations, those carry a zero
    # halt, so an intermediate zero-halt row is treated as passing through. An explicit flag wins.
    implicit = is_end or halt_min is None or halt_min > 0
    halts = explicit if isinstance(explicit, bool) else implicit
    day = parse_number(_pick(s, "day", "dayCount", "day_count"))
    return RouteStop(
        code=code,
        arrival=parse_hhmm(_pick(s, "arrival", "arrivalTime", "arr")),
        departure=parse_hhmm(_pick(s, "departure", "departureTime", "dep")),
        halt_minutes=int(halt_min) if halt_min is not None else None,
        distance_km=parse_number(_pick(s, "distance", "distanceKm", "distance_km", "km")),
        day=int(day) if day is not None else None,
        halts=halts,
    )


def _journey_from_stops(stops: list[RouteStop]) -> int | None:
    if len(stops) < 2 or not stops[0].departure or not stops[-1].arrival:
        return None
    dh, dm = map(int, stops[0].departure.split(":"))
    ah, am = map(int, stops[-1].arrival.split(":"))
    days = (stops[-1].day or 1) - (stops[0].day or 1)
    minutes = days * 1440 + (ah * 60 + am) - (dh * 60 + dm)
    return minutes if minutes > 0 else None


def parse_schedule(data: Any, train_no: str, order: str = DEFAULT_RUN_DAYS_ORDER) -> TrainSchedule | None:
    if not isinstance(data, dict):
        return None
    info = _pick(data, "trainInfo", "train_info", "train", "info")
    info = info if isinstance(info, dict) else data
    raw_route = _pick(data, "route", "stations", "schedule", "stops")
    raw_route = [r for r in raw_route if isinstance(r, dict)] if isinstance(raw_route, list) else []
    stops = [s for s in (parse_stop(r, i in (0, len(raw_route) - 1)) for i, r in enumerate(raw_route)) if s is not None]
    no = normalize_train_no(_pick(info, "train_no", "trainNo", "trainNumber")) or train_no
    dep = parse_hhmm(_pick(info, "from_time", "fromTime", "departure")) or (stops[0].departure if stops else None)
    journey = parse_duration_minutes(_pick(info, "travel_time", "travelTime", "duration")) or _journey_from_stops(stops)
    return TrainSchedule(
        train_no=no,
        name=str(_pick(info, "train_name", "trainName", "name") or "").strip(),
        train_type=str(_pick(info, "type", "train_type", "trainType") or "").strip(),
        origin=str(_pick(info, "from_stn_code", "fromStnCode", "source") or (stops[0].code if stops else "")).upper(),
        destination=str(_pick(info, "to_stn_code", "toStnCode", "destination") or (stops[-1].code if stops else ""))
        .upper()
        .strip(),
        dep_time=dep,
        journey_minutes=journey,
        running_days=parse_running_days(_pick(info, "running_days", "runningDays", "runDays", "days"), order),
        stops=tuple(stops),
    )
