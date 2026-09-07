#!/usr/bin/env python3
"""Book opening stock against variants that already exist.

Reads lines of `SKU,VARIANT_CODE,QUANTITY` from a file (blank lines and
`#` comments ignored) and posts each as an `opening` movement to MAIN, so
the stock ledger distinguishes an opening count from a later correction.

Usage:
    TOKEN=<admin access token> uv run python scripts/load_opening_stock.py lines.csv --confirm
"""
import os
import sys
from pathlib import Path

import httpx

API = os.environ.get("API_BASE", "https://mpstt-crm-api-production.up.railway.app")
WAREHOUSE_CODE = "MAIN"
REASON = "Opening stock count provided by MPSTT"


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--confirm" not in sys.argv or not args:
        print("Usage: TOKEN=... load_opening_stock.py <lines.csv> --confirm")
        return 2
    token = os.environ.get("TOKEN")
    if not token:
        print("TOKEN is not set.")
        return 2

    lines = []
    for raw in Path(args[0]).read_text().splitlines():
        raw = raw.split("#")[0].strip()
        if not raw:
            continue
        sku, code, qty = (part.strip() for part in raw.split(","))
        lines.append((sku, code, qty))

    c = httpx.Client(base_url=API, headers={"Authorization": f"Bearer {token}"}, timeout=60)

    def data(resp: httpx.Response) -> dict:
        if resp.status_code >= 400:
            raise SystemExit(f"{resp.request.method} {resp.request.url.path} -> "
                             f"{resp.status_code}: {resp.text[:300]}")
        return resp.json()["data"]

    warehouse = next(w for w in data(c.get("/api/v1/inventory/warehouses"))
                     if w["code"] == WAREHOUSE_CODE)
    products = {p["sku"]: p for p in data(c.get("/api/v1/catalogue/products",
                                                params={"page_size": 100}))}

    variants: dict[tuple[str, str], dict] = {}
    for sku in {s for s, _, _ in lines}:
        detail = data(c.get(f"/api/v1/catalogue/products/{products[sku]['id']}"))
        for v in detail.get("variants", []):
            variants[(sku, v["variant_code"])] = v

    for sku, code, qty in lines:
        variant = variants.get((sku, code))
        if variant is None:
            raise SystemExit(f"No variant {code} on {sku}")
        balance = data(c.post("/api/v1/inventory/adjustments", json={
            "warehouse_id": warehouse["id"],
            "product_variant_id": variant["id"],
            "quantity": qty,
            "reason": REASON,
            "reference": "Opening stock",
            "movement_type": "opening",
        }))
        print(f"  {products[sku]['name']:16} {variant['variant_name']:24} "
              f"+{qty:>4}  on_hand={balance['on_hand']}")

    print(f"\nDone. {len(lines)} lines booked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
