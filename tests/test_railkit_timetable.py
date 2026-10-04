from __future__ import annotations

import httpx
import pytest

from patribot.collector.config import WEEKDAYS
from patribot.sources.base import CallBudgetExhausted, SourceStopped
from patribot.sources.railkit_timetable import (
    RailKitTimetableSource,
    parse_duration_minutes,
    parse_hhmm,
    parse_running_days,
    parse_schedule,
)

KEY = "rk_secret"

# Verbatim example responses from the provider docs (endpointDocs.ts).
DOC_TRAIN_INFO = {
    "success": True,
    "data": {
        "trainInfo": {
            "train_no": "12345",
            "train_name": "SARAIGHAT EXP",
            "from_stn_name": "Howrah Jn",
            "from_stn_code": "HWH",
            "to_stn_name": "Guwahati",
            "to_stn_code": "GHY",
            "from_time": "16:05",
            "to_time": "09:40",
            "travel_time": "17:35 hrs",
            "running_days": "1111111",
            "type": "SUPERFAST",
            "train_id": "1891",
        },
        "route": [
            {
                "stnCode": "HWH",
                "stnName": "Howrah Jn",
                "arrival": "--",
                "departure": "16:05",
                "halt": "0 min",
                "haltMinutes": 0,
                "distance": "0",
                "day": "1",
                "platform": 15,
                "coordinates": {"latitude": 22.5835032884945, "longitude": 88.3422660827637},
            }
        ],
    },
}
DOC_BETWEEN = {
    "success": True,
    "data": [
        {
            "train_no": "12904",
            "train_name": "GOLDEN TEMPLE M",
            "source_stn_name": "Amritsar Jn",
            "source_stn_code": "ASR",
            "dstn_stn_name": "Bandra Terminus",
            "dstn_stn_code": "BDTS",
            "from_stn_name": "Hazrat Nizamuddin",
            "from_stn_code": "NZM",
            "to_stn_name": "Bandra Terminus",
            "to_stn_code": "BDTS",
            "from_time": "04:00",
            "to_time": "23:55",
            "travel_time": "19:55 hrs",
            "running_days": "1111111",
            "distance": "1365",
            "halts": 20,
        }
    ],
}
DOC_STATION = {
    "success": True,
    "data": {
        "summary": "168 Trains scheduled at ASN - ASANSOL JN. on 28-Aug-2026",
        "station": "ASN",
        "date": "28-Aug-2026",
        "totalTrains": 168,
        "trains": [
            {
                "trainNo": "15052",
                "trainName": "GKP KOAA EXP",
                "source": "GKP",
                "sourceName": "Gorakhpur Jn",
                "destination": "KOAA",
                "destinationName": "Kolkatta Terminal",
                "trainType": "Mail Express",
                "classes": "1A,2A,3A,SL,GEN,PWD",
                "runningDays": "",
                "arrival": "00:01",
                "departure": "00:11",
            }
        ],
    },
}


def make(handler, **kw) -> RailKitTimetableSource:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return RailKitTimetableSource(KEY, client=client, sleep=lambda s: None, **kw)


def routed(seen: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path.endswith("/timetable"):
            return httpx.Response(200, json=DOC_STATION)
        if "/between/" in path:
            return httpx.Response(200, json=DOC_BETWEEN)
        return httpx.Response(200, json=DOC_TRAIN_INFO)

    return handler


def test_request_shapes_and_documented_responses():
    seen: list[httpx.Request] = []
    src = make(routed(seen))

    at = src.list_trains_at("ASN")
    between = src.list_trains_between("NZM", "BDTS")
    sched = src.get_schedule("12345")

    assert [str(r.url) for r in seen] == [
        "https://api.railkit.in/api/v1/stations/ASN/timetable",  # no date: all trains with their running days
        "https://api.railkit.in/api/v1/trains/between/NZM/BDTS",
        "https://api.railkit.in/api/v1/trains/12345/info",
    ]
    assert all(r.headers["x-api-key"] == KEY for r in seen)
    assert src.calls == 3 and src.calls_by_kind == {"station": 1, "between": 1, "schedule": 1}

    assert at and at[0].train_no == "15052" and at[0].origin == "GKP" and at[0].destination == "KOAA"
    assert at[0].train_type == "Mail Express" and "SL" in at[0].classes and at[0].running_days is None
    assert between and between[0].train_no == "12904" and between[0].origin == "ASR"
    assert between[0].running_days == WEEKDAYS
    assert sched and sched.name == "SARAIGHAT EXP" and sched.train_type == "SUPERFAST"
    assert sched.dep_time == "16:05" and sched.journey_minutes == 17 * 60 + 35
    assert sched.origin == "HWH" and sched.destination == "GHY"
    stop = sched.stops[0]
    assert stop.code == "HWH" and stop.arrival is None and stop.departure == "16:05" and stop.distance_km == 0
    assert stop.halts and stop.day == 1


@pytest.mark.parametrize(
    ("value", "order", "expected"),
    [
        ("1111111", "MON", WEEKDAYS),
        ("1000001", "MON", ("MON", "SUN")),
        ("1000001", "SUN", ("SAT", "SUN")),  # Sunday-first string: index 0 = SUN, index 6 = SAT
        ("YNNNNNN", "MON", ("MON",)),
        ("Daily", "MON", WEEKDAYS),
        ("Mon, Wed, Fri", "MON", ("MON", "WED", "FRI")),
        (["Tue", "Sat"], "MON", ("TUE", "SAT")),
        ([1, 0, 0, 0, 0, 0, 1], "MON", ("MON", "SUN")),
        ({"mon": True, "tue": False, "sun": 1}, "MON", ("MON", "SUN")),
        ("", "MON", None),
        ("0000000", "MON", None),
        (None, "MON", None),
    ],
)
def test_parse_running_days(value, order, expected):
    assert parse_running_days(value, order) == expected


def test_parse_times_and_durations():
    assert parse_hhmm("6:05") == "06:05" and parse_hhmm("10:05 05-Oct") == "10:05"
    assert parse_hhmm("--") is None and parse_hhmm("DSTN") is None
    assert parse_duration_minutes("17:35 hrs") == 1055 and parse_duration_minutes("17h 35m") == 1055
    assert parse_duration_minutes(900) == 900 and parse_duration_minutes("") is None


def test_schedule_tolerates_alternative_shapes():
    data = {
        "trainNo": 12301,  # number, not string
        "trainName": "HWH RAJDHANI",
        "stations": [
            {"stationCode": "hwh", "departureTime": "16:50", "distance": 0, "dayCount": 1},
            {"stationCode": "DHN", "arrivalTime": "20:00", "departureTime": "20:05", "haltMinutes": 5, "distance": 259},
            {"stationCode": "GMO", "arrivalTime": "20:40", "departureTime": "20:40", "haltMinutes": 0, "distance": 300},
            {"stationCode": "NDLS", "arrivalTime": "10:05", "distance": "1451 km", "dayCount": 2},
        ],
    }
    s = parse_schedule(data, "12301")
    assert s and s.train_no == "12301" and s.dep_time == "16:50" and s.origin == "HWH" and s.destination == "NDLS"
    assert s.journey_minutes == 1035  # derived from the route: 16:50 day 1 -> 10:05 day 2
    assert [x.halts for x in s.stops] == [True, True, False, True]  # zero-halt intermediate row = pass-through
    assert s.stops[-1].distance_km == 1451


def test_quota_and_bad_key_stop_discovery():
    src = make(lambda r: httpx.Response(429, json={"success": False, "error": "Usage limit exceeded"}))
    with pytest.raises(SourceStopped, match="429"):
        src.list_trains_at("ASN")
    src = make(lambda r: httpx.Response(401, json={"success": False, "error": "Invalid API key"}))
    with pytest.raises(SourceStopped) as exc:
        src.get_schedule("12301")
    assert KEY not in str(exc.value)


def test_not_found_and_errors_return_none():
    src = make(lambda r: httpx.Response(404, json={"success": False, "error": "Train not found"}))
    assert src.get_schedule("99999") is None and src.errors == []
    src = make(lambda r: httpx.Response(500, text="upstream down"))
    assert src.list_trains_at("ASN") is None and "HTTP 500" in src.errors[0]
    src = make(lambda r: httpx.Response(200, json={"success": False, "error": "Request timed out"}))
    assert src.list_trains_between("A", "B") is None

    def boom(request):
        raise httpx.ConnectError(f"failed {request.url}")

    src = make(boom)
    assert src.get_schedule("12301") is None and KEY not in src.errors[0]


def test_max_calls_guard_sends_nothing_more():
    seen: list[httpx.Request] = []
    src = make(routed(seen), max_calls=2)
    src.list_trains_at("ASN")
    src.list_trains_at("DHN")
    with pytest.raises(CallBudgetExhausted):
        src.list_trains_at("GAYA")
    assert len(seen) == 2 and src.calls == 2


def test_disk_cache_hits_are_free_and_expire(tmp_path):
    seen: list[httpx.Request] = []
    now = {"t": 1_000_000.0}
    kw = {"cache_dir": tmp_path, "wall_clock": lambda: now["t"]}
    first = make(routed(seen), **kw)
    first.get_schedule("12345")
    first.list_trains_at("ASN")
    assert len(seen) == 2

    second = make(routed(seen), max_calls=0, **kw)  # a fresh run: served from disk, so the guard is not hit
    assert second.get_schedule("12345").name == "SARAIGHAT EXP"
    assert second.list_trains_at("ASN")[0].train_no == "15052"
    assert second.calls == 0 and second.cache_hits == 2 and len(seen) == 2

    now["t"] += 7 * 86400  # station lists expire after 6 days, schedules after ~3-4 weeks
    third = make(routed(seen), **kw)
    third.get_schedule("12345")
    third.list_trains_at("ASN")
    assert third.cache_hits == 1 and third.calls_by_kind == {"station": 1}


def test_failed_responses_are_not_cached(tmp_path):
    src = make(lambda r: httpx.Response(500, text="down"), cache_dir=tmp_path)
    src.get_schedule("12345")
    assert list(tmp_path.iterdir()) == []
