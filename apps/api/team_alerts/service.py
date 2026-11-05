"""Who hears about a call: one list, one rule of when, one queue.

The list is the account owner (email to the account's email, WhatsApp once they opt in; the
`notify_hot_lead` job) and the team addresses below. Everyone on it hears about the same calls,
and each person once per channel per call, whatever told them first. Three ways in:

* **After the call** (`queue_after_call`, post-call pipeline): when the agent's rule matched
  (an outcome or an answer the owner ticked), or when the agent already told the team during
  it. The rule is exactly what is ticked: an outcome that moves a lead to Hot used to alert
  whatever the owner chose, which a business whose best outcome is not a sale ("App
  installed") could not switch off (founder, 5 Nov 2026). Until the owner saves a rule, it is
  every positive outcome the agent has now (`default_rule`).
* **During the call** (`queue_in_call`, the agent's `tell_the_team` action): the agent says what
  the problem is and the team addresses are told at once; the owner hears after the call, once
  there is a lead to open. The action exists on an agent only while that agent's rule allows it
  AND a verified team address will receive it (`in_call_live`), so "I'll tell our team" is only
  ever said by an agent that can.
* **A Follow-up's "tell the team" step** (`queue_for_follow_up`): the same list, about the call
  the run last placed.

The rule is per agent because what it watches is: each agent has its own outcomes and its own
answers. Who hears is per account.

An address is an email (always offered) or a WhatsApp number, which is offered only when the
client has its own WhatsApp account or provider connected and is sent only through it, with
the client's own approved template (founder, 27 Oct 2026; `team_alerts/whatsapp.py`). Either
kind is verified once by a code sent to it the same way alerts will be.

Whatever the trigger, one `team_alerts` row per (call, address), inserted ON CONFLICT DO
NOTHING, and one outbox job keyed the same; the owner's alert is one outbox job per (lead, call)
(`owner_dedupe_key`). So a pipeline re-run, a repeated action or a Follow-up about a call
already told never sends twice. An owner whose own email or WhatsApp number is also a confirmed
team address hears it once, as a team address (`team_covers`).

WHY THE FULL NUMBER GOES IN THIS ALERT when the hot-lead email masks it
(`workers/notifications._compose`): that email goes to `organizations.billing_email`, an
invoicing address nobody chose for customer data. This one goes only to an address or number
the owner added for exactly this and that proved it is reachable by the code sent to it. It is
the business's own customer, sent to the business's own team (on WhatsApp, through the
business's own account), so they can ring back; a masked number would defeat the alert. The
summary is still redacted (hard rule 5), the agent's note of the problem is redacted like any
action input, and no log line carries an address or a number (hard rule 6).
"""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from calevate_shared.lead_fields import with_core
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import call_outcomes
from apps.api.authn import codes
from apps.api.compliance.audit import write_audit
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.reliability.service import enqueue_outbox, enqueue_outbox_once
from apps.api.team_alerts.models import MAX_ADDRESS_CHARS, WHATSAPP_SLOTS
from apps.api.tenancy.core_labels import core_labels
from apps.workers.redaction import redact

log = get_logger(__name__)

#: The worker jobs (`apps/workers/team_alerts.py`).
CODE_JOB: Final = "send_team_contact_code"
ALERT_JOB: Final = "deliver_team_alert"
#: The owner's alert (`apps/workers/notifications.notify_hot_lead`), which queues the
#: owner's WhatsApp beside it.
OWNER_JOB: Final = "notify_hot_lead"


def owner_dedupe_key(*, lead_id: UUID, call_id: UUID) -> str:
    """The owner is told once per (lead, call), whichever trigger reaches the call first."""
    return f"hot-lead:{lead_id}:{call_id}"


MAX_CONTACTS: Final = 10
CODE_TTL: Final = timedelta(minutes=30)
CODE_MAX_ATTEMPTS: Final = 5
RESEND_WAIT: Final = timedelta(seconds=60)
#: How many choice fields one agent's rule may watch.
MAX_FIELD_TRIGGERS: Final = 10
MAX_PROBLEM_CHARS: Final = 500

# --- the in-call action ---------------------------------------------------------------

#: The function name the model calls. Reserved against client actions
#: (`actions/service.RESERVED_ACTION_NAMES`).
TEAM_ACTION_NAME: Final = "tell_the_team"
TEAM_ACTION_DESCRIPTION: Final = (
    "Tell the business's own team about a caller who needs a person: something you cannot "
    "do or answer on this call after you have tried. The team gets the caller's name and "
    "number and what you pass as the problem, and someone contacts the caller. Say that the "
    "team will contact them only after the answer says the team was told; never promise a "
    "time."
)
TEAM_PROBLEM_PARAM: Final = "problem"
TEAM_PROBLEM_DESCRIPTION: Final = (
    "One or two plain sentences on what the caller needs help with, for a person who has "
    "heard none of this call. Never include card numbers, passwords or codes."
)

InCallOutcome = Literal["queued", "already_told", "unavailable"]


def _code_domain(contact_id: UUID) -> str:
    return f"team-alert-contact:{contact_id}"


@dataclass(frozen=True, slots=True)
class Contact:
    id: UUID
    address: str
    verified: bool
    code_sent_at: datetime | None
    channel: str = "email"
    #: WhatsApp only: the client's own connection the alert goes through (None once deleted).
    whatsapp_account_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class WhatsAppSetup:
    """How a WhatsApp team alert is sent: the client's own connection, their approved
    template, and which value fills each body variable in order (`models.WHATSAPP_SLOTS`)."""

    credential_id: UUID
    template: str
    values: tuple[str, ...]
    language: str | None = None
    number_id: str | None = None


@dataclass(frozen=True, slots=True)
class FieldTrigger:
    key: str
    values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Rule:
    on_outcomes: tuple[str, ...] = ()
    on_fields: tuple[FieldTrigger, ...] = ()
    in_call: bool = False


@dataclass(frozen=True, slots=True)
class Choice:
    key: str
    label: str
    values: tuple[str, ...] = ()
    #: Outcomes only: it makes the caller a lead (`crm/lead_definition.LEAD_BAND`), so it is
    #: ticked until the owner saves a rule of their own.
    positive: bool = False
    #: Outcomes only: it moves the lead to Hot, the business's goal
    #: (`analytics/proof.goal_labels`).
    goal: bool = False


@dataclass(frozen=True, slots=True)
class RuleView:
    rule: Rule
    #: Whether the owner has saved this agent's rule; until then `rule` is `default_rule`.
    saved: bool = False
    outcomes: list[Choice] = field(default_factory=list)
    fields: list[Choice] = field(default_factory=list)
    #: Confirmed team addresses that hear now (the owner is told besides).
    team_addresses: int = 0
    in_call_live: bool = False


# --- contacts -------------------------------------------------------------------------

_CONTACT_COLUMNS: Final = (
    "id, address, verified_at IS NOT NULL, code_sent_at, channel, whatsapp_credential_id"
)

#: A team address that receives alerts now: confirmed, and for WhatsApp still connected.
_LIVE_SQL: Final = (
    "removed_at IS NULL AND verified_at IS NOT NULL "
    "AND (channel = 'email' OR whatsapp_credential_id IS NOT NULL)"
)


def _contact(row: Any) -> Contact:
    return Contact(
        id=row[0],
        address=str(row[1]),
        verified=bool(row[2]),
        code_sent_at=row[3],
        channel=str(row[4]),
        whatsapp_account_id=row[5],
    )


async def list_contacts(session: AsyncSession) -> list[Contact]:
    rows = (
        await session.execute(
            text(
                f"SELECT {_CONTACT_COLUMNS} FROM team_alert_contacts WHERE removed_at IS NULL "
                f"ORDER BY created_at LIMIT {MAX_CONTACTS}"
            )
        )
    ).all()
    return [_contact(r) for r in rows]


async def _live_contact(session: AsyncSession, contact_id: UUID, *, lock: bool = False) -> Contact:
    row = (
        await session.execute(
            text(
                f"SELECT {_CONTACT_COLUMNS} FROM team_alert_contacts "
                "WHERE id = :id AND removed_at IS NULL" + (" FOR UPDATE" if lock else "")
            ),
            {"id": contact_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Team address")
    return _contact(row)


def _normalise(address: str) -> str:
    cleaned = address.strip().lower()
    if not 3 <= len(cleaned) <= MAX_ADDRESS_CHARS:
        raise ProblemError(
            kind="validation",
            code="team_address_invalid",
            title="That email address will not work",
            detail="Enter one email address your team reads.",
        )
    return cleaned


async def _issue_code(session: AsyncSession, *, tenant_id: UUID, contact_id: UUID) -> None:
    """A new code for this address, stored as a keyed hash, and the promise to mail it."""
    code = codes.new_otp_code()
    now = datetime.now(UTC)
    await session.execute(
        text(
            "UPDATE team_alert_contacts SET code_hash = :hash, code_expires_at = :expires, "
            "code_sent_at = :now, code_attempts = 0, updated_at = now() WHERE id = :id"
        ),
        {
            "hash": codes.code_fingerprint(code, domain=_code_domain(contact_id)),
            "expires": now + CODE_TTL,
            "now": now,
            "id": contact_id,
        },
    )
    # The code rides in the outbox payload, which `mark_outbox_published` clears once the job is
    # queued, and the job keeps no result (`workers/settings.RESULT_WINDOW_S`).
    await enqueue_outbox(
        session,
        job=CODE_JOB,
        payload={"tenant_id": str(tenant_id), "contact_id": str(contact_id), "code": code},
    )


def _refuse_whatsapp(detail: str) -> ProblemError:
    return ProblemError(
        kind="validation",
        code="team_whatsapp_invalid",
        title="That WhatsApp set-up will not work",
        detail=detail,
    )


async def _check_whatsapp(session: AsyncSession, setup: WhatsAppSetup) -> None:
    from apps.api.team_alerts import whatsapp as team_wa

    provider = await team_wa.provider_of(session, setup.credential_id)
    if provider is None:
        raise _refuse_whatsapp("Choose one of your connected WhatsApp accounts.")
    if not setup.template.strip():
        raise _refuse_whatsapp("Enter the name of your approved message template.")
    values = list(setup.values)
    if (
        len(values) != len(set(values))
        or any(v not in WHATSAPP_SLOTS for v in values)
        or not {"name", "phone", "why"} <= set(values)
    ):
        raise _refuse_whatsapp(
            "Your template must carry the caller's name, their number and why, each once."
        )
    if provider in team_wa.NEEDS_LANGUAGE and not (setup.language or "").strip():
        raise _refuse_whatsapp("Enter the template's language code, for example en or te.")


async def add_contact(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    address: str,
    channel: str = "email",
    whatsapp: WhatsAppSetup | None = None,
) -> Contact:
    """Add a team address and send it a code. An address already on the list is answered with
    the existing one, so a double click adds nothing. A WhatsApp number is sent its code
    through the client's own connection and template."""
    if channel == "whatsapp":
        from apps.api.ingest.service import normalize_phone

        number = normalize_phone(address)
        if number is None or whatsapp is None:
            raise _refuse_whatsapp("Enter the team's WhatsApp number with its country code.")
        await _check_whatsapp(session, whatsapp)
        cleaned = number
    else:
        cleaned = _normalise(address)
    existing = (
        await session.execute(
            text(
                f"SELECT {_CONTACT_COLUMNS} FROM team_alert_contacts "
                "WHERE address = :address AND channel = :channel AND removed_at IS NULL"
            ),
            {"address": cleaned, "channel": channel},
        )
    ).first()
    if existing is not None:
        return _contact(existing)
    count = (
        await session.execute(
            text("SELECT count(*) FROM team_alert_contacts WHERE removed_at IS NULL")
        )
    ).scalar_one()
    if int(count) >= MAX_CONTACTS:
        raise ProblemError.business_rule(
            "team_addresses_full",
            f"You can keep up to {MAX_CONTACTS} team addresses.",
            remediation="Remove one you no longer use, then add this one.",
        )
    contact_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO team_alert_contacts (id, tenant_id, channel, address, "
            "whatsapp_credential_id, whatsapp_template, whatsapp_language, whatsapp_number_id, "
            "whatsapp_values, created_at, updated_at) VALUES (:id, :tid, :channel, :address, "
            ":cred, :template, :language, :number_id, CAST(:values AS jsonb), now(), now())"
        ),
        {
            "id": contact_id,
            "tid": tenant_id,
            "channel": channel,
            "address": cleaned,
            "cred": whatsapp.credential_id if whatsapp else None,
            "template": whatsapp.template.strip() if whatsapp else None,
            "language": (whatsapp.language or "").strip() or None if whatsapp else None,
            "number_id": (whatsapp.number_id or "").strip() or None if whatsapp else None,
            "values": _json(list(whatsapp.values)) if whatsapp else None,
        },
    )
    await _issue_code(session, tenant_id=tenant_id, contact_id=contact_id)
    return await _live_contact(session, contact_id)


async def resend_code(session: AsyncSession, *, tenant_id: UUID, contact_id: UUID) -> Contact:
    contact = await _live_contact(session, contact_id, lock=True)
    if contact.verified:
        return contact
    if contact.code_sent_at is not None and datetime.now(UTC) - contact.code_sent_at < RESEND_WAIT:
        raise ProblemError.conflict(
            "team_code_just_sent",
            "A code was sent to this address a moment ago.",
            remediation="Wait a minute, check spam, then ask for another.",
        )
    await _issue_code(session, tenant_id=tenant_id, contact_id=contact_id)
    return await _live_contact(session, contact_id)


VerifyOutcome = Literal["verified", "wrong", "expired", "used_up"]


async def verify_contact(*, tenant_id: UUID, contact_id: UUID, code: str) -> VerifyOutcome:
    """Check the code in its OWN committed transaction, so a wrong guess is counted even
    though the request then answers with a refusal (which rolls the request's session back)."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT verified_at, code_hash, code_expires_at, code_attempts "
                    "FROM team_alert_contacts WHERE id = :id AND removed_at IS NULL FOR UPDATE"
                ),
                {"id": contact_id},
            )
        ).first()
        if row is None:
            raise ProblemError.not_found("Team address")
        verified_at, stored, expires, attempts = row
        if verified_at is not None:
            return "verified"
        if stored is None or int(attempts) >= CODE_MAX_ATTEMPTS:
            return "used_up"
        if expires is None or expires <= datetime.now(UTC):
            return "expired"
        candidates = codes.code_fingerprints(code.strip(), domain=_code_domain(contact_id))
        if any(hmac.compare_digest(bytes(stored), c) for c in candidates):
            await session.execute(
                text(
                    "UPDATE team_alert_contacts SET verified_at = now(), code_hash = NULL, "
                    "code_expires_at = NULL, updated_at = now() WHERE id = :id"
                ),
                {"id": contact_id},
            )
            return "verified"
        await session.execute(
            text(
                "UPDATE team_alert_contacts SET code_attempts = code_attempts + 1, "
                "updated_at = now() WHERE id = :id"
            ),
            {"id": contact_id},
        )
        return "wrong"


def refuse_verify(outcome: VerifyOutcome) -> ProblemError:
    if outcome == "expired":
        return ProblemError.business_rule(
            "team_code_expired",
            "That code has expired.",
            remediation="Ask for a new code and enter it within 30 minutes.",
        )
    if outcome == "used_up":
        return ProblemError.business_rule(
            "team_code_used_up",
            "Too many wrong codes were entered.",
            remediation="Ask for a new code.",
        )
    return ProblemError(
        kind="validation",
        code="team_code_wrong",
        title="That code is not right",
        detail="Check the latest email we sent to this address and enter its six digits.",
    )


async def remove_contact(session: AsyncSession, *, contact_id: UUID) -> list[UUID]:
    """Stop sending to this address. Returns the agents with an in-call rule, whose action
    goes when this was the last address that could hear it."""
    await _live_contact(session, contact_id, lock=True)
    await session.execute(
        text(
            "UPDATE team_alert_contacts SET removed_at = now(), is_default = false, "
            "code_hash = NULL, updated_at = now() WHERE id = :id"
        ),
        {"id": contact_id},
    )
    return await agents_with_rules(session)


async def live_contacts(session: AsyncSession) -> list[UUID]:
    """Every team address that hears now, oldest first."""
    rows = (
        await session.execute(
            text(f"SELECT id FROM team_alert_contacts WHERE {_LIVE_SQL} ORDER BY created_at")
        )
    ).all()
    return [UUID(str(r[0])) for r in rows]


async def team_covers(session: AsyncSession, *, call_id: UUID, channel: str, address: str) -> bool:
    """Was a team alert about this call queued to this owner address? Then the owner's own
    alert on that channel is skipped: the team alert reaches the same inbox or phone, with
    more. Asked of the call's alerts rather than of the list, so an address added after the
    call was told cannot swallow the owner's alert."""
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM team_alerts a JOIN team_alert_contacts c ON c.id = a.contact_id "
                "WHERE a.call_id = :cid AND a.status <> 'cancelled' "
                "AND c.channel = :channel AND c.address = :address LIMIT 1"
            ),
            {"cid": call_id, "channel": channel, "address": address.strip().lower()},
        )
    ).first()
    return row is not None


async def agents_with_rules(session: AsyncSession) -> list[UUID]:
    rows = (
        await session.execute(text("SELECT agent_id FROM team_alert_rules WHERE in_call"))
    ).all()
    return [UUID(str(r[0])) for r in rows]


# --- rules ----------------------------------------------------------------------------


async def load_rule(session: AsyncSession, agent_id: UUID) -> Rule | None:
    row = (
        await session.execute(
            text(
                "SELECT on_outcomes, on_fields, in_call FROM team_alert_rules WHERE agent_id = :aid"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        return None
    fields = tuple(
        FieldTrigger(str(f["key"]), tuple(str(v) for v in f.get("values") or ()))
        for f in (row[1] or [])
        if isinstance(f, dict) and f.get("key")
    )
    return Rule(
        on_outcomes=tuple(str(k) for k in (row[0] or [])),
        on_fields=fields,
        in_call=bool(row[2]),
    )


async def in_call_live(session: AsyncSession, agent_id: UUID) -> bool:
    """Whether `tell_the_team` is one of this agent's in-call actions now."""
    rule = await load_rule(session, agent_id)
    return rule is not None and rule.in_call and bool(await live_contacts(session))


async def _agent_choices(
    session: AsyncSession, agent_id: UUID
) -> tuple[list[Choice], list[Choice]]:
    """The agent's business outcomes and its choice fields, as the owner may pick them."""
    row = (
        await session.execute(
            text(
                "SELECT a.business_outcomes, es.fields FROM agents a "
                "LEFT JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    # Local: `crm.schemas` reaches this module through `agents.service`, a cycle at import.
    from apps.api.crm.lead_definition import LEAD_BAND

    outcomes, _starting = call_outcomes.outcomes_in_use(row[0])
    fields = [
        Choice(f.key, f.label, tuple(f.enum_values or ()))
        for f in with_core(row[1], await core_labels(session))
        if f.type == "enum" and f.enum_values
    ]
    choices = [
        Choice(o.key, o.label, positive=o.lead_status in LEAD_BAND, goal=o.lead_status == "hot")
        for o in outcomes
    ]
    return choices, fields


def default_rule(outcomes: list[Choice]) -> Rule:
    """An agent's rule until its owner saves one: every positive outcome it has now.

    Derived on every read rather than written when the agent is made or its outcomes are
    drafted, because the outcomes change under it (the starting set, then the AI draft, then
    the owner's edits) and a stored copy would hold the keys of a list that is gone. Once the
    owner saves, the row is theirs and no redraft touches it.
    """
    return Rule(on_outcomes=tuple(o.key for o in outcomes if o.positive))


async def effective_rule(session: AsyncSession, agent_id: UUID) -> Rule:
    """The rule a call is judged by: the owner's saved one, else `default_rule`."""
    saved = await load_rule(session, agent_id)
    if saved is not None:
        return saved
    outcomes, _fields = await _agent_choices(session, agent_id)
    return default_rule(outcomes)


async def read_rule(session: AsyncSession, *, agent_id: UUID) -> RuleView:
    outcomes, fields = await _agent_choices(session, agent_id)
    saved = await load_rule(session, agent_id)
    rule = saved or default_rule(outcomes)
    heard_by = len(await live_contacts(session))
    return RuleView(
        rule=rule,
        saved=saved is not None,
        outcomes=outcomes,
        fields=fields,
        team_addresses=heard_by,
        in_call_live=rule.in_call and heard_by > 0,
    )


def _refuse_choice(detail: str) -> ProblemError:
    return ProblemError(
        kind="validation",
        code="team_alert_choice_unknown",
        title="That choice is not on this agent",
        detail=detail,
        remediation="Reload the page and choose again.",
    )


async def save_rule(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, rule: Rule
) -> RuleView:
    """Store this agent's rule after checking every choice against the agent as it is now."""
    outcomes, fields = await _agent_choices(session, agent_id)
    outcome_keys = {o.key for o in outcomes}
    unknown = [k for k in rule.on_outcomes if k not in outcome_keys]
    if unknown:
        raise _refuse_choice("One of the chosen outcomes is no longer one of this agent's.")
    by_key = {f.key: f for f in fields}
    if len(rule.on_fields) > MAX_FIELD_TRIGGERS:
        raise _refuse_choice(f"Choose at most {MAX_FIELD_TRIGGERS} answers to watch.")
    for trigger in rule.on_fields:
        choice = by_key.get(trigger.key)
        if (
            choice is None
            or not trigger.values
            or any(v not in choice.values for v in trigger.values)
        ):
            raise _refuse_choice("One of the chosen answers is no longer one this agent records.")
    if rule.in_call:
        await _assert_room_for_action(session, agent_id)
    await session.execute(
        text(
            "INSERT INTO team_alert_rules (id, tenant_id, agent_id, on_outcomes, "
            "on_fields, in_call, created_at, updated_at) VALUES (:id, :tid, :aid, "
            "CAST(:outcomes AS jsonb), CAST(:fields AS jsonb), :in_call, now(), now()) "
            "ON CONFLICT (agent_id) DO UPDATE SET "
            "on_outcomes = EXCLUDED.on_outcomes, on_fields = EXCLUDED.on_fields, "
            "in_call = EXCLUDED.in_call, updated_at = now()"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "aid": agent_id,
            "outcomes": _json(list(dict.fromkeys(rule.on_outcomes))),
            "fields": _json([{"key": t.key, "values": list(t.values)} for t in rule.on_fields]),
            "in_call": rule.in_call,
        },
    )
    await resync_agents(session, [agent_id])
    return await read_rule(session, agent_id=agent_id)


async def _assert_room_for_action(session: AsyncSession, agent_id: UUID) -> None:
    """The in-call action shares the agent's action budget with the client's own actions."""
    from apps.api.actions.service import in_call_tools
    from apps.api.reliability.engine_actions import (
        THINNEST_CLIENT_ACTIONS_MAX,
        too_many_client_actions,
    )

    count = len(await in_call_tools(session, agent_id=agent_id)) + 1
    if count > THINNEST_CLIENT_ACTIONS_MAX:
        raise too_many_client_actions(count)


async def resync_agents(session: AsyncSession, agent_ids: list[UUID]) -> None:
    """Bring each live agent's voice-platform actions in line now (adds or removes
    `tell_the_team`); a no-op for an agent not live on an action engine."""
    from apps.api.reliability.engine_actions import sync_client_actions_now

    for agent_id in agent_ids:
        await sync_client_actions_now(session, agent_id=agent_id)


# --- queueing -------------------------------------------------------------------------


def _field_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def after_call_reasons(
    rule: Rule,
    *,
    outcome_key: str | None,
    outcome_label: str | None,
    data: dict[str, Any],
    labels: dict[str, str],
) -> list[dict[str, Any]]:
    """What in this call matched the owner's rule; empty when nothing did."""
    reasons: list[dict[str, Any]] = []
    if outcome_key and outcome_key in rule.on_outcomes:
        reasons.append({"kind": "outcome", "key": outcome_key, "label": outcome_label or ""})
    for trigger in rule.on_fields:
        matched = [v for v in _field_values(data.get(trigger.key)) if v in trigger.values]
        if matched:
            reasons.append(
                {
                    "kind": "field",
                    "key": trigger.key,
                    "label": labels.get(trigger.key, trigger.key),
                    "values": matched,
                }
            )
    return reasons


async def _queue(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    call_id: UUID,
    contact_id: UUID,
    trigger: str,
    reasons: list[dict[str, Any]],
    problem: str | None = None,
) -> bool:
    """One alert per (call, address). False when this call already told this address."""
    alert_id = (
        await session.execute(
            text(
                "INSERT INTO team_alerts (id, tenant_id, agent_id, call_id, contact_id, trigger, "
                "reasons, status, attempts, created_at, updated_at) VALUES (:id, :tid, :aid, "
                ":cid, :contact, :trigger, CAST(:reasons AS jsonb), 'queued', 0, now(), now()) "
                "ON CONFLICT (call_id, contact_id) DO NOTHING RETURNING id"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "aid": agent_id,
                "cid": call_id,
                "contact": contact_id,
                "trigger": trigger,
                "reasons": _json(reasons),
            },
        )
    ).scalar_one_or_none()
    if alert_id is None:
        return False
    payload: dict[str, Any] = {"tenant_id": str(tenant_id), "alert_id": str(alert_id)}
    if problem:
        payload["problem"] = problem
    await enqueue_outbox_once(
        session,
        job=ALERT_JOB,
        payload=payload,
        dedupe_key=f"team-alert:{call_id}:{contact_id}",
    )
    await write_audit(
        session,
        action="team_alert.queued",
        actor_type="system",
        tenant_id=tenant_id,
        object_type="call",
        object_id=str(call_id),
        summary={
            "agent_id": str(agent_id),
            "contact_id": str(contact_id),
            "trigger": trigger,
            "reasons": str(len(reasons)),
        },
    )
    return True


def reason_label(reason: dict[str, Any]) -> str:
    """One reason as the owner's alert names it: labels and values the owner configured, a
    Follow-up's own `why`, never anything the caller said."""
    kind = reason.get("kind")
    if kind == "outcome":
        return str(reason.get("label") or reason.get("key") or "")
    if kind == "field":
        values = ", ".join(str(v) for v in reason.get("values") or [])
        return f"{reason.get('label') or reason.get('key')}: {values}"
    if kind == "follow_up":
        return str(reason.get("why") or "")
    if kind == "in_call":
        return "Needs a person"
    return ""


async def _tell_owner(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    lead_id: UUID,
    call_id: UUID,
    reasons: list[dict[str, Any]],
) -> bool:
    queued = await enqueue_outbox_once(
        session,
        job=OWNER_JOB,
        payload={
            "tenant_id": str(tenant_id),
            "lead_id": str(lead_id),
            "call_id": str(call_id),
            "triggers": [label for label in (reason_label(r) for r in reasons) if label],
        },
        dedupe_key=owner_dedupe_key(lead_id=lead_id, call_id=call_id),
    )
    return queued is not None


async def tell_everyone(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    call_id: UUID,
    lead_id: UUID | None,
    trigger: str,
    reasons: list[dict[str, Any]],
) -> str:
    """Tell the whole list about this call: every team address, and the owner when there is a
    lead to open. Anyone already told about this call is not told again. Returns `queued`,
    `already_told`, or `nobody` when there is no team address and no lead."""
    contacts = await live_contacts(session)
    if not contacts and lead_id is None:
        return "nobody"
    told = False
    for contact_id in contacts:
        told |= await _queue(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            call_id=call_id,
            contact_id=contact_id,
            trigger=trigger,
            reasons=reasons,
        )
    if lead_id is not None:
        told |= await _tell_owner(
            session, tenant_id=tenant_id, lead_id=lead_id, call_id=call_id, reasons=reasons
        )
    return "queued" if told else "already_told"


async def _told_in_call(session: AsyncSession, call_id: UUID) -> bool:
    row = (
        await session.execute(
            text("SELECT 1 FROM team_alerts WHERE call_id = :cid AND trigger = 'in_call' LIMIT 1"),
            {"cid": call_id},
        )
    ).first()
    return row is not None


async def queue_after_call(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    call_id: UUID,
    lead_id: UUID | None,
    hot: bool,
    outcome_key: str | None,
    outcome_label: str | None,
    data: dict[str, Any],
    labels: dict[str, str],
) -> str:
    """STEP 6 of the post-call pipeline: tell the list when the agent's rule matched, or when
    the agent told the team during the call (the owner hears of that here, once there is a
    lead). Returns what happened, for the stage span.

    `hot` decides nothing here: a Hot outcome alerts only when it is ticked, like any other.
    It stays in the signature for the pipeline's call."""
    del hot
    rule = await effective_rule(session, agent_id)
    reasons = after_call_reasons(
        rule, outcome_key=outcome_key, outcome_label=outcome_label, data=data, labels=labels
    )
    if not reasons and await _told_in_call(session, call_id):
        reasons = [{"kind": "in_call"}]
    if not reasons:
        return "not_worth_telling"
    return await tell_everyone(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        call_id=call_id,
        lead_id=lead_id,
        trigger="after_call",
        reasons=reasons,
    )


async def queue_for_follow_up(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    call_id: UUID,
    lead_id: UUID | None,
    why: str,
    follow_up_id: UUID,
) -> str:
    """A Follow-up's "tell the team" step (D-940), about the call its run last placed, to the
    same list. Anyone already told about that call is not told again."""
    return await tell_everyone(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        call_id=call_id,
        lead_id=lead_id,
        trigger="follow_up",
        reasons=[{"kind": "follow_up", "why": why, "follow_up_id": str(follow_up_id)}],
    )


def clean_problem(raw: object) -> str:
    """The agent's note of the problem, as any action input reaching a person is: redacted,
    on one line, clipped."""
    one_line = " ".join(str(raw or "").split())
    return redact(one_line).text[:MAX_PROBLEM_CHARS]


async def queue_in_call(
    *, tenant_id: UUID, agent_id: UUID, call_id: UUID | None, problem: object
) -> InCallOutcome:
    """The `tell_the_team` action: tell every team address now, with what the agent said is
    wrong. The owner hears after the call (`queue_after_call`), once there is a lead."""
    if call_id is None:
        return "unavailable"
    async with tenant_session(tenant_id) as session:
        rule = await load_rule(session, agent_id)
        contacts = await live_contacts(session) if rule and rule.in_call else []
        if not contacts:
            return "unavailable"
        note = clean_problem(problem) or None
        queued = False
        for contact_id in contacts:
            queued |= await _queue(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                call_id=call_id,
                contact_id=contact_id,
                trigger="in_call",
                reasons=[{"kind": "in_call"}],
                problem=note,
            )
    log.info(
        "team_alert_in_call",
        extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id), "queued": queued},
    )
    return "queued" if queued else "already_told"


def _json(value: Any) -> str:
    return json.dumps(value)


__all__ = [
    "ALERT_JOB",
    "CODE_JOB",
    "MAX_CONTACTS",
    "OWNER_JOB",
    "TEAM_ACTION_DESCRIPTION",
    "TEAM_ACTION_NAME",
    "TEAM_PROBLEM_DESCRIPTION",
    "TEAM_PROBLEM_PARAM",
    "Choice",
    "Contact",
    "FieldTrigger",
    "Rule",
    "RuleView",
    "add_contact",
    "after_call_reasons",
    "agents_with_rules",
    "clean_problem",
    "default_rule",
    "effective_rule",
    "in_call_live",
    "list_contacts",
    "live_contacts",
    "load_rule",
    "owner_dedupe_key",
    "queue_after_call",
    "queue_for_follow_up",
    "queue_in_call",
    "read_rule",
    "reason_label",
    "refuse_verify",
    "remove_contact",
    "resend_code",
    "resync_agents",
    "save_rule",
    "team_covers",
    "tell_everyone",
    "verify_contact",
]
