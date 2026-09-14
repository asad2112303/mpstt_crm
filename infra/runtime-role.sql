-- Least-privileged runtime role for the FastAPI service.
-- Run this once as the database owner (postgres / supabase admin) AFTER the
-- Alembic migrations have been applied. The API process must connect as
-- crm_app, never as the owner.
--
-- Usage:
--   psql "$OWNER_DATABASE_URL" -v app_password='<strong-generated-password>' -f runtime-role.sql

\set ON_ERROR_STOP on

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'crm_app') THEN
        CREATE ROLE crm_app LOGIN PASSWORD :'app_password';
    END IF;
END $$;

GRANT USAGE ON SCHEMA crm TO crm_app;

-- Data access: normal CRUD on application tables, but no DDL.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA crm TO crm_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA crm TO crm_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA crm
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO crm_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA crm
    GRANT USAGE, SELECT ON SEQUENCES TO crm_app;

-- Audit log is append-only for the runtime role: INSERT + SELECT, no UPDATE/DELETE.
-- (Re-run after the M1 migration creates the table.)
DO $$
BEGIN
    IF to_regclass('crm.audit_log') IS NOT NULL THEN
        REVOKE UPDATE, DELETE ON crm.audit_log FROM crm_app;
    END IF;
END $$;

-- Website intake: public.quotation_requests (created from
-- supabase/sql/quotation_requests.sql, outside Alembic because it belongs to
-- the website). The website inserts through /api/quote with the Supabase
-- secret key; the CRM only reads the queue and moves it along, so the runtime
-- role gets SELECT plus UPDATE on the three workflow columns and nothing else
-- — it cannot rewrite what the customer submitted, and cannot INSERT/DELETE.
--
-- RLS is enabled on that table with no policies, which denies every role that
-- cannot bypass RLS, crm_app included. Grants alone would leave the inbox
-- silently empty, so crm_app also needs its own policies. These are scoped to
-- crm_app by name: anon and authenticated stay fully denied.
DO $$
BEGIN
    IF to_regclass('public.quotation_requests') IS NOT NULL THEN
        GRANT USAGE ON SCHEMA public TO crm_app;
        GRANT SELECT ON public.quotation_requests TO crm_app;
        GRANT UPDATE (status, internal_notes, contacted_at)
            ON public.quotation_requests TO crm_app;

        DROP POLICY IF EXISTS crm_app_select ON public.quotation_requests;
        CREATE POLICY crm_app_select ON public.quotation_requests
            FOR SELECT TO crm_app USING (true);

        DROP POLICY IF EXISTS crm_app_update ON public.quotation_requests;
        CREATE POLICY crm_app_update ON public.quotation_requests
            FOR UPDATE TO crm_app USING (true) WITH CHECK (true);
    END IF;
END $$;

-- The runtime role must not create objects anywhere.
REVOKE CREATE ON SCHEMA crm FROM crm_app;
REVOKE CREATE ON SCHEMA public FROM crm_app;
