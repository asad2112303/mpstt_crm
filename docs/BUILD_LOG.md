# Build log — module status

| Module | Status | Notes |
|---|---|---|
| M0 Foundation | ✅ done | Monorepo, Docker Postgres, Alembic baseline, error envelope, CI, MPSTT design tokens |
| M1 Core access | ✅ done | Supabase JWT verify (HS256/JWKS), profiles/roles, admin user mgmt, numbering, append-only audit, idempotency |
| M3 Catalogue | ✅ done | Categories with validated attribute schemas, brands, UOMs, products/variants, templates, search |
| M2 Prospects | ✅ done | Orgs/branches/contacts, stage guards (won never manual), activities, tasks, requirements, samples, price history, action queue |
| M4 Customers/conversion | ✅ done | Atomic first-order conversion — race-safe, idempotent, history preserved on the SAME record |
| M11 Documents/settings/audit | ✅ done | Validated private storage (local/Supabase), signed downloads, settings editor, audit viewer, PDF platform, backup runbook |
| M5 Quotations | ✅ done | Immutable sent snapshots, revision chains, accept/reject/convert; **PDF replicates MPSTT_Quotation_Template_v1.2.docx** |
| M6 Orders/inventory | ✅ done | Reservation on confirm (race-safe), cancellation release, admin adjustments, movements, v_stock_available |
| M7 Invoices | ✅ done | Issue freezes number/due-date/PDF; derived paid/overdue states; invoice ≠ delivery |
| M8 Delivery/POD | ✅ done | Partial challans, POD gate, stock/reservation reconcile, exception views, challan PDF |
| M9 Payments/AR | ✅ done | Allocations (over-allocation impossible, race-safe), admin+MFA reversal, receipts, aging, statements |
| M10 Dashboard/reports | ✅ done | Action-first tiles, admin funnel/aging, reconciled reports, audited CSV export, global search |
| M12 Migration/QA/go-live | ✅ done | Staged CSV import (validate→duplicates→approve), full-lifecycle UAT test, Playwright smoke, go-live checklist |

**Backend tests: 100+ (unit, DB, API, permissions, concurrency, idempotency, UAT lifecycle).**
**Frontend: lint + typecheck + build clean; Playwright smoke E2E green.**

## Deviations from the blueprint (documented)

- **pgTAP** replaced by pytest-based DB tests against real Postgres (same
  assertions, one toolchain).
- Local dev/test uses a plain Postgres 17 container instead of the full local
  Supabase stack; JWT verification supports the legacy HS256 secret so tests
  can mint tokens. Staging/production use the managed Supabase project.
- Storage has a `local` filesystem backend for dev/tests; the `supabase`
  backend is enforced by settings validation in staging/production.
- Branch/contact/price sub-resources live under `/api/v1/organizations/*`
  (shared by prospects and customers) instead of being duplicated under
  `/prospects/*`.
- Quotation numbers stay stable across revisions (`QT-YYYY-NNNN` + revision_no)
  with a unique (number, revision) pair.
- The quotation PDF adds a "Quotation No" line to the template's meta panel —
  the CRM must print the tracking number on the document.
- Authenticated browser E2E requires a real Supabase project; the committed
  Playwright suite covers the unauthenticated shell and is extended at go-live.

## What is intentionally NOT in V1 (per blueprint §14)

Suppliers/POs/GRNs, lots/expiry/FEFO, tenders/contracts, territories,
WhatsApp automation, route optimization, GL integration, customer portal,
AI forecasting.
