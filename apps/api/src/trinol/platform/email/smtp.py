from __future__ import annotations

import logging
import re
from email.message import EmailMessage as MimeMessage

import aiosmtplib

from trinol.core.deps import get_settings
from trinol.platform.email.protocol import EmailMessage

logger = logging.getLogger(__name__)

_HEADER_INJECTION_CHARS = re.compile(r"[\r\n]")


def _sanitize_header(value: str) -> str:
    """EMAIL.md §4: any user-controlled value used in a header has CR/LF
    stripped, closing header injection."""
    return _HEADER_INJECTION_CHARS.sub("", value)


class SMTPEmailSender:
    """EMAIL.md §1/§2: Hostinger SMTP over implicit TLS (port 465 -- TLS from
    the first byte, not STARTTLS, which fails silently into plaintext on some
    clients if misconfigured). No provider SDK: aiosmtplib + stdlib
    email.message cover this completely."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        from_email: str,
        from_name: str,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_email = from_email
        self._from_name = from_name

    def _allowed_recipient(self, to: str) -> bool:
        settings = get_settings()
        if settings.app_env == "production":
            return True
        allowlist = settings.smtp_dev_allowlist
        allowed = {addr.strip().lower() for addr in allowlist.split(",")} if allowlist else set()
        return to.strip().lower() in allowed

    async def send(self, message: EmailMessage) -> None:
        if not self._allowed_recipient(message.to):
            logger.warning(
                "email blocked: recipient not in non-production allowlist",
                extra={"to": message.to},
            )
            return

        mime = MimeMessage()
        mime["Subject"] = _sanitize_header(message.subject)
        mime["From"] = f"{_sanitize_header(self._from_name)} <{self._from_email}>"
        mime["To"] = _sanitize_header(message.to)
        if message.reply_to:
            mime["Reply-To"] = _sanitize_header(message.reply_to)
        mime.set_content(message.text_body)
        mime.add_alternative(message.html_body, subtype="html")

        # EMAIL.md §3: one immediate retry on a transient error, then log and
        # give up -- a mail failure must never raise into the caller (it runs
        # from a background task after the response is already sent, but the
        # rule holds regardless of caller).
        for attempt in (1, 2):
            try:
                await aiosmtplib.send(
                    mime,
                    hostname=self._host,
                    port=self._port,
                    username=self._username,
                    password=self._password,
                    use_tls=True,
                )
                return
            except Exception:
                if attempt == 2:
                    logger.exception(
                        "failed to send email after retry",
                        extra={"to": message.to, "subject": message.subject},
                    )
