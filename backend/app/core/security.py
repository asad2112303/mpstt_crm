"""Supabase JWT verification and authorization dependencies.

The browser signs in with Supabase Auth. Every protected request carries the
Supabase access token as a Bearer header. We verify it (HS256 legacy secret or
the project JWKS), then load ``crm.user_profiles`` — an inactive or missing
profile is rejected even with a valid token.
"""
import logging
import time
from dataclasses import dataclass

import httpx
import jwt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.context import user_id_var
from app.core.db import get_db
from app.core.errors import AuthenticationError, AuthorizationError
from app.models.access import UserProfile


@dataclass
class CurrentUser:
    id: str
    email: str | None
    role: str  # 'admin' | 'user'
    aal: str  # 'aal1' | 'aal2'
    full_name: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


_jwks_cache: dict = {"keys": None, "fetched_at": 0.0}
_JWKS_TTL = 3600.0


async def _get_jwks(settings: Settings) -> dict:
    now = time.monotonic()
    if _jwks_cache["keys"] is None or now - _jwks_cache["fetched_at"] > _JWKS_TTL:
        url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            _jwks_cache["keys"] = resp.json()
            _jwks_cache["fetched_at"] = now
    return _jwks_cache["keys"]


async def decode_token(token: str, settings: Settings) -> dict:
    """Verify signature, expiry, and audience; return claims."""
    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg", "HS256")
        if alg == "HS256":
            if not settings.supabase_jwt_secret:
                raise AuthenticationError("Token verification is not configured.")
            return jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience=settings.supabase_jwt_aud,
            )
        jwks = await _get_jwks(settings)
        kid = header.get("kid")
        key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        if key is None:
            raise AuthenticationError("Unknown signing key.")
        public_key = jwt.PyJWK(key).key
        return jwt.decode(
            token, public_key, algorithms=[alg], audience=settings.supabase_jwt_aud
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Session expired. Please sign in again.") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid authentication token.") from exc


def _extract_bearer(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise AuthenticationError("Missing authentication token.")
    return auth[7:].strip()


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    token = _extract_bearer(request)
    claims = await decode_token(token, settings)
    sub = claims.get("sub")
    if not sub:
        raise AuthenticationError("Invalid authentication token.")

    profile = (
        await db.execute(select(UserProfile).where(UserProfile.id == sub))
    ).scalar_one_or_none()
    if profile is None:
        # Operational aid: bootstrap needs this id to create the first profile.
        logging.getLogger("app.auth").warning(
            "NO_PROFILE for auth user sub=%s email=%s", sub, claims.get("email")
        )
        raise AuthorizationError("No CRM profile exists for this account.", code="NO_PROFILE")
    if not profile.is_active:
        raise AuthorizationError("This account has been deactivated.", code="ACCOUNT_DISABLED")

    user_id_var.set(str(profile.id))
    return CurrentUser(
        id=str(profile.id),
        email=claims.get("email") or profile.email,
        role=profile.role,
        aal=claims.get("aal", "aal1"),
        full_name=profile.full_name,
    )


async def require_user(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    return user


async def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.is_admin:
        raise AuthorizationError("Administrator access is required.")
    return user


async def require_admin_mfa(
    user: CurrentUser = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    """High-risk admin actions: enforce aal2 (TOTP) when REQUIRE_ADMIN_MFA is on."""
    if settings.require_admin_mfa and user.aal != "aal2":
        raise AuthorizationError(
            "This action requires multi-factor authentication (aal2).", code="MFA_REQUIRED"
        )
    return user
