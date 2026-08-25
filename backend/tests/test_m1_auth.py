"""M1 exit-gate tests: token verification, role matrix, MFA gate."""
import pytest

from tests.helpers import auth_headers, new_id, seed_profile


async def test_missing_token_is_401(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_garbage_token_is_401(client):
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


async def test_expired_token_is_401(client, db_session):
    uid = await seed_profile(db_session)
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(uid, expired=True))
    assert resp.status_code == 401


async def test_wrong_audience_is_401(client, db_session):
    uid = await seed_profile(db_session)
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(uid, aud="anon"))
    assert resp.status_code == 401


async def test_valid_token_without_profile_is_403(client):
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(new_id()))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "NO_PROFILE"


async def test_inactive_user_is_blocked(client, db_session):
    uid = await seed_profile(db_session, is_active=False)
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(uid))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "ACCOUNT_DISABLED"


async def test_me_returns_profile_and_updates_last_login(client, db_session):
    uid = await seed_profile(db_session, role="admin")
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(uid))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == uid
    assert data["role"] == "admin"

    from sqlalchemy import select

    from app.models.access import UserProfile

    profile = (
        await db_session.execute(select(UserProfile).where(UserProfile.id == uid))
    ).scalar_one()
    await db_session.refresh(profile)
    assert profile.last_login_at is not None


async def test_operational_user_cannot_manage_users(client, db_session):
    uid = await seed_profile(db_session, role="user")
    resp = await client.get("/api/v1/admin/users", headers=auth_headers(uid))
    assert resp.status_code == 403


async def test_admin_can_list_invite_and_update_users(client, db_session):
    admin_id = await seed_profile(db_session, role="admin")
    headers = auth_headers(admin_id)

    resp = await client.get("/api/v1/admin/users", headers=headers)
    assert resp.status_code == 200

    resp = await client.post(
        "/api/v1/admin/users/invite",
        headers=headers,
        json={"email": f"invitee-{new_id()[:8]}@mpstt.pk", "full_name": "Field Officer", "role": "user"},
    )
    assert resp.status_code == 201
    invited = resp.json()["data"]
    assert invited["role"] == "user"

    resp = await client.patch(
        f"/api/v1/admin/users/{invited['id']}", headers=headers, json={"is_active": False}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["is_active"] is False


async def test_admin_cannot_deactivate_self(client, db_session):
    admin_id = await seed_profile(db_session, role="admin")
    resp = await client.patch(
        f"/api/v1/admin/users/{admin_id}",
        headers=auth_headers(admin_id),
        json={"is_active": False},
    )
    assert resp.status_code == 409


async def test_mfa_gate_blocks_aal1_admin_when_required():
    from app.core.config import Settings
    from app.core.errors import AuthorizationError
    from app.core.security import CurrentUser, require_admin_mfa

    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL="postgresql+asyncpg://u:p@h/db",
        REQUIRE_ADMIN_MFA=True,
    )
    admin_aal1 = CurrentUser(id=new_id(), email=None, role="admin", aal="aal1", full_name="A")
    with pytest.raises(AuthorizationError):
        await require_admin_mfa(user=admin_aal1, settings=settings)

    admin_aal2 = CurrentUser(id=new_id(), email=None, role="admin", aal="aal2", full_name="A")
    assert await require_admin_mfa(user=admin_aal2, settings=settings) is admin_aal2
