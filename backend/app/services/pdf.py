"""Shared PDF platform: Jinja2 templates + WeasyPrint.

Templates are versioned (templates/pdf/v1/...) and rendered from frozen
server-side snapshots only — never from editable browser totals. Rendering is
deterministic for a given context (no wall-clock calls inside templates).
"""
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
        _env.filters["money"] = lambda v: f"{v:,.2f}" if v is not None else "0.00"
    return _env


def render_pdf(template_name: str, context: dict) -> bytes:
    """Render an HTML template to PDF bytes."""
    from weasyprint import HTML  # imported lazily: needs system pango libs

    html = get_env().get_template(template_name).render(**context)
    return HTML(string=html, base_url=str(TEMPLATE_ROOT)).write_pdf()


def render_html(template_name: str, context: dict) -> str:
    """The exact HTML used for the PDF — handy for tests and previews."""
    return get_env().get_template(template_name).render(**context)
