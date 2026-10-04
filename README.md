# PatriBot

AI travel planner for Indian Railways. It predicts realistic train arrival times (ETA) from historical
running data and answers natural-language trip requests ("overnight train Kolkata → Delhi, Nov 20–30, least
travel time"), including split/break-journey planning, with a RAG + agent layer.

## Docs
1. [Business Requirements](docs/01-business-requirements.md) — *v0.3*
2. [Solution Architecture](docs/02-solution-architecture.md) — *v0.2*
3. Phase 0: [API provider spike](docs/phase0/01-api-provider-spike.md) · [Collector setup (owner steps)](docs/phase0/02-collector-setup.md)
4. Phase 1: [Generated watchlist](docs/phase1/watchlist.md)

## Status
**Phase 0, Foundations:** the corridor config, the budgeted collector (RailKit, D15), CI, and the data-repo workflows are built.
The watchlist generator (corridor membership from RailKit timetables) is built; it runs weekly in the data repo once set up.
Waiting on 3 owner steps: RailKit key, the private `patribot-data` repo, and one secret ([setup](docs/phase0/02-collector-setup.md)).

## Development
```bash
uv sync
uv run pytest
uv run patribot-collector plan --data-dir data        # what would be collected now (no API calls)
uv run patribot-collector run --data-dir data         # offline run with the fixture source
RAIL_API_KEY=... uv run patribot-watchlist build --out watchlist.yaml   # corridor trains; output is private (D15)
```
