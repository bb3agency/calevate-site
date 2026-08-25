"""Email transport for notifications (ROADMAP M1: "email first, WhatsApp next").

TWO CONSUMERS, ONE TRANSPORT. Hot-lead notifications (`workers/notifications.py`) and
OPERATOR ALERTS (`apps/api/core/alerting.py`, OPERATIONS §4) both send through here.
A second delivery mechanism for alerts would be a second thing to configure and a
second thing to be broken on the night it is needed. The alerting path calls `send()`
from its own daemon thread — this module stays synchronous and blocking, which is what
lets it be a plain client of one protocol, and callers on a latency budget defer rather
than adapt it. `httpx.Client`, never `AsyncClient`: an async client here would make
every caller either grow an event loop or run one inside a thread that already is one.

## Four implementations behind one Protocol, and ONE selector

`calevate_shared.config.email_transport_reason()` is the single resolver and
`get_transport()` below is its only consumer, so "which transport is this deployment
using?" has exactly one answer: `EMAIL_PROVIDER`, plus APP_ENV=local for the dev sink.
Nothing infers a transport from the presence of a credential.

- **`ResendTransport`** — `EMAIL_PROVIDER=resend`. The real one. One `POST` to an HTTP
  API, no vendor SDK (hard rule 9: `httpx` is already a dependency and this is a single
  request; adding `resend` to the lockfile would buy four constants we can read for
  free, and every package is a supply-chain decision — `incident_report.md`).
- **`SmtpTransport`** — `EMAIL_PROVIDER=smtp`. KEPT, deliberately, and not as an
  accumulated second way of doing one thing: the selector above means there is still
  exactly one rule for choosing, and what this buys is that a suspended Resend account
  or a provider outage is a config change from a browser rather than a deploy. Any
  provider with SMTP works, which is the property that keeps provider choice a
  deployment decision. It is unreachable unless `EMAIL_PROVIDER` names it — `SMTP_HOST`
  alone no longer selects anything.
- **`ConsoleTransport`** — local dev (APP_ENV=local with no provider set). Logs the
  envelope and reports SUCCESS, because locally the delivery genuinely did happen: it
  went to the developer's terminal.
- **`NullTransport`** — no channel configured. Reports FAILURE **and names the reason**.
  This is the one that matters: a transport that silently returns success when nothing
  is wired makes the hot-lead SLO look met while nobody is being told.

## What we know about the Resend API, and how well — read this before trusting it

**`resend.com` is refused by this environment's egress proxy** (WebFetch →
EGRESS_BLOCKED, tried 16 Aug 2026), so nobody here has read their documentation pages.
The contract below therefore uses the three-rung evidence ladder
`apps/api/billing/payments.py` established, cited per fact:

* **READ AT SOURCE** — from Resend's own published repositories, fetched 16 Aug 2026:
  `github.com/resend/resend-openapi` (`resend.yaml`, their published OpenAPI document),
  `github.com/resend/resend-python` (`resend/request.py`, `resend/exceptions.py`) and
  `github.com/resend/resend-node` (`src/interfaces.ts`). Vendor-published code and spec,
  so it is strong evidence about the things it actually describes:
  - `POST https://api.resend.com/emails`, `Authorization: Bearer re_…`,
    `Content-Type: application/json`, `Accept: application/json`;
  - required body fields are `from`, `to`, `subject`. `to` is a string OR an array of
    1 to 50 strings. **`html` and `text` are both optional, so a plain-text body is
    schema-valid** — which is what this module sends, because every message it carries is
    already composed as text;
  - success is **200** with body `{"id": "<uuid>"}`;
  - an error body is `{"statusCode": int, "name": str, "message": str}` where `name` is a
    closed vocabulary: `validation_error`, `missing_api_key`, `restricted_api_key`,
    `invalid_api_key`, `not_found`, `rate_limit_exceeded`, `daily_quota_exceeded`,
    `monthly_quota_exceeded`, `application_error`, `invalid_from_address`, … The Python
    SDK's own map pins `401 → missing_api_key`, `403 → invalid_api_key`,
    `400/422 → validation_error`, `429 → rate_limit_exceeded`, `500 → application_error`.
* **REPORTED, NOT READ** — search-engine summaries of pages nobody here can open:
  - the rate limit is **2 requests/second** by default, and a 429 carries a `retry-after`
    header. Our volume is a handful of messages a day and the transport never bursts, so
    this shapes nothing below except the decision NOT to sleep-and-retry inside a daemon
    thread (the callers already have retry ladders);
  - an **unverified sender domain is a 403** whose `name` is `validation_error` and whose
    `message` quotes the domain. This is the failure mode that would otherwise be silent,
    and `_refuse()` below is written around it;
  - an `Idempotency-Key` request header is honoured for 24 hours. NOT USED — see the
    note on `send()`.
* **UNVERIFIED** — **no request has ever been made to `api.resend.com` from this
  repository**, no Resend account exists, and no status code below has been observed
  against the live service. `RESEND_API_CONTRACT_VERIFIED` is the greppable form of that
  sentence.

## Hard rule 6 applies at the boundary, and one rung harder here than for SMTP

The body is composed from redacted values before it reaches this module, and this module
logs recipient DOMAINS rather than addresses. An HTTP provider adds a hazard SMTP did
not: **the error body quotes the addresses it rejected**, so nothing here logs a response
body, a `message`, a subject or a body. The one field read out of any response is `id`
(see `_message_id`), and refusals are reported as a status code plus OUR OWN sentence —
the same doctrine `apps/api/ops/secret_probes.py` holds to for the same reason.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any, Protocol

from calevate_shared.config import (
    EMAIL_PROVIDER_RESEND,
    EMAIL_PROVIDER_SMTP,
    NO_RESEND_API_KEY_REASON,
    NO_SMTP_HOST_REASON,
    email_transport_reason,
)

from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings

log = get_logger(__name__)

SMTP_TIMEOUT_S = 15.0

# Is the Resend contract above an OBSERVATION or still a reading? A reading. Flipping it
# is not a code change and not a config change: it needs a Resend account, a live key and
# one accepted send — a VENDOR ACCOUNT, in CLAUDE.md's sense of an external blocker. The
# cheapest thing that moves it is `POST /v1/ops/secrets/resend_api_key/test` returning
# `accepted` (`apps/api/ops/secret_probes.py`), which is why that probe exists.
#
# A constant rather than a comment so the claim is greppable and testable, the same device
# `billing/rates.ENGINE_REPORTS_TTS_MODEL` and `billing/payments.PROVIDER_CREATES_ORDERS`
# use. `apps/workers/transport_test.py` pins it.
RESEND_API_CONTRACT_VERIFIED = False

#: READ AT SOURCE (`resend-openapi/resend.yaml`, `resend-python/resend/emails/_emails.py`).
RESEND_SEND_URL = "https://api.resend.com/emails"

# THE TIMEOUT IS THE POINT — the reason `SMTP_TIMEOUT_S` above exists, and the reason an
# HTTP transport needs its own answer: a call with no deadline parks the alerting daemon
# thread for ever, and that thread is the only one that can tell a human anything.
#
# PHASE BY PHASE RATHER THAN ONE NUMBER, because httpx has no whole-request deadline:
# `timeout=15.0` sets connect, read, write AND pool to 15 seconds EACH, so a stalled
# connect followed by a stalled read is a 30-second park that reads in the source as 15.
# Named phases make the worst case arithmetic instead of a surprise.
#
# THE SUM IS `SMTP_TIMEOUT_S`, AND THAT IS NOT COSMETIC. 15 seconds is the number three
# other places were sized against, none of which this module can see: `alerting`'s bounded
# queue ("an unbounded queue in front of a 15-second SMTP timeout is a memory leak with a
# delay fuse"), `alerting._flush_on_exit`'s shutdown deadline, and
# `scripts/host_alert.FLUSH_TIMEOUT_S` (45s = "a 15-second timeout, one retry after
# `DELIVERY_RETRY_DELAY_S`, plus slack"). A 21-second worst case here would have pushed
# two attempts plus the delay to 47s and made the backup relay report "NOT delivered" for
# mail that was on its way. Keeping the budget equal leaves all three true without
# reaching into files this change does not own. `transport_test.py` pins the arithmetic.
RESEND_TIMEOUT_BUDGET_S = SMTP_TIMEOUT_S
RESEND_CONNECT_TIMEOUT_S = 5.0
RESEND_WRITE_TIMEOUT_S = 3.0
RESEND_READ_TIMEOUT_S = 6.0
RESEND_POOL_TIMEOUT_S = 1.0


class Transport(Protocol):
    name: str

    #: `html` is the ALTERNATIVE part, never the only one. `body` stays required and stays
    #: the text a screen reader, a terminal client and an inbox preview pane read; a
    #: transport that received html and dropped the text would be sending a message some
    #: readers cannot open. Default None so the OTP mails — austere by decision, see
    #: `email_render` — need not pass it, and so `alerting._deliver` and every other
    #: non-auth caller is unchanged.
    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool: ...


def _domain(address: str) -> str:
    """Log the domain, never the mailbox — an email address is personal data."""
    return address.rpartition("@")[2] or "unknown"


def _message_id(decoded: Any) -> str | None:
    """The ONE field this module reads out of a Resend response body.

    Everything else is refused on principle. An error body carries a `message` that
    quotes the addresses it rejected, so logging a body verbatim would put a mailbox into
    a log line (hard rule 6) — which is why `ops/secret_probes.py` reads a status code and
    nothing else, and why refusals here do the same.

    `id` earns its exception: it is an opaque provider identifier with no personal data in
    it, and it is the only join between our log line and the provider's dashboard on the
    day a client says the mail never arrived. Bounded and type-checked so a malformed or
    hostile body cannot widen a log record.
    """
    if not isinstance(decoded, dict):
        return None
    value = decoded.get("id")
    return value[:64] if isinstance(value, str) and value else None


class ResendTransport:
    """One `POST` per message. No SDK, no client reuse, no retry.

    NO RETRY HERE, deliberately: both callers already own a ladder that knows what an
    attempt costs (`notifications.RETRY_BACKOFF_S` against a 2-minute SLO;
    `alerting.DELIVERY_RETRY_DELAY_S` on the delivery thread). A third one inside the
    transport would multiply with them invisibly and would sleep on a thread whose whole
    job is to be responsive.
    """

    name = "resend"

    def __init__(self, api_key: str, sender: str) -> None:
        self._api_key = api_key
        self._sender = sender

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        # IMPORTED HERE, NOT AT MODULE SCOPE, and it is load-bearing rather than a style
        # choice. `alerting._deliver` imports this module on a daemon thread inside
        # `apps/voice-runtime`, whose ack budget is 500ms and whose import surface is
        # asserted (tests/voice_runtime_import_surface_test.py, hard rule 3). httpx pulls
        # httpcore, h11 and certifi, and NONE of them are in that process's boot graph
        # today — measured, not assumed. At module scope they would join it in every
        # deployment, including the ones that never send an email. Deferred, they land
        # once, on the delivery thread, the first time a message is actually sent.
        import httpx

        # `to` as a one-element ARRAY rather than a bare string. Both are schema-valid
        # (READ AT SOURCE), and the array is the shape that does not change meaning if a
        # caller ever passes an address containing a comma.
        payload: dict[str, Any] = {
            "from": self._sender,
            "to": [to],
            "subject": subject,
            "text": body,
        }
        # BOTH PARTS, and `text` is not optional when `html` is present. Resend sends a
        # multipart/alternative when it receives both; given only `html` it sends an
        # HTML-only message, which is the one a plain-text client shows as nothing at all.
        if html is not None:
            payload["html"] = html
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        timeout = httpx.Timeout(
            connect=RESEND_CONNECT_TIMEOUT_S,
            write=RESEND_WRITE_TIMEOUT_S,
            read=RESEND_READ_TIMEOUT_S,
            pool=RESEND_POOL_TIMEOUT_S,
        )
        try:
            # A client per send, matching `ops/secret_probes.py` rather than inventing a
            # pooled global: `get_transport()` already builds a transport per send, so a
            # module-level pooled client would outlive the config it was built from and
            # would need a shutdown hook on four processes. At this volume the cost is one
            # TLS handshake per message, on a thread that is allowed to wait.
            # `follow_redirects=False` is httpx's default and is spelled out because it
            # is a SECURITY property, not a preference: this request carries a bearer
            # credential in a header, and httpx re-sends headers on a same-scheme
            # redirect. A 30x from a hijacked or misconfigured host would hand the key to
            # wherever `Location` pointed. A redirect from `api.resend.com` is not a thing
            # we would follow anyway — it would mean the contract moved.
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                response = client.post(RESEND_SEND_URL, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            # Return False rather than raising: the CALLER decides whether a failed
            # notification should retry the whole job, and it records the outcome on the
            # lead timeline either way. `type(exc).__name__` and never `str(exc)` —
            # httpx puts the request URL, and therefore nothing personal, in the message,
            # but "nothing personal today" is not a property to depend on in a log line.
            log.warning(
                "email_send_failed",
                extra={
                    "transport": self.name,
                    "recipient_domain": _domain(to),
                    "reason": type(exc).__name__,
                },
            )
            return False

        status = response.status_code
        if 200 <= status < 300:
            try:
                decoded = response.json()
            except ValueError:
                # A 2xx with an unparseable body. The send was accepted; we simply have
                # no id to quote. Never a failure — inventing one here would make a
                # delivered message look lost and burn a retry ladder for nothing.
                decoded = None
            log.info(
                "email_sent",
                extra={
                    "transport": self.name,
                    "recipient_domain": _domain(to),
                    "provider_message_id": _message_id(decoded),
                },
            )
            return True

        self._refuse(status, to)
        return False

    def _refuse(self, status: int, to: str) -> None:
        """Say what an operator has to DO, from the status code alone.

        EVERY `remediation` BELOW FITS IN `logging._MAX_FREE_TEXT` (200 chars). It is
        run through `redact_mapping` on the way out like every other string a caller
        supplies, and a sentence that overflows loses its TAIL — which is where the
        instruction is. Pinned by `transport_test.py` rather than left to counting.

        The status is all we take. The `name` field would separate a wrong key from an
        unverified sender domain — both are 403 — but it sits inside the same object as a
        `message` that quotes addresses, and a parser that reaches into that body once
        will be extended to log it. So 403 names BOTH causes and both remediations, which
        is honest and is still one screen away from a fix, and hard rule 6 stays a
        property of the module rather than of the care taken by its next editor.
        """
        recipient_domain = _domain(to)
        sender_domain = _domain(self._sender)
        if status == 403:
            # THE LOUD FAILURE. An unverified sender domain is otherwise the quietest
            # possible outage — every message refused, nothing in an inbox, nothing
            # obviously wrong — so it gets ERROR, its own event name, and the domain that
            # has to be verified. (REPORTED, NOT READ: 403 + `validation_error` for an
            # unverified `from` domain; READ AT SOURCE: 403 + `invalid_api_key`.)
            log.error(
                "email_sender_rejected",
                extra={
                    "transport": self.name,
                    "status": status,
                    "sender_domain": sender_domain,
                    "recipient_domain": recipient_domain,
                    "remediation": (
                        "Resend refused this sender: the key is wrong or revoked, or the "
                        "sender domain is not verified. Check RESEND_API_KEY in this "
                        "host's environment, and the domain in Resend."
                    ),
                },
            )
            return
        if status == 401:
            log.error(
                "email_credential_rejected",
                extra={
                    "transport": self.name,
                    "status": status,
                    "recipient_domain": recipient_domain,
                    "remediation": (
                        "Resend did not accept the API key (absent, or scoped so narrowly "
                        "it cannot send). Set RESEND_API_KEY in this host's environment, "
                        "with Sending access for this domain."
                    ),
                },
            )
            return
        if status in (400, 422):
            # OUR request, not their service. Nothing an operator can fix and nothing a
            # retry can fix either — logged at ERROR because it means this module and the
            # API disagree about the contract, which is the thing
            # `RESEND_API_CONTRACT_VERIFIED` exists to warn about.
            log.error(
                "email_request_rejected",
                extra={
                    "transport": self.name,
                    "status": status,
                    "recipient_domain": recipient_domain,
                    "remediation": (
                        "Resend rejected the request body: a contract mismatch in "
                        "workers/transport.py, not a configuration error."
                    ),
                },
            )
            return
        if status == 429:
            # REPORTED, NOT READ: 2 requests/second, `retry-after` on the response. Not
            # slept on here — the callers' ladders already defer, and sleeping would park
            # the alerting thread for a bound the vendor chooses.
            log.warning(
                "email_rate_limited",
                extra={
                    "transport": self.name,
                    "status": status,
                    "recipient_domain": recipient_domain,
                },
            )
            return
        log.warning(
            "email_send_failed",
            extra={
                "transport": self.name,
                "recipient_domain": recipient_domain,
                "reason": f"http_{status}",
            },
        )


class SmtpTransport:
    """The escape hatch (`EMAIL_PROVIDER=smtp`). See the module docstring for why it is
    kept rather than migrated away: it is what makes a provider outage a config change."""

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

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        # `add_alternative` after `set_content` is what makes this multipart/alternative
        # with the text part FIRST — the order is the standard's, and it is what decides
        # which part a client that understands both chooses to show (the last one) and
        # which a client that understands neither falls back to (the first).
        if html is not None:
            message.add_alternative(html, subtype="html")
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
                extra={
                    "transport": self.name,
                    "recipient_domain": _domain(to),
                    "reason": type(exc).__name__,
                },
            )
            return False
        log.info("email_sent", extra={"transport": self.name, "recipient_domain": _domain(to)})
        return True


class ConsoleTransport:
    """Local dev. Reports success honestly — the message really did get delivered,
    to a terminal.

    **IT PRINTS THE BODY, and until D-409 it did not — which made a local stack
    unsignable-into.** Admin sign-in is password + an emailed six-digit code (D-170),
    the code is stored only as a keyed hash (`authn/codes.py`), and the plaintext exists
    in exactly one place: the message body. This transport logged the recipient's domain,
    the subject and a CHARACTER COUNT, so the one thing a developer needed was the one
    thing thrown away. `scripts/seed_dev.py` handed out working passwords to accounts
    nobody could finish signing in as, and the second factor looked broken when it was
    working perfectly.

    **THIS IS NOT AN MFA BYPASS AND MUST NEVER BECOME ONE.** Nothing in `authn/` changes:
    the challenge is issued, the code is hashed, attempts are counted, the rate limit and
    the ten-minute expiry apply, and a wrong code is refused. A developer reads the code
    they were actually sent and types it in — the same round trip a real operator makes,
    which is the point. A flag that skipped the check would leave `apps/api/authn/otp.py`
    unexercised on every laptop in exactly the code path most worth exercising, and would
    be one misconfigured env var from doing the same in production (CLAUDE.md: never add
    a bypass "for testing").

    **THE BODY IS GATED ON `app_env == "local"`, structurally, and that is defence in
    depth rather than the primary control.** The primary control is selection:
    `get_transport` only reaches this class when the resolver has already established
    APP_ENV=local with no provider named (`config.email_transport_reason`). The check
    below is here because the cost of the two disagreeing is a real customer's message
    printed into an aggregated log, and a second read is cheap next to that.

    **IT GOES IN AN EXTRA RATHER THAN THE MESSAGE**, which is what keeps it redacted.
    `JsonFormatter` sends every extra through `redact_mapping`, so `dev_message` is
    phone-masked on the way out — a six-digit OTP survives (`_PHONE_RE` needs nine-plus
    digits) while a hot-lead alert's caller number does not. The key must stay OUT of
    `REDACT_KEYS`: `body`, `text` and `recipient` are all in it, so the obvious names
    would print `[redacted]` and reintroduce this bug wearing a fix's clothes.
    """

    name = "console"

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        extra: dict[str, Any] = {
            "recipient_domain": _domain(to),
            "subject": subject,
            "chars": len(body),
            # The TEXT is what gets logged, deliberately, even when html exists: a
            # developer reading a terminal wants the link, not 4KB of table markup. The
            # flag is here so "did the branded version render?" is answerable without it.
            "has_html": html is not None,
        }
        if get_settings().app_env == "local":
            # The delivery itself. A sink that reports success while discarding the
            # content did not deliver anything.
            extra["dev_message"] = body
        log.info("email_console", extra=extra)
        return True


class NullTransport:
    """No channel configured. Reports FAILURE, loudly, AND SAYS WHY.

    The alternative — returning True — would make the 2-minute hot-lead SLO look met
    in every dashboard while no client was ever told about a lead.

    `reason` is an authored code from `calevate_shared.config` (`no_email_provider`,
    `no_resend_api_key`, `provider_not_implemented:<name>`, …). It is carried because the
    docstring above has always promised this transport "says why" and, until it existed,
    the log line said only that there was no transport — leaving an operator to guess
    between "nobody set EMAIL_PROVIDER", "the key is missing" and "somebody typed
    sendgrid".
    """

    name = "null"

    def __init__(self, reason: str = "unconfigured") -> None:
        self.reason = reason

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        log.warning(
            "email_no_transport",
            extra={"recipient_domain": _domain(to), "reason": self.reason},
        )
        return False


def get_transport() -> Transport:
    """THE transport this deployment sends through. The only consumer of the selector.

    `email_transport_reason()` (`calevate_shared/config.py`) decides whether email can be
    delivered at all and answers with an authored code; this function does nothing but
    turn that answer into an object. A caller that wants to know whether email works asks
    the resolver, never this — which is why `init_observability`'s boot warning cannot
    drift away from what actually gets built.

    IDEMPOTENCY IS NOT WIRED, and the omission is deliberate rather than overlooked.
    Resend honours an `Idempotency-Key` header for 24 hours (REPORTED, NOT READ), which
    would collapse the double-send that a read timeout plus a retry can produce. It is not
    added because only the CALLER knows what "the same email" means: a key derived here
    from the message content would give two genuinely separate alerts with identical text
    the same key, silently stretching `alerting.ALERT_REPEAT_INTERVAL_S` from fifteen
    minutes to twenty-four hours — a worse defect than the one it fixes. Wiring it means
    `Transport.send` growing a caller-supplied key, `notifications` passing
    `lead+call`, and `alerting` minting one per notice. That is a change to both
    consumers' contracts, and the double-send it prevents is a property SMTP had too, so
    this migration neither introduces it nor is the moment to fix it.
    """
    settings = get_settings()
    reason = email_transport_reason(settings)
    if reason is not None:
        return NullTransport(reason=reason)

    provider = (settings.email_provider or "").strip().lower()
    # Non-None whenever the resolver returned None — it refuses `no_sender_address` — so
    # this read cannot be empty. Spelled with a fallback anyway only where mypy needs the
    # narrowing, never as a second rule about what the sender is.
    sender = settings.notifications_from or ""

    if provider == EMAIL_PROVIDER_RESEND:
        api_key = settings.resend_api_key
        if api_key is None:  # unreachable; the resolver already refused it by this name
            return NullTransport(reason=NO_RESEND_API_KEY_REASON)
        return ResendTransport(api_key=api_key, sender=sender)

    if provider == EMAIL_PROVIDER_SMTP:
        host = settings.smtp_host
        if host is None:  # unreachable, as above
            return NullTransport(reason=NO_SMTP_HOST_REASON)
        return SmtpTransport(
            host=host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            sender=sender,
            use_tls=settings.smtp_use_tls,
        )

    # No provider named, and the resolver allowed it: APP_ENV=local, the dev sink.
    return ConsoleTransport()


__all__ = [
    "RESEND_API_CONTRACT_VERIFIED",
    "RESEND_SEND_URL",
    "RESEND_TIMEOUT_BUDGET_S",
    "ConsoleTransport",
    "NullTransport",
    "ResendTransport",
    "SmtpTransport",
    "Transport",
    "get_transport",
]
