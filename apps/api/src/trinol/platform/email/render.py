from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader


def _should_autoescape(template_name: str | None) -> bool:
    # select_autoescape(("jinja",)) would match both templates here — they
    # both end in .jinja (invitation.html.jinja, invitation.txt.jinja) — and
    # incorrectly escape the plain-text body too (turning "&" into "&amp;").
    # EMAIL.md §4 wants every interpolated value autoescaped, but only in the
    # HTML half.
    return template_name is not None and ".html." in template_name


_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=_should_autoescape,
)


def render_invitation_email(
    *,
    inviter_name: str,
    organization_name: str,
    role: str,
    accept_url: str,
    expires_at: str,
) -> tuple[str, str]:
    """Returns (html_body, text_body)."""
    context = {
        "inviter_name": inviter_name,
        "organization_name": organization_name,
        "role": role,
        "accept_url": accept_url,
        "expires_at": expires_at,
    }
    html_body = _env.get_template("invitation.html.jinja").render(context)
    text_body = _env.get_template("invitation.txt.jinja").render(context)
    return html_body, text_body


def render_new_lead_notification_email(
    *,
    name: str,
    email: str,
    phone: str | None,
    company: str | None,
    service: str | None,
    budget: str | None,
    message: str,
    reference_number: str,
) -> tuple[str, str]:
    """Returns (html_body, text_body). EMAIL.md §5: sent to hello@trinolit.com
    on every non-spam contact submission."""
    context = {
        "name": name,
        "email": email,
        "phone": phone,
        "company": company,
        "service": service,
        "budget": budget,
        "message": message,
        "reference_number": reference_number,
    }
    html_body = _env.get_template("new_lead_notification.html.jinja").render(context)
    text_body = _env.get_template("new_lead_notification.txt.jinja").render(context)
    return html_body, text_body


def render_contact_confirmation_email(
    *, name: str, reference_number: str, message: str
) -> tuple[str, str]:
    """Returns (html_body, text_body). EMAIL.md §5: sent to the customer,
    carrying the reference number and an echo of their message."""
    context = {"name": name, "reference_number": reference_number, "message": message}
    html_body = _env.get_template("contact_confirmation.html.jinja").render(context)
    text_body = _env.get_template("contact_confirmation.txt.jinja").render(context)
    return html_body, text_body
