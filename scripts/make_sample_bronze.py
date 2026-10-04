"""Generate synthetic RailKit-shaped bronze files for local development, tests and CI.

    uv run python scripts/make_sample_bronze.py --out samples/bronze            # 30 days from 2026-12-15
    uv run python scripts/make_sample_bronze.py --out /tmp/b --start 2026-10-01 --days 7

The output mirrors what the collector writes (`patribot.collector.store`):
  <out>/raw/railkit/running_status/collected_date=YYYY-MM-DD/HHMMSSZ.jsonl.gz

Data is SYNTHETIC: routes come from the corridor waypoints in config/corridors.yaml, distances and schedules are made
up, and delays are drawn from a seeded random walk that accumulates along the route (worse in the Dec–Feb fog season
on northern corridors). The default window crosses New Year, to exercise the parser's year inference. A few runs are
deliberately awkward: cancelled (404 every attempt), retried (404 then ok, 429 then ok), incomplete (no actuals near
the destination), a cancelled-flag payload, "*" on actual times, and junk station rows.
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
import zlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from patribot.collector.config import WatchedTrain, load_watchlist

IST = ZoneInfo("Asia/Kolkata")
REPO = Path(__file__).resolve().parents[1]
NORTHERN = {"KOL-DEL", "DEL-PAT", "MUM-DEL"}
PREMIUM = ("RAJDHANI", "DURONTO", "SHATABDI", "VANDE")
CRON_MINUTE = 17  # the collector workflow runs at :17 every 3 hours
STATION_NAMES = {
    "HWH": "HOWRAH JN",
    "SDAH": "SEALDAH",
    "SHM": "SHALIMAR",
    "NDLS": "NEW DELHI",
    "ASN": "ASANSOL JN.",
    "DHN": "DHANBAD JN",
    "GAYA": "GAYA JN",
    "DDU": "PT DEEN DAYAL UPADHYAYA JN",
    "PRYJ": "PRAYAGRAJ JN",
    "CNB": "KANPUR CENTRAL",
    "PNBE": "PATNA JN",
    "RJPB": "RAJENDRANAGAR T",
    "MMCT": "MUMBAI CENTRAL",
    "MAS": "MGR CHENNAI CTL",
}

# Known seed trains: (corridor, path, reverse path?, origin override, destination override, keep every n-th stop)
ROUTES: dict[str, tuple[str, str, bool, str | None, str | None, int]] = {
    "12301": ("KOL-DEL", "grand_chord", False, None, None, 1),
    "12313": ("KOL-DEL", "grand_chord", False, "SDAH", None, 1),
    "12273": ("KOL-DEL", "grand_chord", False, None, None, 3),
    "12381": ("KOL-DEL", "via_patna", False, None, None, 1),
    "12309": ("DEL-PAT", "main", True, "RJPB", None, 1),
    "12951": ("MUM-DEL", "western", False, None, None, 1),
    "12841": ("KOL-MAS", "east_coast", False, "SHM", None, 1),
}


@dataclass
class Stop:
    code: str
    km: float
    sched_arr: datetime | None
    sched_dep: datetime | None


def _h(*parts: object) -> int:
    return zlib.crc32("|".join(map(str, parts)).encode())


def route_for(train: WatchedTrain, corridors: dict[str, dict[str, Any]]) -> tuple[str, list[str]]:
    if train.train_no in ROUTES:
        cid, path, reverse, origin, dest, stride = ROUTES[train.train_no]
    else:
        cid = train.corridors[0] if train.corridors and train.corridors[0] in corridors else next(iter(corridors))
        path = next(iter(corridors[cid]["paths"]))
        reverse, origin, dest, stride = bool(_h(train.train_no) % 2), None, None, 1 + _h(train.train_no, "s") % 2
    codes = list(corridors[cid]["paths"][path])
    if reverse:
        codes.reverse()
    if stride > 1:
        codes = [codes[0], *codes[1:-1][stride - 1 :: stride], codes[-1]]
    if origin:
        codes[0] = origin
    if dest:
        codes[-1] = dest
    return cid, codes


def timetable(train: WatchedTrain, codes: list[str], start: date) -> list[Stop]:
    premium = any(p in train.name.upper() for p in PREMIUM)
    dwell = [0] + [2 if premium else (5 if _h(c) % 3 == 0 else 2) for c in codes[1:-1]] + [0]
    seg_km = [60 + _h(a, b) % 140 for a, b in zip(codes, codes[1:], strict=False)]
    run_minutes = train.journey_minutes - sum(dwell)
    total_km = round(train.journey_minutes * (1.35 if premium else 1.05))
    scale = total_km / sum(seg_km)
    t = datetime.combine(start, train.dep_time, tzinfo=IST)
    km = 0.0
    stops = [Stop(codes[0], 0.0, None, t)]
    for i, seg in enumerate(seg_km, 1):
        km += seg * scale
        t = t + timedelta(minutes=round(run_minutes * seg / sum(seg_km)))
        dep = None if i == len(codes) - 1 else t + timedelta(minutes=dwell[i])
        stops.append(Stop(codes[i], round(km), t, dep))
        if dep:
            t = dep
    return stops


def fmt(ts: datetime | None) -> str:
    return ts.strftime("%H:%M %d-%b") if ts else ""


def delay_text(minutes: int) -> str:
    if minutes <= 0:
        return "On Time"
    h, m = divmod(minutes, 60)
    return f"{h} Hr {m} Min" if h else f"{m} Min"


def simulate(train: WatchedTrain, cid: str, stops: list[Stop], start: date, rng: random.Random) -> list[dict]:
    premium = any(p in train.name.upper() for p in PREMIUM)
    fog = 2.5 if cid in NORTHERN and start.month in (12, 1, 2) else 1.0
    delay = 0 if rng.random() < 0.7 else round(rng.expovariate(1 / (12 * fog)))
    rows = []
    act_dep_prev: datetime | None = None
    for i, s in enumerate(stops):
        row: dict[str, Any] = {"stationCode": s.code, "stationName": STATION_NAMES.get(s.code, f"{s.code} JN")}
        row["platform"] = str(1 + _h(s.code, "pf") % 10)
        if i:
            row["distanceKm"] = str(int(s.km))
        if i == 0:
            act_dep = s.sched_dep + timedelta(minutes=delay)
            row["arrival"] = {"scheduled": "SRC", "actual": "SRC"}
            row["departure"] = {"scheduled": fmt(s.sched_dep), "actual": fmt(act_dep), "delay": delay_text(delay)}
            act_dep_prev = act_dep
            rows.append(row)
            continue
        seg_minutes = (s.sched_arr - (stops[i - 1].sched_dep or s.sched_arr)) / timedelta(minutes=1)
        drift = rng.gauss((1.5 if premium else 4.0) * fog * seg_minutes / 120, 6 * fog)
        if rng.random() < 0.03:
            drift += rng.uniform(45, 180)  # signal failure, crossing, loco trouble
        if i == len(stops) - 1:
            drift -= rng.uniform(0, 15)  # timetable slack before the terminal
        delay = max(-15, round(delay + drift))
        act_arr = max(s.sched_arr + timedelta(minutes=delay), act_dep_prev + timedelta(minutes=10))
        delay = round((act_arr - s.sched_arr) / timedelta(minutes=1))
        row["arrival"] = {"scheduled": fmt(s.sched_arr), "actual": fmt(act_arr), "delay": delay_text(delay)}
        if s.sched_dep is None:
            row["departure"] = {"scheduled": "DSTN", "actual": "DSTN"}
        else:
            act_dep = max(s.sched_dep, act_arr + timedelta(minutes=1))
            dep_delay = round((act_dep - s.sched_dep) / timedelta(minutes=1))
            row["departure"] = {"scheduled": fmt(s.sched_dep), "actual": fmt(act_dep), "delay": delay_text(dep_delay)}
            act_dep_prev = act_dep
            delay = dep_delay
        rows.append(row)
    return rows


def envelope(train_no: str, start: date, fetched: datetime, status: str, http: int, payload: Any) -> dict:
    return {
        "schema_version": 1,
        "source": "railkit",
        "endpoint": f"https://api.railkit.in/api/v1/trains/{train_no}/history/{start:%d-%m-%Y}",
        "train_no": train_no,
        "start_date": start.isoformat(),
        "status": status,
        "http_status": http,
        "fetched_at": fetched.isoformat(),
        "error": None if status == "ok" else f"HTTP {http}: {'Too many requests' if http == 429 else 'Not found'}",
        "payload": payload,
    }


def next_cron(after: datetime) -> datetime:
    """The first collector run (every 3 h at :17 UTC) at or after `after`."""
    t = after.astimezone(UTC).replace(minute=CRON_MINUTE, second=0, microsecond=0)
    while t < after or t.hour % 3:
        t += timedelta(hours=1)
    return t


def generate(out: Path, start: date, days: int, seed: int = 7, watchlist: Path | None = None) -> dict[str, int]:
    wl = load_watchlist(watchlist or REPO / "config" / "watchlist.yaml")
    corridors = {c["id"]: c for c in yaml.safe_load((REPO / "config" / "corridors.yaml").read_text())["corridors"]}
    rng = random.Random(seed)
    batches: dict[datetime, list[dict]] = defaultdict(list)
    counts = defaultdict(int)
    trains = wl.trains
    # deterministic awkward cases, keyed by (train index, day index)
    special = {
        (0, 3): "cancelled",
        (min(3, len(trains) - 1), 11): "cancelled",
        (min(1, len(trains) - 1), 5): "retry_404",
        (min(2, len(trains) - 1), 8): "retry_429",
        (min(4, len(trains) - 1), 13): "incomplete",
        (min(5, len(trains) - 1), 20): "flag_cancelled",
        (0, 16): "junk_rows",
    }
    for ti, train in enumerate(trains):
        cid, codes = route_for(train, corridors)
        for di in range(days):
            start_d = start + timedelta(days=di)
            run_rng = random.Random(f"{seed}-{train.train_no}-{start_d}")
            stops = timetable(train, codes, start_d)
            arrival = stops[-1].sched_arr
            first_try = next_cron(arrival + timedelta(hours=6, minutes=rng.randint(0, 59)))
            kind = special.get((ti, di), "normal")
            if kind == "cancelled":
                for k in range(3):
                    batches[first_try + timedelta(hours=3 * k)].append(
                        envelope(
                            train.train_no,
                            start_d,
                            first_try + timedelta(hours=3 * k, seconds=ti),
                            "not_found",
                            404,
                            {"success": False, "message": "Not found"},
                        )
                    )
                counts["cancelled"] += 1
                continue
            rows = simulate(train, cid, stops, start_d, run_rng)
            note: dict[str, Any] = {}
            if kind == "incomplete":
                for row in rows[-2:]:
                    for side in ("arrival", "departure"):
                        if row[side]["actual"] not in ("SRC", "DSTN"):
                            row[side]["actual"], row[side]["delay"] = "", ""
            elif kind == "flag_cancelled":
                note = {"statusNote": "Train Cancelled"}
                for row in rows:
                    for side in ("arrival", "departure"):
                        if row[side]["actual"] not in ("SRC", "DSTN"):
                            row[side]["actual"], row[side]["delay"] = "", ""
            elif kind == "junk_rows":
                rows.insert(2, {"stationName": "NO CODE", "arrival": {"scheduled": "??"}})
                rows.insert(3, "garbage")  # type: ignore[arg-type]
            if run_rng.random() < 0.3:  # NTES marks some actuals as provisional with "*"
                rows[-1]["arrival"]["actual"] += "*" if rows[-1]["arrival"]["actual"] else ""
            payload = {
                "success": True,
                "data": {
                    "trainNo": train.train_no,
                    "trainName": train.name.upper()[:20] or train.train_no,
                    "journeyDate": f"{start_d:%d-%m-%Y}",
                    "sourceStationCode": codes[0],
                    "destinationStationCode": codes[-1],
                    "stations": rows,
                    "lastUpdate": f"{first_try.astimezone(IST):%d-%m-%Y %H:%M:%S} IST",
                    **note,
                },
            }
            fetched = first_try
            if kind in ("retry_404", "retry_429"):
                http = 404 if kind == "retry_404" else 429
                status = "not_found" if http == 404 else "error"
                batches[fetched].append(envelope(train.train_no, start_d, fetched, status, http, {"success": False}))
                fetched = fetched + timedelta(hours=3)
            batches[fetched].append(
                envelope(train.train_no, start_d, fetched + timedelta(seconds=ti), "ok", 200, payload)
            )
            counts[kind] += 1

    out = Path(out)
    for ts, records in sorted(batches.items()):
        path = out / "raw" / "railkit" / "running_status" / f"collected_date={ts:%Y-%m-%d}" / f"{ts:%H%M%S}Z.jsonl.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    counts["files"] = len(batches)
    counts["trains"] = len(trains)
    return dict(counts)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default="samples/bronze", help="data dir to write raw/ into (default samples/bronze)")
    p.add_argument("--start", type=date.fromisoformat, default=date(2026, 12, 15), help="first run start date")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--watchlist", type=Path, default=None)
    args = p.parse_args(argv)
    print(json.dumps(generate(Path(args.out), args.start, args.days, args.seed, args.watchlist), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
