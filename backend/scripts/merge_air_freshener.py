#!/usr/bin/env python3
"""Collapse the fragranced Air Freshener variants back into one stock line.

MPSTT tracks air freshener as a single item, not per fragrance. The
per-fragrance counts are moved onto the plain Manual variant and the
fragrance variants are deactivated.

Nothing is destroyed: each transfer is a stock movement, so the original
9 / 6 / 8 split stays readable in the Movements ledger and the variants can
be reactivated if the split is wanted again.

Usage:
    TOKEN=<admin access token> uv run python scripts/merge_air_freshener.py --confirm
"""
import os
import sys

import httpx

API = os.environ.get("API_BASE", "https://mpstt-crm-api-production.up.railway.app")
PRODUCT_SKU = "PROD-008"
KEEP_CODE = "VAR-0016"  # plain "Manual"
MERGE_CODES = ["AF-MAN-PINK-ROSE", "AF-MAN-DUNHILL", "AF-MAN-LAVENDER"]
WAREHOUSE_CODE = "MAIN"


def main() -> int:
    if "--confirm" not in sys.argv:
        print("Refusing to run without --confirm.")
        return 2
    token = os.environ.get("TOKEN")
    if not token:
        print("TOKEN is not set.")
        return 2

    c = httpx.Client(base_url=API, headers={"Authorization": f"Bearer {token}"}, timeout=60)

    def data(resp: httpx.Response) -> dict:
        if resp.status_code >= 400:
            raise SystemExit(f"{resp.request.method} {resp.request.url.path} -> "
                             f"{resp.status_code}: {resp.text[:300]}")
        return resp.json()["data"]

    warehouse = next(w for w in data(c.get("/api/v1/inventory/warehouses"))
                     if w["code"] == WAREHOUSE_CODE)
    product = next(p for p in data(c.get("/api/v1/catalogue/products", params={"page_size": 100}))
                   if p["sku"] == PRODUCT_SKU)
    variants = {v["variant_code"]: v
                for v in data(c.get(f"/api/v1/catalogue/products/{product['id']}"))["variants"]}
    balances = {b["variant_code"]: b for b in data(c.get("/api/v1/inventory/balances"))
                if b["sku"] == PRODUCT_SKU}

    def adjust(variant: dict, qty: str, reason: str) -> dict:
        return data(c.post("/api/v1/inventory/adjustments", json={
            "warehouse_id": warehouse["id"],
            "product_variant_id": variant["id"],
            "quantity": qty,
            "reason": reason,
            "reference": "Merge to single line",
            "movement_type": "adjustment",
        }))

    total = 0.0
    for code in MERGE_CODES:
        variant = variants[code]
        on_hand = float(balances.get(code, {}).get("on_hand", 0))
        if on_hand:
            adjust(variant, f"-{on_hand:g}",
                   f"Merged into a single Air Freshener line (was {variant['variant_name']})")
            total += on_hand
            print(f"  moved out {on_hand:g} from {variant['variant_name']}")
        data(c.patch(f"/api/v1/catalogue/variants/{variant['id']}", json={"is_active": False}))
        print(f"  deactivated {variant['variant_name']}")

    keep = variants[KEEP_CODE]
    if total:
        balance = adjust(keep, f"{total:g}",
                         "Merged Pink Rose, Dunhill and Lavender into one Air Freshener line")
        print(f"\n  {keep['variant_name']}: on_hand={balance['on_hand']}")

    remaining = [v for v in data(c.get(f"/api/v1/catalogue/products/{product['id']}"))["variants"]
                 if v["is_active"]]
    print(f"  active Air Freshener variants: {[v['variant_name'] for v in remaining]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
