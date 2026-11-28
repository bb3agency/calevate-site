"""The failure-state and compliance events, and the test event (D-1049, MASTER-PLAN W2.4).

`integrations/service.py` owns the fan-out; this module owns what five of the events SAY
and calls it from the producers' own transactions, so each event commits with the fact it
reports (BACKEND-PATTERNS §4):

* `call.not_connected` — we could not reach the person: the call ended unanswered, busy,
  at voicemail or failed (`reason` is the call's status), or the dial gate refused to ring
  them (`reason: "refused"`, `rule` the gate's rule) or held them until a stated time
  (`reason: "deferred"`, `opens_at`). Once per call.
* `call.inbound_missed` — a call to one of the account's numbers that never connected, with
  the Follow-up that will ring the caller back when one is switched on. Once per call.
* `campaign.status_changed` — a campaign started, paused (with why), resumed, stopped,
  finished, or finished one run of a repeating schedule.
* `lead.consent_changed` — a consent record was written for a number: a grant, a refusal,
  a withdrawal.
* `dnc.added` — a number went onto this account's do-not-call list.

Every one of them carries a `phone` the fan-out masks per endpoint (WEBHOOKS §1.2), except
`campaign.status_changed`, which names no person. None is sent for a test or trial call: an
owner ringing their own number is not a customer the CRM should hear about.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.integrations import service

log = get_logger(__name__)

CALL_NOT_CONNECTED_EVENT: Final = "call.not_connected"
CALL_INBOUND_MISSED_EVENT: Final = "call.inbound_missed"
CAMPAIGN_STATUS_CHANGED_EVENT: Final = "campaign.status_changed"
LEAD_CONSENT_CHANGED_EVENT: Final = "lead.consent_changed"
DNC_ADDED_EVENT: Final = "dnc.added"

#: A call's final statuses that mean nobody was reached (`crm/lens.CALL_STATUS_GROUPS`).
NOT_REACHED_STATUSES: Final = frozenset({"no_answer", "busy", "voicemail", "failed"})
#: `call.not_connected.reason` when the dial gate is why: settled for good, or held.
REFUSED: Final = "refused"
DEFERRED: Final = "deferred"

#: The `consent_ledger.purpose` values `lead.consent_changed` reports.
CONTACT_CONSENT_PURPOSES: Final = frozenset({"marketing", "callback", "messaging"})

CampaignChange = Literal["started", "paused", "resumed", "stopped", "completed", "run_finished"]

_CALL_SQL: Final = (
    "SELECT c.direction, c.status, c.from_e164, c.to_e164, c.lead_id, c.campaign_id, "
    "c.inbound_line_id, (c.trial_call OR c.paid_test_call), c.ended_at, c.created_at "
    "FROM calls c WHERE c.id = :cid"
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def emit_call_ended_unreached(
    session: AsyncSession, *, tenant_id: UUID, call_id: UUID, lead_id: UUID | None
) -> int:
    """`call.not_connected` (outbound) or `call.inbound_missed` (inbound) for a call whose
    final status reached nobody; nothing for any other call. Called by the post-call
    pipeline in its step-8 transaction; a re-run sends nothing new
    (`service.ONCE_PER_CALL_EVENTS`)."""
    row = (await session.execute(text(_CALL_SQL), {"cid": call_id})).first()
    if row is None or row[1] not in NOT_REACHED_STATUSES or row[7]:
        return 0
    direction, status, from_e164, to_e164, stored_lead, campaign_id, line_id, _test, ended, made = (
        row
    )
    lead = lead_id or stored_lead
    occurred_at = _iso(ended or made)
    if direction == "inbound":
        return await service.enqueue_event(
            session,
            tenant_id=tenant_id,
            event=CALL_INBOUND_MISSED_EVENT,
            data={
                "call_id": str(call_id),
                "lead_id": str(lead) if lead else None,
                "phone": from_e164,
                "inbound_line_id": str(line_id) if line_id else None,
                "status": status,
                "call_back": await _call_back_follow_up(session, line_id),
                "occurred_at": occurred_at,
            },
        )
    return await service.enqueue_event(
        session,
        tenant_id=tenant_id,
        event=CALL_NOT_CONNECTED_EVENT,
        data={
            "call_id": str(call_id),
            "lead_id": str(lead) if lead else None,
            "phone": to_e164,
            "campaign_id": str(campaign_id) if campaign_id else None,
            "reason": status,
            "rule": None,
            "opens_at": None,
            "occurred_at": occurred_at,
        },
    )


async def _call_back_follow_up(
    session: AsyncSession, line_id: UUID | None
) -> dict[str, Any] | None:
    """The Follow-up that rings this line's missed callers back, or None when none is on.
    Read from the live Follow-ups (`follow_ups/starters.line_call_back`), never remembered:
    the call-back itself is booked by that Follow-up after this event, at its own time."""
    if line_id is None:
        return None
    from apps.api.core.errors import ProblemError
    from apps.api.follow_ups import starters

    try:
        state = await starters.line_call_back(session, line_id)
    except ProblemError:
        # The line was archived since the call: nobody is set to ring back from it.
        return None
    if state.state == "on" and state.follow_up_id is not None:
        return {"follow_up_id": str(state.follow_up_id)}
    if state.state == "covered" and state.covered_by is not None:
        return {"follow_up_id": str(state.covered_by)}
    return None


async def emit_dial_refused(
    session: AsyncSession,
    *,
    contact_id: UUID,
    rule: str,
    deferred: bool,
    opens_at: datetime | None,
) -> int:
    """`call.not_connected` for a campaign contact the gate would not ring. Only for the
    refusals a CRM can act on: one that settled the contact (the person is on do-not-call,
    has no consent, was erased) and one that holds it to a stated time (the per-person
    pacing, the recent-call skip). A refusal about us (the hour, a cap, the halt) puts the
    contact back on the ladder within minutes and is not news to anyone downstream."""
    row = (
        await session.execute(
            text(
                "SELECT c.tenant_id, c.campaign_id, c.phone_e164 "
                "FROM campaign_contacts c WHERE c.id = :id"
            ),
            {"id": contact_id},
        )
    ).first()
    if row is None:
        return 0
    tenant_id, campaign_id, phone = row
    return await service.enqueue_event(
        session,
        tenant_id=UUID(str(tenant_id)),
        event=CALL_NOT_CONNECTED_EVENT,
        data={
            "call_id": None,
            "lead_id": await _lead_for(session, str(phone)),
            "phone": phone,
            "campaign_id": str(campaign_id),
            "reason": DEFERRED if deferred else REFUSED,
            "rule": rule,
            "opens_at": _iso(opens_at),
            "occurred_at": datetime.now(UTC).isoformat(),
        },
    )


_CAMPAIGNS_SQL: Final = (
    "SELECT id, tenant_id, name, status, auto_pause_reason, paused_by_maintenance_id, "
    "paused_by_heal_id FROM campaigns WHERE id = ANY(:ids) ORDER BY id"
)


def _campaign_reason(
    change: CampaignChange,
    *,
    auto_pause_reason: str | None,
    maintenance: bool,
    protection: bool,
) -> str:
    """Why, in our words, read from the row the change just wrote."""
    if change == "paused":
        if auto_pause_reason:
            return str(auto_pause_reason)
        if maintenance:
            return "maintenance"
        if protection:
            return "protection"
        return "owner"
    if change in ("completed", "run_finished"):
        return "finished"
    return "owner"


async def emit_campaign_status_changed(
    session: AsyncSession,
    *,
    campaign_ids: Sequence[UUID],
    change: CampaignChange,
    reason: str | None = None,
) -> int:
    """`campaign.status_changed` for campaigns whose status this transaction just moved.

    Read back after the write, so `status` and the pause's why are what the row now says.
    `reason` overrides the derived one where the caller knows better (a resume after a
    top-up is `credit_added`, not `owner`). Grouped by tenant because the maintenance and
    protection writers move several campaigns at once."""
    if not campaign_ids:
        return 0
    rows = (
        await session.execute(text(_CAMPAIGNS_SQL), {"ids": [str(c) for c in campaign_ids]})
    ).all()
    changed_at = datetime.now(UTC).isoformat()
    by_tenant: dict[UUID, list[dict[str, Any]]] = {}
    for campaign_id, tenant_id, name, status, auto_reason, maintenance, protection in rows:
        by_tenant.setdefault(UUID(str(tenant_id)), []).append(
            {
                "campaign_id": str(campaign_id),
                "name": name,
                "status": status,
                "change": change,
                "reason": reason
                or _campaign_reason(
                    change,
                    auto_pause_reason=auto_reason,
                    maintenance=maintenance is not None,
                    protection=protection is not None,
                ),
                "changed_at": changed_at,
            }
        )
    written = 0
    for tenant_id, data in by_tenant.items():
        written += await service.enqueue_events(
            session, tenant_id=tenant_id, event=CAMPAIGN_STATUS_CHANGED_EVENT, rows=data
        )
    return written


def change_for(to_status: str, from_statuses: Sequence[str]) -> CampaignChange | None:
    """The `change` a `set_campaign_status` move is, or None for a move that is none of
    the five (a draft scheduled, a schedule withdrawn)."""
    if to_status == "paused":
        return "paused"
    if to_status == "cancelled":
        return "stopped"
    if to_status == "completed":
        return "completed"
    if to_status == "running":
        return "resumed" if "paused" in from_statuses else "started"
    return None


async def _lead_for(session: AsyncSession, phone: str) -> str | None:
    """This account's most recently touched lead for a number, if it has one."""
    value = (
        await session.execute(
            text(
                "SELECT id FROM leads WHERE phone_e164 = :phone "
                "ORDER BY updated_at DESC, id DESC LIMIT 1"
            ),
            {"phone": phone},
        )
    ).scalar()
    return str(value) if value is not None else None


async def emit_consent_changed(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    phone: str,
    purpose: str,
    status: str,
    source: str,
    call_id: UUID | None = None,
    expires_at: datetime | None = None,
) -> int:
    """`lead.consent_changed` for one `consent_ledger` row this transaction wrote.

    Not for `recording`: that consent is about one call being recorded, written on most
    calls, and says nothing about whether the person may be contacted again."""
    if purpose not in CONTACT_CONSENT_PURPOSES:
        return 0
    return await service.enqueue_event(
        session,
        tenant_id=tenant_id,
        event=LEAD_CONSENT_CHANGED_EVENT,
        data={
            "lead_id": await _lead_for(session, phone),
            "phone": phone,
            "purpose": purpose,
            "status": status,
            "source": source,
            "call_id": str(call_id) if call_id else None,
            "expires_at": _iso(expires_at),
            "recorded_at": datetime.now(UTC).isoformat(),
        },
    )


async def emit_dnc_added(
    session: AsyncSession, *, tenant_id: UUID, phones: Sequence[str], source: str
) -> int:
    """`dnc.added` for numbers this transaction put on the account's own list. The
    platform-wide list is ours, not the client's, and is not reported to their CRM."""
    if not phones:
        return 0
    added_at = datetime.now(UTC).isoformat()
    rows = [
        {
            "phone": phone,
            "lead_id": await _lead_for(session, phone),
            "source": source,
            "added_at": added_at,
        }
        for phone in phones
    ]
    return await service.enqueue_events(
        session, tenant_id=tenant_id, event=DNC_ADDED_EVENT, rows=rows
    )


#: The ordinary delivery job (`service.OUTBOUND_WEBHOOK_JOB`); `test` in the payload makes
#: it a test. A literal, so `check_job_wiring` resolves the enqueue.
TEST_DELIVERY_JOB: Final = "deliver_outbound_webhook"


# --- the test event (MASTER-PLAN W2.6) ---------------------------------------------
#
# A signed delivery with made-up data, so a receiver can be built and checked before a
# real lead arrives. The ids are fresh uuids that name nothing of ours, and the phone is the
# masked form every endpoint gets by default.


def sample_data(event: str) -> dict[str, Any]:
    """Made-up `data` in the published shape of `event` (WEBHOOKS §1.2)."""
    now = datetime.now(UTC).isoformat()
    lead = str(uuid7())
    call = str(uuid7())
    campaign = str(uuid7())
    samples: dict[str, dict[str, Any]] = {
        "lead.created": {
            "lead_id": lead,
            "phone": "[redacted]",
            "name": "Test Lead",
            "source": "webhook",
            "status": "new",
        },
        "call.completed": {
            "call_id": call,
            "lead_id": lead,
            "direction": "outbound",
            "duration_s": 42,
            "outcome": "call_back_booked",
            "sentiment": "positive",
            "summary": "A test call. Nobody was rung.",
            "business_outcome": None,
            "business_outcome_label": None,
        },
        "call.recording_ready": {"call_id": call, "lead_id": lead, "duration_s": 42},
        "campaign.completed": {
            "campaign_id": campaign,
            "name": "Test campaign",
            "contacts_total": 10,
            "contacts_reached": 4,
            "completed_at": now,
        },
        CALL_NOT_CONNECTED_EVENT: {
            "call_id": call,
            "lead_id": lead,
            "phone": "[redacted]",
            "campaign_id": campaign,
            "reason": "no_answer",
            "rule": None,
            "opens_at": None,
            "occurred_at": now,
        },
        CALL_INBOUND_MISSED_EVENT: {
            "call_id": call,
            "lead_id": lead,
            "phone": "[redacted]",
            "inbound_line_id": str(uuid7()),
            "status": "no_answer",
            "call_back": None,
            "occurred_at": now,
        },
        CAMPAIGN_STATUS_CHANGED_EVENT: {
            "campaign_id": campaign,
            "name": "Test campaign",
            "status": "paused",
            "change": "paused",
            "reason": "owner",
            "changed_at": now,
        },
        LEAD_CONSENT_CHANGED_EVENT: {
            "lead_id": lead,
            "phone": "[redacted]",
            "purpose": "marketing",
            "status": "granted",
            "source": "web_form_optin",
            "call_id": None,
            "expires_at": None,
            "recorded_at": now,
        },
        DNC_ADDED_EVENT: {
            "phone": "[redacted]",
            "lead_id": lead,
            "source": "manual",
            "added_at": now,
        },
    }
    samples["lead.updated"] = {**samples["lead.created"], "status": "contacted"}
    samples["call.updated"] = {**samples["call.completed"], "outcome": "interested"}
    return samples[event]


async def queue_test_delivery(
    session: AsyncSession, *, tenant_id: UUID, endpoint_id: UUID, event: str | None
) -> tuple[UUID, str]:
    """Queue one signed test delivery to a webhook endpoint. Returns `(delivery_id, event)`.

    A signed webhook only: a test row appended to a client's real spreadsheet or written to
    their LeadSquared as a lead is not a test any more. Allowed while the endpoint is paused
    by the breaker, because that is exactly when the client wants to know it works again.
    The event is the one asked for, else the endpoint's first subscription."""
    from apps.api.core.errors import ProblemError
    from apps.api.reliability.service import enqueue_outbox

    choices = await service.read_endpoint_choices(session, endpoint_id)
    if choices.kind != service.WEBHOOK_KIND:
        raise ProblemError.business_rule(
            "endpoint_test_webhook_only",
            "A test is sent to a webhook address. A spreadsheet or LeadSquared would keep "
            "the made-up lead as a real one.",
            remediation="Use a webhook destination to try a delivery.",
        )
    chosen = event or (choices.events[0] if choices.events else "lead.created")
    if chosen not in service.EVENT_TYPES:
        raise ProblemError(
            kind="validation",
            code="unknown_event",
            title="Unknown event",
            detail=f"{chosen} is not an event we send.",
            remediation="Choose from the events the Integrations screen lists.",
        )
    delivery_id = uuid7()
    await enqueue_outbox(
        session,
        job=TEST_DELIVERY_JOB,
        payload={
            "tenant_id": str(tenant_id),
            "endpoint_id": str(endpoint_id),
            "event": chosen,
            "data": sample_data(chosen),
            "delivery_id": str(delivery_id),
            "occurred_at": datetime.now(UTC).isoformat(),
            "test": True,
        },
    )
    log.info("outbound_test_queued", extra={"tenant_id": str(tenant_id), "event": chosen})
    return delivery_id, chosen


__all__ = [
    "CALL_INBOUND_MISSED_EVENT",
    "CALL_NOT_CONNECTED_EVENT",
    "CAMPAIGN_STATUS_CHANGED_EVENT",
    "DEFERRED",
    "DNC_ADDED_EVENT",
    "LEAD_CONSENT_CHANGED_EVENT",
    "NOT_REACHED_STATUSES",
    "REFUSED",
    "TEST_DELIVERY_JOB",
    "CampaignChange",
    "change_for",
    "emit_call_ended_unreached",
    "emit_campaign_status_changed",
    "emit_consent_changed",
    "emit_dial_refused",
    "emit_dnc_added",
    "queue_test_delivery",
    "sample_data",
]
