from __future__ import annotations

import os

from patribot.sources.base import RunningStatusSource
from patribot.sources.fixture import FixtureSource
from patribot.sources.indianrailapi import IndianRailApiSource
from patribot.sources.railkit import DEFAULT_MIN_INTERVAL_S, RailKitSource

SOURCES = ("fixture", "railkit", "indianrailapi")


def get_source(name: str) -> RunningStatusSource:
    key = os.environ.get("RAIL_API_KEY", "")
    base = os.environ.get("RAIL_API_BASE_URL")
    if name == "fixture":
        return FixtureSource()
    if name == "railkit":
        interval = float(os.environ.get("RAIL_MIN_INTERVAL_S", DEFAULT_MIN_INTERVAL_S))
        return (
            RailKitSource(key, base, min_interval_s=interval) if base else RailKitSource(key, min_interval_s=interval)
        )
    if name == "indianrailapi":
        return IndianRailApiSource(key, base) if base else IndianRailApiSource(key)
    raise ValueError(f"unknown source {name!r}; expected one of {SOURCES}")
