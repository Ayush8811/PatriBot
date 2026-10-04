"""Place resolution (BRD FR-2): city names and colloquial aliases → station clusters, station codes and names →
single stations."""

from __future__ import annotations

import re
from dataclasses import dataclass

from patribot.planner.model import PlannerData
from patribot.planner.schemas import PlaceResult

# Colloquial and historical names per cluster id (config/corridors.yaml `clusters`). Lower case.
CLUSTER_ALIASES: dict[str, tuple[str, ...]] = {
    "KOLKATA": ("kolkata", "calcutta", "kolkatta"),
    "DELHI": ("delhi", "dilli"),  # "New Delhi" is the station NDLS
    "PATNA": ("patna",),
    "MUMBAI": ("mumbai", "bombay"),
    "BENGALURU": ("bengaluru", "bangalore", "bengalooru"),
    "HYDERABAD": ("hyderabad", "secunderabad"),
    "CHENNAI": ("chennai", "madras"),
}
_SUFFIX = re.compile(r"\s+(jn|jn\.|junction|cantt|terminal|terminus)$")


class UnknownPlace(LookupError):
    def __init__(self, text: str):
        super().__init__(f"unknown place: {text}")
        self.text = text


@dataclass(frozen=True)
class ResolvedPlace:
    kind: str  # "cluster" | "station"
    id: str
    name: str
    stations: tuple[str, ...]


def cluster_name(cluster_id: str) -> str:
    return cluster_id.title()


def aliases(cluster_id: str) -> tuple[str, ...]:
    return CLUSTER_ALIASES.get(cluster_id, (cluster_id.lower(),))


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def station_key(name: str | None) -> str:
    """'Howrah Jn' → 'howrah' (for matching station names typed by people)."""
    return _SUFFIX.sub("", _norm(name or ""))


def resolve(data: PlannerData, text: str) -> ResolvedPlace:
    """A cluster id, alias, station code or exact station name → stations. Raises UnknownPlace."""
    t = _norm(text)
    up = text.strip().upper()
    if up in data.clusters:
        return ResolvedPlace("cluster", up, f"{cluster_name(up)} (all stations)", data.clusters[up])
    if up in data.stations:
        return ResolvedPlace("station", up, data.station_name(up), (up,))
    for cid, names in CLUSTER_ALIASES.items():
        if t in names and cid in data.clusters:
            return ResolvedPlace("cluster", cid, f"{cluster_name(cid)} (all stations)", data.clusters[cid])
    matches = [s for s in data.stations.values() if s.name and (_norm(s.name) == t or station_key(s.name) == t)]
    if len(matches) == 1:
        return ResolvedPlace("station", matches[0].code, data.station_name(matches[0].code), (matches[0].code,))
    raise UnknownPlace(text.strip())


def search(data: PlannerData, query: str, limit: int = 10) -> list[PlaceResult]:
    """Clusters first, then stations, best match first: exact code / alias, prefix, word prefix, substring."""
    q = _norm(query)
    if not q:
        return []
    scored: list[tuple[int, int, str, PlaceResult]] = []
    for cid, codes in data.clusters.items():
        names = (cid.lower(), *aliases(cid))
        if q in names:
            score = 0
        elif any(n.startswith(q) for n in names):
            score = 1
        elif any(q in n for n in names):
            score = 4
        else:
            continue
        res = PlaceResult(kind="cluster", id=cid, name=f"{cluster_name(cid)} (all stations)", stations=list(codes))
        scored.append((score, 0, cid, res))
    for code, st in data.stations.items():
        name = _norm(st.name or "")
        if q == code.lower():
            score = 0
        elif code.lower().startswith(q) or name.startswith(q):
            score = 2
        elif any(w.startswith(q) for w in name.split()):
            score = 3
        elif q in name:
            score = 5
        else:
            continue
        res = PlaceResult(kind="station", id=code, name=st.name or code, cluster=st.cluster)
        scored.append((score, 1, st.name or code, res))
    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    return [r for *_, r in scored[:limit]]
