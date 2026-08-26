#!/usr/bin/env python3
"""Back up all private Supabase Storage buckets to a local directory.

Usage:
    SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... python storage_backup.py --out ./backup

Database backups do NOT contain Storage objects; run this separately.
"""
import argparse
import os
import sys
from pathlib import Path

import httpx

BUCKETS = ["commercial-documents", "delivery-pod", "payment-proofs"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not base or not key:
        print("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required", file=sys.stderr)
        return 1
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    out_root = Path(args.out)

    total = 0
    with httpx.Client(timeout=60) as client:
        for bucket in BUCKETS:
            offset = 0
            while True:
                resp = client.post(
                    f"{base}/storage/v1/object/list/{bucket}",
                    headers=headers,
                    json={"prefix": "", "limit": 100, "offset": offset,
                          "sortBy": {"column": "name", "order": "asc"}},
                )
                resp.raise_for_status()
                objects = [o for o in resp.json() if o.get("id")]
                if not objects:
                    break
                for obj in objects:
                    name = obj["name"]
                    dest = out_root / bucket / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    download = client.get(
                        f"{base}/storage/v1/object/{bucket}/{name}", headers=headers
                    )
                    download.raise_for_status()
                    dest.write_bytes(download.content)
                    total += 1
                offset += len(objects)
            print(f"{bucket}: done")
    print(f"Backed up {total} objects to {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
