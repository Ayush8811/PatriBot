from __future__ import annotations

import csv
import io

from patribot.transform.seeds import load_config, main, render_seeds, stale_seeds


def test_committed_dbt_seeds_match_corridors_yaml():
    stale = stale_seeds()
    assert not stale, f"regenerate with `uv run python -m patribot.transform.seeds`: {stale}"


def test_seed_content_reflects_config():
    cfg = load_config()
    seeds = {name: list(csv.DictReader(io.StringIO(text))) for name, text in render_seeds(cfg).items()}

    clusters = seeds["seed_station_cluster.csv"]
    assert {"cluster_id": "DELHI", "station_code": "NDLS", "cluster_rank": "1"} in clusters
    codes = [r["station_code"] for r in clusters]
    assert len(codes) == len(set(codes)), "a station must belong to one cluster only"

    corridors = {r["corridor_id"]: r for r in seeds["seed_corridor.csv"]}
    assert set(corridors) == {c["id"] for c in cfg["corridors"]}
    assert corridors["KOL-DEL"]["is_primary"] == "true"

    gc = [r for r in seeds["seed_corridor_waypoint.csv"] if r["path_name"] == "grand_chord"]
    assert gc[0]["station_code"] == "HWH" and gc[-1]["station_code"] == "NDLS"
    assert [int(r["waypoint_seq"]) for r in gc] == list(range(1, len(gc) + 1))


def test_check_mode_detects_drift(tmp_path, capsys):
    assert main(["--seeds-dir", str(tmp_path)]) == 0
    assert main(["--seeds-dir", str(tmp_path), "--check"]) == 0
    (tmp_path / "seed_corridor.csv").write_text("corridor_id\nX\n", encoding="utf-8")
    assert main(["--seeds-dir", str(tmp_path), "--check"]) == 1
    assert "seed_corridor.csv" in capsys.readouterr().err
