from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class EmailMessage:
    to: str
    subject: str
    html_body: str
    text_body: str
    reply_to: str | None = None


class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...
