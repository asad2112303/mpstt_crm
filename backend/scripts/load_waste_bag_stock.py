#!/usr/bin/env python3
"""Create the real Waste Bag variants and load their opening stock.

The workbook could only say "Waste Bag — Standard (confirm sizes)"; these are
the actual colour/size lines MPSTT holds. Runs through the API so the normal
rules and audit trail apply rather than writing to tables directly.

The `-S` / `-G` suffixes are kept verbatim in the size attribute and the
variant name, because their meaning was not stated and guessing would bury a
wrong assumption in the catalogue.

Usage:
    TOKEN=<admin access token> uv run python scripts/load_waste_bag_stock.py --confirm
"""
import os
import sys

import httpx

API = os.environ.get("API_BASE", "https://mpstt-crm-api-production.up.railway.app")
PRODUCT_SKU = "PROD-013"
CATEGORY_NAME = "Bags & Utility Supplies"
WAREHOUSE_CODE = "MAIN"
REASON = "Opening stock count provided by MPSTT"

# (colour, size, quantity_kg) — exactly as supplied.
LINES = [
    ("White", "15L-S", "52"),
    ("White", "30L-S", "4"),
    ("Blue", "30L", "54"),
    ("Blue", "15L", "10"),
    ("White", "30L", "25"),
    ("Red", "45L", "25"),
    ("Yellow", "30L", "50"),
    ("Yellow", "15L", "25"),
    ("Red", "15L", "25"),
    ("White", "15L-G", "25"),
    ("Red", "30L", "25"),
]
CODE = {"White": "WHT", "Blue": "BLU", "Red": "RED", "Yellow": "YEL"}


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

    # --- resolve product, category, warehouse, uom -------------------------
    products = data(c.get("/api/v1/catalogue/products", params={"page_size": 50}))
    product = next(p for p in products if p["sku"] == PRODUCT_SKU)
    categories = data(c.get("/api/v1/catalogue/categories"))
    category = next(x for x in categories if x["name"] == CATEGORY_NAME)
    warehouses = data(c.get("/api/v1/inventory/warehouses"))
    warehouse = next(w for w in warehouses if w["code"] == WAREHOUSE_CODE)
    uoms = data(c.get("/api/v1/catalogue/uoms"))
    kg = next(u for u in uoms if u["code"] == "KG")
    print(f"product={product['name']} category={category['name']} warehouse={warehouse['code']}")

    # --- make room for colour on the category ------------------------------
    keys = {a["key"] for a in category["attribute_schema"]["attributes"]}
    if "colour" not in keys:
        attributes = list(category["attribute_schema"]["attributes"])
        attributes.insert(0, {"key": "colour", "label": "Colour", "type": "text"})
        data(c.patch(f"/api/v1/catalogue/categories/{category['id']}", json={
            "name": category["name"],
            "description": category.get("description"),
            "attribute_schema": {"attributes": attributes},
            "is_active": category["is_active"],
        }))
        print("  category: added 'colour' attribute")
    else:
        print("  category: 'colour' already present")

    # --- create the variants ----------------------------------------------
    existing = {v["variant_code"]: v for v in
                data(c.get(f"/api/v1/catalogue/products/{product['id']}")).get("variants", [])}
    created: dict[str, str] = {}
    for colour, size, _qty in LINES:
        code = f"WB-{CODE[colour]}-{size}"
        name = f"{colour} {size}"
        if code in existing:
            created[code] = existing[code]["id"]
            print(f"  variant exists  {name}")
            continue
        v = data(c.post(f"/api/v1/catalogue/products/{product['id']}/variants", json={
            "variant_code": code,
            "variant_name": name,
            "uom_id": kg["id"],
            "attributes": {"colour": colour, "size": size},
        }))
        created[code] = v["id"]
        print(f"  variant created {name:16} {code}")

    # --- opening stock -----------------------------------------------------
    total = 0.0
    for colour, size, qty in LINES:
        code = f"WB-{CODE[colour]}-{size}"
        balance = data(c.post("/api/v1/inventory/adjustments", json={
            "warehouse_id": warehouse["id"],
            "product_variant_id": created[code],
            "quantity": qty,
            "reason": REASON,
            "reference": "Opening stock",
            "movement_type": "opening",
        }))
        total += float(qty)
        print(f"  stocked {colour} {size:6} {qty:>4} KG   on_hand={balance['on_hand']}")

    # --- retire the placeholder -------------------------------------------
    placeholder = existing.get(f"{PRODUCT_SKU}-STD")
    if placeholder and placeholder["is_active"]:
        data(c.patch(f"/api/v1/catalogue/variants/{placeholder['id']}", json={"is_active": False}))
        print("  placeholder 'Standard (confirm sizes)' deactivated")

    print(f"\nDone. {len(LINES)} variants stocked, {total:g} KG total.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
