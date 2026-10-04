from __future__ import annotations

import copy
from datetime import date, datetime

import pytest

from patribot.transform.railkit import (
    IST,
    parse_delay_text,
    parse_distance,
    parse_envelope,
    parse_ir_time,
    parse_payload,
)

# The provider's documented train-history example.
DOC_PAYLOAD = {
    "success": True,
    "data": {
        "trainNo": "12301",
        "trainName": "RAJDHANI EXPRES",
        "journeyDate": "11-06-2026",
        "sourceStationCode": "HWH",
        "destinationStationCode": "NDLS",
        "stations": [
            {
                "stationCode": "HWH",
                "stationName": "HOWRAH JN",
                "platform": "9",
                "arrival": {"scheduled": "SRC", "actual": "SRC"},
                "departure": {"scheduled": "16:50 11-Jun", "actual": "16:50 11-Jun", "delay": "On Time"},
            },
            {
                "stationCode": "ASN",
                "stationName": "ASANSOL JN.",
                "platform": "4",
                "distanceKm": "200",
                "arrival": {"scheduled": "18:47 11-Jun", "actual": "19:03 11-Jun", "delay": "16 Min"},
                "departure": {"scheduled": "18:49 11-Jun", "actual": "19:05 11-Jun", "delay": "16 Min"},
            },
            {
                "stationCode": "NDLS",
                "stationName": "NEW DELHI",
                "platform": "14",
                "distanceKm": "1449",
                "arrival": {"scheduled": "10:05 12-Jun", "actual": "10:13 12-Jun", "delay": "8 Min"},
                "departure": {"scheduled": "DSTN", "actual": "DSTN"},
            },
        ],
        "lastUpdate": "12-06-2026 11:12:53 IST",
    },
}
START = date(2026, 6, 11)


def envelope(payload=DOC_PAYLOAD, status="ok", source="railkit", start="2026-06-11"):
    return {
        "schema_version": 1,
        "source": source,
        "endpoint": "https://api.railkit.in/api/v1/trains/12301/history/11-06-2026",
        "train_no": "12301",
        "start_date": start,
        "status": status,
        "http_status": 200,
        "fetched_at": "2026-06-12T12:00:00+00:00",
        "error": None,
        "payload": payload,
    }


def ist(*args) -> datetime:
    return datetime(*args, tzinfo=IST)


# ---- documented example -----------------------------------------------------------------------------------


def test_documented_example_parses_into_three_stops():
    run = parse_envelope(envelope())
    assert run is not None
    origin, mid, dest = run.stops
    assert [s.seq for s in run.stops] == [1, 2, 3]
    assert [s.station_code for s in run.stops] == ["HWH", "ASN", "NDLS"]

    assert origin.is_origin and not origin.is_destination
    assert origin.sched_arr is None and origin.act_arr is None and origin.arr_delay_min is None
    assert origin.sched_dep == ist(2026, 6, 11, 16, 50)
    assert origin.dep_delay_min == 0
    assert origin.distance_km == 0.0  # origin without distanceKm

    assert mid.sched_arr == ist(2026, 6, 11, 18, 47) and mid.act_arr == ist(2026, 6, 11, 19, 3)
    assert (mid.arr_delay_min, mid.dep_delay_min) == (16, 16)
    assert mid.distance_km == 200.0 and mid.platform == "4" and mid.station_name == "ASANSOL JN."

    assert dest.is_destination and not dest.is_origin
    assert dest.sched_arr == ist(2026, 6, 12, 10, 5)
    assert dest.arr_delay_min == 8
    assert dest.sched_dep is None and dest.act_dep is None and dest.dep_delay_min is None

    h = run.header
    assert (h.train_no, h.start_date, h.journey_date) == ("12301", START, START)
    assert (h.origin_code, h.destination_code, h.train_name) == ("HWH", "NDLS", "RAJDHANI EXPRES")
    assert (h.n_stations_raw, h.n_stations_parsed, h.is_cancelled) == (3, 3, False)
    assert h.last_update == ist(2026, 6, 12, 11, 12, 53)


def test_times_are_timezone_aware_ist():
    run = parse_envelope(envelope())
    ts = run.stops[1].act_arr
    assert ts.tzinfo is not None and ts.utcoffset().total_seconds() == 5.5 * 3600


# ---- time parsing ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "ref", "expected"),
    [
        ("16:50 11-Jun", date(2026, 6, 11), ist(2026, 6, 11, 16, 50)),
        ("05:10 01-Jan", date(2026, 12, 31), ist(2027, 1, 1, 5, 10)),  # Dec → Jan rollover
        ("23:55 31-Dec", date(2026, 12, 31), ist(2026, 12, 31, 23, 55)),
        ("10:00 02-Jan", date(2026, 12, 30), ist(2027, 1, 2, 10, 0)),  # 3-day run across New Year
        ("22:00 31-Dec", date(2027, 1, 1), ist(2026, 12, 31, 22, 0)),  # provider date before start date
        ("16:05 28-Aug*", date(2026, 8, 28), ist(2026, 8, 28, 16, 5)),  # "*" provisional marker
        (" 6:05 1-Jan ", date(2027, 1, 1), ist(2027, 1, 1, 6, 5)),
        ("10:00 29-Feb", date(2028, 2, 28), ist(2028, 2, 29, 10, 0)),  # leap day
        ("16:50 11-Jun-2026", date(2026, 6, 11), ist(2026, 6, 11, 16, 50)),
        ("16:50 11-JUNE", date(2026, 6, 11), ist(2026, 6, 11, 16, 50)),
    ],
)
def test_parse_ir_time(text, ref, expected):
    assert parse_ir_time(text, ref) == expected


@pytest.mark.parametrize(
    "text",
    [
        "SRC",
        "DSTN",
        "",
        "-",
        "--",
        None,
        "*",
        "25:00 01-Jan",
        "10:61 01-Jan",
        "10:00 32-Jan",
        "10:00 01-Foo",
        "soon",
        1234,
    ],
)
def test_parse_ir_time_rejects_markers_and_garbage(text):
    assert parse_ir_time(text, date(2026, 6, 11)) is None


@pytest.mark.parametrize(
    ("text", "minutes"),
    [
        ("On Time", 0),
        ("on time", 0),
        ("16 Min", 16),
        ("21 Mins.", 21),
        ("1 Hr 5 Min", 65),
        ("2 Hrs", 120),
        ("1 Hrs 05 Mins", 65),
        ("01:05", 65),
        ("45", 45),
        ("-5", -5),
        ("5 Min early", -5),
        ("Before 10 Min", -10),
        (12, 12),
        ("", None),
        (None, None),
        ("DSTN", None),
        ("unknown", None),
    ],
)
def test_parse_delay_text(text, minutes):
    assert parse_delay_text(text) == minutes


@pytest.mark.parametrize(
    ("value", "km"),
    [("200", 200.0), ("1,449", 1449.0), (12.5, 12.5), ("", None), (None, None), ("km?", None), (-3, None)],
)
def test_parse_distance(value, km):
    assert parse_distance(value) == km


# ---- tricky payloads -------------------------------------------------------------------------------------


def test_year_rollover_across_a_run():
    payload = copy.deepcopy(DOC_PAYLOAD)
    st = payload["data"]["stations"]
    st[0]["departure"] = {"scheduled": "16:50 31-Dec", "actual": "17:20 31-Dec", "delay": "30 Min"}
    st[1]["arrival"] = {"scheduled": "23:50 31-Dec", "actual": "00:20 01-Jan", "delay": "30 Min"}
    st[1]["departure"] = {"scheduled": "23:52 31-Dec", "actual": "00:22 01-Jan", "delay": "30 Min"}
    st[2]["arrival"] = {"scheduled": "10:05 01-Jan", "actual": "10:00 01-Jan", "delay": "On Time"}
    run = parse_payload(payload, "12301", date(2026, 12, 31))
    assert run.stops[1].act_arr == ist(2027, 1, 1, 0, 20)
    assert run.stops[1].arr_delay_min == 30
    assert run.stops[2].sched_arr == ist(2027, 1, 1, 10, 5)
    assert run.stops[2].arr_delay_min == -5  # early arrival computed from times, not the "On Time" text


def test_computed_delay_wins_over_provider_text():
    payload = copy.deepcopy(DOC_PAYLOAD)
    payload["data"]["stations"][1]["arrival"]["delay"] = "3 Min"  # provider text disagrees with times
    assert parse_payload(payload, "12301", START).stops[1].arr_delay_min == 16


def test_missing_actuals_fall_back_to_delay_text_or_none():
    payload = copy.deepcopy(DOC_PAYLOAD)
    payload["data"]["stations"][1]["arrival"] = {"scheduled": "18:47 11-Jun", "actual": "", "delay": "16 Min"}
    payload["data"]["stations"][1]["departure"] = {"scheduled": "18:49 11-Jun", "actual": "-"}
    payload["data"]["stations"][2]["arrival"] = {"scheduled": "10:05 12-Jun"}
    stops = parse_payload(payload, "12301", START).stops
    assert stops[1].act_arr is None and stops[1].arr_delay_min == 16
    assert stops[1].act_dep is None and stops[1].dep_delay_min is None
    assert stops[2].act_arr is None and stops[2].arr_delay_min is None


def test_star_suffix_on_actual_is_stripped():
    payload = copy.deepcopy(DOC_PAYLOAD)
    payload["data"]["stations"][2]["arrival"]["actual"] = "10:13 12-Jun*"
    stop = parse_payload(payload, "12301", START).stops[2]
    assert stop.act_arr == ist(2026, 6, 12, 10, 13) and stop.arr_delay_min == 8


def test_malformed_rows_are_skipped_not_fatal():
    payload = copy.deepcopy(DOC_PAYLOAD)
    st = payload["data"]["stations"]
    st.insert(1, "garbage")
    st.insert(1, None)
    st.insert(1, {"stationName": "NO CODE", "arrival": {"scheduled": "??"}})
    st.insert(1, {"stationCode": "  ", "arrival": {}})
    st.insert(1, {"stationCode": "XYZ", "arrival": "broken", "departure": ["also broken"]})  # no usable schedule
    st[-1]["distanceKm"] = {"nested": "junk"}
    run = parse_payload(payload, "12301", START)
    assert [s.station_code for s in run.stops] == ["HWH", "ASN", "NDLS"]
    assert [s.seq for s in run.stops] == [1, 2, 3]
    assert run.stops[-1].distance_km is None
    assert run.header.n_stations_raw == 8 and run.header.n_stations_parsed == 3


def test_station_named_src_is_not_confused_with_the_marker():
    payload = copy.deepcopy(DOC_PAYLOAD)
    payload["data"]["stations"][0]["stationCode"] = "SRC"  # Santragachi, in the Kolkata cluster
    run = parse_payload(payload, "12301", START)
    assert run.stops[0].station_code == "SRC" and run.stops[0].is_origin


def test_cancelled_flag_and_timeline_shape():
    payload = {
        "success": True,
        "data": {
            "trainNo": "12345",
            "date": "28-Aug-2026",
            "statusNote": "Train is Cancelled",
            "timeline": [
                {
                    "type": "stoppage",
                    "stationCode": "HWH",
                    "arrival": {"scheduled": "SRC", "actual": "SRC", "delay": ""},
                    "departure": {"scheduled": "16:05 28-Aug", "actual": "16:05 28-Aug*", "delay": "On Time"},
                },
                {"type": "intermediate", "stationCode": "LLH", "arrival": {"scheduled": "16:20 28-Aug"}},
                {
                    "type": "stoppage",
                    "stationCode": "BWN",
                    "arrival": {"scheduled": "17:30 28-Aug", "actual": "", "delay": ""},
                    "departure": {"scheduled": "DSTN", "actual": "DSTN"},
                },
            ],
        },
    }
    run = parse_payload(payload, "12345", date(2026, 8, 28))
    assert run.header.is_cancelled
    assert run.header.journey_date == date(2026, 8, 28)
    assert [s.station_code for s in run.stops] == ["HWH", "BWN"]
    assert run.stops[0].act_dep == ist(2026, 8, 28, 16, 5)


@pytest.mark.parametrize(
    "payload",
    [None, "Not found", [], {"success": False}, {"success": True, "data": None}, {"success": True, "data": "x"}],
)
def test_unusable_payloads_yield_none(payload):
    assert parse_payload(payload, "12301", START) is None


def test_empty_station_list_is_a_run_without_stops():
    run = parse_payload({"success": True, "data": {"stations": []}}, "12301", START)
    assert run is not None and run.stops == []


@pytest.mark.parametrize(
    "env",
    [
        envelope(status="not_found"),
        envelope(status="error"),
        envelope(source="fixture"),
        envelope(start="not-a-date"),
        {**envelope(), "train_no": None},
        "not a dict",
    ],
)
def test_non_ok_or_broken_envelopes_yield_none(env):
    assert parse_envelope(env) is None
