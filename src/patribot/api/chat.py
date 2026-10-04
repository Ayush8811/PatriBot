"""`POST /chat` stub (docs/api/v1.md; the AI chat arrives in Phase 4). Parses simple messages with rules, not an
LLM, runs the same planner as `/plan` and answers with a fixed message plus the itineraries.

Understood: places (cluster names and aliases, station codes, station names) with "from"/"to"; dates ("Nov 20-30",
"20-30 Nov", "25 November", "2026-11-25", "today", "tomorrow"); "overnight"; "fastest" / "least travel time";
"reliable" / "on time"; "split" / "break journey" / "full"; "reach … by 9 AM" (hard arrive-by on P90); classes
("3A", "3AC", "sleeper").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from patribot.planner.model import PlannerData
from patribot.planner.places import CLUSTER_ALIASES, station_key
from patribot.planner.schemas import PlanRequest, Preferences

MONTHS = {m: i for i, m in enumerate(("jan feb mar apr may jun jul aug sep oct nov dec").split(), 1)}
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
CLASS_WORDS = {
    "1a": "1A", "1ac": "1A", "2a": "2A", "2ac": "2A", "3a": "3A", "3ac": "3A", "3e": "3E", "sl": "SL",
    "sleeper": "SL", "cc": "CC", "ec": "EC", "chair car": "CC",
}  # fmt: skip


@dataclass
class Parsed:
    request: PlanRequest | None
    question: str | None = None  # a clarifying question when something essential is missing (FR-3)
    summary: str = ""


def _future(day: int, month: int, today: date) -> date | None:
    """The next date with this day and month on or after today."""
    for year in (today.year, today.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if d >= today:
            return d
    return None


def parse_dates(text: str, today: date) -> tuple[date, date] | None:
    t = text.lower()
    if m := re.search(r"(\d{4}-\d{2}-\d{2})(?:\s*(?:to|-|–|until)\s*(\d{4}-\d{2}-\d{2}))?", t):
        d0 = date.fromisoformat(m.group(1))
        return d0, date.fromisoformat(m.group(2)) if m.group(2) else d0
    if m := re.search(rf"\b{_MON}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*(?:-|–|to)\s*(\d{{1,2}})(?:st|nd|rd|th)?)?\b", t):
        month, d0, d1 = MONTHS[m.group(1)], int(m.group(2)), int(m.group(3) or m.group(2))
    elif m := re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*(?:-|–|to)\s*(\d{{1,2}})(?:st|nd|rd|th)?)?\s+{_MON}", t):
        d0, d1, month = int(m.group(1)), int(m.group(2) or m.group(1)), MONTHS[m.group(3)]
    elif re.search(r"\btomorrow\b", t):
        return today + timedelta(days=1), today + timedelta(days=1)
    elif re.search(r"\btoday\b|\btonight\b", t):
        return today, today
    else:
        return None
    start = _future(d0, month, today)
    if start is None:
        return None
    try:
        end = date(start.year, month, d1)
    except ValueError:
        return None
    return (start, end) if end >= start else (start, start)


def parse_places(text: str, data: PlannerData) -> tuple[str | None, str | None]:
    """(origin, destination) as cluster ids or station codes. 'to X' marks the destination, 'from X' the origin;
    otherwise the first place mentioned is the origin."""
    low = text.lower()
    mentions: list[tuple[int, int, str]] = []  # (start, end, place id)
    names: list[tuple[str, str]] = [(alias, cid) for cid, al in CLUSTER_ALIASES.items() for alias in al]
    names += [(cid.lower(), cid) for cid in data.clusters]
    names += [(station_key(s.name), s.code) for s in data.stations.values() if s.name and len(station_key(s.name)) > 3]
    for name, pid in sorted(names, key=lambda x: -len(x[0])):
        for m in re.finditer(rf"\b{re.escape(name)}\b", low):
            if not any(s <= m.start() < e for s, e, _ in mentions):
                mentions.append((m.start(), m.end(), pid))
    for m in re.finditer(r"\b[A-Z]{2,5}\b", text):  # station codes typed in capitals
        if m.group() in data.stations and not any(s <= m.start() < e for s, e, _ in mentions):
            mentions.append((m.start(), m.end(), m.group()))
    mentions.sort()
    origin = dest = None
    for start, _, pid in mentions:
        before = low[max(0, start - 6) : start]
        if re.search(r"\bto\s*$", before) and dest is None:
            dest = pid
        elif re.search(r"\bfrom\s*$", before) and origin is None:
            origin = pid
    rest = [pid for _, _, pid in mentions if pid not in (origin, dest)]
    if origin is None and rest:
        origin = rest.pop(0)
    if dest is None and rest:
        dest = rest.pop(0)
    return origin, dest


def parse_message(text: str, data: PlannerData, today: date) -> Parsed:
    low = text.lower()
    origin, dest = parse_places(text, data)
    dates = parse_dates(text, today)
    missing = [w for w, v in (("where you are starting from", origin), ("where you want to go", dest)) if not v]
    if not dates:
        missing.append("your travel date or date range (e.g. 'Nov 20-30')")
    if missing:
        return Parsed(None, question=f"Could you tell me {' and '.join(missing)}?")
    assert dates is not None
    prefs: dict = {"objective": "balanced"}
    if re.search(r"\bovernight\b|\bnight train\b", low):
        prefs["overnight"] = True
    if re.search(r"fastest|quickest|least (travel )?time|shortest", low):
        prefs["objective"] = "fastest"
    elif re.search(r"reliab|on[- ]time|punctual", low):
        prefs["objective"] = "most_reliable"
    if re.search(r"split|break journey|change trains?|connection|\bfull\b|\bvia\b", low):
        prefs["allow_split"] = True
    d0, d1 = dates
    if m := re.search(r"\bby\s+(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?", low):
        h, mins = int(m.group(1)), int(m.group(2) or 0)
        if m.group(3) and m.group(3).startswith("p") and h < 12:
            h += 12
        if m.group(3) and m.group(3).startswith("a") and h == 12:
            h = 0
        if 0 <= h <= 23 and 0 <= mins <= 59:
            prefs.update(arrive_by=f"{h:02d}:{mins:02d}", hard=["arrive_by"])
            if d0 == d1:  # "reach Delhi by 9 AM on Nov 25": the date is the arrival day
                prefs["arrive_by_date"] = d1
                d0 = max(today, d1 - timedelta(days=2))
    classes = sorted({c for w, c in CLASS_WORDS.items() if re.search(rf"\b{re.escape(w)}\b", low)})
    if classes:
        prefs["classes"] = classes
    req = PlanRequest(
        origin=origin, destination=dest, date_from=d0, date_to=d1, preferences=Preferences(**prefs), max_results=5
    )
    return Parsed(req, summary=summarise(req))


def summarise(req: PlanRequest) -> str:
    p = req.preferences
    when = f"{req.date_from:%d %b}" if req.date_from == req.date_to else f"{req.date_from:%d %b}–{req.date_to:%d %b}"
    bits = []
    if p.overnight:
        bits.append("overnight preferred")
    if p.arrive_by:
        bits.append(f"arriving by {p.arrive_by}" + (f" on {p.arrive_by_date:%d %b}" if p.arrive_by_date else ""))
    if p.classes:
        bits.append("class " + "/".join(p.classes))
    if p.allow_split:
        bits.append("split journeys allowed")
    bits.append({"fastest": "fastest first", "most_reliable": "most reliable first", "balanced": "balanced"}[p.objective])
    return f"{req.origin} → {req.destination}, {when} ({', '.join(bits)})"
