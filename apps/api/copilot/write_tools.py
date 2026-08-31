"""The copilot's WRITE surface: three tools that change nothing, and the one door that does.

═══ THE PRINCIPLE, BECAUSE EVERY LINE BELOW IS A CONSEQUENCE OF IT ═══

Human-in-the-loop here is a GOVERNANCE control, not a trust control. The difference is
where the confirmation trigger lives. If it lived in the prompt ("ask the user before you
change anything") it would be a request to a text generator, and OWASP GenAI LLM Top 10
2026 LLM01 #4 says in as many words to hold state-change capability in application code
rather than in the model. So it lives HERE: a write tool has no code path that mutates
anything. It reads, it describes, and it returns a PROPOSAL. The mutation is in
`confirm()`, which is reached only by a second, separately authenticated HTTP request that
a person's click produces.

That is why the three tools are `plan` functions and not `do` functions, and why the
registry below carries the executor as a SEPARATE callable: a reviewer can check the
no-mutation property by reading three short functions, without having to trace a flag.

═══ WHAT A PROPOSAL IS ═══

A signed JWT, and nothing else. There is NO proposals table, and the reason has to be
stated properly now that `memory.py` exists: this package DOES persist something, so
"nothing here persists" is no longer the argument and citing it would be citing a sentence
`copilot/__init__.py` has since corrected. The argument is the one that survived that
change — a durable store is a PRICE (a retention category, an erasure arm, a redaction
guard, an RLS policy), and it is paid where it buys something. One redacted memory row per
answered question buys recall across conversations. A table of PENDING INTENTS about a
person's leads buys nothing a five-minute token does not already give: it would exist to
hold state for a decision that is either made in the next few minutes or abandoned, and
every row of it would be a new thing for DPDP erasure and retention to enumerate.
Everything the confirm step needs is inside the token, and the token is worthless without
the confirmer's own session.

The token binds FOUR things, and each one closes a specific attack:

* `sub` = the tenant. A proposal minted inside tenant A is refused against tenant B's
  session (hard rule 1). This is checked in `confirm()` BEFORE anything is executed, so a
  cross-tenant confirm is refused ahead of RLS — and RLS is still behind it.
* `act.sub` = the person. A proposal minted for one member of a tenant cannot be confirmed
  by another; the audit row then names an actor who really did decide.
* `tool` + `args` = the intent, verbatim. The browser cannot widen "mark lead X hot" into
  "mark every lead won" because the arguments are inside the signature, not in the confirm
  body. THE CONFIRM BODY CARRIES NO PARAMETERS AT ALL — only the token.
* `exp` = `PROPOSAL_TTL` from minting. A proposal a person left open in a tab overnight is
  not a decision they are still making.

Replay is closed separately, because a signature cannot close it: a valid token is valid
until it expires, so the same one would confirm twice. `jti` is consumed ONCE in Redis
(`SET NX`), and — unlike `core/auth._first_read_in_window`, which fails towards RECORDING
because it guards an audit trail — this one FAILS CLOSED. A Redis outage refuses the
confirm; it does not permit a double execution. Suppressing a number twice is harmless,
but "pause, then resume, then a replayed pause" is not, and the direction has to be chosen
once for all three tools rather than per tool.

═══ THE KEY ═══

`_signing_key()` derives a purpose-separated subkey from `IMPERSONATION_GRANT_SECRET`
rather than adding a fifth deployment secret. See its docstring: the objection D-85 raised
to derivation (coupled ROTATION SCHEDULES) does not reach a token whose whole life is five
minutes.

═══ WHERE PERMISSION IS ENFORCED — TWICE, AND ONLY THE SECOND ONE COUNTS ═══

`plan_write` checks the tool's permission so the model is not offered a proposal the person
could never confirm; `confirm` checks it again, against the session that actually arrives.
The propose-time check is ADVISORY — it is a UX property, and a token minted a second
before a role change must not be a way to spend the old role. The confirm-time check is the
gate. Both go through `_may`, which is `core/auth.requires`'s ladder (role table, then
D-22's read-only refusal for a mutating permission) written once rather than approximated.

═══ AND THE GATE THAT WAS ALREADY THERE ═══

Every executor calls the SAME service function the human's button calls —
`crm.service.update_lead`, `compliance.dnc.add_numbers`, `campaigns.service.
set_campaign_status`. Not a copy of its body, not a "fast path", not a variant with a flag.
So every refusal those functions make — the CAS 409 on a campaign that is not running, the
404 that is also RLS's answer for a neighbour's row, the DNC recall that D-428(b) requires
before a suppression counts as honoured — happens on this path exactly as it happens on
that one, because it IS that path. Hard rule 5's "never add a bypass" is satisfied
structurally: there is no second implementation to keep in step.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID

import jwt
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns import service as campaigns_service
from apps.api.compliance import dnc
from apps.api.compliance.audit import write_audit
from apps.api.copilot.prompt import function_tool
from apps.api.copilot.sanitize import strip_invisible
from apps.api.copilot.schemas import CopilotConfirmOut, CopilotProposalEvent
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import MUTATING_PERMISSIONS, Permission, role_has
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings, resolve_hmac_key
from apps.api.crm import service as crm_service
from apps.api.crm.schemas import LeadStatus
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session

log = get_logger(__name__)

#: The one audience this token is minted for and the only one it is accepted under.
#: Pinned on decode, so an impersonation grant — the other HS256 token this deployment
#: mints, from the parent of this key — can never be presented here and vice versa.
PROPOSAL_AUDIENCE: Final = "calevate:copilot-proposal"

#: Pinned on encode AND decode. PyJWT makes `algorithms` mandatory on decode for the
#: algorithm-confusion reason `core/impersonation.py` documents; this is the same pin.
PROPOSAL_ALGORITHM: Final = "HS256"

#: FIVE MINUTES, and the number is about ATTENTION rather than about key strength.
#:
#: A proposal is a sentence on somebody's screen saying "shall I do this?". The window
#: that matters is how long that sentence stays a true description of what they were
#: thinking about — a campaign that was running when the proposal was minted may have
#: finished, a lead's status may have moved. Longer would let a tab left open overnight
#: confirm a decision made yesterday against today's data; shorter would expire the
#: proposal while somebody reads it, which is the failure that teaches people to click
#: without reading.
#:
#: The CAS underneath is what makes a stale confirm safe rather than merely unlikely:
#: `set_campaign_status` refuses a campaign that has left `running`, and the lead executor
#: reports honestly when the lead was already in the requested state.
PROPOSAL_TTL: Final = timedelta(minutes=5)

#: Clock skew between API replicas. `core/impersonation.GRANT_CLOCK_SKEW_S`'s number and
#: its reason: both ends of this comparison are our own processes, so this covers NTP
#: drift and nothing else.
PROPOSAL_CLOCK_SKEW_S: Final = 5

#: RFC 8693 §4.1, the same claim `core/impersonation.py` carries: a JSON object whose
#: members identify the actor. One member, `sub`.
ACTOR_CLAIM: Final = "act"

_REQUIRED_CLAIMS: Final = ("exp", "iat", "jti", "sub", "aud", ACTOR_CLAIM, "tool", "args")

#: The Redis key one confirmed proposal burns. Namespaced like every other marker this
#: repo sets (`calevate:adminread:seen:…`), so a `SCAN` during an incident reads.
_JTI_KEY: Final = "calevate:copilot:proposal:used:{jti}"


class WriteRefusedError(Exception):
    """The model asked for a proposal this request cannot mint, in a way it could FIX.

    Sibling of `service.FillRefusedError` and it exists for the same reason: the refusal
    is handed BACK to the model as a tool result so it can correct itself inside the turn
    cap, rather than surfacing to a person as a dead end. A `ProblemError` raised by a
    service function underneath (a 404 lead, a 409 campaign) is NOT this — that is a fact
    about the world the model cannot argue with, and it reaches the person.

    `reason` names ids and shapes, never a value (hard rule 6): it reaches a log line and
    a prompt.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class ToolActor:
    """Who a proposal is minted for. Ids only (hard rule 6).

    A narrowed `Principal`: the two fields the copilot cannot work without are Optional on
    that dataclass (an admin-realm principal has no tenant), and threading `UUID | None`
    into a signing function is how a `None` ends up in a `sub` claim. `actor_for` is the
    one place the narrowing happens and it refuses rather than defaults.
    """

    tenant_id: UUID
    user_id: UUID
    role: str
    impersonating: bool


def actor_for(principal: Principal) -> ToolActor | None:
    """The copilot actor behind this principal, or None if there is not one.

    None is not an error here: `service.run_copilot` is reachable in tests and from callers
    that hold no principal, and a tool that cannot name an actor simply refuses (see
    `plan_write`). Refusing INSIDE the tool rather than by dropping the tool from the
    schema is deliberate — the tool list is the cacheable prompt prefix (`prompt.py`,
    point 1) and must be byte-identical on every request.
    """
    if principal.tenant_id is None or principal.user_id is None or principal.role is None:
        return None
    return ToolActor(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        role=principal.role,
        impersonating=principal.impersonating,
    )


def _may(actor: ToolActor, permission: Permission) -> bool:
    """`core/auth.requires`'s ladder, in a form a non-route caller can ask.

    NOT a re-derivation: the role table is `rbac.role_has` and the D-22 clause is
    `MUTATING_PERMISSIONS`, both imported. A second copy of either would be a second
    answer to "may this person do this", and the two would diverge on the day one of
    them was updated.
    """
    if not role_has(actor.role, permission):
        return False
    return not (actor.impersonating and permission in MUTATING_PERMISSIONS)


# --- the signing key -------------------------------------------------------------------


#: RFC 5869 §2.3's `info`, versioned so a future change of claim shape can be a new label
#: rather than a silent reinterpretation of old tokens.
_KDF_INFO: Final = b"calevate:copilot-proposal:v1"


def _signing_key() -> bytes:
    """A purpose-separated subkey of `IMPERSONATION_GRANT_SECRET`, or a refusal.

    **A DERIVED SUBKEY RATHER THAN A FIFTH DEPLOYMENT SECRET, and D-85 refused exactly
    that derivation for the impersonation grant itself — so the departure is argued, not
    overlooked.** D-85's objection is about ROTATION SCHEDULES: deriving the grant key from
    `AUDIT_CHAIN_SECRET` would have welded a routine credential rotation to a drill, "and
    coupling a routine credential rotation to a drill means it never happens". That
    objection does not reach here. What rotating the parent costs THIS key is that every
    outstanding proposal stops verifying — and a proposal's whole life is `PROPOSAL_TTL`,
    five minutes, on a token that authorises nothing by itself. Nothing is coupled that
    anybody would hesitate over.

    What the derivation buys is the thing a fifth secret would cost: a new
    `/healthz/ready` key, a new deploy-preflight name and a new value an operator must
    generate and inject before this feature works at all — i.e. a feature that ships dark
    on every existing host. The parent is ALREADY demanded by readiness
    (`core/settings.missing_runtime_keys`) and by `scripts/check_deploy_env.py`, so this
    surface fails closed outside `local` on a condition operators already have a runbook
    for.

    Key separation is real rather than nominal: this is HKDF-Expand (RFC 5869 §2.3) with
    `L = 32` — one block, `T(1) = HMAC-SHA256(PRK, info ‖ 0x01)` — under a distinct,
    versioned `info` label. Recovering the parent from it is a preimage on HMAC-SHA256,
    and NIST SP 800-108's KDF-in-counter-mode is the same construction from the other
    standards body. The audience pin above is the second, independent separation: a token
    signed under one label and presented as the other fails `aud` before its signature is
    ever the question.

    THE PARENT IS `IMPERSONATION_GRANT_SECRET` rather than the audit chain's or the
    idempotency key's because it is the same SPECIES of secret — it signs a short-lived,
    non-credential intent token that we mint, hand to our own browser, and verify back.
    The audit chain's key is tamper-evidence over history and must carry a retired
    generation forward; the idempotency key is a pseudonymisation key whose stability is
    client-visible. Neither of those properties belongs to a five-minute token.
    """
    settings = get_settings()
    parent = resolve_hmac_key(
        settings.impersonation_grant_secret,
        env_var="IMPERSONATION_GRANT_SECRET",
        purpose="copilot write proposals",
        code="copilot_proposals_not_configured",
        title="The assistant cannot propose changes",
        local_fallback=f"calevate-local-dev-impersonation-grant-key:{settings.app_env}",
        app_env=settings.app_env,
    )
    return hmac.new(parent, _KDF_INFO + b"\x01", hashlib.sha256).digest()


# --- what a tool produces ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Plan:
    """A described intent. Produced by a READ, and by nothing else.

    `current` and `proposed` are the pair the whole design turns on: a person confirming
    "set this to hot" without being shown that it is already hot, or that it is currently
    won, is not making an informed decision, and a proposal that omitted them would be a
    button with a label instead of a description.

    `args` is the CANONICAL argument dict — normalised by the tool, not the model's raw
    JSON — and it is what gets signed. So what executes is what was described, not what
    was asked for.
    """

    object_id: str
    title: str
    summary: str
    current: str | None
    proposed: str
    args: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Executed:
    """What one confirmed proposal did.

    `applied` is False when the world was ALREADY in the requested state — a real outcome
    and not a failure, the same distinction `set_campaign_status` and `set_lead_status`
    make (D-65). It is reported rather than smoothed over because "I did nothing because
    it was already done" and "I did it" are different answers to the person who asked.
    """

    applied: bool
    detail: str
    audit_summary: dict[str, Any]


#: A tool's read half: session (tenant-scoped, read-only by construction) → described plan.
Planner = Callable[[AsyncSession, "ToolActor", Mapping[str, Any]], Awaitable[Plan]]
#: A tool's write half, reached ONLY from `confirm`.
Executor = Callable[[AsyncSession, "ToolActor", Mapping[str, Any]], Awaitable[Executed]]


@dataclass(frozen=True, slots=True)
class WriteTool:
    """One proposable action.

    The `permission` is the one the HUMAN's route already declares for the same act, read
    off that route rather than chosen here: `PATCH /v1/leads/{id}` is `leads:write`,
    `POST /v1/dnc` and `POST /v1/campaigns/{id}/pause` are both `leads:dispatch`. Picking
    a different one would be this feature quietly disagreeing with the console about who
    may do what.
    """

    name: str
    permission: Permission
    object_type: str
    audit_action: str
    schema: Mapping[str, Any]
    plan: Planner
    execute: Executor


def _parse[M: BaseModel](model: type[M], args: Mapping[str, Any]) -> M:
    """Tool arguments as a typed object, or a refusal the model can act on.

    Pydantic's own message is not forwarded: it names internal field paths and can quote
    the offending VALUE, and this string becomes both a log line and a prompt.
    """
    try:
        return model.model_validate(dict(args))
    except ValidationError as exc:
        fields = sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]})
        named = ", ".join(f"`{field}`" for field in fields) or "the arguments"
        raise WriteRefusedError(f"{named} was missing or the wrong shape") from exc


# --- tool 1: lead_set_status ------------------------------------------------------------


class _LeadStatusArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: UUID
    status: LeadStatus


#: How a status reads in a sentence. The wire values are lowercase machine tokens and the
#: proposal is prose a person approves, so "interested" → "Interested" is not decoration.
_LEAD_STATUS_LABELS: Final[dict[str, str]] = {
    "new": "New",
    "contacted": "Contacted",
    "interested": "Interested",
    "hot": "Hot",
    "won": "Won",
    "lost": "Lost",
}


async def _plan_lead_status(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    """READ ONLY. `get_lead` is the 404 (and, under RLS, the neighbour's answer too).

    THE LEAD'S NAME AND NUMBER ARE DELIBERATELY NOT IN THE SUMMARY. They are on the
    person's screen already, and this string is composed by the server, streamed through
    the copilot channel and could be handled by any future consumer of that channel;
    keeping it to ids and statuses means it can never become the place a phone number
    leaks (hard rule 6, `sanitize.py`'s whole subject).
    """
    del actor
    parsed = _parse(_LeadStatusArgs, args)
    lead = await crm_service.get_lead(session, parsed.lead_id)
    current = _LEAD_STATUS_LABELS[lead.status]
    proposed = _LEAD_STATUS_LABELS[parsed.status]
    return Plan(
        object_id=str(parsed.lead_id),
        title="Change this lead's status",
        summary=(
            f"Mark this lead as {proposed}. It is currently {current}. "
            "Nothing changes until you confirm."
        ),
        current=current,
        proposed=proposed,
        args={"lead_id": str(parsed.lead_id), "status": parsed.status},
    )


async def _execute_lead_status(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`crm.service.update_lead` — the function `PATCH /v1/leads/{id}` calls, unchanged.

    The pre-read is what makes `applied` honest. `update_lead` composes three primitives
    and returns the lead, not whether the status moved; reading the row first, in the SAME
    transaction, is one indexed SELECT and is the only way to report "it was already Hot"
    rather than claiming a change that did not happen. `set_lead_status` returns that
    boolean directly, and calling IT instead was the tempting shortcut — it would have
    skipped `update_lead`'s `lead.updated` emission, which is the CRM's own change feed.
    """
    parsed = _parse(_LeadStatusArgs, args)
    before = await crm_service.get_lead(session, parsed.lead_id)
    after = await crm_service.update_lead(
        session,
        parsed.lead_id,
        status=parsed.status,
        name=None,
        actor=str(actor.user_id),
    )
    applied = before.status != after.status
    return Executed(
        applied=applied,
        detail=(
            f"The lead is now marked {_LEAD_STATUS_LABELS[after.status]}."
            if applied
            else f"The lead was already marked {_LEAD_STATUS_LABELS[after.status]}, "
            "so nothing changed."
        ),
        audit_summary={"to_status": parsed.status, "moved": applied},
    )


# --- tool 2: dnc_add --------------------------------------------------------------------


class _DncAddArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: UUID
    #: Two of `compliance/dnc.SOURCES`' four. `call_optout` is written by the in-call
    #: opt-out path and `regulator` by an operator handling a complaint; neither is a thing
    #: a person types into a chat box, and admitting them here would let a copilot
    #: conversation manufacture the provenance of a suppression a regulator may later ask
    #: about.
    reason: Literal["customer_request", "manual"] = "manual"


async def _plan_dnc_add(session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]) -> Plan:
    """READ ONLY, and THE NUMBER IS NAMED BY REFERENCE — never by value.

    This is the constraint that shaped the tool. `sanitize.assert_redacted` refuses any
    request whose text still looks like a phone number (D-127 G-2), so a `dnc_add(phone=…)`
    tool could never be driven: the model cannot be told a number, and must not be. A LEAD
    ID is the reference the screen already has, the server resolves it to E.164 itself, and
    the number never enters the prompt, the token, the log or the audit row.

    `check_number` is asked rather than assumed so the proposal can say whether this
    changes anything — and it mirrors the dispatch gate's own query by construction, so
    the sentence a person approves agrees with the gate that will enforce it.
    """
    parsed = _parse(_DncAddArgs, args)
    phone, _name = await crm_service.lead_phone(session, parsed.lead_id)
    check = await dnc.check_number(session, tenant_id=actor.tenant_id, raw=phone)
    current = "Already on your do-not-call list" if check.suppressed else "Not suppressed"
    return Plan(
        object_id=str(parsed.lead_id),
        title="Stop calling this lead",
        summary=(
            "Add this lead's number to your do-not-call list. "
            f"{current} right now. Calls already queued to it are pulled back as well. "
            "Nothing changes until you confirm."
        ),
        current=current,
        proposed="On your do-not-call list",
        args={"lead_id": str(parsed.lead_id), "reason": parsed.reason},
    )


async def _execute_dnc_add(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`compliance.dnc.add_numbers` — the function `POST /v1/dnc` calls, unchanged.

    Which is the whole point: D-428(b)'s recall enqueue (a suppression is not honoured
    until the dials the vendor is already holding are pulled back) lives INSIDE that
    function, in its transaction, and so it happens here without this module knowing it
    exists. A hand-written INSERT would have been three lines and would have silently
    dropped it.
    """
    parsed = _parse(_DncAddArgs, args)
    phone, _name = await crm_service.lead_phone(session, parsed.lead_id)
    result = await dnc.add_numbers(
        session,
        tenant_id=actor.tenant_id,
        raw_numbers=[phone],
        source=parsed.reason,
    )
    applied = result.added > 0
    return Executed(
        applied=applied,
        detail=(
            "That number is on your do-not-call list, and calls already queued to it are "
            "being pulled back."
            if applied
            else "That number was already on your do-not-call list, so nothing changed."
        ),
        # Counts and the reason, exactly as `dnc_routes.add_numbers` records them. The
        # number is the sensitive part of this act and belongs in no record of it.
        audit_summary={
            "added": result.added,
            "already_suppressed": result.already_suppressed,
            "source": parsed.reason,
        },
    )


# --- tool 3: campaign_pause -------------------------------------------------------------


class _CampaignPauseArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID


async def _plan_campaign_pause(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    """READ ONLY. The campaign's own name is quoted back because "pause the campaign" with
    no name is a sentence a person cannot check, and this is a stop button.

    Stripped of invisible characters on the way out for `sanitize.py`'s egress reason: the
    person approves the string they can SEE, and a tag-block character would make the
    rendered sentence and the signed intent different things.
    """
    del actor
    parsed = _parse(_CampaignPauseArgs, args)
    row = (
        await session.execute(
            text("SELECT name, status FROM campaigns WHERE id = :cid"),
            {"cid": parsed.campaign_id},
        )
    ).first()
    if row is None:
        # RLS makes this the same answer for a neighbour's campaign, deliberately.
        raise ProblemError.not_found("Campaign")
    name, status = strip_invisible(str(row[0])), str(row[1])
    return Plan(
        object_id=str(parsed.campaign_id),
        title="Pause this campaign",
        summary=(
            f"Stop dialling on “{name}”. It is {status} right now. "
            "Contacts already dialled are unaffected; the rest stop. "
            "Nothing changes until you confirm."
        ),
        current=status,
        proposed="paused",
        args={"campaign_id": str(parsed.campaign_id)},
    )


async def _execute_campaign_pause(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`campaigns.service.set_campaign_status` — `POST /v1/campaigns/{id}/pause`'s call,
    with `from_statuses=("running",)` verbatim.

    So the three answers are that primitive's, not this module's: False when it was already
    paused (idempotent, no audit row claiming a second act), a 409 naming the state when
    the campaign is a draft or cancelled, a 404 when no visible campaign has that id. A
    copilot that could pause a cancelled campaign would be a copilot with its own state
    machine.
    """
    del actor
    parsed = _parse(_CampaignPauseArgs, args)
    applied = await campaigns_service.set_campaign_status(
        session,
        campaign_id=parsed.campaign_id,
        to_status="paused",
        from_statuses=("running",),
    )
    return Executed(
        applied=applied,
        detail=(
            "Dialling has stopped on that campaign."
            if applied
            else "That campaign was already paused, so nothing changed."
        ),
        audit_summary={"moved": applied},
    )


# --- the registry -----------------------------------------------------------------------


def _tool_schema(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    """One tool definition in the subset openai-python's `to_strict_json_schema` preserves
    (`prompt.set_fields_tool` argues the subset; this is the same shape so that a reader
    comparing the two finds one convention).

    A FUNCTION rather than three dict literals so the envelope — `strict`, every property
    required, `additionalProperties: false` — cannot drift between the tools. The ORDER of
    keys is insertion order and is pinned by `write_tools_test.py`, because the tool block
    is part of the cacheable prompt prefix and a reordering is a cache miss on every
    request.

    WHAT IS THIS MODULE'S AND WHAT IS THE PACKAGE'S: the ENVELOPE is
    `prompt.function_tool`, spelled once for `set_fields`, for the read tools and for
    these. What stays here is the PARAMETERS object, because "every property is required"
    is a fact about the write tools specifically — none of them has an optional argument,
    and a read tool expresses an optional one as `anyOf: [T, null]` instead.
    """
    return function_tool(
        name=name,
        description=description,
        parameters={
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    )


#: Said at the end of every write tool's description. The confirmation trigger is in code
#: — this sentence is not what makes it true — but a model that believes it has ACTED will
#: tell the person it has, and that lie is the one thing the code cannot prevent.
_PROPOSES_ONLY: Final = (
    " This does NOT do it. It shows the person exactly what would change and waits for "
    "them to confirm. Say that you have suggested it, never that you have done it."
)

LEAD_SET_STATUS: Final = WriteTool(
    name="lead_set_status",
    permission="leads:write",
    object_type="lead",
    # A new action name, in `number.dlt_status_set`'s spelling. The human `PATCH
    # /v1/leads/{id}` writes NO audit row at all — a gap this path does not inherit,
    # because an action a machine proposed needs a record naming the person who agreed.
    audit_action="lead.status_set",
    schema=_tool_schema(
        "lead_set_status",
        "Propose changing one lead's status (new, contacted, interested, hot, won, lost)."
        + _PROPOSES_ONLY,
        {
            "lead_id": {
                "type": "string",
                "description": "The lead's id, taken from the SCREEN STATE. Never invented.",
            },
            "status": {
                "type": "string",
                "enum": list(_LEAD_STATUS_LABELS),
                "description": "The status to move the lead to.",
            },
        },
    ),
    plan=_plan_lead_status,
    execute=_execute_lead_status,
)

DNC_ADD: Final = WriteTool(
    name="dnc_add",
    permission="leads:dispatch",
    object_type="lead",
    audit_action="dnc.added",
    schema=_tool_schema(
        "dnc_add",
        "Propose adding one lead's phone number to this business's do-not-call list, so "
        "the platform stops calling them. Identify the lead by id — you are never told a "
        "phone number and must never ask for one." + _PROPOSES_ONLY,
        {
            "lead_id": {
                "type": "string",
                "description": (
                    "The lead whose number should be suppressed, taken from the SCREEN "
                    "STATE. The server looks the number up itself."
                ),
            },
            "reason": {
                "type": "string",
                "enum": ["customer_request", "manual"],
                "description": (
                    "`customer_request` when the person said the customer asked not to be "
                    "called; `manual` otherwise."
                ),
            },
        },
    ),
    plan=_plan_dnc_add,
    execute=_execute_dnc_add,
)

CAMPAIGN_PAUSE: Final = WriteTool(
    name="campaign_pause",
    permission="leads:dispatch",
    object_type="campaign",
    audit_action="campaign.paused",
    schema=_tool_schema(
        "campaign_pause",
        "Propose pausing a running campaign, so it stops dialling." + _PROPOSES_ONLY,
        {
            "campaign_id": {
                "type": "string",
                "description": "The campaign's id, taken from the SCREEN STATE.",
            }
        },
    ),
    plan=_plan_campaign_pause,
    execute=_execute_campaign_pause,
)

#: Registration order is wire order and is therefore part of the cacheable prefix. New
#: tools APPEND; they never insert.
WRITE_TOOLS: Final[tuple[WriteTool, ...]] = (LEAD_SET_STATUS, DNC_ADD, CAMPAIGN_PAUSE)

_BY_NAME: Final[dict[str, WriteTool]] = {tool.name: tool for tool in WRITE_TOOLS}


def write_tool_schemas() -> list[dict[str, Any]]:
    """Every write tool's definition, in registration order — the SAME list on every
    request, for every tenant, for every role.

    **GATING BY VARYING THIS LIST IS THE ONE THING THAT MUST NOT HAPPEN.** It is the
    obvious implementation of "don't offer what they cannot do" and it would give this
    feature a prompt-cache hit rate of zero (`prompt.py`, point 1) while making the prompt
    prefix a function of the caller's role — two costs for a UX nicety. The refusal lives
    inside `plan_write` instead, where it is also enforceable.
    """
    return [dict(tool.schema) for tool in WRITE_TOOLS]


def is_write_tool(name: str) -> bool:
    return name in _BY_NAME


# --- proposing ---------------------------------------------------------------------------


async def plan_write(
    name: str, raw_arguments: str, *, actor: ToolActor | None
) -> CopilotProposalEvent:
    """One write tool call → one signed proposal. READS ONLY.

    ITS OWN SHORT `tenant_session`, opened and closed here. `copilot/routes.py`'s "NO
    `Depends(db)`" is a property of a STREAMING route — a pooled Postgres connection must
    not be held across a provider round trip — and this call happens BETWEEN two of them,
    so it takes a connection, reads, and gives it back before the next model turn.

    THE PERMISSION CHECK HERE IS ADVISORY (module docstring). It exists so the person is
    not shown a proposal they will be refused at the door; `confirm` is the gate.
    """
    tool = _BY_NAME.get(name)
    if tool is None:  # pragma: no cover - the loop only routes registered names here
        raise WriteRefusedError(f"`{name}` is not a tool you have")
    if actor is None:
        raise WriteRefusedError(
            f"`{name}` needs a signed-in account and this session has none, "
            "so nothing can be proposed"
        )
    if not _may(actor, tool.permission):
        raise WriteRefusedError(
            f"this person's role may not do what `{name}` proposes, so do not offer it"
        )
    try:
        parsed_arguments = json.loads(raw_arguments or "")
    except ValueError as exc:
        raise WriteRefusedError("the tool call was not valid JSON") from exc
    if not isinstance(parsed_arguments, dict):
        raise WriteRefusedError("the tool call was not an object")

    async with tenant_session(actor.tenant_id) as session:
        plan = await tool.plan(session, actor, parsed_arguments)

    issued_at = datetime.now(UTC)
    # Floored to whole seconds so the `expires_at` the browser is told is exactly the `exp`
    # the verifier will enforce — `core/impersonation.mint_grant`'s reason, and the same
    # class of bug (a console that re-asks one second too late).
    expires_at = (issued_at + PROPOSAL_TTL).replace(microsecond=0)
    claims: dict[str, Any] = {
        "aud": PROPOSAL_AUDIENCE,
        "sub": str(actor.tenant_id),
        ACTOR_CLAIM: {"sub": str(actor.user_id)},
        "jti": str(uuid7()),
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "tool": tool.name,
        # The CANONICAL arguments, not the model's raw JSON: what executes is what was
        # described. `obj` rides alongside so the confirm route can name the target in its
        # audit row without re-parsing a tool-specific shape.
        "args": plan.args,
        "obj": plan.object_id,
    }
    return CopilotProposalEvent(
        token=jwt.encode(claims, _signing_key(), algorithm=PROPOSAL_ALGORITHM),
        tool=tool.name,
        title=plan.title,
        summary=strip_invisible(plan.summary),
        object_type=tool.object_type,
        object_id=plan.object_id,
        current=plan.current,
        proposed=plan.proposed,
        expires_at=expires_at,
    )


# --- confirming -------------------------------------------------------------------------


def _refused(code: str, detail: str, remediation: str) -> ProblemError:
    """Every confirm refusal, one shape. 403 (`kind="permission"`) across the board, and
    deliberately the SAME body for a forged token as for an expired one: distinguishing
    them for the caller would turn this endpoint into an oracle about which half of a
    token is wrong."""
    return ProblemError(
        kind="permission",
        code=code,
        title="That change could not be confirmed",
        detail=detail,
        remediation=remediation,
    )


@dataclass(frozen=True, slots=True)
class _VerifiedProposal:
    tool: WriteTool
    jti: str
    args: Mapping[str, Any]
    object_id: str


def _verify(token: str, *, actor: ToolActor) -> _VerifiedProposal:
    """Signature, audience, expiry, tenant, actor, tool — in one call, refusing on any.

    THE TENANT AND ACTOR COMPARISONS ARE THE POINT and they are here rather than in the
    route so that no future caller can reach `execute` having checked only the signature.
    A token is a description of an intent; WHOSE intent is half the description.
    """
    try:
        claims = jwt.decode(
            token,
            _signing_key(),
            algorithms=[PROPOSAL_ALGORITHM],
            audience=PROPOSAL_AUDIENCE,
            leeway=PROPOSAL_CLOCK_SKEW_S,
            options={"require": list(_REQUIRED_CLAIMS)},
        )
    except jwt.PyJWTError as exc:
        # The exception CLASS only: a decode failure's message can quote the token.
        log.info("copilot_proposal_rejected", extra={"error": type(exc).__name__})
        raise _refused(
            "copilot_proposal_invalid",
            "This suggestion is no longer valid.",
            "Ask the assistant again — nothing has been changed.",
        ) from exc

    tool = _BY_NAME.get(str(claims.get("tool")))
    if tool is None:
        raise _refused(
            "copilot_proposal_invalid",
            "This suggestion refers to something the assistant can no longer do.",
            "Ask the assistant again — nothing has been changed.",
        )
    if str(claims["sub"]) != str(actor.tenant_id):
        # Hard rule 1, in front of RLS rather than instead of it. Ids only, and warned
        # rather than info'd: a proposal crossing accounts is an event somebody should
        # be able to find.
        log.warning(
            "copilot_proposal_wrong_tenant",
            extra={"tenant_id": str(actor.tenant_id), "tool": tool.name},
        )
        raise _refused(
            "copilot_proposal_invalid",
            "This suggestion was made for a different account.",
            "Ask the assistant again from this account.",
        )
    actor_claim = claims.get(ACTOR_CLAIM)
    if not isinstance(actor_claim, dict) or str(actor_claim.get("sub")) != str(actor.user_id):
        raise _refused(
            "copilot_proposal_invalid",
            "This suggestion was made for someone else.",
            "Ask the assistant yourself — nothing has been changed.",
        )
    args = claims.get("args")
    if not isinstance(args, dict):  # pragma: no cover - `require` already demands it
        raise _refused(
            "copilot_proposal_invalid",
            "This suggestion is no longer valid.",
            "Ask the assistant again — nothing has been changed.",
        )
    return _VerifiedProposal(
        tool=tool, jti=str(claims["jti"]), args=args, object_id=str(claims.get("obj", ""))
    )


async def _burn(jti: str) -> None:
    """Consume this proposal's id, once. FAILS CLOSED.

    `SET NX` with a TTL one skew-window past `PROPOSAL_TTL`, so the marker outlives every
    token that could still verify and is then reaped — an unbounded set of ids would be a
    slow leak in a store this repo explicitly does not use as a system of record.

    **THE FAILURE DIRECTION IS THE OPPOSITE OF `core/auth._first_read_in_window`'s, and
    the contrast is the argument.** That marker guards an AUDIT trail, so a Redis outage
    must degrade into noise (write the row twice) rather than into silence. This one
    guards EXECUTION, so an outage must degrade into a refusal rather than into a second
    dial being pulled back, a second pause racing a resume, or any other act a person
    approved once. Both are one line; picking the wrong line is the whole bug.
    """
    key = _JTI_KEY.format(jti=jti)
    ttl = int(PROPOSAL_TTL.total_seconds()) + PROPOSAL_CLOCK_SKEW_S
    try:
        first = await get_redis().set(key, "1", nx=True, ex=ttl)
    except Exception as exc:
        log.warning("copilot_proposal_replay_guard_unavailable")
        raise ProblemError(
            kind="dependency",
            code="copilot_confirm_unavailable",
            title="That change could not be confirmed",
            detail="The assistant could not check that this suggestion is still unused.",
            remediation="Try again in a moment — nothing has been changed.",
        ) from exc
    if not first:
        raise _refused(
            "copilot_proposal_already_used",
            "This suggestion has already been confirmed.",
            "Check the record — the change was made the first time.",
        )


async def confirm(
    session: AsyncSession,
    token: str,
    *,
    principal: Principal,
    ip: str | None,
) -> CopilotConfirmOut:
    """Verify, re-check the permission, burn, execute, audit — in that order.

    **THE ORDER IS THE DESIGN.** The burn comes BEFORE the execution, so a crash between
    the two loses the change rather than allowing it to happen twice; a person can ask
    again, and "it did not happen" is recoverable in a way "it happened twice" is not on
    an append-only ledger and a live dial queue. The cost of that direction is real and is
    accepted: a service function that REFUSES after the burn (a campaign that stopped
    running while the person read the dialog) has spent the token, and the answer is to
    ask again — which is the same answer the CAS gives the button.

    **THE PERMISSION IS CHECKED AGAIN HERE AND THIS IS THE CHECK THAT COUNTS.** The
    propose-time one ran against the role the person held while the model was talking;
    this one runs against the session in front of us. A member demoted between the two is
    refused, and so is an impersonating admin (D-22: `leads:write` and `leads:dispatch`
    are both in `MUTATING_PERMISSIONS`).

    **ONE TRANSACTION FOR THE CHANGE AND ITS AUDIT ROW**, which is `session`'s — the
    route's `Depends(db)`. `write_audit` holds the chain lock from its call to COMMIT, so
    the row and the act it describes commit together or not at all; an execution that
    could not be recorded is one SEC-COMP §5 does not permit.

    NO `Idempotency-Key`. The `jti` burn IS the idempotency, and it is stronger: the
    header protects against a client retrying the same REQUEST, while `jti` protects
    against the same DECISION being submitted twice by any means.
    """
    actor = actor_for(principal)
    if actor is None:  # pragma: no cover - the route's dependency guarantees a tenant
        raise _refused(
            "copilot_proposal_invalid",
            "This suggestion cannot be confirmed by this session.",
            "Sign in to the account the suggestion was made for.",
        )
    proposal = _verify(token, actor=actor)
    if not _may(actor, proposal.tool.permission):
        raise ProblemError.forbidden("You do not have permission to do this.")
    # THE BURN SITS IMMEDIATELY BEFORE THE EXECUTION and nothing may be inserted between
    # them: everything that can refuse has refused by here, so a burnt proposal is one
    # that was really about to run. The permission check is above it for that reason —
    # consuming a token in order to answer "you may not" would spend a decision nobody
    # got to make.
    await _burn(proposal.jti)

    executed = await proposal.tool.execute(session, actor, proposal.args)
    await write_audit(
        session,
        action=proposal.tool.audit_action,
        actor=principal,
        tenant_id=actor.tenant_id,
        object_type=proposal.tool.object_type,
        object_id=proposal.object_id or None,
        ip=ip,
        # Ids, names and counts (hard rule 6). `via` is what separates this row from the
        # identical act performed by a click — the ledger reads the same for both, and
        # answers "did a person or the assistant suggest this" without a second action
        # name to keep in step.
        summary={"via": "copilot", "tool": proposal.tool.name, **executed.audit_summary},
    )
    return CopilotConfirmOut(
        tool=proposal.tool.name,
        object_type=proposal.tool.object_type,
        object_id=proposal.object_id,
        applied=executed.applied,
        detail=executed.detail,
    )


__all__ = [
    "ACTOR_CLAIM",
    "CAMPAIGN_PAUSE",
    "DNC_ADD",
    "LEAD_SET_STATUS",
    "PROPOSAL_ALGORITHM",
    "PROPOSAL_AUDIENCE",
    "PROPOSAL_CLOCK_SKEW_S",
    "PROPOSAL_TTL",
    "WRITE_TOOLS",
    "Executed",
    "Plan",
    "ToolActor",
    "WriteRefusedError",
    "WriteTool",
    "actor_for",
    "confirm",
    "is_write_tool",
    "plan_write",
    "write_tool_schemas",
]
