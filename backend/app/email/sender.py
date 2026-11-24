"""Outbound email: a small interface with SMTP, console and in-memory backends.

Emails are sent *after* the database transaction commits (via FastAPI background
tasks), so a failed send never rolls back business data. Failures are logged and the
buyer can resend an invitation. A durable outbox replaces this in Phase 7.
"""

from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

import aiosmtplib

from app.core.config import Settings
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class OutgoingEmail:
    to: str
    subject: str
    text: str
    html: str | None = None
    tags: dict[str, str] = field(default_factory=dict)


class EmailSender(Protocol):
    async def send(self, message: OutgoingEmail) -> None: ...


class SmtpEmailSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def send(self, message: OutgoingEmail) -> None:
        s = self.settings
        mime = EmailMessage()
        mime["From"] = s.email_from
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.text)
        if message.html:
            mime.add_alternative(message.html, subtype="html")
        await aiosmtplib.send(
            mime,
            hostname=s.smtp_host,
            port=s.smtp_port,
            username=s.smtp_username,
            password=s.smtp_password.get_secret_value() if s.smtp_password else None,
            start_tls=s.smtp_use_tls,
            timeout=s.smtp_timeout_seconds,
        )


class ConsoleEmailSender:
    async def send(self, message: OutgoingEmail) -> None:
        log.info("email_console", to=message.to, subject=message.subject, body=message.text)


class MemoryEmailSender:
    """Test backend: keeps every message for assertions."""

    def __init__(self) -> None:
        self.outbox: list[OutgoingEmail] = []

    async def send(self, message: OutgoingEmail) -> None:
        self.outbox.append(message)


def create_email_sender(settings: Settings) -> EmailSender:
    match settings.email_backend:
        case "smtp":
            return SmtpEmailSender(settings)
        case "memory":
            return MemoryEmailSender()
        case _:
            return ConsoleEmailSender()


async def send_safely(sender: EmailSender, message: OutgoingEmail) -> None:
    """Background-task entry point: never raises."""
    try:
        await sender.send(message)
        log.info("email_sent", to=message.to, subject=message.subject, **message.tags)
    except Exception:
        log.exception("email_send_failed", to=message.to, subject=message.subject, **message.tags)
