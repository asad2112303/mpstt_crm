"""Starting categories and selling units for billing

The billing brief names the categories the business actually sells (waste bags,
dustbins, cleaning products, stationery, other supplies) and the units they
sell in (piece, packet, roll, kilogram). Seeding them means a user can raise a
bill on day one without configuring master data first.

Everything here is editable afterwards and inserted idempotently, so an
existing deployment that already has these names keeps its own rows.

Note on units: no conversion factors are defined between piece, packet, roll
and kilogram, and none are inferred. A packet is never silently turned into
pieces — the brief requires an explicit configured conversion, and until one
exists each unit stands alone.

Revision ID: 0016_billing_seed
Revises: 0015_direct_billing
Create Date: 2026-09-26
"""
import json
from collections.abc import Sequence

from alembic import op

revision: str = '0016_billing_seed'
down_revision: str | None = '0015_direct_billing'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLOURS = ["Red", "Yellow", "Black", "White", "Blue", "Green", "Other"]

CATEGORIES = [
    (
        "Waste Bags",
        "Clinical, general and biohazard waste bags.",
        {
            "attributes": [
                {
                    "key": "bag_type", "label": "Bag type", "type": "select",
                    "required": True,
                    "options": ["General waste", "Clinical waste", "Biohazard", "Other"],
                },
                {
                    "key": "colour", "label": "Colour", "type": "select",
                    "required": True, "options": COLOURS,
                },
                {"key": "size", "label": "Size", "type": "text", "required": False},
                {
                    "key": "thickness_micron", "label": "Thickness", "type": "number",
                    "unit": "micron", "required": False, "min": 5, "max": 500,
                },
                {"key": "material", "label": "Material", "type": "text", "required": False},
            ]
        },
    ),
    (
        "Dustbins",
        "Pedal, open and swing-lid bins.",
        {
            "attributes": [
                {
                    "key": "colour", "label": "Colour", "type": "select",
                    "required": True, "options": COLOURS,
                },
                {
                    "key": "capacity_litres", "label": "Capacity", "type": "number",
                    "unit": "L", "required": True, "min": 1, "max": 1100,
                },
                {
                    "key": "lid_type", "label": "Lid type", "type": "select",
                    "required": False, "options": ["Pedal", "Open", "Swing", "Other"],
                },
            ]
        },
    ),
    (
        "Cleaning Products",
        "Detergents, disinfectants, sanitizers and consumables.",
        {
            "attributes": [
                {"key": "pack_size", "label": "Pack size", "type": "text", "required": False},
                {"key": "fragrance", "label": "Fragrance", "type": "text", "required": False},
            ]
        },
    ),
    ("Stationery", "Office and ward stationery.", {"attributes": []}),
    (
        "Other Supplies",
        "Anything that does not belong to another category, including products "
        "created while billing.",
        {"attributes": []},
    ),
]

# (code, name, category, decimal_scale)
UNITS = [
    ("PCS", "Piece", "count", 0),
    ("PKT", "Packet", "count", 0),
    ("ROLL", "Roll", "count", 0),
    ("BOX", "Box", "count", 0),
    ("SET", "Set", "count", 0),
    ("DOZ", "Dozen", "count", 0),
    ("KG", "Kilogram", "weight", 3),
    ("LTR", "Litre", "volume", 3),
]


def upgrade() -> None:
    for name, description, schema in CATEGORIES:
        op.execute(
            f"""
            INSERT INTO crm.product_categories (name, description, attribute_schema, is_active)
            VALUES (
                {name!r},
                {description!r},
                '{json.dumps(schema)}'::jsonb,
                true
            )
            ON CONFLICT (name) DO NOTHING
            """
        )
    for code, name, category, scale in UNITS:
        op.execute(
            f"""
            INSERT INTO crm.units_of_measure (code, name, category, decimal_scale, is_active)
            VALUES ({code!r}, {name!r}, {category!r}, {scale}, true)
            ON CONFLICT (code) DO NOTHING
            """
        )


def downgrade() -> None:
    # Only remove rows nothing points at; a seeded row that has been used for
    # real products must survive a downgrade.
    for name, _description, _schema in CATEGORIES:
        op.execute(
            f"""
            DELETE FROM crm.product_categories c
            WHERE c.name = {name!r}
              AND NOT EXISTS (SELECT 1 FROM crm.products p WHERE p.category_id = c.id)
            """
        )
    for code, _name, _category, _scale in UNITS:
        op.execute(
            f"""
            DELETE FROM crm.units_of_measure u
            WHERE u.code = {code!r}
              AND NOT EXISTS (SELECT 1 FROM crm.products p WHERE p.base_uom_id = u.id)
              AND NOT EXISTS (SELECT 1 FROM crm.product_variants v WHERE v.uom_id = u.id)
            """
        )
