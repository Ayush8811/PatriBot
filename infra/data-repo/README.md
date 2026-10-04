# patribot-data (private)

Raw railway data collected by [PatriBot](https://github.com/Ayush8811/PatriBot). **Do not make this repo public
or share its contents** (BRD D15).

- `raw/<source>/running_status/collected_date=YYYY-MM-DD/*.jsonl.gz`: raw provider responses
- `state/manifest.jsonl`: every fetch attempt · `state/usage/YYYY-MM.json`: API calls per day
- `probe/`: provider checks

Workflows: `collect` (every 3 h) and `probe` (manual). The only setup is the secret `RAIL_API_KEY`.
