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

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy import text

from apps.api.billing.ai_quota import new_assist_ref
from apps.api.billing.platform_ai import require_platform_ai
from apps.api.compliance.audit import write_audit
from apps.api.copilot import admin_memory, memory, service, write_tools
from apps.api.copilot import prompt as prompt_module
from apps.api.copilot.context import live_state_block
from apps.api.copilot.sanitize import assert_redacted
from apps.api.copilot.schemas import (
    AdminCopilotAskIn,
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
`text`, `fill`, `proposal`, `done`, `error`. A `proposal` is NOT a change and, in this
realm today, will not be offered: the write tools need an account-scoped identity that an
admin session does not carry, and inside a view-as session they are refused outright
because impersonation is read-only.

**BILLING: this never touches a client's AI allowance.** Operator spend is metered to the
platform's own ledger under the cost name `admin_copilot`. It is still bounded by the
platform-wide AI brake, which pauses this console's assistant exactly as it pauses every
client's.

Requires `copilot:admin` — held by operators and superadmins.\
"""


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

    A CLAIMED ID IS VALIDATED, NOT TRUSTED, and the refusal is deliberate rather than a
    silent `None`. It widens nothing — both admin roles hold `admin:tenants` and can read
    any account's page — so this is not an access control; it is the difference between a
    screen that believes it scoped the assistant and one that knows it did. An operator
    whose console sent a stale id gets told, instead of getting answers about the platform
    to a question about one client.
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
    spend: service.CopilotSpend | None = None
    filled: tuple[str, ...] = ()
    proposed: str | None = None
    answer_parts: list[str] = []
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
            if event.spend is not None:
                spend = event.spend
    except ProblemError as refusal:
        # The selector refused before a request was made, so nothing was paid for and there
        # is nothing to meter.
        yield _error_event(refusal)
        return
    except Exception:
        # A provider that died mid-answer. Ids only (hard rule 6). If the model had already
        # answered, `spend` is None and the money is unrecorded — which is why this arm logs
        # loudly rather than swallowing.
        log.exception(
            "admin_copilot_stream_failed",
            extra={"admin_user_id": str(principal.user_id), "ref": ref},
        )
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

    # 4. THE METER, THE AUDIT AND THE MEMORY, in ONE transaction of their own — the record
    #    of a payment that has already happened. Nothing between the run and the meter may
    #    raise: a completed answer is money spent whether or not it was any good.
    metered = False
    if spend is not None and principal.user_id is not None:
        async with untenanted_session() as record_session:
            metering = await meter_platform_assist(
                record_session,
                admin_user_id=principal.user_id,
                # CONTEXT, NEVER A PAYER. This is what makes "what did supporting this
                # client cost us" a query; nothing prices it and no client ledger moves.
                viewing_tenant_id=tenant_id,
                ref=ref,
                result=spend,
                feature=ASSIST_FEATURE_ADMIN_COPILOT,
                model=spend.model,
            )
            metered = metering.metered
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
                    "provider": spend.capability.provider,
                    "fallback_reason": spend.capability.fallback_reason,
                    "metered": metered,
                    "ref": ref,
                    "filled_field_count": len(filled),
                    "proposed_tool": proposed,
                    "impersonating": principal.impersonating,
                },
            )
            # 5. THE MEMORY, after the audit so a memory write can never be what stops an
            #    `audit_log` entry landing, and in the same transaction so a memory of an
            #    answer whose ledger rows rolled back is unreachable.
            await admin_memory.remember_exchange(
                record_session,
                admin_user_id=principal.user_id,
                viewing_tenant_id=tenant_id,
                screen_route=payload.screen.route,
                question=payload.question,
                answer="".join(answer_parts),
                meta={
                    "realm": "admin",
                    "provider": spend.capability.provider,
                    "filled_field_count": len(filled),
                },
            )

    yield ServerSentEvent(
        event="done",
        data=CopilotDoneEvent(
            disclosure=(service.disclosure_for(spend.capability) if spend is not None else None),
            metered=metered,
        ),
    )


__all__ = ["router"]
