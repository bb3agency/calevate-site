"""WhatsApp transport for hot-lead alerts (ROADMAP M2: "WhatsApp follow-up + hot-lead
WhatsApp alerts"; FLOWS §6 "status hot OR urgency=emergency ⇒ WhatsApp+email to owner
within 2 min").

**This module is the transport, the jobs and the seam. The vendor half lives next door
in `apps/workers/whatsapp_cloud.py` and is UNTESTED AGAINST A REAL WABA — see below.**

This module used to ship no adapter at all, on the stated grounds that "an adapter
written against an imagined API is worse than none, because it looks finished", because
ROADMAP §6 carried no D-entry choosing a WhatsApp Business Solution Provider. **D-91
chooses one: Meta Cloud API DIRECTLY, no BSP.** The argument, in the order that decides
it for a two-person pre-revenue company:

  * **Self-serve, no sales process.** A WABA is created and a number onboarded through
    the Meta Developer Console without talking to anyone; Business Verification (2-4
    business days) is needed only to raise messaging limits, not to send. Gupshup's
    India pricing is negotiated case-by-case, which is a sales process by another name
    and disqualifying at our size.
  * **The monthly floor dominates, exactly as D-32 said it would for LiveKit.** Cloud
    API has no platform fee — Meta hosts it and charges per delivered message. Every
    BSP in the Indian market charges a floor first: AiSensy and Interakt from
    ₹1,499/agent/mo, WATI Growth ₹2,199/mo, all before a single message. Our OWN
    message spend at launch volume is smaller than any of those floors (worked in
    `whatsapp_cloud.py`), so a BSP would roughly triple the cost of this feature to
    supply an inbox and a campaign builder — which is the product we are building.
  * **Residency, the D-36 argument applied here.** Cloud API Local Storage lists IN as
    a supported region, so message payloads can be pinned to India after processing. A
    BSP inserts its own store in front of that, and its residency is then the BSP's
    claim rather than a control we hold.
  * **Template approval is Meta's loop either way.** Every BSP submits into the same
    review; none shortens it (machine review in minutes, human review up to ~48h). A
    BSP inserts itself into that loop without improving it.

What ships behind the seam is one class with one method, exactly as this docstring
promised. Shape mirrors `workers/transport.py` and `workers/google_sheets.py`: a
Protocol, a dev sink that needs no credentials and no network, an `Unconfigured` sink
that refuses loudly, and the real provider chosen by config.

**WHAT WE CANNOT PROVE, SAID PLAINLY.** There is no WABA, no phone number id and no
access token in this repository, and `graph.facebook.com` / `developers.facebook.com`
are both blocked by this build environment's egress proxy. So `whatsapp_cloud.py` is
written from documentation (marked source by source, the way `apps/api/ingest/meta.py`
marks its Meta sources) and has **never exchanged a byte with Meta**. It carries a
greppable `CLOUD_API_CONFIRMED_AGAINST_LIVE_WABA = False` and a named operational gate,
for the same reason `billing/payments.py::PROVIDER_CREATES_ORDERS` and
`ingest/meta.py::LEAD_RETRIEVAL_IMPLEMENTED` do: a vendor half nobody has run is a
claim, and the honest place to record a claim is beside the code making it.

**Template gate, encoded rather than described.** A business-initiated WhatsApp message
must use a pre-approved template; free text is only allowed inside a 24-hour customer
service window that a notification cannot rely on. `WhatsAppMessage` therefore has no
body field at all — a template name, a locale and positional variables. There is no way
to send prose from this module.

**Who the recipient is decides which rules bite.** This message goes to OUR CLIENT
about their own lead — not to the consumer. So TRAI/DLT (which governs commercial
telecom traffic to subscribers) is not the operative regime here, and neither is the
caller-consent machinery in `consent_ledger` (that ledger records the CALLER's consent,
keyed to a call). What does bite:
  * Meta's own policy — the business owner must have opted in to receive messages from
    the Calevate WABA, and the opt-in must be recorded with when and how.
  * DPDP — the client owner's phone number is personal data we process, and the lead's
    details would be a THIRD party's personal data handed to a US-headquartered
    processor. Which is why the template below carries no consumer data whatsoever:
    the WhatsApp message is a NUDGE, the dashboard is where the data lives. That also
    makes the template trivial to get approved and survives a forwarded screenshot.

**The opt-in has a home now** — `whatsapp_alert_optin_ledger`, migration
`e6b2d94f31a7`, read through `compliance.whatsapp_optin`. It is a LEDGER rather than
columns on `organizations`, and it belongs to a PERSON rather than to an org; the
migration argues both, and `resolve_destination` says what each key buys. The gate below
still refuses by name (`recipient_not_opted_in`) when no live grant exists, which is the
default of the world and stays the honest behaviour: an un-recorded opt-in is a policy
violation, not a formality. What changed is that the refusal is now fixable by the owner
saying yes, on their own settings screen, at `POST /v1/compliance/whatsapp-alerts`.
`whatsapp_enabled` still defaults to False so that refusal is silent rather than an
alert per lead until the switch-on checklist is done.

Retry doctrine is the one that landed for the email path (`workers/notifications.py`,
FLOWS §6): a worker earns a retry ONLY by raising `arq.Retry` — under arq 0.28 a plain
raise is terminal on the first attempt — transport failures get the ladder, permanent
rejections (unapproved template, recipient not opted in, no provider) do not, and a
message that never went out ALERTS rather than returning quietly. Nobody being told
about a hot lead is the exact failure this feature exists to prevent.

Hard rule 6: the destination number is never logged, not even masked and not even in a
fingerprint. `transport.py` logs an email DOMAIN because a domain is shared, low-entropy
and not a person; a phone number has no such component, so the logs here carry ids and
template names only.

---

**Two messages live here, and they go to opposite ends of the business.**

The hot-lead alert above goes to OUR CLIENT about their own lead. The campaign
escalation below (`escalate_campaign_contact`, ROADMAP §3 bullet 1, FLOWS §4.5 "after
exhaustion: WhatsApp/SMS follow-up") goes to a CONSUMER who did not answer a phone
call — which changes which rules bite, and how hard:

  * **TRAI/DLT is operative now.** This is commercial traffic to a subscriber, so the
    escalation runs through `compliance.service.check_dispatch` — the same gate every
    dial passes, giving it the live DNC read (hard rule 5), the calling window and the
    big red switch. There is no messaging-specific bypass: a person who asked not to be
    contacted, and then did not answer the phone, is the last person a follow-up may
    reach.
  * **Meta's opt-in is the consumer's, not the client's.** Consent to be CALLED — the
    campaign's list provenance (SEC-COMP §3) — is not opt-in to be MESSAGED by our
    WABA. `consent_ledger` is where that opt-in lives, under the `messaging` purpose
    added by migration `c2f7a91b4e63`, and `apps/api/compliance/consent.py` is the one
    place that reads or writes it. A contact nobody has opted in is still refused —
    that is the default of the world, and it is RECORDED rather than alerted for
    exactly that reason. What changed is that the refusal is now fixable by somebody
    saying yes, through `POST /v1/compliance/messaging-consent`.

SMS, the other half of the FLOWS §4.5 sentence, is NOT built: there is no SMS transport
anywhere in this repo, no provider in the decision log, and `dlt_templates.kind` is a
CHECK constrained to `'voice'` — an SMS follow-up needs its own DLT content-template
registration under the client's PE. Building it would mean inventing all three.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from arq import Retry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.consent import read_messaging_consent
from apps.api.compliance.service import check_dispatch
from apps.api.compliance.whatsapp_optin import read_alert_optin
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session
from apps.api.reliability.service import enqueue_outbox_once

log = get_logger(__name__)

JOB_NAME = "notify_hot_lead_whatsapp"

# The channel discriminator written into every `lead_events.notification` row this
# module creates. `lead_events.type` is a fixed CHECK enum (crm/models.py) with no
# whatsapp member and this milestone ships no migration, so the channel lives in the
# payload — exactly where the email path already puts `"channel": "email"`.
CHANNEL = "whatsapp"

# Seconds before each retry, indexed by the attempt that just failed. One shorter than
# the budget because the last attempt has nothing after it. Same numbers as the email
# ladder: both are racing the same 2-minute hot-lead SLO.
RETRY_BACKOFF_S: tuple[float, ...] = (15.0, 45.0)

# The template body a human must submit for approval, kept next to the code that fills
# it so the two cannot drift:
#
#     "Calevate: a hot lead just came in ({{1}}). Open your dashboard to see the
#      details and call them back."
#
# ONE variable, no consumer name, no phone number, no call summary. Meta rejects
# templates whose variables could be arbitrary content, and we would fail a DPDP
# question about handing a caller's details to a foreign processor. The nudge is the
# product here; the data stays behind the client's login.
TEMPLATE_VARIABLE_COUNT = 1


# --- the message ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WhatsAppMessage:
    """A template invocation. There is deliberately no `body` field.

    Business-initiated WhatsApp messaging is template-gated; a type that cannot express
    free text cannot accidentally send it when someone is in a hurry.
    """

    to_e164: str
    template: str
    locale: str
    variables: tuple[str, ...]


class SendStatus(StrEnum):
    DELIVERED = "delivered"
    # The provider could not be reached, or reported a condition that may pass. Worth
    # another go inside the SLO window.
    TRANSPORT_FAILED = "transport_failed"
    # A verdict on the request: unapproved template, recipient not opted in, no
    # provider configured. Retrying only delays the same answer three times over.
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class SendResult:
    status: SendStatus
    # An authored code (`template_not_approved`), never vendor prose — a provider error
    # string is untrusted text that may quote the payload we just sent it.
    reason: str = ""

    @property
    def retryable(self) -> bool:
        return self.status is SendStatus.TRANSPORT_FAILED

    @property
    def delivered(self) -> bool:
        return self.status is SendStatus.DELIVERED


class WhatsAppTransport(Protocol):
    name: str

    # ASYNC, unlike `transport.Transport.send` next door, and the difference is not
    # taste. That one is a blocking SMTP client on purpose — `core/alerting.py` calls it
    # from its own daemon thread, which is what lets the alarm path touch no event loop.
    # This one talks HTTP to a vendor from inside an arq worker that is already async,
    # so a blocking implementation would park the loop for the length of a round trip to
    # Meta and stall every other job on the same worker. Same shape as
    # `sheets_sync.SheetsTransport.append`, which made this call before us.
    async def send(self, message: WhatsAppMessage) -> SendResult: ...


# --- transports ----------------------------------------------------------------


class ConsoleWhatsAppTransport:
    """Local dev + the test suite. No credentials, no network, no vendor account.

    Reports DELIVERED honestly, for the same reason `ConsoleTransport` does: the
    message really did arrive — in the developer's terminal. Never logs `to_e164`.
    """

    name = "console"

    async def send(self, message: WhatsAppMessage) -> SendResult:
        log.info(
            "whatsapp_console",
            extra={
                "template": message.template,
                "locale": message.locale,
                "variables": len(message.variables),
            },
        )
        return SendResult(SendStatus.DELIVERED)


class UnconfiguredWhatsAppTransport:
    """No usable provider. Reports REJECTED — permanently, and says why.

    Returning DELIVERED would make the 2-minute SLO look met on every dashboard while
    no client was ever pinged, which is the failure `transport.NullTransport` was
    written to prevent on the email side. REJECTED rather than TRANSPORT_FAILED because
    three retries cannot configure a vendor account.
    """

    name = "unconfigured"

    def __init__(self, reason: str) -> None:
        self._reason = reason

    @property
    def reason(self) -> str:
        """Read by `whatsapp_delivery_status()` so the settings screen can say WHICH
        thing is missing rather than a bare "unavailable"."""
        return self._reason

    async def send(self, message: WhatsAppMessage) -> SendResult:
        log.warning("whatsapp_no_transport", extra={"reason": self._reason})
        return SendResult(SendStatus.REJECTED, reason=self._reason)


# The provider name that selects the Meta Cloud API adapter (D-91). Declared HERE rather
# than in the adapter so the selector below needs no import to decide it is not wanted —
# the seam depends on nothing, the adapter depends on the seam (the rule
# `sheets_sync.get_sheets_transport` states).
CLOUD_API_PROVIDER = "meta_cloud_api"
CONSOLE_PROVIDER = "console"

# Authored refusal codes for the states a DEPLOYMENT can be in. Each one names the single
# thing an operator has to go and do, because "unavailable" is not an instruction.
NO_PROVIDER_REASON = "no_provider_configured"
NO_TOKEN_REASON = "cloud_api_access_token_missing"
NO_PHONE_ID_REASON = "cloud_api_phone_number_id_missing"
DEV_SINK_OUTSIDE_LOCAL_REASON = "dev_sink_refused_outside_local"
PROVIDER_NOT_IMPLEMENTED_REASON = "provider_not_implemented"

# The Graph API version to call when the deployment does not pin one. Meta versions the
# Graph API and unversioned calls are not a supported form, so a default is required
# rather than optional — and a STALE pinned version fails loudly at the vendor, which is
# better than a floating one changing behaviour under us on Meta's release schedule.
DEFAULT_GRAPH_VERSION = "v22.0"


# ---------------------------------------------------------------------------------
# TEMPORARY SHIM — DELETE THE `getattr`s WHEN THE SETTINGS KEYS LAND.
#
# `Settings` is `extra="forbid"` (packages/shared/.../config.py), so these three keys
# must be DECLARED there before they can be read at all — and this slice is not the
# owner of that file. Until they are declared, this reads them defensively so the module
# typechecks and behaves correctly (absent key == absent credential == a named refusal),
# which is exactly what a deployment without them should do anyway.
#
# The keys to declare, verbatim:
#     whatsapp_cloud_access_token: str | None = None
#     whatsapp_cloud_phone_number_id: str | None = None
#     whatsapp_cloud_graph_version: str = "v22.0"
#
# When they exist, each `getattr(settings, "x", None)` below becomes `settings.x` and
# this comment goes with them. Nothing else in this module changes.
# ---------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _CloudApiConfig:
    access_token: str
    phone_number_id: str
    graph_version: str


def _cloud_api_config() -> _CloudApiConfig:
    settings = get_settings()
    return _CloudApiConfig(
        access_token=str(getattr(settings, "whatsapp_cloud_access_token", "") or "").strip(),
        phone_number_id=str(getattr(settings, "whatsapp_cloud_phone_number_id", "") or "").strip(),
        graph_version=str(
            getattr(settings, "whatsapp_cloud_graph_version", "") or DEFAULT_GRAPH_VERSION
        ).strip(),
    )


@dataclass(frozen=True, slots=True)
class DeliveryStatus:
    """Can THIS deployment send a WhatsApp message at all, and if not, which thing is
    missing?"""

    available: bool
    # An authored code (`cloud_api_access_token_missing`), or None when available.
    reason: str | None


def whatsapp_delivery_status() -> DeliveryStatus:
    """THE selection decision, made once, in one place.

    Both callers below are downstream of this: `get_whatsapp_transport()` turns the
    verdict into an object that can send (or refuse), and the opt-in surface renders the
    same verdict as a sentence so a client is never offered a channel this deployment
    cannot deliver on. That is the rule `sheets_delivery_available()` states — a screen
    that decided for itself whether WhatsApp works would eventually disagree with the
    worker, and the disagreement reads as "the screen says on and no message ever
    arrives".

    It is factored as the DECISION rather than as "call the factory and look at what came
    back", which is how the sheets pair does it, and the difference is deliberate:
    `scripts/check_compliance_invariants.py` treats every call of
    `get_whatsapp_transport` as a send site that must first consult
    `Destination.opt_in_at`. That is a rule worth keeping true — a function holding a
    live transport IS one line away from sending — so the capability read shares the
    decision instead of borrowing the factory, and the guardrail keeps its teeth.

    Note what it does NOT claim. It answers for the TRANSPORT — a provider is named and
    its credentials are present. Whether those credentials authenticate, whether the
    template is approved, and whether the WABA exists are facts only a live send can
    establish, and `CLOUD_API_CONFIRMED_AGAINST_LIVE_WABA` records that none of them has
    been. `whatsapp_enabled` is a separate switch and stays off until they have.
    """
    settings = get_settings()
    provider = (settings.whatsapp_provider or "").strip().lower()

    if provider == CLOUD_API_PROVIDER:
        config = _cloud_api_config()
        # Two separate reasons rather than one "not configured": they are two different
        # errands (mint a system-user token vs copy the number id out of the console),
        # and an operator reading a log line deserves to be told which one is left.
        if not config.access_token:
            return DeliveryStatus(available=False, reason=NO_TOKEN_REASON)
        if not config.phone_number_id:
            return DeliveryStatus(available=False, reason=NO_PHONE_ID_REASON)
        return DeliveryStatus(available=True, reason=None)

    if provider == CONSOLE_PROVIDER:
        if settings.app_env != "local":
            # An explicit dev sink outside local is operator error, and it is the kind
            # that reports success forever. Refuse it rather than swallow leads.
            return DeliveryStatus(available=False, reason=DEV_SINK_OUTSIDE_LOCAL_REASON)
        return DeliveryStatus(available=True, reason=None)
    if provider:
        return DeliveryStatus(
            available=False, reason=f"{PROVIDER_NOT_IMPLEMENTED_REASON}:{provider}"
        )
    if settings.app_env == "local":
        return DeliveryStatus(available=True, reason=None)
    return DeliveryStatus(available=False, reason=NO_PROVIDER_REASON)


def get_whatsapp_transport() -> WhatsAppTransport:
    """The thing that can send, built from the verdict above.

    `whatsapp_provider` is the seam D-91 lands in. `meta_cloud_api` selects the real
    adapter; any OTHER name still resolves to `provider_not_implemented`, on purpose:
    setting `WHATSAPP_PROVIDER=gupshup` must fail loudly rather than look configured,
    because we have not written that adapter and a BSP is not a drop-in for Cloud API.

    **A named provider with missing credentials is a REFUSAL, not a fallback.** It would
    be easy to fall back to the console sink or to "no provider" here; both would report
    a channel that cannot send. The refusal carries the reason `whatsapp_delivery_status`
    already computed, so the string an operator reads in a log and the string a client
    reads on their settings screen are the same string.
    """
    status = whatsapp_delivery_status()
    if status.reason is not None:
        return UnconfiguredWhatsAppTransport(status.reason)

    settings = get_settings()
    provider = (settings.whatsapp_provider or "").strip().lower()
    if provider == CLOUD_API_PROVIDER:
        # Imported HERE, not at module scope: `apps.workers.whatsapp_cloud` imports this
        # module for the message type and the result vocabulary, so a top-level import
        # would be a cycle — the same resolution `sheets_sync` uses for its adapter.
        from apps.workers.whatsapp_cloud import CloudApiWhatsAppTransport

        config = _cloud_api_config()
        return CloudApiWhatsAppTransport(
            access_token=config.access_token,
            phone_number_id=config.phone_number_id,
            graph_version=config.graph_version,
        )
    # Available and not the cloud adapter leaves exactly one case: the dev sink, either
    # named explicitly under `local` or fallen back to under `local`. Anything else was
    # already returned as a refusal above.
    return ConsoleWhatsAppTransport()


# --- who receives it -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Destination:
    to_e164: str
    # When the recipient opted in to WhatsApp from the Calevate WABA. `None` means "we
    # cannot show an opt-in", which is treated as "not opted in" — never as consent.
    opt_in_at: datetime | None


async def resolve_destination(session: AsyncSession, tenant_id: UUID) -> Destination | None:
    """The client's owner, and whether we can EVIDENCE their opt-in.

    Number: the owner-role member's `users.phone` (E.164). Deactivated
    users are excluded — a removed owner must not keep receiving the business's leads.

    Opt-in: `whatsapp_alert_optin_ledger`, through `compliance.whatsapp_optin` — the one
    implementation of "may we alert this person", shared with the settings screen and
    the admin surface that capture it, so the worker and the console can never disagree.
    Migration `e6b2d94f31a7` created it; that migration and
    `compliance/whatsapp_optin.py` carry the argument for the shape, and in particular
    for why this is a LEDGER and not the three columns this docstring used to ask for
    (a state column makes revocation an UPDATE that destroys the evidence of the opt-in
    that was live when last month's alerts went out).

    **The read is keyed to (tenant, THIS user, THIS number), and all three legs matter.**
    They are what lets that ledger carry no expiry column: an owner handover finds no row
    for the new person, a changed number finds no row for the new number, and a
    deactivated owner is excluded by the query above — each fails closed on a fact we
    observe at send time rather than on a clock that would switch a client's hot-lead
    alerts off on a day nobody is watching.
    """
    row = (
        await session.execute(
            text(
                "SELECT u.id, u.phone FROM memberships m JOIN users u ON u.id = m.user_id "
                "WHERE m.tenant_id = :tid AND m.role = 'owner' "
                "AND u.deactivated_at IS NULL AND u.phone IS NOT NULL "
                "ORDER BY m.created_at LIMIT 1"
            ),
            {"tid": tenant_id},
        )
    ).first()
    if row is None or not row[1]:
        return None
    user_id, phone_e164 = UUID(str(row[0])), str(row[1])
    state = await read_alert_optin(
        session, tenant_id=tenant_id, user_id=user_id, phone_e164=phone_e164
    )
    # `messageable`, not `status == "granted"`: the property is where "what counts as a
    # live opt-in" is defined, and the two must not be able to disagree — the same rule
    # `resolve_escalation_destination` follows for the consumer ledger.
    return Destination(
        to_e164=phone_e164, opt_in_at=state.captured_at if state.messageable else None
    )


# --- the job -------------------------------------------------------------------


def _retry_after(attempt: int) -> float:
    index = min(attempt, len(RETRY_BACKOFF_S)) - 1
    return RETRY_BACKOFF_S[max(index, 0)]


def _compose_variables(triggers: list[str]) -> tuple[str, ...]:
    """The single approved template variable: WHY this lead is hot.

    Trigger keys are our own vocabulary (`pipeline.HOT_LEAD_FIELD_TRIGGERS`), not
    caller-supplied text, so nothing here can carry a name, a number or a transcript
    fragment into a third party's system.
    """
    return (", ".join(triggers) if triggers else "marked hot",)


async def notify_hot_lead_whatsapp(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Second channel for the FLOWS §6 hot-lead alert. Its OWN job, not a branch of
    `notify_hot_lead`.

    Separate on purpose: the email job returns `duplicate` as soon as its own delivery
    is recorded, so a WhatsApp failure retried through that job would short-circuit at
    the email dedupe and never reach the transport again — a ladder that cannot climb.
    Two jobs, two records, two independent ladders, one enqueue point.
    """
    tenant_id = UUID(str(payload["tenant_id"]))
    lead_id = UUID(str(payload["lead_id"]))
    call_id = UUID(str(payload["call_id"]))
    triggers: list[str] = list(payload.get("triggers") or [])
    attempt = int(ctx.get("job_try", 1))
    settings = get_settings()

    if not settings.whatsapp_enabled:
        # Not a failure: email is the channel of record until a human completes the
        # switch-on checklist. Alerting per lead here would train everyone to ignore
        # this alert before it ever means anything.
        return "disabled"

    async with tenant_session(tenant_id) as session:
        if await _already_delivered(session, lead_id=lead_id, call_id=call_id):
            return "duplicate"

        destination = await resolve_destination(session, tenant_id)
        if destination is None:
            result = SendResult(SendStatus.REJECTED, reason="no_recipient")
        elif destination.opt_in_at is None:
            # Meta policy and DPDP both land here. Permanent by nature: the same row
            # will be just as un-opted-in in two minutes.
            result = SendResult(SendStatus.REJECTED, reason="recipient_not_opted_in")
        else:
            result = await get_whatsapp_transport().send(
                WhatsAppMessage(
                    to_e164=destination.to_e164,
                    template=settings.whatsapp_template_hot_lead,
                    locale=settings.whatsapp_template_locale,
                    variables=_compose_variables(triggers),
                )
            )

        # Recorded whatever happened, and recorded ONCE per (lead, call, channel)
        # however many attempts it takes — "I was never told" has to be answerable
        # from the timeline, including when the answer is "you are right".
        await _record_attempt(
            session,
            tenant_id=tenant_id,
            lead_id=lead_id,
            call_id=call_id,
            result=result,
            attempts=attempt,
            triggers=triggers,
            template=settings.whatsapp_template_hot_lead,
        )

    if result.delivered:
        # Ids only (hard rule 6). `attempts` is here because "delivered on the third
        # try" and "delivered immediately" are the same outcome and very different
        # health signals against a 2-minute SLO.
        log.info(
            "whatsapp_hot_lead_notified",
            extra={"lead_id": str(lead_id), "attempts": attempt},
        )
        return "sent"

    if result.status is SendStatus.REJECTED:
        # A verdict, not a blip: config, consent or template. The ladder is skipped and
        # a human is told immediately, because only a person can close any of those —
        # and the lead is just as un-notified while they are open.
        alert(
            "WORKER_TERMINAL",
            "hot_lead_whatsapp_rejected",
            detail=f"whatsapp hot-lead alert refused: {result.reason}",
            tenant_id=str(tenant_id),
            lead_id=str(lead_id),
        )
        return f"rejected {result.reason}"

    if attempt < WORKER_MAX_TRIES:
        # The one exception arq treats as "not finished" (arq 0.28 retries for Retry /
        # RetryJob / CancelledError and nothing else). The attempt row is already
        # committed — the session closed above — so the retry resumes from a recorded
        # attempt rather than from nothing.
        raise Retry(defer=_retry_after(attempt))

    alert(
        "WORKER_DELIVERY",
        "hot_lead_whatsapp_exhausted",
        detail=f"whatsapp hot-lead alert undelivered after {attempt} attempt(s)",
        tenant_id=str(tenant_id),
        lead_id=str(lead_id),
    )
    return f"exhausted after {attempt}"


# --- the delivery record -------------------------------------------------------


async def _already_delivered(session: AsyncSession, *, lead_id: UUID, call_id: UUID) -> bool:
    """Has the WhatsApp alert for this lead+call actually REACHED someone?

    Scoped to `channel = 'whatsapp'` in both directions, so the two channels can never
    answer for each other: a delivered email must not make the WhatsApp ladder report
    success, and a recorded WhatsApp attempt must not satisfy the email dedupe.

    A recorded ATTEMPT is not an answer to this question — only `delivered: true` is.
    Treating an attempt as a duplicate is what would make the retry ladder decorative.
    """
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM lead_events WHERE lead_id = :lid AND type = 'notification' "
                "AND payload->>'channel' = :channel AND payload->>'call_id' = :cid "
                "AND payload->>'delivered' = 'true' LIMIT 1"
            ),
            {"lid": lead_id, "cid": str(call_id), "channel": CHANNEL},
        )
    ).first()
    return row is not None


async def _record_attempt(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    lead_id: UUID,
    call_id: UUID,
    result: SendResult,
    attempts: int,
    triggers: list[str],
    template: str,
) -> None:
    """One timeline row per (lead, call, channel), updated in place as the ladder walks.

    Update-then-insert rather than `ON CONFLICT`, because `lead_events` has no unique
    key for this shape (same pattern as `notifications._record_attempt` and
    `pipeline._persist_extraction`). `lead_events` is a timeline, not one of the
    append-only ledgers of hard rule 4, so flipping `delivered` to true when a retry
    finally lands is the honest record — and an alert that never landed stays visible
    as one instead of disappearing.

    Note the `channel` predicate on the UPDATE: without it this would also rewrite the
    email path's row for the same call, and a client asking "was I told?" would get one
    channel's answer for both.
    """
    body = _json(
        {
            "call_id": str(call_id),
            "channel": CHANNEL,
            "delivered": result.delivered,
            "status": str(result.status),
            "reason": result.reason,
            "template": template,
            "attempts": attempts,
            "triggers": triggers,
        }
    )
    updated = await session.execute(
        text(
            "UPDATE lead_events SET payload = CAST(:payload AS jsonb), updated_at = now() "
            "WHERE lead_id = :lid AND type = 'notification' "
            "AND payload->>'channel' = :channel AND payload->>'call_id' = :cid"
        ),
        {"payload": body, "lid": lead_id, "cid": str(call_id), "channel": CHANNEL},
    )
    if rowcount_of(updated) == 0:
        await session.execute(
            text(
                "INSERT INTO lead_events (id, tenant_id, lead_id, type, payload, actor, "
                "created_at, updated_at) VALUES (:id, :tid, :lid, 'notification', "
                "CAST(:payload AS jsonb), 'system', now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_id, "lid": lead_id, "payload": body},
        )


# --- the enqueue point (this is what `notifications.py` calls) -----------------


async def enqueue_hot_lead_whatsapp(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    lead_id: UUID,
    call_id: UUID,
    triggers: list[str],
) -> bool:
    """Queue the WhatsApp alert through the OUTBOX, in the caller's transaction.

    Called from `notifications.notify_hot_lead` — one `await` inside the session block
    that job already holds open, so the outbox row and the email's delivery record share
    one transaction and one fate. Returns whether a message was enqueued, so the caller
    can log it without needing to know why not.

    The `whatsapp_enabled` gate is HERE rather than at the call site because the caller
    should not have to know that a disabled channel is a no-op: the email job asks for
    the second channel unconditionally and this decides whether there is one. Note what
    that means for the timeline — while the channel is off, nothing is queued and so
    nothing is RECORDED, which is the deliberate difference from the campaign escalation
    below (`enqueue_campaign_escalation`, which is not gated and records its refusal):
    that path has no second channel, this one has email as its channel of record.

    Queued once per (lead, call), and that is now a UNIQUE index rather than a scan
    followed by an insert (P6.7). The key is its own — `hot-lead-whatsapp:` rather than
    the email leg's `hot-lead:` — because the two channels are separately queued and a
    shared key would make whichever ran first silently suppress the other.
    """
    if not get_settings().whatsapp_enabled:
        return False
    return (
        await enqueue_outbox_once(
            session,
            job=JOB_NAME,
            payload={
                "tenant_id": str(tenant_id),
                "lead_id": str(lead_id),
                "call_id": str(call_id),
                "triggers": triggers,
            },
            dedupe_key=f"hot-lead-whatsapp:{lead_id}:{call_id}",
        )
        is not None
    )


# --- campaign escalation: the follow-up after the dial ladder is spent --------
#
# ROADMAP §3 bullet 1's named gap. FLOWS §4.5 and §5: "No-answer → retry policy
# (respecting hours) → after exhaustion: WhatsApp/SMS follow-up template". Until this
# existed, a contact that burned its attempts went `failed` and nothing else happened —
# no message, no record, no operator signal. A lead the client paid for went cold in
# silence, which is the same failure the hot-lead ladder above was written to prevent.


ESCALATION_JOB_NAME = "escalate_campaign_contact"

# The discriminator INSIDE the whatsapp channel. Both messages write
# `lead_events.type = 'notification'` with `channel = 'whatsapp'` (the type column is a
# fixed CHECK enum and this milestone ships no migration), so without `kind` a delivered
# hot-lead alert and an un-sent follow-up would answer for each other on the same lead.
ESCALATION_KIND = "campaign_escalation"

# The template a human must submit for approval, kept next to the code that fills it:
#
#     "{{1}} tried to reach you by phone and could not get through. Reply here or call
#      back when it suits you."
#
# ONE variable, and it is the CLIENT's business name — Meta requires a business-initiated
# message to identify who is contacting the recipient, and the recipient has no idea who
# "Calevate" is. Nothing about the enquiry, the call or the person crosses to a foreign
# processor: the number is already the minimum a message needs, and everything else stays
# behind the client's login (the same DPDP reasoning as the hot-lead template above).
#
# It is a module constant rather than a setting because a template name is only meaningful
# alongside the body approved for it, and the two must not drift; `whatsapp_template_locale`
# is reused for the locale, since a client's callers get one language from the agent too.
TEMPLATE_MISSED_CALL = "calevate_missed_call_follow_up_v1"


@dataclass(frozen=True, slots=True)
class _Escalation:
    """Everything the follow-up needs, read in one round trip."""

    campaign_id: UUID
    agent_id: UUID
    lead_id: UUID | None
    phone_e164: str
    status: str
    business_name: str


async def resolve_escalation_destination(
    session: AsyncSession, *, tenant_id: UUID, phone_e164: str
) -> Destination:
    """The contact themself, plus whether we can EVIDENCE their opt-in to be messaged.

    The number is not in doubt — we just dialled it. The opt-in is, and it is a different
    opt-in from every other consent this system records:

      * `campaigns.consent_source` says the client may CALL this list (SEC-COMP §3). A
        person who agreed to be phoned about their enquiry has not thereby agreed to
        receive WhatsApp from a WABA they have never heard of; Meta's business-initiated
        rules and DPDP's purpose limitation both read that as a separate permission.
      * the ledger's `recording`/`callback` rows record what a CALLER agreed to DURING a
        call, keyed to `call_id`. This person never took the call — that is the entire
        reason we are here.

    So the question is asked of the `messaging` purpose specifically, through
    `compliance.consent.read_messaging_consent` — the one implementation of "may we
    message this person", shared with the client-facing capture surface so the worker
    and the console can never disagree. That function is where the latest-row-wins
    rule, the validity window and the research behind both are written down.
    """
    state = await read_messaging_consent(session, tenant_id=tenant_id, phone_e164=phone_e164)
    # `messageable`, not `status == "granted"`: an opt-in older than the validity window
    # is a record of something that WAS true. The two differ on exactly the row a
    # five-year-old campaign list would produce.
    return Destination(
        to_e164=phone_e164, opt_in_at=state.captured_at if state.messageable else None
    )


def _compose_escalation_variables(business_name: str) -> tuple[str, ...]:
    """The single approved variable: who is contacting them. Our client's own trading
    name — not the consumer's name, not the enquiry, not the agent's transcript."""
    return (business_name,)


async def escalate_campaign_contact(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """The follow-up for a contact whose dial ladder is spent (FLOWS §4.5).

    Its own job with its own record and its own ladder, for the same reason the hot-lead
    WhatsApp alert is not a branch of the email job: two outcomes that can fail
    independently must be able to retry independently.

    Every non-delivery is RECORDED on the lead timeline before this function returns,
    whatever the reason — an unconfigured provider, an opt-out, a missing opt-in, a
    switched-off channel. "We never followed up" is a fact the client is entitled to see;
    a follow-up that quietly evaporates is indistinguishable from one that landed.
    """
    tenant_id = UUID(str(payload["tenant_id"]))
    contact_id = UUID(str(payload["contact_id"]))
    attempt = int(ctx.get("job_try", 1))
    settings = get_settings()

    async with tenant_session(tenant_id) as session:
        escalation = await _load_escalation(session, contact_id=contact_id)
        if escalation is None:
            # The contact (or its campaign) is gone. Nothing to follow up and nowhere to
            # record it; ids only.
            log.warning(
                "campaign_escalation_contact_missing", extra={"contact_id": str(contact_id)}
            )
            return "contact_missing"
        if escalation.status != "failed":
            # The reaper put this contact back on the dial ladder between the enqueue and
            # now. Phoning beats messaging: let the ladder finish.
            return "not_exhausted"
        if escalation.lead_id is None:
            # No lead means no timeline, which means no visible record — so this refuses
            # rather than sending something it cannot account for. Reachable only when
            # every dial was refused by the ENGINE (no call row, so the post-call
            # pipeline never upserted a lead); a lead exists on every ordinary path.
            alert(
                "WORKER_TERMINAL",
                "campaign_escalation_unrecordable",
                detail="campaign contact exhausted with no lead to record the follow-up on",
                tenant_id=str(tenant_id),
                contact_id=str(contact_id),
            )
            return "no_lead"

        if await _escalation_delivered(session, lead_id=escalation.lead_id, contact_id=contact_id):
            return "duplicate"

        if not settings.whatsapp_enabled:
            # The channel is off until a human finishes the switch-on checklist (WABA,
            # business verification, an approved template, a chosen BSP). Recorded, not
            # alerted: paging someone per exhausted contact for a feature that is
            # deliberately off trains everyone to ignore the alert.
            result = SendResult(SendStatus.REJECTED, reason="whatsapp_disabled")
        else:
            result = await _send_escalation(session, tenant_id=tenant_id, escalation=escalation)

        await _record_escalation_attempt(
            session,
            tenant_id=tenant_id,
            lead_id=escalation.lead_id,
            campaign_id=escalation.campaign_id,
            contact_id=contact_id,
            result=result,
            attempts=attempt,
        )

    if result.delivered:
        log.info(
            "campaign_escalation_sent",
            extra={"contact_id": str(contact_id), "attempts": attempt},
        )
        return "sent"

    if result.status is SendStatus.REJECTED:
        if _is_operational(result.reason):
            # Config or template: only a person can close it, and every exhausted
            # contact keeps going un-followed-up until they do.
            alert(
                "WORKER_TERMINAL",
                "campaign_escalation_rejected",
                detail=f"campaign follow-up refused: {result.reason}",
                tenant_id=str(tenant_id),
                contact_id=str(contact_id),
            )
        else:
            # A lawful refusal — DNC, calling hours, the halt, no opt-in, channel off.
            # The system working as designed, so it is recorded and counted, never paged.
            log.info(
                "campaign_escalation_refused",
                extra={"contact_id": str(contact_id), "reason": result.reason},
            )
        return f"rejected {result.reason}"

    if attempt < WORKER_MAX_TRIES:
        raise Retry(defer=_retry_after(attempt))

    alert(
        "WORKER_DELIVERY",
        "campaign_escalation_exhausted",
        detail=f"campaign follow-up undelivered after {attempt} attempt(s)",
        tenant_id=str(tenant_id),
        contact_id=str(contact_id),
    )
    return f"exhausted after {attempt}"


# The refusals a HUMAN has to clear. Everything else — `blocked_dnc`, `blocked_dnc`'s
# siblings from the dispatch gate, `recipient_not_opted_in`, `recipient_unreachable`,
# `whatsapp_disabled` — is a lawful outcome, or a fact about one person, that would page
# an operator once per contact for no possible action.
#
# `cloud_api_` covers the adapter's own operator errands — a missing or rejected token, a
# sending number that was never registered. Every REJECTED reason `whatsapp_cloud.py`
# produces under that prefix is one an operator must clear; its transient ones
# (`cloud_api_rate_limited`, `cloud_api_unavailable`, `cloud_api_response_malformed`) are
# TRANSPORT_FAILED and never reach this function, which is only consulted for a verdict.
_OPERATIONAL_REFUSALS = (
    "no_provider_configured",
    "provider_not_implemented",
    "template_",
    "dev_sink_",
    "cloud_api_",
)


def _is_operational(reason: str) -> bool:
    return reason.startswith(_OPERATIONAL_REFUSALS)


async def _send_escalation(
    session: AsyncSession, *, tenant_id: UUID, escalation: _Escalation
) -> SendResult:
    """The gate, then the transport. In that order, and never the other way round.

    `check_dispatch` is the ONE function every outbound path calls (hard rule 5). A
    WhatsApp follow-up is outbound commercial contact with a subscriber, so it gets the
    identical treatment a dial does — the live DNC read above all, which is what makes
    an opt-out captured mid-campaign stop the message as well as the call. There is no
    messaging-shaped copy of those rules here and no flag that skips them.
    """
    decision = await check_dispatch(
        session,
        tenant_id=tenant_id,
        agent_id=escalation.agent_id,
        phone_e164=escalation.phone_e164,
    )
    if not decision.allowed:
        # The RULE, never the client-facing prose and never the number: the reason lands
        # in a jsonb payload the client can read.
        return SendResult(SendStatus.REJECTED, reason=f"blocked_{decision.rule or 'unknown'}")

    destination = await resolve_escalation_destination(
        session, tenant_id=tenant_id, phone_e164=escalation.phone_e164
    )
    if destination.opt_in_at is None:
        # Permanent by nature: the same person will be just as un-opted-in in two
        # minutes, and we do not hand a number to a processor to find out whether we
        # were allowed to.
        return SendResult(SendStatus.REJECTED, reason="recipient_not_opted_in")

    return await get_whatsapp_transport().send(
        WhatsAppMessage(
            to_e164=destination.to_e164,
            template=TEMPLATE_MISSED_CALL,
            locale=get_settings().whatsapp_template_locale,
            variables=_compose_escalation_variables(escalation.business_name),
        )
    )


async def _load_escalation(session: AsyncSession, *, contact_id: UUID) -> _Escalation | None:
    """One round trip for the contact, its campaign's agent, the client's trading name
    and the lead to record against.

    The lead is found through the contact's last CALL (`calls.lead_id`, which the
    pipeline sets when it upserts the lead) and falls back to the lead's natural key —
    one lead per (tenant, phone, agent) — so a contact whose last call row was retention-
    swept still lands on the right timeline.
    """
    row = (
        await session.execute(
            text(
                "SELECT cc.campaign_id, c.agent_id, cc.phone_e164, cc.status, o.name, "
                "  COALESCE(cl.lead_id, (SELECT l.id FROM leads l "
                "    WHERE l.tenant_id = cc.tenant_id AND l.phone_e164 = cc.phone_e164 "
                "    AND l.agent_id = c.agent_id)) "
                "FROM campaign_contacts cc "
                "JOIN campaigns c ON c.id = cc.campaign_id "
                "JOIN organizations o ON o.id = cc.tenant_id "
                "LEFT JOIN calls cl ON cl.id = cc.last_call_id "
                "WHERE cc.id = :id"
            ),
            {"id": contact_id},
        )
    ).first()
    if row is None:
        return None
    return _Escalation(
        campaign_id=UUID(str(row[0])),
        agent_id=UUID(str(row[1])),
        phone_e164=str(row[2]),
        status=str(row[3]),
        business_name=str(row[4]),
        lead_id=UUID(str(row[5])) if row[5] is not None else None,
    )


async def _escalation_delivered(session: AsyncSession, *, lead_id: UUID, contact_id: UUID) -> bool:
    """Has the follow-up for this CONTACT actually reached them?

    Scoped to `kind = 'campaign_escalation'` in both directions so the hot-lead alert
    and the follow-up cannot answer for each other on the same lead. A recorded ATTEMPT
    is not an answer — only `delivered: true` is, or the second attempt would find the
    `delivered: false` row it wrote itself and report the person messaged.
    """
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM lead_events WHERE lead_id = :lid AND type = 'notification' "
                "AND payload->>'channel' = :channel AND payload->>'kind' = :kind "
                "AND payload->>'contact_id' = :contact AND payload->>'delivered' = 'true' LIMIT 1"
            ),
            {
                "lid": lead_id,
                "channel": CHANNEL,
                "kind": ESCALATION_KIND,
                "contact": str(contact_id),
            },
        )
    ).first()
    return row is not None


async def _record_escalation_attempt(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    lead_id: UUID,
    campaign_id: UUID,
    contact_id: UUID,
    result: SendResult,
    attempts: int,
) -> None:
    """One timeline row per contact, updated in place as the ladder walks — the same
    update-then-insert as `_record_attempt`, keyed on `contact_id` instead of `call_id`
    so the two rows on one lead never overwrite each other.

    `lead_events` is a timeline, not one of hard rule 4's append-only ledgers, so
    flipping `delivered` to true when a retry finally lands is the honest record; a
    follow-up that never landed stays visible as one.
    """
    body = _json(
        {
            "channel": CHANNEL,
            "kind": ESCALATION_KIND,
            "campaign_id": str(campaign_id),
            "contact_id": str(contact_id),
            "delivered": result.delivered,
            "status": str(result.status),
            "reason": result.reason,
            "template": TEMPLATE_MISSED_CALL,
            "attempts": attempts,
        }
    )
    updated = await session.execute(
        text(
            "UPDATE lead_events SET payload = CAST(:payload AS jsonb), updated_at = now() "
            "WHERE lead_id = :lid AND type = 'notification' "
            "AND payload->>'channel' = :channel AND payload->>'kind' = :kind "
            "AND payload->>'contact_id' = :contact"
        ),
        {
            "payload": body,
            "lid": lead_id,
            "channel": CHANNEL,
            "kind": ESCALATION_KIND,
            "contact": str(contact_id),
        },
    )
    if rowcount_of(updated) == 0:
        await session.execute(
            text(
                "INSERT INTO lead_events (id, tenant_id, lead_id, type, payload, actor, "
                "created_at, updated_at) VALUES (:id, :tid, :lid, 'notification', "
                "CAST(:payload AS jsonb), 'system', now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_id, "lid": lead_id, "payload": body},
        )


async def enqueue_campaign_escalation(
    session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID, contact_id: UUID
) -> bool:
    """Queue the follow-up through the OUTBOX, in the caller's transaction.

    Called from `campaign_dispatch._record_failure` the moment a contact's ladder is
    spent, so the escalation and the `failed` status share one fate: a rolled-back
    exhaustion cannot leave a message queued to somebody we are still trying to phone.

    ONCE PER CONTACT, and the outbox row is what says so. The status transition is not
    enough on its own: `_reap_stuck_dialing` returns a stranded contact to `pending`
    with its attempt count intact and no ceiling, so the same person can reach
    "exhausted" more than once — and messaging them again about one enquiry is exactly
    the behaviour that gets a WABA reported. `enqueue_outbox_once` makes that a UNIQUE
    index on `campaign-escalation:{contact_id}`, so "once per contact" holds even without
    a lock around the read (P6.7) — which matters here, because unlike the hot-lead path
    this one has no `lock_call_writes` above it.

    NOT gated on `whatsapp_enabled`, unlike the hot-lead alert: that alert has email as
    its channel of record, so a disabled WhatsApp leg loses nothing. This escalation has
    no second channel — we do not email a consumer — so the job runs and RECORDS the
    refusal, which is how "we never followed up" stays visible instead of never
    happening at all.
    """
    return (
        await enqueue_outbox_once(
            session,
            job=ESCALATION_JOB_NAME,
            payload={
                "tenant_id": str(tenant_id),
                "campaign_id": str(campaign_id),
                "contact_id": str(contact_id),
            },
            dedupe_key=f"campaign-escalation:{contact_id}",
        )
        is not None
    )


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


__all__ = [
    "CHANNEL",
    "CLOUD_API_PROVIDER",
    "CONSOLE_PROVIDER",
    "DEV_SINK_OUTSIDE_LOCAL_REASON",
    "ESCALATION_JOB_NAME",
    "ESCALATION_KIND",
    "JOB_NAME",
    "NO_PHONE_ID_REASON",
    "NO_PROVIDER_REASON",
    "NO_TOKEN_REASON",
    "PROVIDER_NOT_IMPLEMENTED_REASON",
    "TEMPLATE_MISSED_CALL",
    "ConsoleWhatsAppTransport",
    "DeliveryStatus",
    "Destination",
    "SendResult",
    "SendStatus",
    "UnconfiguredWhatsAppTransport",
    "WhatsAppMessage",
    "WhatsAppTransport",
    "enqueue_campaign_escalation",
    "enqueue_hot_lead_whatsapp",
    "escalate_campaign_contact",
    "get_whatsapp_transport",
    "notify_hot_lead_whatsapp",
    "resolve_destination",
    "resolve_escalation_destination",
    "whatsapp_delivery_status",
]
