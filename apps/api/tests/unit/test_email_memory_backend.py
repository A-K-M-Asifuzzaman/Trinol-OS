from __future__ import annotations

from trinol.platform.email.memory import MemoryEmailSender
from trinol.platform.email.protocol import EmailMessage
from trinol.platform.email.render import render_invitation_email


async def test_memory_sender_appends_sent_messages() -> None:
    sender = MemoryEmailSender()
    message = EmailMessage(to="a@x.com", subject="s", html_body="<p>h</p>", text_body="t")

    await sender.send(message)

    assert sender.sent == [message]


def test_render_invitation_email_escapes_html_but_not_text() -> None:
    """The bug this guards against: select_autoescape(("jinja",)) matches
    both invitation.html.jinja and invitation.txt.jinja by file extension,
    which would escape the plain-text body too."""
    html_body, text_body = render_invitation_email(
        inviter_name="A & B",
        organization_name="Org & Co",
        role="MEMBER",
        accept_url="https://example.com/join?token=abc",
        expires_at="2026-01-01",
    )
    assert "A &amp; B" in html_body
    assert "A & B" in text_body
    assert "&amp;" not in text_body
