from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa

# Unlike platform/email/render.py's Environment (HTML *and* plain-text
# templates sharing one loader, escaped selectively), every template here
# is HTML fed straight to xhtml2pdf — always autoescape.
_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=True,
)


@dataclass(frozen=True, slots=True)
class InvoicePdfLineItem:
    """Plain strings, not Decimal — this module takes already-formatted
    display values, the same reasoning platform/email/render.py's own
    functions take plain strings rather than ORM instances (platform must
    not depend on modules/, ARCHITECTURE.md §3)."""

    description: str
    quantity: str
    unit_price: str
    line_total: str


class PdfRenderError(Exception):
    """Raised when xhtml2pdf itself reports a rendering failure
    (`pisa.CreatePDF`'s own `err` count) — distinct from a Jinja2 template
    error, which raises on its own before this is ever reached."""


def render_invoice_pdf(
    *,
    organization_name: str,
    client_name: str,
    client_company: str | None,
    client_address: str | None,
    client_email: str | None,
    invoice_number: str,
    status: str,
    issue_date: str,
    due_date: str,
    currency: str,
    items: list[InvoicePdfLineItem],
    subtotal: str,
    discount_amount: str,
    tax_amount: str,
    total: str,
    notes: str | None,
    terms: str | None,
) -> bytes:
    """Renders `invoice.html.jinja` then feeds the resulting HTML straight
    to `xhtml2pdf.pisa.CreatePDF` (Stage 6 decision: xhtml2pdf, pure-Python
    with no system-level dependencies, over WeasyPrint). A table-based
    layout (header, bill-to, line items, totals) stays within xhtml2pdf's
    supported CSS subset — no flexbox/floats needed."""
    context = {
        "organization_name": organization_name,
        "client_name": client_name,
        "client_company": client_company,
        "client_address": client_address,
        "client_email": client_email,
        "invoice_number": invoice_number,
        "status": status,
        "issue_date": issue_date,
        "due_date": due_date,
        "currency": currency,
        "items": items,
        "subtotal": subtotal,
        "discount_amount": discount_amount,
        "tax_amount": tax_amount,
        "total": total,
        "notes": notes,
        "terms": terms,
    }
    html = _env.get_template("invoice.html.jinja").render(context)

    buffer = io.BytesIO()
    result = pisa.CreatePDF(html, dest=buffer)
    if result.err:
        raise PdfRenderError(f"xhtml2pdf reported {result.err} error(s) rendering invoice PDF")
    return buffer.getvalue()
