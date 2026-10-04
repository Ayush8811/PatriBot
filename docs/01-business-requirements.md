# PatriBot — Business Requirements Document (BRD)

| Field | Value |
|---|---|
| Document | 01 — Business Requirements |
| Status | **v0.3: review round 2 applied (D1–D15, see §13)** |
| Next documents | 02 — Solution Architecture, 03 — Data Design, 04 — ML (ETA) Design, 05 — RAG / Agent Design |
| Scope | Indian Railways (IR) passenger trains, reserved classes |

---

## 1. Problem statement

Planning a long-distance train trip in India is slow, fragmented and based on guesswork:

1. **The timetable is not reality.** Long-distance trains often arrive hours late, and the delay depends on
   the train, route, season and day. In Nov–Feb, fog in North India makes it much worse. The scheduled
   travel time that IRCTC and aggregators show is not the travel time a passenger will actually have.
2. **Search is rigid.** IRCTC answers "trains from A to B on date D". Real travellers ask questions like
   *"Find me a good overnight train from Kolkata to Delhi sometime between Nov 20–30, preferably one that
   actually gets in on time."* That takes several searches, several tabs and personal judgement.
3. **Sold-out routes need creative routing.** When direct trains are waitlisted, experienced travellers
   split the trip through a hub (e.g. Howrah → Patna → New Delhi) or use alternate terminals
   (Sealdah / Kolkata Chitpur, New Delhi / Old Delhi / Anand Vihar / Hazrat Nizamuddin). That knowledge lives in
   people's heads and forum posts, not in any tool.
4. **Waitlist uncertainty.** Passengers can't tell whether "GNWL 45" will be confirmed, so they over-book or
   give up.

**PatriBot** is an AI travel planner for Indian Railways. It combines:

- a **data platform** that collects timetables and historical running-status data,
- an **ML model** that predicts *realistic* arrival times (ETA) and delay risk per train, route segment and date,
- a **RAG + agent layer** that understands natural-language trip requests, searches the options (direct trains,
  alternate stations and break/split journeys), ranks them with the ETA model and explains the recommendation
  with sources.

## 2. Business objectives

| # | Objective | How we'll know |
|---|---|---|
| BO-1 | Cut trip-planning time for flexible, multi-day searches | A 10-day window query answered in < 15 s, compared with ~20+ min of manual searching |
| BO-2 | Give travellers realistic arrival expectations | ETA MAE beats the "scheduled time" baseline by ≥ 40 % on held-out data |
| BO-3 | Find options that users would miss | ≥ 20 % of recommended itineraries on busy routes use an alternate station or a split journey |
| BO-4 | Build trust through transparency | Every recommendation shows a delay-risk band and cites its sources (timetable, historical stats, rules) |
| BO-5 | Portfolio and real-world value | A working end-to-end system: ingestion → lakehouse → model → API → chat UI, with monitoring |

## 3. Stakeholders and personas

| Persona | Description | Primary need |
|---|---|---|
| **P1 — Flexible leisure traveller** | Visiting family or on holiday; dates flexible within a week or two | "Best train in this window": overnight, comfortable, reliable |
| **P2 — Time-critical traveller** | Has an interview, exam, wedding or connecting flight | "Which train will *actually* get me there before 10 AM?" (P90 arrival) |
| **P3 — Budget / sold-out traveller** | Direct trains are waitlisted | Split journeys, alternate terminals, waitlist confirmation odds |
| **P4 — Pickup / logistics** | Family member picking someone up, or a cab or hotel operator | Live and predicted arrival of a specific train |
| **Project owner (you)** | Builds and runs the platform | Low cost, legally clean data sourcing, demo-able, extensible |

## 4. Example user queries (acceptance scenarios)

These are the "golden" queries. The finished system must handle them end to end.

| ID | Query | Expected behaviour |
|---|---|---|
| Q1 | *"Suitable train from Kolkata to Delhi, Nov 20–30, overnight preferred, least travel time."* | Resolve city → station clusters (HWH, SDAH, KOAA → NDLS, DLI, ANVT, NZM). Enumerate trains per date. Filter for overnight. Rank by **predicted** travel time and reliability. Show the top N with date, class, predicted arrival (P50/P90) and why each was chosen. |
| Q2 | *"I must reach New Delhi by 9 AM on Nov 25. What should I take from Howrah?"* | Constraint solving on **P90** predicted arrival, not the timetable |
| Q3 | *"All direct trains are full on Nov 22. Plan a break journey."* | Search 2-leg itineraries via hubs (e.g. Patna, Prayagraj, Kanpur, Dhanbad) with a safe connection buffer that accounts for the predicted delay of leg 1 |
| Q4 | *"How late does 12301 Rajdhani usually run in late November?"* | Answer from historical stats, with a delay distribution, by station |
| Q5 | *"Can I break my journey on a Rajdhani ticket?"* | RAG answer from IR rules documents, with a citation |
| Q6 | *"Where is 12273 right now and when will it reach Kanpur?"* | Live position (if a live source is available) plus a model-adjusted ETA for downstream stations |

## 5. Scope

### 5.1 In scope (MVP)

- **Geography:** **5 MVP corridors**: Kolkata ↔ Delhi (primary), Delhi ↔ Patna, Mumbai ↔ Delhi,
  Bengaluru ↔ Hyderabad, Kolkata ↔ Chennai. Design must scale to all-India.
- **What a corridor includes (D10):** a corridor is **not** just the trains between its two end cities. It
  covers **every reserved train that runs along the corridor's main-line path**, including trains that start or
  end at intermediate stations (e.g. Patna → Delhi, Asansol → Kanpur and Dhanbad → New Delhi all belong to
  Kolkata ↔ Delhi). This is needed for split-journey planning (leg 1 and leg 2 are often such trains) and lets the
  ETA model learn delays segment by segment. The exact rule is in the solution architecture doc, §3.
- **Train search:** station and city resolution, direct trains, date-range search, filters (overnight,
  departure/arrival windows, class, train type such as Rajdhani, Duronto or Vande Bharat Sleeper).
- **ETA and delay prediction:** per train × station × date, predicted delay distribution (P50, P90), and
  an on-time reliability score.
- **Ranking:** a multi-objective score combining predicted travel time, reliability, user preferences
  (overnight, arrival window) and, optionally, fare.
- **Break and split journeys:** 2-leg itineraries through hub stations with minimum and maximum layovers that
  allow for predicted delays.
- **RAG knowledge base:** IR rules (break journey, refunds, quotas, Tatkal, ARP), train and route facts,
  and historical performance summaries.
- **Conversational interface:** a chat UI and a REST API.
- **Explainability:** every recommendation has a short rationale and source citations.
- **Accounts and plans (D8):** sign-in, a **free tier** (unlimited form search plus a small daily allowance of
  AI chat queries) and a **paid tier at ₹100/month for up to 50 AI chat queries**. Payment collection may
  come after the POC, but usage metering and quotas are built from the start.

### 5.2 Phase 2 (post-MVP)

- Waitlist **confirmation-probability** model (WL/RAC → CNF). *Deferred by decision D6.*
- Live seat availability and fare lookup through a licensed or partner API.
- Alerts, e.g. "notify me if 12301's predicted delay at NDLS goes above 2 h".
- Multi-modal fallback (flight or bus suggestions when every rail option is poor).
- Hindi and Bengali queries.

### 5.3 Out of scope

- **Ticket booking.** We deep-link to IRCTC only. We never handle IRCTC credentials. Our only payment is the
  ₹100/month subscription, through a payment gateway (we never store card or UPI details).
- Unreserved or general-class and suburban/local trains.
- Freight.

## 6. Functional requirements

### 6.1 Query understanding
| ID | Requirement | Priority |
|---|---|---|
| FR-1 | Parse natural-language queries into a structured intent: origin, destination, date or date range, time windows, preferences (overnight, fastest, most reliable, cheapest), class, passenger count, hard vs. soft constraints | Must |
| FR-2 | Resolve cities and colloquial names (e.g. "Kolkata", "Delhi", "Bombay") to **station clusters**, and allow single-station override | Must |
| FR-3 | Ask a clarifying question when a query is ambiguous (e.g. no date given) instead of guessing | Should |
| FR-4 | Keep context across turns ("what about 3AC instead?") | Should |

### 6.2 Search and itinerary planning
| ID | Requirement | Priority |
|---|---|---|
| FR-5 | List direct trains between station clusters for every date in a range, respecting days of operation | Must |
| FR-6 | **Overnight** classification: departure in a configurable evening window (default 16:00–23:59) and arrival in a morning window (default 04:00–11:00) after ≥ 1 night | Must |
| FR-7 | **Break / split journeys:** generate 2-leg (Phase 2: 3-leg) itineraries via hub stations. Minimum connection buffer = f(predicted P90 delay of leg 1) and maximum layover is configurable | Must |
| FR-8 | Distinguish an **official break journey** (one ticket, IR break-journey rules apply) from a **split itinerary** (separate tickets), and warn about each one's risks (e.g. a missed connection on separate tickets gets no refund protection) | Must |
| FR-9 | Rank itineraries with an explainable multi-objective score. Show the top N with the trade-offs | Must |

### 6.3 ETA and delay intelligence
| ID | Requirement | Priority |
|---|---|---|
| FR-10 | Predict delay at each scheduled station for a train run on a future date (forecast mode) | Must |
| FR-11 | Re-predict downstream delays from the current live position (nowcast mode) when live data is available | Should |
| FR-12 | Report the **uncertainty** (P50 and P90 arrival), not just a point estimate | Must |
| FR-13 | Compute a per-train and per-segment **reliability score** (e.g. % of runs arriving within 30 min of schedule, by month) | Must |
| FR-14 | Use seasonal and contextual signals: month, fog season, festivals and rush periods, day of week, route congestion, upstream delay, and weather where available | Must |

### 6.4 Knowledge (RAG)
| ID | Requirement | Priority |
|---|---|---|
| FR-15 | Answer rules and policy questions (break journey, refund/TDR, Tatkal, quotas, ARP, luggage) from an indexed corpus of official IR documents, with citations | Must |
| FR-16 | Answer train-fact questions (route, stops, rake type, pantry, classes) from structured data, not from free text | Must |
| FR-17 | Answer historical-performance questions from aggregated statistics (gold tables), not raw text | Must |
| FR-18 | Do not hallucinate. If the data isn't there, say so | Must |

### 6.5 Interfaces
| ID | Requirement | Priority |
|---|---|---|
| FR-19 | A proper web app (not Streamlit), with a chat UI and itinerary cards (train, date, departure, scheduled vs. predicted arrival, reliability badge, IRCTC deep link) | Must |
| FR-20 | A REST API: `/search`, `/plan`, `/predict-eta`, `/chat` | Must |
| FR-21 | An admin and observability dashboard covering pipeline freshness, model metrics, query logs and **LLM spend** | Should |
| FR-22 | Sign-in (Google or phone OTP) and a user profile with plan, quota used and quota remaining | Must |
| FR-23 | **Quota metering:** each AI chat query counts as 1 "call". Free tier: N calls per day (default 3). Paid: 50 calls per month. The structured search form never uses quota | Must |
| FR-24 | A **global LLM spend guard**: free-tier AI chat pauses for the day (form search keeps working) once the day's share of the monthly budget is used up | Must |
| FR-25 | Paid-plan subscription through a payment gateway (e.g. Razorpay), with webhooks updating the plan | Should (POC: manual or coupon-based activation is acceptable) |
| FR-26 | Ad slots (e.g. Google AdSense) on search and result pages, behind a feature flag and off during the POC | Could |

## 7. Data requirements

| Dataset | Content | Refresh | Candidate sources (to validate in Solutioning) |
|---|---|---|---|
| **Stations master** | Code, name, city, state, zone, lat/long | Monthly | Open datasets (e.g. datameet railways), IR publications |
| **Train master and timetable** | Train no., name, type, days of run, stop sequence, scheduled arr/dep, distance, classes | Weekly + on timetable change | Open datasets, IR timetable PDFs, licensed APIs |
| **Historical running status** ⭐ | Actual arr/dep per station per run date | Daily (backfill as far back as possible) | Licensed API or permitted sources. **This is the core training data.** |
| **Live running status** | Current position and delay | Every 5–15 min, for tracked trains only | Licensed API (optional, Phase 2) |
| **Calendar and events** | Holidays, festivals (Diwali, Chhath, etc.), exam dates, rush periods | Yearly + ad hoc | Public calendars |
| **Weather** | Fog, visibility, rain and temperature along the route | Daily, plus a forecast for future dates | Open-Meteo / IMD |
| **Infrastructure context** | Track blocks, diversions, cancellations, new rakes | Daily | IR notices, news (RAG) |
| **Rules corpus** | Break journey, refund, Tatkal, quotas, ARP | On change | Official IR / IRCTC documents |
| **Availability and fare** (Phase 2) | Seat availability and fares by class and quota | On demand | Licensed API only |

**Data-quality requirements:** dedupe of run records, timezone consistency (IST), correct handling of
multi-day runs (day 1/2/3 offsets), detection of cancellations and diversions (excluded from delay training
or labelled as such), and outlier handling.

## 8. Non-functional requirements

| ID | Category | Requirement |
|---|---|---|
| NFR-1 | Latency | Single-date search < 3 s P95. 10-day planning query < 15 s P95. Chat first token < 2 s |
| NFR-2 | Freshness | Timetable ≤ 7 days old. Historical delays loaded by T+1. Live data ≤ 15 min old (when enabled) |
| NFR-3 | Accuracy | ETA MAE (final destination, forecast mode) ≥ 40 % better than the scheduled-time baseline. P90 coverage within 85–95 % |
| NFR-4 | Reliability | Pipelines are idempotent and re-runnable, with backfill support. API uptime 99 % (best effort) |
| NFR-5 | Cost | Data API spend ≤ **₹500/month**. **Claude API spend ≤ ₹500/month** in the POC. Runs local-first on Docker; cloud deployment comes later. **The LLM cost of an AI chat query must stay well under ₹2** (₹100 ÷ 50 calls), so the paid tier at least breaks even. See the solution architecture doc, §9 |
| NFR-6 | Compliance | Use only data sources whose terms allow it. Respect robots.txt and rate limits. Store only the PII that accounts need (name, email or phone) and follow India's **DPDP Act 2023** (consent, privacy policy, deletion on request). Keep a **provenance record for every dataset**, which a future acquirer's IP due diligence will need |
| NFR-7 | Explainability | Every ranking factor is visible to the user. Model feature importances are documented |
| NFR-8 | Observability | Data-quality checks, pipeline run logs, model drift monitoring, and LLM traces (prompt, tools, latency, cost) |
| NFR-9 | Reproducibility | Versioned data snapshots, models and prompts. Infrastructure as code. One-command local setup |

## 9. Success metrics (KPIs)

| Area | KPI | MVP target |
|---|---|---|
| Model | MAE / RMSE of arrival delay at destination (forecast mode) | ≥ 40 % better than baseline |
| Model | P90 interval coverage | 85–95 % |
| Model | On-time vs. late classification (> 60 min late), AUC | ≥ 0.80 |
| Planner | Golden-query pass rate (Q1–Q6 plus ~50 curated queries) | ≥ 90 % |
| RAG | Answer faithfulness / citation correctness (LLM-judge + manual check) | ≥ 95 % |
| Data | Pipeline success rate, freshness SLA hit rate | ≥ 98 % |
| Product | Median time to a useful answer | < 15 s |

## 10. Assumptions

- A legally usable source of **historical running-status data** exists, or a usable history can be built up
  over several months by collecting daily snapshots. Without it there is no ETA model. This is the
  **#1 dependency**.
- Timetable data from open or official sources is good enough for search. It is cross-checked against a
  second source.
- Advance Reservation Period is currently **60 days** (to be re-verified), so date-range queries further out than that
  are "plan only, not yet bookable" and should be flagged.
- Users book on IRCTC themselves. PatriBot is advisory only.

## 11. Constraints and risks

| Risk | Impact | Mitigation |
|---|---|---|
| No official public API for NTES / IRCTC. Scraping may breach terms | High | Prefer licensed or aggregator APIs and open datasets. Keep source adapters pluggable. Document the provenance of every dataset |
| Not enough history for the ETA model | High | Start collecting daily snapshots on day 1. Use a hierarchical / pooled model (route- and segment-level priors) for sparse trains. Fall back to historical-average baselines |
| Disruptions (fog, accidents, diversions) are rare, high-impact events | Medium | Predict a distribution rather than a point. Show P90. Add a "disruption notices" RAG feed |
| LLM hallucinating trains or rules | High | LLM never invents trains: all train facts come from tool calls to structured data. Grounded RAG with citations. Eval suite |
| Timetable changes (new trains, renumbering) | Medium | Weekly refresh, SCD-2 history on the train master, alerting on schema or volume drift |
| Cost creep (LLM, cloud) | Medium | Caching, small models for parsing, budget alerts |
| Split-journey advice causes missed connections | Medium | Conservative buffers (P90+), explicit risk warnings, no auto-booking |

## 12. Release plan (proposed)

The phases are **milestone-based, not calendar-based** (D11). Each phase is done when its exit criteria are met.

| Phase | Deliverable | Exit criteria |
|---|---|---|
| **0 — Foundations** | Repo, docs, source evaluation, start of the daily data collection job | Data sources confirmed. History collection running daily. **This is the only phase with a hard deadline: start as soon as possible, because every day without collection is lost training data** |
| **1 — Data platform** | Ingestion → bronze/silver/gold, station and train masters, timetable, historical runs, quality checks, orchestration | Gold tables for the Kolkata ↔ Delhi corridor with ≥ 3 months of history (or a backfill) |
| **2 — ETA model v1** | Baselines, then a gradient-boosted / quantile model, served via API, with an evaluation report | KPIs in §9 met on the corridor |
| **3 — Search and planner** | Direct and split itinerary engine, ranking, `/search` and `/plan` APIs | Q1–Q3 pass |
| **4 — RAG and agent** | Rules corpus, vector index, tool-calling agent, chat UI | Q1–Q6 pass. Eval suite ≥ 90 % |
| **5 — Ops and hardening** | Monitoring, drift detection, CI/CD, deployment, demo | Public demo plus write-up |
| **6 — Phase 2 features** | WL-confirmation model, live nowcast, alerts, more corridors | — |

## 13. Decisions log

| # | Question | Decision | Consequence |
|---|---|---|---|
| D1 | Data sourcing | Paid API is allowed, **≤ ₹500/month** | Use a freemium/paid railway API for timetables and running status, plus open data. Call volume must fit the budget (see the solution architecture doc, §4) |
| D2 | Stack | **Local-first**, cloud later | Docker Compose. Storage and compute stay cloud-portable (S3-compatible paths, dbt, containers). The daily data collector is the one exception: it must run every day, so it gets a tiny always-on runner |
| D3 | LLM | **Claude** (Anthropic API) | Tool-use agent through the Anthropic Python SDK. Embeddings come from a local open-source model, since Anthropic has no embeddings endpoint |
| D4 | MVP corridors | **5 corridors** (revised in round 2) | Kolkata ↔ Delhi, Delhi ↔ Patna, Mumbai ↔ Delhi, Bengaluru ↔ Hyderabad, **Kolkata ↔ Chennai** |
| D5 | Audience | Portfolio now. **Long term, sell to ConfirmTkt / ixigo-class companies** | API-first and B2B-ready. Data sources sit behind adapters so a buyer can plug in their own data. Measurable accuracy benchmarks. Clean data provenance (see §15) |
| D6 | Waitlist-confirmation model | **Not now** | Moved to the backlog |
| D7 | UI | **Proper web app** | Next.js + TypeScript frontend calling a FastAPI backend |
| D8 | LLM budget and monetisation | **Claude spend ≤ ₹500/month** in the POC. Free tier plus **₹100/month for 50 AI chat queries**. Google ads later if it takes off | Low-cost AI pipeline instead of an open-ended agent loop for most queries (solution architecture doc, §8–9). Accounts, quotas and a spend guard are now in scope (FR-22–26) |
| D9 | Always-on collector infra | No GitHub Actions + Cloudflare R2 setup yet | Collector runs on the GitHub account the project already uses (Actions is included with it), storing raw files in a **separate private GitHub repo**. No new accounts needed. Storage stays swappable to S3/R2 later (solution architecture doc, §2) |
| D10 | Corridor definition | A corridor = **every train along the path between the two clusters**, including trains that start or end at intermediate stations | More trains per corridor. The data-API budget is managed through train-type filters and sampling (solution architecture doc, §4) |
| D11 | Timeline | "Depends" on available time | Phases are milestone-based. Only the collector start date is urgent |
| D12 | Claude models (OQ-5) | **Haiku 4.5 for parsing + Sonnet 5.5 for the explanation** (tentative, "maybe") | `PATRIBOT_MODEL_PARSE=claude-haiku-4-5`, `PATRIBOT_MODEL_EXPLAIN=claude-sonnet-5-5`. Re-check against measured token cost and quality in Phase 4 |
| D13 | Free-tier allowance (OQ-6) | **3 AI chat queries per user per day** | `FREE_DAILY_AI_QUERIES=3` |
| D15 | Railway data provider | **RailKit** (`api.railkit.in`), with its terms knowingly set aside **for the POC only** | RailKit's terms forbid historical datasets and long-term retention. Accepted risks: the key could be revoked, and the collected history **cannot be used commercially or shown to a buyer** (D5). Mitigations: the data stays in the private repo and is never redistributed; rows are tagged `source=railkit`; history must be **re-sourced from a provider that licenses it** before any commercial use or sale. Rate limits are respected |
| D14 | Raw data storage (OQ-2) | Private `patribot-data` repo approved | Collector writes there |

## 14. Glossary

| Term | Meaning |
|---|---|
| ETA | Estimated time of arrival. Here, model-predicted actual arrival |
| NTES | National Train Enquiry System (IR's running-status system) |
| ARP | Advance Reservation Period |
| WL / RAC / CNF | Waitlisted / Reservation Against Cancellation / Confirmed |
| Break journey | IR provision for breaking a single-ticket journey at an intermediate station, subject to rules |
| Split itinerary | Two or more separate tickets via an intermediate hub |
| Station cluster | All major stations serving a city (e.g. Delhi = NDLS, DLI, NZM, ANVT, DEE) |
| P50 / P90 | Median and 90th-percentile predicted arrival time |
| Bronze / Silver / Gold | Raw / cleaned / business-ready data layers (medallion architecture) |

## 15. Commercial positioning (long-term, from D5)

**Likely buyers or partners:** ixigo (which owns ConfirmTkt and its trains business), RailYatri, MakeMyTrip/Goibibo,
Paytm Travel, and IRCTC-authorised agents.

**They already have:** booking flows, very large user bases, and their own running-status and PNR data.
**What they would value from PatriBot:**
1. **Proven ETA accuracy:** a published benchmark, per corridor, against "scheduled time" and against
   naive historical averages.
2. **An itinerary intelligence engine:** split and break journeys plus alternate-station planning that accounts for delay risk.
   Booking apps don't do this well today.
3. **A natural-language planning layer** on top of their existing inventory.
4. **Easy integration:** a clean REST API, source adapters for *their* data, and a containerised deployment.
5. **Clean IP:** no scraped or terms-violating data in the training history, with documented provenance.

The architecture therefore treats **data sources as replaceable plug-ins** and the **models plus the planner as the
product**.
