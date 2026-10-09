"""The ADMIN assistant's own actions (D-694): what an operator may ask it to do.

The client action tools (`write_tools.WRITE_TOOLS`) act inside ONE account under that
account's RLS session, as a `users.id`. An operator is an `admin_users.id` acting on
platform state, so the admin realm gets its own small registry with its own actor type, and
the same two rules as the client one:

* every action states its tier, and only `confirm` exists here today — the first admin
  action is a stop button for the whole platform;
* an action whose button on the console asks for step-up asks for it here too. The
  proposal carries the confirmation string the button would send (`confirm_action`), and
  `POST /v1/admin/copilot/confirm` demands both halves of step-up — that header and a
  fresh second factor — exactly as `POST /v1/ops/platform` does.

THE PROPOSAL TOKEN IS THE CLIENT ONE'S SHAPE UNDER A DIFFERENT AUDIENCE. `sub` is the fixed
string `platform` rather than a tenant, `act.sub` is the operator, and the audience is
`calevate:admin-copilot-proposal`, so a client token cannot be confirmed here and an admin
token cannot be confirmed on the client door. The `jti` burn is the same Redis marker.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID

import jwt
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.copilot import action_log
from apps.api.copilot.actions import (
    PROPOSES_ONLY,
    ActionTier,
    Executed,
    Plan,
    WriteRefusedError,
    action_schema,
    parse_args,
)
from apps.api.copilot.sanitize import strip_invisible
from apps.api.copilot.schemas import CopilotConfirmOut, CopilotProposalEvent
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.loadshed import set_platform_status
from apps.api.core.logging import get_logger
from apps.api.core.rbac import Permission, role_has
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.ops.halt import queue_dial_recall
from apps.api.ops.routes import platform_confirmation
from apps.api.ops.service import read_halt_state

log = get_logger(__name__)

#: The admin proposal's audience. Distinct from `write_tools.PROPOSAL_AUDIENCE`, so neither
#: realm's door accepts the other's token.
ADMIN_PROPOSAL_AUDIENCE: Final = "calevate:admin-copilot-proposal"

#: `sub` on every admin token: the platform, not a tenant.
PLATFORM_SUBJECT: Final = "platform"


@dataclass(frozen=True, slots=True)
class AdminActor:
    """Who an admin action runs for. Ids only (hard rule 6)."""

    admin_user_id: UUID
    role: str
    viewing_tenant_id: UUID | None


def admin_actor_for(principal: Principal, *, viewing_tenant_id: UUID | None) -> AdminActor | None:
    """The admin actor behind this principal, or None.

    An IMPERSONATING operator is refused here: inside a view-as session the operator is
    acting as the client's console, and platform actions do not belong to that session.
    """
    if (
        principal.realm != "admin"
        or principal.impersonating
        or principal.user_id is None
        or principal.role is None
    ):
        return None
    return AdminActor(
        admin_user_id=principal.user_id,
        role=principal.role,
        viewing_tenant_id=viewing_tenant_id,
    )


AdminPlanner = Callable[[AsyncSession, AdminActor, Mapping[str, Any]], Awaitable[Plan]]
AdminExecutor = Callable[[AsyncSession, AdminActor, Mapping[str, Any]], Awaitable[Executed]]


@dataclass(frozen=True, slots=True)
class AdminActionTool:
    """One action the admin assistant can take. `tier` has no default (D-694)."""

    name: str
    tier: ActionTier
    permission: Permission
    object_type: str
    audit_action: str
    schema: Mapping[str, Any]
    plan: AdminPlanner
    execute: AdminExecutor
    where: str
    #: The `X-Confirm-Action` value the equivalent BUTTON demands, computed from the
    #: canonical arguments, or None when the button asks for no step-up.
    confirm_action: Callable[[Mapping[str, Any]], str] | None
    #: WHICH SESSION the plan, the execution and the audit row run in (D-698). `platform`
    #: is an untenanted session for platform state. `tenant` is the account whose page the
    #: operator has open (`viewing_tenant_id`), entered with its own `tenant_session` — the
    #: way the console's per-client admin routes do it, so RLS isolates the work rather
    #: than a WHERE clause — and refused when no account is open.
    scope: Literal["platform", "tenant"] = "platform"

    def __post_init__(self) -> None:
        if self.tier != "confirm":
            raise ValueError(
                f"{self.name}: the admin realm has no Undo framework for its own actions yet, "
                "so every admin action is `confirm`"
            )


# --- platform_halt_outbound -------------------------------------------------------------


class _HaltArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=300)


async def _plan_halt(session: AsyncSession, actor: AdminActor, args: Mapping[str, Any]) -> Plan:
    """READ ONLY: the switch's current position, so the card says whether this changes it."""
    del actor
    parsed = parse_args(_HaltArgs, args)
    reason = strip_invisible(parsed.reason.strip())
    if not reason:
        raise WriteRefusedError("a halt needs a short reason, so ask the operator for one")
    state = await read_halt_state(session)
    current = "Halted" if state.outbound_halted else "Dialling normally"
    return Plan(
        object_id="1",
        title="Stop all outbound calling",
        summary=(
            "Halt outbound dialling for every client on the platform, and pull back calls "
            f"already queued. Outbound is {current.lower()} right now. Inbound answering "
            "is not affected."
        ),
        current=current,
        proposed="Halted",
        cost=None,
        reversal=(
            "Releasing the halt is a separate step on the Operations screen. Queued calls "
            "that were pulled back are not put back."
        ),
        args={"reason": reason},
    )


async def _execute_halt(
    session: AsyncSession, actor: AdminActor, args: Mapping[str, Any]
) -> Executed:
    """`set_platform_status` and the recall — what `POST /v1/ops/platform` does for a halt."""
    parsed = parse_args(_HaltArgs, args)
    before = await read_halt_state(session)
    await set_platform_status(
        outbound_halted=True, halt_reason=parsed.reason, actor_id=str(actor.admin_user_id)
    )
    await queue_dial_recall()
    return Executed(
        applied=not before.outbound_halted,
        detail=(
            "Outbound dialling is halted for every client, and queued calls are being pulled back."
            if not before.outbound_halted
            else "Outbound dialling was already halted. Queued calls are being pulled back again."
        ),
        audit_summary={"outbound_halted": True, "reason": parsed.reason},
    )


PLATFORM_HALT_OUTBOUND: Final = AdminActionTool(
    name="platform_halt_outbound",
    tier="confirm",
    # `POST /v1/ops/platform`'s permission, which only a superadmin holds.
    permission="ops:manage",
    object_type="platform_state",
    # The button's own audit action, so one query finds every halt however it was thrown.
    audit_action="ops.halt_outbound",
    where="on the Operations screen",
    schema=action_schema(
        "platform_halt_outbound",
        "Propose halting ALL outbound calling on the platform (the big red switch), for "
        "example during an incident. It needs the operator's second factor when they "
        "confirm. Releasing a halt is not something you can do." + PROPOSES_ONLY,
        {
            "reason": {
                "type": "string",
                "description": "Why, in the operator's own words — shown on the ops screen.",
            }
        },
    ),
    plan=_plan_halt,
    execute=_execute_halt,
    confirm_action=lambda args: platform_confirmation(outbound_halted=True, load_shed_mode=None),
)

# --- D-698: the per-client actions an operator takes from a client's page ----------------
#
# Each is `scope="tenant"`: it acts on the account whose page is open and runs in that
# account's own session, exactly as its console route does. None of their buttons asks for
# step-up, so none does here (`confirm_action=None`); the halt above keeps its own.


async def _client_name(session: AsyncSession, tenant_id: UUID) -> str:
    from sqlalchemy import text

    row = (
        await session.execute(
            text("SELECT name FROM organizations WHERE id = :t"), {"t": tenant_id}
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Client")
    return strip_invisible(str(row[0]))


def _viewing(actor: AdminActor) -> UUID:
    assert actor.viewing_tenant_id is not None  # `scope="tenant"` refuses without one
    return actor.viewing_tenant_id


class _KycReviewArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    document_ref: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=500)
    pan_checked: bool


async def _plan_kyc_review(
    session: AsyncSession, actor: AdminActor, args: Mapping[str, Any]
) -> Plan:
    from apps.api.compliance.kyc_review import assert_awaiting_review

    parsed = parse_args(_KycReviewArgs, args)
    tenant_id = _viewing(actor)
    record = await assert_awaiting_review(session, tenant_id=tenant_id)
    name = await _client_name(session, tenant_id)
    reason = None if parsed.reason is None else (strip_invisible(parsed.reason.strip()) or None)
    if parsed.decision == "reject" and not reason:
        raise WriteRefusedError("a rejection needs the reason the client will be shown")
    if parsed.decision == "approve" and record.kyc_path == "manual" and not parsed.pan_checked:
        raise WriteRefusedError(
            "approving a document review needs the operator to have matched the PAN, name and "
            "date of birth at the Income Tax 'Verify Your PAN' service — ask them, and only "
            "pass `pan_checked: true` if they say it matched"
        )
    return Plan(
        object_id=str(tenant_id),
        title="Approve this client's verification"
        if parsed.decision == "approve"
        else "Reject this client's verification",
        summary=(
            f"Mark {name}'s business verification as verified"
            + (", recording that you matched the PAN at Income Tax" if parsed.pan_checked else "")
            + ". Outbound calling then depends only on the pledge and the other checks."
            if parsed.decision == "approve"
            else f"Reject {name}'s verification and show them: “{reason}”."
        )
        + " The owner's ID file is deleted either way.",
        current=str(record.status),
        proposed="verified" if parsed.decision == "approve" else "rejected",
        cost=None,
        reversal="A decision is not reopened here; the client resubmits to be reviewed again.",
        args={
            "decision": parsed.decision,
            "document_ref": parsed.document_ref,
            "reason": reason,
            "pan_checked": parsed.pan_checked,
        },
    )


async def _execute_kyc_review(
    session: AsyncSession, actor: AdminActor, args: Mapping[str, Any]
) -> Executed:
    """`kyc_review.decide_kyc_review` — the review screen's own decision. The owner-ID file
    whose deletion it requests is removed by `workers/kyc_owner_id_purge` on its next tick
    (the screen also asks a background task to do it at once)."""
    from apps.api.compliance.kyc_review import decide_kyc_review, review_audit_summary

    parsed = parse_args(_KycReviewArgs, args)
    outcome = await decide_kyc_review(
        session,
        tenant_id=_viewing(actor),
        decision=parsed.decision,
        document_ref=parsed.document_ref,
        reason=parsed.reason,
        pan_checked=parsed.pan_checked,
        admin_id=actor.admin_user_id,
    )
    return Executed(
        applied=True,
        detail=(
            "The verification is approved."
            if parsed.decision == "approve"
            else "The verification is rejected; the client sees the reason."
        ),
        audit_summary=dict(review_audit_summary(outcome, decision=parsed.decision)),
    )


ADMIN_KYC_REVIEW: Final = AdminActionTool(
    name="admin_kyc_review",
    tier="confirm",
    permission="admin:tenants",
    object_type="kyc_record",
    audit_action="kyc.reviewed",
    where="on the client's Identity review page",
    schema=action_schema(
        "admin_kyc_review",
        "Propose approving or rejecting the open client's business verification. Approving "
        "a document review needs the operator to say they matched the PAN at Income Tax; "
        "rejecting needs the reason the client will read." + PROPOSES_ONLY,
        {
            "decision": {"type": "string", "enum": ["approve", "reject"]},
            "document_ref": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": (
                    "The registry number checked (CIN, LLPIN, Udyam), or null for the "
                    "GSTIN on file."
                ),
            },
            "reason": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "For a rejection, what was wrong, in words the client can act on.",
            },
            "pan_checked": {
                "type": "boolean",
                "description": (
                    "True only if the operator said the PAN details matched at Income Tax."
                ),
            },
        },
    ),
    plan=_plan_kyc_review,
    execute=_execute_kyc_review,
    confirm_action=None,
    scope="tenant",
)


class _FirstCampaignArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    note: str = Field(min_length=3, max_length=2000)


async def _plan_first_campaign(
    session: AsyncSession, actor: AdminActor, args: Mapping[str, Any]
) -> Plan:
    from apps.api.compliance.first_campaign import read_first_campaign_review

    parsed = parse_args(_FirstCampaignArgs, args)
    note = strip_invisible(parsed.note.strip())
    if len(note) < 3:
        raise WriteRefusedError("the decision needs a note saying what was reviewed")
    tenant_id = _viewing(actor)
    name = await _client_name(session, tenant_id)
    review = await read_first_campaign_review(session, tenant_id=tenant_id)
    return Plan(
        object_id=str(tenant_id),
        title="Release this client's campaign calling"
        if parsed.decision == "approved"
        else "Keep this client's campaign calling held",
        summary=(
            f"{'Release' if parsed.decision == 'approved' else 'Hold'} {name}'s campaigns, "
            f"recording: “{note}”."
            + (
                " Their campaigns can then launch."
                if parsed.decision == "approved"
                else " They are shown why."
            )
        ),
        current=review.status or "not reviewed",
        proposed=parsed.decision,
        cost=None,
        reversal="The decision can be changed again from the client's page.",
        args={"decision": parsed.decision, "note": note},
    )


async def _execute_first_campaign(
    session: AsyncSession, actor: AdminActor, args: Mapping[str, Any]
) -> Executed:
    """`record_first_campaign_decision` — the first-campaign review button's call."""
    from apps.api.compliance.first_campaign import record_first_campaign_decision

    parsed = parse_args(_FirstCampaignArgs, args)
    await record_first_campaign_decision(
        session,
        tenant_id=_viewing(actor),
        status=parsed.decision,
        note=parsed.note,
        decided_by_admin_id=actor.admin_user_id,
    )
    return Executed(
        applied=True,
        detail="Recorded. The client's campaigns are "
        + ("released." if parsed.decision == "approved" else "still held."),
        audit_summary={
            "decision": parsed.decision,
            "note": parsed.note,
            "reviewed_campaign_id": None,
        },
    )


ADMIN_FIRST_CAMPAIGN_DECIDE: Final = AdminActionTool(
    name="admin_first_campaign_decide",
    tier="confirm",
    permission="admin:tenants",
    object_type="first_campaign_review",
    audit_action="first_campaign_review.decided",
    where="on the client's page, under its holds",
    schema=action_schema(
        "admin_first_campaign_decide",
        "Propose releasing (or keeping held) the open client's campaign calling after their "
        "first campaign was reviewed. The note says what was looked at." + PROPOSES_ONLY,
        {
            "decision": {"type": "string", "enum": ["approved", "rejected"]},
            "note": {"type": "string", "description": "What was reviewed, or what was wrong."},
        },
    ),
    plan=_plan_first_campaign,
    execute=_execute_first_campaign,
    confirm_action=None,
    scope="tenant",
)


class _NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


async def _plan_workspace_provision(
    session: AsyncSession, actor: AdminActor, args: Mapping[str, Any]
) -> Plan:
    from apps.api.tenancy.engine_workspace import engine_has_workspaces, read_workspace_state

    parse_args(_NoArgs, args)
    if not engine_has_workspaces():
        raise WriteRefusedError("this deployment's voice platform has no per-client workspaces")
    tenant_id = _viewing(actor)
    name = await _client_name(session, tenant_id)
    state = await read_workspace_state(session, tenant_id)
    return Plan(
        object_id=str(tenant_id),
        title="Set up this client's voice workspace again",
        summary=(
            f"Queue {name}'s own voice-platform workspace to be provisioned again "
            f"(it is {state.status})."
        ),
        current=str(state.status),
        proposed="queued for provisioning",
        cost=None,
        reversal="Provisioning is idempotent; nothing is removed by running it again.",
        args={},
    )


async def _execute_workspace_provision(
    session: AsyncSession, actor: AdminActor, args: Mapping[str, Any]
) -> Executed:
    """`queue_workspace_provisioning` — the console's Provision again button's call."""
    from apps.api.tenancy.engine_workspace import queue_workspace_provisioning

    del args
    queued = await queue_workspace_provisioning(session, tenant_id=_viewing(actor))
    return Executed(
        applied=bool(queued),
        detail="Provisioning is queued." if queued else "It was already queued.",
        audit_summary={"queued": str(queued)},
    )


ADMIN_WORKSPACE_PROVISION: Final = AdminActionTool(
    name="admin_workspace_provision",
    tier="confirm",
    permission="admin:tenants",
    object_type="organization",
    audit_action="engine_workspace.provision_requested",
    where="on the client's page, under Voice workspace",
    schema=action_schema(
        "admin_workspace_provision",
        "Propose provisioning the open client's own voice-platform workspace again, after a "
        "plan upgrade or a fix." + PROPOSES_ONLY,
        {},
    ),
    plan=_plan_workspace_provision,
    execute=_execute_workspace_provision,
    confirm_action=None,
    scope="tenant",
)


class _AdminNumberArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number_id: UUID


async def _plan_admin_number_release(
    session: AsyncSession, actor: AdminActor, args: Mapping[str, Any]
) -> Plan:
    from sqlalchemy import text

    from apps.api.tenancy.engine_workspace import engine_has_workspaces
    from apps.workers.redaction import redact

    parsed = parse_args(_AdminNumberArgs, args)
    if not engine_has_workspaces():
        raise WriteRefusedError("this deployment's voice platform has no per-client workspaces")
    name = await _client_name(session, _viewing(actor))
    row = (
        await session.execute(
            text("SELECT e164 FROM phone_numbers WHERE id = :nid AND released_at IS NULL"),
            {"nid": parsed.number_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Phone number")
    masked = redact(str(row[0])).text
    return Plan(
        object_id=str(parsed.number_id),
        title="Release this client's number",
        summary=f"Give up {masked} for {name}. Calls to it stop reaching their agents.",
        current=masked,
        proposed="Released",
        cost="The month already paid is not refunded.",
        reversal="A released number cannot be recovered.",
        args={"number_id": str(parsed.number_id)},
    )


async def _execute_admin_number_release(
    session: AsyncSession, actor: AdminActor, args: Mapping[str, Any]
) -> Executed:
    """`release_engine_number(by_admin=True)` — the admin numbers panel's Release."""
    from apps.api.campaigns.engine_number_purchase import release_engine_number

    parsed = parse_args(_AdminNumberArgs, args)
    released = await release_engine_number(
        session, tenant_id=_viewing(actor), number_id=parsed.number_id, by_admin=True
    )
    return Executed(
        applied=released,
        detail="The number is released." if released else "It was already released.",
        audit_summary={"refunded": False},
    )


ADMIN_NUMBER_RELEASE: Final = AdminActionTool(
    name="admin_number_release",
    tier="confirm",
    permission="admin:tenants",
    object_type="phone_number",
    audit_action="number.released",
    where="on the client's page, under Numbers",
    schema=action_schema(
        "admin_number_release",
        "Propose releasing one of the open client's phone numbers for good (take the id from "
        "`numbers_list`)." + PROPOSES_ONLY,
        {"number_id": {"type": "string", "description": "From `numbers_list`."}},
    ),
    plan=_plan_admin_number_release,
    execute=_execute_admin_number_release,
    confirm_action=None,
    scope="tenant",
)


class _VoiceCurationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_id: str = Field(min_length=1, max_length=200)
    state: Literal["enabled", "disabled", "archived"]


async def _plan_voice_curation(
    session: AsyncSession, actor: AdminActor, args: Mapping[str, Any]
) -> Plan:
    from apps.api.agents.voice_curation import list_curated_voices

    del actor
    parsed = parse_args(_VoiceCurationArgs, args)
    voices = {row.voice.id: row for row in await list_curated_voices(session, scope="all")}
    row = voices.get(parsed.voice_id)
    if row is None:
        raise WriteRefusedError(
            "no voice in the catalogue has that id; look it up with `admin_voices`"
        )
    label = strip_invisible(row.voice.label)
    return Plan(
        object_id=parsed.voice_id,
        title="Change whether clients may choose this voice",
        summary=(
            f"Set “{label}” to {parsed.state} for every client. {row.live_agents} agent(s) "
            "speak it now and keep speaking it; only the picker changes."
        ),
        current=row.state,
        proposed=parsed.state,
        cost=None,
        reversal="Set it back the same way on the Voices screen.",
        args={"voice_id": parsed.voice_id, "state": parsed.state},
    )


async def _execute_voice_curation(
    session: AsyncSession, actor: AdminActor, args: Mapping[str, Any]
) -> Executed:
    """`voice_curation.set_curation_state` — `PATCH /v1/ops/voices`'s call."""
    from apps.api.agents.voice_curation import set_curation_state

    del actor
    parsed = parse_args(_VoiceCurationArgs, args)
    row = await set_curation_state(session, voice_id=parsed.voice_id, state=parsed.state)
    return Executed(
        applied=True,
        detail=f"The voice is now {row.state}.",
        audit_summary={
            "voice_id": parsed.voice_id,
            "state": parsed.state,
            "live_agents": row.live_agents,
        },
    )


ADMIN_VOICE_SET: Final = AdminActionTool(
    name="admin_voice_set",
    tier="confirm",
    permission="ops:manage",
    object_type="platform_voice_catalog",
    audit_action="ops.voice_curation_set",
    where="on the Voices screen",
    schema=action_schema(
        "admin_voice_set",
        "Propose enabling, disabling or archiving one voice for every client's picker. Agents "
        "already using it are not changed." + PROPOSES_ONLY,
        {
            "voice_id": {"type": "string", "description": "From `admin_voices`."},
            "state": {"type": "string", "enum": ["enabled", "disabled", "archived"]},
        },
    ),
    plan=_plan_voice_curation,
    execute=_execute_voice_curation,
    confirm_action=None,
)


#: Registration order is wire order. New actions APPEND.
ADMIN_ACTIONS: Final[tuple[AdminActionTool, ...]] = (
    PLATFORM_HALT_OUTBOUND,
    ADMIN_KYC_REVIEW,
    ADMIN_FIRST_CAMPAIGN_DECIDE,
    ADMIN_WORKSPACE_PROVISION,
    ADMIN_NUMBER_RELEASE,
    ADMIN_VOICE_SET,
)

_BY_NAME: Final[dict[str, AdminActionTool]] = {tool.name: tool for tool in ADMIN_ACTIONS}


def admin_action_schemas() -> list[dict[str, Any]]:
    return [dict(tool.schema) for tool in ADMIN_ACTIONS]


def admin_tool_named(name: str) -> AdminActionTool | None:
    return _BY_NAME.get(name)


def is_admin_action(name: str) -> bool:
    return name in _BY_NAME


async def _may(actor: AdminActor, permission: Permission) -> bool:
    return role_has(actor.role, permission)


async def plan_admin_action(
    name: str, raw_arguments: str, *, principal: Principal | None, viewing_tenant_id: UUID | None
) -> CopilotProposalEvent:
    """One admin action call → one signed proposal. READS ONLY. Mirrors `plan_write`."""
    # Imported here: `write_tools` imports the agent actions, which import nothing of this
    # module, but sharing its key and constants at module level would be a cycle the day
    # write_tools needs an admin import.
    from apps.api.copilot import write_tools

    tool = _BY_NAME.get(name)
    if tool is None:  # pragma: no cover - the loop only routes registered names here
        raise WriteRefusedError(f"`{name}` is not a tool you have")
    actor = (
        None
        if principal is None
        else admin_actor_for(principal, viewing_tenant_id=viewing_tenant_id)
    )
    if actor is None:
        raise WriteRefusedError(
            f"`{name}` is a platform action and this session cannot take one — inside a "
            "view-as session, platform actions are not available"
        )
    if not await _may(actor, tool.permission):
        raise WriteRefusedError(
            f"this operator's role may not do what `{name}` proposes, so do not offer it"
        )
    try:
        parsed = json.loads(raw_arguments or "")
    except ValueError as exc:
        raise WriteRefusedError("the tool call was not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise WriteRefusedError("the tool call was not an object")
    if tool.scope == "tenant":
        if viewing_tenant_id is None:
            raise WriteRefusedError(
                f"`{name}` acts on one client's account and no client's page is open — tell "
                "the operator to open that client's page first"
            )
        async with tenant_session(viewing_tenant_id) as session:
            plan = await tool.plan(session, actor, parsed)
    else:
        async with untenanted_session() as session:
            plan = await tool.plan(session, actor, parsed)
    issued_at = datetime.now(UTC)
    expires_at = (issued_at + write_tools.PROPOSAL_TTL).replace(microsecond=0)
    claims: dict[str, Any] = {
        "aud": ADMIN_PROPOSAL_AUDIENCE,
        "sub": PLATFORM_SUBJECT,
        write_tools.ACTOR_CLAIM: {"sub": str(actor.admin_user_id)},
        "jti": str(uuid7()),
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "tool": tool.name,
        "args": plan.args,
        "obj": plan.object_id,
        "viewing": None if viewing_tenant_id is None else str(viewing_tenant_id),
    }
    return CopilotProposalEvent(
        token=jwt.encode(
            claims, write_tools.signing_key(), algorithm=write_tools.PROPOSAL_ALGORITHM
        ),
        tool=tool.name,
        title=strip_invisible(plan.title),
        summary=strip_invisible(plan.summary),
        object_type=tool.object_type,
        object_id=plan.object_id,
        current=None if plan.current is None else strip_invisible(plan.current),
        proposed=strip_invisible(plan.proposed),
        cost=None if plan.cost is None else strip_invisible(plan.cost),
        reversal=strip_invisible(plan.reversal),
        expires_at=expires_at,
        confirm_action=None if tool.confirm_action is None else tool.confirm_action(plan.args),
    )


def _refused(detail: str) -> ProblemError:
    return ProblemError(
        kind="permission",
        code="copilot_proposal_invalid",
        title="That change could not be confirmed",
        detail=detail,
        remediation="Ask the assistant again — nothing has been changed.",
    )


async def _execute_and_audit(
    session: AsyncSession,
    tool: AdminActionTool,
    actor: AdminActor,
    args: Mapping[str, Any],
    *,
    principal: Principal,
    tenant_id: UUID | None,
    object_id: str | None,
    ip: str | None,
) -> Executed:
    executed = await tool.execute(session, actor, args)
    await write_audit(
        session,
        action=tool.audit_action,
        actor=principal,
        tenant_id=tenant_id,
        object_type=tool.object_type,
        object_id=object_id,
        ip=ip,
        summary={"via": "copilot", "tool": tool.name, **executed.audit_summary},
    )
    return executed


async def confirm_admin(
    session: AsyncSession,
    token: str,
    *,
    principal: Principal,
    require_step_up: Callable[[str], None],
    ip: str | None,
) -> CopilotConfirmOut:
    """Verify, re-check, step-up, burn, execute, audit, log — `write_tools.confirm`'s order."""
    from apps.api.copilot import write_tools

    try:
        claims = jwt.decode(
            token,
            write_tools.signing_key(),
            algorithms=[write_tools.PROPOSAL_ALGORITHM],
            audience=ADMIN_PROPOSAL_AUDIENCE,
            leeway=write_tools.PROPOSAL_CLOCK_SKEW_S,
            options={"require": ["exp", "iat", "jti", "sub", "aud", "act", "tool", "args"]},
        )
    except jwt.PyJWTError as exc:
        log.info("admin_copilot_proposal_rejected", extra={"error": type(exc).__name__})
        raise _refused("This suggestion is no longer valid.") from exc
    tool = _BY_NAME.get(str(claims.get("tool")))
    act = claims.get(write_tools.ACTOR_CLAIM)
    if tool is None or claims.get("sub") != PLATFORM_SUBJECT:
        raise _refused("This suggestion refers to something the assistant can no longer do.")
    viewing_raw = claims.get("viewing")
    viewing = UUID(viewing_raw) if isinstance(viewing_raw, str) else None
    actor = admin_actor_for(principal, viewing_tenant_id=viewing)
    if actor is None or not isinstance(act, dict) or act.get("sub") != str(actor.admin_user_id):
        raise _refused("This suggestion was made for someone else.")
    if not await _may(actor, tool.permission):
        raise ProblemError(
            kind="permission",
            code="forbidden",
            title="Forbidden",
            detail="Your role cannot make this change.",
            remediation="Ask a superadmin to confirm it instead.",
        )
    args = claims["args"]
    if not isinstance(args, dict):  # pragma: no cover - `require` already demands it
        raise _refused("This suggestion is no longer valid.")
    # STEP-UP BEFORE THE BURN: a refusal for a stale second factor must leave the token
    # usable once the operator has re-proved it.
    if tool.confirm_action is not None:
        require_step_up(tool.confirm_action(args))
    if tool.scope == "tenant" and viewing is None:
        raise _refused("This suggestion was made without a client's page open.")
    object_id = str(claims.get("obj") or "") or None
    await write_tools.burn_proposal(str(claims["jti"]))
    try:
        if tool.scope == "tenant":
            assert viewing is not None
            # The work and its audit row commit together in the client's own session; the
            # action-log row below lives in the platform table and follows them.
            async with tenant_session(viewing) as scoped:
                executed = await _execute_and_audit(
                    scoped,
                    tool,
                    actor,
                    args,
                    principal=principal,
                    tenant_id=viewing,
                    object_id=object_id,
                    ip=ip,
                )
        else:
            executed = await _execute_and_audit(
                session,
                tool,
                actor,
                args,
                principal=principal,
                tenant_id=None,
                object_id=object_id,
                ip=ip,
            )
        await action_log.insert(
            session,
            action_log.NewAction(
                realm="admin",
                tool=tool.name,
                tier=tool.tier,
                status="done",
                source="interactive",
                object_type=tool.object_type,
                actor_id=actor.admin_user_id,
                tenant_id=viewing,
                object_id=str(claims.get("obj") or "") or None,
                args=args,
                summary=executed.detail,
            ),
        )
    except BaseException:
        await write_tools.unburn_proposal(str(claims["jti"]))
        raise
    return CopilotConfirmOut(
        tool=tool.name,
        object_type=tool.object_type,
        object_id=str(claims.get("obj") or ""),
        applied=executed.applied,
        detail=strip_invisible(executed.detail),
    )


__all__ = [
    "ADMIN_ACTIONS",
    "ADMIN_PROPOSAL_AUDIENCE",
    "PLATFORM_HALT_OUTBOUND",
    "AdminActionTool",
    "AdminActor",
    "admin_action_schemas",
    "admin_actor_for",
    "confirm_admin",
    "is_admin_action",
    "plan_admin_action",
]
