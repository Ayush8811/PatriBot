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
goes, sets `lookback_days`, and starts collection.

## Current state: collection paused, waiting on a paid RailKit plan
- **The free tier can't be used.** The probe on 2026-10-04 got `HTTP 403 "Missing SDK signature headers. To use the API,
  please upgrade your plan."` for every date. Free accounts may only call through RailKit's official Node SDK, and
  REST access needs a paid plan. We don't emulate the SDK signature.
- `patribot-data` has the `collect` and `probe` workflows. Its `watchlist.yaml` (which overrides
  `config/watchlist.yaml`) has `trains: []`, so scheduled runs make no calls and send no failure emails.
- The probe can also be triggered by pushing `probe-request.txt` (line 1: train number, line 2: days back), because
  workflow dispatch isn't available to Claude's session.
- **To resume:** buy **Advance** (₹89, 10k/month, "API endpoint access", + optional 20k pack ₹159). **Pro (₹59) is
  "SDK access only"** like the free tier, so it would also return 403 to our REST client. Claude then re-runs the
  probe, sets `lookback_days`, and restores the train list and budget.

## Monitoring
- **A failed run sends you an email from GitHub.** The run fails on a bad key (401/403), an exhausted quota or rate limit
  (429; it stops immediately and the remaining runs wait for the next run), or when every call errors.
- `state/usage/<month>.json` shows API calls per day. The collector spreads `max_calls_per_month` evenly across the
  month.
- GitHub Actions minutes: private repos get 2,000 free minutes/month. The collector needs about 700–900.
