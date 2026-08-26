# Production go-live checklist (M12 gate)

Sign off every item before releasing to MPSTT users.

## Build & tests
- [ ] `cd backend && uv run alembic upgrade head` from an EMPTY database succeeds
- [ ] `uv run pytest` — all green (incl. concurrency + UAT lifecycle test)
- [ ] `uv run ruff check .` clean
- [ ] `cd frontend && npm run lint && npm run build` clean
- [ ] `npm run test:e2e` smoke passes against a production build
- [ ] Secret scan (gitleaks in CI) clean; `.env*` never committed
- [ ] Dependency audit (`npm audit`, `pip-audit`) reviewed

## Supabase project
- [ ] Project created; `supabase/README.md` followed end to end
- [ ] Public signup DISABLED; Admin invited and TOTP MFA enrolled
- [ ] `REQUIRE_ADMIN_MFA=true` in backend production env
- [ ] `crm` schema NOT exposed via the Data API
- [ ] Private buckets created: commercial-documents, delivery-pod, payment-proofs
- [ ] Least-privileged role applied (`infra/runtime-role.sql`); API connects as `crm_app`
- [ ] Database SSL enforced; connection mode matches deployment (session vs Supavisor)

## Configuration
- [ ] Backend env: `APP_ENV=production`, `STORAGE_BACKEND=supabase`, real
      SUPABASE_URL / JWT secret / service key; CORS allowlist = frontend origin only
- [ ] Frontend env: publishable Supabase values + `NEXT_PUBLIC_API_BASE_URL` (https)
- [ ] Company settings filled in-app (identity, NTN/STRN, bank details, terms, footer)
- [ ] Number sequences verified (first documents will be ORG-/CUST-/QT-/ORD-/INV-/DC-/PAY-/RCP-YYYY-0001)

## Data migration
- [ ] Legacy workbook exported to the documented CSV columns
- [ ] Staged via Admin → Data import; errors fixed at source and re-staged
- [ ] Duplicates reviewed by a human; none auto-merged
- [ ] Batch report archived (counts + checksum); ready = imported + rejected
- [ ] Opening inventory entered as `opening` adjustments after Admin review
- [ ] Opening receivables entered as `origin=migration` invoices after Admin review

## Operations
- [ ] HTTPS on both services; HTTP redirects
- [ ] Rate limiting at the edge for /auth, uploads, exports, high-risk POSTs
- [ ] Error tracking + structured log shipping with retention policy
- [ ] Monitoring: /health, /ready, DB connections, disk
- [ ] Database backup verified AND restore drill executed (see backup-restore.md)
- [ ] Storage-object backup executed AND spot-restore verified (separate from DB!)
- [ ] Rollback plan written: previous image tags + `alembic downgrade` path
- [ ] Malware-scan control for uploads documented (even if asynchronous/manual)

## Final QA
- [ ] UAT lifecycle walked through IN THE BROWSER by MPSTT staff
      (prospect → visit → requirement → sample → quote → revise → accept →
      convert → reserve → invoice → 2 partial deliveries + POD → partial +
      final payment → receipt → reports)
- [ ] PDF visual QA: long names, multi-page item tables, totals, footers
- [ ] Authorization matrix re-tested with a real Operational User account
- [ ] Accessibility pass: keyboard nav, labels, contrast on key flows
- [ ] Sign-off recorded by MPSTT owner + Quality/Legal (waste-category mapping)
