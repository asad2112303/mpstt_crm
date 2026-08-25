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

-- The runtime role must not create objects anywhere.
REVOKE CREATE ON SCHEMA crm FROM crm_app;
REVOKE CREATE ON SCHEMA public FROM crm_app;
