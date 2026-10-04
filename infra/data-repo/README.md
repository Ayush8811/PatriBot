# patribot-data (private)

Raw railway data collected by [PatriBot](https://github.com/Ayush8811/PatriBot). **Do not make this repo public
or share its contents** (BRD D15).

- `raw/<source>/running_status/collected_date=YYYY-MM-DD/*.jsonl.gz`: raw provider responses
- `state/manifest.jsonl`: every fetch attempt · `state/usage/YYYY-MM.json`: API calls per day
- `probe/`: provider checks
- `watchlist.yaml`: the generated collector watchlist (corridor member trains) · `state/watchlist-report.json`: its
  counts and API usage · `state/timetable-cache/`: cached RailKit timetable responses

Workflows: `collect` (every 3 h), `watchlist` (weekly, or run it by hand) and `probe` (manual). The only setup is
the secret `RAIL_API_KEY`. `collect` uses `watchlist.yaml` here when it exists, else the seed in the code repo. To tune
the collector budget, edit the `collector:` block of `watchlist.yaml` here; rebuilds keep it.

Hosting: `Dockerfile` + `render.yaml` build and serve the API on Render from this private repo. `deploy` workflow
rebuilds it daily (needs the secret `RENDER_DEPLOY_HOOK`). See docs/deploy/render.md in the code repo.
