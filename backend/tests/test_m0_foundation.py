"""M0 exit-gate tests: config validation, health/ready, error envelope, CORS."""
import pytest
from sqlalchemy import text


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"] == "ok"
    assert body["meta"]["request_id"]


async def test_ready_checks_database(client):
    resp = await client.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ready"


async def test_request_id_header_present(client):
    resp = await client.get("/health")
    assert resp.headers.get("x-request-id")


async def test_404_uses_error_envelope(client):
    resp = await client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
    err = resp.json()["error"]
    assert err["code"] == "NOT_FOUND"
    assert "request_id" in err
    assert "field_errors" in err


async def test_cors_allows_frontend_origin(client):
    resp = await client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"


async def test_cors_blocks_unknown_origin(client):
    resp = await client.options(
        "/health",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.headers.get("access-control-allow-origin") is None


async def test_settings_reject_bad_database_url(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("DATABASE_URL", "mysql://nope")
    monkeypatch.setenv("APP_ENV", "test")
    with pytest.raises(ValueError):
        Settings(_env_file=None)


async def test_production_settings_require_supabase(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    settings = Settings(_env_file=None)
    with pytest.raises(RuntimeError):
        settings.validate_for_env()


async def test_crm_schema_and_extensions_exist(raw_conn):
    schema = (
        await raw_conn.execute(
            text("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'crm'")
        )
    ).scalar()
    assert schema == 1
    exts = {
        row[0]
        for row in await raw_conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname IN ('pgcrypto','pg_trgm')")
        )
    }
    assert exts == {"pgcrypto", "pg_trgm"}


def test_production_accepts_jwks_only_verification(monkeypatch):
    """ES256 projects have no legacy JWT secret — SUPABASE_URL (JWKS) suffices."""
    from app.core.config import Settings

    settings = Settings(
        _env_file=None,
        APP_ENV="production",
        DATABASE_URL="postgresql+asyncpg://u:p@h/db",
        SUPABASE_URL="https://example.supabase.co",
        SUPABASE_JWT_SECRET="",
        STORAGE_BACKEND="supabase",
        REQUIRE_ADMIN_MFA=True,
        CORS_ORIGINS="https://crm.example.com",
    )
    settings.validate_for_env()  # must not raise


def test_production_still_requires_supabase_url(monkeypatch):
    import pytest as _pytest

    from app.core.config import Settings

    settings = Settings(
        _env_file=None,
        APP_ENV="production",
        DATABASE_URL="postgresql+asyncpg://u:p@h/db",
        SUPABASE_URL="",
        STORAGE_BACKEND="supabase",
        REQUIRE_ADMIN_MFA=True,
    )
    with _pytest.raises(RuntimeError, match="SUPABASE_URL"):
        settings.validate_for_env()
