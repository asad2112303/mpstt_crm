"""Test fixtures.

Tests run against a real PostgreSQL database (docker-compose `db` service,
database ``mpstt_crm_test``). Migrations are applied once per session from
empty, exactly like a production deploy.
"""
import os
import subprocess
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parent.parent
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:54322/mpstt_crm_test",
)

os.environ.setdefault("APP_ENV", "test")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret-for-local-tests-only")


def _run_migrations() -> None:
    env = dict(os.environ, DATABASE_URL=TEST_DATABASE_URL)
    subprocess.run(
        ["uv", "run", "alembic", "downgrade", "base"], cwd=BACKEND_DIR, env=env, check=True,
        capture_output=True,
    )
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"], cwd=BACKEND_DIR, env=env, check=True,
        capture_output=True,
    )


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    _run_migrations()
    yield


@pytest.fixture()
async def db_session():
    engine = create_async_engine(TEST_DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture()
async def client():
    from app.core import db as db_module
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await db_module.dispose_engine()


@pytest.fixture()
async def raw_conn():
    """Direct asyncpg-style connection for DB-level assertions."""
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as conn:
        yield conn
    await engine.dispose()


async def table_exists(conn, name: str) -> bool:
    result = await conn.execute(
        text("SELECT to_regclass(:qualified) IS NOT NULL"), {"qualified": f"crm.{name}"}
    )
    return bool(result.scalar())
