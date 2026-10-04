# PatriBot web

Next.js (App Router) + TypeScript + Tailwind v4 + shadcn/ui front end for PatriBot. It is built against the API
contract in [`docs/api/v1.md`](../docs/api/v1.md). See [`docs/phase3/web-app.md`](../docs/phase3/web-app.md) for the full guide and
[`docs/deploy/vercel.md`](../docs/deploy/vercel.md) to deploy it.

```bash
npm ci
npm run dev:mock:noauth # fixtures, no backend, sign-in skipped: http://localhost:3000
npm run dev:mock        # fixtures + sign-in (set PATRIBOT_AUTH_* in .env.local, see .env.example)
npm run dev             # real API through /api/proxy (PATRIBOT_API_URL + PATRIBOT_API_KEY)
npm run hash-password   # prints PATRIBOT_AUTH_PASSWORD_HASH
npm run lint && npm run typecheck && npm test
npm run test:e2e        # builds in mock mode, starts next, runs Playwright
```
