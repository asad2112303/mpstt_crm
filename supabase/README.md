# Supabase project setup

The CRM uses a managed Supabase project for three things only:

1. **PostgreSQL** — the relational source of truth (`crm` schema).
2. **Auth** — identity, sessions, and optional TOTP MFA. No CRM password table exists.
3. **Storage** — private buckets for business documents.

Alembic (in `backend/`) is the **only** schema-change path. Do not create
`crm.*` tables through the Supabase dashboard or SQL editor.

## 1. Create the project

1. Create a project at <https://supabase.com/dashboard> (region close to Pakistan, e.g. `ap-south-1`).
2. Note down (Settings → API):
   - Project URL → `SUPABASE_URL` (backend) and `NEXT_PUBLIC_SUPABASE_URL` (frontend)
   - `anon` / publishable key → `NEXT_PUBLIC_SUPABASE_ANON_KEY` (frontend only)
   - `service_role` / secret key → `SUPABASE_SERVICE_ROLE_KEY` (**backend only — never in the browser**)
   - JWT secret (Settings → API → JWT) → `SUPABASE_JWT_SECRET` (backend)
3. Database connection (Settings → Database): build
   `DATABASE_URL=postgresql+asyncpg://postgres:<password>@db.<ref>.supabase.co:5432/postgres`.
   - Long-lived FastAPI container → direct connection / session pooling (port 5432).
   - Auto-scaling deployment → Supavisor transaction pooling (port 6543) and add
     `?prepared_statement_cache_size=0` for asyncpg.

## 2. Apply the schema

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://... uv run alembic upgrade head
```

Then create the least-privileged runtime role:

```bash
psql "$OWNER_DATABASE_URL" -v app_password='<generated>' -f ../infra/runtime-role.sql
```

Point the API's `DATABASE_URL` at `crm_app`, not at `postgres`.

## 3. Auth configuration

- **Disable public signup** (Authentication → Providers → Email → "Allow new users to sign up" OFF).
  Users are invited by the Admin from inside the CRM (service-role invite).
- Enable **TOTP MFA**. The Admin account must enroll; the backend enforces
  `aal2` on high-risk admin actions when `REQUIRE_ADMIN_MFA=true` (mandatory in production).
- Site URL / redirect URLs: set to the deployed frontend origin.

## 4. Data API exposure

Do **not** add `crm` to the exposed schemas (API → Data API → Exposed schemas).
The browser reads and writes CRM data only through FastAPI.

## 5. Storage buckets

Create these **private** buckets (Storage → New bucket, "Public bucket" OFF):

| Bucket | Contents |
|---|---|
| `commercial-documents` | Customer POs, quotation PDFs, invoice PDFs, receipts |
| `delivery-pod` | Signed challans, POD signatures/photos |
| `payment-proofs` | Deposit slips, transfer screenshots |

All uploads/downloads go through FastAPI (`/api/v1/documents/*`), which
authorizes the request and issues short-lived signed URLs.

## 6. Backups

- Database backups (Supabase managed) do **not** include Storage objects.
- Storage objects need a separate backup job — see `docs/runbooks/backup-restore.md`.
