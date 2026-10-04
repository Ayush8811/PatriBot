# Phase 3: Web app (Next.js)

The PatriBot web app lives in `web/`. It is a Next.js 16 (App Router) + TypeScript + Tailwind v4 + shadcn/ui front
end for the FastAPI backend. It follows decision D7 (a proper web app) and the screens in the solution architecture
§10.1. It is built only against the API contract [`docs/api/v1.md`](../api/v1.md) and never imports backend code. A
fixtures **mock mode** makes it fully demoable without the backend.

## Run it locally

Requirements: Node 22 and npm.

```bash
cd web
npm ci

# 1) Mock mode: no backend. Fixtures cover Kolkata → Delhi.
npm run dev:mock:noauth             # http://localhost:3000, sign-in skipped (PATRIBOT_AUTH_DISABLED=1)
npm run dev:mock                    # same, with the login (needs PATRIBOT_AUTH_* in .env.local)

# 2) Against the API (Phase 2 FastAPI on http://localhost:8000)
cp .env.example .env.local          # fill PATRIBOT_AUTH_*, PATRIBOT_API_URL, PATRIBOT_API_KEY
npm run dev
```

| Env var | Default | Meaning |
|---|---|---|
| `PATRIBOT_AUTH_USER` | – | The one username (server only) |
| `PATRIBOT_AUTH_PASSWORD_HASH` | – | `scrypt$N$r$p$salt$hash` from `npm run hash-password` (server only) |
| `PATRIBOT_SESSION_SECRET` | – | ≥ 32 chars, signs the session cookie (server only) |
| `PATRIBOT_AUTH_DISABLED` | unset | `1` skips sign-in, **only** in mock mode or `next dev` |
| `PATRIBOT_API_URL` | – | FastAPI base URL without `/api/v1`, used by the proxy (server only) |
| `PATRIBOT_API_KEY` | – | Sent upstream as `x-patribot-key` (server only) |
| `NEXT_PUBLIC_API_MOCK` | unset | `1` serves every call from `lib/api/mock` (simulated latency and SSE streaming) |
| `NEXT_PUBLIC_API_BASE_URL` | `/api/proxy` | Optional local-dev override to call an API directly from the browser |
| `NEXT_PUBLIC_ADS_ENABLED` | unset | `1` shows the FR-26 ad slot placeholders. Off in the POC |

`NEXT_PUBLIC_*` values are inlined at **build** time (and are public), so set them before `next build`, not at
`next start`. The `PATRIBOT_*` vars are read at request time on the server and never reach the browser. In `.env`
files Next.js expands `$VAR`, so escape every `$` of the password hash as `\$` (`npm run hash-password` prints that
form too).

> The browser only talks to the web app's own origin (`/api/proxy/*`), so the API needs no CORS for it.

### Quality gates (the same as CI)

```bash
npm run lint          # ESLint (eslint-config-next, flat config)
npm run typecheck     # next typegen && tsc --noEmit
npm test              # Vitest + Testing Library (formatting helpers, API client/mock, cards)
npm run test:e2e      # Playwright: next build && next start in mock mode, then the smoke tests
```

Playwright uses a preinstalled Chromium when one exists: `PLAYWRIGHT_CHROMIUM_EXECUTABLE`, or
`/opt/pw-browsers/chromium` (the cloud dev container). Otherwise, run `npx playwright install chromium` once. The e2e
run writes screenshots (desktop and mobile) to `web/e2e/screenshots/`, which is git-ignored. CI runs all of this in the
`web` job of `.github/workflows/ci.yml`.

## Screens

| Route | What it does |
|---|---|
| `/` | Hero and **search form**: origin/destination autocomplete (`GET /places/search`, ARIA combobox), date range (default: next weekend, IST; hint for the 60-day ARP window), overnight and split toggles, objective (balanced / fastest / most reliable), and under "More options" a must-arrive-by time (a hard constraint judged on P90), a departure window and classes (hard filter). Submitting goes to `/plan?…`. The URL holds the whole request, so results are shareable |
| `/plan` | `POST /plan` results as **itinerary cards**. Sort chips (best match, fastest, most reliable, earliest), filter chips (overnight, direct only, bookable now), "Modify search", plus loading, empty, error (with retry) and 404 "unknown place" states |
| `/trains/[trainNo]` | `GET /trains/{no}` + `/performance`: running days, classes, headline stats, a route timeline with a per-stop P50/P90 delay bar, a monthly "% within 30 min" bar chart (recharts) with a table view, and recent runs |
| `/login` | Sign-in form (username + password) for the single owner account. See [Auth & proxy](#auth--proxy) |
| `/chat` | **"Ask AI": Coming soon** (Phase 4 deferred by the owner): what plain-language planning will do, example questions and a link to the search form. It never calls `POST /chat`. The finished chat shell (`app/chat/chat-view.tsx`: streamed `token` text, `itineraries` cards, `queries_left_today`, stop button) stays in the codebase unused; render `<ChatView />` again to switch it on |

**Itinerary card** (`components/itinerary/itinerary-card.tsx`):
- Train number, name and type, linked to the train page. Date, departure, classes.
- Scheduled vs. predicted arrival (P50, with a `+1` day offset) and a delay label.
- A visual **P50–P90 band** against the timetable tick (`arrival-band.tsx`).
- **Reliability badge**: ≥ 0.8 green "Reliable", 0.5–0.8 amber "Often late", < 0.5 red "Usually late", always with an
  icon, a percentage and "based on N runs". `history_runs = 0` shows a grey "Estimate".
- Overnight tag.
- Split journeys show both legs and a layover strip: scheduled layover, P90 layover and a risk badge. The risk is
  *comfortable* at ≥ 45 min, *tight* at 0–45 min and *likely missed* below 0. The ticket label always says which kind
  it is: "Split · separate tickets" or "Break journey · one ticket". Warnings appear in an alert.
- "Plan only · not yet bookable" when a leg's `run_date` is outside `meta.bookable_from..bookable_to`.
- **"Why this?"** expander with the `score_breakdown` bars and the `why[]` reasons.
- An IRCTC button that opens a new tab. There is no booking (out of scope).

All times are shown in **IST**, whatever the viewer's time zone (`lib/format.ts`). Station codes appear next to
names. Light and dark themes come from `next-themes` (system default, plus a header toggle).

## Structure

```
web/
├── proxy.ts                  # auth gate (Next 16 "Proxy", formerly Middleware)
├── app/                      # routes: page.tsx (home), plan/, trains/[trainNo]/, chat/ (coming soon), login/,
│                             #   api/proxy/[...path]/ (server-side API proxy), not-found
├── components/
│   ├── ui/                   # shadcn/ui primitives (new-york style, Radix): button, badge, card, input, switch, …
│   ├── itinerary/            # itinerary card, arrival band, reliability badge
│   ├── search/               # search form, place combobox
│   ├── train/                # route timeline, performance charts
│   ├── site-header.tsx, site-footer.tsx (data disclaimer), theme.tsx, ad-slot.tsx (FR-26)
├── lib/
│   ├── api/                  # typed client for docs/api/v1.md
│   │   ├── types.ts          #   request/response types (snake_case, mirrors the contract)
│   │   ├── http.ts           #   fetch client + ApiError + SSE chat as an async iterator
│   │   ├── sse.ts            #   incremental text/event-stream parser
│   │   ├── query.ts          #   PlanRequest ⇄ /plan URL params
│   │   ├── mock/             #   fixtures, a tiny deterministic planner, simulated chat stream
│   │   ├── proxy-handler.ts  #   server: session check + forward to PATRIBOT_API_URL with x-patribot-key
│   │   └── index.ts          #   `api` = mock or http, chosen by NEXT_PUBLIC_API_MOCK
│   ├── auth/                 # owner login: config (env), password (scrypt), token (HMAC), session, actions,
│   │                         #   next-param (open-redirect guard), rate-limit; index.ts = plan/quota placeholder
│   ├── format.ts             # IST time, day offsets, durations, delay labels, reliability thresholds, layover risk
│   ├── itineraries.ts        # client-side sort and filter
│   └── use-async.ts          # small fetch hook (abort on change, retry)
├── scripts/hash-password.mjs # npm run hash-password
├── tests/                    # Vitest unit and component tests
└── e2e/                      # Playwright smoke (desktop + @mobile)
```

The shadcn registry isn't reachable from the dev container, so the primitives in `components/ui/` were written by hand
from the shadcn new-york (Tailwind v4) sources. `components.json` is present, so `npx shadcn add …` works where the
registry is reachable.

### Mock data

`lib/api/mock/fixtures.ts` holds illustrative timetables (not authoritative IR data) with synthetic delay
percentiles:
- **Direct:** 12301 Howrah Rajdhani, 12313 Sealdah Rajdhani, 12273 Howrah Duronto (`history_runs = 0`, so it shows
  as an estimate) and 12381 Poorva Express (low reliability).
- **Splits:** 22347 Howrah–Patna Vande Bharat + 12309 Patna Rajdhani via **PNBE** (a comfortable layover), and 12381
  + 12801 Purushottam via DDU. In the second one, leg 1's P90 arrival is after leg 2 departs, which shows the "likely
  missed" risk state. 12801 is joined mid-route, so leg 2's `run_date` is the day before.
- Running days, per-date jitter and the ARP window (today to today + 59) are applied. Other corridors resolve as
  places but return no trains (the empty state).
- The mock chat parses "X to Y" with simple rules and streams a reply built *only* from the itinerary JSON. It allows
  3 queries per page load, after which it returns an `error` event (the free-tier quota).

## What's stubbed

- **Accounts (FR-22):** there is one owner login (see [Auth & proxy](#auth--proxy)). Multi-user accounts with
  Auth.js + Google, and per-user plans, are a later phase. No secrets are in the repo.
- **Quota and plans (FR-23–25):** the UI shows `queries_left_today` from the chat `done` event and a static
  "3 free AI queries / day" before that. There is no account or upgrade page yet.
- **Ads (FR-26):** `<AdSlot>` renders nothing unless `NEXT_PUBLIC_ADS_ENABLED=1`, and then only a placeholder.
- **Chat:** deferred (Phase 4). `/chat` is a "Coming soon" page; the chat UI and SSE client remain for Phase 4, and
  the proxy already streams `text/event-stream` through.
- **Ops dashboard** (§10.1 screen 4): not built.

## Contract notes (for the API owner)

These were found while building against `docs/api/v1.md`. The contract was not changed.
1. **The chat `itineraries` event has no `meta`**, so chat cards can't show "plan only" (bookable window) or the ETA
   model. Suggestion: `event: itineraries` → `{"itineraries": [...], "meta": {...}}`, or a separate `meta` event.
2. **No quota endpoint.** `queries_left_today` only arrives after a chat message. FR-22 needs plan, used and remaining
   up front (e.g. `GET /me/usage`).
3. **Chat errors have no machine-readable code.** The UI can't tell "quota exhausted" (show the upgrade or search
   form) from "LLM spend guard paused" (FR-24) or a server error. Suggestion: `{"code": "quota_exceeded", "detail": …}`.
4. **`/plan` `query` shape is unspecified.** The UI can't show the resolved station lists or names, so it carries
   display labels in its own URL. Pinning `origin_stations`/`destination_stations` (and names) would help.
5. **Limits are unspecified:** maximum date-range length and the `max_results` default and cap. The UI caps the range
   at 31 days and sends `max_results: 20`.
6. **Nullability is unspecified:** `RouteStop.delay_p50_min`/`delay_p90_min` when there is no history, and
   `StationPlace.cluster` for stations outside a cluster. The client treats them as nullable.
7. **`performance.on_time_pct`'s definition** (on time? within 30 min?) differs from `by_month.pct_within_30min`.
   The UI labels it "within 30 min". Please confirm.
8. **ARP and `run_date`:** "plan only" is judged on each leg's `run_date` (the train's origin date), as the contract
   defines it. If the backend means the boarding date, `bookable_from/to` should say so.
9. **CORS:** resolved by the server-side proxy: the browser never calls the API directly.

## Auth & proxy

The app is hosted publicly (Vercel) but only the owner may use it, and the railway data is private. Two pieces do
that, with no database.

**Single-owner login**
- One account from env: `PATRIBOT_AUTH_USER` and `PATRIBOT_AUTH_PASSWORD_HASH`, a self-describing scrypt hash
  `scrypt$N$r$p$saltB64$hashB64` (N = 32768, r = 8, p = 1, 16-byte salt, 32-byte key). `npm run hash-password` prompts
  for the password without echo (or reads stdin or an argument) and prints the line. Verification uses Node
  `crypto.scrypt` + `timingSafeEqual`. The username is compared in constant time too, and both checks always run.
- `/login` posts to a Server Function (`lib/auth/actions.ts`; Next.js checks its Origin header). On success it sets
  the `patribot_session` cookie: `HttpOnly`, `SameSite=Lax`, `Secure` in production, `Path=/`, 30-day `Max-Age`. The
  value is a token `base64url(payload).base64url(HMAC-SHA256)` signed with `PATRIBOT_SESSION_SECRET` through Web
  Crypto (`lib/auth/token.ts`). The payload holds the username, `iat` and `exp`. Changing the secret (or the
  username) signs every session out. "Log out" in the header clears the cookie.
- **Gate:** `proxy.ts` (Next.js 16 renamed Middleware to *Proxy*) runs on every request except `/_next/static`,
  `/_next/image` and `/favicon.ico`. `/login` is public. Other pages redirect to `/login?next=<path>`, and `/api/*`
  answers `401 {"detail": "Not signed in."}` with `x-patribot-auth: required`. `next` must be a same-origin path
  (`lib/auth/next-param.ts` rejects absolute and protocol-relative URLs, backslashes, control characters, `/login`
  and `/api/*`), so there is no open redirect.
- **Brute force:** constant-time compares, a fixed 800 ms delay on every failure, and an in-memory limiter of
  5 failures per IP per 15 min, then a 15 min lockout (keyed on the first `x-forwarded-for` entry). On serverless
  the limiter is best effort: each warm instance has its own memory and cold starts reset it. Use a long random
  password; scrypt also makes offline guessing slow.
- **Fail closed:** if any auth var is missing or malformed (or the secret is shorter than 32 chars), `/login` shows
  "Sign-in is not configured", every page redirects there and every API call gets 503. Nobody gets in.
  `PATRIBOT_AUTH_DISABLED=1` skips sign-in only in mock mode (`NEXT_PUBLIC_API_MOCK=1`) or under `next dev`. It is
  never the default and is ignored in a real production build.

**Server-side API proxy** (`app/api/proxy/[...path]/route.ts` → `lib/api/proxy-handler.ts`)
- The typed client's base URL is `/api/proxy` (same origin). The handler re-checks the session (defence in depth),
  then forwards `GET`/`POST` to `${PATRIBOT_API_URL}/api/v1/<path>?<query>` with `x-patribot-key: ${PATRIBOT_API_KEY}`.
  Only `content-type` and `accept` are forwarded: no cookies or other headers go upstream, and no upstream
  `set-cookie` comes back. Path segments must be plain (`[A-Za-z0-9._~-]`, no `..`). Bodies are capped at 64 KB.
- Status codes and bodies pass through, and bodies are streamed, so `POST /chat` SSE works (`cache-control:
  no-transform`). An upstream 401/403 means the *app's key* was rejected, so it is reported as 502. A 401 from the
  proxy always means "not signed in", and the client then sends the browser to `/login?next=…`.
- **Cold starts:** the free API host sleeps and needs ~30–60 s to wake. The proxy waits up to 90 s for response
  headers (`maxDuration = 120` on the route), then answers 504 "… may still be waking up". In the UI, a request still
  pending after 4 s swaps the skeleton for a "Waking up the server…" notice (results page, train page, place
  autocomplete) instead of an error.
- `PATRIBOT_API_URL` and `PATRIBOT_API_KEY` are server-only, so neither is in any client bundle. The e2e run uses
  throwaway values, and the CI `web` job greps `.next/static` for them.

**Tests.** Vitest covers hash verify (good, bad, malformed, script ↔ server format), token sign/verify/expiry/tamper,
`next` validation, the fail-closed config rules, the limiter, the proxy handler (auth gate with a mock `fetch`, key
header, status and SSE pass-through, path tricks, 502/503/504) and `proxy.ts`. Playwright runs with auth **enabled**
(`e2e/credentials.ts`; the hash is generated in `playwright.config.ts`): redirect to `/login` → wrong password →
login back to the requested page → search → logout, an open-redirect attempt, Coming soon, and the mobile smoke.

Deployment steps: [docs/deploy/vercel.md](../deploy/vercel.md).
