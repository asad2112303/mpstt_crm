# MPSTT CRM

Prospect-to-payment CRM for **Medical Prism Supplies for Treatment and Technology** —
medical safety, healthcare-waste, and institutional supplies. Not a hospital
clinical system; it stores no patient data.

Built from the *MPSTT CRM Graph Structural Build Prompt* (see
`MPSTT_CRM_Graph_Structural_Build_Prompt.md`).

## Monorepo layout

| Path | Contents |
|---|---|
| `frontend/` | Next.js App Router + TypeScript + Tailwind + shadcn/ui |
| `backend/` | FastAPI + SQLAlchemy 2 async + Alembic (`/api/v1`) |
| `supabase/` | Supabase project setup docs (Auth, Storage, exposure rules) |
| `infra/` | docker-compose (local Postgres), Dockerfiles, runtime DB role |
| `docs/` | Architecture notes, runbooks, build log |

## Local development

Requirements: Docker, Node 22+, Python 3.11+, [`uv`](https://docs.astral.sh/uv/).

```bash
# 1. Database (Postgres 17 on localhost:54322, dev + test databases)
cd infra && docker compose up -d
docker exec mpstt-crm-db psql -U postgres -c "CREATE DATABASE mpstt_crm_test" || true

# 2. Backend
cd ../backend
cp .env.example .env          # defaults point at the docker-compose database
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# 3. Frontend
cd ../frontend
cp .env.example .env.local    # fill in Supabase publishable values
npm install
npm run dev                   # http://localhost:3000
```

## Tests

```bash
cd backend && uv run pytest        # unit + DB + API tests (needs docker db)
cd frontend && npm run lint && npm run build
```

## Architecture (frozen)

- Browser authenticates with **Supabase Auth**; all CRM reads/writes go through
  **FastAPI `/api/v1`**, which verifies the Supabase JWT and enforces
  `admin|user` roles from `crm.user_profiles`.
- **PostgreSQL** (`crm` schema, Alembic-managed) is the relational source of truth.
- **Private Supabase Storage** holds business documents; `crm.documents` holds
  metadata. No permanent public URLs.
- Server-side calculations, numbering, stock, statuses, and PDF snapshots are
  authoritative. Money is `numeric(14,2)`, quantities `numeric(14,3)`,
  timestamps `timestamptz` (displayed in `Asia/Karachi`).

See `supabase/README.md` for provisioning a real Supabase project and
`docs/` for runbooks.
