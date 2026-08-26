#!/usr/bin/env python3
"""Create the first Admin: a Supabase Auth user + its crm.user_profiles row.

There is deliberately no public signup, so the very first account is created
here. After this, invite further users from inside the CRM (Admin → Users).

Usage (from backend/, reads .env):
    uv run python scripts/bootstrap_admin.py --email you@mpstt.pk --name "Your Name" \
        [--password 'S3cure!pass']    # omit to send an invite email instead

Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (the sb_secret_... key,
Dashboard → Settings → API) in backend/.env — server-side only, never in git.
Alternatively, if you already created the user in the Supabase dashboard:
    uv run python scripts/bootstrap_admin.py --email you@mpstt.pk --name "Your Name" --existing
"""
import argparse
import os
import sys
from pathlib import Path

import httpx


def load_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def find_user_by_email(base: str, headers: dict, email: str) -> str | None:
    resp = httpx.get(
        f"{base}/auth/v1/admin/users", headers=headers,
        params={"page": 1, "per_page": 200}, timeout=15,
    )
    resp.raise_for_status()
    for user in resp.json().get("users", []):
        if (user.get("email") or "").lower() == email.lower():
            return user["id"]
    return None


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--password", help="Set a password directly (else an invite email is sent)")
    parser.add_argument("--existing", action="store_true",
                        help="User already exists in Supabase Auth; only create the CRM profile")
    parser.add_argument("--role", default="admin", choices=["admin", "user"])
    args = parser.parse_args()

    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    secret = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    db_url = os.environ.get("DATABASE_URL", "").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    if not base or not secret:
        print("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in backend/.env",
              file=sys.stderr)
        return 1
    headers = {"apikey": secret, "Authorization": f"Bearer {secret}"}

    user_id = find_user_by_email(base, headers, args.email)
    if user_id:
        print(f"Auth user already exists: {user_id}")
    elif args.existing:
        print("No auth user with that email found.", file=sys.stderr)
        return 1
    elif args.password:
        resp = httpx.post(
            f"{base}/auth/v1/admin/users", headers=headers, timeout=15,
            json={"email": args.email, "password": args.password, "email_confirm": True},
        )
        resp.raise_for_status()
        user_id = resp.json()["id"]
        print(f"Created auth user {user_id} (password set, email confirmed)")
    else:
        resp = httpx.post(
            f"{base}/auth/v1/invite", headers=headers, timeout=15,
            json={"email": args.email},
        )
        resp.raise_for_status()
        user_id = resp.json()["id"]
        print(f"Invited {args.email} — auth user {user_id} (check the inbox)")

    import psycopg

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO crm.user_profiles (id, full_name, email, role, is_active)
            VALUES (%s, %s, %s, %s, true)
            ON CONFLICT (id) DO UPDATE
                SET full_name = EXCLUDED.full_name,
                    role = EXCLUDED.role,
                    is_active = true
            """,
            (user_id, args.name, args.email, args.role),
        )
        conn.commit()
    print(f"CRM profile ready: {args.email} as {args.role}. Sign in at the CRM login page.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
