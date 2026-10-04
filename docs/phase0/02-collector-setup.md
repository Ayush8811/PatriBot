# Phase 0: Collector setup (owner steps)

The collector code and the GitHub Actions workflow (`.github/workflows/collector.yml`) are ready. It runs every
3 hours, collects train runs that have finished, and commits the raw responses to the private data repo. These
steps need your GitHub account and the API sign-up, so only you can do them. About 30 minutes in total.

## 1. RailKit key and plan (about 10 min). Provider decided: RailKit (D15)
1. Sign up at **railkit.in**, open the Dashboard, and generate an API key. The free tier (50 requests) is enough to probe.
2. On your machine:
   ```bash
   uv sync
   export RAIL_API_KEY=...            # never commit this
   uv run patribot-collector probe --source railkit --train 12301 --days-back 7
   ```
   This uses 8 requests. Each line shows one past date: `ok` = a completed journey history came back, `not_found` =
   none. **The oldest `ok` date = the past-date depth.** Set `collector.lookback_days` in `config/watchlist.yaml`
   to that number of days.
3. Open a file in `samples/` and check it has `data.stations[]` with scheduled/actual times and delays. Share it if
   it looks different, and the adapter will be adjusted.
4. Buy a plan:

   | Option | Cost/month | Requests | Set `max_calls_per_month` to |
   |---|---|---|---|
   | Advance only | ₹89 | 10,000 | `9000` (default). Tier-B trains get sampled |
   | **Advance + 20k request pack (recommended)** | ₹89 + ₹159 = **₹248** | 30,000 | `27000` |

   Request packs don't renew and expire with the subscription, so buy the pack again each month.
5. Rate limits: Advance allows 600 requests per 10 min. The collector spaces calls 1.1 s apart. On the Pro plan
   (200 per 10 min), set the Actions variable `RAIL_MIN_INTERVAL_S=3.1`.

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
| Secret | `RAIL_API_KEY` | the RailKit API key |
| Secret | `DATA_REPO_TOKEN` | the fine-grained token from step 2 |
| Variable | `DATA_REPO` | `ayush8811/patribot-data` |
| Variable | `RAIL_SOURCE` | `railkit`. Leave it unset to do a dry run with the offline `fixture` source first |

## 4. Turn it on
- Scheduled workflows only run from the **default branch**, so merge this branch into `main`.
- Actions tab → **collector** → *Run workflow* once by hand. Check that `patribot-data` gets a commit with
  `raw/…/*.jsonl.gz`, `state/manifest.jsonl` and `state/usage/<month>.json`.
- Phase 0 exit criterion: three consecutive days of green runs.

## What to watch
- **A failed run sends you an email from GitHub.** The run fails on a bad key (401/403), an exhausted quota or rate limit
  (429; it stops immediately and the remaining runs wait for the next run), or when every call errors.
- `state/usage/<month>.json` shows calls used per day. The collector spreads `max_calls_per_month` evenly across the
  month and never goes over it.
