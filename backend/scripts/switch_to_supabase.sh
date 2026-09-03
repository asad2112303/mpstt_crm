#!/usr/bin/env bash
# Point the CRM at the managed Supabase database, migrate the schema, and
# import the existing data. Run from backend/:
#
#   ./scripts/switch_to_supabase.sh 'YOUR_DATABASE_PASSWORD'
#
# The password is written only into backend/.env (git-ignored) — never committed.
# Special characters are percent-encoded automatically.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 'YOUR_DATABASE_PASSWORD'" >&2
  exit 1
fi

RAW_PASSWORD="$1"
POOLER_HOST="aws-0-ap-northeast-2.pooler.supabase.com"
POOLER_PORT="5432"
DB_USER="postgres.rhghnfmilvetlxmcbkjl"
DB_NAME="postgres"

# Percent-encode the password so special characters survive the URL.
ENCODED_PASSWORD=$(python3 -c "import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1], safe=''))" "$RAW_PASSWORD")
SUPABASE_DB_URL="postgresql+asyncpg://${DB_USER}:${ENCODED_PASSWORD}@${POOLER_HOST}:${POOLER_PORT}/${DB_NAME}"

cd "$(dirname "$0")/.."

echo "==> 1/6 Testing the connection to Supabase"
DATABASE_URL="$SUPABASE_DB_URL" uv run python - <<'PY'
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    url = os.environ["DATABASE_URL"]
    # asyncpg + Supavisor pooling: disable prepared-statement cache.
    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    async with engine.connect() as conn:
        version = (await conn.execute(text("select version()"))).scalar_one()
    await engine.dispose()
    print("    connected:", version.split(",")[0])

asyncio.run(main())
PY

echo "==> 2/6 Backing up the current local .env"
cp .env ".env.local-backup-$(date +%Y%m%d-%H%M%S)"

echo "==> 3/6 Writing the Supabase DATABASE_URL into .env"
python3 - "$SUPABASE_DB_URL" <<'PY'
import re, sys
url = sys.argv[1]
text = open(".env").read()
if re.search(r"^DATABASE_URL=.*$", text, flags=re.M):
    text = re.sub(r"^DATABASE_URL=.*$", f"DATABASE_URL={url}", text, flags=re.M)
else:
    text += f"\nDATABASE_URL={url}\n"
open(".env", "w").write(text)
print("    .env updated (git-ignored)")
PY

echo "==> 4/6 Applying all migrations to Supabase"
DATABASE_URL="$SUPABASE_DB_URL" uv run alembic upgrade head

echo "==> 5/6 Creating the admin profile"
ADMIN_ID="${MIGRATION_USER_ID:-7cab17f1-7861-4129-a102-820a9f1e7763}"
ADMIN_EMAIL="${ADMIN_EMAIL:-rasad2465@gmail.com}"
ADMIN_NAME="${ADMIN_NAME:-Asad Mushtaq}"
DATABASE_URL="$SUPABASE_DB_URL" ADMIN_ID="$ADMIN_ID" ADMIN_EMAIL="$ADMIN_EMAIL" ADMIN_NAME="$ADMIN_NAME" \
  uv run python - <<'PY'
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"],
                                 connect_args={"statement_cache_size": 0})
    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO crm.user_profiles (id, full_name, email, role, is_active)
            VALUES (:id, :name, :email, 'admin', true)
            ON CONFLICT (id) DO UPDATE
              SET role='admin', is_active=true, email=EXCLUDED.email
        """), {"id": os.environ["ADMIN_ID"], "name": os.environ["ADMIN_NAME"],
               "email": os.environ["ADMIN_EMAIL"]})
    await engine.dispose()
    print("    admin profile ready:", os.environ["ADMIN_EMAIL"])

asyncio.run(main())
PY

echo "==> 6/6 Importing the MPSTT workbook (if present)"
if [[ -d ../MPSTT_CRM ]]; then
  DATABASE_URL="$SUPABASE_DB_URL" PYTHONPATH="$PWD" uv run python scripts/migrate_workbook.py || true
else
  echo "    ../MPSTT_CRM not found — skipping workbook import"
fi

echo
echo "Done. The CRM now uses the Supabase server database."
echo "Restart the backend:  uv run uvicorn app.main:app --host 127.0.0.1 --port 8100"
