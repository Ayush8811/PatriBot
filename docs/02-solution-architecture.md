# PatriBot — Solution Architecture

| Field | Value |
|---|---|
| Document | 02 — Solution Architecture |
| Status | **v0.2: round-2 decisions applied (D8–D11)** |
| Inputs | [01 — Business Requirements v0.3](01-business-requirements.md), decisions D1–D11 |
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
                │   └─ /chat ─► Claude: parse ─► planner ─► explain (low-cost path, §8)│
                │  Next.js web app  ◄── SSE streaming ──                                 │
                └────────────────────────────────────────────────────────────────────────┘
```

**Guiding principles**
1. **The LLM parses and explains, and the code computes.** Claude turns the request into a structured intent and explains the result.
   Train lists, times, predictions and rankings always come from deterministic code and data. The LLM never invents
   a train.
2. **Data sources are plug-ins.** Every external feed sits behind an adapter interface, so a buyer (D5) can swap in
   their own feed.
3. **Precompute what's predictable.** Forecast ETAs for every corridor train run over the booking window are computed
   nightly. Request-time work is mostly lookups plus the planner search.
4. **Local-first and cloud-portable.** Everything runs in Docker Compose. Every component has a managed-cloud
   equivalent (§10).

## 2. Is local-first OK? (D2, D9)

**Yes, it's the right choice for this phase.** It costs nothing, iterates fast, and if the stack is containerised and
storage paths are S3-compatible, moving to cloud later is a configuration change, not a rewrite.

**One exception: the data collector.** The ETA model's training history only builds up if we capture every
train run *every day*. A laptop that's asleep breaks that, and missed days can't be recovered (most APIs only give a
few days of past running status).

**Collector design (D9, D14, D15):** the workflow lives in the **private** `patribot-data` repo. This code repo is
public and RailKit data must not be published.

| Piece | Choice |
|---|---|
| Scheduler and runner | **GitHub Actions** in `patribot-data` (template in `infra/data-repo/`), every 3 hours. It checks out this repo's `main` and runs `patribot-collector run` |
| Raw storage | The same private repo: `raw/<source>/running_status/collected_date=<yyyy-mm-dd>/<hhmmss>Z.jsonl.gz` |
| Auth | The built-in `GITHUB_TOKEN` (no personal access token). The only secret is `RAIL_API_KEY` |
| Size | About 15–30k responses/month, ≈ 30–60 MB gzipped per month. Monthly compaction to Parquet if needed |
| Actions minutes | About 700–900 min/month, within the 2,000 free minutes for private repos |
| Monitoring | A failing run emails the owner. `state/usage/` tracks calls against budget. A `probe` workflow checks the provider |
| Swappable | Storage goes through `fsspec`, so moving to R2, S3 or GCS later changes only configuration |

The local stack runs `git pull` on `patribot-data` (a Dagster sensor) and processes new files from there.

## 3. MVP corridors (D4, D10)

### 3.1 Corridors
| # | Corridor | Cluster A | Cluster B | Main-line path(s) (to confirm in Phase 0) | Why |
|---|---|---|---|---|---|
| 1 | **Kolkata ↔ Delhi** | HWH, SDAH, KOAA, SRC, SHM | NDLS, DLI, NZM, ANVT, DEE | (a) Grand Chord: Asansol–Dhanbad–Gaya–DDU–Prayagraj–Kanpur. (b) Via Patna: Barddhaman–Jasidih–Kiul–Patna–Buxar–DDU. (c) Via Varanasi–Lucknow–Moradabad, for the trains that use it | Primary demo (Q1). Rajdhani, Duronto. Fog-prone |
| 2 | **Delhi ↔ Patna** | NDLS, DLI, ANVT, NZM | PNBE, RJPB, PPTA, DNR | Mostly a subset of 1(b) | Heavy delays and rush periods. **Almost no extra data cost**, because its trains are already in corridor 1 |
| 3 | **Mumbai ↔ Delhi** | CSMT, MMCT, BDTS, LTT, DR | NDLS, NZM, DLI | (a) Western: Surat–Vadodara–Ratlam–Kota–Mathura. (b) Central: Bhusaval–Itarsi–Bhopal–Jhansi–Agra | Different zones (Western/Central). Tests generalisation |
| 4 | **Bengaluru ↔ Hyderabad** | SBC, YPR, SMVB | SC, HYB, KCG | Dharmavaram–Anantapur–Guntakal–Kurnool–Mahbubnagar | Southern overnight corridor. Low fog. Contrast case |
| 5 | **Kolkata ↔ Chennai** | HWH, SHM, SRC, KOAA | MAS, MS, TBM | East Coast: Kharagpur–Balasore–Bhubaneswar–Visakhapatnam–Vijayawada–Gudur | Long (about 1,650 km) overnight-plus journeys. Cyclone and monsoon effects. Shares the Kolkata cluster with corridor 1 |

### 3.2 Which trains belong to a corridor (D10)
A corridor is a **path**: an ordered list of main-line segments between junctions, possibly with alternative
paths. A train belongs to the corridor in a given direction if **all** of the following are true:
1. It is a **reserved train**: Mail/Express, Superfast, Rajdhani, Shatabdi, Duronto, Vande Bharat, Humsafar,
   Garib Rath, etc. MEMU, DEMU, EMU, passenger and unreserved-only services are excluded (BRD §5.3).
2. Its stopping pattern covers **≥ 150 km** of the corridor path, or **≥ 2 consecutive corridor segments**, in the
   corridor's direction.
3. It can therefore start or end **anywhere** on the path or beyond it. For example, Patna → New Delhi,
   Dhanbad → New Delhi, Asansol → Kanpur and Howrah → Amritsar (passing through) are all members of corridor 1.

Membership is computed from the timetable by a dbt model, `dim_train_corridor`, and recomputed weekly. A train can
belong to several corridors (e.g. 1 and 2) but is **collected only once**, because one running-status call returns
every stop.

**Planner use:** split-journey legs are drawn from the corridor's member trains. **Model use:** delays are learned
per **segment** as well as per train, so intermediate-origin trains add training signal for the trunk route.

## 4. Data sourcing and budget (D1)

### 4.1 Source adapters
```python
class TimetableSource(Protocol):
    def list_trains_between(self, src: str, dst: str) -> list[TrainSummary]: ...
    def get_schedule(self, train_no: str) -> TrainSchedule: ...  # stops, times, day offsets, days of run


class RunningStatusSource(Protocol):
    def get_run(self, train_no: str, start_date: date) -> RunStatus: ...  # actual arr/dep per stop
```
Concrete adapters: `RapidApiRailAdapter`, `IndianRailApiAdapter` (both candidates), `OpenDataTimetableAdapter`
(open datasets), and later `PartnerAdapter` for a buyer's own feed.

### 4.2 Call budget (≤ ₹500/month ≈ $6)

The wider corridor definition (D10) increases the train count. **Rough estimate, to be replaced by real counts in
Phase 0:** about 500–700 distinct reserved trains across the 5 corridors after de-duplication.

| Pull | Frequency | Volume / month (est.) |
|---|---|---|
| Running status, **Tier A**: trains serving both end clusters, plus premium trains (Rajdhani, Duronto, Vande Bharat, Shatabdi) | Every run | ~250 trains × ~0.75 runs/day × 30 ≈ **5,600** |
| Running status, **Tier B**: other corridor member trains (intermediate origin or destination) | Every run if the budget allows, else **every 2nd run** | ~400 × 0.75 × 30 ≈ 9,000, or **~4,500 sampled** |
| Retries and gap fill | As needed | ~800 |
| Timetable refresh (corridor membership + schedules) | Weekly | ~2,800 |
| Live status for nowcast (on request, cached 5 min) | On demand | ~500 |
| **Total** | | **≈ 14,000–19,000 calls/month** |

**Budget control:** the collector reads a `max_calls_per_month` setting, spreads it evenly across the month, and
automatically switches Tier B to sampling when it is running ahead of budget. Sampled runs still give an unbiased
picture of each train's delay distribution, just with fewer data points.

**Phase 0 provider spike:** compare 2–3 providers on:
- (a) price at about 15–20k calls a month;
- (b) how many days back they return past running status (this limits backfill);
- (c) schema completeness (all stops, actual arrival and departure, cancellation and diversion flags);
- (d) terms of use permitting storage and derived models.

If no provider fits ₹500 at full volume, Tier B stays sampled.

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

### 8.1 AI chat request paths (cost-optimised for D8)

An open-ended agent loop costs roughly 5–10 times more per query than the budget allows (§9). Most queries therefore
take a **fixed, short pipeline**, and the agent loop is kept for the rare complex cases.

| Path | When | LLM calls | Quota |
|---|---|---|---|
| **A: Form search** | The structured search form | **0** (pure planner) | Free, unlimited |
| **B: AI plan** (default chat path) | Trip planning, train stats, ETA questions | **2**: (1) *parse*: query + short conversation summary → structured intent JSON, including `query_type`, via structured outputs. (2) *explain*: ranked itineraries JSON → a short explanation (≤ 120 words). The cards are rendered from JSON, not from the LLM | 1 call |
| **C: Rules Q&A** | `query_type = rules` | Parse + 1 answer call over the top-k retrieved chunks (RAG) | 1 call |
| **D: Agentic fallback** | Multi-step requests that B and C can't express (e.g. "compare these three options and find a split via a hub you choose") | Tool loop, **capped at 3 tool steps** | 1 call (paid tier only, or a free-tier daily limit of 1) |

**Calls 1 and 2 use the Anthropic Python SDK.** The model for each step is configurable
(`PATRIBOT_MODEL_PARSE`, `PATRIBOT_MODEL_EXPLAIN`, `PATRIBOT_MODEL_AGENT`), so cost and quality can be tuned per step
(see §9 and the open question on model choice). Each step also has a configurable effort level.

**Tools for path D (strict JSON schemas):**

| Tool | Purpose |
|---|---|
| `resolve_place(text)` | City or colloquial name → station cluster |
| `search_trains(origin, dest, dates, filters)` | Direct options with ETA predictions |
| `plan_itinerary(origin, dest, dates, constraints, allow_split)` | Ranked direct and split options |
| `predict_eta(train_no, run_date, stop?)` | Forecast or nowcast for a specific run |
| `train_performance(train_no, period)` | Historical delay stats and distributions |
| `search_knowledge(query)` | RAG over the rules and notices corpus, returning cited chunks |
| `live_status(train_no)` | Current position (cached, budget-limited) |

**Guardrails (all paths):**
- The prompts forbid stating any train number, time or rule that isn't in the provided data.
- A post-check rejects explanations that mention train numbers not in the itinerary JSON.
- Missing data → say so (FR-18).

**Cost controls:**
- **Prompt caching** on the stable system prompts and schemas.
- A **response cache** keyed by normalised intent + date, valid for 6 h. Repeat queries cost nothing and don't count against quota.
- Streaming to the web app over SSE.

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

## 9. LLM cost and unit economics (D3, D8)

**Constraints:**
- Claude spend ≤ **₹500/month** (about $5.9 at ₹85/$).
- The paid tier earns ₹100 for 50 queries, so a query must cost **well under ₹2** for the paid tier to break even.

**Current Anthropic list prices (USD per million tokens):**

| Model | Input | Output | Cache read |
|---|---|---|---|
| Claude Opus 5.5 | $4 | $20 | $0.20 |
| Claude Sonnet 5.5 | $2 | $10 | $0.20 |
| Claude Haiku 4.5 | $1 | $5 | ~$0.10 |

**Path B token estimate (to be measured in Phase 4):** about 5.5k input tokens (~3.5k of them cacheable system
prompts and schemas) and about 1k output tokens (including reasoning).

| Model for both steps | ≈ ₹ per AI query | Queries for ₹500 | LLM cost of one paid user (50 queries) | Paid-tier margin on ₹100 |
|---|---|---|---|---|
| Opus 5.5 | ~₹2.5 | ~200 | ~₹125 | **Negative** |
| Sonnet 5.5 | ~₹1.2–1.3 | ~400 | ~₹62 | ~₹35 |
| Haiku 4.5 | ~₹0.7–0.9 | ~600 | ~₹40 | ~₹58 |
| Haiku 4.5 parse + Sonnet 5.5 explain | ~₹1.0 | ~500 | ~₹50 | ~₹48 |

Margins are before payment-gateway fees (~2%) and any applicable taxes. Path D (agentic) costs about 3–5 times path B,
so it is capped and limited.

**Spend guard (FR-24):**
- Every LLM call logs its tokens and ₹ cost to `llm_usage`.
- The free-tier daily budget is (monthly free budget ÷ days in month). When it is used up, free AI chat pauses until midnight IST, and form search keeps working.
- Paid usage has its own monthly ceiling.
- An admin alert fires at 50 / 80 / 100 % of each budget.

**Chosen (D12, tentative):** Haiku 4.5 for parsing + Sonnet 5.5 for the explanation, ≈ ₹1.0 per query. To be re-checked against measured cost and quality in Phase 4.

## 10. Application layer and infrastructure

| Concern | Local (now) | Cloud (later) |
|---|---|---|
| API | FastAPI (uvicorn) in Docker | Cloud Run / ECS / Fly.io |
| Web | **Next.js (App Router) + TypeScript + Tailwind + shadcn/ui** | Vercel / Cloud Run |
| Auth | **Auth.js (NextAuth) with Google sign-in** (free). Phone OTP costs per SMS, so it comes later | Same |
| Payments | POC: coupon or manual activation of the paid plan. Then **Razorpay Subscriptions** + webhook → `subscriptions` table | Same |
| Ads | AdSense slots behind the `ADS_ENABLED` flag, off during the POC | Same |
| Orchestration | Dagster (webserver + daemon) | Dagster+ / VM |
| Warehouse | DuckDB file | MotherDuck / BigQuery |
| Object storage | Local FS ⇄ private `patribot-data` repo | R2 / S3 / GCS |
| Serving DB | Postgres + pgvector container | Neon / Supabase / Cloud SQL |
| ML tracking | MLflow container | Managed MLflow / same VM |
| Collector | GitHub Actions cron → `patribot-data` | Same |
| CI | GitHub Actions: ruff, mypy, pytest, dbt build on sample data, web lint and typecheck | Same, plus deploy |
| Secrets | `.env` (git-ignored) | Platform secret manager |

**App tables (Postgres):** `users`, `subscriptions` (plan, period, status), `usage_ledger` (user, timestamp, path,
counted call, response-cache hit), `llm_usage` (request id, model, tokens in, cached and out, ₹ cost), `chat_sessions`.

### 10.1 Web app screens (MVP)
0. **Sign-in and account:** Google sign-in, plan, quota used and quota remaining, upgrade button.
1. **Chat planner:**
   - Conversational input.
   - Streamed answer with **itinerary cards**: train, date, departure, scheduled vs. predicted arrival (P50–P90 band), reliability badge, overnight tag, split-journey legs, IRCTC link.
   - A "why this?" expander showing the score breakdown.
2. **Search form:** the same engine, without the LLM, for power users and cheap queries.
3. **Train page:** route map, per-stop delay distribution chart, monthly reliability trend.
4. **Ops dashboard** (admin): pipeline freshness, collector calls used vs. budget, model metrics (MAE, coverage), LLM spend vs. budget, and quota usage.

## 11. Repository layout
The code starts as a single Python package (`src/patribot/`) with subpackages. It is split into a uv workspace only
if build or deploy boundaries require it.
```
PatriBot/
├── docs/                      # BRD, architecture, phase notes
├── config/                    # corridors.yaml, watchlist.yaml (collector)
├── src/patribot/
│   ├── sources/               # source adapters (Protocol + implementations)        ✅ Phase 0
│   ├── collector/             # budgeted daily collector + CLI                      ✅ Phase 0
│   ├── planner/               # search, split journeys, ranking                     Phase 2
│   ├── ml/                    # features, training, inference, evaluation           Phase 5
│   └── agent/                 # Claude parse/explain, RAG                           Phase 4
├── pipelines/                 # Dagster definitions                                 Phase 1
├── dbt/                       # dbt project (bronze→silver→gold)                    Phase 1
├── api/                       # FastAPI service                                     Phase 2
├── web/                       # Next.js app                                         Phase 3
├── evals/                     # golden queries and eval runner                      Phase 4
├── infra/                     # data-repo workflows (✅ Phase 0), docker-compose (Phase 1)
├── tests/
└── .github/workflows/         # ci.yml                                              ✅ Phase 0
```

## 12. Security and compliance
- API keys live only in env or secrets, never in the repo. Collector secrets go in GitHub Actions secrets.
- Provenance: every bronze file records its source, endpoint, retrieval timestamp and terms version.
- Accounts store minimal PII (name, email). Follow India's DPDP Act 2023: a consent notice, a privacy policy, data deletion on request, and chat logs kept for at most 90 days.
- Payments go through Razorpay only. We never see or store card or UPI details. Webhook signatures are verified.
- Rate limiting on public endpoints. A spend cap on LLM calls.
- No scraping of sites whose terms forbid it.

## 13. Delivery plan (milestone-based, D11)

| Phase | Scope | Exit criteria |
|---|---|---|
| **0 — Foundations** ⏰ *urgent* | API provider spike → pick one. Station clusters and corridor paths. Collector on GitHub Actions → `patribot-data`. Repo scaffold (uv, Docker Compose, CI) | Collector has run green for 3 consecutive days |
| **1 — Data platform** | Dagster + dbt bronze→silver→gold, `dim_train_corridor`, data-quality checks, reverse ETL to Postgres, weather and calendar | Gold tables for all 5 corridors refresh daily, with quality checks passing |
| **2 — Planner + API** | Direct search, overnight filter, split journeys, ranking with baseline ETA (B2) | Q1–Q3 pass via `/plan` |
| **3 — Web app v1** | Next.js, Google sign-in, search form, result cards | Form search usable end to end |
| **4 — AI chat + RAG** | Paths B and C, quotas, spend guard, rules corpus, eval suite. **Measure real token cost per query** | Q1–Q6 pass. Measured cost per query fits the chosen model's budget |
| **5 — ETA model v1** | LightGBM quantile, nightly batch forecast, backtests, model card | Needs ≥ 4–6 weeks of collected data. Beats B2 on MAE |
| **6 — Monetisation + hardening** | Coupon or Razorpay subscription, path D (agentic), monitoring, drift, demo, benchmark report | Paid plan can be activated. Public demo |

Phases 1–4 run on **baseline** ETAs, and phase 5 swaps in the ML model. The product is usable while the history builds up.

## 14. Architecture decision records (summary)

| ADR | Decision | Alternatives considered |
|---|---|---|
| ADR-1 | Dagster for orchestration | Airflow (heavier locally, task-centric), Prefect |
| ADR-2 | DuckDB warehouse + Postgres serving | Postgres-only (weaker for analytics), BigQuery (not local) |
| ADR-3 | dbt for transformations | Pandas/Polars scripts (no lineage or tests) |
| ADR-4 | LightGBM quantile regression | Deep sequence models (data-hungry), Prophet (per-series, doesn't pool) |
| ADR-5 | Claude for parse + explain around a deterministic planner. Agent loop only as a capped fallback | Agent loop for every query (5–10× the cost), LLM-only planning (hallucination risk), no LLM (loses natural-language UX) |
| ADR-6 | Local bge-m3 embeddings + pgvector hybrid | Hosted embeddings (cost), separate vector DB (extra ops) |
| ADR-7 | Collector on GitHub Actions → private data repo | Laptop cron (gaps), R2 (new account), paid VM (cost) |
| ADR-8 | Corridors defined as paths, with segment-based train membership | Endpoint-to-endpoint train lists (miss split-journey legs and segment signal) |

## 15. Open questions

| # | Question | Status |
|---|---|---|
| OQ-1 | Does ₹500 include Claude? | ✅ Resolved: a separate ₹500/month for Claude (D8) |
| OQ-2 | Collector infrastructure | ✅ Resolved: GitHub Actions + private `patribot-data` repo (D9, D14) |
| OQ-3 | Corridors | ✅ Resolved: 5 corridors, path-based membership (D4, D10) |
| OQ-4 | Timeline | ✅ Resolved: milestone-based (D11) |
| OQ-5 | **Which Claude model(s) for parse and explain?** See the §9 table. Opus 5.5 gives a negative paid-tier margin at ₹100 per 50 queries. Sonnet 5.5, Haiku 4.5, or the Haiku + Sonnet mix all fit | ✅ Tentative: Haiku 4.5 parse + Sonnet 5.5 explain (D12). Re-check in Phase 4 |
| OQ-6 | Free-tier AI chat allowance | ✅ 3 per user per day (D13) |
| OQ-7 | Railway API provider: decided by the Phase 0 spike. Needs you to sign up and add the key as a GitHub secret | Open |
