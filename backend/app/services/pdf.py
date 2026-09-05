"""Shared PDF platform: Jinja2 templates + WeasyPrint.

Templates are versioned (templates/pdf/v1/...) and rendered from frozen
server-side snapshots only — never from editable browser totals. Rendering is
deterministic for a given context (no wall-clock calls inside templates).
"""
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

TEMPLATE_ROOT = Path(__file__).resolve().parent.parent / "templates" / "pdf"
TEMPLATE_VERSION = "v1"

_env: Environment | None = None


def get_env() -> Environment:
    global _env
    if _env is None:
        _env = Environment(
            loader=FileSystemLoader(TEMPLATE_ROOT / TEMPLATE_VERSION),
            undefined=StrictUndefined,
            autoescape=True,
        )
        _env.filters["money"] = _money
        _env.filters["num"] = _num
    return _env


def _num(value: object) -> Decimal:
    """Coerce a context value to Decimal so templates can compare amounts.

    A frozen context carries amounts as strings; comparing those against a
    number would raise. Amounts are kept as strings rather than floats so a
    quantity such as "5.000" still renders with its original precision.
    """
    if value is None:
        return Decimal(0)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _money(value: object) -> str:
    """Format an amount for a document.

    Accepts Decimal, int, float or a numeric string, because a frozen context
    read back from JSON carries its amounts as strings. Formatting via Decimal
    keeps the stored and live renders byte-identical.
    """
    if value is None:
        return "0.00"
    try:
        return f"{Decimal(str(value)):,.2f}"
    except (InvalidOperation, ValueError):
        return str(value)


def freeze_context(context: dict) -> dict:
    """A JSON-safe copy of a render context, for storing alongside the record.

    Documents must not change after they are issued, but keeping the rendered
    file in object storage makes issuing depend on that storage being reachable.
    Freezing the context instead keeps the guarantee — the same inputs always
    produce the same document — while the file itself is rendered on demand.
    """
    return json.loads(json.dumps(context, default=str))


def render_pdf(template_name: str, context: dict) -> bytes:
    """Render an HTML template to PDF bytes."""
    from weasyprint import HTML  # imported lazily: needs system pango libs

    html = get_env().get_template(template_name).render(**context)
    return HTML(string=html, base_url=str(TEMPLATE_ROOT)).write_pdf()


def render_html(template_name: str, context: dict) -> str:
    """The exact HTML used for the PDF — handy for tests and previews."""
    return get_env().get_template(template_name).render(**context)
