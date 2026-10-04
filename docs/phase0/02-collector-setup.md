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

## Current state (free tier)
- `patribot-data` is set up with the `collect` and `probe` workflows and a **free-tier `watchlist.yaml`**: 1 train
  (12301) and `max_calls_per_month: 40`. A `watchlist.yaml` at the data-repo root overrides `config/watchlist.yaml`.
- The probe can also be triggered by pushing `probe-request.txt` (line 1: train number, line 2: days back), because
  workflow dispatch isn't available to Claude's session.
- **To scale up:** buy the Advance plan (+ request pack), then replace the data-repo `watchlist.yaml` with the
  generated one and raise `max_calls_per_month`.

## Monitoring
- **A failed run sends you an email from GitHub.** The run fails on a bad key (401/403), an exhausted quota or rate limit
  (429; it stops immediately and the remaining runs wait for the next run), or when every call errors.
- `state/usage/<month>.json` shows API calls per day. The collector spreads `max_calls_per_month` evenly across the
  month.
- GitHub Actions minutes: private repos get 2,000 free minutes/month. The collector needs about 700–900.
- On RailKit's Pro plan (200 requests per 10 min), add the Actions variable `RAIL_MIN_INTERVAL_S=3.1` in `patribot-data`.
