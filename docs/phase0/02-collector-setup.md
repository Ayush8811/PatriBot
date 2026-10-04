# Phase 0: Collector setup (owner steps)

The collector code and the GitHub Actions workflow (`.github/workflows/collector.yml`) are ready. It runs every
3 hours, collects train runs that have finished, and commits the raw responses to the private data repo. These
steps need your GitHub account and the API sign-up, so only you can do them. About 30 minutes in total.

## 1. Pick the API provider (about 15 min)
1. Create a free **test account** at IndianRailAPI.com (the primary candidate, see `01-api-provider-spike.md`).
2. On your machine:
   ```bash
   uv sync
   export RAIL_API_KEY=...            # never commit this
   uv run patribot-collector probe --source indianrailapi --train 12301 --days-back 7
   ```
3. Read the output. Each line shows one past date and whether data came back. **The oldest date with
   `ok` = the past-date depth.** Set `collector.lookback_days` in `config/watchlist.yaml` to that number of days.
4. Open one of the files in `samples/` and check that it has every stop with scheduled and actual times. If not, share
   it, and the adapter will be adjusted.
5. Check the request cap on the paid plan and the data-storage clause in the terms. Save a copy of the terms in
   `docs/phase0/terms/`.
6. If everything checks out, upgrade to the paid plan (₹500/month).

## 2. Create the private data repo (about 5 min)
1. GitHub → **New repository** → name `patribot-data`, **Private**, tick "Add a README".
2. GitHub → Settings → Developer settings → **Fine-grained personal access tokens** → Generate:
   - Repository access: **only** `patribot-data`
   - Permissions: **Contents: Read and write**
   - Expiry: 1 year (set a calendar reminder to renew it)

## 3. Configure this repo (about 5 min)
In `patribot` → Settings → Secrets and variables → **Actions**:

| Kind | Name | Value |
|---|---|---|
| Secret | `RAIL_API_KEY` | the API key |
| Secret | `DATA_REPO_TOKEN` | the fine-grained token from step 2 |
| Variable | `DATA_REPO` | `ayush8811/patribot-data` |
| Variable | `RAIL_SOURCE` | `indianrailapi`. Leave it unset to do a dry run with the offline `fixture` source first |

## 4. Turn it on
- Scheduled workflows only run from the **default branch**, so merge this branch into `main`.
- Actions tab → **collector** → *Run workflow* once by hand. Check that `patribot-data` gets a commit with
  `raw/…/*.jsonl.gz`, `state/manifest.jsonl` and `state/usage/<month>.json`.
- Phase 0 exit criterion: three consecutive days of green runs.

## What to watch
- **A failed run sends you an email from GitHub.** The run fails when *every* API call errors, which usually means a bad
  or expired key or a provider outage.
- `state/usage/<month>.json` shows calls used per day. The collector spreads `max_calls_per_month` evenly across the
  month and never goes over it.
