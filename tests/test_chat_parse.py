"""Rule-based message parsing of the Phase 2 `/chat` stub (BRD Q1–Q3 phrasings)."""

from __future__ import annotations

from datetime import date

from patribot.api.chat import parse_dates, parse_message
from patribot.planner.model import DelayStats, PlannerData, Station

TODAY = date(2026, 10, 5)
DATA = PlannerData(
    stations={
        "HWH": Station("HWH", "Howrah Jn", "KOLKATA"),
        "NDLS": Station("NDLS", "New Delhi", "DELHI"),
        "PNBE": Station("PNBE", "Patna Jn", "PATNA"),
    },
    clusters={"KOLKATA": ("HWH",), "DELHI": ("NDLS",), "PATNA": ("PNBE",), "MUMBAI": ()},
    trains={},
    corridors={},
    delays=DelayStats(),
)


def test_q1_phrasing():
    p = parse_message("Suitable train from Kolkata to Delhi, Nov 20-30, overnight preferred, least travel time", DATA,
                      TODAY)  # fmt: skip
    r = p.request
    assert (r.origin, r.destination) == ("KOLKATA", "DELHI")
    assert (r.date_from, r.date_to) == (date(2026, 11, 20), date(2026, 11, 30))
    assert r.preferences.overnight and r.preferences.objective == "fastest" and not r.preferences.hard


def test_q2_phrasing_is_a_hard_p90_deadline_on_the_arrival_day():
    p = parse_message("I must reach New Delhi by 9 AM on Nov 25. What should I take from Howrah?", DATA, TODAY)
    r = p.request
    assert (r.origin, r.destination) == ("HWH", "NDLS")
    assert r.preferences.arrive_by == "09:00" and r.preferences.hard == ["arrive_by"]
    assert r.preferences.arrive_by_date == date(2026, 11, 25)
    assert r.date_to == date(2026, 11, 25) and r.date_from == date(2026, 11, 23)


def test_q3_phrasing_allows_splits():
    p = parse_message("All direct trains are full on Nov 22 from Kolkata to Delhi. Plan a break journey.", DATA, TODAY)
    assert p.request.preferences.allow_split and p.request.date_from == date(2026, 11, 22)


def test_missing_parts_ask_a_question():
    p = parse_message("train to Delhi", DATA, TODAY)
    assert p.request is None and "starting from" in p.question and "date" in p.question


def test_dates_roll_into_next_year_and_aliases_resolve():
    assert parse_dates("5 Jan", TODAY) == (date(2027, 1, 5), date(2027, 1, 5))
    assert parse_dates("2026-12-01 to 2026-12-03", TODAY) == (date(2026, 12, 1), date(2026, 12, 3))
    assert parse_dates("tomorrow", TODAY) == (date(2026, 10, 6), date(2026, 10, 6))
    p = parse_message("Calcutta to Patna on 3rd December in 3AC", DATA, TODAY)
    assert (p.request.origin, p.request.destination) == ("KOLKATA", "PATNA")
    assert p.request.preferences.classes == ["3A"]
