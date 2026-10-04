# PatriBot

AI travel planner for Indian Railways. It predicts realistic train arrival times (ETA) from historical
running data and answers natural-language trip requests ("overnight train Kolkata → Delhi, Nov 20–30, least
travel time"), including split/break-journey planning, with a RAG + agent layer.

## Docs
1. [Business Requirements](docs/01-business-requirements.md) — *v0.3*
2. [Solution Architecture](docs/02-solution-architecture.md) — *v0.2*
3. Phase 0: [API provider spike](docs/phase0/01-api-provider-spike.md) · [Collector setup (owner steps)](docs/phase0/02-collector-setup.md)
4. Phase 1: [Generated watchlist](docs/phase1/watchlist.md)
5. Phase 1: [Data platform (run locally, tables)](docs/phase1/data-platform.md)

## Status
- **Phase 0, Foundations: done.** The collector runs every 3 h on RailKit Advance (D15) in the private `patribot-data` repo.
- **Phase 1, Data platform: in progress.**
  - The watchlist generator (corridor membership from RailKit timetables) runs weekly in the data repo.
  - The bronze → silver → gold pipeline (Dagster + dbt-duckdb) and the reverse ETL to Postgres are built and tested.
  - Still to come: `dim_train_corridor` in dbt, weather and calendar.

## Development
```bash
uv sync
uv run pytest
uv run patribot-collector plan --data-dir data        # what would be collected now (no API calls)
uv run patribot-collector run --data-dir data         # offline run with the fixture source
RAIL_API_KEY=... uv run patribot-watchlist build --out watchlist.yaml   # corridor trains; output is private (D15)

# data platform on synthetic data (details: docs/phase1/data-platform.md)
uv run python scripts/make_sample_bronze.py --out samples/bronze
PATRIBOT_DATA_DIR=samples/bronze uv run python -m patribot.transform.bronze   # bronze → Parquet silver input
uv run dbt build --project-dir dbt --profiles-dir dbt                          # silver + gold in warehouse/patribot.duckdb
PATRIBOT_DATA_DIR=samples/bronze uv run dagster dev                            # or orchestrate it all in Dagster
docker compose -f infra/docker-compose.yml --env-file .env up -d               # Postgres + pgvector (cp .env.example .env)
```
