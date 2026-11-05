# Deployment

The deployed application uses Vercel Services: `frontend/` is Next.js, `backend/` is FastAPI. Root `vercel.json` routes `/api/*` to backend and all other paths to frontend. Python dependencies are declared in `backend/pyproject.toml`; development/test installation uses `requirements.txt`.

## Vercel + Neon

1. Install the official Vercel CLI and authenticate: `npm install -g vercel`, `vercel login`.
2. From the repository root run `vercel link` and select/create the project.
3. Provision/connect the **free** Neon plan using Vercel Marketplace or CLI: `vercel integration add neon --billing-plan free_v3 --meta region=sin1 --meta auth=false`.
4. Verify the integration attached `DATABASE_URL` to production. Keep its value private. Never commit a database URL.
5. Add `JWT_SECRET_KEY` using `vercel env add JWT_SECRET_KEY production`, supplying a cryptographically random value with at least 32 characters. Keep it stable across instances/deployments.
6. Set `DEMO_MODE=true` for synthetic demonstration; the first backend startup initializes the tables and seed dataset. For real operations disable demo and public registration, create an administrator through `admin.py` against the production database, then import operational records through controlled procedures.
7. Run tests and `npm run build` from `frontend/`.
8. Deploy from repository root: `vercel deploy --prod --yes`.
9. Confirm `vercel inspect <deployment-url>` reports Ready; check `/api/health` returns `engine: PostgreSQL` and `persistent: true`.
10. Sign into demo, run intelligence, inspect agent logs and verify the warehouse map and persisted state.

For a separate backend host, use `python -m uvicorn main:app --host 0.0.0.0 --port $PORT` from `backend/`. Set `FRONTEND_URL` to your trusted frontend origin. Set frontend `NEXT_PUBLIC_API_URL` to the backend's HTTPS origin and configure deployment routing appropriately. Same-origin Vercel deployment requires no `NEXT_PUBLIC_API_URL`.

Do not use ephemeral Vercel SQLite storage for durable production. The fallback `/tmp` database is for emergency demo/testing only. The current deployment has Neon attached.

## GitHub

Push to the requested repository using ordinary Git credentials. Vercel's GitHub App must independently have repository access to enable automatic deployments; a successful Git push does not grant the Vercel App access. If integration connection is unavailable, direct CLI deployment still works. Authorize the repository under the Vercel GitHub App installation and connect it in Project Settings → Git to enable auto-deploys.

## Release limits

This release has application integration tests and a production build check. It has not undergone load testing, security penetration testing, formal accessibility audit, carrier certification, tenant isolation or production backup recovery testing. See README for functional scope limits. No paid AI API is required; stay within provider free-tier quotas.
