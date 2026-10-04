from __future__ import annotations

from pathlib import Path

import pytest

from patribot.sources.base import RouteStop
from patribot.watchlist.corridors import CorridorConfig, MembershipRule, load_corridors
from patribot.watchlist.membership import (
    exclusion_reason,
    is_premium,
    match_path,
    memberships,
    path_slots,
    serves_both_ends,
    serves_end_or_hub,
)

CFG = CorridorConfig.model_validate(
    {
        "membership": {"min_km": 150, "min_consecutive_segments": 2},
        "clusters": {"KOL": ["HWH", "SDAH"], "DEL": ["NDLS", "NZM"], "PAT": ["PNBE", "RJPB"]},
        "corridors": [
            {"id": "KOL-DEL", "a": "KOL", "b": "DEL", "paths": {"main": ["HWH", "BWN", "ASN", "DHN", "GAYA", "NDLS"]}},
            {"id": "DEL-PAT", "a": "DEL", "b": "PAT", "paths": {"main": ["NDLS", "CNB", "DDU", "PNBE"]}},
        ],
    }
)
SLOTS = path_slots(CFG)
RULE = CFG.membership
KM = {"HWH": 0, "SDAH": 0, "BWN": 95, "ASN": 200, "DHN": 259, "GMO": 300, "GAYA": 458, "DDU": 661, "CNB": 1010}
KM |= {"NDLS": 1451, "NZM": 1458, "PNBE": 540, "RJPB": 545, "XYZ": 700}


def route(*codes: str, passes: tuple[str, ...] = (), km: dict[str, float] | None = None) -> list[RouteStop]:
    dist = KM if km is None else km
    return [RouteStop(c, distance_km=dist.get(c), halts=c not in passes) for c in codes]


def corridors_of(stops) -> set[str]:
    return {m.corridor for m in memberships(stops, SLOTS, RULE)}


def test_end_to_end_train_is_member():
    m = memberships(route("HWH", "ASN", "DHN", "GAYA", "NDLS"), SLOTS, RULE)
    kd = next(x for x in m if x.corridor == "KOL-DEL")
    assert (kd.from_code, kd.to_code, kd.segments, kd.direction) == ("HWH", "NDLS", 5, "AB")
    assert serves_both_ends(route("HWH", "ASN", "NDLS"), CFG, "KOL-DEL")


def test_intermediate_origin_train_is_member():
    # Dhanbad -> New Delhi: starts on the path, not at an end cluster
    assert corridors_of(route("DHN", "GAYA", "NDLS")) == {"KOL-DEL"}
    assert not serves_both_ends(route("DHN", "GAYA", "NDLS"), CFG, "KOL-DEL")


def test_train_starting_outside_and_passing_through_is_member():
    # e.g. a train from beyond the path that joins at ASN and leaves after GAYA
    assert corridors_of(route("XYZ", "ASN", "DHN", "GAYA", "XYZ2")) == {"KOL-DEL"}


def test_reverse_direction_is_member():
    m = match_path(route("NDLS", "GAYA", "ASN"), SLOTS[0], RULE)
    assert m and m.direction == "BA" and m.from_code == "NDLS" and m.to_code == "ASN"


def test_cluster_station_off_path_maps_to_end_slot():
    assert corridors_of(route("SDAH", "ASN", "DHN")) == {"KOL-DEL"}  # SDAH is not a waypoint but is in KOLKATA
    assert corridors_of(route("RJPB", "DDU", "NZM")) == {"DEL-PAT"}  # both ends via cluster stations


def test_single_halt_on_path_is_not_member():
    # passes DHN and GAYA without stopping; only ASN is a halt on the path
    assert corridors_of(route("XYZ", "ASN", "DHN", "GAYA", "XYZ2", passes=("DHN", "GAYA"))) == set()


def test_short_one_segment_hop_is_not_member():
    assert corridors_of(route("HWH", "BWN")) == set()  # 95 km, 1 segment
    assert corridors_of(route("SDAH", "HWH")) == set()  # same end slot


def test_under_150_km_but_two_segments_is_member():
    km = {"BWN": 95, "ASN": 200, "DHN": 240}  # BWN -> DHN = 145 km over 2 segments
    m = match_path(route("BWN", "ASN", "DHN", km=km), SLOTS[0], RULE)
    assert m and m.segments == 2 and m.km == 145


def test_one_segment_over_150_km_is_member():
    m = match_path(route("GAYA", "NDLS"), SLOTS[0], RULE)  # one segment, 993 km
    assert m and m.segments == 1 and m.km == 993


def test_one_segment_without_distance_is_not_member():
    assert match_path(route("GAYA", "NDLS", km={}), SLOTS[0], RULE) is None


def test_multi_corridor_train():
    # Howrah -> Patna -> ... -> New Delhi style: covers both corridors
    stops = route("HWH", "ASN", "DHN", "GAYA", "NDLS")
    assert corridors_of(stops) == {"KOL-DEL"}
    stops = route("PNBE", "DDU", "CNB", "NDLS", "GAYA", "DHN")
    assert corridors_of(stops) == {"KOL-DEL", "DEL-PAT"}


@pytest.mark.parametrize(
    ("no", "name", "ttype", "classes", "reason"),
    [
        ("12301", "HWH RAJDHANI", "RAJDHANI", "1A,2A,3A", None),
        ("12381", "POORVA EXPRESS", "Mail Express", "", None),
        ("22406", "GARIB RATH", "SUPERFAST", "3A", None),
        ("63501", "ASN MEMU", "", "", "MEMU (6xxxx)"),
        ("73001", "DMU", "", "", "DEMU / railcar (7xxxx)"),
        ("53001", "GAYA PASS", "", "", "passenger (5xxxx)"),
        ("37001", "HWH LOCAL", "", "", "suburban (3xxxx, Kolkata area)"),
        ("13001", "SOME TRAIN", "MEMU", "", "type MEMU"),
        ("13002", "SOME TRAIN", "Passenger", "", "type PASSENGER"),
        ("13003", "SOME TRAIN", "EMU", "", "type EMU"),
        ("22833", "HWH ANTYODAYA EXP", "Superfast", "GEN", "name ANTYODAYA"),
        ("13004", "SOME TRAIN", "Mail Express", "GEN", "unreserved classes only"),
        ("13005", "SOME TRAIN", "Mail Express", "GEN, UR", "unreserved classes only"),
        ("03001", "HWH NDLS SPL", "", "", "special (0xxxx)"),
    ],
)
def test_exclusion(no, name, ttype, classes, reason):
    assert exclusion_reason(no, name, ttype, classes, RULE.exclude_train_types) == reason


def test_specials_can_be_included():
    assert exclusion_reason("03001", "HWH NDLS SPL", "", "", RULE.exclude_train_types, include_specials=True) is None


@pytest.mark.parametrize(
    ("name", "ttype", "premium"),
    [
        ("HWH RAJDHANI", "", True),
        ("NDLS SWARN SHTBDI", "", True),
        ("SDAH DURONTO", "", True),
        ("VANDE BHARAT EXP", "", True),
        ("SOME TRAIN", "Vande Bharat", True),
        ("TEJAS RAJDHANI", "", True),
        ("HUMSAFAR EXP", "", True),
        ("POORVA EXPRESS", "SUPERFAST", False),
    ],
)
def test_premium(name, ttype, premium):
    assert is_premium(name, ttype) is premium


def test_real_corridor_config_loads_and_maps_clusters():
    cfg = load_corridors(Path(__file__).resolve().parents[1] / "config" / "corridors.yaml")
    slots = {(p.corridor, p.path): p for p in path_slots(cfg)}
    gc = slots[("KOL-DEL", "grand_chord")]
    assert gc.slots["HWH"] == gc.slots["SDAH"] == 0 and gc.slots["DLI"] == gc.slots["NDLS"] == len(gc.stations) - 1
    western = slots[("MUM-DEL", "western")]
    assert western.slots["NZM"] == western.stations.index("NZM")  # an explicit waypoint keeps its own position
    assert western.slots["BDTS"] == 0
    assert isinstance(cfg.membership, MembershipRule) and cfg.membership.min_km == 150
    assert {"HWH", "SDAH", "NDLS", "DLI", "BZA"} <= set(cfg.all_stations())


def test_serves_end_or_hub_separates_tier_b_from_c():
    cfg = CorridorConfig.model_validate(
        CFG.model_dump() | {"corridors": [c.model_dump() | {"split_hubs": ["GAYA"]} for c in CFG.corridors]}
    )
    assert serves_end_or_hub(route("DHN", "GAYA", "NDLS"), cfg, "KOL-DEL")  # end cluster (NDLS)
    assert serves_end_or_hub(route("ASN", "DHN", "GAYA"), cfg, "KOL-DEL")  # split hub (GAYA)
    assert not serves_end_or_hub(route("BWN", "ASN", "DHN"), cfg, "KOL-DEL")  # neither -> tier C
    assert not serves_end_or_hub(route("BWN", "ASN", "GAYA", passes=("GAYA",)), cfg, "KOL-DEL")  # passes the hub
