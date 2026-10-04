"""patribot-collector: daily running-status collector (runs on GitHub Actions, architecture doc §2).

patribot-collector plan  --data-dir data            show what would be fetched now (no API calls)
patribot-collector run   --data-dir data            fetch due runs within budget and store them
patribot-collector probe --train 12301 --days-back 7  check a provider's past-date depth and schema
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from patribot.collector.config import load_watchlist
from patribot.collector.planner import make_plan
from patribot.collector.store import DataStore
from patribot.sources.base import STOP_HTTP_STATUSES, FetchStatus, RawResponse, RunningStatusSource
from patribot.sources.registry import SOURCES, get_source

DEFAULT_WATCHLIST = Path(__file__).resolve().parents[3] / "config" / "watchlist.yaml"


def _now_local(tz: str, override: str | None) -> datetime:
    if override:
        return datetime.fromisoformat(override).astimezone(ZoneInfo(tz))
    return datetime.now(UTC).astimezone(ZoneInfo(tz))


def _plan(args: argparse.Namespace):
    wl = load_watchlist(args.watchlist)
    store = DataStore(args.data_dir)
    now = _now_local(wl.collector.timezone, args.now)
    plan = make_plan(wl.trains, wl.collector, now, store.load_manifest(), store.load_usage(now.date()))
    return wl, store, now, plan


def _summary(plan, extra: dict | None = None) -> dict:
    out = {
        "due_total": plan.due_total,
        "selected": len(plan.selected),
        "sampled_out": plan.sampled_out,
        "over_budget": plan.over_budget,
        "tier_b_rate": plan.tier_b_rate,
        "tier_c_rate": plan.tier_c_rate,
        "remaining_budget_today": plan.remaining_budget,
    }
    return out | (extra or {})


def cmd_plan(args: argparse.Namespace) -> int:
    _, _, _, plan = _plan(args)
    print(json.dumps(_summary(plan), indent=2))
    for r in plan.selected:
        print(f"  {r.tier}  {r.train_no}  {r.start_date}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    _, store, now, plan = _plan(args)
    source: RunningStatusSource = get_source(args.source)
    responses: list[RawResponse] = []
    stopped = None
    for r in plan.selected:
        resp = source.fetch_run_status(r.train_no, r.start_date)
        responses.append(resp)
        if resp.http_status in STOP_HTTP_STATUSES:
            # bad key or quota/rate limit: further calls would fail too; the rest stay due for the next run
            stopped = f"stopped after HTTP {resp.http_status}"
            break
    path = store.write_batch(responses, now.astimezone(UTC), now.date())
    counts = {s.value: sum(r.status is s for r in responses) for s in FetchStatus}
    extra = {"fetched": counts, "stopped": stopped, "file": str(path) if path else None}
    print(json.dumps(_summary(plan, extra), indent=2))
    # fail the workflow (=> GitHub email) on a bad key, exhausted quota, or when every call errored
    all_failed = bool(responses) and counts[FetchStatus.ERROR.value] == len(responses)
    return 1 if all_failed or stopped else 0


def cmd_probe(args: argparse.Namespace) -> int:
    source = get_source(args.source)
    samples = Path(args.samples_dir)
    samples.mkdir(parents=True, exist_ok=True)
    today = date.today()
    for back in range(args.days_back, -1, -1):
        day = today - timedelta(days=back)
        r = source.fetch_run_status(args.train, day)
        keys = sorted(r.payload)[:12] if isinstance(r.payload, dict) else type(r.payload).__name__
        size = len(json.dumps(r.payload, ensure_ascii=False)) if r.payload is not None else 0
        print(f"{day}  -{back}d  {r.status.value:<9} http={r.http_status}  bytes={size}  keys={keys}")
        (samples / f"{r.source}_{args.train}_{day}.json").write_text(
            json.dumps(r.to_record(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
    print(f"samples saved to {samples}/ - check stops, scheduled/actual times, delay and cancellation fields")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="patribot-collector", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--data-dir", default="data", help="checkout of the private patribot-data repo")
        sp.add_argument("--watchlist", default=str(DEFAULT_WATCHLIST))
        sp.add_argument("--now", help="override current time (ISO 8601), for testing")

    sp = sub.add_parser("plan", help="show due runs without calling the API")
    common(sp)
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser("run", help="fetch due runs within budget and store them")
    common(sp)
    sp.add_argument("--source", choices=SOURCES, default="fixture")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("probe", help="check past-date depth and schema of a provider")
    sp.add_argument("--source", choices=SOURCES, required=True)
    sp.add_argument("--train", default="12301")
    sp.add_argument("--days-back", type=int, default=7)
    sp.add_argument("--samples-dir", default="samples")
    sp.set_defaults(func=cmd_probe)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
