"""Server-side Supabase Admin API calls (service-role key, never in browser)."""
import uuid

import httpx

from app.core.config import Settings
from app.core.errors import AppError


class SupabaseAdminError(AppError):
    status_code = 502
    code = "AUTH_PROVIDER_ERROR"


async def invite_user(settings: Settings, email: str) -> uuid.UUID:
    """Invite a user via Supabase Auth; returns the new auth user id.

    In development without a configured Supabase project, a local-only profile
    id is generated so the flow can be exercised end to end.
    """
    if not settings.supabase_url or not settings.supabase_service_role_key:
        if settings.env in ("development", "test"):
            return uuid.uuid4()
        raise SupabaseAdminError("Supabase Auth is not configured.")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/invite",
            headers={
                "apikey": settings.supabase_service_role_key,
                "Authorization": f"Bearer {settings.supabase_service_role_key}",
            },
            json={"email": email},
        )
    if resp.status_code >= 400:
        raise SupabaseAdminError("The identity provider rejected the invitation.")
    return uuid.UUID(resp.json()["id"])
