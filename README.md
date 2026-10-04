# PatriBot

AI travel planner for Indian Railways. It predicts realistic train arrival times (ETA) from historical
running data and answers natural-language trip requests ("overnight train Kolkata → Delhi, Nov 20–30, least
travel time"), including split/break-journey planning, with a RAG + agent layer.

## Live app
**https://patri-bot.vercel.app** (private, single-owner login). The API runs on Render's free tier
at `https://patribot-api.onrender.com`, so the first search after idle can take 30–60 s to wake up.

## Docs
1. [Business Requirements](docs/01-business-requirements.md) — *v0.3*
2. [Solution Architecture](docs/02-solution-architecture.md) — *v0.2*
3. Phase 0: [API provider spike](docs/phase0/01-api-provider-spike.md) · [Collector setup (owner steps)](docs/phase0/02-collector-setup.md)
4. Phase 1: [Generated watchlist](docs/phase1/watchlist.md)
5. Phase 1: [Data platform (run locally, tables)](docs/phase1/data-platform.md)
6. [API v1 contract](docs/api/v1.md) · Phase 2: [Planner and API](docs/phase2/planner-api.md)
7. Phase 3: [Web app (Next.js, mock mode, auth & proxy)](docs/phase3/web-app.md) · [Deploy the web app on Vercel](docs/deploy/vercel.md)

## Status
- **Phase 0, Foundations: done.** The collector runs every 3 h on RailKit Advance (D15) in the private `patribot-data` repo.
- **Phase 1, Data platform: done** (weather deferred).
  - The watchlist generator (corridor membership from RailKit timetables) runs weekly in the data repo.
  - The bronze → silver → gold pipeline (Dagster + dbt-duckdb) and the reverse ETL to Postgres are built and tested.
  - The cached timetable feeds `dim_train_schedule`, `dim_train_corridor` and station coordinates. A calendar seed
    (holidays, festival windows, fog season) feeds `dim_date`.
- **Phase 2, Planner + API: built.** Direct, overnight and split search with the `baseline_hist` ETA and explainable
  ranking, served by FastAPI under `/api/v1` ([contract](docs/api/v1.md)). `/chat` is a rule-based stub until Phase 4.
- **Phase 3, Web app: in progress.** Next.js app in `web/` (search form, itinerary cards, train page), built against
  the API v1 contract. A fixtures mock mode lets it run without the backend. Single-owner login and a server-side API
  proxy make it safe to host publicly ([Vercel steps](docs/deploy/vercel.md)). "Ask AI" shows *Coming soon* (Phase 4
  deferred).

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
PATRIBOT_DATA_DIR=samples/bronze uv run python -m patribot.transform.timetable  # timetable cache → Parquet
uv run dbt build --project-dir dbt --profiles-dir dbt                          # silver + gold in warehouse/patribot.duckdb
PATRIBOT_DATA_DIR=samples/bronze uv run dagster dev                            # or orchestrate it all in Dagster
docker compose -f infra/docker-compose.yml --env-file .env up -d               # Postgres + pgvector (cp .env.example .env)

# planner API on that warehouse (details: docs/phase2/planner-api.md)
PATRIBOT_TODAY=2026-12-10 uv run patribot-api       # http://127.0.0.1:8000/api/v1/docs (PATRIBOT_TODAY: sample data only)
curl -s localhost:8000/api/v1/plan -H 'content-type: application/json' -d '{"origin": "KOLKATA",
  "destination": "DELHI", "date_from": "2026-12-20", "date_to": "2026-12-30",
  "preferences": {"overnight": true, "objective": "fastest"}}'
```

### Web app (`web/`, Node 22)
```bash
cd web && npm ci
npm run dev:mock:noauth                            # fixtures, no backend, sign-in skipped: http://localhost:3000
npm run dev:mock                                   # same, with sign-in (PATRIBOT_AUTH_* in web/.env.local)
npm run dev                                        # via the /api/proxy route to PATRIBOT_API_URL (+ PATRIBOT_API_KEY)
npm run hash-password                              # PATRIBOT_AUTH_PASSWORD_HASH for the owner login
npm run lint && npm run typecheck && npm test      # ESLint, tsc, Vitest
npm run test:e2e                                   # Playwright smoke on a mock-mode production build
```
