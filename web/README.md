# PatriBot web

Next.js (App Router) + TypeScript + Tailwind v4 + shadcn/ui front end for PatriBot. It is built against the API
contract in [`docs/api/v1.md`](../docs/api/v1.md). See [`docs/phase3/web-app.md`](../docs/phase3/web-app.md) for the full guide.

```bash
npm ci
npm run dev:mock        # fixtures, no backend: http://localhost:3000
npm run dev             # against NEXT_PUBLIC_API_BASE_URL (default http://localhost:8000/api/v1)
npm run lint && npm run typecheck && npm test
npm run test:e2e        # builds in mock mode, starts next, runs Playwright
```
