"""Timetable loader: cached RailKit timetable responses → Parquet silver input for dbt.

The watchlist build (docs/phase1/watchlist.md) caches every successful timetable response in the private data repo,
`state/timetable-cache/*.json.gz`, each file `{"fetched_at": epoch, "path": "/api/v1/...", "data": ...}`:

  /api/v1/trains/{no}/info              train info + route (stopping stations only)
  /api/v1/stations/{code}/timetable     trains at a station, with classes and the finer train type

This module reads that cache (env `PATRIBOT_TIMETABLE_DIR`, default `<PATRIBOT_DATA_DIR>/state/timetable-cache`) and
writes, under `<warehouse_dir>/silver_input/`:

  train_schedule.parquet   one row per train × route stop (times "HH:MM" local, day offset, distance, halt, lat/lon)
  train_info.parquet       one row per train (name, types, origin/destination, running days at origin, classes)
  train_corridor.parquet   corridor membership per train × corridor path, computed with the SAME rule the watchlist
                           uses (`patribot.watchlist.membership`, architecture doc §3.2, D10)

The output is RailKit-derived (D15): it stays in the git-ignored warehouse and is never committed.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa

from patribot.sources.railkit_timetable import (
    _pick,
    normalize_train_no,
    parse_hhmm,
    parse_number,
    parse_running_days,
    parse_schedule,
    parse_stop,
)
from patribot.transform.bronze import _write_atomic, silver_input_dir
from patribot.watchlist.corridors import CorridorConfig, load_corridors
from patribot.watchlist.membership import exclusion_reason, memberships, path_slots

log = logging.getLogger(__name__)

SOURCE = "railkit"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CORRIDORS = REPO_ROOT / "config" / "corridors.yaml"

_INFO_PATH = re.compile(r"^/api/v1/trains/(\d{5})/info$")
_STATION_PATH = re.compile(r"^/api/v1/stations/([A-Za-z0-9]+)/timetable$")
_TS_UTC = pa.timestamp("us", tz="UTC")

SCHEDULE_SCHEMA = pa.schema(
    [
        ("source", pa.string()),
        ("train_no", pa.string()),
        ("seq", pa.int32()),
        ("station_code", pa.string()),
        ("station_name", pa.string()),
        ("arr", pa.string()),  # "HH:MM" local, NULL at the origin
        ("dep", pa.string()),  # "HH:MM" local, NULL at the destination
        ("day_offset", pa.int32()),  # 0 = the day the train leaves its origin; day of the arrival (else departure)
        ("dep_day_offset", pa.int32()),  # day of the departure (differs when the halt crosses midnight)
        ("distance_km", pa.float64()),
        ("halt_min", pa.int32()),
        ("halts", pa.bool_()),
        ("platform", pa.string()),
        ("lat", pa.float64()),
        ("lon", pa.float64()),
    ]
)

INFO_SCHEMA = pa.schema(
    [
        ("source", pa.string()),
        ("train_no", pa.string()),
        ("train_name", pa.string()),
        ("train_type", pa.string()),  # provider's coarse type from train info, e.g. RAJDHANI, SUPERFAST
        ("train_type_detail", pa.string()),  # station timetables' finer type, e.g. "Vande Bharat", "Garib Rath"
        ("train_type_display", pa.string()),  # detail, else the coarse type title-cased ("Mail Express")
        ("origin_code", pa.string()),
        ("destination_code", pa.string()),
        ("dep_time", pa.string()),
        ("arr_time", pa.string()),
        ("travel_minutes", pa.int32()),
        ("running_days", pa.list_(pa.string())),  # MON..SUN, at the ORIGIN
        ("classes", pa.list_(pa.string())),  # reserved classes, from station timetables; empty when unknown
        ("exclusion_reason", pa.string()),  # NULL = reserved train (BRD §5.3)
        ("n_stops", pa.int32()),
        ("fetched_at", _TS_UTC),
    ]
)

CORRIDOR_SCHEMA = pa.schema(
    [
        ("train_no", pa.string()),
        ("corridor_id", pa.string()),
        ("path_name", pa.string()),
        ("from_code", pa.string()),
        ("to_code", pa.string()),
        ("segments", pa.int32()),
        ("km", pa.float64()),
        ("direction", pa.string()),
    ]
)

# Unreserved / non-class tokens seen in station timetables' `classes` (e.g. "1A,2A,3A,SL,GEN,PWD").
NON_RESERVED_CLASSES = {"GEN", "GN", "UR", "GS", "II", "PWD", "UNRESERVED", "SLRD", "LADIES"}
CLASS_ORDER = ["1A", "EV", "EC", "2A", "FC", "3A", "3E", "VS", "CC", "SL", "2S"]


@dataclass
class TimetableStats:
    files: int = 0
    bad_files: int = 0
    train_files: int = 0
    station_files: int = 0
    other_files: int = 0
    trains: int = 0
    stops: int = 0
    reserved_trains: int = 0
    member_trains: int = 0
    memberships: int = 0
    excluded: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def timetable_dir(data_dir: str | Path | None = None) -> Path:
    """`PATRIBOT_TIMETABLE_DIR`, else `<data_dir>/state/timetable-cache` (data_dir defaults to PATRIBOT_DATA_DIR)."""
    env = os.environ.get("PATRIBOT_TIMETABLE_DIR")
    if env:
        return Path(env)
    return Path(data_dir or os.environ.get("PATRIBOT_DATA_DIR") or "data") / "state" / "timetable-cache"


def timetable_files(cache_dir: str | Path) -> list[Path]:
    return sorted(Path(cache_dir).glob("*.json.gz"))


def _read(path: Path) -> dict[str, Any] | None:
    try:
        entry = json.loads(gzip.decompress(path.read_bytes()))
    except (OSError, ValueError, EOFError):
        return None
    return entry if isinstance(entry, dict) and isinstance(entry.get("path"), str) else None


def sort_classes(classes: set[str]) -> list[str]:
    return sorted(classes, key=lambda c: (CLASS_ORDER.index(c) if c in CLASS_ORDER else len(CLASS_ORDER), c))


def reserved_classes(text: str) -> set[str]:
    return {c for c in re.split(r"[\s,/|]+", (text or "").upper()) if c and c not in NON_RESERVED_CLASSES}


def display_type(coarse: str | None, detail: str | None) -> str | None:
    """'Vande Bharat' (station timetable) beats 'SHATABDI' (train info); 'MAIL_EXPRESS' → 'Mail Express'."""
    if detail:
        return detail
    words = re.sub(r"[_\s]+", " ", coarse or "").strip()
    return words.title() if re.fullmatch(r"[A-Za-z ]+", words) else None


def _clock(hhmm: str | None) -> int | None:
    if not hhmm:
        return None
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def day_offsets(rows: list[tuple[str | None, str | None, int | None]]) -> list[tuple[int | None, int | None]]:
    """(arrival, departure) 0-based day offsets per stop from (arr "HH:MM", dep "HH:MM", provider day) rows.

    Times along a route never go backwards and no gap between consecutive times reaches 24 h, so each time is placed
    at the earliest day that keeps the sequence monotonic. The provider's `day` (1 = origin day) is a floor. RailKit's
    `day` is the DEPARTURE day when a halt crosses midnight (arrival 23:45 on day 1, departure 00:40, day "2"); other
    sources may use the arrival day; the floor is set so that both conventions give the same result."""
    out: list[tuple[int | None, int | None]] = []
    prev_abs: int | None = None  # absolute minutes (from midnight of day 0) of the previous time on the route

    def place(clock: int | None, floor_day: int) -> int | None:
        nonlocal prev_abs
        if clock is None:
            return None
        t = max(floor_day, 0) * 1440 + clock
        if prev_abs is not None:
            while t < prev_abs:
                t += 1440
        prev_abs = t
        return t // 1440

    for arr, dep, day in rows:
        a, d = _clock(arr), _clock(dep)
        crosses = a is not None and d is not None and d < a
        base = (day - 1) if day is not None and day >= 1 else 0
        arr_off = place(a, base - 1 if crosses else base)
        dep_off = place(d, base)
        out.append((arr_off, dep_off))
    return out


def parse_train_info(entry: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """One cached `/trains/{no}/info` response → (train row without classes/types detail, stop rows)."""
    m = _INFO_PATH.match(entry["path"])
    data = entry.get("data")
    if not m or not isinstance(data, dict):
        return None
    sched = parse_schedule(data, m.group(1))
    if sched is None:
        return None
    raw_route = _pick(data, "route", "stations", "schedule", "stops")
    raw_route = [r for r in raw_route if isinstance(r, dict)] if isinstance(raw_route, list) else []
    parsed = []
    for i, r in enumerate(raw_route):
        stop = parse_stop(r, i in (0, len(raw_route) - 1))
        if stop is not None:
            parsed.append((stop, r))
    if len(parsed) < 2:
        return None
    offsets = day_offsets([(s.arrival, s.departure, s.day) for s, _ in parsed])
    stops = []
    for seq, ((s, r), (arr_off, dep_off)) in enumerate(zip(parsed, offsets, strict=True), 1):
        coords = r.get("coordinates") if isinstance(r.get("coordinates"), dict) else {}
        lat = parse_number(_pick(coords, "latitude", "lat")) if coords else None
        lon = parse_number(_pick(coords, "longitude", "lng", "lon")) if coords else None
        platform = _pick(r, "platform", "pf")
        stops.append(
            {
                "source": SOURCE,
                "train_no": sched.train_no,
                "seq": seq,
                "station_code": s.code,
                "station_name": str(_pick(r, "stnName", "stationName", "station_name", "name") or "").strip() or None,
                "arr": None if seq == 1 else s.arrival,
                "dep": None if seq == len(parsed) else s.departure,
                "day_offset": arr_off if arr_off is not None and seq > 1 else (dep_off or 0),
                "dep_day_offset": dep_off if seq < len(parsed) else None,
                "distance_km": s.distance_km,
                "halt_min": s.halt_minutes,
                "halts": bool(s.halts),
                "platform": str(platform) if platform not in (None, "", "--") else None,
                "lat": lat if lat not in (None, 0.0) else None,
                "lon": lon if lon not in (None, 0.0) else None,
            }
        )
    info = _pick(data, "trainInfo", "train_info", "train", "info")
    info = info if isinstance(info, dict) else data
    fetched = entry.get("fetched_at")
    train = {
        "source": SOURCE,
        "train_no": sched.train_no,
        "train_name": sched.name or None,
        "train_type": sched.train_type or None,
        "origin_code": sched.origin or stops[0]["station_code"],
        "destination_code": sched.destination or stops[-1]["station_code"],
        "dep_time": sched.dep_time,
        "arr_time": parse_hhmm(_pick(info, "to_time", "toTime", "arrival")) or stops[-1]["arr"],
        "travel_minutes": sched.journey_minutes,
        "running_days": list(sched.running_days) if sched.running_days else [],
        "n_stops": len(stops),
        "fetched_at": datetime.fromtimestamp(float(fetched), UTC) if isinstance(fetched, int | float) else None,
    }
    return train, stops


@dataclass
class StationListing:
    classes: set[str] = field(default_factory=set)
    types: Counter[str] = field(default_factory=Counter)
    names: Counter[str] = field(default_factory=Counter)
    running_days: tuple[str, ...] | None = None


def parse_station_timetable(entry: dict[str, Any], listings: dict[str, StationListing]) -> bool:
    """Collect classes, finer train type and name per train from a cached `/stations/{code}/timetable` response."""
    if not _STATION_PATH.match(entry["path"]):
        return False
    data = entry.get("data")
    trains = _pick(data, "trains", "data", "results") if isinstance(data, dict) else data
    if not isinstance(trains, list):
        return True
    for t in trains:
        if not isinstance(t, dict):
            continue
        no = normalize_train_no(_pick(t, "trainNo", "train_no", "trainNumber", "number"))
        if not no:
            continue
        lst = listings.setdefault(no, StationListing())
        lst.classes |= reserved_classes(str(_pick(t, "classes", "class", "classList") or ""))
        if ttype := str(_pick(t, "trainType", "train_type", "type") or "").strip():
            lst.types[ttype] += 1
        if name := str(_pick(t, "trainName", "train_name", "name") or "").strip():
            lst.names[name] += 1
    return True


def build_timetable_tables(
    cache_dir: str | Path, corridors: CorridorConfig | None = None
) -> tuple[pa.Table, pa.Table, pa.Table, TimetableStats]:
    cfg = corridors or load_corridors(DEFAULT_CORRIDORS)
    stats = TimetableStats()
    trains: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]] = {}
    listings: dict[str, StationListing] = {}
    for path in timetable_files(cache_dir):
        stats.files += 1
        entry = _read(path)
        if entry is None:
            stats.bad_files += 1
            continue
        if _INFO_PATH.match(entry["path"]):
            parsed = parse_train_info(entry)
            if parsed is None:
                stats.bad_files += 1
                continue
            stats.train_files += 1
            no = parsed[0]["train_no"]
            prev = trains.get(no)
            if prev is None or (parsed[0]["fetched_at"] or datetime.min.replace(tzinfo=UTC)) >= (
                prev[0]["fetched_at"] or datetime.min.replace(tzinfo=UTC)
            ):
                trains[no] = parsed
        elif parse_station_timetable(entry, listings):
            stats.station_files += 1
        else:
            stats.other_files += 1

    all_slots = path_slots(cfg)
    rule = cfg.membership
    info_rows, stop_rows, corridor_rows = [], [], []
    excluded: Counter[str] = Counter()
    for no in sorted(trains):
        train, stops = trains[no]
        lst = listings.get(no, StationListing())
        detail = lst.types.most_common(1)[0][0] if lst.types else None
        train["train_type_detail"] = detail
        train["train_type_display"] = display_type(train["train_type"], detail)
        train["classes"] = sort_classes(lst.classes)
        if not train["train_name"] and lst.names:
            train["train_name"] = lst.names.most_common(1)[0][0]
        reason = exclusion_reason(
            no,
            train["train_name"] or "",
            f"{train['train_type'] or ''} {detail or ''}",
            ",".join(sorted(lst.classes)) if lst.classes else "",
            rule.exclude_train_types,
        )
        train["exclusion_reason"] = reason
        info_rows.append(train)
        stop_rows.extend(stops)
        if reason:
            excluded[reason] += 1
            continue
        stats.reserved_trains += 1
        route = parse_schedule_stops(stops)
        matches = memberships(route, all_slots, rule)
        if matches:
            stats.member_trains += 1
        for m in matches:
            corridor_rows.append(
                {
                    "train_no": no,
                    "corridor_id": m.corridor,
                    "path_name": m.path,
                    "from_code": m.from_code,
                    "to_code": m.to_code,
                    "segments": m.segments,
                    "km": m.km,
                    "direction": m.direction,
                }
            )
    stats.trains = len(info_rows)
    stats.stops = len(stop_rows)
    stats.memberships = len(corridor_rows)
    stats.excluded = dict(sorted(excluded.items()))
    return (
        pa.Table.from_pylist(stop_rows, schema=SCHEDULE_SCHEMA),
        pa.Table.from_pylist(info_rows, schema=INFO_SCHEMA),
        pa.Table.from_pylist(corridor_rows, schema=CORRIDOR_SCHEMA),
        stats,
    )


def parse_schedule_stops(stops: list[dict[str, Any]]):
    """Stop rows → `RouteStop`s for the membership functions."""
    from patribot.sources.base import RouteStop

    return [
        RouteStop(
            code=s["station_code"],
            arrival=s["arr"],
            departure=s["dep"],
            halt_minutes=s["halt_min"],
            distance_km=s["distance_km"],
            day=s["day_offset"] + 1,
            halts=s["halts"],
        )
        for s in stops
    ]


def build_timetable_input(
    cache_dir: str | Path, warehouse_dir: str | Path, corridors: str | Path | None = None
) -> TimetableStats:
    """Rebuild the three timetable Parquet files (empty, with their schema, when there is no cache)."""
    cfg = load_corridors(corridors or DEFAULT_CORRIDORS)
    if not Path(cache_dir).exists():
        log.warning("timetable cache %s does not exist; writing empty timetable tables", cache_dir)
    schedule, info, corridor, stats = build_timetable_tables(cache_dir, cfg)
    out = silver_input_dir(warehouse_dir)
    _write_atomic(schedule, out / "train_schedule.parquet")
    _write_atomic(info, out / "train_info.parquet")
    _write_atomic(corridor, out / "train_corridor.parquet")
    log.info("timetable input: %s", stats.as_dict())
    return stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build the Parquet timetable input from cached RailKit responses.")
    p.add_argument("--timetable-dir", default=None, help="default: $PATRIBOT_TIMETABLE_DIR or <data dir>/state/...")
    p.add_argument("--data-dir", default=os.environ.get("PATRIBOT_DATA_DIR", "data"))
    p.add_argument("--warehouse-dir", default=os.environ.get("PATRIBOT_WAREHOUSE_DIR", "warehouse"))
    p.add_argument("--corridors", default=str(DEFAULT_CORRIDORS))
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cache = Path(args.timetable_dir) if args.timetable_dir else timetable_dir(args.data_dir)
    stats = build_timetable_input(cache, args.warehouse_dir, args.corridors)
    print(json.dumps(stats.as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
