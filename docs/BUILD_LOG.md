# Build log — module status

| Module | Status | Notes |
|---|---|---|
| M0 Foundation | ✅ done | Monorepo, Docker Postgres, Alembic baseline, error envelope, CI, MPSTT design tokens |
| M1 Core access | ⬜ | |
| M3 Catalogue | ⬜ | |
| M2 Prospects | ⬜ | |
| M4 Customers/conversion | ⬜ | |
| M11 Documents/settings/audit | ⬜ | |
| M5 Quotations | ⬜ | Waiting on MPSTT quotation format from owner |
| M6 Orders/inventory | ⬜ | |
| M7 Invoices | ⬜ | |
| M8 Delivery/POD | ⬜ | |
| M9 Payments/AR | ⬜ | |
| M10 Dashboard/reports | ⬜ | |
| M12 Migration/QA/go-live | ⬜ | |

## Deviations from the blueprint (documented)

- **pgTAP** replaced by pytest-based DB tests against real Postgres (same
  assertions, one toolchain). Revisit if MPSTT mandates pgTAP.
- Local dev/test uses a plain Postgres 17 container instead of the full local
  Supabase stack; JWT verification supports the legacy HS256 secret so tests
  can mint tokens. Staging/production use the managed Supabase project.
- Storage has a `local` filesystem backend for dev/tests; `supabase` backend
  is mandatory (enforced by settings validation) in staging/production.
