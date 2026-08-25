"""Category attribute-definition schema and variant attribute validation.

A category's ``attribute_schema`` is:

    {"attributes": [
        {"key": "colour", "label": "Colour", "type": "select",
         "options": ["Yellow", "Red", "Blue", "White", "Black"],
         "required": true},
        {"key": "thickness_micron", "label": "Thickness", "type": "number",
         "unit": "micron", "min": 5, "max": 500},
        ...
    ]}

Variant ``attributes`` must only use defined keys, satisfy required flags,
match the declared type, and (for selects) be one of the options. Users can
never invent arbitrary unvalidated keys.
"""
from typing import Any

from app.core.errors import ValidationFailedError

ALLOWED_TYPES = {"text", "number", "boolean", "select"}


def validate_schema_definition(schema: dict) -> None:
    """Validate a category attribute schema itself (admin editing)."""
    if not isinstance(schema, dict) or not isinstance(schema.get("attributes"), list):
        raise ValidationFailedError(
            "attribute_schema must be an object with an 'attributes' list.",
            field_errors={"attribute_schema": ["Must be {'attributes': [...]}"]},
        )
    seen: set[str] = set()
    for i, attr in enumerate(schema["attributes"]):
        loc = f"attribute_schema.attributes.{i}"
        if not isinstance(attr, dict):
            raise ValidationFailedError("Each attribute must be an object.", field_errors={loc: ["Invalid"]})
        key = attr.get("key")
        if not key or not isinstance(key, str) or not key.replace("_", "").isalnum():
            raise ValidationFailedError(
                "Attribute keys must be snake_case alphanumeric.", field_errors={loc: ["Invalid key"]}
            )
        if key in seen:
            raise ValidationFailedError("Duplicate attribute key.", field_errors={loc: [f"Duplicate: {key}"]})
        seen.add(key)
        if attr.get("type") not in ALLOWED_TYPES:
            raise ValidationFailedError(
                f"Attribute type must be one of {sorted(ALLOWED_TYPES)}.",
                field_errors={loc: [f"Invalid type: {attr.get('type')}"]},
            )
        if attr["type"] == "select":
            options = attr.get("options")
            if not isinstance(options, list) or not options or not all(isinstance(o, str) for o in options):
                raise ValidationFailedError(
                    "Select attributes need a non-empty string options list.",
                    field_errors={loc: ["Missing options"]},
                )


def validate_attributes(schema: dict, attributes: dict) -> dict:
    """Validate variant attributes against the category schema; returns them."""
    if not isinstance(attributes, dict):
        raise ValidationFailedError("attributes must be an object.")
    defs = {a["key"]: a for a in schema.get("attributes", [])}
    field_errors: dict[str, list[str]] = {}

    for key in attributes:
        if key not in defs:
            field_errors.setdefault(f"attributes.{key}", []).append(
                "Unknown attribute for this category."
            )

    for key, definition in defs.items():
        value: Any = attributes.get(key)
        loc = f"attributes.{key}"
        if value is None or value == "":
            if definition.get("required"):
                field_errors.setdefault(loc, []).append("This specification is required.")
            continue
        kind = definition["type"]
        if kind == "text" and not isinstance(value, str):
            field_errors.setdefault(loc, []).append("Must be text.")
        elif kind == "boolean" and not isinstance(value, bool):
            field_errors.setdefault(loc, []).append("Must be true or false.")
        elif kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                field_errors.setdefault(loc, []).append("Must be a number.")
            else:
                minimum, maximum = definition.get("min"), definition.get("max")
                if minimum is not None and value < minimum:
                    field_errors.setdefault(loc, []).append(f"Must be at least {minimum}.")
                if maximum is not None and value > maximum:
                    field_errors.setdefault(loc, []).append(f"Must be at most {maximum}.")
        elif kind == "select":
            if value not in definition.get("options", []):
                field_errors.setdefault(loc, []).append("Not an allowed option.")

    if field_errors:
        raise ValidationFailedError(
            "Variant specifications do not match the category definition.",
            field_errors=field_errors,
        )
    return attributes


# Editable starting templates. These are product master data, not a legal
# compliance determination — MPSTT Quality/Legal approves the exact mapping.
CATEGORY_TEMPLATES: list[dict] = [
    {
        "name": "Waste Bags",
        "description": "Healthcare-waste segregation bags",
        "attribute_schema": {"attributes": [
            {"key": "colour", "label": "Colour", "type": "select", "required": True,
             "options": ["Yellow", "Red", "Blue", "White", "Black", "Green"]},
            {"key": "dimensions", "label": "Dimensions (W x H)", "type": "text", "required": True},
            {"key": "thickness_micron", "label": "Thickness", "type": "number", "unit": "micron",
             "min": 5, "max": 500},
            {"key": "material", "label": "Material", "type": "select",
             "options": ["LDPE", "HDPE", "PP", "Biodegradable"]},
            {"key": "capacity_liters", "label": "Capacity", "type": "number", "unit": "L", "min": 1},
            {"key": "pack_quantity", "label": "Qty per pack", "type": "number", "min": 1},
            {"key": "intended_use", "label": "Intended waste category/use", "type": "text"},
            {"key": "labelling", "label": "Labelling / symbol", "type": "text"},
            {"key": "certificate_ref", "label": "Certificate/document reference", "type": "text"},
        ]},
    },
    {
        "name": "Rolls & Liners",
        "description": "Bin liners and rolls",
        "attribute_schema": {"attributes": [
            {"key": "colour", "label": "Colour", "type": "text"},
            {"key": "width_cm", "label": "Width", "type": "number", "unit": "cm", "min": 1},
            {"key": "roll_length_m", "label": "Roll length", "type": "number", "unit": "m", "min": 1},
            {"key": "thickness_micron", "label": "Thickness", "type": "number", "unit": "micron"},
            {"key": "material", "label": "Material", "type": "text"},
        ]},
    },
    {
        "name": "Containers & Bins",
        "description": "Sharps containers, waste bins, wheeled containers",
        "attribute_schema": {"attributes": [
            {"key": "colour", "label": "Colour", "type": "text"},
            {"key": "capacity_liters", "label": "Capacity", "type": "number", "unit": "L", "min": 0.1,
             "required": True},
            {"key": "material", "label": "Material", "type": "text"},
            {"key": "load_rating_kg", "label": "Load rating", "type": "number", "unit": "kg"},
            {"key": "lid_type", "label": "Lid type", "type": "text"},
            {"key": "puncture_resistant", "label": "Puncture resistant", "type": "boolean"},
            {"key": "certificate_ref", "label": "Certificate/document reference", "type": "text"},
        ]},
    },
    {
        "name": "Paper & Tissue",
        "description": "Couch rolls, paper towels, tissues",
        "attribute_schema": {"attributes": [
            {"key": "ply", "label": "Ply", "type": "number", "min": 1},
            {"key": "gsm", "label": "GSM", "type": "number", "unit": "gsm"},
            {"key": "sheet_size", "label": "Sheet size", "type": "text"},
            {"key": "sheets_per_pack", "label": "Sheets per pack", "type": "number", "min": 1},
            {"key": "packs_per_carton", "label": "Packs per carton", "type": "number", "min": 1},
        ]},
    },
    {
        "name": "Cleaning Chemicals",
        "description": "Disinfectants and cleaning agents",
        "attribute_schema": {"attributes": [
            {"key": "volume_liters", "label": "Volume", "type": "number", "unit": "L", "min": 0.05},
            {"key": "concentration", "label": "Concentration/dilution", "type": "text"},
            {"key": "active_ingredient", "label": "Active ingredient", "type": "text"},
            {"key": "fragrance", "label": "Fragrance", "type": "text"},
            {"key": "certificate_ref", "label": "Certificate/document reference", "type": "text"},
        ]},
    },
    {
        "name": "Safety Supplies",
        "description": "Gloves, masks, gowns, PPE",
        "attribute_schema": {"attributes": [
            {"key": "size", "label": "Size", "type": "select",
             "options": ["XS", "S", "M", "L", "XL", "XXL", "Universal"]},
            {"key": "colour", "label": "Colour", "type": "text"},
            {"key": "material", "label": "Material", "type": "text"},
            {"key": "sterile", "label": "Sterile", "type": "boolean"},
            {"key": "pack_quantity", "label": "Qty per pack", "type": "number", "min": 1},
            {"key": "standard_ref", "label": "Standard/certificate reference", "type": "text"},
        ]},
    },
]
