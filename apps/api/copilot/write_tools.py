"""The copilot's WRITE surface: four tools that change nothing, and the one door that does.

═══ THE PRINCIPLE, BECAUSE EVERY LINE BELOW IS A CONSEQUENCE OF IT ═══

Human-in-the-loop here is a GOVERNANCE control, not a trust control. The difference is
where the confirmation trigger lives. If it lived in the prompt ("ask the user before you
change anything") it would be a request to a text generator, and OWASP GenAI LLM Top 10
2026 LLM01 #4 says in as many words to hold state-change capability in application code
rather than in the model. So it lives HERE: a write tool has no code path that mutates
anything. It reads, it describes, and it returns a PROPOSAL. The mutation is in
`confirm()`, which is reached only by a second, separately authenticated HTTP request that
a person's click produces.

That is why the tools are `plan` functions and not `do` functions, and why the registry
below carries the executor as a SEPARATE callable: a reviewer can check the no-mutation
property by reading four short functions, without having to trace a flag.

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
but "pause, then resume, then a replayed pause" is not, and a replayed `propose_knowledge`
is a duplicate source in somebody's review queue. The direction is chosen once for every
tool rather than per tool.

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
set_campaign_status`, `kb.service.submit_source`. Not a copy of its body, not a "fast
path", not a variant with a flag. So every refusal those functions make — the CAS 409 on a
campaign that is not running, the 404 that is also RLS's answer for a neighbour's row, the
DNC recall that D-428(b) requires before a suppression counts as honoured, the
preview-and-approve queue a knowledge submission joins — happens on this path exactly as it
happens on that one, because it IS that path. Hard rule 5's "never add a bypass" is
satisfied structurally: there is no second implementation to keep in step.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Final, Literal
from uuid import UUID

import jwt
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.write_guard import assert_agent_writable
from apps.api.campaigns import service as campaigns_service
from apps.api.compliance import dnc
from apps.api.compliance.audit import write_audit
from apps.api.copilot.actions import (
    PROPOSES_ONLY,
    ActionTier,
    ActionTool,
    Executed,
    Plan,
    ToolActor,
    WriteRefusedError,
    action_schema,
    actor_for,
    may_act,
    parse_args,
)
from apps.api.copilot.agent_actions import AGENT_ACTIONS
from apps.api.copilot.sanitize import strip_invisible
from apps.api.copilot.schemas import (
    CopilotActionEvent,
    CopilotConfirmOut,
    CopilotProposalEvent,
)
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings, resolve_hmac_key
from apps.api.crm import service as crm_service
from apps.api.crm.schemas import LeadStatus
from apps.api.db.base import uuid7
from apps.api.db.ownership import assert_visible
from apps.api.db.session import tenant_session
from apps.api.kb import proposals as kb_proposals
from apps.api.reliability.service import (
    claim_idempotency,
    complete_idempotency,
    fail_idempotency,
    scope_key,
)

#: **`WriteTool` IS `actions.ActionTool` AND THE OLD NAME IS KEPT ON PURPOSE.** The type
#: moved to `actions.py` when the registry grew a second leaf module (`agent_actions.py`)
#: and a shared vocabulary had to live somewhere neither could import in a cycle. Renaming
#: it at the same time would have made one change read as two; the alias is what keeps
#: `copilot/service.py`, the tests and every reader's `grep` pointing at one thing.
WriteTool = ActionTool

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


# THE TYPES THAT USED TO BE DEFINED HERE NOW LIVE IN `copilot/actions.py`:
# `WriteRefusedError`, `ToolActor`, `actor_for`, `may_act` (which was `_may`), `Plan`,
# `Executed`, `Planner`, `Executor`, `ActionTool` (which was `WriteTool`), `parse_args`
# (which was `_parse`) and `action_schema` (which was `_tool_schema`). They moved unchanged
# apart from `Plan.cost` / `Plan.reversal` and `ActionTool.tier`, because a SECOND leaf
# module of actions (`agent_actions.py`) now shares them and two leaves cannot import each
# other. Nothing about the mechanism changed with the address; this file still owns the
# token, the burn, the confirm door and the four tools that shipped first.


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
    parsed = parse_args(_LeadStatusArgs, args)
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
        # A CRM label move: nothing is dialled, nothing is billed, and the previous status
        # is on the card the person just read, which is what makes the reversal exact
        # rather than a reassurance.
        cost=None,
        reversal=f"Set it back to {current} on the lead's own screen at any time.",
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
    parsed = parse_args(_LeadStatusArgs, args)
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
    parsed = parse_args(_DncAddArgs, args)
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
        cost=None,
        # HONEST IN THE NEGATIVE DIRECTION. A suppression is removable, but the dials it
        # pulls back are gone from the queue, and a person told simply "reversible" would
        # believe a paused campaign resumes where it stopped.
        reversal=(
            "You can take the number off your do-not-call list from the Do not call "
            "screen. Calls it pulled out of the queue are not put back."
        ),
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
    parsed = parse_args(_DncAddArgs, args)
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
    parsed = parse_args(_CampaignPauseArgs, args)
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
        # Pausing SAVES money rather than costing it, and saying "no cost" would be the
        # wrong half of that. `None` is "nothing is charged for doing this", which is true.
        cost=None,
        reversal=(
            "You can start it again from the campaign screen. Calls already placed cannot "
            "be recalled."
        ),
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
    parsed = parse_args(_CampaignPauseArgs, args)
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


# --- tool 4: propose_knowledge ----------------------------------------------------------
#
# THE ONE TOOL WHOSE ACT IS ITSELF A PROPOSAL, AND IT STILL RIDES THIS MACHINE. Confirming
# it does not teach an agent anything: it creates a `pending_approval` source that a human
# approves and publishes on the ADMIN surface afterwards. So the person clicking Confirm is
# agreeing to put words into a review queue, and the review is unchanged and untouched.
#
# That is why it is here rather than in a lane of its own. It shipped once as a second
# propose→confirm system — its own token format, its own `POST /v1/kb/proposals/confirm`,
# its own audit write, its own `WriteTool` type — and both were correct; two of them was
# the defect. `kb/proposals.py` keeps what is the knowledge base's (what may be drafted,
# which gaps may be cited, the one door into `kb_sources`) exactly as `crm`, `compliance`
# and `campaigns` keep theirs above.


#: The longest `topic_key` that could ever be legitimate, DERIVED from the closed set
#: `gap_refusal` judges against rather than chosen — so it can never be set too small, and
#: a key added to that set carries its own bound with it.
#:
#: BOUNDED HERE BECAUSE THE REFUSAL QUOTES IT. `gap_refusal` answers an unrecognised key
#: with "`<key>` is not a recognised knowledge-gap topic", and that sentence becomes a tool
#: result and then part of the next turn's prompt (`service._with_tool_result`). Every
#: OTHER argument on this tool is already bounded — `name` and `body` by
#: `proposable_refusal`, the rest by their types — so this was the one place a model could
#: be talked into putting an arbitrarily long attacker-chosen string into its own next
#: prompt. `parse_args`' refusal names the FIELD and never the value, which is the whole
#: point of routing it through Pydantic instead of through the echo.
#: ⚠ DERIVED FROM THE CANONICAL KEYS ALONE, THIS WAS TOO TIGHT AND REFUSED A REAL INPUT.
#: `insights/detection._topic` emits `q_<up to three caller words>` when no canonical
#: keyword matches, and those are longer than any canonical key. Bounding the INPUT at the
#: longest canonical key made a legitimate `q_*` citation fail as "missing or the wrong
#: shape" instead of "not a recognised topic" — the wrong reason, and the one that does not
#: tell the model to stop citing caller wording. The real risk was never the input's length
#: but the ECHO's, and that is bounded where the echo happens
#: (`kb/proposals._ECHO_CHARS`). This cap stays as a sanity bound on an argument that
#: reaches a query, generous enough to admit anything this system can itself produce.
_MAX_TOPIC_KEY: Final = 128


class _ProposeKnowledgeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    name: str
    body: str
    #: Provenance shown to whoever approves it, and the founder shipped BOTH: `gap_digest`
    #: is "your agent noticed callers keep asking this", `copilot` is "you and the
    #: assistant were talking and this came up". They carry different trust and they vary
    #: no gate. It is signed into the token as part of `args`, so the browser cannot
    #: relabel a conversation as a detection between the proposal and the confirm.
    origin: kb_proposals.ProposalOrigin
    #: The canonical knowledge-gap topic this answers, or null. REQUIRED when `origin` is
    #: `gap_digest`: a provenance claim with nothing to point at is one the system cannot
    #: support. Length-bounded — see `_MAX_TOPIC_KEY`; membership is `gap_refusal`'s
    #: question and is deliberately not asked twice.
    topic_key: Annotated[str, Field(max_length=_MAX_TOPIC_KEY)] | None


async def _plan_propose_knowledge(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    """READ ONLY, and the reads are authorization reads: the agent must be visible to this
    tenant's session, and a cited gap must be open on it.

    Every refusal here is a `WriteRefusedError` rather than a `ProblemError`, EXCEPT the
    404 `assert_visible` raises — and that split is the one this module already draws. A
    body carrying a phone number, a title too long for a card, a `q_*` topic slugged out of
    a caller's question, a gap that is not open: all of those the model can fix inside the
    turn by asking the person a better question. An agent id that names nothing this tenant
    can see is a fact about the world, and it is `crm_service.get_lead`'s 404 by another
    name.

    THE SUMMARY QUOTES THE DRAFTED TITLE AND NOT THE BODY. The title is a handful of words
    the person is about to own; the body is up to 4,000 characters and belongs in the card
    the browser renders from `proposed`, not in a sentence that is also logged.
    """
    parsed = parse_args(_ProposeKnowledgeArgs, args)
    if parsed.origin == "gap_digest" and parsed.topic_key is None:
        raise WriteRefusedError(
            "a suggestion presented as something the agent noticed must name the topic "
            "it noticed, so pass `topic_key` or use the `copilot` origin"
        )
    refusal = kb_proposals.proposable_refusal(parsed.name, parsed.body)
    if refusal is not None:
        raise WriteRefusedError(refusal)
    await assert_visible(session, "agent", parsed.agent_id)
    if parsed.topic_key is not None:
        gap = await kb_proposals.gap_refusal(
            session, agent_id=parsed.agent_id, topic_key=parsed.topic_key
        )
        if gap is not None:
            raise WriteRefusedError(gap)
    name = strip_invisible(parsed.name.strip())
    return Plan(
        object_id=str(parsed.agent_id),
        title="Add this to your agent's knowledge",
        summary=(
            f"Save “{name}” to this agent's knowledge. It goes to review first and the "
            "agent cannot use it until it is approved. Nothing changes until you confirm."
        ),
        # Nothing is being replaced — a submission is a new VERSION of a named source, and
        # `None` is the honest answer to "what is it now" rather than a sentence invented
        # to fill the field.
        current=None,
        proposed=name,
        cost=None,
        reversal=(
            "Nothing reaches a caller until somebody approves it. Whoever reviews it can "
            "reject it, and you can edit or remove it under Knowledge afterwards."
        ),
        args={
            "agent_id": str(parsed.agent_id),
            "name": name,
            "body": strip_invisible(parsed.body.strip()),
            "origin": parsed.origin,
            "topic_key": parsed.topic_key,
        },
    )


async def _execute_propose_knowledge(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`kb.service.submit_source`, through `kb_proposals.submit_proposed_source` — the
    function `POST /v1/kb/sources` calls, with the same arguments.

    `applied` is unconditionally True, and it is the one executor where that is right
    rather than lazy: the other three ask the world to reach a state it may already be in,
    while this one appends a new source VERSION. Submitting the same wording twice is two
    versions, both of which a reviewer sees; there is no "it was already like that".

    The content guard runs again on what the signature carried back — see
    `proposable_refusal` on why twice — and a failure here is a `ProblemError`, not a
    `WriteRefusedError`: no model is listening at confirm time, and the person needs a
    sentence rather than the loop needing a retry.
    """
    parsed = parse_args(_ProposeKnowledgeArgs, args)
    refusal = kb_proposals.proposable_refusal(parsed.name, parsed.body)
    if refusal is not None:  # pragma: no cover - the signature proves this ran at propose
        raise ProblemError(
            kind="validation",
            code="kb_proposal_not_proposable",
            title="That suggestion cannot be saved",
            detail="The assistant's suggestion is no longer something it may write.",
            remediation="Add it yourself under Knowledge in your dashboard.",
        )
    await assert_visible(session, "agent", parsed.agent_id)
    created = await kb_proposals.submit_proposed_source(
        session,
        tenant_id=actor.tenant_id,
        actor_id=actor.user_id,
        agent_id=parsed.agent_id,
        name=parsed.name,
        body=parsed.body,
    )
    return Executed(
        applied=True,
        detail=(
            "That knowledge is saved and waiting for review. The agent starts using it "
            "once it is approved."
        ),
        # IDS, COUNTS AND CLOSED-SET STRINGS (hard rules 4 and 6). Not the title, not the
        # body: `audit_log` is append-only, so text written into it is text a DPDP erasure
        # cannot reach, and the `kb_sources` row is where the words live and where deletion
        # already gets to them. `origin` is here because an owner reviewing the queue has to
        # tell "your agent noticed this" from "this came up in conversation"; the realm is
        # NOT, because `write_audit` derives `actor_type` from the principal and hashes it
        # into the chain, and a second spelling of the same fact is a second thing to keep
        # in step.
        audit_summary={
            "source_id": str(created["id"]),
            "agent_id": str(parsed.agent_id),
            "version": created["version"],
            "chunks": created["chunks"],
            "status": created["status"],
            "origin": parsed.origin,
            "topic_key": parsed.topic_key,
        },
    )


# --- the registry -----------------------------------------------------------------------


LEAD_SET_STATUS: Final = WriteTool(
    name="lead_set_status",
    # TIER 2, AND IT IS THE ONE OF THE FOUR WHERE THAT IS A JUDGEMENT RATHER THAN A
    # DEDUCTION. Moving a lead to `lost` reaches no caller and spends nothing, so the
    # tier rule alone would admit `immediate`. It stays `confirm` because the founder's
    # instruction was to keep the existing confirmable ones confirmable: people have
    # already learned that this assistant asks before it touches their leads, and quietly
    # taking the click away is a promise withdrawn without anybody being told.
    tier="confirm",
    permission="leads:write",
    object_type="lead",
    # A new action name, in `number.dlt_status_set`'s spelling. The human `PATCH
    # /v1/leads/{id}` writes NO audit row at all — a gap this path does not inherit,
    # because an action a machine proposed needs a record naming the person who agreed.
    audit_action="lead.status_set",
    where="on the lead's own screen",
    schema=action_schema(
        "lead_set_status",
        "Propose changing one lead's status (new, contacted, interested, hot, won, lost)."
        + PROPOSES_ONLY,
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
    # TIER 2 — it stops dials that are already queued at the vendor, which is a change to
    # what happens on a phone line.
    tier="confirm",
    permission="leads:dispatch",
    object_type="lead",
    audit_action="dnc.added",
    where="on the Do not call screen",
    schema=action_schema(
        "dnc_add",
        "Propose adding one lead's phone number to this business's do-not-call list, so "
        "the platform stops calling them. Identify the lead by id — you are never told a "
        "phone number and must never ask for one." + PROPOSES_ONLY,
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
    # TIER 2 — a stop button on live dialling. It is the SAFE direction, and it is still a
    # click, because a campaign somebody is watching must not stop because a sentence was
    # read a certain way.
    tier="confirm",
    permission="leads:dispatch",
    object_type="campaign",
    audit_action="campaign.paused",
    where="on the campaign's own screen",
    schema=action_schema(
        "campaign_pause",
        "Propose pausing a running campaign, so it stops dialling." + PROPOSES_ONLY,
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

PROPOSE_KNOWLEDGE: Final = WriteTool(
    name="propose_knowledge",
    # TIER 2, AND THE FOUNDER'S TIER 1 LIST SAYS "draft knowledge". The two are reconciled
    # by the sentence in the same instruction that says to keep the existing confirmable
    # ones confirmable: this tool shipped confirmable, and what it drafts is words a
    # business owner OWNS and a reviewer will read as theirs. Re-tiering it is a decision
    # somebody can take later in one line; taking it here, off an inference, is not.
    tier="confirm",
    # `kb:write` — what the "Add knowledge" form already declares. Deciding what the agent
    # knows is ONE permission (D-21), and the gate is the PERMISSION rather than a role
    # name, so widening who may curate is one line in `rbac.py` and never a line here.
    permission="kb:write",
    # The AGENT, not the source: the source does not exist when the proposal is minted, and
    # `obj` is signed at plan time. The created `kb_sources` id rides in the audit summary
    # instead, so the row still answers "which source did this produce".
    object_type="agent",
    audit_action="kb.source_proposed",
    where="under Knowledge, in the review queue",
    schema=action_schema(
        "propose_knowledge",
        "Propose adding a fact to one agent's knowledge, so it can answer that question in "
        "future. Only for something the person has just told you about their own business "
        "— never invent a price, a policy or an opening time, and never repeat something a "
        "caller said. Confirming puts it in the review queue; it is NOT live until "
        "somebody approves it." + PROPOSES_ONLY,
        {
            "agent_id": {
                "type": "string",
                "description": "The agent's id, taken from the SCREEN STATE. Never invented.",
            },
            "name": {
                "type": "string",
                "description": (
                    "A short title for this knowledge, e.g. 'Saturday opening hours'. At "
                    f"most {kb_proposals.MAX_NAME_CHARS} characters."
                ),
            },
            "body": {
                "type": "string",
                "description": (
                    "What the agent should know, in the words the person used. Write it "
                    "the way you would tell a new receptionist. Do not include phone "
                    "numbers, email addresses or identity numbers."
                ),
            },
            "origin": {
                "type": "string",
                "enum": list(kb_proposals.PROPOSAL_ORIGINS),
                "description": (
                    "`gap_digest` when you are answering a knowledge gap the agent "
                    "reported; `copilot` when the person simply volunteered the fact."
                ),
            },
            "topic_key": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": (
                    "The recognised knowledge-gap topic this answers: "
                    + ", ".join(sorted(kb_proposals.CITABLE_TOPIC_KEYS))
                    + ". REQUIRED with the `gap_digest` origin. Null otherwise — never a "
                    "topic made out of what one caller asked."
                ),
            },
        },
    ),
    plan=_plan_propose_knowledge,
    execute=_execute_propose_knowledge,
)

#: Registration order is wire order and is therefore part of the cacheable prefix. New
#: tools APPEND; they never insert.
WRITE_TOOLS: Final[tuple[ActionTool, ...]] = (
    LEAD_SET_STATUS,
    DNC_ADD,
    CAMPAIGN_PAUSE,
    PROPOSE_KNOWLEDGE,
    # D-500's build/publish/launch actions, appended in their own registration order. They
    # live in `agent_actions.py` because they are about agents and campaigns rather than
    # about tokens, and they join THIS tuple rather than a second one: `service.tool_array`
    # composes from `write_tool_schemas()`, `plan_write`, `run_immediate` and `confirm` all
    # resolve through `_BY_NAME`, and a second registry would be a second answer to "what
    # may the assistant do".
    *AGENT_ACTIONS,
)

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


def tier_of(name: str) -> ActionTier | None:
    """Which gate this action stands behind, or `None` if there is no such action.

    **THE ONE PLACE THE TIER IS READ, AND IT IS READ FROM THE REGISTRY.** `service.py`
    dispatches on this and on nothing else: not on a flag in the arguments, not on a
    property of the object, and above all not on anything the model said. A mis-tiered
    action is a campaign launched without a click, so the answer has exactly one source and
    that source is a required field with no default (`actions.ActionTier`).
    """
    tool = _BY_NAME.get(name)
    return None if tool is None else tool.tier


def immediate_tool_names() -> frozenset[str]:
    """The Tier 1 actions, derived. For tests and for `service.py`'s own assertions — a
    hand-kept list of "the ones that run without a click" is the drift this function
    exists to make impossible."""
    return frozenset(tool.name for tool in WRITE_TOOLS if tool.tier == "immediate")


# --- proposing ---------------------------------------------------------------------------


async def _refuse_a_deleted_agent(
    session: AsyncSession, tool: WriteTool, args: Mapping[str, Any]
) -> None:
    """The assistant's half of the one refusal: no write tool acts on a DELETED agent.

    THE SAME RULE AS THE API'S, AT THE SAME KIND OF CHOKE POINT. `core/auth.requires()`
    refuses a mutating HTTP request whose path names a retired agent; this is the copilot's
    equivalent, because the assistant does not go through a route — it calls the service
    functions directly, so it would otherwise inherit only whatever check each of those
    happens to make. `agent_rename` had none: `lifecycle.update_agent` refused it, but only
    AFTER the person had been shown a card describing the rename and had pressed Confirm.

    IT RUNS AT PLAN TIME (and at claim time for Tier 1), which is what stops the assistant
    OFFERING the edit. A refusal at execute is a correct answer to the wrong question.

    Keyed on the tool's declared `object_type` plus an `agent_id` argument, so `agent_create`
    — which has no subject yet — is untouched and a future agent tool is covered the day it
    is registered. A `WriteRefusedError` rather than a `ProblemError`: this is something the
    model must relay in words, not retry around.
    """
    if tool.object_type != "agent":
        return
    raw = args.get("agent_id")
    if not isinstance(raw, str):
        return
    try:
        agent_id = UUID(raw)
    except ValueError:
        # A malformed id is the planner's own refusal to make, with a better message.
        return
    try:
        await assert_agent_writable(session, agent_id)
    except ProblemError as exc:
        raise WriteRefusedError(
            "that agent has been deleted, so nothing about it can be changed — tell the "
            "person it is deleted and that restoring it from the Agents screen is the one "
            "thing that would let it be edited again, and do not offer to change it"
        ) from exc


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

    **AND IT MINTS A TOKEN ONLY FOR A `confirm` TOOL.** The loop already dispatches on the
    tier, so the guard below is unreachable through it — which is exactly why it is here.
    It is the second of the two halves that keep the tiers from leaking into each other,
    and it fails in the safe direction: a Tier 1 action mis-routed to this function
    produces no token and no change, where the reverse mistake would produce a change with
    no click.
    """
    tool = _BY_NAME.get(name)
    if tool is None:  # pragma: no cover - the loop only routes registered names here
        raise WriteRefusedError(f"`{name}` is not a tool you have")
    if tool.tier != "confirm":  # pragma: no cover - `service.py` dispatches on the tier
        raise WriteRefusedError(f"`{name}` is not something this app asks you to propose")
    if actor is None:
        raise WriteRefusedError(
            f"`{name}` needs a signed-in account and this session has none, "
            "so nothing can be proposed"
        )
    try:
        parsed_arguments = json.loads(raw_arguments or "")
    except ValueError as exc:
        raise WriteRefusedError("the tool call was not valid JSON") from exc
    if not isinstance(parsed_arguments, dict):
        raise WriteRefusedError("the tool call was not an object")

    async with tenant_session(actor.tenant_id) as session:
        # THE PERMISSION CHECK MOVED INSIDE THIS BLOCK when `_may` became session-aware
        # (see its docstring: `kb:write` is the role table PLUS the owner's switch, which
        # is a row). It is still the FIRST thing that happens under the session and still
        # runs before `tool.plan` reads anything, so the order the refusals arrive in is
        # unchanged — only where the connection is opened moved.
        if not await may_act(session, actor, tool.permission):
            raise WriteRefusedError(
                f"this person's role may not do what `{name}` proposes, so do not offer it"
            )
        await _refuse_a_deleted_agent(session, tool, parsed_arguments)
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
    # EVERY RENDERED FIELD IS STRIPPED HERE, and it used to be three of the six.
    #
    # `summary`, `cost` and `reversal` were stripped and `title`, `current` and `proposed`
    # were not — on the reasoning that each planner strips what it interpolates, which is
    # true of all seven today (`_plan_campaign_pause` and `_plan_agent_rename` say so in
    # their own docstrings). It is the wrong place for the guarantee to live. `proposed` is
    # the field the card renders as "what this becomes", so it is the LAST one that should
    # depend on a future tool author remembering; and the approval model here is that a
    # person authorises the string they can see, which fails silently the moment a rendered
    # value and a signed one can differ (`sanitize.py`, the egress half). One pass over the
    # whole event costs nothing measurable and makes the property structural rather than
    # conventional. The planners keep their own strips — they need them for the SIGNED
    # `args`, which this cannot reach.
    return CopilotProposalEvent(
        token=jwt.encode(claims, _signing_key(), algorithm=PROPOSAL_ALGORITHM),
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
    )


# --- running, without a click (TIER 1) ---------------------------------------------------


#: The `route` an immediate action's idempotency record is filed under. Not an HTTP route
#: and deliberately not shaped like one: `idempotency_records` is keyed on
#: `(scope_key, route, method, idempotency_key)`, and filing an action under a path that
#: also exists in the API would put two different mechanisms in one namespace.
_ACTION_ROUTE: Final = "copilot:action/{tool}"

#: The `method` column's value for every one of them. `POST` would have been a lie: nothing
#: here arrives over HTTP.
_ACTION_METHOD: Final = "ACTION"


def conversation_seed(question: str, history: Sequence[str]) -> str:
    """A stable fingerprint of WHICH CONVERSATION this is, for the idempotency key.

    **THE KEY MUST BE DERIVED FROM THINGS THAT DO NOT CHANGE ON RETRY, AND THIS IS THE
    HARD HALF OF THAT.** The obvious ingredients are wrong in both directions: the metering
    ref (`billing/ai_quota.new_assist_ref`) is minted per ATTEMPT, so a retry gets a new one
    and the guard protects nothing; a bare `uuid4` is worse. A turn INDEX is wrong too — the
    model may reach the same action on a different turn of an otherwise identical run, and
    a key that moved with the turn would let the second run create a second agent.

    What genuinely does not change when a person re-asks the same thing is the CONVERSATION:
    the question they typed and the turns the browser replayed with it. So the key is
    `(this conversation, this tool, these canonical arguments)`, which is content-derived in
    the sense the pattern requires — the same request produces the same key however many
    times it is sent, and a genuinely new request (a new question, or a different argument)
    produces a different one and is allowed through.

    IT IS NOT A UNIVERSAL DUPLICATE GUARD AND MUST NOT BE READ AS ONE. A person who asks
    "create an outbound agent" twice, an hour apart, in two conversations, gets two agents —
    which is correct, because that is two decisions. What it stops is the mechanical
    duplicate: a dropped stream re-asked, a double submit, the same run re-entered.
    `_plan_agent_create`'s name check is what stops the human duplicate, and the two are
    deliberately different mechanisms because they are different failures.

    HASHED RATHER THAN CARRIED. The question is a person's own words and the history is a
    conversation; neither belongs in a column, and `scope_key` already establishes that this
    table stores fingerprints rather than content (§4).
    """
    digest = hashlib.sha256()
    for part in (question, *history):
        # LENGTH-PREFIXED, so ("ab", "c") and ("a", "bc") are different conversations. A
        # plain concatenation is the classic way a digest over a list stops being injective.
        encoded = part.encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _action_key(seed: str, tool: WriteTool, args: Mapping[str, Any]) -> str:
    """`(conversation, tool, arguments)` as one hex key.

    THE ARGUMENTS AS THE MODEL SENT THEM, key-sorted — not the planner's canonical ones, and
    that ordering is the whole reason this works. The claim has to come BEFORE the plan: a
    planner READS, and `_plan_agent_create`'s read is a duplicate-NAME check that the first
    attempt's own agent would fail on the retry. Keying on the canonical arguments would
    have meant planning first, which means the replay path for a create is unreachable and
    a re-asked question answers "you already have an agent called that" instead of "that is
    already done".

    The cost is exact and small: two spellings of one request (`"  Reception "` and
    `"Reception"`) are two keys. A retry replays the same tool call, so the spelling does
    not change on the path this guards; and if a model does re-word it, the planner's own
    duplicate check catches it and tells the model. Two mechanisms, each covering what the
    other cannot — the mechanical duplicate and the human one.

    `sort_keys` because dict order is not part of the intent.
    """
    digest = hashlib.sha256()
    digest.update(seed.encode())
    digest.update(b"\x00")
    digest.update(tool.name.encode())
    digest.update(b"\x00")
    digest.update(json.dumps(args, sort_keys=True, default=str).encode())
    return digest.hexdigest()


async def run_immediate(
    name: str,
    raw_arguments: str,
    *,
    principal: Principal | None,
    seed: str,
    ip: str | None,
) -> CopilotActionEvent:
    """One TIER 1 action: describe it, claim it, do it, record it. IN THAT ORDER.

    **THIS IS THE FUNCTION THE FOUNDER'S RISK TIERING BUYS, AND EVERY CONTROL A TIER 2
    ACTION HAS IS STILL HERE EXCEPT THE CLICK.** Spelled out, because "runs without
    confirmation" reads like "runs without checks" and it is not:

    * The PERMISSION is checked, against the same `may_act` ladder `confirm` uses and
      against the permission the equivalent button declares. A staff member without
      `org:manage` is refused here, inside the tool, exactly as `run_read_tool` refuses.
    * D-22 still holds: `org:manage` is in `MUTATING_PERMISSIONS`, so an impersonating
      operator in a read-only view-as session cannot create anything.
    * RLS still holds: the executor runs in a `tenant_session` for the actor's own tenant.
    * The PLANNER still runs first, and it still only READS. So the arguments that execute
      are the canonical ones it returned, not the model's, and its refusals (a blank name,
      a name already taken) happen before anything is written.
    * An `audit_log` row is written IN THE SAME TRANSACTION as the change. No click does
      not mean no record; `via: copilot` and `tier: immediate` are what tell a later reader
      which of the two paths it came down.
    * An idempotency record is claimed BEFORE the executor runs, so a retry cannot
      double-create.

    What is NOT here is a token, and it is not missing — it would be meaningless. A
    proposal token exists to survive the gap between the description and the click, and
    there is no gap: this is one call inside one request the person already authenticated.

    **THE SESSION IS THIS FUNCTION'S OWN AND IT WRAPS EVERYTHING.** `copilot/routes.py` holds
    no pooled connection across a provider round trip, and this call happens BETWEEN two of
    them. The claim, the execution and the audit row are one transaction: an action that
    could not be recorded is one SEC-COMP §5 does not permit, and a claim that committed
    without its execution would burn the key for a change that never happened.

    Raises `WriteRefusedError` for anything the model can fix and lets a `ProblemError` from
    the service function underneath through untouched — `service.py` reports both back to
    the model so it can relay the refusal and its remediation rather than retrying around it.
    """
    tool = _BY_NAME.get(name)
    if tool is None:  # pragma: no cover - the loop only routes registered names here
        raise WriteRefusedError(f"`{name}` is not a tool you have")
    if tool.tier != "immediate":
        # THE HALF THAT MATTERS. `plan_write`'s mirror image, and this is the direction in
        # which a mistake would be an incident: a `confirm` tool reaching this function
        # would be a campaign launched with no click. The loop dispatches on the tier and
        # can never route one here; this is the guard that makes that a property of the
        # code rather than of the loop's control flow.
        raise WriteRefusedError(
            f"`{name}` is a change this app asks a person to confirm, so it cannot be run "
            "directly — propose it instead"
        )
    actor = None if principal is None else actor_for(principal)
    if actor is None or principal is None:
        raise WriteRefusedError(
            f"`{name}` needs a signed-in account and this session has none, so nothing was done"
        )
    try:
        parsed_arguments = json.loads(raw_arguments or "")
    except ValueError as exc:
        raise WriteRefusedError("the tool call was not valid JSON") from exc
    if not isinstance(parsed_arguments, dict):
        raise WriteRefusedError("the tool call was not an object")

    async with tenant_session(actor.tenant_id) as session:
        if not await may_act(session, actor, tool.permission):
            raise WriteRefusedError(
                f"this person's role may not do what `{name}` does, so tell them rather "
                "than trying it another way"
            )
        await _refuse_a_deleted_agent(session, tool, parsed_arguments)
        # THE CLAIM COMES FIRST, BEFORE THE PLANNER READS ANYTHING. See `_action_key`: a
        # planner's read can itself be a duplicate check that the first attempt's own row
        # would fail, so planning ahead of the claim makes the replay path unreachable.
        # It also means a replay costs one indexed read rather than a plan.
        key = _action_key(seed, tool, parsed_arguments)
        claim = await claim_idempotency(
            session,
            scope=scope_key(tenant_id=actor.tenant_id, user_id=actor.user_id),
            route=_ACTION_ROUTE.format(tool=tool.name),
            method=_ACTION_METHOD,
            key=key,
            # THE KEY IS ALREADY THE BODY'S DIGEST, so the "same key, different body" 409
            # `claim_idempotency` raises is unreachable from here by construction. Passing
            # the same value is the honest spelling of that rather than an unrelated
            # constant that would look like a second fact.
            request_hash=key,
        )
        if claim.state == "replay":
            # EVERYTHING THE RECEIPT NEEDS IS IN THE STORED PAYLOAD, which is why the
            # completion below writes four keys rather than two: this arm has no plan to
            # read a title or a reversal sentence off, and composing fresh ones from
            # today's world would be a second account of one act.
            stored = claim.response_payload or {}
            log.info("copilot_action_replayed", extra={"tool": tool.name})
            return CopilotActionEvent(
                tool=tool.name,
                title=strip_invisible(str(stored.get("title", ""))) or tool.name,
                detail=(strip_invisible(str(stored.get("detail", ""))) or "That was already done."),
                object_type=tool.object_type,
                object_id=str(stored.get("object_id", "")),
                # FALSE, ALWAYS, ON A REPLAY. `applied` answers "did THIS call change
                # anything", and this one did not: the first one did.
                applied=False,
                reversal=strip_invisible(str(stored.get("reversal", ""))),
                where=tool.where,
            )

        # READ, DESCRIBE, NORMALISE — and only now, with the key held.
        try:
            plan = await tool.plan(session, actor, parsed_arguments)
        except Exception:
            # A REFUSED PLAN MUST NOT BURN THE KEY. The commonest one is a
            # `WriteRefusedError` the model is about to fix and call again with different
            # arguments — but a blank name corrected to a real one is a DIFFERENT key, and
            # the same arguments retried after a transient read failure must still be
            # allowed through. Releasing here costs one CAS and removes a class of
            # "nothing happened and it will not let me try again".
            await fail_idempotency(session, record_id=claim.record_id)
            raise

        try:
            executed = await tool.execute(session, actor, plan.args)
        except Exception:
            # RELEASE THE KEY so the person's own retry is not refused by a claim that
            # holds nothing. `fail_idempotency` is a CAS on `processing` and never raises;
            # the original exception carries on to `service.py` untouched.
            await fail_idempotency(session, record_id=claim.record_id)
            raise
        object_id = executed.object_id or plan.object_id
        await write_audit(
            session,
            action=tool.audit_action,
            actor=principal,
            tenant_id=actor.tenant_id,
            object_type=tool.object_type,
            object_id=object_id or None,
            ip=ip,
            # Ids, names and counts (hard rule 6). `via` separates this row from the same
            # act performed by a click, and `tier` says which of the assistant's two paths
            # it came down — the difference between "a person clicked Confirm" and "a
            # person asked and this ran", which is the first question an auditor has.
            summary={
                "via": "copilot",
                "tier": tool.tier,
                "tool": tool.name,
                **executed.audit_summary,
            },
        )
        await complete_idempotency(
            session,
            record_id=claim.record_id,
            response_status=200,
            response_payload={
                "detail": executed.detail,
                "object_id": object_id,
                "title": plan.title,
                "reversal": plan.reversal,
            },
        )
    log.info(
        "copilot_action_ran",
        # The tool and the outcome. Never the arguments and never the detail: both can
        # carry a client's own business copy (hard rule 6).
        extra={"tool": tool.name, "applied": executed.applied, "tier": tool.tier},
    )
    # STRIPPED FOR `plan_write`'s reason, and here it is a receipt rather than a request
    # for permission: `executed.detail` quotes an agent's name back at the person
    # (`agent_actions._execute_agent_rename`), so it is client-authored text on its way to
    # the DOM. The names it quotes came off `plan.args`, which the planner already
    # stripped; this is the seam that holds when a future executor composes one some other
    # way.
    return CopilotActionEvent(
        tool=tool.name,
        title=strip_invisible(plan.title),
        detail=strip_invisible(executed.detail),
        object_type=tool.object_type,
        object_id=object_id,
        applied=executed.applied,
        reversal=strip_invisible(plan.reversal),
        where=tool.where,
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
    if tool is None or tool.tier != "confirm":
        # **THE TIER IS RE-READ HERE, FROM THE REGISTRY, AT CONFIRM TIME.** A token minted
        # while a tool was `confirm` must not survive that tool being re-tiered, and the
        # direction of the refusal is the point: this endpoint's whole job is to be the
        # click, so an action that no longer needs one has no business arriving through it.
        # Same body as an unknown tool, deliberately — see `_refused`.
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
    if not await may_act(session, actor, proposal.tool.permission):
        # `ProblemError.forbidden` carries NO `remediation`, and every failure a person can
        # reach owes them one (BACKEND-PATTERNS §3). This one is reachable by two ordinary
        # routes — a member demoted while the assistant was talking, and a D-22 view-as
        # session — and "you do not have permission" with no next step leaves somebody
        # staring at a card they cannot act on. Same kind, same code, same 403: only the
        # sentence is added.
        raise ProblemError(
            kind="permission",
            code="forbidden",
            title="Forbidden",
            detail="You do not have permission to make this change.",
            remediation="Ask an owner or manager on this account to confirm it instead.",
        )
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
        # The egress strip the proposal card and the action receipt get, on the third and
        # last surface that renders an executor's prose to a person.
        detail=strip_invisible(executed.detail),
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
    "PROPOSE_KNOWLEDGE",
    "WRITE_TOOLS",
    "ActionTier",
    "ActionTool",
    "Executed",
    "Plan",
    "ToolActor",
    "WriteRefusedError",
    "WriteTool",
    "actor_for",
    "confirm",
    "conversation_seed",
    "immediate_tool_names",
    "is_write_tool",
    # Exported because the EXECUTORS re-parse the signed arguments through it, so it is
    # part of this module's contract rather than an implementation detail — and a test that
    # proves a refusal is refused has to reach the same door the executor does.
    "parse_args",
    "plan_write",
    "run_immediate",
    "tier_of",
    "write_tool_schemas",
]
