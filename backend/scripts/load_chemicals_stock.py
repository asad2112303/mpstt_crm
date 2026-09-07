#!/usr/bin/env python3
"""Create the fragranced Air Freshener / Hand Wash variants and stock them.

The workbook only knew Air Freshener as Manual/Automatic and Hand Wash by
size; MPSTT actually holds them by fragrance. Adds a `fragrance` attribute to
the Cleaning Chemicals category, creates the six real variants, and books
their opening counts.

Confirmed with MPSTT before running: the three air fresheners are Manual
cans, and Hand Wash "Classic" (5L) is a different product from "Classic Care"
(500ml) rather than the same one written two ways.

Usage:
    TOKEN=<admin access token> uv run python scripts/load_chemicals_stock.py --confirm
"""
import os
import sys

import httpx

API = os.environ.get("API_BASE", "https://mpstt-crm-api-production.up.railway.app")
CATEGORY_NAME = "Cleaning Chemicals"
WAREHOUSE_CODE = "MAIN"
REASON = "Opening stock count provided by MPSTT"

# sku, variant_code, variant_name, uom, attributes, quantity
LINES = [
    ("PROD-008", "AF-MAN-PINK-ROSE", "Manual — Pink Rose", "CAN",
     {"size": "30 ml", "type": "Manual", "fragrance": "Pink Rose"}, "9"),
    ("PROD-008", "AF-MAN-DUNHILL", "Manual — Dunhill", "CAN",
     {"size": "30 ml", "type": "Manual", "fragrance": "Dunhill"}, "6"),
    ("PROD-008", "AF-MAN-LAVENDER", "Manual — Lavender", "CAN",
     {"size": "30 ml", "type": "Manual", "fragrance": "Lavender"}, "8"),
    ("PROD-010", "HW-500-CLASSIC-CARE", "500 ml — Classic Care", "BTL",
     {"size": "500 ml", "fragrance": "Classic Care"}, "18"),
    ("PROD-010", "HW-500-LAVENDER", "500 ml — Lavender", "BTL",
     {"size": "500 ml", "fragrance": "Lavender"}, "19"),
    ("PROD-010", "HW-5L-CLASSIC", "5 litre — Classic", "BTL",
     {"size": "5 litre", "fragrance": "Classic"}, "1"),
]


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
    uoms = {u["code"]: u["id"] for u in data(c.get("/api/v1/catalogue/uoms"))}
    products = {p["sku"]: p for p in data(c.get("/api/v1/catalogue/products",
                                                params={"page_size": 100}))}
    category = next(x for x in data(c.get("/api/v1/catalogue/categories"))
                    if x["name"] == CATEGORY_NAME)

    # --- make room for fragrance ------------------------------------------
    attributes = list(category["attribute_schema"]["attributes"])
    if not any(a["key"] == "fragrance" for a in attributes):
        attributes.append({"key": "fragrance", "label": "Fragrance", "type": "text"})
        data(c.patch(f"/api/v1/catalogue/categories/{category['id']}", json={
            "name": category["name"],
            "description": category.get("description"),
            "attribute_schema": {"attributes": attributes},
            "is_active": category["is_active"],
        }))
        print("  category: added 'fragrance' attribute")
    else:
        print("  category: 'fragrance' already present")

    # --- create variants ---------------------------------------------------
    existing: dict[tuple[str, str], dict] = {}
    for sku in {line[0] for line in LINES}:
        detail = data(c.get(f"/api/v1/catalogue/products/{products[sku]['id']}"))
        for v in detail.get("variants", []):
            existing[(sku, v["variant_code"])] = v

    ids: dict[str, str] = {}
    for sku, code, name, uom, attrs, _qty in LINES:
        if (sku, code) in existing:
            ids[code] = existing[(sku, code)]["id"]
            print(f"  variant exists  {name}")
            continue
        v = data(c.post(f"/api/v1/catalogue/products/{products[sku]['id']}/variants", json={
            "variant_code": code,
            "variant_name": name,
            "uom_id": uoms[uom],
            "attributes": attrs,
        }))
        ids[code] = v["id"]
        print(f"  variant created {name:24} {code}")

    # --- opening stock -----------------------------------------------------
    for sku, code, name, uom, _attrs, qty in LINES:
        balance = data(c.post("/api/v1/inventory/adjustments", json={
            "warehouse_id": warehouse["id"],
            "product_variant_id": ids[code],
            "quantity": qty,
            "reason": REASON,
            "reference": "Opening stock",
            "movement_type": "opening",
        }))
        print(f"  {products[sku]['name']:16} {name:24} +{qty:>3} {uom}  "
              f"on_hand={balance['on_hand']}")

    print(f"\nDone. {len(LINES)} variants created and stocked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
