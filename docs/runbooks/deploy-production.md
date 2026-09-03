# Production deployment runbook

Deploys the CRM with `infra/docker-compose.prod.yml` on any Docker host
(VPS, on-prem, or a container platform). Database, auth, and file storage are
the **managed Supabase project** — nothing stateful runs in these containers.

## 0. Prerequisites (once)

- Supabase project fully configured per `supabase/README.md`
  (signup disabled, Admin with TOTP, private buckets, `crm` schema unexposed).
- Least-privileged DB role applied: `psql "$OWNER_DATABASE_URL" -v app_password='…' -f infra/runtime-role.sql`
  → production `DATABASE_URL` uses **crm_app**, not `postgres`.
- A domain + TLS terminator in front (platform LB, Caddy, or nginx):
  route `crm.yourdomain` → web:3000 and `api.crm.yourdomain` → api:8000.
- `docs/runbooks/go-live-checklist.md` signed off.

## 1. Configure

```bash
cp infra/.env.prod.example infra/.env.prod   # fill real values; never commit
```

Hard rules enforced by the app at boot (it refuses to start otherwise):
`APP_ENV=production` ⇒ `STORAGE_BACKEND=supabase`, `REQUIRE_ADMIN_MFA=true`,
Supabase URL + verification configured. These are baked into the compose file.

## 2. Build

```bash
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod build
```

## 3. Migrate (separate, explicit step — never automatic on boot)

```bash
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod \
  run --rm migrate
```

## 4. Start

```bash
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d api web
curl -fsS http://localhost:8000/ready   # {"data":{"status":"ready"}...}
```

`web` waits for the api healthcheck before starting.

## 5. Update / release a new version

```bash
git pull
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod build
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod run --rm migrate
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d api web
```

## 6. Rollback

```bash
git checkout <previous-tag-or-sha>
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod build
# Only if the bad release added migrations:
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod \
  run --rm migrate uv run alembic downgrade <previous-revision>
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d api web
```

## 7. Operations

- Logs: `docker compose -f infra/docker-compose.prod.yml logs -f api` (JSON lines,
  request_id/user_id included; rotated at 20 MB × 5).
- Backups: database AND storage objects separately — `docs/runbooks/backup-restore.md`.
- Rate limiting & TLS live at the proxy layer; the containers listen on plain HTTP
  behind it and must not be exposed directly.
