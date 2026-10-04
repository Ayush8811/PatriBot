# Phase 0: Collector setup

**How it runs:** the collector workflow lives in the **private** repo `Ayush8811/patribot-data`, not in this public
repo, because RailKit data must not be published (D15). Every 3 hours it checks out this repo's `main`, collects
the train runs that have finished, and commits them to itself using GitHub's built-in token. No personal access
token is needed. The workflow files are kept in [`infra/data-repo/`](../../infra/data-repo).

## Owner steps (about 10 minutes; these are the only things that need a human)
1. **RailKit:** sign up at railkit.in → Dashboard → generate an API key. Buy a plan:

   | Option | Cost/month | Requests | `max_calls_per_month` in `config/watchlist.yaml` |
   |---|---|---|---|
   | Advance only | ₹89 | 10,000 | `9000` (current default). Tier-B trains get sampled |
   | **Advance + 20k request pack (recommended)** | **₹248** | 30,000 | `27000` |

   Request packs don't renew, so buy the pack again each month. The free tier (50 requests) is enough for the
   probe only.
2. **GitHub → New repository** → name `patribot-data`, **Private**, with no README. Claude can't create
   repositories from its session.
3. In `patribot-data` → Settings → Secrets and variables → Actions → **New repository secret**:
   `RAIL_API_KEY` = the RailKit key.

Then tell Claude. Claude pushes the workflows, runs the `probe` workflow to check how far back RailKit's history
goes, sets `lookback_days`, then runs the `watchlist` workflow, which generates the list of corridor trains to collect
(`watchlist.yaml` in the data repo, [details](../phase1/watchlist.md)) and refreshes it weekly, and starts
collection. Until the first watchlist exists, the collector uses the 7-train seed in `config/watchlist.yaml`.

## Current state: collecting on the RailKit Advance plan (₹89, 10k/month)
- The **free tier and Pro (₹59) are "SDK access only"**: REST calls return `403 "Missing SDK signature headers"`
  (probe on 2026-10-04). Advance includes REST endpoint access.
- **Probe on Advance (2026-10-04, train 12301):** journey history came back for the **last 6 days**. 7 days back and
  today (journey not yet finished) returned `404 "Train history record not found"`. The response matches the documented
  shape (`data.stations[]` with `distanceKm`, `arrival`/`departure` `scheduled`/`actual`/`delay`). So
  `lookback_days: 5`.
- The data repo's `watchlist.yaml` (which overrides `config/watchlist.yaml`) holds the 7 seed trains with
  `max_calls_per_month: 9000`. It will be replaced by the generated corridor watchlist.
- `collect` runs every 3 h, and also on any push that changes `watchlist.yaml` or `collect-request.txt`. `probe` runs on a push of
  `probe-request.txt` (line 1: train number, line 2: days back). Both are push-triggered because workflow dispatch isn't
  available to Claude's session.

## Monitoring
- **A failed run sends you an email from GitHub.** The run fails on a bad key (401/403), an exhausted quota or rate limit
  (429; it stops immediately and the remaining runs wait for the next run), or when every call errors.
- `state/usage/<month>.json` shows API calls per day. The collector spreads `max_calls_per_month` evenly across the
  month.
- GitHub Actions minutes: private repos get 2,000 free minutes/month. The collector needs about 700–900, the weekly
  watchlist rebuild about 30–60 (the first run up to 90).
- `state/watchlist-report.json` shows the watchlist's train counts per corridor and tier, its estimated collection
  calls per month, and the RailKit calls the rebuild used (about 1,500–2,000 a month, from the same quota).
