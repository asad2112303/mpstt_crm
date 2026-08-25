"""Shared test helpers: JWT minting and profile seeding."""
import uuid
from datetime import UTC, datetime, timedelta

import jwt

TEST_SECRET = "test-jwt-secret-for-local-tests-only"


def make_token(
    sub: str,
    *,
    email: str = "someone@example.com",
    aal: str = "aal1",
    expired: bool = False,
    aud: str = "authenticated",
    secret: str = TEST_SECRET,
) -> str:
    now = datetime.now(UTC)
    exp = now - timedelta(hours=1) if expired else now + timedelta(hours=1)
    return jwt.encode(
        {
            "sub": sub,
            "email": email,
            "aud": aud,
            "aal": aal,
            "iat": int(now.timestamp()) - 7200 if expired else int(now.timestamp()),
            "exp": int(exp.timestamp()),
        },
        secret,
        algorithm="HS256",
    )


def auth_headers(sub: str, **kwargs) -> dict:
    return {"Authorization": f"Bearer {make_token(sub, **kwargs)}"}


def new_id() -> str:
    return str(uuid.uuid4())


async def seed_profile(session, *, role: str = "user", is_active: bool = True, full_name: str | None = None):
    """Insert a user profile and return its id (str)."""
    from app.models.access import UserProfile

    uid = uuid.uuid4()
    session.add(
        UserProfile(
            id=uid,
            full_name=full_name or f"Test {role.title()}",
            email=f"{uid.hex[:10]}@test.mpstt.pk",
            role=role,
            is_active=is_active,
        )
    )
    await session.commit()
    return str(uid)
