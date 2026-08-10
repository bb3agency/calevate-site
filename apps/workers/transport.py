"""Email transport for notifications (ROADMAP M1: "email first, WhatsApp next").

Three implementations behind one Protocol, selected by config:

- **`SmtpTransport`** — the real one. Any provider with SMTP works, which keeps the
  choice of provider a deployment decision rather than a code dependency.
- **`ConsoleTransport`** — local dev. Logs the envelope and reports SUCCESS, because
  locally the delivery genuinely did happen: it went to the developer's terminal.
- **`NullTransport`** — no channel configured. Reports FAILURE and says why. This is
  the one that matters: a transport that silently returns success when nothing is
  wired makes the hot-lead SLO look met while nobody is being told.

Hard rule 6 applies at the boundary: the body is composed from redacted values before
it reaches this module, and this module logs recipient DOMAINS rather than addresses.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Protocol

from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings

log = get_logger(__name__)

SMTP_TIMEOUT_S = 15.0


class Transport(Protocol):
    name: str

    def send(self, *, to: str, subject: str, body: str) -> bool: ...


def _domain(address: str) -> str:
    """Log the domain, never the mailbox — an email address is personal data."""
    return address.rpartition("@")[2] or "unknown"


class SmtpTransport:
    name = "smtp"

    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        sender: str,
        use_tls: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._sender = sender
        self._use_tls = use_tls

    def send(self, *, to: str, subject: str, body: str) -> bool:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(self._host, self._port, timeout=SMTP_TIMEOUT_S) as smtp:
                if self._use_tls:
                    smtp.starttls()
                if self._username and self._password:
                    smtp.login(self._username, self._password)
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            # Return False rather than raising: the CALLER decides whether a failed
            # notification should retry the whole job, and it records the outcome on
            # the lead timeline either way.
            log.warning(
                "email_send_failed",
                extra={"recipient_domain": _domain(to), "reason": type(exc).__name__},
            )
            return False
        log.info("email_sent", extra={"recipient_domain": _domain(to)})
        return True


class ConsoleTransport:
    """Local dev. Reports success honestly — the message really did get delivered,
    to a terminal."""

    name = "console"

    def send(self, *, to: str, subject: str, body: str) -> bool:
        log.info(
            "email_console",
            extra={"recipient_domain": _domain(to), "subject": subject, "chars": len(body)},
        )
        return True


class NullTransport:
    """No channel configured. Reports FAILURE, loudly.

    The alternative — returning True — would make the 2-minute hot-lead SLO look met
    in every dashboard while no client was ever told about a lead.
    """

    name = "null"

    def send(self, *, to: str, subject: str, body: str) -> bool:
        log.warning("email_no_transport", extra={"recipient_domain": _domain(to)})
        return False


def get_transport() -> Transport:
    settings = get_settings()
    if settings.smtp_host:
        return SmtpTransport(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            sender=settings.notifications_from or "alerts@calevate.tech",
            use_tls=settings.smtp_use_tls,
        )
    if settings.app_env == "local":
        return ConsoleTransport()
    return NullTransport()


__all__ = [
    "ConsoleTransport",
    "NullTransport",
    "SmtpTransport",
    "Transport",
    "get_transport",
]
