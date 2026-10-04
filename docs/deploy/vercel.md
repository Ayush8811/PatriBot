# Deploy the web app on Vercel

The Next.js app in `web/` is hosted on Vercel. It is public on the internet, but only the owner can sign in, and the
browser never talks to the FastAPI backend: the app's server-side proxy does, with a shared key. How it works:
[docs/phase3/web-app.md → Auth & proxy](../phase3/web-app.md#auth--proxy).

## Before you start

- The API is deployed and reachable over HTTPS (e.g. `https://patribot-api.onrender.com`), with `PATRIBOT_API_KEY`
  set on the API side. Pick the key now: `openssl rand -base64 32`.
- Node 22 locally, to generate the password hash.

## 1. Generate the secrets (on your machine)

```bash
cd web
npm ci
npm run hash-password          # type the password twice (hidden); prints one line: scrypt$32768$8$1$…$…
openssl rand -base64 48        # PATRIBOT_SESSION_SECRET (≥ 32 chars)
```

Use a long random password (a password manager's 20+ characters, or a 5–6 word passphrase). Paste the hash line
into Vercel **exactly as printed** (with its `$` signs). Only for a local `.env.local` must every `$` be escaped as
`\$`; the script prints that form too.

## 2. Import the project

1. Go to <https://vercel.com/new> and sign in with GitHub.
2. **Import Git Repository** → `Ayush8811/PatriBot` (grant the Vercel GitHub app access to it if it is not listed).
3. **Root Directory:** `web` (click *Edit* and pick the folder).
4. **Framework Preset:** Next.js (detected). Leave the build and install commands at their defaults
   (`npm install` / `next build`; `package-lock.json` is used). Node.js version: 22.x (Project → Settings → General).

## 3. Environment variables

In the import screen (or later in Project → Settings → Environment Variables) add, for **Production** (and
**Preview** if you use preview deployments):

| Name | Value |
|---|---|
| `PATRIBOT_AUTH_USER` | your username, e.g. `ayush` |
| `PATRIBOT_AUTH_PASSWORD_HASH` | the `scrypt$…` line from step 1 |
| `PATRIBOT_SESSION_SECRET` | the `openssl rand -base64 48` output |
| `PATRIBOT_API_URL` | the API base URL **without** `/api/v1`, e.g. `https://patribot-api.onrender.com` |
| `PATRIBOT_API_KEY` | the same key as `PATRIBOT_API_KEY` on the API |

Do **not** set:
- `NEXT_PUBLIC_API_MOCK`: it must be unset (or `0`), otherwise the site serves demo fixtures.
- `NEXT_PUBLIC_API_BASE_URL`: unset, so the browser uses the same-origin `/api/proxy`.
- `PATRIBOT_AUTH_DISABLED`: never on Vercel. (A real production build ignores it anyway.)

None of these may start with `NEXT_PUBLIC_`: that prefix puts a value into the public JavaScript bundle. The
sensitive ones can be marked **Sensitive** in Vercel.

## 4. Deploy and check

Click **Deploy**. When it is live:

1. Open the site: you land on `/login`. (If it says *Sign-in is not configured*, an auth variable is missing or
   malformed; fix it and **Redeploy**.)
2. Sign in. The header shows your username and **Log out**.
3. Run a search. The first request after the API has been idle can take 30–60 s while the free API host wakes up;
   the page shows "Waking up the server…" meanwhile. A 502 saying the API *rejected this app's key* means the two
   `PATRIBOT_API_KEY` values differ.
4. Unauthenticated API calls are refused: `curl -i https://<your-app>.vercel.app/api/proxy/health` → `401`.

Environment variable changes apply to new deployments only: after editing one, use Deployments → ⋯ → **Redeploy**.

## Notes

- **Function duration:** the proxy route sets `maxDuration = 120` s so it can wait up to 90 s for a cold API. That
  is within Vercel's limits with Fluid compute (the default for new projects, up to 300 s on Hobby). If a deploy
  complains about the duration, enable Fluid compute (Project → Settings → Functions) or lower `maxDuration` in
  `web/app/api/proxy/[...path]/route.ts`.
- **Sign everyone out / rotate:** change `PATRIBOT_SESSION_SECRET` and redeploy. To change the password, generate a
  new hash and redeploy.
- **Brute-force limiter** is per serverless instance (best effort). The long password and scrypt are the real
  protection.
- **Custom domain:** Project → Settings → Domains. Cookies are host-only, so nothing else changes.
- Pushes to `main` redeploy production automatically. Every other branch gets a preview URL. Previews need the
  same variables in the *Preview* environment, otherwise they stay locked (fail closed).
