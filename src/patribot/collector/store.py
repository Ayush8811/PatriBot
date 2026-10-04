"""Bronze storage inside a checkout of the private `patribot-data` repo (architecture doc §2).

Layout:
  raw/<source>/running_status/collected_date=YYYY-MM-DD/<HHMMSS>Z.jsonl.gz   one file per collector run
  state/manifest.jsonl                                                     append-only attempt log
  state/usage/YYYY-MM.json                                                 API calls per day (budget)
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from patribot.sources.base import FetchStatus, RawResponse

RunKey = tuple[str, date]  # (train_no, start_date)


@dataclass
class RunState:
    status: FetchStatus
    attempts: int


class DataStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._manifest = self.root / "state" / "manifest.jsonl"
        self._usage_dir = self.root / "state" / "usage"

    # ---- manifest -------------------------------------------------------------------------------------
    def load_manifest(self) -> dict[RunKey, RunState]:
        states: dict[RunKey, RunState] = {}
        if not self._manifest.exists():
            return states
        with self._manifest.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                rec = json.loads(line)
                key = (rec["train_no"], date.fromisoformat(rec["start_date"]))
                prev = states.get(key)
                attempts = (prev.attempts if prev else 0) + 1
                status = FetchStatus(rec["status"])
                # once a run is collected successfully it stays collected
                if prev and prev.status is FetchStatus.OK:
                    status = FetchStatus.OK
                states[key] = RunState(status, attempts)
        return states

    # ---- usage ----------------------------------------------------------------------------------------
    def _usage_path(self, day: date) -> Path:
        return self._usage_dir / f"{day:%Y-%m}.json"

    def load_usage(self, day: date) -> dict[str, int]:
        path = self._usage_path(day)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))["by_day"]

    def _add_usage(self, day: date, calls: int) -> None:
        by_day = self.load_usage(day)
        by_day[day.isoformat()] = by_day.get(day.isoformat(), 0) + calls
        path = self._usage_path(day)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"month": f"{day:%Y-%m}", "total": sum(by_day.values()), "by_day": dict(sorted(by_day.items()))}
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    # ---- write a collector run ------------------------------------------------------------------------
    def write_batch(self, responses: list[RawResponse], now_utc: datetime, local_day: date) -> Path | None:
        """Persist responses, manifest entries and usage atomically enough for a single-writer cron job."""
        if not responses:
            return None
        source = responses[0].source
        out = (
            self.root
            / "raw"
            / source
            / "running_status"
            / f"collected_date={now_utc:%Y-%m-%d}"
            / f"{now_utc:%H%M%S}Z.jsonl.gz"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(out, "wt", encoding="utf-8") as fh:
            for r in responses:
                fh.write(json.dumps(r.to_record(), ensure_ascii=False) + "\n")

        self._manifest.parent.mkdir(parents=True, exist_ok=True)
        rel = out.relative_to(self.root).as_posix()
        with self._manifest.open("a", encoding="utf-8") as fh:
            for r in responses:
                fh.write(
                    json.dumps(
                        {
                            "train_no": r.train_no,
                            "start_date": r.start_date.isoformat(),
                            "source": r.source,
                            "status": r.status.value,
                            "fetched_at": r.fetched_at.isoformat(),
                            "file": rel,
                        }
                    )
                    + "\n"
                )
        self._add_usage(local_day, len(responses))
        return out
