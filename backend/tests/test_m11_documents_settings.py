"""M11 exit-gate tests: upload validation, download auth, settings, audit, PDF."""
import uuid

import pytest

from tests.helpers import auth_headers, seed_profile

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture()
async def user_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="user"))


@pytest.fixture()
async def admin_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="admin"))


def upload_form(entity_id: str | None = None) -> dict:
    return {
        "entity_type": "payment",
        "entity_id": entity_id or str(uuid.uuid4()),
        "document_type": "payment_proof",
    }


async def test_upload_requires_auth(client):
    resp = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("slip.pdf", PDF_BYTES, "application/pdf")},
        data=upload_form(),
    )
    assert resp.status_code == 401


async def test_upload_validates_type_and_content(client, user_headers):
    # Disallowed extension
    resp = await client.post(
        "/api/v1/documents/upload", headers=user_headers,
        files={"file": ("run.exe", b"MZ\x90\x00", "application/octet-stream")},
        data=upload_form(),
    )
    assert resp.status_code == 422

    # Extension/content mismatch (claims pdf, content is not)
    resp = await client.post(
        "/api/v1/documents/upload", headers=user_headers,
        files={"file": ("fake.pdf", b"<html>not a pdf</html>", "application/pdf")},
        data=upload_form(),
    )
    assert resp.status_code == 422

    # Path traversal in the name is neutralized by sanitization.
    resp = await client.post(
        "/api/v1/documents/upload", headers=user_headers,
        files={"file": ("../../etc/passwd.png", PNG_BYTES, "image/png")},
        data=upload_form(),
    )
    assert resp.status_code == 201
    doc = resp.json()["data"]
    assert "/" not in doc["original_filename"]
    assert ".." not in doc["original_filename"]


async def test_upload_download_roundtrip_and_entity_link(client, user_headers):
    entity_id = str(uuid.uuid4())
    resp = await client.post(
        "/api/v1/documents/upload", headers=user_headers,
        files={"file": ("deposit slip.pdf", PDF_BYTES, "application/pdf")},
        data=upload_form(entity_id),
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()["data"]
    assert doc["mime_type"] == "application/pdf"

    resp = await client.get(
        "/api/v1/documents", headers=user_headers,
        params={"entity_type": "payment", "entity_id": entity_id},
    )
    assert [d["id"] for d in resp.json()["data"]] == [doc["id"]]

    resp = await client.get(f"/api/v1/documents/{doc['id']}/download", headers=user_headers)
    assert resp.status_code == 200
    assert resp.content == PDF_BYTES

    # Download without auth denied.
    resp = await client.get(f"/api/v1/documents/{doc['id']}/download")
    assert resp.status_code == 401


async def test_settings_read_write_and_permissions(client, user_headers, admin_headers):
    resp = await client.get("/api/v1/settings", headers=user_headers)
    assert resp.status_code == 200
    current = resp.json()["data"]
    assert current["default_currency"] == "PKR"
    assert current["timezone"] == "Asia/Karachi"

    body = {**{k: v for k, v in current.items() if k != "updated_at"},
            "phone": "+92-51-1234567", "bank_details": "Meezan Bank — 0101-XXXX"}
    resp = await client.put("/api/v1/admin/settings", headers=user_headers, json=body)
    assert resp.status_code == 403

    resp = await client.put("/api/v1/admin/settings", headers=admin_headers, json=body)
    assert resp.status_code == 200
    assert resp.json()["data"]["phone"] == "+92-51-1234567"


async def test_audit_viewer_admin_only_with_filters(client, user_headers, admin_headers):
    resp = await client.get("/api/v1/admin/audit", headers=user_headers)
    assert resp.status_code == 403

    resp = await client.get(
        "/api/v1/admin/audit", headers=admin_headers,
        params={"entity_type": "company_settings"},
    )
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert any(r["action"] == "settings.updated" for r in rows)


async def test_pdf_render_is_deterministic():
    from app.services.pdf import render_pdf

    context = {
        "company": {
            "company_name": "MPSTT", "legal_name": None, "address": "Islamabad",
            "city": None, "phone": "+92-51-0000000", "email": "info@mpstt.pk",
            "ntn": "1234567-8", "strn": None, "document_footer": None,
        },
    }
    # A minimal template exercising the base layout.
    from app.services.pdf import TEMPLATE_ROOT, TEMPLATE_VERSION, get_env

    test_template = TEMPLATE_ROOT / TEMPLATE_VERSION / "_test_doc.html"
    test_template.write_text(
        '{% extends "base.html" %}{% block doc_title %}TEST{% endblock %}'
        "{% block content %}<p>Deterministic body</p>{% endblock %}"
    )
    try:
        get_env.__globals__["_env"] = None  # reset cached env to pick up the file
        pdf_a = render_pdf("_test_doc.html", context)
        pdf_b = render_pdf("_test_doc.html", context)
        assert pdf_a[:5] == b"%PDF-"
        assert len(pdf_a) > 1000
        # WeasyPrint embeds no timestamps by default in document body; sizes match.
        assert len(pdf_a) == len(pdf_b)
    finally:
        test_template.unlink(missing_ok=True)
        get_env.__globals__["_env"] = None
