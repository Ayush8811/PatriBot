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
npm run dev:mock                    # http://localhost:3000

# 2) Against the API (Phase 2 FastAPI, default http://localhost:8000/api/v1)
cp .env.example .env.local          # set NEXT_PUBLIC_API_BASE_URL if the API runs elsewhere
npm run dev
```

| Env var | Default | Meaning |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000/api/v1` | API base URL, called **from the browser** |
| `NEXT_PUBLIC_API_MOCK` | unset | `1` serves every call from `lib/api/mock` (simulated latency and SSE streaming) |
| `NEXT_PUBLIC_ADS_ENABLED` | unset | `1` shows the FR-26 ad slot placeholders. Off in the POC |

`NEXT_PUBLIC_*` values are inlined at **build** time, so set them before `next build`, not at `next start`.

> The browser calls the API directly, so the FastAPI app must allow CORS from the web origin
> (e.g. `http://localhost:3000`) in development.

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
| `/chat` | Chat shell for `POST /chat` (SSE). Renders streamed `token` text, `itineraries` as the same cards and `queries_left_today` from `done`. An `error` event shows inline. Stop button (abort). Suggestions when empty |

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
├── app/                      # routes: page.tsx (home), plan/, trains/[trainNo]/, chat/, not-found
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
│   │   └── index.ts          #   `api` = mock or http, chosen by NEXT_PUBLIC_API_MOCK
│   ├── auth/                 # Auth.js stub (TODO), free-tier session placeholder
│   ├── format.ts             # IST time, day offsets, durations, delay labels, reliability thresholds, layover risk
│   ├── itineraries.ts        # client-side sort and filter
│   └── use-async.ts          # small fetch hook (abort on change, retry)
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

- **Auth (FR-22):** `lib/auth/index.ts` returns an anonymous free-tier session. The header's "Sign in" button is
  disabled. The TODO lists the Auth.js + Google steps and env vars. No secrets are in the repo.
- **Quota and plans (FR-23–25):** the UI shows `queries_left_today` from the chat `done` event and a static
  "3 free AI queries / day" before that. There is no account or upgrade page yet.
- **Ads (FR-26):** `<AdSlot>` renders nothing unless `NEXT_PUBLIC_ADS_ENABLED=1`, and then only a placeholder.
- **Chat:** `POST /chat` is itself a stub until Phase 4. The UI already handles the full SSE contract.
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
9. **CORS:** the browser calls the API directly, so the API needs CORS for the web origin. The alternative is a
   Next.js rewrite proxy.
