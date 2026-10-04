# PatriBot — Solution Architecture

| Field | Value |
|---|---|
| Document | 02 — Solution Architecture |
| Status | **Draft v0.1, for review** |
| Inputs | [01 — Business Requirements v0.2](01-business-requirements.md), decisions D1–D7 |
| Next | 03 — Data Design (schemas, contracts), 04 — ETA Model Design, 05 — Agent and RAG Design |

---

## 1. Architecture at a glance

```
                ┌────────────────────────────── DATA PLANE ─────────────────────────────────┐
 External       │  Ingestion           Lakehouse (DuckDB + Parquet)          Serving        │
 sources        │  (Dagster assets)    bronze ──► silver ──► gold  (dbt)     (Postgres)     │
 ───────────    │                                                                           │
 Railway API ───┼─► source adapters ─► raw JSON ─► cleaned ─► facts/dims ─► reverse-ETL ──┐ │
 (paid, ≤₹500)  │   (pluggable)        (immutable)  runs/stops  features     curated tables │ │
 Open datasets ─┼─►                                            delay stats               │ │
 Weather API ───┼─►                                                                      │ │
 Calendars ─────┼─►                                                                      │ │
 Rules PDFs ────┼─► doc parser ─► chunks ─► embeddings (local bge-m3) ─────► pgvector ───┤ │
                └──────────────────────────────────────────────────────────────────────┼─┘
                ┌───────────────────────────── ML PLANE ───────────────────────────────┼─┐
                │  gold features ─► train (LightGBM quantile) ─► MLflow registry       │ │
                │  nightly batch inference: next-60-day runs × stops ─► predictions ───┤ │
                │  on-request nowcast (live delay → downstream ETA)                    │ │
                └──────────────────────────────────────────────────────────────────────┼─┘
                ┌─────────────────────────── APP PLANE ────────────────────────────────▼─┐
                │  FastAPI                                                               │
                │   ├─ /search, /plan, /predict-eta  ─► Planner engine (deterministic)   │
                │   └─ /chat ─► Claude agent (tool use) ─► tools = planner, ETA, RAG     │
                │  Next.js web app  ◄── SSE streaming ──                                 │
                └────────────────────────────────────────────────────────────────────────┘
```

**Guiding principles**
1. **The LLM orchestrates and the code computes.** Claude parses the request, calls tools and explains the result.
   Train lists, times, predictions and rankings always come from deterministic code and data. The LLM never invents
   a train.
2. **Data sources are plug-ins.** Every external feed sits behind an adapter interface, so a buyer (D5) can swap in
   their own feed.
3. **Precompute what's predictable.** Forecast ETAs for every corridor train run over the booking window are computed
   nightly. Request-time work is mostly lookups plus the planner search.
4. **Local-first and cloud-portable.** Everything runs in Docker Compose. Every component has a managed-cloud
   equivalent (§10).

## 2. Is local-first OK? (D2)

**Yes, it's the right choice for this phase.** It costs nothing, iterates fast, and if the stack is containerised and
storage paths are S3-compatible, moving to cloud later is a configuration change, not a rewrite.

**One exception: the data collector.** The ETA model's training history only builds up if we capture every
train run *every day*. A laptop that's asleep breaks that, and missed days can't be recovered (most APIs only give a
few days of past running status). So:

| Component | Where it runs | Cost |
|---|---|---|
| **Collector** (daily API pulls → raw JSON) | **GitHub Actions scheduled workflow** (or any free always-on micro VM), writing to **Cloudflare R2** (S3-compatible) | Free tier is enough |
| Everything else (Dagster, dbt, DuckDB, Postgres, MLflow, API, web) | Local Docker Compose | ₹0 |

The local stack syncs raw files down from R2 and processes them. Collection never depends on your laptop.

## 3. MVP corridors (D4)

| # | Corridor | Station cluster A | Station cluster B | Why |
|---|---|---|---|---|
| 1 | **Kolkata ↔ Delhi** | HWH, SDAH, KOAA, SRC | NDLS, DLI, NZM, ANVT, DEE | Primary demo (golden query Q1). Premium trains (Rajdhani, Duronto). Fog-prone |
| 2 | **Delhi ↔ Patna** | NDLS, DLI, ANVT, NZM | PNBE, RJPB, PPTA, DNR | Among the worst-delayed and most rush-hit corridors (Chhath and post-Diwali). Shares track with #1, so segment-level learning transfers, and Patna is a natural **split-journey hub** for #1 |
| 3 | **Mumbai ↔ Delhi** | CSMT, MMCT, BDTS, LTT | NDLS, NZM, DLI | Different zones and operating behaviour (Western/Central). Tests generalisation |
| 4 | **Bengaluru ↔ Hyderabad** | SBC, YPR, SMVB | SC, HYB, KCG | A southern, mostly overnight corridor with lower fog risk. A contrast case for the model |

Station codes and train lists are **confirmed during Phase 0** from the timetable source. Expect roughly 150–250
distinct train numbers in total, including intermediate hubs.

## 4. Data sourcing and budget (D1)

### 4.1 Source adapters
```python
class TimetableSource(Protocol):
    def list_trains_between(self, src: str, dst: str) -> list[TrainSummary]: ...
    def get_schedule(self, train_no: str) -> TrainSchedule: ...        # stops, times, day offsets, days of run

class RunningStatusSource(Protocol):
    def get_run(self, train_no: str, start_date: date) -> RunStatus: ... # actual arr/dep per stop
```
Concrete adapters: `RapidApiRailAdapter`, `IndianRailApiAdapter` (both candidates), `OpenDataTimetableAdapter`
(open datasets), and later `PartnerAdapter` for a buyer's own feed.

### 4.2 Call budget (≤ ₹500/month ≈ $6)

| Pull | Frequency | Volume / month (est.) |
|---|---|---|
| Running status: one call per completed train run (returns every stop) | Daily, after the expected arrival | ~150 trains × ~0.8 runs/day × 30 ≈ **3,600** |
| Retry and gap fill | As needed | ~400 |
| Timetable refresh for corridor trains | Weekly | ~1,000 |
| Live status for nowcast (demo only, on request, cached 5 min) | On demand | ~500 |
| **Total** | | **≈ 5,500 calls/month** |

**Phase 0 spike:** compare 2–3 providers on (a) price for about 6k calls a month, (b) how many days back they
return past running status (that limits backfill), (c) schema completeness, and (d) terms of use permitting storage
and derived models. Choose the cheapest one that passes all four.

### 4.3 Other sources (free)
- **Weather:** Open-Meteo (historical + forecast, free, no key) at sample points along each corridor. Visibility
  and fog proxies matter for Nov–Feb.
- **Calendar:** national holidays and festival dates (Diwali, Chhath, Holi, Durga Puja, Eid). Maintained as a seed CSV
  in dbt.
- **Rules corpus:** official IR/IRCTC PDFs and pages (refund rules, break journey, Tatkal, quotas, ARP), stored
  with source URL and retrieval date.

### 4.4 Cold-start reality check
The history starts the day the collector goes live, so by late November we'll have about **6–7 weeks** of data. That
is enough for the model to learn a train's typical delay, but not **seasonal** effects (one fog season needs a year).
Mitigations:
- A hierarchical design: train-level stats are shrunk toward segment- and corridor-level stats when data is sparse.
- Use any history the chosen API can backfill.
- Report coverage honestly in the UI ("based on 41 runs since Oct 2026").
- Seasonal features are built in from day one, so the model improves as each season gets recorded.

## 5. Data platform

### 5.1 Stack
| Concern | Choice | Why |
|---|---|---|
| Language and packaging | Python 3.12, `uv` workspace | Fast, reproducible |
| Orchestration | **Dagster** | Asset-based lineage, partitions per run date, backfills, asset checks, good local UI |
| Raw storage | Parquet/JSON on local disk ⇄ R2 (S3 API via `fsspec`) | Same code works locally and in the cloud |
| Warehouse | **DuckDB** | Zero-ops, very fast on Parquet. Swappable for MotherDuck or BigQuery |
| Transformations | **dbt-core + dbt-duckdb** | Versioned SQL models, tests, docs, lineage |
| Data quality | dbt tests + Dagster asset checks | Freshness, uniqueness, accepted ranges, volume anomalies |
| Serving DB | **Postgres 16 + pgvector** | App queries, concurrency, vector search in one place |

### 5.2 Medallion layers (detail in doc 03)
| Layer | Key tables |
|---|---|
| **Bronze** | `raw_running_status` (JSON, partitioned by `source/run_date`), `raw_schedule`, `raw_weather` |
| **Silver** | `stg_train_run_stop` (one row per run × stop: scheduled vs. actual, day offset resolved, IST), `stg_train_schedule`, `stg_station` |
| **Gold** | `dim_station`, `dim_station_cluster`, `dim_train` (SCD-2), `fct_run_stop_delay`, `agg_delay_stats` (train × stop × month), `feat_eta_training`, `route_graph_edges`, `fct_eta_forecast` |

**Data rules that matter:** resolve multi-day runs with day offsets. Flag cancelled and diverted runs and keep them out
of the delay targets. Mark rescheduled departures. Clip delay outliers above a set threshold, but keep them in a
separate disruption table.

### 5.3 Reverse ETL
A Dagster asset copies serving tables (`fct_eta_forecast`, `dim_*`, `agg_delay_stats`, schedule) from DuckDB into
Postgres after each successful build. The API only reads from Postgres.

## 6. ML plane: ETA model (detail in doc 04)

| Aspect | Design |
|---|---|
| **Target** | Arrival delay (minutes) at each stop of a run |
| **Modes** | *Forecast* (future run date, no live info) and *Nowcast* (current delay at last-reported stop known) |
| **Baselines** | B0: scheduled time (delay = 0). B1: historical mean delay per train × stop. B2: B1 by month |
| **Model** | LightGBM **quantile regression** (P10/P50/P90), with conformal calibration on a time-based holdout |
| **Key features** | Train type and priority, stop index and distance from origin, segment, day of week, month, festival/rush window, fog-season flag and weather, rolling 7/30/90-day delay stats for train × stop and segment, origin departure delay (nowcast), upstream delay at the current stop (nowcast) |
| **Validation** | Rolling time-series splits only, never random splits, so there's no leakage |
| **Tracking** | MLflow (local): params, metrics, model registry, model card |
| **Inference** | Nightly batch: all corridor runs × stops for the next 60 days → `fct_eta_forecast`. Request-time: nowcast re-prediction for a specific live run |
| **Monitoring** | Daily backtest once actual arrivals come in (MAE, P90 coverage by corridor), feature drift, and alerts on degradation |

Derived product metrics: **predicted journey time** = predicted P50 arrival at destination minus scheduled
departure, and a **reliability score** = P(arrival delay ≤ 30 min).

## 7. Planner engine (deterministic)

### 7.1 Direct search
1. Resolve origin and destination to station clusters.
2. For each date in the range, find trains running that day that stop at both clusters in the correct order.
3. Join `fct_eta_forecast` to get predicted P50/P90 arrivals.
4. Apply hard constraints (e.g. must arrive by 09:00 at P90) and preference filters (overnight).

### 7.2 Split / break journeys
For each hub H in a curated hub list per corridor (e.g. for Kolkata → Delhi: Patna, Gaya, Prayagraj,
Pt. DD Upadhyaya Jn, Kanpur, Dhanbad):
- Leg 1 A → H, with predicted arrival `t1_p90`.
- Leg 2 H → B, departing `t2 ≥ t1_p90 + min_buffer` and `t2 ≤ t1_p50 + max_layover` (defaults: 45 min buffer, 8 h max layover).
- Label each result as an **official break journey** (one ticket, rules permitting) or a **split itinerary**
  (separate tickets, with a missed-connection risk warning).

Phase 2 replaces the hub enumeration with a **Connection Scan Algorithm** over the time-expanded timetable,
for all-India coverage.

### 7.3 Ranking
```
score = w1·norm(predicted_journey_time_p50)
      + w2·(1 − reliability)
      + w3·preference_penalty   (not overnight, outside arrival window, class unavailable)
      + w4·transfer_penalty     (per extra leg, scaled by connection risk)
```
Weights come from the parsed intent: "least travel time" raises w1, and "must reach by" turns into a hard P90
constraint. Every score component is returned to the UI for explainability (NFR-7).

## 8. Agent and RAG (detail in doc 05)

### 8.1 Agent
- **Anthropic Python SDK** with tool use (the SDK tool runner), **Claude Opus 5.5 (`claude-opus-5-5`)** as the
  default model. The model is configurable through an env var (§9).
- **Tools (strict JSON schemas):**

| Tool | Purpose |
|---|---|
| `resolve_place(text)` | City or colloquial name → station cluster |
| `search_trains(origin, dest, dates, filters)` | Direct options with ETA predictions |
| `plan_itinerary(origin, dest, dates, constraints, allow_split)` | Ranked direct and split options |
| `predict_eta(train_no, run_date, stop?)` | Forecast or nowcast for a specific run |
| `train_performance(train_no, period)` | Historical delay stats and distributions |
| `search_knowledge(query)` | RAG over the rules and notices corpus, returning cited chunks |
| `live_status(train_no)` | Current position (cached, budget-limited) |

- **Guardrails:**
  - The system prompt forbids stating any train number, time or rule that didn't come from a tool result.
  - The response includes structured itinerary cards (JSON) alongside the prose, and the UI renders cards from the JSON, not from the prose.
  - Missing data → say so (FR-18).
- **Prompt caching** on the stable system prompt and tool definitions. The agent loop has a capped number of
  steps.
- **Streaming** to the web app over SSE.

### 8.2 RAG
| Step | Choice |
|---|---|
| Parse | `pypdf` / HTML-to-text. Keep page numbers and source URL |
| Chunk | ~500-token structure-aware chunks (rule sections), with a contextual header (doc title + section) |
| Embed | **Local `BAAI/bge-m3`** (free, multilingual, so Hindi and Bengali come later at no extra cost). Anthropic does not offer an embeddings model |
| Store | pgvector (HNSW) + Postgres full-text search → **hybrid retrieval** (RRF fusion) |
| Answer | Claude answers using only the retrieved chunks, citing doc, section and URL |

**What RAG is *not* used for:** train facts and delay statistics. Those are structured data served by tools (FR-16,
FR-17).

### 8.3 Evaluation
- A golden set: Q1–Q6 plus about 50 curated queries, each with expected tool calls and constraints.
- Automated checks:
  - Correct tools called.
  - Constraints satisfied in the returned itineraries.
  - No train number in the answer that isn't in the tool outputs.
  - RAG faithfulness via an LLM judge plus spot checks.
- Runs in CI on demand (it costs money), and is required before any prompt or model change.

## 9. LLM cost (D3), needs your confirmation

Current Anthropic list prices (per million tokens, input / output): **Opus 5.5: $4 / $20**, Sonnet 5.5: $2 / $10,
Haiku 4.5: $1 / $5. Cache reads are much cheaper than fresh input (Opus 5.5: $0.20).

**Rough estimate, to be measured:** a typical planning query is 3–5 tool-loop turns, about 40–50k input tokens (half
of them cached) and about 3k output tokens:

| Model | ≈ cost per planning query | 100 queries / month | 500 queries / month |
|---|---|---|---|
| Opus 5.5 (default) | ~$0.12–0.15 | ~$15 (≈ ₹1,300) | ~$70 (≈ ₹6,000) |
| Sonnet 5.5 | ~$0.06–0.08 | ~$7 (≈ ₹600) | ~$35 (≈ ₹3,000) |
| Haiku 4.5 | ~$0.03–0.04 | ~$4 (≈ ₹300) | ~$18 (≈ ₹1,500) |

**Controls:**
- The model is an env var (`PATRIBOT_LLM_MODEL`).
- Effort level is set per route.
- Prompt caching.
- Responses for identical normalised intents are cached.
- A daily spend cap in the API layer, with per-query cost logged to Postgres.

⚠️ The ₹500/month budget (D1) covers the railway data API. **Claude usage is billed separately.** See open
question OQ-1.

## 10. Application layer and infrastructure

| Concern | Local (now) | Cloud (later) |
|---|---|---|
| API | FastAPI (uvicorn) in Docker | Cloud Run / ECS / Fly.io |
| Web | **Next.js (App Router) + TypeScript + Tailwind + shadcn/ui** | Vercel / Cloud Run |
| Orchestration | Dagster (webserver + daemon) | Dagster+ / VM |
| Warehouse | DuckDB file | MotherDuck / BigQuery |
| Object storage | Local FS ⇄ R2 | R2 / S3 / GCS |
| Serving DB | Postgres + pgvector container | Neon / Supabase / Cloud SQL |
| ML tracking | MLflow container | Managed MLflow / same VM |
| Collector | GitHub Actions cron → R2 | Same |
| CI | GitHub Actions: ruff, mypy, pytest, dbt build on sample data, web lint and typecheck | Same, plus deploy |
| Secrets | `.env` (git-ignored) | Platform secret manager |

### 10.1 Web app screens (MVP)
1. **Chat planner:**
   - Conversational input.
   - Streamed answer with **itinerary cards**: train, date, departure, scheduled vs. predicted arrival (P50–P90 band), reliability badge, overnight tag, split-journey legs, IRCTC link.
   - A "why this?" expander showing the score breakdown.
2. **Search form:** the same engine, without the LLM, for power users and cheap queries.
3. **Train page:** route map, per-stop delay distribution chart, monthly reliability trend.
4. **Ops dashboard** (admin): pipeline freshness, model metrics (MAE, coverage), LLM cost and latency.

## 11. Repository layout
```
PatriBot/
├── docs/                      # BRD, architecture, ADRs
├── collector/                 # standalone daily collector (GitHub Actions entrypoint)
├── packages/
│   ├── patribot_sources/      # source adapters (Protocol + implementations)
│   ├── patribot_planner/      # search, split journeys, ranking
│   ├── patribot_ml/           # features, training, inference, evaluation
│   └── patribot_agent/        # Claude agent, tools, RAG
├── pipelines/                 # Dagster definitions (assets, schedules, checks)
├── dbt/                       # dbt project (bronze→silver→gold)
├── api/                       # FastAPI service
├── web/                       # Next.js app
├── evals/                     # golden queries and eval runner
├── infra/                     # docker-compose, Dockerfiles, (later) Terraform
└── .github/workflows/         # CI + collector cron
```

## 12. Security and compliance
- API keys live only in env or secrets, never in the repo. Collector secrets go in GitHub Actions secrets.
- Provenance: every bronze file records its source, endpoint, retrieval timestamp and terms version.
- No user accounts in the MVP, so no PII. Chat logs are stored with anonymous session IDs and redacted free text.
- Rate limiting on public endpoints. A spend cap on LLM calls.
- No scraping of sites whose terms forbid it.

## 13. Delivery plan (refines BRD §12)

| Phase | Scope | Target |
|---|---|---|
| **0 — Foundations** *(start now)* | API provider spike → pick one. Repo scaffold (uv, Docker Compose, CI). **Collector live on GitHub Actions → R2.** Station clusters and corridor train list | Week 1 |
| **1 — Data platform** | Dagster + dbt bronze→silver→gold, data-quality checks, reverse ETL to Postgres, weather and calendar | Weeks 2–3 |
| **2 — Planner + API** | Direct search, overnight filter, split journeys, ranking with baseline ETA (B2) | Weeks 3–4 |
| **3 — Web app v1** | Next.js search form + results cards against `/plan` | Weeks 4–5 |
| **4 — Agent + RAG** | Claude tools, rules corpus, chat UI with streaming, eval suite | Weeks 5–6 |
| **5 — ETA model v1** | LightGBM quantile, nightly batch forecast, backtests, model card | Weeks 6–7 (needs ≥ 4–6 weeks of collected data) |
| **6 — Hardening** | Monitoring, drift, cost dashboard, README and demo video, benchmark report | Week 8 |

The planner ships first on **baseline** ETAs (historical averages) and is upgraded to the ML model once enough
history exists. This keeps the product usable while data builds up.

## 14. Architecture decision records (summary)

| ADR | Decision | Alternatives considered |
|---|---|---|
| ADR-1 | Dagster for orchestration | Airflow (heavier locally, task-centric), Prefect |
| ADR-2 | DuckDB warehouse + Postgres serving | Postgres-only (weaker for analytics), BigQuery (not local) |
| ADR-3 | dbt for transformations | Pandas/Polars scripts (no lineage or tests) |
| ADR-4 | LightGBM quantile regression | Deep sequence models (data-hungry), Prophet (per-series, doesn't pool) |
| ADR-5 | Claude tool-use agent + deterministic planner | LLM-only planning (hallucination risk), no LLM (loses natural-language UX) |
| ADR-6 | Local bge-m3 embeddings + pgvector hybrid | Hosted embeddings (cost), separate vector DB (extra ops) |
| ADR-7 | Collector on GitHub Actions + R2 | Laptop cron (gaps), paid VM (cost) |

## 15. Open questions

| # | Question |
|---|---|
| OQ-1 | **Does the ₹500/month include Claude API usage?** If yes, we need the Haiku 4.5 or Sonnet 5.5 tier plus strict caching and a low query volume. If no, Opus 5.5 is the default. See §9 |
| OQ-2 | Do you have (or can you create) a **GitHub Actions + Cloudflare R2** setup for the collector? Any free always-on alternative works |
| OQ-3 | Are the corridor picks OK (especially #4, Bengaluru ↔ Hyderabad, vs. Chennai ↔ Bengaluru or Mumbai ↔ Bengaluru)? |
| OQ-4 | Is the 8-week timeline realistic for your available hours per week? |
