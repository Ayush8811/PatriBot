from __future__ import annotations

from datetime import time
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

Weekday = Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
WEEKDAYS: tuple[Weekday, ...] = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


class CollectorSettings(BaseModel):
    timezone: str = "Asia/Kolkata"
    max_calls_per_month: int = Field(15000, gt=0)
    lookback_days: int = Field(3, ge=0, le=30)
    grace_hours: float = Field(6, ge=0)
    max_attempts: int = Field(3, ge=1)
    max_tier_b_stride: int = Field(4, ge=1)  # tier-B sampling never drops below 1 / max_tier_b_stride


class WatchedTrain(BaseModel):
    train_no: str = Field(pattern=r"^\d{5}$")
    name: str = ""
    corridors: list[str] = []
    tier: Literal["A", "B"] = "B"
    dep_time: time  # departure from origin, local (IST)
    journey_minutes: int = Field(gt=0)
    run_days: list[Weekday] = list(WEEKDAYS)

    @field_validator("run_days")
    @classmethod
    def _non_empty(cls, v: list[Weekday]) -> list[Weekday]:
        if not v:
            raise ValueError("run_days must not be empty")
        return v


class Watchlist(BaseModel):
    collector: CollectorSettings = CollectorSettings()
    trains: list[WatchedTrain]

    @field_validator("trains")
    @classmethod
    def _unique(cls, v: list[WatchedTrain]) -> list[WatchedTrain]:
        seen = [t.train_no for t in v]
        dupes = {n for n in seen if seen.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate train numbers in watchlist: {sorted(dupes)}")
        return v


def load_watchlist(path: str | Path) -> Watchlist:
    with open(path, encoding="utf-8") as fh:
        return Watchlist.model_validate(yaml.safe_load(fh))
