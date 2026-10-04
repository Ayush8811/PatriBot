from __future__ import annotations

import os

from patribot.sources.base import RunningStatusSource
from patribot.sources.fixture import FixtureSource
from patribot.sources.indianrailapi import IndianRailApiSource

SOURCES = ("fixture", "indianrailapi")


def get_source(name: str) -> RunningStatusSource:
    if name == "fixture":
        return FixtureSource()
    if name == "indianrailapi":
        base = os.environ.get("RAIL_API_BASE_URL")
        key = os.environ.get("RAIL_API_KEY", "")
        return IndianRailApiSource(key, base) if base else IndianRailApiSource(key)
    raise ValueError(f"unknown source {name!r}; expected one of {SOURCES}")
