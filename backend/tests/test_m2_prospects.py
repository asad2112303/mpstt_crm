"""M2 exit-gate tests: progressive capture, stage guards, duplicates, queue."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tests.helpers import auth_headers, seed_profile


@pytest.fixture()
async def user_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="user"))


async def create_prospect(client, headers, **overrides) -> dict:
    body = {
        "name": f"Shifa Hospital {uuid.uuid4().hex[:6]}",
        "org_type": "hospital",
        "city": "Islamabad",
        "source": "field_visit",
        # Suite runs create many similar names; duplicate flow is tested explicitly.
        "confirm_duplicate": True,
        **overrides,
    }
    resp = await client.post("/api/v1/prospects", headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def test_minimal_create_and_progressive_enrichment(client, user_headers):
    prospect = await create_prospect(client, user_headers)
    assert prospect["org_code"].startswith("ORG-")
    assert prospect["lifecycle_status"] == "prospect"
    assert prospect["prospect_profile"]["stage"] == "targeted"

    resp = await client.patch(
        f"/api/v1/prospects/{prospect['id']}", headers=user_headers,
        json={"phone": "0301-2345678", "area": "G-8", "next_action_summary": "Call procurement"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["prospect_profile"]["next_action_summary"] == "Call procurement"


async def test_duplicate_warning_without_auto_merge(client, user_headers):
    name = f"Quaid Hospital {uuid.uuid4().hex[:6]}"
    first = await create_prospect(client, user_headers, name=name, phone="0300-1112223")

    resp = await client.post(
        "/api/v1/prospects", headers=user_headers,
        json={"name": name, "org_type": "hospital", "phone": "0300 111 2223",
              "confirm_duplicate": False},
    )
    assert resp.status_code == 409
    err = resp.json()["error"]
    assert err["code"] == "DUPLICATE_SUSPECTED"
    assert err["field_errors"]["duplicates"]

    # Explicit confirmation creates a separate record (never merged).
    second = await create_prospect(
        client, user_headers, name=name, phone="0300 111 2223", confirm_duplicate=True
    )
    assert second["id"] != first["id"]


async def test_phone_normalization_matches_search(client, user_headers):
    prospect = await create_prospect(client, user_headers, phone="0345-9990001")
    resp = await client.get(
        "/api/v1/prospects", headers=user_headers, params={"search": "+92 345 9990001"}
    )
    assert any(p["id"] == prospect["id"] for p in resp.json()["data"])


async def test_won_stage_cannot_be_patched(client, user_headers):
    prospect = await create_prospect(client, user_headers)
    resp = await client.patch(
        f"/api/v1/prospects/{prospect['id']}", headers=user_headers, json={"stage": "won"}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "WON_IS_NOT_MANUAL"


async def test_lost_and_deferred_require_reason(client, user_headers):
    prospect = await create_prospect(client, user_headers)
    resp = await client.patch(
        f"/api/v1/prospects/{prospect['id']}", headers=user_headers, json={"stage": "lost"}
    )
    assert resp.status_code == 422

    resp = await client.patch(
        f"/api/v1/prospects/{prospect['id']}", headers=user_headers,
        json={"stage": "lost", "lost_reason": "Chose a cheaper supplier"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["prospect_profile"]["stage"] == "lost"


async def test_activity_advances_stage_and_touches_profile(client, user_headers):
    prospect = await create_prospect(client, user_headers)
    resp = await client.post(
        f"/api/v1/prospects/{prospect['id']}/activities", headers=user_headers,
        json={
            "activity_type": "visit",
            "outcome": "Met procurement officer",
            "next_action_title": "Send waste bag samples",
            "next_action_due_at": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
        },
    )
    assert resp.status_code == 201, resp.text

    resp = await client.get(f"/api/v1/prospects/{prospect['id']}", headers=user_headers)
    profile = resp.json()["data"]["prospect_profile"]
    assert profile["stage"] == "visited"
    assert profile["last_activity_at"] is not None
    assert profile["next_action_summary"] == "Send waste bag samples"

    resp = await client.get(f"/api/v1/prospects/{prospect['id']}/tasks", headers=user_headers)
    assert len(resp.json()["data"]) == 1


async def test_missing_next_action_appears_in_exception_queue(client, user_headers):
    prospect = await create_prospect(client, user_headers)
    resp = await client.get(
        "/api/v1/prospects/action-queue", headers=user_headers,
        params={"missing_next_action": True},
    )
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert any(r["organization_id"] == prospect["id"] for r in rows)

    # Adding an open task removes it from the exception filter.
    await client.post(
        f"/api/v1/prospects/{prospect['id']}/tasks", headers=user_headers,
        json={"title": "Call back", "due_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
    )
    resp = await client.get(
        "/api/v1/prospects/action-queue", headers=user_headers,
        params={"missing_next_action": True},
    )
    assert all(r["organization_id"] != prospect["id"] for r in resp.json()["data"])


async def test_requirement_profiles_replace_and_advance_stage(client, user_headers, db_session):
    from tests.test_m3_catalogue import seed_catalogue

    admin_headers = auth_headers(await seed_profile(db_session, role="admin"))
    ids = await seed_catalogue(client, admin_headers)
    prospect = await create_prospect(client, user_headers)

    resp = await client.put(
        f"/api/v1/prospects/{prospect['id']}/product-profiles", headers=user_headers,
        json=[{
            "product_id": ids["product"]["id"],
            "frequency": "monthly",
            "min_quantity": "100",
            "max_quantity": "500",
            "current_supplier": "Existing Vendor",
            "current_rate": "12.50",
        }],
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["data"]) == 1

    resp = await client.get(f"/api/v1/prospects/{prospect['id']}", headers=user_headers)
    assert resp.json()["data"]["prospect_profile"]["stage"] == "requirement_collected"


async def test_sample_lifecycle(client, user_headers, db_session):
    from tests.test_m3_catalogue import seed_catalogue

    admin_headers = auth_headers(await seed_profile(db_session, role="admin"))
    ids = await seed_catalogue(client, admin_headers)
    prospect = await create_prospect(client, user_headers)

    resp = await client.post(
        f"/api/v1/prospects/{prospect['id']}/samples", headers=user_headers,
        json={"product_id": ids["product"]["id"], "quantity": "10",
              "receiver_name": "Store Incharge", "feedback_due_date": "2026-09-15"},
    )
    assert resp.status_code == 201, resp.text
    sample = resp.json()["data"]
    assert sample["status"] == "issued"

    resp = await client.get(f"/api/v1/prospects/{prospect['id']}", headers=user_headers)
    assert resp.json()["data"]["prospect_profile"]["stage"] == "sample_provided"

    resp = await client.patch(
        f"/api/v1/prospects/samples/{sample['id']}/feedback", headers=user_headers,
        json={"status": "feedback_received", "feedback": "Quality approved by matron"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "feedback_received"

    # Zero quantity rejected
    resp = await client.post(
        f"/api/v1/prospects/{prospect['id']}/samples", headers=user_headers,
        json={"product_id": ids["product"]["id"], "quantity": "0"},
    )
    assert resp.status_code == 422


async def test_branches_and_contacts_crud(client, user_headers):
    prospect = await create_prospect(client, user_headers)
    org_id = prospect["id"]

    resp = await client.post(
        f"/api/v1/organizations/{org_id}/branches", headers=user_headers,
        json={"branch_name": "Main Campus", "city": "Islamabad", "is_primary": True},
    )
    assert resp.status_code == 201
    branch = resp.json()["data"]

    resp = await client.post(
        f"/api/v1/organizations/{org_id}/contacts", headers=user_headers,
        json={"full_name": "Dr Khan", "designation": "Procurement Head",
              "phone_primary": "0333-7778889", "branch_id": branch["id"]},
    )
    assert resp.status_code == 201
    contact = resp.json()["data"]

    resp = await client.get(f"/api/v1/organizations/{org_id}/contacts", headers=user_headers)
    assert any(c["id"] == contact["id"] for c in resp.json()["data"])


async def test_price_history_no_overlap(client, user_headers, db_session):
    from tests.test_m3_catalogue import seed_catalogue

    admin_headers = auth_headers(await seed_profile(db_session, role="admin"))
    ids = await seed_catalogue(client, admin_headers)
    prospect = await create_prospect(client, user_headers)
    org_id = prospect["id"]

    resp = await client.post(
        f"/api/v1/organizations/{org_id}/prices", headers=user_headers,
        json={"product_id": ids["product"]["id"], "unit_price": "15.00",
              "effective_from": "2026-01-01"},
    )
    assert resp.status_code == 201, resp.text
    first = resp.json()["data"]

    # Overlapping open-ended period rejected.
    resp = await client.post(
        f"/api/v1/organizations/{org_id}/prices", headers=user_headers,
        json={"product_id": ids["product"]["id"], "unit_price": "14.00",
              "effective_from": "2026-06-01"},
    )
    assert resp.status_code == 422

    # Expire, then a new price starting later is accepted; history remains.
    resp = await client.post(f"/api/v1/organizations/prices/{first['id']}/expire",
                             headers=user_headers)
    assert resp.status_code == 200

    resp = await client.post(
        f"/api/v1/organizations/{org_id}/prices", headers=user_headers,
        json={"product_id": ids["product"]["id"], "unit_price": "14.00",
              "effective_from": "2099-01-01"},
    )
    assert resp.status_code == 201

    resp = await client.get(f"/api/v1/organizations/{org_id}/prices", headers=user_headers)
    assert len(resp.json()["data"]) == 2


async def test_prospect_list_excludes_customers_and_paginates(client, user_headers, db_session):
    prospect = await create_prospect(client, user_headers)
    # Manually flip to customer to verify the filter (conversion itself is M4).
    from sqlalchemy import text

    await db_session.execute(
        text("UPDATE crm.organizations SET lifecycle_status='customer' WHERE id=:id"),
        {"id": prospect["id"]},
    )
    await db_session.commit()

    resp = await client.get("/api/v1/prospects", headers=user_headers,
                            params={"page": 1, "page_size": 5})
    assert resp.status_code == 200
    assert all(p["id"] != prospect["id"] for p in resp.json()["data"])
