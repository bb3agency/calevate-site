"""`POST /v1/admin/copilot/ask` — the OPERATOR's assistant, streamed, paid for by us.

**THIS ROUTE CLOSES THE DEFERRAL `copilot/routes.py` WROTE DOWN.** That file refused the
admin realm with one line and named the reason: *"an admin-realm copilot would either spend
the founder's Azure credential with no ledger row — which hard rule 7 forbids in as many
words — or charge whichever client's page happened to be open for an operator's typing …
what closes it is a platform-payer AI ledger in `billing/`, which is a money surface with
its own migration and its own append-only rules."* The ledger is `platform_ai_usage`
(migration `f2c81a4d05e7`), the writer is `billing/platform_ai.py`, and the founder settled
the objection's own question in the direction it was arguing for: **you never charge a
client for your own support work**, so an operator's copilot spend lands on the platform
ledger whether they are on a console screen or inside a client's view-as session.

## WHY A SECOND ROUTE RATHER THAN A REALM BRANCH IN THE FIRST

`/v1/copilot/ask` is `realm="any"`, and `current_any` resolves the ADMIN realm only when an
impersonation header is present — an operator on `/admin/ops` sends none, so that route
cannot see them at all. It is not a branch that was declined; it is a door that does not
open. Two routes also keep the two realms' contracts separate where they genuinely differ:
this one takes `tenant_id` (which account is open) and returns an operator's assistant, and
`ADMIN_REALM_PREFIXES` makes `realm="admin"` mandatory for anything under `/v1/admin/`.

Everything the two share is shared for real: one `service.run_copilot`, one tool loop, one
metering discipline, one SSE contract. What differs is composed once, per realm, in
`service.tool_array` / `service.build_messages` / this file's payer.

## THE PAYER, IN ONE PARAGRAPH

`require_platform_ai` (the platform brake, which is the only ceiling this surface has —
there is no operator allowance to sell) → run → `meter_platform_assist` → two
`platform_ai_usage` rows under `ASSIST_FEATURE_ADMIN_COPILOT` and one bump of the SAME
`platform_ai_spend` counter the tenant meter moves. No `usage_events` row is written on any
path in this file, and no tenant's `AiQuota` is read or moved. That is the property a
reader should check first, and `tests/admin_copilot_billing_test.py` states it as an
assertion over both ledgers rather than as this sentence.

## D-22 IS INTACT AND THIS ROUTE IS REACHABLE INSIDE A VIEW-AS SESSION

`copilot:admin` is in `MUTATING_PERMISSIONS` (asking spends real money) AND in
`rbac.IMPERSONATION_PERMITTED_MUTATIONS`, which is argued at that constant: the hazard the
D-22 refusal protects against on `copilot:use` is an operator burning a CLIENT'S allowance,
and this permission has no path to a client's balance at all. What an impersonating operator
still cannot do is CHANGE anything — every write tool refuses inside itself through the same
`MUTATING_PERMISSIONS` membership, asked by `write_tools`' own permission ladder, and
`POST /v1/copilot/confirm` stays refused by the ordinary D-22 line because it declares
`copilot:use` and that permission is not exempted.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy import text

from apps.api.billing.ai_quota import new_assist_ref
from apps.api.billing.platform_ai import require_platform_ai
from apps.api.compliance.audit import write_audit
from apps.api.copilot import admin_memory, memory, service, session_run, transcript, write_tools
from apps.api.copilot import prompt as prompt_module
from apps.api.copilot.context import live_state_block
from apps.api.copilot.sanitize import assert_redacted
from apps.api.copilot.schemas import (
    AdminCopilotAskIn,
    CopilotConversationClearedOut,
    CopilotConversationOut,
    CopilotDoneEvent,
    CopilotFact,
    CopilotFillEvent,
    CopilotTextEvent,
)
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.crm.assist import ASSIST_FEATURE_ADMIN_COPILOT, meter_platform_assist
from apps.api.db.session import admin_session, untenanted_session

log = get_logger(__name__)

router = APIRouter(prefix="/v1/admin", tags=["copilot"])

#: The door. A module-level `Annotated` alias, which is this repo's idiom for every
#: `*_routes.py` that is not literally named `routes.py` (`ops/config_routes.py`,
#: `admin/holds_routes.py`) — the B008 per-file ignore is scoped to `routes.py` alone, and
#: the alias form is what the rule wants anyway.
#:
#: `realm="admin"` is what keeps a client `owner` out, never the permission
#: (`rbac.ADMIN_REALM_PREFIXES` states this at length): the role table is one flat dict over
#: both realms, so a route under `/v1/admin/` that forgot the realm would be open to every
#: tenant owner whose role happened to hold the string.
AdminCopilotUser = Annotated[Principal, Depends(requires("copilot:admin", realm="admin"))]

_DESCRIPTION = """\
The admin console's own assistant. Answers about the screen the operator is on, about
PLATFORM state (the client roster, the triage board, whether outbound dialling is halted,
whether our telemarketer registration is live, how much of this month's AI budget is
spent), about the ONE account named in `tenant_id` when one is open, and about Calevate's
own runbooks — every one of those by calling a read tool, never from memory.

`tenant_id` is the account whose admin page is open, or null. It scopes the account tools,
the live-state block and memory recall. Inside a view-as session it is ignored in favour of
the impersonated account, which is proven by the grant rather than claimed in a body.

Streams `text/event-stream` with exactly the frames `POST /v1/copilot/ask` documents —
`text`, `fill`, `step`, `proposal`, `action`, `done`, `error`. A `proposal` is NOT a
change and, in this realm today, neither a `proposal` nor an `action` will be offered: the
write tools need an account-scoped identity that an admin session does not carry, and
inside a view-as session they are refused outright because impersonation is read-only.

**BILLING: this never touches a client's AI allowance.** Operator spend is metered to the
platform's own ledger under the cost name `admin_copilot`. It is still bounded by the
platform-wide AI brake, which pauses this console's assistant exactly as it pauses every
client's.

Requires `copilot:admin` — held by operators and superadmins.\
"""


def _operator_id(principal: Principal) -> UUID:
    """The operator's `admin_users.id`, or a refusal.

    Unreachable through `requires("copilot:admin", realm="admin")`, which resolves it.
    Raised rather than answered with an empty page, because "you have no conversation" is
    a false statement to make to somebody whose conversation we merely failed to look up.
    """
    if principal.user_id is None:  # pragma: no cover - the realm dependency resolves it
        raise ProblemError(
            kind="permission",
            code="copilot_conversation_not_yours",
            title="The assistant's conversation belongs to a person",
            detail="This credential is not an operator, so it has no conversation.",
            remediation="Sign in to the operator console and open the assistant there.",
        )
    return principal.user_id


def _error_event(problem: ProblemError) -> ServerSentEvent:
    """A refusal as an SSE frame, carrying the SAME body the error handler would have
    written — `copilot/routes._error_event`'s reason, one problem shape for the platform."""
    return ServerSentEvent(event="error", data=problem.as_problem())


async def _viewed_tenant(principal: Principal, claimed: UUID | None) -> UUID | None:
    """Which account is open: the impersonation grant's, else the body's, else none.

    **THE GRANT WINS AND THE TWO ARE NEVER RECONCILED.** `Principal.tenant_id` on an admin
    principal exists only inside a D-22 view-as session, where it was minted behind a second
    factor (D-210) and is audited on every read; the body field is a claim a browser
    composed. Preferring the proven one is the same rule `copilot/routes.py` states about
    `payload.screen` — a caller-composed description is for the prompt and the audit row,
    never for scoping.

    A CLAIMED ID IS VALIDATED, NOT TRUSTED: an id that names no live account is refused
    rather than silently ignored, so an operator whose console sent a stale id gets told
    instead of getting answers about the platform to a question about one client.

    **WHAT THE CLAIM OPENS, STATED PLAINLY BECAUSE THIS DOCSTRING USED TO UNDERSTATE IT.**
    It said the claim "widens nothing — both admin roles hold `admin:tenants` and can read
    any account's page". The permission half is true and the conclusion does not follow.
    `service.realm_read_tools` gives the admin realm a strict SUPERSET — the platform tools
    plus every client read tool — and this id is what scopes their `tenant_session`. So an
    operator holding only `copilot:admin` can ask the assistant about ANY live account's
    leads, campaigns, agents and (through `search_calls`) its redacted transcript windows,
    none of which has an admin-realm route: `/v1/leads` and `/v1/crm/calls` are client-realm
    and an operator reaches them only through a D-22 view-as session, which is minted behind
    a second factor (D-210) and audited on every read. Grepped this session, not recalled —
    the only admin-realm surface over a client's call content is
    `/v1/admin/qa-samples/{id}` (`calls:read`, redacted, sampled calls only).

    THAT IS D-499's DESIGN AND NOT A HOLE THIS FUNCTION OPENED — an operator on a client's
    admin page is meant to be able to ask about that client — but it is a second, lighter
    door to client data beside the audited one, and the audit row is what has to make the
    two distinguishable. `ask_admin_copilot` records `impersonating`, so a `tenant_id` with
    `impersonating: false` IS the "reached by a body claim" case. Anything that widens what
    the account tools return belongs in a decision-log entry, not in this function.
    """
    if principal.tenant_id is not None:
        return principal.tenant_id
    if claimed is None:
        return None
    async with admin_session() as session:
        # `admin_session` is the only session that can see `organizations` across tenants
        # (migration b57e2f9c4a13), and this is the whole of what it is used for here.
        exists = (
            await session.execute(
                text("SELECT 1 FROM organizations WHERE id = :id AND deleted_at IS NULL"),
                {"id": claimed},
            )
        ).first()
    if exists is None:
        raise ProblemError(
            kind="validation",
            code="admin_copilot_unknown_account",
            title="That account could not be found",
            detail="The assistant was asked to work inside an account that does not exist.",
            remediation="Reload the page and try again from the account's own screen.",
        )
    return claimed


@router.post(
    "/copilot/ask",
    response_class=EventSourceResponse,
    openapi_extra=permission_meta("copilot:admin"),
    summary="Ask the admin console's assistant — streamed, metered to the platform",
    description=_DESCRIPTION,
)
async def ask_admin_copilot(
    request: Request,
    payload: Annotated[AdminCopilotAskIn, Body()],
    principal: AdminCopilotUser,
) -> AsyncIterator[ServerSentEvent]:
    """SUBJECT → GATE → RUN → METER, with the meter, the audit and the memory in one
    transaction — `copilot/routes.ask_copilot`'s order, on the platform's own money.

    **NO `Depends(db)`**, for that route's reason: a streaming route must not hold a pooled
    Postgres connection across a provider round trip. The gate takes its own short session
    and closes it before the first token; the meter takes another after the last one.

    **THE GATE IS ONE CONDITION, NOT THREE.** `require_ai_assist` refuses on a tenant's
    included allowance, on a wallet at its ceiling and on the platform brake; two of those
    do not exist for an operator. `require_platform_ai` is the third alone, and its refusal
    code is deliberately not the client's — `ai_quota_exceeded` is what opens a wallet
    dialog, and an operator has no wallet to open.

    **NO `Idempotency-Key`**, for `ask_copilot`'s reason: the answer is a stream, and a key
    that could not replay anything would be a claim row and a 409 on an honest retry. The
    `costly` rate-limit profile bounds a double-click.
    """
    tenant_id: UUID | None = None
    try:
        # 1. THE SUBJECT, before the money — and this guard is not softened for the admin
        #    realm even though an operator legitimately sees more than a client does. What
        #    it protects is not the OPERATOR'S eyes, it is what leaves this deployment for
        #    a vendor's: a phone number in a screen block reaches Azure whoever is looking
        #    at it, and D-127 G-1's rule is about the wire, not about the audience.
        assert_redacted(payload.question, authored=True)
        screen = prompt_module.render_screen(payload)
        prompt_module.assert_screen_fits(screen)
        assert_redacted(screen, *(turn.content for turn in payload.history))

        tenant_id = await _viewed_tenant(principal, payload.tenant_id)

        # 2. THE GATE, and 2b THE MEMORY, on ONE untenanted session opened and closed here.
        #    Both read platform-scoped tables (`platform_ai_spend`, `admin_copilot_memories`)
        #    which carry no policy, so no tenant GUC is needed to see them and none would
        #    help. `recall` never raises — an operator whose memory query failed gets an
        #    answer without memory, never an error instead of an answer.
        async with untenanted_session() as gate_session:
            await require_platform_ai(gate_session)
            remembered = (
                await admin_memory.recall(
                    gate_session,
                    admin_user_id=principal.user_id,
                    viewing_tenant_id=tenant_id,
                    question=payload.question,
                )
                if principal.user_id is not None
                else ()
            )
    except ProblemError as refusal:
        yield _error_event(refusal)
        return

    # 2c. THE ACCOUNT'S LIVE STATE, when one is open, in its own short session. Empty on a
    #     platform screen, which is what `build_admin_messages` documents as the ordinary
    #     value: `live_state_block` composes a TENANT's business state and there is no
    #     tenant to compose one for. It never raises and never blocks the answer.
    live = await live_state_block(tenant_id) if tenant_id is not None else ""

    # MEMORY REACHES THE MODEL AS A `fact`, which is the seam the client route already
    # established: `facts` is defined as read-only context the browser volunteers and
    # `prompt.py` already fences it. Appended AFTER `assert_redacted` deliberately — this
    # text went through `redact()` on the way IN (`memory.redacted_content` is the only
    # writer), so re-running the guard could only fail on a row the database should not
    # contain, in the middle of answering somebody.
    if remembered:
        payload = payload.model_copy(
            update={
                "facts": [
                    *payload.facts,
                    CopilotFact(
                        key="remembered",
                        label="What you have told the assistant before",
                        value=memory.render_for_prompt(remembered),
                    ),
                ]
            }
        )

    # 3. THE RUN. The metering key is minted HERE, by the server, per attempt — the same
    #    `new_assist_ref()` both ledgers accept and nothing else, because idempotency is a
    #    switch that turns metering off (D-140).
    ref = new_assist_ref()
    # EVERY SPEND OF THIS RUN — `copilot/routes.py`'s argument, and the platform is the
    # payer that a lost one is charged to. `run_copilot` can emit two: a leg that failed
    # before it streamed anything is re-selected under `provider_unavailable=True`, and the
    # first leg's tokens were paid for whether or not the second answered.
    spends: list[service.CopilotSpend] = []
    filled: tuple[str, ...] = ()
    proposed: str | None = None
    acted: list[str] = []
    answer_parts: list[str] = []

    # WHICH SIGN-IN RUN THIS ANSWER BELONGS TO (D-540) — the admin realm's own, so an
    # operator's conversation ends with their shift and never leaks into the next one.
    # Read before the model call for `copilot/routes.py`'s reason.
    run_started_at = (
        await session_run.current_run_start(realm="admin", subject_id=principal.user_id)
        if principal.user_id is not None
        else None
    )

    # 4. THE METER, THE AUDIT AND THE MEMORY, in ONE transaction of their own — the record
    #    of a payment that has already happened. Nothing between the run and the meter may
    #    raise: a completed answer is money spent whether or not it was any good.
    #
    # **A CLOSURE, FOR `copilot/routes.py`'s REASON**: there are four ways out of the run
    # and all four owe the ledger the same rows. Straight-line code after the `async for`
    # was reached only by the way out that worked, so a provider that died mid-answer and a
    # browser that closed the tab were both spend the platform ledger never saw.
    metered = False
    recorded = False
    #: Did the run finish on its own? False on a refusal, a provider failure and a
    #: disconnect — the three exits that used to skip the ledger entirely.
    completed = False

    async def _record() -> None:
        """Write this run's platform ledger rows, its audit row and its memory. Once."""
        nonlocal metered, recorded
        if recorded:
            return
        recorded = True
        if not spends or principal.user_id is None:
            return
        async with untenanted_session() as record_session:
            refs = [ref if index == 0 else new_assist_ref() for index in range(len(spends))]
            for spent, spend_ref in zip(spends, refs, strict=True):
                metering = await meter_platform_assist(
                    record_session,
                    admin_user_id=principal.user_id,
                    # CONTEXT, NEVER A PAYER. This is what makes "what did supporting this
                    # client cost us" a query; nothing prices it and no client ledger moves.
                    viewing_tenant_id=tenant_id,
                    ref=spend_ref,
                    result=spent,
                    feature=ASSIST_FEATURE_ADMIN_COPILOT,
                    model=spent.model,
                )
                metered = metered or metering.metered
            last = spends[-1]
            await write_audit(
                record_session,
                action="admin_copilot.ask",
                actor=principal,
                # THE ACCOUNT THE OPERATOR WAS LOOKING AT, so a client's audit trail shows
                # that support work happened on their account and by whom. `None` on a
                # platform screen, which is a platform-level row.
                tenant_id=tenant_id,
                object_type="screen",
                object_id=payload.screen.route,
                ip=client_request_ip(request),
                # Ids, names and COUNTS. No question, no answer, no field value (rule 6).
                # `payer` is stated explicitly rather than left to be inferred from the
                # action name: this row is the operations record of spend that a client did
                # NOT pay for, and the next reader should not have to know which ledger
                # `admin_copilot.ask` writes to in order to read it correctly.
                summary={
                    "realm": "admin",
                    "payer": "platform",
                    "feature": ASSIST_FEATURE_ADMIN_COPILOT,
                    "provider": last.capability.provider,
                    "fallback_reason": last.capability.fallback_reason,
                    "spend_count": len(spends),
                    "completed": completed,
                    "metered": metered,
                    "ref": ref,
                    "filled_field_count": len(filled),
                    # THE TIER 1 ACTIONS THIS ANSWER PERFORMED, as the client route records
                    # them. Each already wrote its own `audit_log` row inside
                    # `run_immediate`'s transaction; this is what the `admin_copilot.ask`
                    # row says about the ANSWER, so a reader of one row can tell that an
                    # operator's question changed something. The count is stated separately
                    # because `redact_mapping` collapses any sequence to "[N items]" on the
                    # way to the log stream.
                    "action_count": len(acted),
                    "actions": sorted(set(acted)),
                    "proposed_tool": proposed,
                    # HOW THIS ACCOUNT WAS REACHED, and it is the field a reviewer needs
                    # first. `tenant_id` set with `impersonating: false` means the account
                    # was named in the request BODY and validated against the directory
                    # (`_viewed_tenant`) rather than proven by an impersonation grant minted
                    # behind a second factor. Both are legitimate; they are not the same
                    # event, and a row that cannot tell them apart cannot be reviewed.
                    "impersonating": principal.impersonating,
                },
            )
            # 5. THE MEMORY, after the audit so a memory write can never be what stops an
            #    `audit_log` entry landing, and in the same transaction so a memory of an
            #    answer whose ledger rows rolled back is unreachable.
            # 5a. THE TRANSCRIPT (D-540), before the memory and in the same transaction,
            #     for `copilot/routes.py`'s reason: what the PERSON can scroll goes first,
            #     because a loss between the two should fall on the copy nobody can tell
            #     is missing. The admin table carries no tenant and no retention category
            #     — see `copilot/models.AdminCopilotConversationTurn` — so this thread's
            #     whole clock is the operator's own 8-hour absolute session bound.
            if run_started_at is not None:
                await transcript.append_exchange(
                    record_session,
                    realm=transcript.ADMIN,
                    owner_id=principal.user_id,
                    # The account on screen, which on this table is `viewing_tenant_id`:
                    # context, never ownership.
                    tenant_id=tenant_id,
                    run_started_at=run_started_at,
                    screen_route=payload.screen.route,
                    question=payload.question,
                    answer="".join(answer_parts),
                )
            await admin_memory.remember_exchange(
                record_session,
                admin_user_id=principal.user_id,
                viewing_tenant_id=tenant_id,
                screen_route=payload.screen.route,
                question=payload.question,
                answer="".join(answer_parts),
                meta={
                    "realm": "admin",
                    "provider": last.capability.provider,
                    "filled_field_count": len(filled),
                },
            )

    try:
        async for event in service.run_copilot(
            payload,
            # NO `tenant_leg`. D-478's per-account model choice is a CLIENT's setting about
            # a CLIENT's own spend; an operator's question runs on the platform's own Azure
            # leg, which is what `assist_capability` selects when no account leg is passed.
            # Reading the viewed account's leg would put a client's model preference in
            # front of an operator's question and price it off that client's model.
            tenant_leg=None,
            # `require_platform_ai` RAISES at the brake, so this is False on every path that
            # reaches here. Written as the read so the caller stays correct if the gate ever
            # learns to answer instead of raise.
            quota_exhausted=False,
            realm="admin",
            # WHO IS ASKING, for the read tools. The tenant is what scopes the RLS session
            # each ACCOUNT tool opens for itself; `None` is a real value here and the
            # account tools refuse with a sentence saying no account is open. The role is
            # what `tools.run_read_tool` judges the tool's own permission against — the
            # platform tools declare `admin:tenants`, which no client role holds.
            tool_context=service.ToolContext(tenant_id=tenant_id, role=principal.role),
            live=live,
            # THE VERIFIED PRINCIPAL, passed whole — the loop narrows it to a `ToolActor`
            # itself (`write_tools.actor_for`, the one place that narrowing happens) and
            # `write_audit` names the actor from it. Never from the body: `payload.screen`
            # is a caller-composed description used for the prompt and the audit row and
            # for nothing else.
            #
            # **WHAT THE WRITE TOOLS DO IN THIS REALM, STATED RATHER THAN DISCOVERED.**
            # `actor_for` refuses a principal with no tenant, and an admin principal carries
            # one ONLY inside a D-22 view-as session. So:
            #   * operator on a console screen → no actor → `plan_write` refuses with "needs
            #     a signed-in account and this session has none". The tools are still
            #     OFFERED, because the array must not vary by caller (`tool_array`).
            #   * operator inside a view-as session → an actor exists, and every write
            #     tool's permission is in `MUTATING_PERMISSIONS`, which D-22 refuses and
            #     which `IMPERSONATION_PERMITTED_MUTATIONS` deliberately does not exempt.
            # Both refusals are the EXISTING ladder asked by the existing code; neither is a
            # new check written here. See the report and D-499 for what would let an
            # operator propose inside an account they are merely viewing.
            principal=principal,
            # WHAT MAKES AN ACTION'S IDEMPOTENCY KEY STABLE ACROSS A RETRY: the question and
            # the replayed history, never the metering `ref` (minted per attempt, so a retry
            # gets a new one and the guard protects nothing). Composed here because this is
            # the layer that has the request.
            seed=write_tools.conversation_seed(
                payload.question, [turn.content for turn in payload.history]
            ),
            ip=client_request_ip(request),
        ):
            if event.text is not None:
                answer_parts.append(event.text)
                yield ServerSentEvent(event="text", data=CopilotTextEvent(delta=event.text))
            if event.fill is not None:
                filled = tuple(item.field_id for item in event.fill)
                yield ServerSentEvent(event="fill", data=CopilotFillEvent(items=list(event.fill)))
            if event.proposal is not None:
                proposed = event.proposal.tool
                yield ServerSentEvent(event="proposal", data=event.proposal)
            if event.step is not None:
                # FORWARDED, AND THIS ROUTE USED TO DROP IT. `service.run_copilot` emits a
                # `step` frame per tool call on both realms; consuming the event and
                # yielding nothing meant an operator watched a spinner while the assistant
                # ran four platform lookups. Observational only — nothing downstream reads
                # one — and never logged or stored, because it carries a bounded preview of
                # a tool's arguments and result (hard rule 6).
                yield ServerSentEvent(event="step", data=event.step)
            if event.action is not None:
                # THE RECEIPT FOR A TIER 1 ACTION, AND DROPPING IT WAS THE SERIOUS HALF.
                # It is unreachable today — `actor_for` refuses a principal with no tenant,
                # and inside a view-as session every action permission is in
                # `MUTATING_PERMISSIONS`, which D-22 refuses — so nothing has been silently
                # applied. But `run_immediate` writes the change and its `audit_log` row
                # before this loop sees the event, so the day that ladder admits an
                # operator, the drop would have been a change made with no receipt on the
                # screen of the person who caused it. Wiring it now costs two lines; a
                # half-wired seam that only fails after somebody else's change is the
                # defect class CLAUDE.md names.
                acted.append(event.action.tool)
                yield ServerSentEvent(event="action", data=event.action)
            if event.spend is not None:
                spends.append(event.spend)
        completed = True
    except ProblemError as refusal:
        # The selector refused before a request was made, so `spends` is empty and `_record`
        # writes nothing — checked rather than asserted, for the client route's reason.
        await _record()
        yield _error_event(refusal)
        return
    except Exception:
        # A PROVIDER THAT DIED MID-ANSWER IS SPEND. Ids only (hard rule 6). This arm used to
        # return before the meter, so tokens the platform had already paid for landed in no
        # `platform_ai_usage` row and moved no `platform_ai_spend` counter — which is the
        # brake going blind, on the surface the brake exists to protect.
        log.exception(
            "admin_copilot_stream_failed",
            extra={"admin_user_id": str(principal.user_id), "ref": ref},
        )
        await _record()
        yield _error_event(
            ProblemError(
                kind="dependency",
                code="copilot_interrupted",
                title="The assistant stopped part-way",
                detail="The assistant did not finish answering.",
                remediation="Ask again — nothing on your screen was changed.",
            )
        )
        return
    finally:
        # THE OPERATOR CLOSED THE TAB. `sse-starlette` `aclose()`s this generator and every
        # arm above is skipped, so an abandoned turn was spend nobody recorded. Shielded
        # because the disconnect usually arrives as a cancellation of the task this runs in,
        # and an unshielded await would be cancelled inside the transaction — the one place
        # a partial write is worse than none. Not a guarantee (a loop already tearing down
        # still loses it), which is why the failure is LOGGED rather than swallowed.
        try:
            await asyncio.shield(_record())
        except Exception:
            log.exception(
                "admin_copilot_meter_failed", extra={"admin_user_id": str(principal.user_id)}
            )

    yield ServerSentEvent(
        event="done",
        data=CopilotDoneEvent(
            # THE LEG THAT ACTUALLY ANSWERED, which is the LAST spend: a run that fell back
            # to Sarvam owes the operator that disclosure.
            disclosure=(service.disclosure_for(spends[-1].capability) if spends else None),
            metered=metered,
        ),
    )


@router.get(
    "/copilot/conversation",
    response_model=CopilotConversationOut,
    openapi_extra=permission_meta("copilot:admin"),
    summary="The operator's own conversation with the admin assistant — durable, paged",
)
async def load_admin_copilot_conversation(
    principal: AdminCopilotUser,
    limit: Annotated[int, Query(ge=1, le=transcript.PAGE_MAX)] = transcript.PAGE_DEFAULT,
    before: Annotated[str | None, Query()] = None,
) -> CopilotConversationOut:
    """One page of this operator's live conversation (D-540).

    `untenanted_session`, and it is the correct one rather than a convenient one:
    `admin_copilot_conversation_turns` carries no `tenant_id` and no policy (these are the
    platform's own rows — `db/registry.py` holds the standing justification), so there is
    no tenant to scope to and `admin_session` would widen `organizations` for no reason.
    The `admin_user_id` predicate is the whole of the scoping, exactly as on
    `admin_copilot_memories`.

    The thread is NOT scoped on the account the operator happens to be viewing. It is one
    conversation and it follows them across screens — which is the founder's decision 3
    (the screen is recorded per message) applied to a console where "the screen" includes
    "whose account". `viewing_tenant_id` is on every row, so the provenance of a turn is
    recoverable; what is not on offer is a separate thread per client, which would change
    underneath an operator the moment the assistant moved them.
    """
    operator = _operator_id(principal)
    run_started_at = await session_run.current_run_start(realm="admin", subject_id=operator)
    if run_started_at is None:
        return CopilotConversationOut(turns=[], has_more=False)
    async with untenanted_session() as session:
        page = await transcript.load(
            session,
            realm=transcript.ADMIN,
            owner_id=operator,
            run_started_at=run_started_at,
            limit=limit,
            before=transcript.turn_cursor(before),
        )
    return transcript.conversation_out(page)


@router.delete(
    "/copilot/conversation",
    response_model=CopilotConversationClearedOut,
    openapi_extra=permission_meta("copilot:admin"),
    summary="Start again — forget this operator's assistant conversation",
)
async def clear_admin_copilot_conversation(
    request: Request,
    principal: AdminCopilotUser,
) -> CopilotConversationClearedOut:
    """Forget this operator's whole conversation.

    ⚠ **IT WRITES AN AUDIT ROW, AND THE EARLIER ARGUMENT FOR NOT WRITING ONE IS
    WITHDRAWN.** That argument — "what is audited is every answer and every change, not a
    person clearing a panel" — is true as far as it goes: every `admin_copilot.ask` row
    survives this, so the RECORD of what an operator asked is untouched and clearing the
    panel destroys only a convenience copy.

    It is still the wrong call here, for a reason outside this route. SEC-COMP §5's
    invariant is that EVERY admin-realm mutation writes an audit row, and
    `tests/admin_read_audit_test._NOT_AN_AUDITED_MUTATION` — the register of sanctioned
    exceptions — is **empty**. Exempting this would have opened that register for the
    first time, and a register that exists gets used: the next reader with a mutation that
    feels minor now has a precedent instead of an absolute. An invariant with no exceptions
    is worth more than this row costs, and this row costs one INSERT on a rare operator
    action.

    Ids and a COUNT only, no content (hard rule 6): the turns being destroyed are the
    operator's own words and an assistant's answers, and the point of the row is that the
    clearing happened, by whom and how much — never what was said.
    """
    operator = _operator_id(principal)
    async with untenanted_session() as session:
        cleared = await transcript.clear(session, realm=transcript.ADMIN, owner_id=operator)
        await write_audit(
            session,
            action="admin_copilot.conversation_cleared",
            actor=principal,
            # PLATFORM-LEVEL, not a tenant's: an operator's assistant panel belongs to no
            # client, and attributing it to whichever account happened to be open would put
            # a row in that client's trail for something that was not about them.
            tenant_id=None,
            object_type="admin_copilot_conversation",
            object_id=str(operator),
            ip=client_request_ip(request),
            summary={"turns_cleared": cleared},
        )
    return CopilotConversationClearedOut(cleared=cleared)


__all__ = ["router"]
