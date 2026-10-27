"""Pip's account actions (D-893 lane L6): numbers, team, settings, integrations and billing
settings, each the button on its own screen as a tool.

Every tool follows `docs/COPILOT-CONTRACT.md`; read §1 for the tiers first. What is
particular to this module:

═══ THE TIER OF EACH ═══

`immediate` (runs, leaves an Undo): changing how an existing number forwards, pausing or
resuming a lead source, and pointing a lead source at another agent. None reaches a caller
or spends anything, and each inverse restores exactly the row the button wrote.

`confirm`: everything else here. Pointing a number at an agent changes who answers live
calls; adding, testing or removing a forwarded number is a personal attestation, a real call
or a deletion; every team act grants, mails or removes access (OWASP ASI03, identity and
privilege abuse); a lead source or endpoint created or re-keyed issues a secret; the
lead-calling plan and a held lead decide who is called; an endpoint edit widens what leaves
the account; a delivery resend sends data out again; and every billing setting moves what
stops or charges the wallet. The AI allowance top-up debits credit.

═══ NEVER HERE (PIP-AGENT-PLAN §1) ═══

A payment, a top-up order, approving an automatic-payment method, the no-cold-calls pledge,
legal documents, KYC and deleting the account. Connecting Google (OAuth) is the person's own
sign-in on the Integrations screen; `integrations_status` says whether it is connected.

═══ SECRETS ═══

Creating or re-keying a lead source or endpoint returns a secret exactly once. It is put in
`Executed.detail`, which only the confirming person's own response carries, and never in
`recorded` (the activity log), `audit_summary` or a Plan; the model never sees it.

═══ THE EMAILED CODE ═══

Some buttons here need a code typed for that one act (`core/stepup.ActionCode`, D-730). Each
such tool declares `ActionTool.action_code`, the template of the exact `X-Confirm-Action`
string its button's route checks, so confirming or approving it through Pip demands the same
code (D-893 F4): adding or testing a forwarded number, inviting an owner, making someone an
owner, and creating a webhook endpoint.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, time
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot.actions import (
    DOES_IT,
    PROPOSES_ONLY,
    ActionTool,
    Executed,
    Plan,
    ToolActor,
    Undo,
    UndoRecord,
    UndoRefusedError,
    WriteRefusedError,
    account_code,
    action_schema,
    parse_args,
)
from apps.api.copilot.sanitize import strip_invisible
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.db.ownership import assert_visible


def _owner_invite_code(args: Mapping[str, Any]) -> str | None:
    """`tenancy/routes.invite_owner_confirmation`: bound to the address; staff need none."""
    if args.get("role") != "owner":
        return None
    return f"invite_owner:{{org}}:{str(args['email']).strip().lower()}"


def _owner_promotion_code(args: Mapping[str, Any]) -> str | None:
    """`tenancy/routes.promote_owner_confirmation`: bound to the person; staff need none."""
    if args.get("role") != "owner":
        return None
    return f"promote_owner:{{org}}:{args['user_id']}"


def _principal_of(actor: ToolActor) -> Principal:
    """The principal a service that writes its own audit row or attestation needs."""
    return Principal(
        realm="client",
        user_id=actor.user_id,
        tenant_id=actor.tenant_id,
        role=actor.role,
        impersonating=actor.impersonating,
    )


def _masked(phone: str) -> str:
    from apps.workers.redaction import redact

    return redact(phone).text


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


def _uuid_or_none(raw: object) -> UUID | None:
    return None if raw is None else UUID(str(raw))


# =========================================================================================
# NUMBERS
# =========================================================================================


class _NumberAssignArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number_id: UUID
    agent_id: UUID | None
    direction: Literal["inbound", "outbound", "both"] | None


async def _plan_number_assign(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_NumberAssignArgs, args)
    row = (
        await session.execute(
            text(
                "SELECT n.e164, a.name, n.direction FROM phone_numbers n "
                "LEFT JOIN agents a ON a.id = n.agent_id "
                "WHERE n.id = :nid AND n.released_at IS NULL"
            ),
            {"nid": parsed.number_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Phone number")
    masked = _masked(str(row[0]))
    current = strip_invisible(str(row[1])) if row[1] is not None else "no agent"
    proposed = (
        "no agent" if parsed.agent_id is None else await _agent_name(session, parsed.agent_id)
    )
    direction = parsed.direction or str(row[2] or "both")
    return Plan(
        object_id=str(parsed.number_id),
        title="Put this number on an agent"
        if parsed.agent_id
        else "Take this number off its agent",
        summary=(
            f"{masked} will be answered and dialled from by “{proposed}” ({direction})."
            if parsed.agent_id
            else f"{masked} will not be answered by any agent until you choose one."
        ),
        current=current,
        proposed=proposed,
        cost=None,
        reversal="Choose another agent for it at any time on the Your phone number screen.",
        args={
            "number_id": str(parsed.number_id),
            "agent_id": None if parsed.agent_id is None else str(parsed.agent_id),
            "direction": parsed.direction,
        },
    )


async def _execute_number_assign(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`number_catalog.assign_number_to_agent` — `POST /v1/numbers/{id}/assign`'s call,
    which holds the activation gate and tells the voice platform in the same request."""
    from apps.api.campaigns.number_catalog import assign_number_to_agent

    parsed = parse_args(_NumberAssignArgs, args)
    routing = await assign_number_to_agent(
        session,
        tenant_id=actor.tenant_id,
        number_id=parsed.number_id,
        agent_id=parsed.agent_id,
        direction=parsed.direction,
    )
    detail = "The number is set. " + (
        "The phone system could not be told yet; it is retried and the screen shows it."
        if routing.failed
        else "Calls follow the new choice now."
    )
    return Executed(
        applied=True,
        detail=detail,
        audit_summary={
            "agent_id": None if parsed.agent_id is None else str(parsed.agent_id),
            "bound": routing.bound,
            "failed": routing.failed,
        },
    )


NUMBER_ASSIGN: Final = ActionTool(
    name="number_assign",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="phone_number",
    audit_action="number.assigned",
    where="on the Your phone number screen",
    schema=action_schema(
        "number_assign",
        "Propose which agent answers and calls from one of the account's numbers, or none."
        + PROPOSES_ONLY,
        {
            "number_id": {"type": "string", "description": "From `numbers_list`."},
            "agent_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "From `agents_list`; null takes it off its agent.",
            },
            "direction": {
                "anyOf": [
                    {"type": "string", "enum": ["inbound", "outbound", "both"]},
                    {"type": "null"},
                ],
                "description": "Null keeps the number's own.",
            },
        },
    ),
    plan=_plan_number_assign,
    execute=_execute_number_assign,
)


_LINE_KINDS: Final = ["mobile", "landline", "office_system"]
_CARRIERS: Final = ["airtel", "jio", "vi", "bsnl", "other"]
_MODES: Final = ["conditional", "all_calls"]


class _LineChoices(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_kind: Literal["mobile", "landline", "office_system"]
    carrier: Literal["airtel", "jio", "vi", "bsnl", "other"]
    mode: Literal["conditional", "all_calls"]
    ring_seconds: int = Field(ge=0, le=30)
    calevate_number_id: UUID | None


class _LineAddArgs(_LineChoices):
    number: str = Field(min_length=6, max_length=24)


def _forward_words(mode: str, ring_seconds: int) -> str:
    return (
        "every call forwards"
        if mode == "all_calls"
        else f"calls forward when unanswered after {ring_seconds} seconds"
    )


def _line_args(parsed: _LineChoices) -> dict[str, Any]:
    return {
        "line_kind": parsed.line_kind,
        "carrier": parsed.carrier,
        "mode": parsed.mode,
        "ring_seconds": parsed.ring_seconds,
        "calevate_number_id": None
        if parsed.calevate_number_id is None
        else str(parsed.calevate_number_id),
    }


async def _plan_line_add(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del session, actor
    parsed = parse_args(_LineAddArgs, args)
    number = strip_invisible(parsed.number.strip())
    return Plan(
        object_id="",
        title="Add the number your callers already know",
        summary=(
            f"Track {_masked(number)} ({parsed.carrier}, {parsed.line_kind}): "
            f"{_forward_words(parsed.mode, parsed.ring_seconds)} to your Calevate number. "
            "Confirming also says this number belongs to your business."
        ),
        current=None,
        proposed=_masked(number),
        cost=None,
        reversal="Remove it on the Phone numbers screen; switch the forward off on the phone too.",
        args={"number": number, **_line_args(parsed)},
    )


async def _execute_line_add(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`forwarding.service.create_line` — `POST /v1/forwarding/lines`'s call. The person's
    Confirm on a card that says so is the attestation the form's tick box gives."""
    from apps.api.forwarding.service import create_line

    parsed = parse_args(_LineAddArgs, args)
    line = await create_line(
        session,
        principal=_principal_of(actor),
        tenant_id=actor.tenant_id,
        number=parsed.number,
        line_kind=parsed.line_kind,
        carrier=parsed.carrier,
        mode=parsed.mode,
        ring_seconds=parsed.ring_seconds,
        calevate_number_id=parsed.calevate_number_id,
        attest=True,
    )
    return Executed(
        applied=True,
        detail="The number is added. Set the forward on the phone, then test it on the screen.",
        audit_summary={"mode": parsed.mode, "carrier": parsed.carrier},
        object_id=str(line.id),
    )


FORWARDING_LINE_ADD: Final = ActionTool(
    name="forwarding_line_add",
    tier="confirm",
    undo=None,
    action_code=account_code("add_forwarded_number"),
    permission="org:manage",
    object_type="forwarded_line",
    audit_action="forwarding.line_added",
    where="on the Phone numbers screen",
    schema=action_schema(
        "forwarding_line_add",
        "Propose tracking the business's existing number, forwarded to its Calevate number."
        + PROPOSES_ONLY,
        {
            "number": {
                "type": "string",
                "description": "The existing number, as the person gave it.",
            },
            "line_kind": {"type": "string", "enum": _LINE_KINDS},
            "carrier": {"type": "string", "enum": _CARRIERS},
            "mode": {"type": "string", "enum": _MODES},
            "ring_seconds": {"type": "integer", "description": "5-30 for conditional, 0 for all."},
            "calevate_number_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "From `numbers_list`; null for the only one.",
            },
        },
    ),
    plan=_plan_line_add,
    execute=_execute_line_add,
)


class _LineChangeArgs(_LineChoices):
    line_id: UUID


async def _plan_line_change(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    from apps.api.forwarding.service import read_line

    parsed = parse_args(_LineChangeArgs, args)
    line = await read_line(session, parsed.line_id)
    return Plan(
        object_id=str(parsed.line_id),
        title="Change how a number forwards",
        summary=(
            f"{_masked(line.e164)}: {_forward_words(parsed.mode, parsed.ring_seconds)}. "
            "Change the forward on the phone to match, then test it again."
        ),
        current=_forward_words(line.mode, line.ring_seconds),
        proposed=_forward_words(parsed.mode, parsed.ring_seconds),
        cost=None,
        reversal="Undo puts the previous setting back.",
        args={"line_id": str(parsed.line_id), **_line_args(parsed)},
    )


async def _execute_line_change(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`forwarding.service.update_line` — `PATCH /v1/forwarding/lines/{id}`'s call."""
    from apps.api.forwarding.service import update_line

    parsed = parse_args(_LineChangeArgs, args)
    await update_line(
        session,
        principal=_principal_of(actor),
        tenant_id=actor.tenant_id,
        line_id=parsed.line_id,
        line_kind=parsed.line_kind,
        carrier=parsed.carrier,
        mode=parsed.mode,
        ring_seconds=parsed.ring_seconds,
        calevate_number_id=parsed.calevate_number_id,
    )
    return Executed(
        applied=True,
        detail="Saved. Change the forward on the phone to match, then test it.",
        audit_summary={"mode": parsed.mode, "carrier": parsed.carrier},
    )


async def _capture_line(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> dict[str, Any]:
    from apps.api.forwarding.service import read_line

    del actor
    line = await read_line(session, UUID(str(args["line_id"])))
    return {
        "line_kind": line.line_kind,
        "carrier": line.carrier,
        "mode": line.mode,
        "ring_seconds": line.ring_seconds,
        "calevate_number_id": None
        if line.calevate_number_id is None
        else str(line.calevate_number_id),
    }


async def _invert_line(session: AsyncSession, actor: ToolActor, record: UndoRecord) -> str:
    from apps.api.forwarding.service import update_line

    line_id = UUID(str(record.args["line_id"]))
    row = (
        await session.execute(
            text(
                "SELECT line_kind, carrier, mode, ring_seconds, calevate_number_id "
                "FROM forwarded_lines WHERE id = :id FOR UPDATE"
            ),
            {"id": line_id},
        )
    ).first()
    if row is None:
        raise UndoRefusedError(
            "that number has been removed since, so there is nothing to put back"
        )
    now = {
        "line_kind": str(row[0]),
        "carrier": str(row[1]),
        "mode": str(row[2]),
        "ring_seconds": int(row[3]),
        "calevate_number_id": None if row[4] is None else str(row[4]),
    }
    if now != dict(record.result_state):
        raise UndoRefusedError(
            "that number's forwarding was changed since, so it was left as it is"
        )
    prior = record.prior_state
    await update_line(
        session,
        principal=_principal_of(actor),
        tenant_id=actor.tenant_id,
        line_id=line_id,
        line_kind=str(prior["line_kind"]),
        carrier=str(prior["carrier"]),
        mode=str(prior["mode"]),
        ring_seconds=int(prior["ring_seconds"]),
        calevate_number_id=_uuid_or_none(prior["calevate_number_id"]),
    )
    return "The number's forwarding is back to what it was."


FORWARDING_LINE_CHANGE: Final = ActionTool(
    name="forwarding_line_change",
    tier="immediate",
    undo=Undo(capture=_capture_line, invert=_invert_line),
    permission="org:manage",
    object_type="forwarded_line",
    audit_action="forwarding.line_changed",
    where="on the Phone numbers screen",
    schema=action_schema(
        "forwarding_line_change",
        "Change how a tracked existing number forwards (from `numbers_list`). Send every "
        "field, unchanged ones as they are." + DOES_IT,
        {
            "line_id": {"type": "string", "description": "From `numbers_list`."},
            "line_kind": {"type": "string", "enum": _LINE_KINDS},
            "carrier": {"type": "string", "enum": _CARRIERS},
            "mode": {"type": "string", "enum": _MODES},
            "ring_seconds": {"type": "integer"},
            "calevate_number_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
    ),
    plan=_plan_line_change,
    execute=_execute_line_change,
)


class _LineIdArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_id: UUID


async def _plan_line_remove(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    from apps.api.forwarding.service import read_line

    parsed = parse_args(_LineIdArgs, args)
    line = await read_line(session, parsed.line_id)
    return Plan(
        object_id=str(parsed.line_id),
        title="Stop tracking an existing number",
        summary=(
            f"Forget {_masked(line.e164)}. Switch the forward off on the phone too, or its "
            "calls keep coming to your Calevate number."
        ),
        current=_masked(line.e164),
        proposed="Removed",
        cost=None,
        reversal="Add it again on the Phone numbers screen; its test history is not kept.",
        args={"line_id": str(parsed.line_id)},
    )


async def _execute_line_remove(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`forwarding.service.delete_line` — `DELETE /v1/forwarding/lines/{id}`'s call."""
    from apps.api.forwarding.service import delete_line

    parsed = parse_args(_LineIdArgs, args)
    await delete_line(
        session,
        principal=_principal_of(actor),
        tenant_id=actor.tenant_id,
        line_id=parsed.line_id,
    )
    return Executed(applied=True, detail="The number is removed.", audit_summary={})


FORWARDING_LINE_REMOVE: Final = ActionTool(
    name="forwarding_line_remove",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="forwarded_line",
    audit_action="forwarding.line_removed",
    where="on the Phone numbers screen",
    schema=action_schema(
        "forwarding_line_remove",
        "Propose no longer tracking one existing number." + PROPOSES_ONLY,
        {"line_id": {"type": "string", "description": "From `numbers_list`."}},
    ),
    plan=_plan_line_remove,
    execute=_execute_line_remove,
)


async def _plan_line_test(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    from apps.api.forwarding.service import read_line

    parsed = parse_args(_LineIdArgs, args)
    line = await read_line(session, parsed.line_id)
    return Plan(
        object_id=str(parsed.line_id),
        title="Test a forwarded number",
        summary=(
            f"We ring {_masked(line.e164)} now to check it reaches your agent. Do not answer it "
            "on the phone itself."
        ),
        current=None,
        proposed="A test call now",
        cost="A few seconds of calling, charged at your plan's rate.",
        reversal="A call cannot be taken back once it has started ringing.",
        args={"line_id": str(parsed.line_id), "attempt": str(uuid4())},
    )


class _LineTestSigned(_LineIdArgs):
    attempt: UUID


async def _execute_line_test(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`forwarding.testing.start_test` — `POST /v1/forwarding/lines/{id}/tests`'s call."""
    from apps.api.forwarding.testing import start_test

    parsed = parse_args(_LineTestSigned, args)
    view = await start_test(
        session,
        principal=_principal_of(actor),
        tenant_id=actor.tenant_id,
        line_id=parsed.line_id,
    )
    return Executed(
        applied=True,
        detail="The test call is being placed; the Phone numbers screen shows the result.",
        audit_summary={"status": view.status},
        object_id=str(view.id),
    )


FORWARDING_LINE_TEST: Final = ActionTool(
    name="forwarding_line_test",
    tier="confirm",
    undo=None,
    action_code=account_code("forwarding_test"),
    permission="org:manage",
    object_type="forwarded_line",
    audit_action="forwarding.test_requested",
    where="on the Phone numbers screen",
    schema=action_schema(
        "forwarding_line_test",
        "Propose a test call to a tracked existing number." + PROPOSES_ONLY,
        {"line_id": {"type": "string", "description": "From `numbers_list`."}},
    ),
    plan=_plan_line_test,
    execute=_execute_line_test,
)


# =========================================================================================
# TEAM
# =========================================================================================

_ROLE_WORDS: Final = {"owner": "an owner", "staff": "staff"}


class _InviteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    role: Literal["owner", "staff"]


async def _plan_team_invite(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del session
    from apps.api.tenancy.members import assert_role_is_grantable

    parsed = parse_args(_InviteArgs, args)
    assert_role_is_grantable(actor.role, parsed.role)
    email = str(parsed.email).strip().lower()
    return Plan(
        object_id="",
        title="Invite someone to your team",
        summary=(
            f"Email an invitation to {email} to join as {_ROLE_WORDS[parsed.role]}. "
            "The link works once, for 72 hours."
        ),
        current=None,
        proposed=f"{email} · {parsed.role}",
        cost=None,
        reversal="Cancel the invitation on the Team screen before it is used.",
        args={"email": email, "role": parsed.role},
    )


async def _execute_team_invite(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`members.send_team_invitation` — `POST /v1/invitations`'s call, mail included."""
    from apps.api.tenancy.members import send_team_invitation

    parsed = parse_args(_InviteArgs, args)
    invitation_id = await send_team_invitation(
        session,
        tenant_id=actor.tenant_id,
        actor_user_id=actor.user_id,
        actor_role=actor.role,
        email=str(parsed.email),
        role=parsed.role,
    )
    return Executed(
        applied=True,
        detail="The invitation is on its way.",
        audit_summary={"role": parsed.role},
        object_id=str(invitation_id),
    )


TEAM_INVITE: Final = ActionTool(
    name="team_invite",
    tier="confirm",
    undo=None,
    action_code=_owner_invite_code,
    permission="org:manage",
    object_type="invitation",
    audit_action="member.invited",
    where="on the Team screen",
    schema=action_schema(
        "team_invite",
        "Propose emailing a team invitation." + PROPOSES_ONLY,
        {
            "email": {"type": "string", "description": "The address the person gave."},
            "role": {"type": "string", "enum": ["owner", "staff"]},
        },
    ),
    plan=_plan_team_invite,
    execute=_execute_team_invite,
)


class _MemberRoleArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    role: Literal["owner", "staff"]


async def _member(session: AsyncSession, user_id: UUID) -> tuple[str, str]:
    row = (
        await session.execute(
            text(
                "SELECT m.role, u.name FROM memberships m JOIN users u ON u.id = m.user_id "
                "WHERE m.user_id = :u"
            ),
            {"u": user_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Member")
    return str(row[0]), strip_invisible(str(row[1] or "this team member"))


async def _plan_member_role(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    parsed = parse_args(_MemberRoleArgs, args)
    if parsed.user_id == actor.user_id:
        raise WriteRefusedError("no one changes their own role; another owner must do it")
    held, name = await _member(session, parsed.user_id)
    if held == parsed.role:
        raise WriteRefusedError(f"{name} is already {_ROLE_WORDS[held]}")
    return Plan(
        object_id=str(parsed.user_id),
        title="Change a team member's role",
        summary=f"{name} becomes {_ROLE_WORDS[parsed.role]}.",
        current=held,
        proposed=parsed.role,
        cost=None,
        reversal="Change it back on the Team screen.",
        args={"user_id": str(parsed.user_id), "role": parsed.role, "expected_role": held},
    )


class _MemberRoleSigned(_MemberRoleArgs):
    expected_role: Literal["owner", "staff"]


async def _execute_member_role(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`members.change_member_role` — `PATCH /v1/members/{id}`'s call, a CAS on the role
    the card showed."""
    from apps.api.tenancy.members import change_member_role

    parsed = parse_args(_MemberRoleSigned, args)
    previous = await change_member_role(
        session,
        actor_user_id=actor.user_id,
        actor_role=actor.role,
        target_user_id=parsed.user_id,
        new_role=parsed.role,
        expected_role=parsed.expected_role,
    )
    return Executed(
        applied=previous != parsed.role,
        detail="The role is changed.",
        audit_summary={"from": previous, "to": parsed.role},
    )


TEAM_MEMBER_ROLE: Final = ActionTool(
    name="team_member_role",
    tier="confirm",
    undo=None,
    action_code=_owner_promotion_code,
    permission="org:manage",
    object_type="membership",
    audit_action="member.role_changed",
    where="on the Team screen",
    schema=action_schema(
        "team_member_role",
        "Propose changing a team member's role (ids from `team_members`)." + PROPOSES_ONLY,
        {
            "user_id": {"type": "string"},
            "role": {"type": "string", "enum": ["owner", "staff"]},
        },
    ),
    plan=_plan_member_role,
    execute=_execute_member_role,
)


class _UserArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID


async def _plan_member_remove(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    parsed = parse_args(_UserArgs, args)
    if parsed.user_id == actor.user_id:
        raise WriteRefusedError("no one removes themselves; another owner must do it")
    held, name = await _member(session, parsed.user_id)
    return Plan(
        object_id=str(parsed.user_id),
        title="Remove a team member",
        summary=f"{name} loses access to this account at once. Leads they own keep their name.",
        current=held,
        proposed="Removed",
        cost=None,
        reversal="Invite them again to give access back.",
        args={"user_id": str(parsed.user_id)},
    )


async def _execute_member_remove(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`members.remove_member` — `DELETE /v1/members/{id}`'s call."""
    from apps.api.tenancy.members import remove_member

    parsed = parse_args(_UserArgs, args)
    previous, still_assigned = await remove_member(
        session, actor_user_id=actor.user_id, target_user_id=parsed.user_id
    )
    detail = "They are removed."
    if still_assigned:
        detail += f" {still_assigned} lead(s) still name them; reassign them on Leads."
    return Executed(
        applied=True,
        detail=detail,
        audit_summary={"previous_role": previous, "leads_still_assigned": still_assigned},
    )


TEAM_MEMBER_REMOVE: Final = ActionTool(
    name="team_member_remove",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="membership",
    audit_action="member.removed",
    where="on the Team screen",
    schema=action_schema(
        "team_member_remove",
        "Propose removing a team member (id from `team_members`)." + PROPOSES_ONLY,
        {"user_id": {"type": "string"}},
    ),
    plan=_plan_member_remove,
    execute=_execute_member_remove,
)


class _InvitationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invitation_id: UUID
    action: Literal["resend", "cancel"]


async def _plan_invitation(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    from apps.api.tenancy.members import assert_role_is_grantable

    parsed = parse_args(_InvitationArgs, args)
    row = (
        await session.execute(
            text(
                "SELECT email, role FROM invitations "
                "WHERE id = :i AND used_at IS NULL AND expires_at > now()"
            ),
            {"i": parsed.invitation_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Invitation")
    assert_role_is_grantable(actor.role, str(row[1]))
    email = str(row[0])
    resend = parsed.action == "resend"
    return Plan(
        object_id=str(parsed.invitation_id),
        title="Send the invitation again" if resend else "Cancel an invitation",
        summary=(
            f"Email {email} a new link; the old one stops working and the 72 hours restart."
            if resend
            else f"The link sent to {email} stops working."
        ),
        current="pending",
        proposed="sent again" if resend else "cancelled",
        cost=None,
        reversal="Cancel it on the Team screen." if resend else "Invite them again.",
        args={"invitation_id": str(parsed.invitation_id), "action": parsed.action},
    )


async def _execute_invitation(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`members.resend_and_mail_invitation` / `revoke_invitation` — the two invitation
    buttons' calls."""
    from apps.api.tenancy.members import resend_and_mail_invitation, revoke_invitation

    parsed = parse_args(_InvitationArgs, args)
    if parsed.action == "resend":
        resent = await resend_and_mail_invitation(
            session, actor_role=actor.role, invitation_id=parsed.invitation_id
        )
        return Executed(
            applied=True,
            detail="Sent again.",
            audit_summary={"action": "resend", "role": resent.role},
        )
    role = await revoke_invitation(session, parsed.invitation_id)
    return Executed(
        applied=True,
        detail="The invitation is cancelled.",
        audit_summary={"action": "cancel", "role": role},
    )


TEAM_INVITATION: Final = ActionTool(
    name="team_invitation",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="invitation",
    audit_action="member.invitation_changed",
    where="on the Team screen",
    schema=action_schema(
        "team_invitation",
        "Propose resending or cancelling a pending invitation (id from `team_members`)."
        + PROPOSES_ONLY,
        {
            "invitation_id": {"type": "string"},
            "action": {"type": "string", "enum": ["resend", "cancel"]},
        },
    ),
    plan=_plan_invitation,
    execute=_execute_invitation,
)


# =========================================================================================
# SETTINGS: line protection, lead sources, lead-calling rules
# =========================================================================================


class _FallbackArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str | None = Field(max_length=24)


async def _plan_fallback(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    from pydantic import ValidationError

    from apps.api.healer import protection
    from apps.api.healer.routes import FallbackPhoneIn

    parsed = parse_args(_FallbackArgs, args)
    current = await protection.fallback_phone(session)
    current_words = "none" if current is None else _masked(current)
    if parsed.phone is None:
        if current is None:
            raise WriteRefusedError("no backup phone is set, so there is nothing to remove")
        return Plan(
            object_id="",
            title="Remove the backup phone",
            summary="If your agent cannot take calls, callers hear a short message instead.",
            current=current_words,
            proposed="none",
            cost=None,
            reversal="Set a phone again on the Line protection screen.",
            args={"phone": None},
        )
    raw = strip_invisible(parsed.phone).replace(" ", "")
    candidate = raw if raw.startswith("+") else f"+91{raw[-10:]}"
    try:
        valid = FallbackPhoneIn(phone_e164=candidate).phone_e164
    except ValidationError as exc:
        raise WriteRefusedError(
            "the backup phone must be an Indian mobile number; ask the person for one"
        ) from exc
    return Plan(
        object_id="",
        title="Set the backup phone",
        summary=(
            f"If your agent cannot take calls, callers are passed to {_masked(valid)} where "
            "the phone system allows it."
        ),
        current=current_words,
        proposed=_masked(valid),
        cost=None,
        reversal="Change or remove it on the Line protection screen.",
        args={"phone": valid},
    )


async def _execute_fallback(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`healer.protection.set_fallback_phone` / `clear_fallback_phone` — the Line
    protection screen's Save and Remove."""
    from apps.api.healer import protection

    phone = args.get("phone")
    if phone is None:
        removed = await protection.clear_fallback_phone(session)
        return Executed(
            applied=removed, detail="The backup phone is removed.", audit_summary={"set": False}
        )
    await protection.set_fallback_phone(
        session, tenant_id=actor.tenant_id, user_id=actor.user_id, phone_e164=str(phone)
    )
    return Executed(applied=True, detail="The backup phone is saved.", audit_summary={"set": True})


LINE_PROTECTION_PHONE: Final = ActionTool(
    name="line_protection_phone",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="organization",
    audit_action="healer.fallback_phone_set",
    where="on the Line protection screen",
    schema=action_schema(
        "line_protection_phone",
        "Propose the backup phone callers are passed to when the agent cannot take calls."
        + PROPOSES_ONLY,
        {
            "phone": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "An Indian mobile the person gave; null removes it.",
            }
        },
    ),
    plan=_plan_fallback,
    execute=_execute_fallback,
)


_SOURCE_KINDS: Final = ["website_form", "zoho", "sheets", "custom"]


class _SourceCreateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["website_form", "zoho", "sheets", "custom"]
    agent_id: UUID | None


async def _plan_source_create(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_SourceCreateArgs, args)
    agent = None if parsed.agent_id is None else await _agent_name(session, parsed.agent_id)
    return Plan(
        object_id="",
        title="Add a lead source",
        summary=(
            f"Make an address your {parsed.source.replace('_', ' ')} can send new leads to"
            + (f"; “{agent}” calls them" if agent else "; choose an agent before leads arrive")
            + ". Its secret is shown once, on the confirmation."
        ),
        current=None,
        proposed=parsed.source,
        cost=None,
        reversal="Pause it on the Lead sources screen.",
        args={
            "source": parsed.source,
            "agent_id": None if parsed.agent_id is None else str(parsed.agent_id),
        },
    )


async def _execute_source_create(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`ingest.service.create_lead_source` — `POST /v1/lead-sources`'s call. The secret
    goes in `detail` only, shown once to the person who confirmed."""
    from apps.api.ingest.routes import SECRET_HEADER, _ingest_path
    from apps.api.ingest.service import create_lead_source

    parsed = parse_args(_SourceCreateArgs, args)
    webhook_id, minted = await create_lead_source(
        session,
        tenant_id=actor.tenant_id,
        source=parsed.source,
        agent_id=parsed.agent_id,
        mapping={},
        supplied_secret=None,
    )
    return Executed(
        applied=True,
        detail=(
            f"Added. Send leads to {_ingest_path(webhook_id, parsed.source)} with the header "
            f"{SECRET_HEADER}: {minted}. Copy it now; it is not shown again."
        ),
        recorded="Added a lead source; its secret was shown once.",
        audit_summary={"source": parsed.source},
        object_id=str(webhook_id),
    )


LEAD_SOURCE_CREATE: Final = ActionTool(
    name="lead_source_create",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="inbound_webhook",
    audit_action="lead_source.created",
    where="on the Lead sources screen",
    schema=action_schema(
        "lead_source_create",
        "Propose a new lead source address. Meta Lead Ads is set up on the Lead sources screen."
        + PROPOSES_ONLY,
        {
            "source": {"type": "string", "enum": _SOURCE_KINDS},
            "agent_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
    ),
    plan=_plan_source_create,
    execute=_execute_source_create,
)


class _SourceAgentArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_source_id: UUID
    agent_id: UUID | None


async def _source_row(session: AsyncSession, source_id: UUID) -> tuple[str, UUID | None, bool]:
    row = (
        await session.execute(
            text("SELECT source, agent_id, active FROM inbound_webhooks WHERE id = :id"),
            {"id": source_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Lead source")
    return str(row[0]), _uuid_or_none(row[1]), bool(row[2])


async def _plan_source_agent(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_SourceAgentArgs, args)
    source, current_agent, _active = await _source_row(session, parsed.lead_source_id)
    current = "no agent" if current_agent is None else await _agent_name(session, current_agent)
    proposed = (
        "no agent" if parsed.agent_id is None else await _agent_name(session, parsed.agent_id)
    )
    return Plan(
        object_id=str(parsed.lead_source_id),
        title="Change who answers a lead source",
        summary=f"New leads from {source.replace('_', ' ')} go to “{proposed}”.",
        current=current,
        proposed=proposed,
        cost=None,
        reversal="Undo puts the previous agent back.",
        args={
            "lead_source_id": str(parsed.lead_source_id),
            "agent_id": None if parsed.agent_id is None else str(parsed.agent_id),
        },
    )


async def _execute_source_agent(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`ingest.service.set_source_agent` — `PATCH /v1/lead-sources/{id}`'s call."""
    from apps.api.ingest.service import set_source_agent

    del actor
    parsed = parse_args(_SourceAgentArgs, args)
    previous = await set_source_agent(
        session, webhook_id=parsed.lead_source_id, agent_id=parsed.agent_id
    )
    return Executed(
        applied=previous != parsed.agent_id,
        detail="Saved. New leads from it go to the chosen agent.",
        audit_summary={"agent_id": None if parsed.agent_id is None else str(parsed.agent_id)},
    )


async def _capture_source_agent(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> dict[str, Any]:
    del actor
    _source, agent, _active = await _source_row(session, UUID(str(args["lead_source_id"])))
    return {"agent_id": None if agent is None else str(agent)}


async def _invert_source_agent(session: AsyncSession, actor: ToolActor, record: UndoRecord) -> str:
    from apps.api.ingest.service import set_source_agent

    del actor
    source_id = UUID(str(record.args["lead_source_id"]))
    row = (
        await session.execute(
            text("SELECT agent_id FROM inbound_webhooks WHERE id = :id FOR UPDATE"),
            {"id": source_id},
        )
    ).first()
    if row is None:
        raise UndoRefusedError("that lead source no longer exists")
    if (None if row[0] is None else str(row[0])) != record.result_state.get("agent_id"):
        raise UndoRefusedError(
            "that lead source's agent was changed since, so it was left as it is"
        )
    try:
        await set_source_agent(
            session,
            webhook_id=source_id,
            agent_id=_uuid_or_none(record.prior_state.get("agent_id")),
        )
    except ProblemError as exc:
        raise UndoRefusedError("the previous agent can no longer take leads") from exc
    return "The lead source is back on its previous agent."


LEAD_SOURCE_EDIT: Final = ActionTool(
    name="lead_source_edit",
    tier="immediate",
    undo=Undo(capture=_capture_source_agent, invert=_invert_source_agent),
    permission="org:manage",
    object_type="inbound_webhook",
    audit_action="lead_source.agent_changed",
    where="on the Lead sources screen",
    schema=action_schema(
        "lead_source_edit",
        "Choose which agent answers leads from one lead source (ids from "
        "`integrations_status`)." + DOES_IT,
        {
            "lead_source_id": {"type": "string"},
            "agent_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
    ),
    plan=_plan_source_agent,
    execute=_execute_source_agent,
)


class _SourceSwitchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_source_id: UUID
    on: bool


async def _plan_source_switch(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_SourceSwitchArgs, args)
    source, _agent, active = await _source_row(session, parsed.lead_source_id)
    if active == parsed.on:
        raise WriteRefusedError(f"that lead source is already {'on' if active else 'paused'}")
    return Plan(
        object_id=str(parsed.lead_source_id),
        title="Resume a lead source" if parsed.on else "Pause a lead source",
        summary=(
            f"Leads from {source.replace('_', ' ')} are accepted again, with the same secret."
            if parsed.on
            else f"Leads sent from {source.replace('_', ' ')} are refused until it is resumed."
        ),
        current="on" if active else "paused",
        proposed="on" if parsed.on else "paused",
        cost=None,
        reversal="Undo switches it back.",
        args={"lead_source_id": str(parsed.lead_source_id), "on": parsed.on},
    )


async def _execute_source_switch(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`ingest.service.set_active` — the Lead sources screen's switch
    (`DELETE /v1/lead-sources/{id}` and `POST .../enable`)."""
    from apps.api.ingest.service import set_active

    del actor
    parsed = parse_args(_SourceSwitchArgs, args)
    moved = await set_active(session, webhook_id=parsed.lead_source_id, active=parsed.on)
    return Executed(
        applied=moved,
        detail="It is on again." if parsed.on else "It is paused.",
        audit_summary={"active": parsed.on},
    )


async def _capture_source_switch(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> dict[str, Any]:
    del actor
    _source, _agent, active = await _source_row(session, UUID(str(args["lead_source_id"])))
    return {"active": active}


async def _invert_source_switch(session: AsyncSession, actor: ToolActor, record: UndoRecord) -> str:
    from apps.api.ingest.service import set_active

    del actor
    source_id = UUID(str(record.args["lead_source_id"]))
    row = (
        await session.execute(
            text("SELECT active FROM inbound_webhooks WHERE id = :id FOR UPDATE"),
            {"id": source_id},
        )
    ).first()
    if row is None:
        raise UndoRefusedError("that lead source no longer exists")
    if bool(row[0]) != record.result_state.get("active"):
        raise UndoRefusedError("that lead source was switched since, so it was left as it is")
    prior = bool(record.prior_state["active"])
    await set_active(session, webhook_id=source_id, active=prior)
    return "The lead source is on again." if prior else "The lead source is paused again."


LEAD_SOURCE_SWITCH: Final = ActionTool(
    name="lead_source_switch",
    tier="immediate",
    undo=Undo(capture=_capture_source_switch, invert=_invert_source_switch),
    permission="org:manage",
    object_type="inbound_webhook",
    audit_action="lead_source.switched",
    where="on the Lead sources screen",
    schema=action_schema(
        "lead_source_switch",
        "Pause (on=false) or resume (on=true) one lead source." + DOES_IT,
        {"lead_source_id": {"type": "string"}, "on": {"type": "boolean"}},
    ),
    plan=_plan_source_switch,
    execute=_execute_source_switch,
)


class _SourceRotateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_source_id: UUID
    retire_old_now: bool


async def _plan_source_rotate(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    from apps.api.ingest.service import CLIENT_SUPPLIED_SECRET_SOURCES

    parsed = parse_args(_SourceRotateArgs, args)
    source, _agent, _active = await _source_row(session, parsed.lead_source_id)
    if source in CLIENT_SUPPLIED_SECRET_SOURCES:
        raise WriteRefusedError(
            "this source uses the person's own app secret; it is replaced on the Lead sources "
            "screen"
        )
    return Plan(
        object_id=str(parsed.lead_source_id),
        title="Issue a new secret for a lead source",
        summary=(
            "A new secret is shown once on the confirmation. "
            + (
                "The old one stops working at once."
                if parsed.retire_old_now
                else "The old one keeps working for an hour while you update your form."
            )
        ),
        current=None,
        proposed="A new secret",
        cost=None,
        reversal="Issue another one; a replaced secret cannot be restored.",
        args={
            "lead_source_id": str(parsed.lead_source_id),
            "retire_old_now": parsed.retire_old_now,
        },
    )


async def _execute_source_rotate(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`ingest.service.rotate_secret` — `POST /v1/lead-sources/{id}/rotate-secret`'s call,
    with the route's default grace (60 minutes) or none."""
    from apps.api.ingest.routes import SECRET_HEADER
    from apps.api.ingest.service import rotate_secret

    del actor
    parsed = parse_args(_SourceRotateArgs, args)
    grace = 0 if parsed.retire_old_now else 60
    rotation = await rotate_secret(
        session, webhook_id=parsed.lead_source_id, grace_minutes=grace, supplied_secret=None
    )
    return Executed(
        applied=True,
        detail=(
            f"New secret for the {SECRET_HEADER} header: {rotation.secret}. Copy it now; it is "
            "not shown again."
        ),
        recorded="Issued a new lead source secret; it was shown once.",
        audit_summary={"grace_minutes": grace},
    )


LEAD_SOURCE_ROTATE: Final = ActionTool(
    name="lead_source_rotate",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="inbound_webhook",
    audit_action="lead_source.secret_rotated",
    where="on the Lead sources screen",
    schema=action_schema(
        "lead_source_rotate",
        "Propose a new secret for one lead source; retire_old_now when it leaked." + PROPOSES_ONLY,
        {"lead_source_id": {"type": "string"}, "retire_old_now": {"type": "boolean"}},
    ),
    plan=_plan_source_rotate,
    execute=_execute_source_rotate,
)


class _CallingRulesArgs(BaseModel):
    """Each field null keeps what the plan holds now."""

    model_config = ConfigDict(extra="forbid")

    calling_agent_id: UUID | Literal["each_source"] | None
    wait_seconds: int | None = Field(ge=0, le=3600)
    hours_start: time | None
    hours_end: time | None
    days: list[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]] | None
    after_hours: Literal["next_open", "open_plus_3h", "next_day", "hold"] | None
    retry_attempts: int | None = Field(ge=0, le=3)
    retry_interval_minutes: int | None = Field(ge=10, le=1440)
    detect_machines: bool | None


def _rules_line(plan: Any) -> str:
    days = ",".join(plan.days)
    return (
        f"{plan.hours_start:%H:%M}-{plan.hours_end:%H:%M} on {days}; wait {plan.wait_seconds}s; "
        f"after hours {plan.after_hours}; {plan.retry_attempts} retr(ies) every "
        f"{plan.retry_interval_minutes} min; answering machines "
        + ("detected" if plan.detect_machines else "not detected")
    )


async def _plan_calling_rules(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    from dataclasses import replace

    from apps.api.ingest import lead_policy

    parsed = parse_args(_CallingRulesArgs, args)
    current = await lead_policy.load_plan(session)
    changes: dict[str, Any] = {}
    if parsed.calling_agent_id == "each_source":
        changes["calling_agent_id"] = None
    elif parsed.calling_agent_id is not None:
        await _agent_name(session, parsed.calling_agent_id)
        changes["calling_agent_id"] = parsed.calling_agent_id
    for field in (
        "wait_seconds",
        "hours_start",
        "hours_end",
        "after_hours",
        "retry_attempts",
        "retry_interval_minutes",
        "detect_machines",
    ):
        value = getattr(parsed, field)
        if value is not None:
            changes[field] = value
    if parsed.days is not None:
        changes["days"] = tuple(parsed.days)
    if not changes:
        raise WriteRefusedError("name at least one rule to change")
    proposed = lead_policy.validated(replace(current, **changes))
    return Plan(
        object_id="",
        title="Change how new leads are called",
        summary=f"New leads: {_rules_line(proposed)}. Do-not-call and 9 AM-9 PM still apply.",
        current=_rules_line(current),
        proposed=_rules_line(proposed),
        cost=None,
        reversal="Change it again on the Lead sources screen.",
        args={
            "calling_agent_id": None
            if proposed.calling_agent_id is None
            else str(proposed.calling_agent_id),
            "wait_seconds": proposed.wait_seconds,
            "hours_start": proposed.hours_start.strftime("%H:%M"),
            "hours_end": proposed.hours_end.strftime("%H:%M"),
            "days": list(proposed.days),
            "holidays": [day.isoformat() for day in proposed.holidays],
            "after_hours": proposed.after_hours,
            "retry_attempts": proposed.retry_attempts,
            "retry_interval_minutes": proposed.retry_interval_minutes,
            "detect_machines": proposed.detect_machines,
        },
    )


async def _execute_calling_rules(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`lead_policy.save_and_apply` — `PUT /v1/lead-calling`'s call."""
    from apps.api.ingest import lead_policy

    plan = lead_policy.LeadCallPlan(
        calling_agent_id=_uuid_or_none(args["calling_agent_id"]),
        wait_seconds=int(args["wait_seconds"]),
        hours_start=time.fromisoformat(str(args["hours_start"])),
        hours_end=time.fromisoformat(str(args["hours_end"])),
        days=tuple(str(day) for day in args["days"]),
        holidays=tuple(date.fromisoformat(str(day)) for day in args["holidays"]),
        after_hours=str(args["after_hours"]),
        retry_attempts=int(args["retry_attempts"]),
        retry_interval_minutes=int(args["retry_interval_minutes"]),
        detect_machines=bool(args["detect_machines"]),
    )
    stored, updating = await lead_policy.save_and_apply(
        session, tenant_id=actor.tenant_id, plan=plan, user_id=actor.user_id
    )
    detail = "Saved."
    if updating:
        detail += f" {updating} live agent(s) are being updated."
    return Executed(
        applied=True,
        detail=detail,
        audit_summary={
            "after_hours": stored.after_hours,
            "retry_attempts": stored.retry_attempts,
            "detect_machines": stored.detect_machines,
        },
    )


_NULLABLE_INT: Final = {"anyOf": [{"type": "integer"}, {"type": "null"}]}

LEAD_CALLING_RULES: Final = ActionTool(
    name="lead_calling_rules",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="lead_call_policy",
    audit_action="lead_calling.saved",
    where="on the Lead sources screen",
    schema=action_schema(
        "lead_calling_rules",
        "Propose how new leads from lead sources are called. Null keeps a rule as it is."
        + PROPOSES_ONLY,
        {
            "calling_agent_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "An agent id, or each_source for each source's own agent.",
            },
            "wait_seconds": _NULLABLE_INT,
            "hours_start": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "HH:MM IST",
            },
            "hours_end": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "days": {
                "anyOf": [
                    {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                        },
                    },
                    {"type": "null"},
                ]
            },
            "after_hours": {
                "anyOf": [
                    {"type": "string", "enum": ["next_open", "open_plus_3h", "next_day", "hold"]},
                    {"type": "null"},
                ]
            },
            "retry_attempts": _NULLABLE_INT,
            "retry_interval_minutes": _NULLABLE_INT,
            "detect_machines": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
        },
    ),
    plan=_plan_calling_rules,
    execute=_execute_calling_rules,
)


class _HeldArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hold_id: UUID
    decision: Literal["call", "drop"]


async def _plan_held(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    del actor
    parsed = parse_args(_HeldArgs, args)
    row = (
        await session.execute(
            text(
                "SELECT a.name FROM lead_call_holds h JOIN leads l ON l.id = h.lead_id "
                "LEFT JOIN agents a ON a.id = h.agent_id "
                "WHERE h.id = :hid AND h.status = 'held' AND l.deleted_at IS NULL"
            ),
            {"hid": parsed.hold_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Held lead")
    agent = strip_invisible(str(row[0] or "its agent"))
    call = parsed.decision == "call"
    return Plan(
        object_id=str(parsed.hold_id),
        title="Call a held lead" if call else "Do not call a held lead",
        summary=(
            f"“{agent}” calls this lead as soon as your hours and 9 AM-9 PM allow."
            if call
            else "This lead leaves the waiting list and is not called; the lead is kept."
        ),
        current="waiting",
        proposed="to be called" if call else "not called",
        cost="Calls are billed per minute at your plan's rate." if call else None,
        reversal="A call cannot be taken back once it has started ringing."
        if call
        else "Call it from its lead page later if you change your mind.",
        args={"hold_id": str(parsed.hold_id), "decision": parsed.decision},
    )


async def _execute_held(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`lead_policy.release_held` / `drop_held` — the held list's two buttons."""
    from apps.api.ingest import lead_policy

    parsed = parse_args(_HeldArgs, args)
    if parsed.decision == "call":
        callback_id, _due = await lead_policy.release_held(
            session, tenant_id=actor.tenant_id, hold_id=parsed.hold_id, user_id=actor.user_id
        )
        return Executed(
            applied=True,
            detail="Booked; it is called through the usual checks. See Call-backs.",
            audit_summary={"decision": "call", "callback_id": str(callback_id)},
        )
    await lead_policy.drop_held(session, hold_id=parsed.hold_id, user_id=actor.user_id)
    return Executed(
        applied=True, detail="It will not be called.", audit_summary={"decision": "drop"}
    )


HELD_LEAD_DECIDE: Final = ActionTool(
    name="held_lead_decide",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="lead_call_hold",
    audit_action="lead_calling.held_decided",
    where="on the Lead sources screen",
    schema=action_schema(
        "held_lead_decide",
        "Propose calling or dropping one lead held after hours (hold id from "
        "`integrations_status`)." + PROPOSES_ONLY,
        {"hold_id": {"type": "string"}, "decision": {"type": "string", "enum": ["call", "drop"]}},
    ),
    plan=_plan_held,
    execute=_execute_held,
)


# =========================================================================================
# INTEGRATIONS
# =========================================================================================

_EVENTS: Final = [
    "lead.created",
    "lead.updated",
    "call.completed",
    "call.updated",
    "call.recording_ready",
    "campaign.completed",
]


class _EndpointExtras(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[
        Literal[
            "lead.created",
            "lead.updated",
            "call.completed",
            "call.updated",
            "call.recording_ready",
            "campaign.completed",
        ]
    ] = Field(min_length=1)
    include_recording_url: bool
    include_transcript: bool
    include_raw_transcript: bool


class _EndpointCreateArgs(_EndpointExtras):
    url: str = Field(min_length=8, max_length=2000)


def _what_it_carries(parsed: _EndpointExtras) -> str:
    extras = [
        name
        for name, on in (
            ("the recording link", parsed.include_recording_url),
            ("the transcript", parsed.include_transcript and not parsed.include_raw_transcript),
            ("the unredacted transcript", parsed.include_raw_transcript),
        )
        if on
    ]
    return ", ".join(sorted(set(parsed.events))) + (
        " with " + " and ".join(extras) if extras else ""
    )


def _host(url: str) -> str:
    from urllib.parse import urlsplit

    return urlsplit(url).hostname or "that address"


async def _plan_endpoint_create(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del session
    from apps.api.integrations.service import (
        assert_raw_transcript_opt_in,
        assert_recording_ready_opt_in,
    )

    parsed = parse_args(_EndpointCreateArgs, args)
    url = strip_invisible(parsed.url.strip())
    if not url.startswith("https://"):
        raise WriteRefusedError("the address must start with https://")
    assert_raw_transcript_opt_in(
        include_transcript=parsed.include_transcript,
        include_raw_transcript=parsed.include_raw_transcript,
        role=actor.role,
    )
    assert_recording_ready_opt_in(
        events=parsed.events, include_recording_url=parsed.include_recording_url
    )
    return Plan(
        object_id="",
        title="Send events to your system",
        summary=(
            f"Send {_what_it_carries(parsed)} to {_host(url)}. Lead details leave Calevate "
            "for that address. Its signing secret is shown once, on the confirmation."
        ),
        current=None,
        proposed=_host(url),
        cost=None,
        reversal="Switch it off on the Integrations screen; what was sent cannot be recalled.",
        args={"url": url, **parsed.model_dump(mode="json")},
    )


async def _execute_endpoint_create(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`integrations.service.create_webhook_endpoint` — the create route's call."""
    from apps.api.integrations.service import create_webhook_endpoint

    parsed = parse_args(_EndpointCreateArgs, args)
    created = await create_webhook_endpoint(
        session,
        tenant_id=actor.tenant_id,
        url=parsed.url,
        events=list(parsed.events),
        include_recording_url=parsed.include_recording_url,
        include_transcript=parsed.include_transcript,
        include_raw_transcript=parsed.include_raw_transcript,
        role=actor.role,
    )
    return Executed(
        applied=True,
        detail=f"Connected. Signing secret: {created.secret}. Copy it now; it is not shown again.",
        recorded="Connected an endpoint; its signing secret was shown once.",
        audit_summary={"host": created.host, "events": ",".join(sorted(parsed.events))},
        object_id=str(created.id),
    )


_ENDPOINT_FLAGS: Final = {
    "events": {"type": "array", "items": {"type": "string", "enum": _EVENTS}},
    "include_recording_url": {"type": "boolean"},
    "include_transcript": {"type": "boolean"},
    "include_raw_transcript": {"type": "boolean"},
}

CRM_ENDPOINT_CREATE: Final = ActionTool(
    name="crm_endpoint_create",
    tier="confirm",
    undo=None,
    action_code=account_code("create_endpoint"),
    permission="org:manage",
    object_type="outbound_webhook",
    audit_action="integration_endpoint.created",
    where="on the Integrations screen",
    schema=action_schema(
        "crm_endpoint_create",
        "Propose sending events to a webhook address the person gave." + PROPOSES_ONLY,
        {"url": {"type": "string", "description": "https:// address."}, **_ENDPOINT_FLAGS},
    ),
    plan=_plan_endpoint_create,
    execute=_execute_endpoint_create,
)


class _EndpointEditArgs(_EndpointExtras):
    endpoint_id: UUID
    #: Set by the plan from the stored row, never taken from the model: whether this edit
    #: switches call content on, which is what asks for the emailed code.
    opens: bool = False


def _endpoint_opt_in_code(args: Mapping[str, Any]) -> str | None:
    """The console edit's code (`integrations/routes.update_endpoint`), only when the plan
    found a recording link or transcript being switched on."""
    from apps.api.integrations.service import ENDPOINT_OPT_IN_VERB

    return f"{ENDPOINT_OPT_IN_VERB}:{{org}}" if args.get("opens") else None


async def _plan_endpoint_edit(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    from apps.api.integrations.service import (
        assert_raw_transcript_opt_in,
        assert_recording_ready_opt_in,
        opens_call_content,
        read_endpoint_choices,
    )

    parsed = parse_args(_EndpointEditArgs, args)
    before = await read_endpoint_choices(session, parsed.endpoint_id)
    assert_raw_transcript_opt_in(
        include_transcript=parsed.include_transcript,
        include_raw_transcript=parsed.include_raw_transcript,
        role=actor.role,
    )
    assert_recording_ready_opt_in(
        events=parsed.events, include_recording_url=parsed.include_recording_url
    )
    current = _what_it_carries(
        _EndpointExtras(
            events=list(before.events),  # type: ignore[arg-type]
            include_recording_url=before.include_recording_url,
            include_transcript=before.include_transcript,
            include_raw_transcript=before.include_raw_transcript,
        )
    )
    return Plan(
        object_id=str(parsed.endpoint_id),
        title="Change what an endpoint is sent",
        summary=f"From now on it is sent {_what_it_carries(parsed)}.",
        current=current,
        proposed=_what_it_carries(parsed),
        cost=None,
        reversal="Change it again on the Integrations screen; what was sent cannot be recalled.",
        args={
            "endpoint_id": str(parsed.endpoint_id),
            **parsed.model_dump(mode="json", exclude={"endpoint_id", "opens"}),
            "opens": opens_call_content(
                before,
                include_recording_url=parsed.include_recording_url,
                include_transcript=parsed.include_transcript,
                include_raw_transcript=parsed.include_raw_transcript,
            ),
        },
    )


async def _execute_endpoint_edit(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`integrations.service.update_endpoint` — `PATCH /v1/integrations/endpoints/{id}`'s
    call."""
    from apps.api.integrations.service import opens_call_content, update_endpoint

    parsed = parse_args(_EndpointEditArgs, args)
    before = await update_endpoint(
        session,
        endpoint_id=parsed.endpoint_id,
        events=list(parsed.events),
        include_recording_url=parsed.include_recording_url,
        include_transcript=parsed.include_transcript,
        include_raw_transcript=parsed.include_raw_transcript,
        role=actor.role,
    )
    # The code was asked for on what the plan saw. Someone switching an opt-in off since
    # would let this click switch it on uncoded, so a changed answer refuses (rolled back).
    if not parsed.opens and opens_call_content(
        before,
        include_recording_url=parsed.include_recording_url,
        include_transcript=parsed.include_transcript,
        include_raw_transcript=parsed.include_raw_transcript,
    ):
        raise WriteRefusedError(
            "that endpoint's settings changed since this was proposed; ask me again"
        )
    return Executed(
        applied=True,
        detail="Saved.",
        audit_summary={"events": ",".join(sorted(parsed.events))},
    )


CRM_ENDPOINT_EDIT: Final = ActionTool(
    name="crm_endpoint_edit",
    tier="confirm",
    undo=None,
    action_code=_endpoint_opt_in_code,
    permission="org:manage",
    object_type="outbound_webhook",
    audit_action="integration_endpoint.updated",
    where="on the Integrations screen",
    schema=action_schema(
        "crm_endpoint_edit",
        "Propose new events or opt-ins for an endpoint (id from `integrations_status`); the "
        "address cannot change." + PROPOSES_ONLY,
        {"endpoint_id": {"type": "string"}, **_ENDPOINT_FLAGS},
    ),
    plan=_plan_endpoint_edit,
    execute=_execute_endpoint_edit,
)


class _EndpointActArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint_id: UUID
    action: Literal["switch_off", "new_secret", "new_secret_retire_old_now"]


async def _plan_endpoint_act(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_EndpointActArgs, args)
    row = (
        await session.execute(
            text("SELECT url, kind, active FROM outbound_webhooks WHERE id = :id"),
            {"id": parsed.endpoint_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Endpoint")
    where = _host(str(row[0] or "")) if row[0] else "the spreadsheet"
    if not row[2]:
        raise WriteRefusedError("that endpoint is already switched off")
    if parsed.action == "switch_off":
        return Plan(
            object_id=str(parsed.endpoint_id),
            title="Stop sending to an endpoint",
            summary=f"Nothing more is sent to {where}. Its delivery history stays readable.",
            current="on",
            proposed="off",
            cost=None,
            reversal="Add the destination again on the Integrations screen.",
            args={"endpoint_id": str(parsed.endpoint_id), "action": parsed.action},
        )
    if row[1] != "webhook":
        raise WriteRefusedError("a spreadsheet destination has no signing secret")
    now = parsed.action == "new_secret_retire_old_now"
    return Plan(
        object_id=str(parsed.endpoint_id),
        title="Issue a new signing secret",
        summary=(
            f"A new secret for {where}, shown once on the confirmation. "
            + ("The old one stops at once." if now else "The old one also signs for a day.")
        ),
        current=None,
        proposed="A new secret",
        cost=None,
        reversal="Issue another one; a replaced secret cannot be restored.",
        args={"endpoint_id": str(parsed.endpoint_id), "action": parsed.action},
    )


async def _execute_endpoint_act(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`integrations.service.deactivate_endpoint` / `rotate_endpoint_secret` — the
    endpoint row's two buttons."""
    from apps.api.integrations import service

    del actor
    parsed = parse_args(_EndpointActArgs, args)
    if parsed.action == "switch_off":
        moved = await service.deactivate_endpoint(session, endpoint_id=parsed.endpoint_id)
        return Executed(
            applied=moved, detail="It is switched off.", audit_summary={"active": False}
        )
    grace = 0 if parsed.action == "new_secret_retire_old_now" else service.ROTATION_GRACE_MINUTES
    rotation = await service.rotate_endpoint_secret(
        session, endpoint_id=parsed.endpoint_id, grace_minutes=grace
    )
    return Executed(
        applied=True,
        detail=f"New signing secret: {rotation.secret}. Copy it now; it is not shown again.",
        recorded="Issued a new endpoint signing secret; it was shown once.",
        audit_summary={"grace_minutes": grace},
    )


CRM_ENDPOINT_ACT: Final = ActionTool(
    name="crm_endpoint_act",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="outbound_webhook",
    audit_action="integration_endpoint.changed",
    where="on the Integrations screen",
    schema=action_schema(
        "crm_endpoint_act",
        "Propose switching an endpoint off or issuing it a new signing secret." + PROPOSES_ONLY,
        {
            "endpoint_id": {"type": "string"},
            "action": {
                "type": "string",
                "enum": ["switch_off", "new_secret", "new_secret_retire_old_now"],
            },
        },
    ),
    plan=_plan_endpoint_act,
    execute=_execute_endpoint_act,
)


class _DeliveryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery_id: UUID


async def _plan_delivery_resend(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    del actor
    parsed = parse_args(_DeliveryArgs, args)
    row = (
        await session.execute(
            # Through `outbound_webhooks`, whose RLS is the tenancy: `webhook_deliveries` has
            # no policy of its own (migration 4be32bf3d12c).
            text(
                "SELECT d.event_type, d.status FROM webhook_deliveries d "
                "JOIN outbound_webhooks w ON w.id = d.endpoint_id "
                "WHERE d.id = :id AND d.direction = 'out'"
            ),
            {"id": parsed.delivery_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Delivery")
    if str(row[1]) != "failed":
        raise WriteRefusedError("only a delivery that failed can be sent again")
    return Plan(
        object_id=str(parsed.delivery_id),
        title="Send a failed delivery again",
        summary=(
            f"Send the {row[0] or 'event'} again with the same id and body, so a receiver that "
            "already has it can ignore it."
        ),
        current="failed",
        proposed="sending again",
        cost=None,
        reversal="What is sent cannot be recalled.",
        args={"delivery_id": str(parsed.delivery_id)},
    )


async def _execute_delivery_resend(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`integrations.service.resend_delivery` — the delivery log's Resend."""
    from apps.api.integrations.service import resend_delivery

    del actor
    parsed = parse_args(_DeliveryArgs, args)
    await resend_delivery(session, delivery_id=parsed.delivery_id)
    return Executed(applied=True, detail="It is queued to send again.", audit_summary={})


CRM_DELIVERY_RESEND: Final = ActionTool(
    name="crm_delivery_resend",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="webhook_delivery",
    audit_action="webhook_delivery.resent",
    where="on the Integrations screen",
    schema=action_schema(
        "crm_delivery_resend",
        "Propose resending one failed delivery (id from `integrations_status`)." + PROPOSES_ONLY,
        {"delivery_id": {"type": "string"}},
    ),
    plan=_plan_delivery_resend,
    execute=_execute_delivery_resend,
)


# =========================================================================================
# BILLING SETTINGS (never a payment, never a top-up order)
# =========================================================================================


def _rupees(raw: str | None, *, field: str) -> Decimal | None:
    if raw is None:
        return None
    try:
        value = Decimal(str(raw).replace(",", "").replace("₹", "").strip())
    except InvalidOperation as exc:
        raise WriteRefusedError(f"`{field}` must be rupees in digits, like 2500") from exc
    if value < 0 or value != value.quantize(Decimal("0.01")):
        raise WriteRefusedError(f"`{field}` must be a positive amount with at most paise")
    return value


def _inr(value: Decimal | None) -> str:
    return "none" if value is None else f"₹{value:,.2f}"


class _CapsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cap_spend_inr: str | None = Field(max_length=20)
    cap_minutes: int | None = Field(ge=0, le=100_000)


async def _plan_caps(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    from apps.api.billing.cap_routes import MAX_CLIENT_CAP_SPEND_INR
    from apps.api.billing.caps import read_caps

    parsed = parse_args(_CapsArgs, args)
    spend = _rupees(parsed.cap_spend_inr, field="cap_spend_inr")
    if spend is not None and spend > MAX_CLIENT_CAP_SPEND_INR:
        raise WriteRefusedError("that limit is above ₹10,00,000; ask the person to check it")
    caps = await read_caps(session, tenant_id=actor.tenant_id)
    current = f"{_inr(caps.client_cap_spend)} a month, {caps.client_cap_min or 'no'} minute limit"
    proposed = f"{_inr(spend)} a month, {parsed.cap_minutes or 'no'} minute limit"
    return Plan(
        object_id=str(actor.tenant_id),
        title="Change your spending limit",
        summary=(
            f"Outgoing calls stop for the month at {proposed}. A limit below this month's "
            "spend stops them now. Incoming calls are never stopped. Empty means no limit of "
            "your own; the plan's still applies."
        ),
        current=current,
        proposed=proposed,
        cost=None,
        reversal="Change it again on Credits & billing.",
        args={
            "cap_spend_inr": None if spend is None else str(spend),
            "cap_minutes": parsed.cap_minutes,
        },
    )


async def _execute_caps(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`caps.apply_client_caps` — `PUT /v1/billing/caps`'s call."""
    from apps.api.billing.caps import apply_client_caps

    spend = None if args["cap_spend_inr"] is None else Decimal(str(args["cap_spend_inr"]))
    minutes = None if args["cap_minutes"] is None else int(args["cap_minutes"])
    result = await apply_client_caps(
        session, tenant_id=actor.tenant_id, cap_min=minutes, cap_spend=spend
    )
    detail = "Saved."
    if result.capped_now:
        detail += " Outgoing calls are stopped for the rest of the month."
    return Executed(
        applied=True,
        detail=detail,
        audit_summary={
            "cap_minutes": minutes,
            "cap_spend_inr": None if spend is None else str(spend),
            "capped_now": result.capped_now,
        },
    )


SPEND_CAPS_SET: Final = ActionTool(
    name="spend_caps_set",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="plans",
    audit_action="billing.caps.set",
    where="on Credits & billing",
    schema=action_schema(
        "spend_caps_set",
        "Propose the account's own monthly spending and minute limits; null clears one."
        + PROPOSES_ONLY,
        {
            "cap_spend_inr": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "cap_minutes": _NULLABLE_INT,
        },
    ),
    plan=_plan_caps,
    execute=_execute_caps,
)


class _AutoRechargeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None
    threshold_inr: str | None = Field(max_length=20)
    amount_inr: str | None = Field(max_length=20)
    monthly_cap_inr: str | None = Field(max_length=20)


async def _plan_auto_recharge(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    from apps.api.billing.auto_recharge import read_auto_recharge

    parsed = parse_args(_AutoRechargeArgs, args)
    state = await read_auto_recharge(session, tenant_id=actor.tenant_id)
    enabled = state.enabled if parsed.enabled is None else parsed.enabled
    threshold = _rupees(parsed.threshold_inr, field="threshold_inr") or state.threshold_inr
    amount = _rupees(parsed.amount_inr, field="amount_inr") or state.amount_inr
    cap = _rupees(parsed.monthly_cap_inr, field="monthly_cap_inr") or state.monthly_cap_inr
    if enabled and state.mandate_status != "confirmed":
        raise WriteRefusedError(
            "auto-recharge needs an automatic payment method approved first, which the person "
            "does themselves on Credits & billing; the assistant never sets up payments"
        )

    def words(on: bool, th: Decimal, am: Decimal, mc: Decimal) -> str:
        return (
            f"on: add {_inr(am)} when below {_inr(th)}, at most {_inr(mc)} a month" if on else "off"
        )

    return Plan(
        object_id=str(actor.tenant_id),
        title="Change auto-recharge",
        summary=(
            "Auto-recharge "
            + words(enabled, threshold, amount, cap)
            + ". Each recharge is charged to the payment method you approved."
        ),
        current=words(state.enabled, state.threshold_inr, state.amount_inr, state.monthly_cap_inr),
        proposed=words(enabled, threshold, amount, cap),
        cost=(
            f"Up to {_inr(cap)} a month is charged automatically while it is on."
            if enabled
            else None
        ),
        reversal="Turn it off on Credits & billing; a recharge already started still lands.",
        args={
            "enabled": enabled,
            "threshold_inr": str(threshold),
            "amount_inr": str(amount),
            "monthly_cap_inr": str(cap),
        },
    )


async def _execute_auto_recharge(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`auto_recharge.save_auto_recharge` — `PUT /v1/billing/auto-recharge`'s call, which
    refuses switching on without a confirmed mandate."""
    from apps.api.billing.auto_recharge import save_auto_recharge
    from apps.api.billing.service import to_paise

    state = await save_auto_recharge(
        session,
        tenant_id=actor.tenant_id,
        enabled=bool(args["enabled"]),
        threshold_inr=to_paise(Decimal(str(args["threshold_inr"]))),
        amount_inr=to_paise(Decimal(str(args["amount_inr"]))),
        monthly_cap_inr=to_paise(Decimal(str(args["monthly_cap_inr"]))),
        actor_user_id=actor.user_id,
    )
    return Executed(
        applied=True,
        detail="Auto-recharge is on." if state.enabled else "Auto-recharge is off.",
        audit_summary={"enabled": state.enabled},
    )


AUTO_RECHARGE_SET: Final = ActionTool(
    name="auto_recharge_set",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="auto_recharge",
    audit_action="billing.auto_recharge.saved",
    where="on Credits & billing",
    schema=action_schema(
        "auto_recharge_set",
        "Propose switching auto-recharge on or off or changing its amounts (rupees as "
        "digits; null keeps one). Never sets up a payment method." + PROPOSES_ONLY,
        {
            "enabled": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
            "threshold_inr": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "amount_inr": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "monthly_cap_inr": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
    ),
    plan=_plan_auto_recharge,
    execute=_execute_auto_recharge,
)


class _AlertArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold_inr: str | None = Field(max_length=20)


async def _plan_alert(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    from apps.api.billing.service import LOW_BALANCE_INR, chosen_low_balance_line
    from apps.api.tenancy.models import LOW_BALANCE_ALERT_MAX_INR

    parsed = parse_args(_AlertArgs, args)
    value = _rupees(parsed.threshold_inr, field="threshold_inr")
    if value is not None and value > LOW_BALANCE_ALERT_MAX_INR:
        raise WriteRefusedError("that warning line is above ₹1,00,000; ask the person to check it")
    chosen = await chosen_low_balance_line(session, tenant_id=actor.tenant_id)

    def words(line: Decimal | None) -> str:
        if line is None:
            return f"below {_inr(LOW_BALANCE_INR)} (Calevate's)"
        return "off" if line == 0 else f"below {_inr(line)}"

    return Plan(
        object_id=str(actor.tenant_id),
        title="Change the low-credit warning",
        summary=f"You are warned when credit falls {words(value)}. Running out is always warned.",
        current=words(chosen),
        proposed=words(value),
        cost=None,
        reversal="Undo puts the previous line back.",
        args={"threshold_inr": None if value is None else str(value)},
    )


async def _execute_alert(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`billing.service.set_low_balance_line` —
    `PUT /v1/billing/wallet/low-balance-alert`'s call."""
    from apps.api.billing.service import set_low_balance_line

    raw = args["threshold_inr"]
    value = None if raw is None else Decimal(str(raw))
    previous = await set_low_balance_line(session, tenant_id=actor.tenant_id, threshold_inr=value)
    return Executed(
        applied=previous != value,
        detail="Saved.",
        audit_summary={"threshold_inr": None if value is None else str(value)},
    )


async def _capture_alert(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> dict[str, Any]:
    from apps.api.billing.service import chosen_low_balance_line

    del args
    chosen = await chosen_low_balance_line(session, tenant_id=actor.tenant_id)
    return {"threshold_inr": None if chosen is None else str(chosen)}


async def _invert_alert(session: AsyncSession, actor: ToolActor, record: UndoRecord) -> str:
    from apps.api.billing.service import set_low_balance_line

    row = (
        await session.execute(
            text("SELECT low_balance_alert_inr FROM organizations WHERE id = :t FOR UPDATE"),
            {"t": actor.tenant_id},
        )
    ).first()
    now = None if row is None or row[0] is None else str(Decimal(str(row[0])))
    if now != record.result_state.get("threshold_inr"):
        raise UndoRefusedError("the warning line was changed since, so it was left as it is")
    prior = record.prior_state.get("threshold_inr")
    await set_low_balance_line(
        session,
        tenant_id=actor.tenant_id,
        threshold_inr=None if prior is None else Decimal(str(prior)),
    )
    return "The low-credit warning is back to what it was."


LOW_BALANCE_ALERT_SET: Final = ActionTool(
    name="low_balance_alert_set",
    tier="immediate",
    undo=Undo(capture=_capture_alert, invert=_invert_alert),
    permission="org:manage",
    object_type="organization",
    audit_action="billing.low_balance_alert.set",
    where="on Credits & billing",
    schema=action_schema(
        "low_balance_alert_set",
        "Set the balance below which the person is warned credit is low (rupees as digits; "
        '"0" turns it off; null returns to Calevate\'s).' + DOES_IT,
        {"threshold_inr": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
    ),
    plan=_plan_alert,
    execute=_execute_alert,
)


async def _plan_ai_extra(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    from apps.api.billing.ai_quota import AI_OVERAGE_BLOCK_INR, read_ai_quota

    del args
    quota = await read_ai_quota(session, tenant_id=actor.tenant_id)
    if quota.extra_unavailable is not None:
        reasons = {
            "not_at_ceiling": "this month's included AI help is not used up yet",
            "already_purchased": "the extra AI help was already added this month",
            "not_prepaid": "this account is invoiced, so it has no wallet to pay from",
            "platform_paused": "AI help is paused for everyone right now",
            "month_ending": "the month ends within the hour; ask again next month",
        }
        raise WriteRefusedError(
            "extra AI help cannot be added: "
            + reasons.get(quota.extra_unavailable, quota.extra_unavailable)
        )
    return Plan(
        object_id=quota.month,
        title="Add more AI help this month",
        summary=f"Add the extra AI help block for {quota.month}, paid from your credit.",
        current=None,
        proposed=_inr(AI_OVERAGE_BLOCK_INR),
        cost=f"{_inr(AI_OVERAGE_BLOCK_INR)} from your credit now.",
        reversal="It cannot be refunded once added.",
        args={"accept_amount_inr": str(AI_OVERAGE_BLOCK_INR)},
    )


async def _execute_ai_extra(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`ai_quota.purchase_ai_overage` — `POST /v1/billing/ai-quota/extra`'s call, which
    compares the amount the card showed before anything moves."""
    from apps.api.billing.ai_quota import purchase_ai_overage

    result = await purchase_ai_overage(
        session,
        tenant_id=actor.tenant_id,
        accepted_amount_inr=Decimal(str(args["accept_amount_inr"])),
    )
    return Executed(
        applied=result.charged,
        detail="Added." if result.charged else "It was already added this month.",
        audit_summary={"month": result.quota.month, "amount_inr": str(result.amount_inr)},
    )


AI_ALLOWANCE_EXTRA: Final = ActionTool(
    name="ai_allowance_extra",
    tier="confirm",
    undo=None,
    permission="org:manage",
    object_type="credit_ledger",
    audit_action="billing.ai_quota.extra_accepted",
    where="on Credits & billing",
    schema=action_schema(
        "ai_allowance_extra",
        "Propose adding this month's extra AI help, paid from credit." + PROPOSES_ONLY,
        {},
    ),
    plan=_plan_ai_extra,
    execute=_execute_ai_extra,
)


#: Registration order is wire order (the cacheable prompt prefix). New actions APPEND.
ACCOUNT_ACTIONS: Final[tuple[ActionTool, ...]] = (
    NUMBER_ASSIGN,
    FORWARDING_LINE_ADD,
    FORWARDING_LINE_CHANGE,
    FORWARDING_LINE_REMOVE,
    FORWARDING_LINE_TEST,
    TEAM_INVITE,
    TEAM_MEMBER_ROLE,
    TEAM_MEMBER_REMOVE,
    TEAM_INVITATION,
    LINE_PROTECTION_PHONE,
    LEAD_SOURCE_CREATE,
    LEAD_SOURCE_EDIT,
    LEAD_SOURCE_SWITCH,
    LEAD_SOURCE_ROTATE,
    LEAD_CALLING_RULES,
    HELD_LEAD_DECIDE,
    CRM_ENDPOINT_CREATE,
    CRM_ENDPOINT_EDIT,
    CRM_ENDPOINT_ACT,
    CRM_DELIVERY_RESEND,
    SPEND_CAPS_SET,
    AUTO_RECHARGE_SET,
    LOW_BALANCE_ALERT_SET,
    AI_ALLOWANCE_EXTRA,
)


__all__ = [
    "ACCOUNT_ACTIONS",
]
