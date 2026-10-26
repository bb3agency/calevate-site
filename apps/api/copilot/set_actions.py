"""Plan-backed actions over a SET of leads (D-893 F3): the pattern every lane reuses.

Each tool here is `plans.set_action_tool(...)`: confirm tier, a plan card, the targets
chosen by a `lens` (the filters a person can read; `copilot/lens_args.py`) or by explicit
`lead_ids` from the screen's selection, never by text a caller or a lead form wrote. The
per-target work calls the same service function the console's button calls:

* `leads_bulk_update` — `crm.service.apply_bulk_leads` (`POST /v1/leads/bulk`), one lead at
  a time, so each lead gets its own outcome.
* `campaign_add_leads` — `campaigns.service.add_contacts` (the campaign screen's upload).
* `callbacks_book_bulk` — `crm.swipe.schedule_lead_callback` (`POST /v1/leads/{id}/
  callback`), standing refusals and the 09:00-21:00 India window included.
* `calls_place_bulk` — a DIALLING plan: a `pip` campaign over the frozen leads, launched
  through `campaigns.service.launch_campaign`, so the compliance gate, the line limit,
  pacing, calling hours and retries all apply (hard rule 5).

Who is left out is decided with the dispatch gate's own person-level questions
(`compliance.service.person_level_refusal`: do-not-call, consent, an erased or non-India
number), recorded on the plan with the reason, and asked again by the service at run time.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final, Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns import controls as campaign_controls
from apps.api.copilot import lens_args, plans
from apps.api.copilot.actions import ToolActor, WriteRefusedError, parse_args
from apps.api.copilot.sanitize import strip_invisible
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.crm import lens as crm_lens
from apps.api.crm import service as crm_service
from apps.api.crm.schemas import LeadStatus

#: The leads a selection may name explicitly; anything larger is a lens.
MAX_NAMED_LEADS: Final = 500

_LEAD_IDS_SCHEMA: Final[dict[str, Any]] = {
    "anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}],
    "description": "The leads ticked on screen; null when `lens` chooses them.",
}

#: Consent sources a dialling plan may name (`campaigns.models.CONSENT_SOURCES` minus the
#: one the launch gate refuses).
DialConsent = Literal[
    "existing_customer", "inbound_enquiry", "web_form_optin", "offline_form_optin"
]


def _principal(actor: ToolActor) -> Principal:
    return Principal(
        realm="client",
        user_id=actor.user_id,
        tenant_id=actor.tenant_id,
        role=actor.role,
        impersonating=actor.impersonating,
    )


async def chosen_leads(session: AsyncSession, args: Mapping[str, Any]) -> tuple[list[UUID], str]:
    """The leads `lens` or `lead_ids` names, in order, and how a person reads that choice.

    Exactly one must be given: a selection AND a filter would be two answers to "which"."""
    raw_ids = args.get("lead_ids")
    raw_lens = args.get("lens")
    if raw_ids and raw_lens:
        raise WriteRefusedError("give `lens` or `lead_ids`, not both")
    if raw_ids:
        if not isinstance(raw_ids, list) or len(raw_ids) > MAX_NAMED_LEADS:
            raise WriteRefusedError(
                f"`lead_ids` takes at most {MAX_NAMED_LEADS} ids; use `lens` for more"
            )
        try:
            ids = [UUID(str(value)) for value in raw_ids]
        except ValueError as exc:
            raise WriteRefusedError("`lead_ids` holds something that is not a lead id") from exc
        targets = await crm_service.resolve_bulk_targets(session, ids=ids)
        return list(targets.ids), f"the {len(targets.ids)} leads you chose"
    if raw_lens is None:
        raise WriteRefusedError(
            "say which leads: pass `lens` (the filters from leads_find) or `lead_ids`"
        )
    try:
        lens = lens_args.lead_lens(raw_lens)
    except lens_args.LensArgumentError as refused:
        raise WriteRefusedError(refused.reason) from refused
    scope = await crm_lens.resolve_lead_scope(session, lens)
    return await crm_lens.lead_ids(session, scope), crm_lens.describe_lead_lens(lens)


async def _phones(session: AsyncSession, lead_ids: Sequence[UUID]) -> dict[UUID, tuple[str, str]]:
    rows = await session.execute(
        text(
            "SELECT id, phone_e164, coalesce(name, '') FROM leads "
            "WHERE id = ANY(:ids) AND deleted_at IS NULL"
        ),
        {"ids": list(lead_ids)},
    )
    return {UUID(str(r[0])): (str(r[1]), str(r[2])) for r in rows.all()}


async def person_exclusions(
    session: AsyncSession, actor: ToolActor, lead_ids: Sequence[UUID]
) -> dict[UUID, str]:
    """Leads the dispatch gate refuses whatever the hour: its own person-level questions."""
    from apps.api.compliance.service import person_level_refusal

    phones = await _phones(session, lead_ids)
    left_out: dict[UUID, str] = {}
    for lead_id in lead_ids:
        found = phones.get(lead_id)
        if found is None:
            left_out[lead_id] = "This lead is no longer on the account."
            continue
        refused = await person_level_refusal(
            session, tenant_id=actor.tenant_id, phone_e164=found[0]
        )
        if refused is not None:
            left_out[lead_id] = refused.reason or "The calling rules do not allow it."
    return left_out


async def dial_estimate(
    session: AsyncSession, *, agent_id: UUID, calls: int, at: datetime | None = None
) -> plans.Estimate:
    """What `calls` answered calls by this agent would cost at most: the account's average
    answered-call length over 30 days, at the published list rate for the agent's voice
    (the dearest per-minute rate a lot can hold). "Not known" without both."""
    from apps.api.agents.voices import voice_tier
    from apps.api.billing.service import rate_card_at

    minutes = (
        await session.execute(
            text(
                "SELECT avg(ceil(duration_s / 60.0)) FROM calls WHERE status = 'completed' "
                "AND duration_s > 0 AND created_at > now() - interval '30 days'"
            )
        )
    ).scalar_one_or_none()
    if minutes is None:
        return plans.Estimate(
            inr=None, note="There are no answered calls in the last 30 days to judge length by."
        )
    voice = (
        await session.execute(text("SELECT tts_voice FROM agents WHERE id = :id"), {"id": agent_id})
    ).scalar_one_or_none()
    try:
        rate = (
            (await rate_card_at(session, at=at or datetime.now(UTC)))
            .list_rates()
            .rate_for(voice_tier(voice))
        )
    except (KeyError, ValueError):
        return plans.Estimate(inr=None, note="The per-minute rate for this voice is not set.")
    per_call = Decimal(str(minutes))
    total = (per_call * rate * calls).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return plans.Estimate(
        inr=total,
        note=(
            f"At most: {calls} answered call(s) of about {per_call:.1f} min at ₹{rate}/min. "
            "Calls nobody answers cost less."
        ),
    )


# --- leads_bulk_update ---------------------------------------------------------------------


class _BulkChange(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: Literal["status", "assign"]
    status: LeadStatus | None = None
    user_id: UUID | None = None


async def _member_name(session: AsyncSession, user_id: UUID | None) -> str:
    if user_id is None:
        return "nobody"
    row = (
        await session.execute(
            text(
                "SELECT u.name FROM memberships m JOIN users u ON u.id = m.user_id "
                "WHERE m.user_id = :uid AND u.deactivated_at IS NULL"
            ),
            {"uid": user_id},
        )
    ).first()
    if row is None:
        raise WriteRefusedError(
            "that person is not on this account's team, so look them up with team_members"
        )
    return strip_invisible(str(row[0] or "a team member"))


async def _prepare_bulk(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> plans.Prepared:
    del actor
    change = parse_args(_BulkChange, args)
    if change.action == "status" and change.status is None:
        raise WriteRefusedError("a status change needs `status`")
    targets, lens_text = await chosen_leads(session, args)
    if change.action == "status":
        why = f"Mark them {change.status}"
    else:
        why = f"Give them to {await _member_name(session, change.user_id)}"
    return plans.Prepared(
        targets=targets,
        lens_text=lens_text,
        title=f"Change {len(targets)} leads",
        why=why,
        change={
            "action": change.action,
            "status": change.status,
            "user_id": None if change.user_id is None else str(change.user_id),
        },
    )


async def _exclude_bulk(
    session: AsyncSession, actor: ToolActor, change: Mapping[str, Any], lead_ids: Sequence[UUID]
) -> dict[UUID, str]:
    del actor
    parsed = _BulkChange.model_validate(change)
    if parsed.action == "status":
        rows = await session.execute(
            text("SELECT id FROM leads WHERE id = ANY(:ids) AND status = :s"),
            {"ids": list(lead_ids), "s": parsed.status},
        )
        reason = f"Already {parsed.status}."
    else:
        rows = await session.execute(
            text(
                "SELECT id FROM leads WHERE id = ANY(:ids) AND assigned_to IS NOT DISTINCT FROM :u"
            ),
            {"ids": list(lead_ids), "u": parsed.user_id},
        )
        reason = "Already owned by that person."
    return {UUID(str(r[0])): reason for r in rows.all()}


async def _no_cost(
    session: AsyncSession, actor: ToolActor, change: Mapping[str, Any], n: int
) -> plans.Estimate:
    del session, actor, change, n
    return plans.NO_COST


async def _run_bulk(
    session: AsyncSession, actor: ToolActor, change: Mapping[str, Any], lead_id: UUID
) -> plans.TargetOutcome:
    """`apply_bulk_leads` for one lead: the route's function, so a lead that moved since the
    plan is re-judged here, not swapped."""
    parsed = _BulkChange.model_validate(change)
    targets = await crm_service.resolve_bulk_targets(session, ids=[lead_id])
    outcome = await crm_service.apply_bulk_leads(
        session,
        targets=targets,
        action=parsed.action,
        status=parsed.status,
        assignee=(
            crm_service.AssigneeChange(user_id=parsed.user_id)
            if parsed.action == "assign"
            else None
        ),
        actor=str(actor.user_id),
    )
    if outcome.failures:
        return plans.TargetOutcome("failed", outcome.failures[0].reason)
    if outcome.changed:
        return plans.TargetOutcome("done")
    return plans.TargetOutcome("skipped", "Already that way.")


BULK_UPDATE: Final = plans.SetAction(
    target_type="lead",
    prepare=_prepare_bulk,
    exclude=_exclude_bulk,
    estimate=_no_cost,
    run_one=_run_bulk,
)

LEADS_BULK_UPDATE: Final = plans.set_action_tool(
    name="leads_bulk_update",
    permission="leads:write",
    object_type="lead",
    audit_action="lead.bulk_action",
    where="on the Leads screen",
    description=(
        "Change the status or the owner of many leads, chosen by `lens` (the filters from "
        "`leads_search`) or the `lead_ids` ticked on screen; for one lead use "
        "`lead_set_status`. The person approves one plan."
    ),
    properties={
        "lens": lens_args.LEAD_LENS_SCHEMA,
        "lead_ids": _LEAD_IDS_SCHEMA,
        "action": {"type": "string", "enum": ["status", "assign"]},
        "status": {
            "anyOf": [{"type": "string", "enum": list(get_args(LeadStatus))}, {"type": "null"}],
            "description": "With `status`, the new status; null with `assign`.",
        },
        "user_id": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "With `assign`: the team member's id, or null for nobody.",
        },
    },
    action=BULK_UPDATE,
)


# --- campaign_add_leads --------------------------------------------------------------------


class _CampaignChange(BaseModel):
    model_config = ConfigDict(extra="ignore")

    campaign_id: UUID


async def _campaign_name(session: AsyncSession, campaign_id: UUID) -> str:
    row = (
        await session.execute(
            text("SELECT name, status FROM campaigns WHERE id = :id"), {"id": campaign_id}
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Campaign")
    if str(row[1]) not in ("draft", "scheduled"):
        raise WriteRefusedError(
            f"that campaign is {row[1]}; leads are added only before it is launched"
        )
    return strip_invisible(str(row[0]))


async def _prepare_add(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> plans.Prepared:
    del actor
    change = parse_args(_CampaignChange, args)
    name = await _campaign_name(session, change.campaign_id)
    targets, lens_text = await chosen_leads(session, args)
    return plans.Prepared(
        targets=targets,
        lens_text=lens_text,
        title=f"Add {len(targets)} leads to “{name}”",
        why=f"Add them to the call list of “{name}”",
        change={"campaign_id": str(change.campaign_id)},
    )


async def _exclude_add(
    session: AsyncSession, actor: ToolActor, change: Mapping[str, Any], lead_ids: Sequence[UUID]
) -> dict[UUID, str]:
    left_out = await person_exclusions(session, actor, lead_ids)
    rows = await session.execute(
        text(
            "SELECT l.id FROM leads l JOIN campaign_contacts c ON c.phone_e164 = l.phone_e164 "
            "AND c.campaign_id = :cid WHERE l.id = ANY(:ids)"
        ),
        {"cid": UUID(str(change["campaign_id"])), "ids": list(lead_ids)},
    )
    for r in rows.all():
        left_out.setdefault(UUID(str(r[0])), "Already on this campaign.")
    return left_out


async def _estimate_add(
    session: AsyncSession, actor: ToolActor, change: Mapping[str, Any], n: int
) -> plans.Estimate:
    del session, actor, change, n
    return plans.Estimate(
        inr=Decimal("0"),
        note="Adding costs nothing; calls are billed when the campaign runs.",
    )


async def _run_add(
    session: AsyncSession, actor: ToolActor, change: Mapping[str, Any], lead_id: UUID
) -> plans.TargetOutcome:
    """`campaigns.controls.add_leads` — `POST /v1/campaigns/{id}/contacts/from-leads`'s
    function, which reads the number from the lead itself."""
    return _added(
        await campaign_controls.add_leads(
            session,
            tenant_id=actor.tenant_id,
            campaign_id=UUID(str(change["campaign_id"])),
            lead_ids=[lead_id],
        )
    )


def _added(result: Mapping[str, int]) -> plans.TargetOutcome:
    if result["added"]:
        return plans.TargetOutcome("done")
    if not result.get("leads"):
        return plans.TargetOutcome("skipped", "This lead is no longer on the account.")
    if result["duplicate"]:
        return plans.TargetOutcome("skipped", "Already on this campaign.")
    return plans.TargetOutcome("skipped", "This number cannot be called from a campaign.")


ADD_TO_CAMPAIGN: Final = plans.SetAction(
    target_type="lead",
    prepare=_prepare_add,
    exclude=_exclude_add,
    estimate=_estimate_add,
    run_one=_run_add,
)

CAMPAIGN_ADD_LEADS: Final = plans.set_action_tool(
    name="campaign_add_leads",
    permission="leads:dispatch",
    object_type="campaign",
    audit_action="campaign.contacts_added",
    where="on the campaign's own screen",
    description=(
        "Add leads to a draft or scheduled campaign's call list, chosen by `lens` (the "
        "filters from `leads_search`) or the `lead_ids` ticked on screen. A CSV is uploaded "
        "on the campaign screen instead. The person approves one plan."
    ),
    properties={
        "campaign_id": {"type": "string", "description": "From `campaigns_list`."},
        "lens": lens_args.LEAD_LENS_SCHEMA,
        "lead_ids": _LEAD_IDS_SCHEMA,
    },
    action=ADD_TO_CAMPAIGN,
)


# --- callbacks_book_bulk -------------------------------------------------------------------


class _CallbackChange(BaseModel):
    model_config = ConfigDict(extra="ignore")

    at: str
    agent_id: UUID | None = None
    note: str | None = Field(default=None, max_length=200)


def _ist_instant(raw: str) -> datetime:
    from apps.api.billing.plans import IST
    from apps.api.crm.swipe import check_schedule_time

    try:
        local = datetime.fromisoformat(raw.strip())
    except ValueError as exc:
        raise WriteRefusedError("`at` must look like 2026-10-28T10:30 (India time)") from exc
    instant = local if local.tzinfo else local.replace(tzinfo=IST)
    try:
        check_schedule_time(instant, now=datetime.now(UTC))
    except ProblemError as problem:
        raise WriteRefusedError(f"{problem.detail} Ask the person for another time") from problem
    return instant.astimezone(UTC)


async def _prepare_callbacks(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> plans.Prepared:
    del actor
    change = parse_args(_CallbackChange, args)
    when = _ist_instant(change.at)
    if change.agent_id is not None:
        found = (
            await session.execute(
                text("SELECT 1 FROM agents WHERE id = :id AND deleted_at IS NULL"),
                {"id": change.agent_id},
            )
        ).first()
        if found is None:
            raise ProblemError.not_found("Agent")
    targets, lens_text = await chosen_leads(session, args)
    note = None if change.note is None else (strip_invisible(change.note).strip() or None)
    return plans.Prepared(
        targets=targets,
        lens_text=lens_text,
        title=f"Call back {len(targets)} leads",
        why="Book an automatic call-back for each",
        change={
            "at": when.isoformat(),
            "agent_id": None if change.agent_id is None else str(change.agent_id),
            "note": note,
        },
        run_at=when,
    )


async def _exclude_callbacks(
    session: AsyncSession, actor: ToolActor, change: Mapping[str, Any], lead_ids: Sequence[UUID]
) -> dict[UUID, str]:
    del change
    left_out = await person_exclusions(session, actor, lead_ids)
    rows = await session.execute(
        text(
            "SELECT DISTINCT lead_id FROM scheduled_callbacks WHERE lead_id = ANY(:ids) "
            "AND status IN ('scheduled', 'dialing')"
        ),
        {"ids": list(lead_ids)},
    )
    for r in rows.all():
        left_out.setdefault(UUID(str(r[0])), "A call-back is already waiting.")
    return left_out


async def _agent_for_estimate(session: AsyncSession, agent_id: str | None) -> UUID | None:
    if agent_id is not None:
        return UUID(agent_id)
    found = (
        await session.execute(
            text(
                "SELECT id FROM agents WHERE deleted_at IS NULL AND status = 'live' "
                "AND direction IN ('outbound', 'both') ORDER BY created_at, id LIMIT 1"
            )
        )
    ).scalar_one_or_none()
    return None if found is None else UUID(str(found))


async def _estimate_callbacks(
    session: AsyncSession, actor: ToolActor, change: Mapping[str, Any], n: int
) -> plans.Estimate:
    del actor
    agent = await _agent_for_estimate(session, change.get("agent_id"))
    if agent is None:
        return plans.Estimate(inr=None, note="No live agent places calls on this account.")
    return await dial_estimate(session, agent_id=agent, calls=n)


async def _run_callback(
    session: AsyncSession, actor: ToolActor, change: Mapping[str, Any], lead_id: UUID
) -> plans.TargetOutcome:
    """`swipe.schedule_lead_callback` — the call-back route's own function."""
    from apps.api.crm.swipe import schedule_lead_callback

    parsed = _CallbackChange.model_validate(change)
    try:
        booked = await schedule_lead_callback(
            session,
            tenant_id=actor.tenant_id,
            lead_id=lead_id,
            at=datetime.fromisoformat(parsed.at),
            note=parsed.note,
            agent_id=parsed.agent_id,
        )
    except ProblemError as problem:
        return plans.TargetOutcome("failed", problem.detail)
    if booked.status == "blocked":
        return plans.TargetOutcome("skipped", booked.blocked_reason)
    return plans.TargetOutcome("done")


BOOK_CALLBACKS: Final = plans.SetAction(
    target_type="lead",
    prepare=_prepare_callbacks,
    exclude=_exclude_callbacks,
    estimate=_estimate_callbacks,
    run_one=_run_callback,
)

CALLBACKS_BOOK_BULK: Final = plans.set_action_tool(
    name="callbacks_book_bulk",
    permission="leads:dispatch",
    object_type="callback",
    audit_action="callback.booked",
    where="on the Call-backs screen",
    description=(
        "Book an automatic call-back for many leads at one time, chosen by `lens` or "
        "`lead_ids`; for one lead use `callback_book`. Between 9am and 9pm India time. The "
        "person approves one plan."
    ),
    properties={
        "lens": lens_args.LEAD_LENS_SCHEMA,
        "lead_ids": _LEAD_IDS_SCHEMA,
        "at": {"type": "string", "description": "India time, like 2026-10-28T10:30."},
        "agent_id": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "The agent that calls; null for each lead's own calling agent.",
        },
        "note": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "What the call-backs are about, or null.",
        },
    },
    action=BOOK_CALLBACKS,
)


# --- calls_place_bulk (a dialling plan) ----------------------------------------------------


class _DialChange(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agent_id: UUID
    classification: Literal["service", "promotional"]
    consent_source: DialConsent


async def _prepare_dial(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> plans.Prepared:
    from apps.api.compliance.registration import refuse_promotional_without_registration
    from apps.api.compliance.service import account_dial_blockers

    change = parse_args(_DialChange, args)
    agent = (
        await session.execute(
            text(
                "SELECT name, status, direction FROM agents WHERE id = :id AND deleted_at IS NULL"
            ),
            {"id": change.agent_id},
        )
    ).first()
    if agent is None:
        raise ProblemError.not_found("Agent")
    if str(agent[2]) == "inbound":
        raise WriteRefusedError("that agent only answers calls; pick one that places them")
    blockers = await account_dial_blockers(session, tenant_id=actor.tenant_id, trial_call=False)
    if blockers:
        raise WriteRefusedError(
            "this account cannot place calls yet: " + "; ".join(reason for _, reason in blockers)
        )
    await refuse_promotional_without_registration(session, classification=change.classification)
    targets, lens_text = await chosen_leads(session, args)
    agent_name = strip_invisible(str(agent[0]))
    return plans.Prepared(
        targets=targets,
        lens_text=lens_text,
        title=f"Call {len(targets)} leads",
        why=f"“{agent_name}” calls each one, as a campaign, inside calling hours",
        change={
            "agent_id": str(change.agent_id),
            "classification": change.classification,
            "consent_source": change.consent_source,
        },
    )


async def _exclude_dial(
    session: AsyncSession, actor: ToolActor, change: Mapping[str, Any], lead_ids: Sequence[UUID]
) -> dict[UUID, str]:
    del change
    return await person_exclusions(session, actor, lead_ids)


async def _estimate_dial(
    session: AsyncSession, actor: ToolActor, change: Mapping[str, Any], n: int
) -> plans.Estimate:
    del actor
    return await dial_estimate(session, agent_id=UUID(str(change["agent_id"])), calls=n)


async def _dial(
    session: AsyncSession,
    actor: ToolActor,
    change: Mapping[str, Any],
    title: str,
    lead_ids: Sequence[UUID],
) -> plans.DialStart:
    """A `pip` campaign over the frozen leads, launched through the launch gate. The
    contacts' consent date is the newest lead's creation: the list existed by then."""
    from apps.api.campaigns import service as campaigns_service
    from apps.api.compliance.audit import write_audit

    parsed = _DialChange.model_validate(change)
    collected = (
        await session.execute(
            text("SELECT max(created_at) FROM leads WHERE id = ANY(:ids)"), {"ids": list(lead_ids)}
        )
    ).scalar_one_or_none() or datetime.now(UTC) - timedelta(minutes=1)
    campaign_id = await campaigns_service.create_campaign(
        session,
        tenant_id=actor.tenant_id,
        agent_id=parsed.agent_id,
        name=f"Pip: {title}"[:120],
        classification=parsed.classification,
        number_id=None,
        dlt_template_id=None,
        concurrency=3,
        consent_source=parsed.consent_source,
        consent_collected_at=collected,
        kind="pip",
    )
    outcomes = {
        lead_id: _added(
            await campaign_controls.add_leads(
                session, tenant_id=actor.tenant_id, campaign_id=campaign_id, lead_ids=[lead_id]
            )
        )
        for lead_id in lead_ids
    }
    result = await campaigns_service.launch_campaign(
        session, tenant_id=actor.tenant_id, campaign_id=campaign_id
    )
    await write_audit(
        session,
        action="campaign.launched",
        actor=_principal(actor),
        tenant_id=actor.tenant_id,
        object_type="campaign",
        object_id=str(campaign_id),
        ip=None,
        summary={
            "via": "copilot_plan",
            "dialable": result["dialable"],
            "dnc_scrubbed": result["dnc_scrubbed"],
        },
    )
    return plans.DialStart(campaign_id=campaign_id, outcomes=outcomes)


DIAL_LEADS: Final = plans.SetAction(
    target_type="lead",
    prepare=_prepare_dial,
    exclude=_exclude_dial,
    estimate=_estimate_dial,
    dial=_dial,
)

CALLS_PLACE_BULK: Final = plans.set_action_tool(
    name="calls_place_bulk",
    permission="leads:dispatch",
    object_type="campaign",
    audit_action="campaign.pip_plan_approved",
    where="in Campaigns and Call logs",
    description=(
        "Have an agent call many leads, chosen by `lens` or `lead_ids`, as a campaign that "
        "keeps calling hours, pacing and retries; for one lead now use `call_place`. Ask "
        "how these people agreed to be called (`consent_source`) and the kind of calls. The "
        "person approves one plan."
    ),
    properties={
        "lens": lens_args.LEAD_LENS_SCHEMA,
        "lead_ids": _LEAD_IDS_SCHEMA,
        "agent_id": {"type": "string", "description": "An agent that places calls."},
        "classification": {"type": "string", "enum": ["service", "promotional"]},
        "consent_source": {
            "type": "string",
            "enum": list(get_args(DialConsent)),
            "description": "How these people agreed to be called; ask, never assume.",
        },
    },
    action=DIAL_LEADS,
)


SET_ACTIONS: Final = (CALLBACKS_BOOK_BULK, CALLS_PLACE_BULK)

__all__ = [
    "ADD_TO_CAMPAIGN",
    "BOOK_CALLBACKS",
    "BULK_UPDATE",
    "CALLBACKS_BOOK_BULK",
    "CALLS_PLACE_BULK",
    "CAMPAIGN_ADD_LEADS",
    "DIAL_LEADS",
    "LEADS_BULK_UPDATE",
    "MAX_NAMED_LEADS",
    "SET_ACTIONS",
    "chosen_leads",
    "dial_estimate",
    "person_exclusions",
]
