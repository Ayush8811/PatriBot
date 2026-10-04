# Deploy: API on Render (free), built from the private data repo

The API image is built **from the private `patribot-data` repo**, so RailKit-derived data stays private (D15). Each
build clones this (public) code repo's `main`, builds the warehouse from the private repo's raw data and timetable
cache (bronze → silver → gold, about 1–2 min), and serves FastAPI. Only the web app's server-side proxy knows the API
key, and browsers never call the API directly (see [vercel.md](vercel.md)).

Files, all in the data repo (templates in `infra/data-repo/` here):
- `Dockerfile`, `.dockerignore`: the image.
- `render.yaml`: the Render Blueprint (free Docker web service, Singapore, health check `/api/v1/health`,
  auto-deploy off, generated `PATRIBOT_API_KEY`).
- `.github/workflows/deploy.yml`: triggers a Render deploy daily at 06:07 IST, or when `deploy-request.txt` is pushed.

## One-time setup (about 10 min)
1. Create a free account at render.com (sign in with GitHub) and give Render's GitHub app access to **`patribot-data`**.
2. Render dashboard → **New → Blueprint** → select `patribot-data` → Apply. Render creates `patribot-api` and builds it.
   The first build takes about 5 min.
3. Open the service:
   - **Environment** → copy the generated **`PATRIBOT_API_KEY`**. You will paste it into Vercel.
   - **Settings → Deploy Hook** → copy the URL.
   - Note the service URL, e.g. `https://patribot-api-xxxx.onrender.com`. This is Vercel's `PATRIBOT_API_URL`.
4. GitHub → `patribot-data` → Settings → Secrets and variables → Actions → New secret **`RENDER_DEPLOY_HOOK`** = the
   deploy hook URL.
5. Check: `https://<service>/api/v1/health` returns `{"status":"ok",...}`. Any other path returns 401 without the key.

## Free-tier behaviour
- The service **sleeps after about 15 min idle**. The first request after that takes about 30–60 s while it wakes;
  the web app shows "Waking up the server…".
- Data freshness: the daily rebuild serves everything collected up to 06:07 IST. To refresh sooner, push a change to
  `deploy-request.txt` in the data repo.
- Memory: about 160 MB in use after a full Kolkata→Delhi search, within the 512 MB free instance.
