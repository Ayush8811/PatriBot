# PatriBot: project memory

AI travel planner for Indian Railways: a data platform, an ETA/delay model, a deterministic itinerary planner, and
Claude-powered chat. Read `docs/01-business-requirements.md` (BRD) and `docs/02-solution-architecture.md` before
making design changes. The decisions D1–D11 recorded there are binding unless the owner changes them.

## Domain definitions (do not drift from these)
- **Corridor = a path, not an endpoint pair.** A corridor includes every *reserved* train running along its
  main-line path between the two station clusters, including trains that start or end at intermediate
  stations (≥ 150 km or ≥ 2 consecutive corridor segments in the corridor's direction). Membership is computed in
  dbt (`dim_train_corridor`). A train in several corridors is collected once.
- **MVP corridors (5):** Kolkata ↔ Delhi (primary), Delhi ↔ Patna, Mumbai ↔ Delhi, Bengaluru ↔ Hyderabad,
  Kolkata ↔ Chennai.
- **Station cluster:** all major stations serving a city (e.g. Delhi = NDLS, DLI, NZM, ANVT, DEE).
- **Break journey** (one ticket, IR rules apply) ≠ **split itinerary** (separate tickets). Always label which one.
- Out of scope: unreserved, suburban, MEMU/DEMU/EMU and passenger trains. No ticket booking.

## Budgets and economics
- Railway data API: **RailKit** (D15). Its terms forbid retention; the owner accepted that for the POC only. Never redistribute
  RailKit data, and keep `source=railkit` tags so the history can be replaced before any commercial use. ≤ ₹500/month. The collector enforces `max_calls_per_month` and samples Tier B trains.
- Claude API: ≤ ₹500/month in the POC. Paid tier is ₹100/month for 50 AI chat queries, so each AI query must cost well
  under ₹2. Default chat path = parse → deterministic planner → explain (2 LLM calls). The agent loop is a capped
  fallback only. Models are configured per step through env vars. Models (D12, tentative): Haiku 4.5 for parsing, Sonnet 5.5 for the explanation. Free tier: 3 AI queries per day (D13).
- The LLM never invents trains, times or rules. Those come only from tool or planner output.

## Stack
Python 3.12 + uv, Dagster, dbt-duckdb, DuckDB (warehouse), Postgres + pgvector (serving), LightGBM quantile +
MLflow, FastAPI, Next.js + TypeScript + Tailwind + shadcn/ui, Auth.js (Google), Anthropic Python SDK, local
bge-m3 embeddings. Local-first in Docker Compose. The collector runs on GitHub Actions and writes to a private
`patribot-data` repo.
