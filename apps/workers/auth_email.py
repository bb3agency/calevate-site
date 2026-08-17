"""Delivering the one-time secrets `apps/api/authn` mints (D-166).

A reset link nobody receives is a password nobody can change, so this job is the other half
of every flow in `authn/service.py` that ends in `_enqueue_auth_email`. It is deliberately
tiny: it renders one of four short messages and hands it to the transport
(`workers/transport.py`) that `notify_hot_lead` already uses. No new dependency, no second
mail path, no template engine — a template engine for four fixed strings would be a second
way to compose an email in a repo that already has one.

═══ WHY IT IS AN OUTBOX JOB AND NOT AN INLINE SEND ═══

BACKEND-PATTERNS §4. The token row and the promise to email it commit together, so there is
no ordering in which one exists without the other. It also keeps a mail provider's latency
and outages off the request path — a sign-in flow that blocks on SMTP is a sign-in flow
that times out when the provider is slow.

═══ HARD RULE 6, WHICH THIS JOB IS THE MOST EXPOSED TO ═══

The payload holds an email address AND a live credential. Neither is ever logged: every log
line here carries the `kind` and the recipient's DOMAIN (via `transport._domain`, the helper
that exists for exactly this), and never the mailbox, never the token, never the code. A
failure that needs diagnosing is diagnosed from the outbox row's id, which is in the log.

═══ RETRIES ═══

Returning a string marks the job done; RAISING is what makes arq retry it, and this job
raises on an undelivered send because the whole point of the outbox is that the promise
survives a bad minute at the provider. `WORKER_MAX_TRIES` then bounds it and the DLQ
catches what is left. A code that expires before the retries succeed is not a problem worth
solving here — the person simply asks for another one, and the expiry is what makes that
safe.
"""

from __future__ import annotations

import asyncio
from typing import Any

from apps.api.core.logging import get_logger
from apps.workers.transport import _domain, get_transport

log = get_logger(__name__)

#: Subject lines, keyed by the `kind` `authn/service._enqueue_auth_email` sends. A closed
#: mapping rather than a formatted string, so an unknown kind is a loud failure rather than
#: an email with a blank subject.
_SUBJECTS: dict[str, str] = {
    "password_reset": "Reset your Calevate password",
    "otp_email_verify": "Your Calevate verification code",
    "otp_login_challenge": "Your Calevate sign-in code",
    "invite_password": "You have been invited to Calevate",
}

#: Where the emailed links point. The token travels in the `token` query parameter of a
#: PAGE, never of an API route — the page then POSTs it — which is what keeps the secret
#: out of the API's access logs and out of any `Referer` an outbound link on that page
#: would send.
_CONSOLE_BASE = "https://app.calevate.tech"
_ADMIN_BASE = "https://admin.calevate.tech"


def _body(kind: str, realm: str, secret: str) -> str:
    """The message. Plain text, because a transactional secret does not need HTML and an
    HTML mail is one more thing that can render wrong in a client we have never seen."""
    base = _ADMIN_BASE if realm == "admin" else _CONSOLE_BASE
    if kind == "password_reset":
        return (
            "Someone asked to reset the password for this Calevate account.\n\n"
            f"{base}/reset-password?token={secret}\n\n"
            "This link works once and expires in one hour. If this was not you, you can "
            "ignore this email — your password has not changed."
        )
    if kind == "invite_password":
        return (
            "You have been invited to a Calevate workspace.\n\n"
            f"{base}/invite?token={secret}\n\n"
            "This link works once and expires in 72 hours."
        )
    # Both OTP kinds. One code, one sentence about what it is for.
    what = "sign in" if kind == "otp_login_challenge" else "confirm your email address"
    return (
        f"Your Calevate code to {what} is:\n\n    {secret}\n\n"
        "It expires in 10 minutes. If you did not ask for it, you can ignore this email."
    )


async def deliver_auth_email(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Send one authentication email. Registered in `settings.FUNCTIONS`.

    `ctx` is arq's job context and is unused — the transport is process-global and this job
    holds no database session, which is deliberate: it must not need one, because the row
    it is acting on was already committed by the request that enqueued it.
    """
    del ctx
    kind = str(payload.get("kind", ""))
    to = str(payload.get("to", ""))
    secret = str(payload.get("secret", ""))
    realm = str(payload.get("realm", "client"))

    subject = _SUBJECTS.get(kind)
    if subject is None or not to or not secret:
        # A malformed payload is OUR bug, not a transient failure, so it must not walk the
        # retry ladder pretending to be one. Raising a ValueError sends it to the DLQ on the
        # first attempt with a message that names the defect.
        raise ValueError(f"auth email payload is not deliverable (kind={kind!r})")

    transport = get_transport()
    delivered = await asyncio.to_thread(
        lambda: transport.send(to=to, subject=subject, body=_body(kind, realm, secret))
    )
    if not delivered:
        # Domain only — never the mailbox (hard rule 6), never the secret.
        log.warning(
            "auth_email_undelivered",
            extra={"kind": kind, "realm": realm, "domain": _domain(to)},
        )
        raise RuntimeError(f"auth email undelivered (kind={kind})")
    log.info("auth_email_sent", extra={"kind": kind, "realm": realm, "domain": _domain(to)})
    return "sent"


__all__ = ["deliver_auth_email"]
