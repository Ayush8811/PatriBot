# PatriBot

AI travel planner for Indian Railways. It predicts realistic train arrival times (ETA) from historical
running data and answers natural-language trip requests ("overnight train Kolkata → Delhi, Nov 20–30, least
travel time"), including split/break-journey planning, with a RAG + agent layer.

## Docs
1. [Business Requirements](docs/01-business-requirements.md) — *v0.3*
2. [Solution Architecture](docs/02-solution-architecture.md) — *v0.2*
3. Phase 0: [API provider spike](docs/phase0/01-api-provider-spike.md) · [Collector setup (owner steps)](docs/phase0/02-collector-setup.md)
4. Phase 1: [Data platform (run locally, tables)](docs/phase1/data-platform.md)

## Status
**Phase 0, Foundations:** the corridor config, the budgeted collector (RailKit, D15), CI, and the data-repo workflows are built.
Waiting on 3 owner steps: RailKit key, the private `patribot-data` repo, and one secret ([setup](docs/phase0/02-collector-setup.md)).

**Phase 1, Data platform (in progress):** the bronze → silver → gold pipeline (Dagster + dbt-duckdb), its data tests and
the reverse ETL to Postgres are built and verified on synthetic data. Still to come: timetable-based corridor membership,
weather and calendar.

## Development
```bash
uv sync
uv run pytest
uv run patribot-collector plan --data-dir data        # what would be collected now (no API calls)
uv run patribot-collector run --data-dir data         # offline run with the fixture source

# data platform on synthetic data (details: docs/phase1/data-platform.md)
uv run python scripts/make_sample_bronze.py --out samples/bronze
PATRIBOT_DATA_DIR=samples/bronze uv run python -m patribot.transform.bronze   # bronze → Parquet silver input
uv run dbt build --project-dir dbt --profiles-dir dbt                          # silver + gold in warehouse/patribot.duckdb
PATRIBOT_DATA_DIR=samples/bronze uv run dagster dev                            # or orchestrate it all in Dagster
docker compose -f infra/docker-compose.yml --env-file .env up -d               # Postgres + pgvector (cp .env.example .env)
```
