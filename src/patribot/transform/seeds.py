"""Generate dbt seed CSVs from `config/corridors.yaml` (the single source of truth for clusters and corridors).

uv run python -m patribot.transform.seeds            # rewrite dbt/seeds/*.csv
uv run python -m patribot.transform.seeds --check    # exit 1 if the committed seeds are stale (used in tests)
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = REPO_ROOT / "config" / "corridors.yaml"
DEFAULT_SEEDS_DIR = REPO_ROOT / "dbt" / "seeds"


def _csv(header: list[str], rows: list[list[Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for row in rows:
        w.writerow(["true" if v is True else "false" if v is False else v for v in row])
    return buf.getvalue()


def render_seeds(config: dict[str, Any]) -> dict[str, str]:
    """Return {file name: CSV text} for every seed derived from the corridor config."""
    clusters = config["clusters"]
    cluster_rows = [[cid, code, i] for cid, codes in clusters.items() for i, code in enumerate(codes, 1)]
    corridor_rows, waypoint_rows, hub_rows = [], [], []
    for c in config["corridors"]:
        corridor_rows.append([c["id"], c["name"], c["a"], c["b"], bool(c.get("primary", False)), bool(c["verified"])])
        for path_name, stations in c["paths"].items():
            waypoint_rows.extend([c["id"], path_name, i, code] for i, code in enumerate(stations, 1))
        hub_rows.extend([c["id"], code] for code in c.get("split_hubs", []))
    m = config["membership"]
    params = [
        ["min_km", m["min_km"]],
        ["min_consecutive_segments", m["min_consecutive_segments"]],
        ["exclude_train_types", "|".join(m["exclude_train_types"])],
    ]
    return {
        "seed_station_cluster.csv": _csv(["cluster_id", "station_code", "cluster_rank"], cluster_rows),
        "seed_corridor.csv": _csv(
            ["corridor_id", "corridor_name", "cluster_a", "cluster_b", "is_primary", "verified"], corridor_rows
        ),
        "seed_corridor_waypoint.csv": _csv(["corridor_id", "path_name", "waypoint_seq", "station_code"], waypoint_rows),
        "seed_corridor_split_hub.csv": _csv(["corridor_id", "station_code"], hub_rows),
        "seed_corridor_membership_param.csv": _csv(["param", "value"], params),
    }


def load_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def stale_seeds(config_path: str | Path = DEFAULT_CONFIG, seeds_dir: str | Path = DEFAULT_SEEDS_DIR) -> list[str]:
    seeds_dir = Path(seeds_dir)
    stale = []
    for name, text in render_seeds(load_config(config_path)).items():
        path = seeds_dir / name
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            stale.append(name)
    return stale


def write_seeds(config_path: str | Path = DEFAULT_CONFIG, seeds_dir: str | Path = DEFAULT_SEEDS_DIR) -> list[Path]:
    seeds_dir = Path(seeds_dir)
    seeds_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in render_seeds(load_config(config_path)).items():
        path = seeds_dir / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("--seeds-dir", default=str(DEFAULT_SEEDS_DIR))
    p.add_argument("--check", action="store_true", help="fail if the seeds differ from the config")
    args = p.parse_args(argv)
    if args.check:
        stale = stale_seeds(args.config, args.seeds_dir)
        if stale:
            print(f"stale dbt seeds (run `python -m patribot.transform.seeds`): {stale}", file=sys.stderr)
            return 1
        print("dbt seeds are in sync with corridors.yaml")
        return 0
    for path in write_seeds(args.config, args.seeds_dir):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
