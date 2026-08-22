"""Delivering the one-time secrets `apps/api/authn` mints (D-170).

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

═══ RETRIES, AND THE TWO THINGS THIS PARAGRAPH USED TO GET WRONG ═══

It said: *"RAISING is what makes arq retry it ... `WORKER_MAX_TRIES` then bounds it and the
DLQ catches what is left."* Both halves were false, and they were false in the direction
that looks fine.

* **arq 0.28 retries for `Retry`, `RetryJob` and `CancelledError` and for NOTHING else**
  (`Worker.run_job`: `if self.retry_jobs and isinstance(e, Retry)` … `elif self.retry_jobs
  and isinstance(e, (asyncio.CancelledError, RetryJob))`, everything else falls to
  `finish` = True). This job raised `RuntimeError`, so it got exactly ONE attempt —
  `WorkerSettings.max_tries = 3` never applied to it. A reset link lost to one slow minute
  at the mail provider was lost for good, while the sign-in screen truthfully reported that
  an email was on its way.
* **There is no arq DLQ.** `WorkerSettings`' own docstring says so at length: an exhausted
  job is written to a result key nothing in `apps/` or `scripts/` reads. The only DLQ here
  is the OUTBOX's `status='failed'`, which covers the ENQUEUE leg — and this job's enqueue
  succeeded. So "the DLQ catches what is left" named a mechanism that does not exist, and
  the failure of the one message a person is actively waiting for was a `log.warning`.

Both are closed by taking the shape every other delivery job in this fleet already uses
(`notify_hot_lead`, `notify_hot_lead_whatsapp`, `escalate_campaign_contact`,
`deliver_outbound_webhook`): `raise Retry(defer=...)` while the budget lasts, then
`alert()` on the last attempt, because the alert IS the dead-letter mechanism.

THE LADDER IS THE TIGHTEST IN THE FLEET, and the reason is the payload: an
`otp_login_challenge` code expires in ten minutes and somebody is looking at a sign-in
screen for the whole of it. 10s + 30s spends at most 40 seconds of that on a provider
having a bad minute, where the hot-lead ladder's 15+45 is paced for a 2-minute SLO nobody
is watching in real time. A code that expires anyway is not a problem worth solving here —
the person asks for another one, and the expiry is what makes that safe.
"""

from __future__ import annotations

import asyncio
from typing import Any

from arq import Retry

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.workers.transport import _domain, get_transport

log = get_logger(__name__)

#: Subject lines, keyed by the `kind` `authn/service._enqueue_auth_email` sends. A closed
#: mapping rather than a formatted string, so an unknown kind is a loud failure rather than
#: an email with a blank subject.
_SUBJECTS: dict[str, str] = {
    "password_reset": "Reset your Calevate password",
    "otp_email_verify": "Your Calevate verification code",
    "otp_login_challenge": "Your Calevate sign-in code",
    "otp_step_up": "Your Calevate authorization code",
    "invite_password": "You have been invited to Calevate",
}

#: Where the emailed links point. The token travels in the `token` query parameter of a
#: PAGE, never of an API route — the page then POSTs it — which is what keeps the secret
#: out of the API's access logs and out of any `Referer` an outbound link on that page
#: would send.
#:
#: `CONSOLE_BASE` is PUBLIC because `workers/notifications.py` links a hot-lead alert
#: back to the lead it is about, and a second literal of this host is the defect class
#: D-103 exists for. It is exported rather than moved because both readers are worker
#: email composers and a module holding one constant is not a better home than the one
#: that already mints links.
CONSOLE_BASE = "https://app.calevate.tech"
_ADMIN_BASE = "https://admin.calevate.tech"

#: Seconds to wait before each retry, indexed by the attempt that just failed. One entry
#: shorter than `WORKER_MAX_TRIES`, because the last attempt has nothing after it — the
#: same shape as `notifications.RETRY_BACKOFF_S`, tighter for the reason in the module
#: docstring.
RETRY_BACKOFF_S: tuple[float, ...] = (10.0, 30.0)


def _retry_after(attempt: int) -> float:
    index = min(attempt, len(RETRY_BACKOFF_S)) - 1
    return RETRY_BACKOFF_S[max(index, 0)]


def _body(kind: str, realm: str, secret: str) -> str:
    """The message. Plain text, because a transactional secret does not need HTML and an
    HTML mail is one more thing that can render wrong in a client we have never seen."""
    base = _ADMIN_BASE if realm == "admin" else CONSOLE_BASE
    if kind == "password_reset":
        return (
            "Someone asked to reset the password for this Calevate account.\n\n"
            f"{base}/reset-password?token={secret}\n\n"
            "This link works once and expires in one hour. If this was not you, you can "
            "ignore this email — your password has not changed."
        )
    if kind == "invite_password":
        # `/auth/accept-invitation`, NOT `/invite`. Both reach the same page — `/invite`
        # survives as a client-side redirect for links already sitting in inboxes — but
        # D-177's rule is that newly minted links name the surviving page directly, and
        # this template mints them. It pointed at the legacy path while nothing sent it;
        # D-190 made it the only way an invitation reaches anybody, which is what turned a
        # stale string into a live extra hop. Kept in step with
        # `apps/web/src/lib/authn/clientAuthn.CLIENT_ACCEPT_INVITE_PATH` (which
        # `members.INVITE_PATH` re-exports) by `tests/auth_email_delivery_test.py`,
        # in the test whose name says so. That reference named
        # `tests/auth_email_test.py`, a file this repo does not have — a guard
        # promised in a comment and never written, which is the same defect class as
        # an unmounted router: the two strings could drift apart and nothing anywhere
        # would go red.
        return (
            "You have been invited to a Calevate workspace.\n\n"
            f"{base}/auth/accept-invitation?token={secret}\n\n"
            "This link works once and expires in 72 hours. If you were not expecting it, "
            "you can ignore this email — nothing happens until you open it."
        )
    # OTP kinds. One code, one sentence about what it is for.
    if kind == "otp_login_challenge":
        what = "sign in"
    elif kind == "otp_step_up":
        what = "authorize this action"
    else:
        what = "confirm your email address"
    return (
        f"Your Calevate code to {what} is:\n\n    {secret}\n\n"
        "It expires in 10 minutes. If you did not ask for it, you can ignore this email."
    )


async def deliver_auth_email(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Send one authentication email. Registered in `settings.FUNCTIONS`.

    `ctx` is read for ONE thing — `job_try`, which bounds the retry ladder below. It was
    discarded on the first line, which is how the missing ladder went unnoticed: nothing in
    the body could see which attempt it was, so there was nowhere for the question to be
    asked. The job still holds no database session, deliberately: it must not need one,
    because the row it is acting on was already committed by the request that enqueued it.
    """
    attempt = int(ctx.get("job_try", 1) or 1)
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
            extra={"kind": kind, "realm": realm, "domain": _domain(to), "attempt": attempt},
        )
        if attempt < WORKER_MAX_TRIES:
            # The one exception type arq treats as "not finished". Nothing here is
            # committed, so the retry starts from exactly where this attempt did.
            raise Retry(defer=_retry_after(attempt))
        # Out of attempts, and there is no queue-level dead letter to fall into — the
        # alert IS the dead letter (`WorkerSettings`' docstring argues why the repo has no
        # second durable store for this). A person is waiting on this message and only an
        # operator can tell them it is not coming.
        alert(
            "WORKER_DELIVERY",
            "auth_email_exhausted",
            # `kind` and the recipient's DOMAIN, never the mailbox: an alert body is
            # forwarded further than a log line is (hard rule 6).
            detail=(
                f"{kind} email to a {_domain(to)} address undelivered after "
                f"{attempt} attempt(s); the person who asked for it will never receive it"
            ),
            realm=realm,
        )
        return f"exhausted after {attempt}"
    log.info(
        "auth_email_sent",
        extra={"kind": kind, "realm": realm, "domain": _domain(to), "attempts": attempt},
    )
    return "sent"


__all__ = ["CONSOLE_BASE", "RETRY_BACKOFF_S", "deliver_auth_email"]
