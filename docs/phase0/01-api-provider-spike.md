# Phase 0: Railway data API provider spike

| Field | Value |
|---|---|
| Status | **Desk research done. Hands-on verification needs owner sign-ups (see §4)** |
| Budget | ≤ ₹500/month (D1). Estimated need: **14–19k running-status calls/month** (architecture doc §4.2) |
| Date | 2026-10-04 |

> **Method note:** the research environment could not open the providers' websites directly (blocked by network
> policy), so the figures below come from search-engine snippets of their pricing and doc pages. Everything marked
> "verify" must be confirmed after sign-up, using the collector's `probe` command (§4).

## 1. Important context: there is no official public API
Indian Railways' NTES and IRCTC do **not** offer a public data API. Every option below is a **third-party**
provider. That has two consequences:
- **Reliability:** providers change endpoints or shut down. That is why the collector uses source adapters
  (architecture doc §4.1), so switching providers changes one class.
- **Provenance (D5):** each provider's terms must permit **storing responses and training models on them**. We keep
  the terms version with every bronze file. A future acquirer will have its own feed and plug it in through an
  adapter. Our sellable IP is the model, the planner and the pipeline, not the scraped history.

## 2. Candidates

| | **IndianRailAPI.com** | **RailRadar** | **RapidAPI marketplace "IRCTC" APIs** |
|---|---|---|---|
| Pricing found | **₹500 per full month** for an active (paid) account, pro-rated for the first month. Free test account for development | **Free sandbox: 1,000 requests/month.** Paid plan prices were not visible in search results | Varies by listing. Example: Pro **$5/mo for 10k requests**, Ultra **$10/mo for 30k** (on one IRCTC listing). Another listing: $4.01 / $11.99 / $49 tiers |
| Fits ₹500? | ✅ Exactly, *if* the request cap ≥ ~15k/month (**verify**) | ❓ Depends on paid tiers (**verify**) | ⚠️ 10k for ~₹425 fits, but **below** our full volume. 30k for ~₹850 is over budget |
| Live status with a date parameter | ✅ `livetrainstatus/.../trainnumber/<no>/date/<yyyymmdd>/` | ✅ Live train status endpoint | ✅ e.g. `getLiveTrainStatus` (irctc1) |
| **Past-date depth** (needed for backfill and catch-up) | ❓ **verify** | ❓ **verify** | ❓ **verify** (irctc1 has a "start day" parameter) |
| Other useful endpoints | Trains between stations, train route, station list, rescheduled trains | Station boards, **GeoJSON route geometry** (useful for corridor paths), timetables | Schedules, trains between stations, live station |
| Terms on storage and commercial use | ❓ Commercial plans exist (good sign). **Verify the data-storage clause** | ⚠️ Terms say its aim is **non-commercial** use by independent developers, and forbid scraping beyond API access. OK for the POC, but **risky for D5** | ❓ Each listing has its own terms. Usually unofficial wrappers. **Highest provenance risk** |
| Security note | API key goes **in the URL path**, over plain `http://` in the documented example. Use HTTPS if supported, and never log raw URLs (the collector redacts keys) | Key in a header (typical) | `X-RapidAPI-Key` header |

## 3. Recommendation

1. **Primary candidate: IndianRailAPI.com.** Its flat ₹500/month matches the budget exactly, it has commercial
   plans, and its endpoint shape is known. Start on the **free test account** to validate.
2. **Development and secondary: RailRadar free sandbox** (1,000 req/month). Use it to cross-check data quality, and
   possibly its route geometry for corridor paths. Don't build the long-term history on it unless its terms allow
   commercial derived use.
3. **Fallback: a RapidAPI listing at about $5/10k.** With 10k calls the collector runs Tier A in full and **samples
   Tier B** (architecture doc §4.2). The budget control handles this automatically.

**Decision rule:** pick the first candidate that passes all four checks in §4. If none passes at full volume, take the
cheapest one that passes checks 2–4 and let the collector sample Tier B.

## 4. Verification checklist (needs the owner, about 30 minutes)

| # | Check | How |
|---|---|---|
| 1 | Monthly request cap on the ₹500 plan (IndianRailAPI) or paid tiers (RailRadar) | Pricing page after sign-in, or email the provider |
| 2 | **Past-date depth**: how many days back running status is returned | `uv run patribot-collector probe --source <name> --train 12301 --days-back 7`. It reports which past dates return data |
| 3 | Schema completeness: all stops, scheduled + actual arrival/departure, delay, cancellation and diversion flags | Same probe. It saves sample responses to `samples/` for review |
| 4 | Terms allow storing responses and building derived models (including commercially) | Read the terms. Save a copy (date + URL) in `docs/phase0/terms/` |

**What the owner needs to do:**
- Create a free test account at IndianRailAPI.com, and optionally at RailRadar.
- Run the probe locally with the key in an env var, or share the probe output.
- Then add the chosen key as the GitHub Actions secret `RAIL_API_KEY`.

## Sources
- [IndianRailAPI: FAQ (pricing, account types)](https://indianrailapi.com/frequently-asked-question)
- [IndianRailAPI: Live train status endpoint](https://indianrailapi.com/api-collection/live-train-status)
- [RailRadar: API docs](https://railradar.in/docs) · [Pricing](https://railradar.in/pricing) · [Terms](https://railradar.in/terms)
- [RapidAPI: IRCTC (irctc1) pricing](https://rapidapi.com/IRCTCAPI/api/irctc1/pricing) · [IRCTC PNR status API pricing](https://rapidapi.com/amiteshgupta/api/irctc-indian-railway-pnr-status/pricing) · [Indian Railway IRCTC](https://rapidapi.com/rahilkhan224/api/indian-railway-irctc)
