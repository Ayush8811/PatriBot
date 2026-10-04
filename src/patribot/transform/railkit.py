"""Parse RailKit journey-history envelopes into canonical stop rows (silver input).

Payload shape (provider docs, `GET /api/v1/trains/{trainNo}/history/{DD-MM-YYYY}`):

    {"success": true, "data": {"trainNo": "12301", "journeyDate": "11-06-2026", "sourceStationCode": "HWH", ...,
     "stations": [{"stationCode": "HWH", "stationName": "HOWRAH JN", "platform": "9", "distanceKm": "",
                   "arrival": {"scheduled": "SRC", "actual": "SRC"},
                   "departure": {"scheduled": "16:50 11-Jun", "actual": "16:50 11-Jun", "delay": "On Time"}}, ...],
     "lastUpdate": "12-06-2026 11:12:53 IST"}}

Quirks handled here:
- Times are "HH:MM DD-Mon" in IST with no year. The year is inferred from the run's start date, so a run that
  starts on 31 Dec and arrives on "05:10 01-Jan" lands in the next year.
- "SRC" / "DSTN" mark the missing arrival at the origin and departure at the destination.
- Actual times can carry a trailing "*" (estimated or not yet confirmed by NTES). It is stripped.
- Delay strings ("On Time", "16 Min", "1 Hr 5 Min", "21 Mins.") are a fallback only. When both scheduled and actual
  times parse, delay = actual − scheduled.
- A malformed station row is skipped, never fatal. A malformed payload yields no rows.

Everything here is pure: no I/O, so the functions are easy to test and reuse in the ETA nowcast later.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
SOURCE = "railkit"

_MARKERS = {"", "SRC", "DSTN", "-", "--", "NA", "N/A", "NULL", "NONE"}
_MONTHS = {
    m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)
}
# "16:50 11-Jun", "16:50 11-Jun-2026", "16:50 11-Jun-26", "6:05 1-Jan"
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})\s+(\d{1,2})[-\s]([A-Za-z]{3})[A-Za-z]*(?:[-\s](\d{2}|\d{4}))?$")
_DELAY_PART_RE = re.compile(r"(\d+)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes)\b", re.IGNORECASE)
_CANCEL_RE = re.compile(r"\bcancel", re.IGNORECASE)
_PASS_THROUGH = {"intermediate", "pass", "passing", "non-stoppage", "nonstoppage", "non_stoppage"}


@dataclass(frozen=True)
class StopRow:
    """One stop of one run. Times are timezone-aware IST datetimes or None."""

    source: str
    train_no: str
    start_date: date
    seq: int  # 1-based position among the kept stops
    station_code: str
    station_name: str | None
    distance_km: float | None
    sched_arr: datetime | None
    act_arr: datetime | None
    sched_dep: datetime | None
    act_dep: datetime | None
    arr_delay_min: int | None
    dep_delay_min: int | None
    platform: str | None
    is_origin: bool
    is_destination: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RunHeader:
    """Run-level facts from the payload header. Cancellation is a best-effort flag: RailKit's history endpoint
    usually answers 404 for a cancelled run, which the collector already records as `not_found`."""

    source: str
    train_no: str
    start_date: date
    train_name: str | None
    journey_date: date | None
    origin_code: str | None
    destination_code: str | None
    n_stations_raw: int
    n_stations_parsed: int
    is_cancelled: bool
    last_update: datetime | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ParsedRun:
    header: RunHeader
    stops: list[StopRow]


# ---- scalar parsers ---------------------------------------------------------------------------------------


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().rstrip("*").strip()
    return None if text.upper() in _MARKERS else text


def parse_ir_time(value: Any, ref: date) -> datetime | None:
    """Parse "HH:MM DD-Mon" (IST, no year) choosing the year that puts it closest to `ref` (the run start date).

    Returns None for markers ("SRC", "DSTN", ""), unparseable text and impossible dates."""
    text = _clean(value)
    if text is None:
        return None
    m = _TIME_RE.match(text)
    if not m:
        return None
    hh, mm, dd, mon, yy = int(m[1]), int(m[2]), int(m[3]), _MONTHS.get(m[4].upper()), m[5]
    if mon is None or hh > 23 or mm > 59:
        return None
    years = [int(yy) + (2000 if len(yy) == 2 else 0)] if yy else [ref.year - 1, ref.year, ref.year + 1]
    anchor = datetime(ref.year, ref.month, ref.day, tzinfo=IST)
    best: datetime | None = None
    for year in years:
        try:
            cand = datetime(year, mon, dd, hh, mm, tzinfo=IST)
        except ValueError:  # 29-Feb in a non-leap year, 31-Apr, ...
            continue
        if best is None or abs(cand - anchor) < abs(best - anchor):
            best = cand
    return best


def parse_delay_text(value: Any) -> int | None:
    """Parse a provider delay string into minutes. "On Time" → 0, "1 Hr 5 Min" → 65, "21 Mins." → 21.

    "Before"/"early"/a leading minus make it negative. Bare numbers are minutes. Anything else → None."""
    if value is None:
        return None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return int(value)
    text = str(value).strip()
    if not text or text.upper() in _MARKERS:
        return None
    low = text.lower()
    if "on time" in low or low in {"ontime", "rt", "right time"}:
        return 0
    sign = -1 if (low.startswith("-") or "before" in low or "early" in low) else 1
    if re.fullmatch(r"[-+]?\d+", low):
        return int(low)
    parts = _DELAY_PART_RE.findall(low)
    if not parts:
        # "01:05" style
        hm = re.fullmatch(r"[-+]?(\d{1,2}):(\d{2})", low)
        return sign * (int(hm[1]) * 60 + int(hm[2])) if hm else None
    total = 0
    for num, unit in parts:
        total += int(num) * (60 if unit.lower().startswith("h") else 1)
    return sign * total


def parse_distance(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value) if value >= 0 else None
    m = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(m[0]) if m else None


def parse_dmy(value: Any) -> date | None:
    """Parse "DD-MM-YYYY" (also "DD-Mon-YYYY") into a date."""
    text = _clean(value)
    if text is None:
        return None
    for fmt in ("%d-%m-%Y", "%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_last_update(value: Any) -> datetime | None:
    text = _clean(value)
    if text is None:
        return None
    text = re.sub(r"\s*IST$", "", text)
    try:
        return datetime.strptime(text, "%d-%m-%Y %H:%M:%S").replace(tzinfo=IST)
    except ValueError:
        return None


def _minutes(later: datetime | None, earlier: datetime | None) -> int | None:
    if later is None or earlier is None:
        return None
    return round((later - earlier) / timedelta(minutes=1))


def _delay(sched: datetime | None, act: datetime | None, text: Any) -> int | None:
    computed = _minutes(act, sched)
    return computed if computed is not None else parse_delay_text(text)


# ---- envelope / payload parsers ---------------------------------------------------------------------------


def _section(row: dict[str, Any], key: str) -> dict[str, Any]:
    sec = row.get(key)
    return sec if isinstance(sec, dict) else {}


def _is_marker(value: Any, marker: str) -> bool:
    return isinstance(value, str) and value.strip().upper() == marker


def _looks_cancelled(data: dict[str, Any]) -> bool:
    for key in ("cancelled", "isCancelled", "is_cancelled"):
        val = data.get(key)
        if val is True or (isinstance(val, str) and val.strip().lower() in {"true", "yes", "y", "1"}):
            return True
    for key in ("statusNote", "status", "trainStatus", "message"):
        val = data.get(key)
        if isinstance(val, str) and _CANCEL_RE.search(val):
            return True
    return False


def parse_payload(payload: Any, train_no: str, start_date: date) -> ParsedRun | None:
    """Parse a RailKit history payload for the run (train_no, start_date). None if the payload is unusable."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    stations = data.get("stations")
    if not isinstance(stations, list):
        stations = data.get("timeline") if isinstance(data.get("timeline"), list) else []

    kept: list[dict[str, Any]] = []
    for raw in stations:
        if not isinstance(raw, dict):
            continue
        code = raw.get("stationCode")
        if not isinstance(code, str) or not code.strip():
            continue
        if str(raw.get("type") or "").lower() in _PASS_THROUGH:  # live timelines also list non-halt points
            continue
        kept.append(raw)

    stops: list[StopRow] = []
    last = len(kept) - 1
    for i, raw in enumerate(kept):
        arr, dep = _section(raw, "arrival"), _section(raw, "departure")
        sched_arr = parse_ir_time(arr.get("scheduled"), start_date)
        act_arr = parse_ir_time(arr.get("actual"), start_date)
        sched_dep = parse_ir_time(dep.get("scheduled"), start_date)
        act_dep = parse_ir_time(dep.get("actual"), start_date)
        is_origin = _is_marker(arr.get("scheduled"), "SRC") or i == 0
        is_destination = _is_marker(dep.get("scheduled"), "DSTN") or i == last
        if sched_arr is None and sched_dep is None and not (is_origin or is_destination):
            continue  # no usable schedule at an intermediate stop: nothing to learn from it
        distance = parse_distance(raw.get("distanceKm"))
        if distance is None and is_origin:
            distance = 0.0
        name = raw.get("stationName")
        platform = _clean(raw.get("platform"))
        stops.append(
            StopRow(
                source=SOURCE,
                train_no=train_no,
                start_date=start_date,
                seq=len(stops) + 1,
                station_code=raw["stationCode"].strip().upper(),
                station_name=name.strip() if isinstance(name, str) and name.strip() else None,
                distance_km=distance,
                sched_arr=None if is_origin else sched_arr,
                act_arr=None if is_origin else act_arr,
                sched_dep=None if is_destination else sched_dep,
                act_dep=None if is_destination else act_dep,
                arr_delay_min=None if is_origin else _delay(sched_arr, act_arr, arr.get("delay")),
                dep_delay_min=None if is_destination else _delay(sched_dep, act_dep, dep.get("delay")),
                platform=platform,
                is_origin=is_origin,
                is_destination=is_destination,
            )
        )

    name = data.get("trainName")
    header = RunHeader(
        source=SOURCE,
        train_no=train_no,
        start_date=start_date,
        train_name=name.strip() if isinstance(name, str) and name.strip() else None,
        journey_date=parse_dmy(data.get("journeyDate") or data.get("date")),
        origin_code=_clean(data.get("sourceStationCode")),
        destination_code=_clean(data.get("destinationStationCode")),
        n_stations_raw=len(stations),
        n_stations_parsed=len(stops),
        is_cancelled=_looks_cancelled(data),
        last_update=_parse_last_update(data.get("lastUpdate")),
    )
    return ParsedRun(header, stops)


def parse_envelope(envelope: dict[str, Any]) -> ParsedRun | None:
    """Parse one bronze envelope (see `RawResponse.to_record`). Only `ok` RailKit envelopes yield a run."""
    if not isinstance(envelope, dict) or envelope.get("source") != SOURCE or envelope.get("status") != "ok":
        return None
    train_no = envelope.get("train_no")
    try:
        start_date = date.fromisoformat(str(envelope.get("start_date")))
    except ValueError:
        return None
    if not isinstance(train_no, str) or not train_no:
        return None
    return parse_payload(envelope.get("payload"), train_no, start_date)
