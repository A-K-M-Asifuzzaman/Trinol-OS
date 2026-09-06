from __future__ import annotations

import logging

from trinol.platform.email.protocol import EmailMessage

logger = logging.getLogger(__name__)


class ConsoleEmailSender:
    """EMAIL.md §1: local dev default. Renders and logs the message, sends
    nothing — the text body is logged in full so a developer can read it
    without an SMTP server."""

    async def send(self, message: EmailMessage) -> None:
        logger.info(
            "email (console backend, not sent)",
            extra={
                "to": message.to,
                "subject": message.subject,
                "text_body": message.text_body,
            },
        )
