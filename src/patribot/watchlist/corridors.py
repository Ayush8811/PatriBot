"""Typed view of config/corridors.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class MembershipRule(BaseModel):
    min_km: float = Field(150, gt=0)
    min_consecutive_segments: int = Field(2, ge=1)
    exclude_train_types: list[str] = ["MEMU", "DEMU", "EMU", "PASSENGER", "UNRESERVED"]


class Corridor(BaseModel):
    id: str
    name: str = ""
    a: str  # cluster id
    b: str
    primary: bool = False
    verified: bool = False
    paths: dict[str, list[str]]  # path name -> waypoint station codes, A -> B
    split_hubs: list[str] = []


class CorridorConfig(BaseModel):
    membership: MembershipRule = MembershipRule()
    clusters: dict[str, list[str]]
    corridors: list[Corridor]

    @model_validator(mode="after")
    def _check(self) -> CorridorConfig:
        for c in self.corridors:
            for cluster in (c.a, c.b):
                if cluster not in self.clusters:
                    raise ValueError(f"corridor {c.id}: unknown cluster {cluster!r}")
            for name, path in c.paths.items():
                if len(path) < 2 or len(set(path)) != len(path):
                    raise ValueError(f"corridor {c.id} path {name}: needs >= 2 distinct stations")
        return self

    def all_stations(self) -> list[str]:
        """Every waypoint and cluster station, de-duplicated, in a stable order (paths first)."""
        seen: dict[str, None] = {}
        for c in self.corridors:
            for path in c.paths.values():
                seen.update(dict.fromkeys(path))
        for c in self.corridors:
            for cluster in (c.a, c.b):
                seen.update(dict.fromkeys(self.clusters[cluster]))
        return list(seen)


def load_corridors(path: str | Path) -> CorridorConfig:
    with open(path, encoding="utf-8") as fh:
        return CorridorConfig.model_validate(yaml.safe_load(fh))
