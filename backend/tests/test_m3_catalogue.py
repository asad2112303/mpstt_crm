"""M3 exit-gate tests: attribute validation, uniqueness, permissions, search."""
import uuid

import pytest

from tests.helpers import auth_headers, seed_profile


@pytest.fixture()
async def admin_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="admin"))


@pytest.fixture()
async def user_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="user"))


async def seed_catalogue(client, admin_headers) -> dict:
    """Create category + uom + product, return their ids."""
    resp = await client.post(
        "/api/v1/catalogue/categories",
        headers=admin_headers,
        json={
            "name": f"Waste Bags {uuid.uuid4().hex[:6]}",
            "attribute_schema": {"attributes": [
                {"key": "colour", "label": "Colour", "type": "select", "required": True,
                 "options": ["Yellow", "Red"]},
                {"key": "thickness_micron", "label": "Thickness", "type": "number",
                 "min": 5, "max": 500},
            ]},
        },
    )
    assert resp.status_code == 201, resp.text
    category = resp.json()["data"]

    resp = await client.post(
        "/api/v1/catalogue/uoms",
        headers=admin_headers,
        json={"code": f"PC{uuid.uuid4().hex[:4]}", "name": "Pieces"},
    )
    assert resp.status_code == 201
    uom = resp.json()["data"]

    resp = await client.post(
        "/api/v1/catalogue/products",
        headers=admin_headers,
        json={
            "sku": f"WB-{uuid.uuid4().hex[:8]}",
            "name": "Hospital Waste Bag",
            "category_id": category["id"],
            "base_uom_id": uom["id"],
            "tax_rate": "18.00",
        },
    )
    assert resp.status_code == 201, resp.text
    product = resp.json()["data"]
    return {"category": category, "uom": uom, "product": product}


async def test_user_cannot_manage_master_structure(client, user_headers):
    resp = await client.post(
        "/api/v1/catalogue/categories", headers=user_headers, json={"name": "Nope"}
    )
    assert resp.status_code == 403
    resp = await client.post(
        "/api/v1/catalogue/uoms", headers=user_headers, json={"code": "X", "name": "X"}
    )
    assert resp.status_code == 403


async def test_invalid_attribute_schema_rejected(client, admin_headers):
    resp = await client.post(
        "/api/v1/catalogue/categories",
        headers=admin_headers,
        json={
            "name": f"Bad {uuid.uuid4().hex[:6]}",
            "attribute_schema": {"attributes": [{"key": "colour", "type": "select"}]},
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_FAILED"


async def test_variant_attributes_validated_against_category(client, admin_headers):
    ids = await seed_catalogue(client, admin_headers)
    product_id = ids["product"]["id"]

    # Unknown key
    resp = await client.post(
        f"/api/v1/catalogue/products/{product_id}/variants",
        headers=admin_headers,
        json={"variant_code": f"V{uuid.uuid4().hex[:6]}", "variant_name": "Bad",
              "attributes": {"colour": "Yellow", "made_up": 1}},
    )
    assert resp.status_code == 422
    assert "attributes.made_up" in resp.json()["error"]["field_errors"]

    # Missing required
    resp = await client.post(
        f"/api/v1/catalogue/products/{product_id}/variants",
        headers=admin_headers,
        json={"variant_code": f"V{uuid.uuid4().hex[:6]}", "variant_name": "Bad2",
              "attributes": {"thickness_micron": 25}},
    )
    assert resp.status_code == 422
    assert "attributes.colour" in resp.json()["error"]["field_errors"]

    # Option not allowed / number out of range
    resp = await client.post(
        f"/api/v1/catalogue/products/{product_id}/variants",
        headers=admin_headers,
        json={"variant_code": f"V{uuid.uuid4().hex[:6]}", "variant_name": "Bad3",
              "attributes": {"colour": "Purple", "thickness_micron": 9000}},
    )
    assert resp.status_code == 422
    errs = resp.json()["error"]["field_errors"]
    assert "attributes.colour" in errs and "attributes.thickness_micron" in errs

    # Valid variant
    resp = await client.post(
        f"/api/v1/catalogue/products/{product_id}/variants",
        headers=admin_headers,
        json={"variant_code": f"V{uuid.uuid4().hex[:6]}", "variant_name": "Yellow 30x36 25mic",
              "attributes": {"colour": "Yellow", "thickness_micron": 25}},
    )
    assert resp.status_code == 201, resp.text


async def test_sku_and_variant_uniqueness(client, admin_headers):
    ids = await seed_catalogue(client, admin_headers)
    product = ids["product"]

    resp = await client.post(
        "/api/v1/catalogue/products",
        headers=admin_headers,
        json={"sku": product["sku"], "name": "Duplicate SKU",
              "category_id": ids["category"]["id"], "base_uom_id": ids["uom"]["id"]},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "DUPLICATE_SKU"

    code = f"V{uuid.uuid4().hex[:6]}"
    body = {"variant_code": code, "variant_name": "Same Name", "attributes": {"colour": "Red"}}
    resp = await client.post(
        f"/api/v1/catalogue/products/{product['id']}/variants", headers=admin_headers, json=body
    )
    assert resp.status_code == 201
    body["variant_code"] = f"V{uuid.uuid4().hex[:6]}"
    resp = await client.post(
        f"/api/v1/catalogue/products/{product['id']}/variants", headers=admin_headers, json=body
    )
    assert resp.status_code == 409


async def test_deactivate_instead_of_delete(client, admin_headers):
    ids = await seed_catalogue(client, admin_headers)
    product_id = ids["product"]["id"]
    resp = await client.patch(
        f"/api/v1/catalogue/products/{product_id}", headers=admin_headers,
        json={"is_active": False},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["is_active"] is False
    # No DELETE route exists.
    resp = await client.delete(f"/api/v1/catalogue/products/{product_id}", headers=admin_headers)
    assert resp.status_code == 405


async def test_search_matches_product_and_variant(client, admin_headers):
    ids = await seed_catalogue(client, admin_headers)
    product = ids["product"]
    resp = await client.post(
        f"/api/v1/catalogue/products/{product['id']}/variants",
        headers=admin_headers,
        json={"variant_code": f"YB-{uuid.uuid4().hex[:6]}", "variant_name": "Yellow Jumbo",
              "attributes": {"colour": "Yellow"}},
    )
    assert resp.status_code == 201

    resp = await client.get(
        "/api/v1/catalogue/search", headers=admin_headers, params={"q": "Yellow Jumbo"}
    )
    assert resp.status_code == 200
    hits = resp.json()["data"]
    assert any(h["product_id"] == product["id"] for h in hits)

    # Inactive product disappears from search.
    await client.patch(
        f"/api/v1/catalogue/products/{product['id']}", headers=admin_headers,
        json={"is_active": False},
    )
    resp = await client.get(
        "/api/v1/catalogue/search", headers=admin_headers, params={"q": "Yellow Jumbo"}
    )
    assert all(h["product_id"] != product["id"] for h in resp.json()["data"])


async def test_apply_templates_seeds_categories_and_uoms(client, admin_headers):
    resp = await client.post("/api/v1/catalogue/categories/apply-templates", headers=admin_headers)
    assert resp.status_code == 200
    resp = await client.get("/api/v1/catalogue/categories", headers=admin_headers)
    names = {c["name"] for c in resp.json()["data"]}
    assert {"Waste Bags", "Containers & Bins", "Safety Supplies"} <= names
    resp = await client.get("/api/v1/catalogue/uoms", headers=admin_headers)
    codes = {u["code"] for u in resp.json()["data"]}
    assert {"PCS", "CTN", "KG"} <= codes
    # Idempotent
    resp = await client.post("/api/v1/catalogue/categories/apply-templates", headers=admin_headers)
    assert resp.json()["data"]["created_categories"] == []


async def test_product_pagination_and_filter(client, admin_headers):
    ids = await seed_catalogue(client, admin_headers)
    resp = await client.get(
        "/api/v1/catalogue/products", headers=admin_headers,
        params={"page": 1, "page_size": 5, "category_id": ids["category"]["id"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["page_size"] == 5
    assert body["meta"]["total"] >= 1
