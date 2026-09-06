from __future__ import annotations

from trinol.core.deps import get_settings
from trinol.platform.email.console import ConsoleEmailSender
from trinol.platform.email.protocol import EmailSender
from trinol.platform.email.smtp import SMTPEmailSender

_sender: EmailSender | None = None


def get_email_sender() -> EmailSender:
    """EMAIL.md §1, selected by EMAIL_BACKEND. Overridden in tests via
    `app.dependency_overrides` with a `MemoryEmailSender` (same pattern as
    get_identity_verifier — tests never touch the network).

    "memory" isn't handled here: nothing outside tests should ever select it,
    and tests replace this dependency entirely rather than relying on the
    setting.
    """
    global _sender
    if _sender is None:
        settings = get_settings()
        if settings.email_backend == "smtp":
            _sender = SMTPEmailSender(
                host=settings.smtp_host or "",
                port=settings.smtp_port,
                username=settings.smtp_username or "",
                password=settings.smtp_password or "",
                from_email=settings.smtp_from_email or "",
                from_name=settings.smtp_from_name or "",
            )
        else:
            _sender = ConsoleEmailSender()
    return _sender
