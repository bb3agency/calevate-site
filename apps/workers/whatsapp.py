"""WhatsApp transport for hot-lead alerts (ROADMAP M2: "WhatsApp follow-up + hot-lead
WhatsApp alerts"; FLOWS §6 "status hot OR urgency=emergency ⇒ WhatsApp+email to owner
within 2 min").

**This module is a transport and a job. It is deliberately NOT a vendor integration.**

The docs have not picked a WhatsApp Business Solution Provider. The only names in the
blueprint — Interakt / AiSensy / Meta Cloud API (BRD §4.2, evidence/outpero-teardown
§9a "[ADOPT integration list]") — are (a) a competitor's *in-call action* integrations,
which run engine-side, not here, and (b) an adoption *intent* recorded in an evidence
file, not a Decision-Log entry. ROADMAP §6 is the binding decision log and it contains
no D-entry choosing a BSP. So there is no adapter here: an adapter written against an
imagined API is worse than none, because it looks finished. What ships is the seam —
`WhatsAppTransport`, a console dev sink, the delivery record, and the retry ladder —
so the day a BSP is decided the vendor work is one class implementing one method.

Shape mirrors `workers/transport.py` on purpose: a Protocol, a dev sink that needs no
credentials and no network, and the real provider chosen by config.

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

**The opt-in cannot be recorded today.** There is no column for it — see
`resolve_destination` for the exact migration this needs. Until it exists the gate
below refuses every send, which is the honest behaviour: an un-recorded opt-in is a
policy violation, not a formality. `whatsapp_enabled` defaults to False so that refusal
is silent rather than an alert per lead.

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
    WABA, and `consent_ledger` cannot answer either: its rows are keyed to a call this
    person never took. So `resolve_escalation_destination` asks the ledger for a
    `messaging` purpose that its CHECK constraint does not yet permit, finds nothing,
    and the send is refused. That refusal is the honest state of this feature until the
    migration named there lands — and it is RECORDED rather than alerted, because
    "no consumer has opted in yet" is the default of the world, not an incident.

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

from apps.api.compliance.service import check_dispatch
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session
from apps.api.reliability.service import enqueue_outbox

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

    def send(self, message: WhatsAppMessage) -> SendResult: ...


# --- transports ----------------------------------------------------------------


class ConsoleWhatsAppTransport:
    """Local dev + the test suite. No credentials, no network, no vendor account.

    Reports DELIVERED honestly, for the same reason `ConsoleTransport` does: the
    message really did arrive — in the developer's terminal. Never logs `to_e164`.
    """

    name = "console"

    def send(self, message: WhatsAppMessage) -> SendResult:
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

    def send(self, message: WhatsAppMessage) -> SendResult:
        log.warning("whatsapp_no_transport", extra={"reason": self._reason})
        return SendResult(SendStatus.REJECTED, reason=self._reason)


def get_whatsapp_transport() -> WhatsAppTransport:
    """Selected by config, exactly like `transport.get_transport()`.

    `whatsapp_provider` is the seam where a decided BSP lands. Any name other than the
    dev sink resolves to `provider_not_implemented`, on purpose: setting
    `WHATSAPP_PROVIDER=gupshup` today must fail loudly rather than look configured.
    """
    settings = get_settings()
    provider = (settings.whatsapp_provider or "").strip().lower()

    if provider == "console":
        if settings.app_env != "local":
            # An explicit dev sink outside local is operator error, and it is the kind
            # that reports success forever. Refuse it rather than swallow leads.
            return UnconfiguredWhatsAppTransport("dev_sink_refused_outside_local")
        return ConsoleWhatsAppTransport()
    if provider:
        return UnconfiguredWhatsAppTransport(f"provider_not_implemented:{provider}")
    if settings.app_env == "local":
        return ConsoleWhatsAppTransport()
    return UnconfiguredWhatsAppTransport("no_provider_configured")


# --- who receives it -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Destination:
    to_e164: str
    # When the recipient opted in to WhatsApp from the Calevate WABA. `None` means "we
    # cannot show an opt-in", which is treated as "not opted in" — never as consent.
    opt_in_at: datetime | None


async def resolve_destination(session: AsyncSession, tenant_id: UUID) -> Destination | None:
    """The client's owner, from data that exists today.

    Number: the owner-role member's `users.phone` (E.164, Clerk-mirrored). Deactivated
    users are excluded — a removed owner must not keep receiving the business's leads.

    Opt-in: **not storable yet, and that is the blocker for this feature.** There is no
    column for it, and `consent_ledger` is the wrong home (its purposes are
    recording/callback/marketing and its rows are keyed to a CALL — it records what a
    caller agreed to, not what our client agreed to receive). The migration this needs,
    reported rather than written because this milestone ships none:

        ALTER TABLE organizations
            ADD COLUMN notify_whatsapp_e164 text,
            ADD COLUMN whatsapp_opt_in_at   timestamptz,
            ADD COLUMN whatsapp_opt_in_source text;

    ...plus the onboarding-wizard step that captures it. When those land, this function
    reads them and nothing else in this module changes.
    """
    row = (
        await session.execute(
            text(
                "SELECT u.phone FROM memberships m JOIN users u ON u.id = m.user_id "
                "WHERE m.tenant_id = :tid AND m.role = 'owner' "
                "AND u.deactivated_at IS NULL AND u.phone IS NOT NULL "
                "ORDER BY m.created_at LIMIT 1"
            ),
            {"tid": tenant_id},
        )
    ).first()
    if row is None or not row[0]:
        return None
    # opt_in_at stays None until the columns above exist: an opt-in we cannot evidence
    # is not an opt-in.
    return Destination(to_e164=str(row[0]), opt_in_at=None)


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
            result = get_whatsapp_transport().send(
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

    Written to be the entire wiring change: one `await` inside the session block that
    `notifications.notify_hot_lead` already holds open. Returns whether a message was
    enqueued, so the caller can log it without needing to know why not.

    Queued once per (lead, call) — the outbox is never deleted from, so it is also the
    right place to ask "did a previous run already promise this?", which is what keeps
    a pipeline replay from pinging a client twice (same doctrine as
    `pipeline._already_enqueued`).
    """
    if not get_settings().whatsapp_enabled:
        return False
    matcher = {"lead_id": str(lead_id), "call_id": str(call_id)}
    existing = (
        await session.execute(
            text(
                "SELECT 1 FROM outbox_messages WHERE job = :job "
                "AND payload @> CAST(:matcher AS jsonb) LIMIT 1"
            ),
            {"job": JOB_NAME, "matcher": _json(matcher)},
        )
    ).first()
    if existing is not None:
        return False
    await enqueue_outbox(
        session,
        queue="notifications",
        job=JOB_NAME,
        payload={
            "tenant_id": str(tenant_id),
            "lead_id": str(lead_id),
            "call_id": str(call_id),
            "triggers": triggers,
        },
    )
    return True


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

# The `consent_ledger.purpose` that would evidence a consumer opting in to WhatsApp from
# our WABA. Not yet a permitted member of that CHECK — see `resolve_escalation_destination`.
MESSAGING_CONSENT_PURPOSE = "messaging"


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
    opt-in from every consent this system currently records:

      * `campaigns.consent_source` says the client may CALL this list (SEC-COMP §3). A
        person who agreed to be phoned about their enquiry has not thereby agreed to
        receive WhatsApp from a WABA they have never heard of; Meta's business-initiated
        rules and DPDP's purpose limitation both read that as a separate permission.
      * `consent_ledger` records what a CALLER agreed to DURING a call (purposes
        recording/callback/marketing, keyed to `call_id`). This person never took the
        call — that is the entire reason we are here.

    So the read below asks the ledger for a purpose its CHECK constraint does not yet
    permit, which means it can only ever return nothing today. That is deliberate: the
    gate is a live read against the table this consent belongs in, not a hardcoded
    `False`, so the day the migration lands the feature starts working without a code
    change. The migration, reported rather than written because this milestone ships
    none:

        -- consent_ledger.purpose CHECK gains 'messaging'; call_id is already nullable,
        -- and the ledger is append-only (hard rule 4), so a withdrawal is a new row
        -- with status='withdrawn' rather than an UPDATE.
        ALTER TABLE consent_ledger DROP CONSTRAINT ck_consent_ledger_purpose_enum;
        ALTER TABLE consent_ledger ADD CONSTRAINT ck_consent_ledger_purpose_enum
            CHECK (purpose IN ('recording','callback','marketing','messaging'));
        CREATE INDEX ix_consent_ledger_messaging
            ON consent_ledger (tenant_id, phone_e164, captured_at DESC)
            WHERE purpose = 'messaging';

    ...plus the surface that captures it (the opt-in checkbox on the client's own lead
    form, or the CSV import declaring one per row) and `CONSENT_PURPOSES` in
    `apps/api/compliance/models.py`. Nothing else in this module changes.

    Latest row wins, so a withdrawal supersedes the grant that preceded it.
    """
    row = (
        await session.execute(
            text(
                "SELECT status, captured_at FROM consent_ledger WHERE tenant_id = :tid "
                "AND phone_e164 = :phone AND purpose = :purpose "
                "ORDER BY captured_at DESC, created_at DESC LIMIT 1"
            ),
            {"tid": tenant_id, "phone": phone_e164, "purpose": MESSAGING_CONSENT_PURPOSE},
        )
    ).first()
    granted_at = row[1] if row is not None and str(row[0]) == "granted" else None
    return Destination(to_e164=phone_e164, opt_in_at=granted_at)


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
# siblings from the dispatch gate, `recipient_not_opted_in`, `whatsapp_disabled` — is a
# lawful outcome that would page an operator once per contact for no possible action.
_OPERATIONAL_REFUSALS = (
    "no_provider_configured",
    "provider_not_implemented",
    "template_",
    "dev_sink_",
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

    return get_whatsapp_transport().send(
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
    the behaviour that gets a WABA reported. The outbox is never deleted from, which is
    what makes it a durable answer to "did a previous run already promise this?" (same
    doctrine as `enqueue_hot_lead_whatsapp` and `pipeline._already_enqueued`).

    NOT gated on `whatsapp_enabled`, unlike the hot-lead alert: that alert has email as
    its channel of record, so a disabled WhatsApp leg loses nothing. This escalation has
    no second channel — we do not email a consumer — so the job runs and RECORDS the
    refusal, which is how "we never followed up" stays visible instead of never
    happening at all.
    """
    matcher = {"contact_id": str(contact_id)}
    existing = (
        await session.execute(
            text(
                "SELECT 1 FROM outbox_messages WHERE job = :job "
                "AND payload @> CAST(:matcher AS jsonb) LIMIT 1"
            ),
            {"job": ESCALATION_JOB_NAME, "matcher": _json(matcher)},
        )
    ).first()
    if existing is not None:
        return False
    await enqueue_outbox(
        session,
        queue="notifications",
        job=ESCALATION_JOB_NAME,
        payload={
            "tenant_id": str(tenant_id),
            "campaign_id": str(campaign_id),
            "contact_id": str(contact_id),
        },
    )
    return True


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


__all__ = [
    "CHANNEL",
    "ESCALATION_JOB_NAME",
    "ESCALATION_KIND",
    "JOB_NAME",
    "TEMPLATE_MISSED_CALL",
    "ConsoleWhatsAppTransport",
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
]
