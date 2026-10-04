# PatriBot

AI travel planner for Indian Railways. It predicts realistic train arrival times (ETA) from historical
running data and answers natural-language trip requests ("overnight train Kolkata → Delhi, Nov 20–30, least
travel time"), including split/break-journey planning, with a RAG + agent layer.

## Docs
1. [Business Requirements](docs/01-business-requirements.md) — *v0.3*
2. [Solution Architecture](docs/02-solution-architecture.md) — *v0.2*
3. Phase 0: [API provider spike](docs/phase0/01-api-provider-spike.md) · [Collector setup (owner steps)](docs/phase0/02-collector-setup.md)

## Status
**Phase 0, Foundations:** the corridor config, the budgeted collector and the CI/collector workflows are built. Waiting on
the API sign-up and data-repo setup ([owner steps](docs/phase0/02-collector-setup.md)).

## Development
```bash
uv sync
uv run pytest
uv run patribot-collector plan --data-dir data        # what would be collected now (no API calls)
uv run patribot-collector run --data-dir data         # offline run with the fixture source
```
