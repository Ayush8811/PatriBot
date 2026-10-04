"""A fake RailKit API that serves the documented response shapes (RAJIV81205/RailKit endpointDocs.ts)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx
import pytest

KEY = "rk_secret"


def info_payload(no, name, ttype, route, running_days="1111111", travel_time=None):
    """`GET /api/v1/trains/{no}/info` body. route: (code, arrival, departure, halt_min, km, day) tuples."""
    rows = [
        {
            "stnCode": code,
            "stnName": code.title(),
            "arrival": arr or "--",
            "departure": dep or "--",
            "halt": f"{halt} min",
            "haltMinutes": halt,
            "distance": str(km),
            "day": str(day),
            "platform": 1,
            "coordinates": {"latitude": 22.5, "longitude": 88.3},
        }
        for code, arr, dep, halt, km, day in route
    ]
    first, last = route[0], route[-1]
    return {
        "success": True,
        "data": {
            "trainInfo": {
                "train_no": no,
                "train_name": name,
                "from_stn_name": first[0].title(),
                "from_stn_code": first[0],
                "to_stn_name": last[0].title(),
                "to_stn_code": last[0],
                "from_time": first[2],
                "to_time": last[1],
                "travel_time": travel_time or "",
                "running_days": running_days,
                "type": ttype,
                "train_id": "1891",
            },
            "route": rows,
        },
    }


@dataclass
class FakeRailKit:
    trains: dict[str, dict] = field(default_factory=dict)  # train_no -> info payload
    classes: dict[str, str] = field(default_factory=dict)  # train_no -> station-timetable "classes"
    fail_stations: set[str] = field(default_factory=set)  # station timetable returns HTTP 500
    status_override: int | None = None
    requests: list[httpx.Request] = field(default_factory=list)

    def add(self, no, name, ttype, route, classes="1A,2A,3A,SL,GEN", **kw) -> None:
        self.trains[no] = info_payload(no, name, ttype, route, **kw)
        self.classes[no] = classes

    def _halts(self, no):
        route = self.trains[no]["data"]["route"]
        return [r for i, r in enumerate(route) if r["haltMinutes"] > 0 or i in (0, len(route) - 1)]

    def _station_row(self, no, stop):
        info = self.trains[no]["data"]["trainInfo"]
        return {
            "trainNo": no,
            "trainName": info["train_name"],
            "source": info["from_stn_code"],
            "sourceName": info["from_stn_name"],
            "destination": info["to_stn_code"],
            "destinationName": info["to_stn_name"],
            "trainType": "Mail Express",
            "classes": self.classes[no],
            "runningDays": "",
            "arrival": stop["arrival"],
            "departure": stop["departure"],
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status_override:
            return httpx.Response(self.status_override, json={"success": False, "error": "Usage limit exceeded"})
        path = request.url.path
        if m := re.fullmatch(r"/api/v1/stations/(\w+)/timetable", path):
            code = m.group(1)
            if code in self.fail_stations:
                return httpx.Response(500, json={"success": False, "error": "Request timed out"})
            rows = [self._station_row(no, s) for no in self.trains for s in self._halts(no) if s["stnCode"] == code]
            data = {"summary": f"{len(rows)} Trains", "station": code, "date": "", "totalTrains": len(rows)}
            return httpx.Response(200, json={"success": True, "data": data | {"trains": rows}})
        if m := re.fullmatch(r"/api/v1/trains/between/(\w+)/(\w+)", path):
            src, dst = m.groups()
            out = []
            for no, payload in self.trains.items():
                codes = [s["stnCode"] for s in self._halts(no)]
                if src in codes and dst in codes and codes.index(src) < codes.index(dst):
                    info = payload["data"]["trainInfo"]
                    out.append(
                        {
                            "train_no": no,
                            "train_name": info["train_name"],
                            "source_stn_code": info["from_stn_code"],
                            "dstn_stn_code": info["to_stn_code"],
                            "from_stn_code": src,
                            "to_stn_code": dst,
                            "running_days": info["running_days"],
                            "distance": "100",
                            "halts": 3,
                        }
                    )
            return httpx.Response(200, json={"success": True, "data": out})
        if m := re.fullmatch(r"/api/v1/trains/(\d+)/info", path):
            if m.group(1) in self.trains:
                return httpx.Response(200, json=self.trains[m.group(1)])
            return httpx.Response(404, json={"success": False, "error": "Train not found"})
        return httpx.Response(404, json={"success": False, "error": "unknown endpoint"})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    def count(self, pattern: str) -> int:
        return sum(bool(re.search(pattern, r.url.path)) for r in self.requests)


@pytest.fixture
def fake_railkit() -> FakeRailKit:
    return FakeRailKit()
