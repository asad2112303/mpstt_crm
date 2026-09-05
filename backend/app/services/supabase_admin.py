"""Server-side Supabase Admin API calls (service-role key, never in browser)."""
import uuid

import httpx

from app.core.config import Settings
from app.core.errors import AppError


class SupabaseAdminError(AppError):
    status_code = 502
    code = "AUTH_PROVIDER_ERROR"


def _configured(settings: Settings) -> bool:
    return bool(settings.supabase_url and settings.supabase_service_role_key)


def _headers(settings: Settings) -> dict:
    key = settings.supabase_service_role_key
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def _provider_detail(resp: httpx.Response) -> str:
    """The provider's own reason, so failures are actionable rather than opaque.

    Only messages are surfaced — never headers or credentials.
    """
    try:
        body = resp.json()
    except ValueError:
        return (resp.text or "")[:200]
    if isinstance(body, dict):
        for key in ("msg", "message", "error_description", "error", "code"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value[:200]
    return str(body)[:200]


async def find_user_id_by_email(settings: Settings, email: str) -> uuid.UUID | None:
    """Look up an existing auth user (the admin may have created it manually)."""
    if not _configured(settings):
        return None
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/admin/users",
            headers=_headers(settings),
            params={"page": 1, "per_page": 200},
        )
    if resp.status_code >= 400:
        return None
    payload = resp.json()
    users = payload.get("users", payload if isinstance(payload, list) else [])
    for user in users:
        if (user.get("email") or "").lower() == email.lower():
            return uuid.UUID(user["id"])
    return None


async def invite_user(settings: Settings, email: str) -> uuid.UUID:
    """Send an invitation email; returns the auth user id.

    Falls back to linking an existing auth account when the address is already
    registered — that is a normal situation (an admin created the login in the
    Supabase dashboard first) and must not fail the CRM profile creation.
    """
    if not _configured(settings):
        if settings.env in ("development", "test"):
            return uuid.uuid4()
        raise SupabaseAdminError(
            "Supabase Auth is not configured: set SUPABASE_SERVICE_ROLE_KEY on the API service.",
            code="AUTH_NOT_CONFIGURED",
        )

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/invite",
            headers=_headers(settings),
            json={"email": email},
        )
    if resp.status_code < 400:
        return uuid.UUID(resp.json()["id"])

    existing = await find_user_id_by_email(settings, email)
    if existing is not None:
        return existing

    detail = _provider_detail(resp)
    if resp.status_code in (429, 500, 502, 503) or "email" in detail.lower():
        # Supabase's built-in mailer is rate limited and often unconfigured.
        raise SupabaseAdminError(
            f"Supabase could not send the invitation email ({resp.status_code}: {detail}). "
            "Use 'Set a password now' instead, or configure SMTP in the Supabase dashboard.",
            code="INVITE_EMAIL_FAILED",
        )
    raise SupabaseAdminError(f"Supabase rejected the invitation ({resp.status_code}): {detail}")


async def create_user_with_password(
    settings: Settings, email: str, password: str
) -> uuid.UUID:
    """Create a confirmed auth user directly — no email delivery involved.

    The reliable path for an internal tool: the admin hands the credentials to
    the user, who changes the password on first sign-in.
    """
    if not _configured(settings):
        if settings.env in ("development", "test"):
            return uuid.uuid4()
        raise SupabaseAdminError(
            "Supabase Auth is not configured: set SUPABASE_SERVICE_ROLE_KEY on the API service.",
            code="AUTH_NOT_CONFIGURED",
        )

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/admin/users",
            headers=_headers(settings),
            json={"email": email, "password": password, "email_confirm": True},
        )
    if resp.status_code < 400:
        return uuid.UUID(resp.json()["id"])

    existing = await find_user_id_by_email(settings, email)
    if existing is not None:
        raise SupabaseAdminError(
            "That email already has a login. Ask the user to sign in, or reset "
            "their password from the Supabase dashboard.",
            code="USER_EXISTS",
        )
    raise SupabaseAdminError(
        f"Supabase rejected the account creation ({resp.status_code}): {_provider_detail(resp)}"
    )
