"""Pip's D-938 coverage actions: the screen buttons that had no Pip action yet.

Each calls the service function its own button's route calls, under the same permission:

* `account_model_tier_set` — AI models screen, `PUT /v1/organization/llm-defaults`.
* `agent_team_alert_set` — an agent's "Tell my team", `PUT /v1/agents/{id}/team-alert`.
* `team_alert_contact` — the team addresses, `/v1/team-alerts/contacts/**` (email only: a
  WhatsApp address needs the account's own template set up on the screen).
* `knowledge_refresh` — approve a waiting upload, or read a PDF or page again,
  `POST /v1/kb/uploads/{id}/confirm` and `/read`.
* `connection_disconnect` — `DELETE /v1/integrations/credentials/{id}`.
* `account_switch_set` — three owner switches: staff may curate knowledge
  (`PUT /v1/kb/staff-curation`), opt-in required before dialling
  (`PUT /v1/compliance/call-consent/policy`) and the save-our-number WhatsApp
  (`PUT /v1/forwarding/save-number`, which demands its emailed code here as on the screen).

Every one is `confirm`: a model tier changes what each minute costs; a team alert sends a
caller's details outside the dashboard; a team address and a disconnect change who receives
what; an approval or a re-read changes what live agents say; and each switch moves who may
write knowledge, who may be called, or whether callers are messaged.

NEVER HERE: entering an emailed verification code for a team address (the person types it on
the Alerts screen), connecting an account (their own sign-in), and the person's own consent
records.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot.actions import (
    PROPOSES_ONLY,
    ActionTool,
    Executed,
    Plan,
    ToolActor,
    WriteRefusedError,
    action_schema,
    parse_args,
)
from apps.api.copilot.actions import principal_of as _principal_of
from apps.api.copilot.help import HELP_LOOKUP
from apps.api.copilot.sanitize import strip_invisible
from apps.api.copilot.tools import ReadTool, ToolContext
from apps.api.core.errors import ProblemError
from apps.api.db.ownership import assert_visible
from apps.api.kb.proposals import CURATE_PERMISSION
from apps.workers.redaction import redact


def _masked(value: str) -> str:
    return redact(value).text


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


async def _agent_name(session: AsyncSession, agent_id: UUID) -> str:
    await assert_visible(session, "agent", agent_id)
    row = (
        await session.execute(
            text("SELECT name FROM agents WHERE id = :aid AND deleted_at IS NULL"),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise WriteRefusedError("that agent has been deleted; choose another from `agents_list`")
    return strip_invisible(str(row[0]))


# =========================================================================================
# THE ACCOUNT'S AI MODEL TIER
# =========================================================================================

Tier = Literal["standard", "plus", "pro", "default"]


class _TierArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: Tier


def _tier_words(model: str | None) -> str:
    from apps.api.agents.llm_tiers import LLM_TIER_LABELS, tier_of_model

    if model is None:
        return "Calevate's default"
    tier = tier_of_model(model)
    return LLM_TIER_LABELS[tier] if tier else "a model chosen for you"


async def _org_model(session: AsyncSession) -> str | None:
    row = (
        await session.execute(
            text("SELECT default_llm_model FROM organizations WHERE deleted_at IS NULL")
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Organization")
    return None if row[0] is None else str(row[0])


async def _plan_tier(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    from apps.api.agents.llm_tiers import LLM_TIER_LABELS, resolve_tier_choice

    del actor
    parsed = parse_args(_TierArgs, args)
    current = await _org_model(session)
    chosen = None if parsed.tier == "default" else parsed.tier
    # The route's own refusal (a tier not switched on, or tiers not chosen here), at plan time.
    resolve_tier_choice(chosen, current_model=current, field="tier")
    proposed = "Calevate's default" if chosen is None else LLM_TIER_LABELS[chosen]
    return Plan(
        object_id="",
        title="Change the AI model your agents use",
        summary=(
            f"Agents that do not name their own model will use {proposed}. Live agents "
            "move to it after any call in progress."
        ),
        current=_tier_words(current),
        proposed=proposed,
        cost="The per-minute price follows the tier; the AI models screen shows each one.",
        reversal="Choose another tier at any time on the AI models screen.",
        args={"tier": parsed.tier},
    )


async def _execute_tier(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    from apps.api.agents.llm_routes import _locked_org_default, _write_default
    from apps.api.agents.llm_tiers import resolve_tier_choice

    parsed = parse_args(_TierArgs, args)
    current = await _locked_org_default(session)
    chosen = None if parsed.tier == "default" else parsed.tier
    model = resolve_tier_choice(chosen, current_model=current, field="tier")
    changed = await _write_default(session, tenant_id=actor.tenant_id, model=model)
    return Executed(
        applied=changed,
        detail="Done. Live agents follow after any call in progress."
        if changed
        else "The account already uses that, so nothing changed.",
        audit_summary={"default_llm_tier": chosen, "default_llm_model": model, "changed": changed},
    )


ACCOUNT_MODEL_TIER_SET: Final = ActionTool(
    name="account_model_tier_set",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="organization",
    audit_action="organization.llm_default_set",
    where="on the AI models screen",
    schema=action_schema(
        "account_model_tier_set",
        "The AI model tier every agent without its own uses; one agent: agent_settings_set."
        + PROPOSES_ONLY,
        {"tier": {"type": "string", "enum": ["standard", "plus", "pro", "default"]}},
    ),
    plan=_plan_tier,
    execute=_execute_tier,
)


# =========================================================================================
# TELL MY TEAM: ONE AGENT'S RULE
# =========================================================================================


class _AlertArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    team_contact_id: UUID | None
    on_outcomes: Annotated[list[Annotated[str, Field(max_length=200)]], Field(max_length=50)]
    #: `key=value`, one per watched answer; a flat list costs the shared area schema less
    #: than the screen's `{key, values}` objects and is grouped back into them here.
    on_answers: Annotated[list[Annotated[str, Field(max_length=250)]], Field(max_length=100)]
    in_call: bool


def _triggers(answers: list[str]) -> tuple[Any, ...]:
    from apps.api.team_alerts.service import MAX_FIELD_TRIGGERS, FieldTrigger

    grouped: dict[str, list[str]] = {}
    for answer in answers:
        key, sep, value = answer.partition("=")
        if not sep or not key.strip() or not value.strip():
            raise WriteRefusedError("each of `on_answers` is `key=value`")
        grouped.setdefault(key.strip(), []).append(value.strip())
    if len(grouped) > MAX_FIELD_TRIGGERS:
        raise WriteRefusedError(f"watch at most {MAX_FIELD_TRIGGERS} details")
    return tuple(FieldTrigger(k, tuple(dict.fromkeys(v))) for k, v in grouped.items())


def _rule_words(rule: Any, outcomes: Mapping[str, str], fields: Mapping[str, str]) -> str:
    parts = [f"after a call ending {outcomes.get(k, k)}" for k in rule.on_outcomes]
    parts += [f"when {fields.get(t.key, t.key)} is {' or '.join(t.values)}" for t in rule.on_fields]
    if rule.in_call:
        parts.append("during the call when the agent decides to")
    return "; ".join(parts) or "never"


async def _contact_words(session: AsyncSession, contact_id: UUID | None) -> str:
    if contact_id is None:
        return "the account's default team address"
    from apps.api.team_alerts.service import _live_contact

    contact = await _live_contact(session, contact_id)
    return _masked(contact.address) + ("" if contact.verified else " (not confirmed yet)")


async def _plan_alert(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    from apps.api.team_alerts.service import Rule, read_rule

    del actor
    parsed = parse_args(_AlertArgs, args)
    name = await _agent_name(session, parsed.agent_id)
    view = await read_rule(session, agent_id=parsed.agent_id)
    outcomes = {o.key: o.label for o in view.outcomes}
    fields = {f.key: f.label for f in view.fields}
    allowed = {f.key: set(f.values) for f in view.fields}
    unknown = [k for k in parsed.on_outcomes if k not in outcomes]
    if unknown:
        raise WriteRefusedError(
            "an outcome is not one of this agent's; take the keys from agent_settings handover"
        )
    on_fields = _triggers(parsed.on_answers)
    for trigger in on_fields:
        if trigger.key not in allowed or not set(trigger.values) <= allowed[trigger.key]:
            raise WriteRefusedError(
                "an answer is not one this agent records; take them from agent_settings handover"
            )
    wanted = Rule(
        contact_id=parsed.team_contact_id,
        on_outcomes=tuple(parsed.on_outcomes),
        on_fields=on_fields,
        in_call=parsed.in_call,
    )
    to = await _contact_words(session, parsed.team_contact_id)
    return Plan(
        object_id=str(parsed.agent_id),
        title="Tell your team about callers",
        summary=(
            f"“{name}” will tell {to}: {_rule_words(wanted, outcomes, fields)}. The message "
            "carries the caller's name, number and why."
        ),
        current=_rule_words(view.rule, outcomes, fields),
        proposed=_rule_words(wanted, outcomes, fields),
        cost=None,
        reversal="Change or clear it at any time on the agent's Settings tab.",
        args={
            "agent_id": str(parsed.agent_id),
            "team_contact_id": None
            if parsed.team_contact_id is None
            else str(parsed.team_contact_id),
            "on_outcomes": list(dict.fromkeys(parsed.on_outcomes)),
            "on_answers": [f"{t.key}={v}" for t in on_fields for v in t.values],
            "in_call": parsed.in_call,
        },
    )


async def _execute_alert(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    from apps.api.team_alerts.service import Rule, save_rule

    parsed = parse_args(_AlertArgs, args)
    await _agent_name(session, parsed.agent_id)
    rule = Rule(
        contact_id=parsed.team_contact_id,
        on_outcomes=tuple(parsed.on_outcomes),
        on_fields=_triggers(parsed.on_answers),
        in_call=parsed.in_call,
    )
    view = await save_rule(session, tenant_id=actor.tenant_id, agent_id=parsed.agent_id, rule=rule)
    return Executed(
        applied=True,
        detail="Saved."
        + (
            ""
            if view.sends_to is not None
            else " Nothing is sent until a team address is confirmed on the Alerts screen."
        ),
        audit_summary={
            "agent_id": str(parsed.agent_id),
            "outcomes": str(len(rule.on_outcomes)),
            "fields": str(len(rule.on_fields)),
            "in_call": str(rule.in_call),
            "own_contact": str(rule.contact_id is not None),
        },
    )


AGENT_TEAM_ALERT_SET: Final = ActionTool(
    name="agent_team_alert_set",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="agent",
    audit_action="agent.team_alert_set",
    where="on the agent's Settings tab",
    schema=action_schema(
        "agent_team_alert_set",
        "When one agent tells the team about a caller: the WHOLE rule. Keys and ids from "
        "agent_settings `handover`." + PROPOSES_ONLY,
        {
            "agent_id": {"type": "string"},
            "team_contact_id": _nullable({"type": "string"}),
            "on_outcomes": {"type": "array", "items": {"type": "string"}},
            "on_answers": {"type": "array", "items": {"type": "string"}},
            "in_call": {"type": "boolean"},
        },
    ),
    plan=_plan_alert,
    execute=_execute_alert,
)


# =========================================================================================
# TEAM ADDRESSES
# =========================================================================================

ContactAct = Literal["add", "remove", "make_default", "resend_code"]


class _ContactArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    act: ContactAct
    team_contact_id: UUID | None
    address: Annotated[str, Field(min_length=3, max_length=254)] | None


#: The audit action each act's own route writes (`team_alerts/routes.py`).
_CONTACT_AUDIT: Final[dict[str, str]] = {
    "remove": "team_alert.contact_removed",
    "make_default": "team_alert.contact_default",
    "resend_code": "team_alert.code_sent",
}

_CONTACT_TITLES: Final[dict[str, str]] = {
    "add": "Add a team address",
    "remove": "Stop telling a team address",
    "make_default": "Make this the team address agents use",
    "resend_code": "Send a new code to a team address",
}


async def _plan_contact(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    from apps.api.team_alerts.service import _live_contact

    del actor
    parsed = parse_args(_ContactArgs, args)
    if parsed.act == "add":
        if parsed.address is None or "@" not in parsed.address:
            raise WriteRefusedError(
                "`address` must be an email; a WhatsApp number is added on the Alerts screen"
            )
        address = parsed.address.strip().lower()
        return Plan(
            object_id="",
            title=_CONTACT_TITLES["add"],
            summary=(
                f"{_masked(address)} is added and sent a six-digit code. Nothing is sent "
                "to it until the code is typed on the Alerts screen."
            ),
            current=None,
            proposed=_masked(address),
            cost=None,
            reversal="Remove it on the Alerts screen at any time.",
            args={"act": "add", "team_contact_id": None, "address": address},
        )
    if parsed.team_contact_id is None:
        raise WriteRefusedError("`team_contact_id` is needed; take it from agent_settings handover")
    contact = await _live_contact(session, parsed.team_contact_id)
    shown = _masked(contact.address)
    summaries = {
        "remove": f"{shown} stops getting caller alerts; agents that used it use the default.",
        "make_default": f"Agents that name no address will tell {shown}.",
        "resend_code": f"A new code is sent to {shown}.",
    }
    return Plan(
        object_id=str(parsed.team_contact_id),
        title=_CONTACT_TITLES[parsed.act],
        summary=summaries[parsed.act],
        current=shown + (" (default)" if contact.is_default else ""),
        proposed=shown,
        cost=None,
        reversal="Add it again on the Alerts screen; it needs a new code."
        if parsed.act == "remove"
        else "Change it on the Alerts screen at any time.",
        args={"act": parsed.act, "team_contact_id": str(parsed.team_contact_id), "address": None},
    )


async def _execute_contact(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    from apps.api.team_alerts import service

    parsed = parse_args(_ContactArgs, args)
    if parsed.act == "add":
        assert parsed.address is not None
        contact = await service.add_contact(
            session, tenant_id=actor.tenant_id, address=parsed.address
        )
        return Executed(
            applied=True,
            detail="Added. A code was emailed to it; type it on the Alerts screen.",
            audit_summary={"act": "add"},
            audit_action="team_alert.contact_added",
            object_id=str(contact.id),
        )
    assert parsed.team_contact_id is not None
    if parsed.act == "remove":
        agents = await service.remove_contact(session, contact_id=parsed.team_contact_id)
        await service.resync_agents(session, agents)
        detail = "Removed."
    elif parsed.act == "make_default":
        await service.set_default(session, contact_id=parsed.team_contact_id)
        await service.resync_agents(session, await service.agents_with_rules(session))
        detail = "It is the default now."
    else:
        await service.resend_code(
            session, tenant_id=actor.tenant_id, contact_id=parsed.team_contact_id
        )
        detail = "A new code was sent."
    return Executed(
        applied=True,
        detail=detail,
        audit_summary={"act": parsed.act},
        audit_action=_CONTACT_AUDIT[parsed.act],
    )


TEAM_ALERT_CONTACT: Final = ActionTool(
    name="team_alert_contact",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="team_alert_contact",
    audit_action="team_alert.contact_changed",
    where="on the Alerts screen",
    schema=action_schema(
        "team_alert_contact",
        "Add an email the team is told about callers at, or remove, make default or resend "
        "the code of one." + PROPOSES_ONLY,
        {
            "act": {"type": "string", "enum": ["add", "remove", "make_default", "resend_code"]},
            "team_contact_id": _nullable({"type": "string"}),
            "address": _nullable({"type": "string"}),
        },
    ),
    plan=_plan_contact,
    execute=_execute_contact,
)


# =========================================================================================
# KNOWLEDGE: APPROVE A WAITING UPLOAD, OR READ A FILE OR PAGE AGAIN
# =========================================================================================


class _RefreshArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: str
    act: Literal["approve", "read_again"]


async def _upload_of(session: AsyncSession, ref: str) -> dict[str, Any]:
    from apps.api.kb import store, uploads

    try:
        kind, item_id = store.parse_ref(ref)
    except ProblemError:
        raise WriteRefusedError("`item` is not a reference from `knowledge_sources`") from None
    if kind in ("fact", "pinned_fact", "note", "profile", "rule") or item_id is None:
        raise WriteRefusedError("only a file, photo or link can be approved or read again")
    return await uploads.get_upload(session, item_id)


async def _plan_refresh(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    from apps.api.kb.models import READ_COPY_KINDS

    del actor
    parsed = parse_args(_RefreshArgs, args)
    row = await _upload_of(session, parsed.item)
    name = strip_invisible(str(row["name"]))
    if parsed.act == "approve":
        if row["review_state"] != "pending_approval":
            raise WriteRefusedError("that item is not waiting for approval")
        title, summary = "Approve knowledge", f"“{name}” goes to every agent."
    else:
        if row["source_kind"] not in READ_COPY_KINDS:
            raise WriteRefusedError("only a PDF or a web page is read again; send a file again")
        title, summary = "Read it again", f"“{name}” is read again and agents get the new copy."
    return Plan(
        object_id=str(row["id"]),
        title=title,
        summary=summary,
        current=str(row["review_state"] if parsed.act == "approve" else row["read_state"]),
        proposed="approved" if parsed.act == "approve" else "reading",
        cost=None,
        reversal="Remove it on the What your agents know screen if it should not be there.",
        args={"item": parsed.item, "act": parsed.act},
    )


async def _execute_refresh(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    from apps.api.kb import uploads
    from apps.api.kb.models import READ_COPY_KINDS
    from apps.api.kb.reading import queue_read

    parsed = parse_args(_RefreshArgs, args)
    row = await _upload_of(session, parsed.item)
    if parsed.act == "approve":
        await uploads.confirm_upload(
            session,
            tenant_id=actor.tenant_id,
            upload_id=row["id"],
            principal=_principal_of(actor),
        )
        detail = "Approved. Agents use it from the next call."
    else:
        if row["source_kind"] not in READ_COPY_KINDS:
            raise WriteRefusedError("only a PDF or a web page is read again")
        await queue_read(session, tenant_id=actor.tenant_id, source_id=row["source_id"], force=True)
        detail = "Reading it again; the screen shows when it is done."
    return Executed(
        applied=True,
        detail=detail,
        audit_summary={"upload_id": str(row["id"]), "act": parsed.act},
        audit_action="kb.approved" if parsed.act == "approve" else "kb.reread",
    )


KNOWLEDGE_REFRESH: Final = ActionTool(
    name="knowledge_refresh",
    tier="confirm",
    undo=None,
    permission=CURATE_PERMISSION,
    object_type="kb_upload",
    audit_action="kb.refreshed",
    where="on the What your agents know screen",
    schema=action_schema(
        "knowledge_refresh",
        "Approve a waiting file or link, or read a PDF or web page again." + PROPOSES_ONLY,
        {"item": {"type": "string"}, "act": {"type": "string", "enum": ["approve", "read_again"]}},
    ),
    plan=_plan_refresh,
    execute=_execute_refresh,
)


# =========================================================================================
# CONNECTED ACCOUNTS: DISCONNECT
# =========================================================================================


class _ConnectionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: UUID


async def _connection(session: AsyncSession, connection_id: UUID) -> Any:
    from apps.api.actions.credentials import list_credentials

    found = next((c for c in await list_credentials(session) if c.id == connection_id), None)
    if found is None:
        raise ProblemError.not_found("Connection")
    return found


async def _plan_disconnect(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    from apps.api.actions import service as actions_service

    del actor
    parsed = parse_args(_ConnectionArgs, args)
    found = await _connection(session, parsed.connection_id)
    agents = await actions_service.agents_using_credential(
        session, credential_id=parsed.connection_id
    )
    label = strip_invisible(str(found.label))
    return Plan(
        object_id=str(parsed.connection_id),
        title="Disconnect an account",
        summary=(
            f"“{label}” is disconnected. In-call actions that use it stop on "
            f"{len(agents)} agent(s); callers are told it cannot help right now."
        ),
        current=f"{label} ({found.kind}), connected",
        proposed="disconnected",
        cost=None,
        reversal="Connect it again on the Integrations screen; you sign in again.",
        args={"connection_id": str(parsed.connection_id)},
    )


async def _execute_disconnect(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    from apps.api.actions import credentials as creds
    from apps.api.actions import service as actions_service
    from apps.api.actions.routes import _resync, _revoke_at_vendor

    parsed = parse_args(_ConnectionArgs, args)
    agents = await actions_service.agents_using_credential(
        session, credential_id=parsed.connection_id
    )
    try:
        resolved = await creds.resolve_credential(
            session, tenant_id=actor.tenant_id, credential_id=parsed.connection_id
        )
    except creds.CredentialUnusableError:
        resolved = None
    if not await creds.delete_credential(session, credential_id=parsed.connection_id):
        raise ProblemError.not_found("Connection")
    await _resync(session, agents)
    await _revoke_at_vendor(resolved)
    return Executed(
        applied=True,
        detail="Disconnected.",
        audit_summary={"agents_resynced": len(agents)},
    )


CONNECTION_DISCONNECT: Final = ActionTool(
    name="connection_disconnect",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="integration_credential",
    audit_action="integration_credential.deleted",
    where="on the Integrations screen",
    schema=action_schema(
        "connection_disconnect",
        "Disconnect a connected account (ids: integrations_status)." + PROPOSES_ONLY,
        {"connection_id": {"type": "string"}},
    ),
    plan=_plan_disconnect,
    execute=_execute_disconnect,
)


# =========================================================================================
# THE OWNER'S SWITCHES
# =========================================================================================

Switch = Literal["staff_knowledge", "opt_in_before_calling", "save_number_whatsapp"]

_SWITCH_WORDS: Final[dict[str, tuple[str, str, str, str]]] = {
    # (what it is, where it lives, what on means, what off means)
    "staff_knowledge": (
        "Staff may add and change knowledge",
        "on the What your agents know screen",
        "Members with the staff role can add knowledge; it reaches agents without review.",
        "Only the owner can add or change knowledge.",
    ),
    "opt_in_before_calling": (
        "Only call people who opted in",
        "on the Messaging consent screen",
        "A number with no opt-in on file is refused rather than dialled.",
        "Numbers are no longer checked for an opt-in before they are dialled.",
    ),
    "save_number_whatsapp": (
        "Ask callers who book to save your number",
        "on the Phone numbers screen",
        "Callers who book, and opted in to messages, get one WhatsApp naming your number.",
        "Callers who book are not sent the save-our-number WhatsApp.",
    ),
}


#: The audit action each switch's own route writes, so the log reads the same either way.
_SWITCH_AUDIT: Final[dict[str, str]] = {
    "staff_knowledge": "organization.staff_kb_curation_set",
    "opt_in_before_calling": "organization.outbound_consent_policy_set",
    "save_number_whatsapp": "forwarding.save_number_switched",
}


class _SwitchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    switch: Switch
    on: bool


async def _read_switch(session: AsyncSession, switch: str) -> bool:
    if switch == "staff_knowledge":
        from apps.api.kb.curation import read_switch

        return await read_switch(session)
    if switch == "opt_in_before_calling":
        from apps.api.compliance.consent_policy import read_policy

        return await read_policy(session)
    from apps.api.forwarding.save_number import read_switch as read_save

    return await read_save(session)


async def _write_switch(session: AsyncSession, switch: str, on: bool) -> bool:
    if switch == "staff_knowledge":
        from apps.api.kb.curation import write_switch

        return await write_switch(session, enabled=on)
    if switch == "opt_in_before_calling":
        from apps.api.compliance.consent_policy import write_policy

        return await write_policy(session, enabled=on)
    from apps.api.forwarding.save_number import write_switch as write_save

    return await write_save(session, enabled=on)


async def _plan_switch(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    parsed = parse_args(_SwitchArgs, args)
    label, where, on_words, off_words = _SWITCH_WORDS[parsed.switch]
    current = await _read_switch(session, parsed.switch)
    return Plan(
        object_id="",
        title=f"{label}: {'on' if parsed.on else 'off'}",
        summary=on_words if parsed.on else off_words,
        current="on" if current else "off",
        proposed="on" if parsed.on else "off",
        cost=None,
        reversal=f"Switch it back {where}.",
        args={"switch": parsed.switch, "on": parsed.on},
    )


async def _execute_switch(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    del actor
    parsed = parse_args(_SwitchArgs, args)
    changed = await _write_switch(session, parsed.switch, parsed.on)
    return Executed(
        applied=changed,
        detail=("Switched " + ("on." if parsed.on else "off."))
        if changed
        else f"It was already {'on' if parsed.on else 'off'}.",
        audit_summary={"switch": parsed.switch, "on": parsed.on, "changed": changed},
        audit_action=_SWITCH_AUDIT[parsed.switch],
    )


def _save_number_code(args: Mapping[str, Any]) -> str | None:
    """`forwarding/routes.put_save_number` demands `save_number_message:<org>` from its
    button; the other two switches' routes ask for no code."""
    from apps.api.forwarding.routes import SAVE_NUMBER_ACTION

    if args.get("switch") != "save_number_whatsapp":
        return None
    return f"{SAVE_NUMBER_ACTION}:{{org}}"


ACCOUNT_SWITCH_SET: Final = ActionTool(
    name="account_switch_set",
    tier="confirm",
    undo=None,
    action_code=_save_number_code,
    permission="org:manage",
    object_type="organization",
    audit_action="organization.switch_set",
    where="on that switch's own screen",
    schema=action_schema(
        "account_switch_set",
        "Turn an owner switch on or off." + PROPOSES_ONLY,
        {
            "switch": {
                "type": "string",
                "enum": ["staff_knowledge", "opt_in_before_calling", "save_number_whatsapp"],
            },
            "on": {"type": "boolean"},
        },
    ),
    plan=_plan_switch,
    execute=_execute_switch,
)


#: Appended to `WRITE_TOOLS` in this order (wire order).
COVERAGE_ACTIONS: Final[tuple[ActionTool, ...]] = (
    ACCOUNT_MODEL_TIER_SET,
    AGENT_TEAM_ALERT_SET,
    TEAM_ALERT_CONTACT,
    KNOWLEDGE_REFRESH,
    CONNECTION_DISCONNECT,
    ACCOUNT_SWITCH_SET,
)


# =========================================================================================
# READS (client realm only, `service.realm_read_tools`)
# =========================================================================================


async def _connection_check(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """`POST /v1/integrations/credentials/{id}/test`'s own function: a proof that sends
    nothing to anyone (a payment key lists one payment, a sign-in mints a token) and writes
    nothing here, which is what lets it be a read."""
    from apps.api.actions.routes import test_credential
    from apps.api.core.context import Principal

    try:
        connection_id = UUID(str(args.get("connection_id")))
    except ValueError:
        return "`connection_id` is not an id; take it from integrations_status."
    assert context.tenant_id is not None
    principal = Principal(
        realm="client", user_id=context.user_id, tenant_id=context.tenant_id, role=context.role
    )
    try:
        result = await test_credential(connection_id, session, principal)
    except ProblemError:
        return "No connection with that id in this account."
    return ("Works: " if result.ok else "Does not work: ") + result.message


CONNECTION_CHECK: Final = ReadTool(
    name="connection_check",
    description="Check one connected account still works; sends nothing.",
    parameters={
        "type": "object",
        "properties": {"connection_id": {"type": "string"}},
        "required": ["connection_id"],
        "additionalProperties": False,
    },
    # The route's own permission: the check opens the stored secret to prove it.
    permission="org:manage",
    run=_connection_check,
)

#: Composed into the CLIENT realm's reads only, after the routines read.
COVERAGE_READS: Final[tuple[ReadTool, ...]] = (HELP_LOOKUP, CONNECTION_CHECK)

__all__ = ["COVERAGE_ACTIONS", "COVERAGE_READS"]
