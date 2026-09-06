from __future__ import annotations

from trinol.platform.email.protocol import EmailMessage


class MemoryEmailSender:
    """EMAIL.md §1: test double. Appends to a list the test asserts
    against — never touches the network (TESTING.md's own rule for every
    external dependency)."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.sent.append(message)
