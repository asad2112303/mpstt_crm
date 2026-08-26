# Backup & restore runbook

Two SEPARATE controls. A database restore alone does **not** bring back
deleted Storage objects — the database only holds file *metadata*
(`crm.documents`); the bytes live in Supabase Storage.

## 1. Database backup

- Supabase managed backups: daily automatic; verify plan retention.
  On-demand: `Dashboard → Database → Backups` or
  `supabase db dump --db-url "$OWNER_DATABASE_URL" -f crm-$(date +%F).sql`.
- Store dumps in a separate location from the project itself.

### Restore drill (run at least before go-live and quarterly)

```bash
createdb crm_restore_test
psql crm_restore_test < crm-YYYY-MM-DD.sql
# verify: row counts on crm.organizations / invoices / payments match source,
# alembic version matches, views exist:
psql crm_restore_test -c "SELECT count(*) FROM crm.organizations"
```

## 2. Storage-object backup

Supabase database backups do NOT include Storage objects. Back up each
private bucket separately:

```bash
# Requires the service-role key; run from a trusted operations machine only.
python infra/storage_backup.py --out ./storage-backup-$(date +%F)
```

The script lists every object in `commercial-documents`, `delivery-pod`,
`payment-proofs` and downloads them preserving paths. Sync the output to
offline/off-site storage.

### Storage restore drill

1. Pick 5 random rows from `crm.documents`.
2. Confirm the backed-up file exists at `bucket/storage_path` and its
   sha256 matches `checksum_sha256`.
3. Re-upload one file to a scratch bucket and confirm a signed URL serves it.

## 3. Orphan reconciliation

Monthly: compare `crm.documents` against actual Storage objects both ways.

- Metadata without object → alert; restore the object from backup.
- Object without metadata → review; likely a failed transaction — delete
  after confirmation.

## 4. What to test before go-live

- [ ] Database dump + restore into a scratch database (checklist above)
- [ ] Storage backup + spot-check restore
- [ ] Sequence continuity after restore (`crm.number_sequences` intact)
- [ ] Application boots against the restored database (read-only smoke test)
