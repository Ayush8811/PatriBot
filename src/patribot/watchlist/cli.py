"""patribot-watchlist: generate the collector watchlist from corridor membership (docs/phase1/watchlist.md).

patribot-watchlist build --source railkit --corridors config/corridors.yaml \\
    --base-watchlist config/watchlist.yaml --out watchlist.yaml [--max-calls 2500]

Needs RAIL_API_KEY. The output is RailKit-derived: write it into the PRIVATE data repo, never commit it to the
public code repo (D15). Exit status 1 when discovery stopped early (max-calls guard, bad key, quota): the report
is written, the watchlist is not (unless --allow-partial), and cached responses let the next run resume.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

from patribot.collector.config import CollectorSettings
from patribot.sources.base import TimetableSource
from patribot.sources.railkit import DEFAULT_MIN_INTERVAL_S
from patribot.sources.railkit_timetable import DEFAULT_RUN_DAYS_ORDER, RailKitTimetableSource
from patribot.watchlist.build import build, render_watchlist
from patribot.watchlist.corridors import load_corridors

TIMETABLE_SOURCES = ("railkit",)
DEFAULT_MAX_CALLS = 2500
ROOT = Path(__file__).resolve().parents[3]


def get_timetable_source(name: str, max_calls: int | None, cache_dir: str | None, run_days_order: str):
    if name != "railkit":
        raise ValueError(f"unknown timetable source {name!r}; expected one of {TIMETABLE_SOURCES}")
    kw: dict = {"min_interval_s": float(os.environ.get("RAIL_MIN_INTERVAL_S", DEFAULT_MIN_INTERVAL_S))}
    if base := os.environ.get("RAIL_API_BASE_URL"):
        kw["base_url"] = base
    return RailKitTimetableSource(
        os.environ.get("RAIL_API_KEY", ""),
        max_calls=max_calls,
        cache_dir=cache_dir,
        run_days_order=run_days_order,
        **kw,
    )


def _collector_settings(base_watchlist: str | None) -> dict:
    if base_watchlist and Path(base_watchlist).exists():
        with open(base_watchlist, encoding="utf-8") as fh:
            raw = (yaml.safe_load(fh) or {}).get("collector")
        if raw:
            return raw
    return CollectorSettings().model_dump(mode="json")


def cmd_build(args: argparse.Namespace) -> int:
    cfg = load_corridors(args.corridors)
    collector = _collector_settings(args.base_watchlist)
    try:
        source: TimetableSource = get_timetable_source(
            args.source, args.max_calls, args.cache_dir or None, args.run_days_order
        )
    except ValueError as exc:  # e.g. RAIL_API_KEY not set
        print(f"error: {exc}", file=sys.stderr)
        return 2
    result = build(source, cfg, include_specials=args.include_specials)
    report = result.report | {"max_calls": args.max_calls, "out": None}
    write = result.trains and (result.complete or args.allow_partial)
    if write:
        Path(args.out).write_text(render_watchlist(result.trains, collector, result.report), encoding="utf-8")
        report["out"] = args.out
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    print(text)
    if not result.complete:
        print(f"stopped early ({result.stopped}); watchlist {'written' if write else 'NOT written'}", file=sys.stderr)
        return 1
    if not result.trains:
        print("no corridor trains found; watchlist NOT written", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="patribot-watchlist", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="command", required=True)
    sp = sub.add_parser("build", help="discover corridor trains and write the watchlist")
    sp.add_argument("--source", choices=TIMETABLE_SOURCES, default="railkit")
    sp.add_argument("--corridors", default=str(ROOT / "config" / "corridors.yaml"))
    sp.add_argument("--base-watchlist", help="watchlist whose `collector:` settings block is kept")
    sp.add_argument("--out", default="watchlist.yaml")
    sp.add_argument("--report", help="also write the JSON report to this file")
    sp.add_argument(
        "--max-calls", type=int, default=DEFAULT_MAX_CALLS, help="stop before sending more API requests than this"
    )
    sp.add_argument(
        "--cache-dir", default=".watchlist-cache", help="on-disk response cache ('' to disable); hits are free"
    )
    sp.add_argument(
        "--run-days-order",
        choices=("mon", "sun"),
        default=DEFAULT_RUN_DAYS_ORDER.lower(),
        help="first day of RailKit's 7-character running-days string",
    )
    sp.add_argument("--include-specials", action="store_true", help="keep 0xxxx special trains")
    sp.add_argument("--allow-partial", action="store_true", help="write the watchlist even if discovery stopped")
    sp.set_defaults(func=cmd_build)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
