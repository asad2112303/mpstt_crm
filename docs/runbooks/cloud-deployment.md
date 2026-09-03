# Cloud deployment (Vercel + Railway + Supabase)

The live topology. Three managed pieces — no server of our own holds state.

```
  Browser
    │
    ├─► Vercel            Next.js frontend (repo root dir: frontend/)
    │      │
    │      └─► Railway    FastAPI backend  (infra/Dockerfile.backend, railway.json)
    │                        │
    └─► Supabase Auth        └─► Supabase Postgres  +  private Storage buckets
```

Why the split: Vercel runs serverless functions, but the backend needs a
long-running process (row-locked transactions, WeasyPrint PDF rendering), so it
lives on a container host. Render is supported too — see `render.yaml`.

## Backend — Railway

Deploy from the GitHub repo; `railway.json` selects `infra/Dockerfile.backend`
and health-checks `/health`. The image reads `$PORT` from the platform.

Variables:

| Key | Value |
|---|---|
| `APP_ENV` | `production` |
| `STORAGE_BACKEND` | `supabase` |
| `REQUIRE_ADMIN_MFA` | `true` |
| `SUPABASE_JWT_AUD` | `authenticated` |
| `SUPABASE_URL` | `https://<project-ref>.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | `sb_secret_…` (backend only — never in the frontend) |
| `DATABASE_URL` | `postgresql+asyncpg://postgres.<ref>:<pw>@<region>.pooler.supabase.com:5432/postgres` |
| `CORS_ORIGINS` | the production frontend origin |
| `CORS_ORIGIN_REGEX` | optional, e.g. `https://myapp-.*\.vercel\.app` |

Gotchas learned the hard way:

- **Percent-encode the database password.** `@` becomes `%40`, `#` becomes `%23`.
  A raw special character silently breaks the URL parse.
- **No `SUPABASE_JWT_SECRET` needed** for projects signing with ES256 — tokens
  are verified against the project JWKS, which only needs `SUPABASE_URL`.
- **Session pooler (port 5432)** suits a long-lived container. For transaction
  pooling (6543) add `?prepared_statement_cache_size=0` for asyncpg.

Verify: `https://<api-domain>/ready` must return `{"data":{"status":"ready"}}` —
that proves the container reached the database. `/docs` is 404 in production by
design.

## Frontend — Vercel

- **Settings → General → Root Directory = `frontend`** (monorepo).
- Environment variables (publishable values only):

| Key | Value |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://<project-ref>.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | `sb_publishable_…` |
| `NEXT_PUBLIC_API_BASE_URL` | the Railway API domain, no trailing slash |

`NEXT_PUBLIC_*` values are **inlined at build time** — after changing one you
must redeploy; editing the variable alone changes nothing.

## CORS and preview deployments

Every Vercel build gets its own hostname (`myapp-<hash>-<team>.vercel.app`), so
a preview URL is **not** covered by `CORS_ORIGINS` and the browser blocks every
API call — the page shows a generic load failure and the console is often empty,
because the request never leaves it. Set `CORS_ORIGIN_REGEX` to cover previews,
or test on the production domain only.

## Release

`git push` → Railway rebuilds the backend, Vercel rebuilds the frontend. Schema
changes are **not** automatic: run migrations explicitly.

```bash
# Railway: one-off command against the service
uv run alembic upgrade head
# or locally, pointed at the same database:
DATABASE_URL=<supabase-url> uv run alembic upgrade head
```

## Data seeding / migration

- `backend/scripts/switch_to_supabase.sh '<db-password>'` — migrate schema, seed
  the admin profile, import the workbook, in one pass.
- `backend/scripts/migrate_workbook.py` — the 13-sheet MPSTT staging workbook.
- `backend/scripts/import_client_list.py` — the Client List accounts.
- `backend/scripts/bootstrap_admin.py` — first admin (no public signup exists).
