#!/usr/bin/env python3
"""Migrate the MPSTT_CRM staging workbook (CSV export) into the CRM database.

Reads the 13-sheet workbook from ../MPSTT_CRM/ and imports, in ONE transaction:

  07 Products / 08 Variants  -> categories, brands, UOMs, products, variants
                                (category attribute schemas built from the
                                variant attribute keys actually used)
  01 Customers               -> organizations + prospect profiles
                                (blueprint rule: default to Prospect; nothing
                                is auto-classified as Customer)
  02 Branches                -> organization_branches
  03 Contacts                -> organization_contacts (phones normalized)
  04 Product Profiles        -> organization_product_profiles (waste-bag
                                monthly consumption, assumption note kept)
  05 Customer Prices         -> organization_prices (historical source rates)
  06 Leads Opportunities     -> prospect stage + area
  09 Opening Inventory       -> warehouse only (sheet intentionally blank:
                                "Do not guess opening quantities")
  10 Opening Receivables     -> skipped (intentionally blank)
  11 Raw Current Clients     -> source archive only, not imported

Duplicate flags (possible_duplicate_of) are preserved in notes — records are
NEVER merged automatically. Re-running aborts if the workbook was already
imported. Usage:  uv run python scripts/migrate_workbook.py
"""
import asyncio
import csv
import os
import sys
import uuid
from datetime import date
from pathlib import Path

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:54322/mpstt_crm"
)

WORKBOOK = Path(__file__).resolve().parent.parent.parent / "MPSTT_CRM"
ADMIN_ID = uuid.UUID(os.environ.get("MIGRATION_USER_ID", "7cab17f1-7861-4129-a102-820a9f1e7763"))

ORG_TYPE_MAP = {
    "hospital": "hospital", "hospital / clinic": "hospital", "ngo - hospital": "hospital",
    "clinic": "clinic",
    "diagnostic centre": "laboratory", "diagnostics centre": "laboratory", "labs": "laboratory",
    "": "other",
}
STAGE_MAP = {
    "New Prospect": "targeted",
    "Contacted": "visited",
    "Meeting Completed": "visited",
    "Quotation Submitted": "quotation_sent",
    "Negotiation": "negotiation",
    # Frozen rule: 'won' is produced only by first-order conversion.
    "Won": "negotiation",
    "Lost / Deferred": "deferred",
}
STAGE_ORDER = ["targeted", "visited", "requirement_collected", "sample_provided",
               "quotation_sent", "negotiation"]
UOM_DEFS = {
    "Ream": ("REAM", 0), "Roll": ("ROLL", 0), "Pack": ("PACK", 0), "Bottle": ("BTL", 0),
    "Can": ("CAN", 0), "Bag": ("BAG", 0), "Box": ("BOX", 0), "KG": ("KG", 3),
    "Kg / Bag": ("KG", 3), "Piece": ("PCS", 0), "Ream ": ("REAM", 0), "Other": ("OTH", 0),
}


def read_sheet(filename: str, header_first: str) -> list[dict]:
    with open(WORKBOOK / filename, encoding="utf-8-sig") as f:
        data = list(csv.reader(f))
    header_i = next(i for i, r in enumerate(data) if r and r[0].strip() == header_first)
    header = [h.strip() for h in data[header_i]]
    rows = []
    for r in data[header_i + 1:]:
        if not r or not r[0].strip():
            continue
        rows.append({header[j]: (r[j].strip() if j < len(r) else "")
                     for j in range(len(header)) if header[j]})
    return rows


def note_join(*parts: str) -> str | None:
    text = " | ".join(p for p in parts if p)
    return text or None


async def main() -> int:
    from sqlalchemy import select
    from sqlalchemy import text as sql_text

    from app.core.db import dispose_engine, get_session_factory
    from app.models.catalogue import Brand, Product, ProductCategory, ProductVariant, UnitOfMeasure
    from app.models.inventory import Warehouse
    from app.models.organization import (
        Organization,
        OrganizationBranch,
        OrganizationContact,
        OrganizationPrice,
        OrganizationProductProfile,
        ProspectProfile,
    )
    from app.services.audit import write_audit
    from app.services.numbering import allocate_number
    from app.services.phone import normalize_phone

    customers = read_sheet("01 Customers-Table 1.csv", "customer_id")
    branches = read_sheet("02 Branches-Table 1.csv", "branch_id")
    contacts = read_sheet("03 Contacts-Table 1.csv", "contact_id")
    profiles = read_sheet("04 Customer Product Profiles-Table 1.csv", "profile_id")
    prices = read_sheet("05 Customer Prices-Table 1.csv", "price_id")
    opps = read_sheet("06 Leads Opportunities-Table 1.csv", "opportunity_id")
    products = read_sheet("07 Products-Table 1.csv", "product_id")
    variants = read_sheet("08 Product Variants-Table 1.csv", "variant_id")

    counts: dict[str, int] = {}
    async with get_session_factory()() as s:
        already = (
            await s.execute(sql_text(
                "SELECT count(*) FROM crm.organizations WHERE notes LIKE '%Migration ID CUST-%'"
            ))
        ).scalar_one()
        if already:
            print(f"ABORT: workbook already imported ({already} organizations carry a "
                  "Migration ID). Delete or review before re-running.")
            return 1

        # ---------- UOMs ----------
        uom_by_code: dict[str, UnitOfMeasure] = {
            u.code: u for u in (await s.execute(select(UnitOfMeasure))).scalars()
        }
        for label, (code, scale) in UOM_DEFS.items():
            if code not in uom_by_code:
                uom = UnitOfMeasure(
                    code=code, name=label.strip(),
                    category="count" if scale == 0 else "weight",
                    decimal_scale=scale,
                )
                s.add(uom)
                await s.flush()
                uom_by_code[code] = uom

        def uom_for(label: str) -> UnitOfMeasure:
            return uom_by_code[UOM_DEFS.get(label, ("OTH", 0))[0]]

        # ---------- categories (attribute schema from variant keys actually used) ----------
        attrs_by_product = {}
        for v in variants:
            keys = attrs_by_product.setdefault(v["product_id"], set())
            for a in (v["attribute_1"], v.get("attribute_2", "")):
                if a:
                    keys.add(a)
        cat_attr_keys: dict[str, set] = {}
        for p in products:
            cat_attr_keys.setdefault(p["category"], set()).update(
                attrs_by_product.get(p["product_id"], set())
            )
        categories: dict[str, ProductCategory] = {
            c.name: c for c in (await s.execute(select(ProductCategory))).scalars()
        }
        for name, keys in cat_attr_keys.items():
            schema = {"attributes": [
                {"key": k.lower().replace(" ", "_"), "label": k, "type": "text"}
                for k in sorted(keys)
            ]}
            if name not in categories:
                cat = ProductCategory(name=name, attribute_schema=schema,
                                      description="Migrated from MPSTT workbook")
                s.add(cat)
                await s.flush()
                categories[name] = cat
        counts["categories"] = len(cat_attr_keys)

        # ---------- brands ----------
        brands: dict[str, Brand] = {b.name: b for b in (await s.execute(select(Brand))).scalars()}
        for p in products:
            if p["brand"] and p["brand"] not in brands:
                brand = Brand(name=p["brand"])
                s.add(brand)
                await s.flush()
                brands[p["brand"]] = brand
        counts["brands"] = len({p["brand"] for p in products if p["brand"]})

        # ---------- products ----------
        prod_map: dict[str, Product] = {}
        for p in products:
            product = Product(
                sku=p["product_id"],
                name=p["product_name"],
                category_id=categories[p["category"]].id,
                brand_id=brands[p["brand"]].id if p["brand"] else None,
                base_uom_id=uom_for(p["unit_of_measure"]).id,
                description=note_join(p["specification_summary"],
                                      f"Data quality: {p['data_quality_status']}"),
                created_by=ADMIN_ID,
            )
            s.add(product)
            await s.flush()
            prod_map[p["product_id"]] = product
        counts["products"] = len(prod_map)

        # ---------- variants ----------
        n_var = 0
        for v in variants:
            attrs = {}
            if v["attribute_1"]:
                attrs[v["attribute_1"].lower().replace(" ", "_")] = v["value_1"]
            if v.get("attribute_2"):
                attrs[v["attribute_2"].lower().replace(" ", "_")] = v["value_2"]
            s.add(ProductVariant(
                product_id=prod_map[v["product_id"]].id,
                variant_code=v["variant_id"],
                variant_name=v["variant_name"],
                uom_id=uom_for(v["unit_of_measure"]).id,
                attributes=attrs,
                created_by=ADMIN_ID,
            ))
            n_var += 1
        # Sellable default variants for products the workbook left variant-less.
        for pid in prod_map:
            if pid not in attrs_by_product:
                s.add(ProductVariant(
                    product_id=prod_map[pid].id,
                    variant_code=f"{pid}-STD",
                    variant_name="Standard (confirm sizes)",
                    uom_id=prod_map[pid].base_uom_id,
                    attributes={},
                    created_by=ADMIN_ID,
                ))
                n_var += 1
        await s.flush()
        counts["variants"] = n_var

        # ---------- opportunities indexed for stage/area ----------
        opp_by_cust: dict[str, dict] = {}
        for o in opps:
            prev = opp_by_cust.get(o["customer_id"])
            stage = STAGE_MAP.get(o["stage"], "targeted")
            if prev is None or STAGE_ORDER.index(stage) > STAGE_ORDER.index(prev["_stage"]):
                opp_by_cust[o["customer_id"]] = {**o, "_stage": stage}
        cust_with_profile = {c["customer_id"] for c in profiles}

        # ---------- organizations + prospect profiles ----------
        org_map: dict[str, Organization] = {}
        for c in customers:
            opp = opp_by_cust.get(c["customer_id"])
            stage = opp["_stage"] if opp else (
                "requirement_collected" if c["customer_id"] in cust_with_profile else "targeted"
            )
            notes = note_join(
                f"Migration ID {c['customer_id']} (source: {c['source_sheet']} #{c['source_no']})",
                f"Workbook CRM status: {c['crm_status']}",
                f"Data quality: {c['data_quality_status']}" if c["data_quality_status"] else "",
                f"POSSIBLE DUPLICATE of {c['possible_duplicate_of']} — review, never auto-merged"
                if c["possible_duplicate_of"] else "",
                f"Source opportunity stage: {opp['stage']}" if opp and opp["stage"] == "Won" else "",
                c["notes"],
            )
            org = Organization(
                org_code=await allocate_number(s, "ORG"),
                name=c["legal_name"],
                org_type=ORG_TYPE_MAP.get(c["customer_type"].lower(), "other"),
                city=c["city"] or None,
                area=(opp.get("location_area") or None) if opp else None,
                source=f"MPSTT workbook / {c['source_sheet']}",
                notes=notes,
                created_by=ADMIN_ID,
            )
            s.add(org)
            await s.flush()
            s.add(ProspectProfile(
                organization_id=org.id,
                stage=stage,
                assigned_user_id=ADMIN_ID,
                deferred_reason="Source: Lost / Deferred" if stage == "deferred" else None,
            ))
            org_map[c["customer_id"]] = org
        counts["organizations"] = len(org_map)

        # ---------- branches ----------
        branch_map: dict[str, OrganizationBranch] = {}
        primary_seen: set = set()
        n_missing_org = 0
        for b in branches:
            org = org_map.get(b["customer_id"])
            if org is None:
                n_missing_org += 1
                continue
            branch = OrganizationBranch(
                organization_id=org.id,
                branch_name=b["branch_name"][:150],
                area=b["area"] or None,
                city=b["city"] or None,
                delivery_address=b["delivery_address"] or None,
                map_url=b["maps_url"] or None,
                route_cluster=b["route_cluster"] or None,
                is_primary=org.id not in primary_seen,
            )
            primary_seen.add(org.id)
            s.add(branch)
            await s.flush()
            branch_map[b["branch_id"]] = branch
        counts["branches"] = len(branch_map)

        # ---------- contacts ----------
        n_cont = 0
        for c in contacts:
            org = org_map.get(c["customer_id"])
            if org is None:
                continue
            branch = branch_map.get(c["branch_id"])
            s.add(OrganizationContact(
                organization_id=org.id,
                branch_id=branch.id if branch else None,
                full_name=c["full_name"] or "(name missing — from workbook)",
                designation=c["designation"] or None,
                department=c["department"] or None,
                phone_primary=c["phone_primary"] or None,
                phone_primary_normalized=normalize_phone(c["phone_primary"] or None),
                phone_alt=note_join(c["phone_alt_1"], c["phone_alt_2_plus"]),
                email=c["email"] or None,
                preferred_channel=(c["preferred_channel"] or None),
                is_primary=True,
            ))
            n_cont += 1
        counts["contacts"] = n_cont

        # ---------- product requirement profiles ----------
        n_prof = 0
        for p in profiles:
            org = org_map.get(p["customer_id"])
            product = prod_map.get(p["product_id"])
            if org is None or product is None:
                continue
            s.add(OrganizationProductProfile(
                organization_id=org.id,
                product_id=product.id,
                frequency="monthly",
                min_quantity=p["est_monthly_min"] or None,
                max_quantity=p["est_monthly_max"] or None,
                uom_id=uom_for(p["unit"]).id,
                current_supplier=p["current_supplier"] or None,
                current_rate=p["customer_current_rate"] or None,
                specification_notes=note_join(
                    f"Source consumption: {p['source_consumption_text']}",
                    p["assumption_note"],
                    f"Migration ID {p['profile_id']}",
                ),
            ))
            n_prof += 1
        counts["product_profiles"] = n_prof

        # ---------- customer prices ----------
        n_price = 0
        for p in prices:
            org = org_map.get(p["customer_id"])
            product = prod_map.get(p["product_id"])
            if org is None or product is None or not p["price"]:
                continue
            s.add(OrganizationPrice(
                organization_id=org.id,
                product_id=product.id,
                price_type="agreed",
                unit_price=p["price"],
                uom_id=uom_for(p["unit"]).id,
                effective_from=date.today(),
                source_reference=note_join(
                    f"Migration {p['price_id']} ({p['source_sheet']} #{p['source_no']})",
                    p["price_type"],
                )[:200],
                created_by=ADMIN_ID,
            ))
            n_price += 1
        counts["prices"] = n_price

        # ---------- warehouse from sheet 09 (quantities intentionally blank) ----------
        wh = (await s.execute(select(Warehouse).where(Warehouse.code == "MAIN"))).scalars().first()
        if wh is None:
            s.add(Warehouse(code="MAIN", name="Main Warehouse"))
        counts["warehouses"] = 1

        await s.flush()
        await write_audit(
            s, action="migration.workbook_imported", entity_type="import_batch",
            entity_id="MPSTT_CRM workbook",
            new={**counts,
                 "skipped": "09 Opening Inventory & 10 Opening Receivables blank by design; "
                            "11 Raw Current Clients archived as source only",
                 "branches_without_org": n_missing_org},
        )
        await s.commit()

    await dispose_engine()
    print("Imported:", counts)
    if n_missing_org:
        print(f"NOTE: {n_missing_org} branch rows referenced unknown customer ids and were skipped.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
