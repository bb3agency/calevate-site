"""`POST /v1/copilot/ask` — the in-app assistant, streamed.

**THE FIRST STREAMING RESPONSE IN THIS API, and D-24 chose polling.** That decision is
about DATA FRESHNESS — the dashboard's `apps/web/src/lib/api/hooks.ts:4-16` polls a lead
list every 20s rather than holding a socket open for it — and it is untouched here. This is
not a subscription to changing state; it is one request whose answer is produced a token at
a time by a model, and the alternatives were measured against the same three tests
`crm/assist.py` applied to the re-summarise route:

* **A 202-and-poll shape needs somewhere to PUT the answer**, which is a table of
  model-written prose about a person's screen. `crm/assist.py:10-31` declines to build
  exactly that store so DPDP erasure and retention gain no new surface, and this feature
  does not get to re-open it.
* **One blocking response** works and is worse for the one thing this feature is: a person
  waiting. It also puts the whole answer behind a single edge read, which is what makes
  `proxy_read_timeout` a total deadline (see `service.TOTAL_BUDGET_S`).
* **A socket** is a second protocol, a second auth path and a second thing to operate, for
  a stream that lives for one answer.

`fastapi.sse.EventSourceResponse` is built into the installed FastAPI (0.140) and works
over POST, so this adds no dependency. It also sets `Cache-Control: no-cache` and
`X-Accel-Buffering: no` itself, which is why `infra/nginx/` needs no change —
`service.TOTAL_BUDGET_S` carries the verification of both halves of that claim.

**ERRORS ARE EVENTS, NOT STATUSES, ONCE THE STREAM HAS STARTED.** An SSE response commits
its status with its headers, so everything a route normally answers with a 4xx has to be
either (a) a dependency, which runs before the generator and produces an ordinary
problem+json response with a real status — permission, rate limit, body validation — or
(b) an `event: error` carrying the same problem+json body. Both shapes exist here and the
split is deliberate: a caller who is not allowed in never reaches the stream at all.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from apps.api.agents.assist_leg import account_assist_leg
from apps.api.billing.ai_quota import new_assist_ref, require_ai_assist
from apps.api.compliance.audit import write_audit
from apps.api.copilot import service
from apps.api.copilot.sanitize import assert_redacted
from apps.api.copilot.schemas import (
    CopilotAskIn,
    CopilotDoneEvent,
    CopilotFillEvent,
    CopilotTextEvent,
)
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.crm.assist import ASSIST_FEATURE_COPILOT, meter_assist
from apps.api.db.session import tenant_session

log = get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["copilot"])

_DESCRIPTION = """\
Answers a question about the screen the caller is on, and can fill that screen's form
fields. Streams `text/event-stream`:

* `event: text` · `data: {"delta": "..."}` — one fragment of the answer.
* `event: fill` · `data: {"items": [{"field_id": "...", "value": ...}]}` — at most one
  per response. Every item has been re-validated server-side against the `fields` this
  request declared: a field that is not `writable`, a `select` value outside its own
  `options`, or a wrong type refuses the WHOLE fill. Write these into local form state,
  highlight them, and offer one Undo; nothing is saved until the user presses Save.
* `event: done` · `data: {"disclosure": null|"...", "metered": true}` — `disclosure` is
  non-null when a substitute model answered and MUST be shown.
* `event: error` · `data: {problem+json}` — a refusal that happened after the stream
  opened. Permission, rate-limit and request-validation refusals arrive as ordinary
  problem+json responses with their real status instead.

Nothing is stored. `history` is the whole memory of the conversation and dies with the
request. Metered against the account's AI allowance and refused before a token is spent
when that allowance is used up (`ai_quota_exceeded` opens the wallet dialog).
Requires `org:manage`.\
"""


def _error_event(problem: ProblemError) -> ServerSentEvent:
    """A refusal as an SSE frame, carrying the SAME body the error handler would have
    written. One problem shape for the whole platform (BACKEND-PATTERNS §3), whether it
    left through a status line or through a stream."""
    return ServerSentEvent(event="error", data=problem.as_problem())


@router.post(
    "/copilot/ask",
    response_class=EventSourceResponse,
    openapi_extra=permission_meta("org:manage"),
    summary="Ask the in-app assistant about this screen — streamed, metered, quota-gated",
    description=_DESCRIPTION,
)
async def ask_copilot(
    request: Request,
    payload: Annotated[CopilotAskIn, Body()],
    principal: Principal = Depends(requires("org:manage")),
) -> AsyncIterator[ServerSentEvent]:
    """SUBJECT → GATE → RUN → METER, with the meter and the audit in their own transaction.

    **`org:manage`, and the admin realm's answer is that it does not get this route.**
    `org:manage` is what this console already uses for the whole client AI surface and the
    argument is `crm/routes.py:255-273`'s, unchanged: it is in `MUTATING_PERMISSIONS`, so a
    D-22 read-only view-as session cannot spend a client's allowance from a client screen,
    and gating the thing that SPENDS the allowance more loosely than the panel that
    displays it (`GET /v1/billing/ai-quota`, `billing:read`) would be this product
    disagreeing with itself.

    **THE ADMIN REALM IS REFUSED, AND THE REASON IS THAT IT HAS NO PAYER — not that
    nobody picked a permission.** Every AI surface in this repository is metered per
    TENANT: `require_ai_assist` takes a `tenant_id`, `record_ai_assist_usage` writes
    `usage_events` (a tenant-scoped RLS table), and the platform brake is bumped only for
    rows that landed. An operator on `/v1/ops/config` or `/v1/admin/operators` has
    `principal.tenant_id is None`, so an admin-realm copilot would either spend the
    founder's Azure credential with no ledger row — which hard rule 7 forbids in as many
    words, "costs recorded per usage_event with our unit_cost_paid" — or charge whichever
    client's page happened to be open for an operator's typing. Neither is acceptable and
    neither is fixable inside this package: what closes it is a platform-payer AI ledger in
    `billing/`, which is a money surface with its own migration and its own append-only
    rules. **The admin console's copilot button is therefore unserved by this change and
    this sentence is the record of that, not a silence.** An operator inside a view-as
    session reaches this route and is correctly refused by the line above, exactly as they
    are refused `POST /v1/calls/{call_id}/assist`.

    **NO `Idempotency-Key`, WHERE `assist_call` REQUIRES ONE, AND THE DIFFERENCE IS WHAT A
    REPLAY WOULD HAVE TO BE.** That route's key works because its answer is one JSON object
    the idempotency record can store and hand back. This answer is a stream, and the only
    way to replay it is to keep it — which is the store of model-written prose about a
    person's screen that this whole package declines to create (`__init__.py`). A key that
    could not replay anything would be a claim row and a 409 on the honest retry, i.e. the
    mechanism's costs with none of its protection. What bounds a double-click instead is
    the `costly` rate-limit profile (`core/ratelimit.py`, 30/min per caller — its own
    comment says "no human clicks these 30 times a minute") and the per-tenant AI ceiling
    the gate below enforces.

    **NO `Depends(db)`.** A streaming route must not hold a pooled Postgres connection
    across a provider round trip, and it does not have to: the gate takes its own
    `tenant_session` and closes it before the first token, and the meter takes another
    after the last one. That is why `crm/assist.py`'s connection-holding departure is not
    inherited here.
    """
    assert principal.tenant_id is not None  # guaranteed by the tenant-scoped session
    tenant_id = principal.tenant_id

    try:
        # 1. THE SUBJECT, before the money. A payload that still carries personal
        #    values cannot be sent to the provider at any price, and finding that out
        #    after the ceiling check would answer a client at their limit with "add
        #    ₹500" for a request the money would not have helped with.
        # THE QUESTION IS JUDGED SEPARATELY FROM THE SCREEN, and only because the
        # message differs. A person who typed a phone number into the ask box is doing
        # the obvious thing, not making a mistake, and deserves a sentence they can act
        # on; a browser that forgot to substitute a placeholder is a defect and deserves
        # one an operator can. The rule refusing both is exactly the same.
        assert_redacted(payload.question, authored=True)
        assert_redacted(
            *(turn.content for turn in payload.history),
            *(fact.value for fact in payload.facts),
            *(str(field.value) for field in payload.fields if field.value is not None),
            *(field.label for field in payload.fields),
            *(field.help or "" for field in payload.fields),
        )

        # 2. THE GATE. It RAISES — `ai_quota_exceeded` is what opens the wallet dialog
        #    (G-5), `ai_paused_platform_wide` is the brake — so a refusal reaches the
        #    client before a token is spent. Its own session, opened and closed here:
        #    everything below this line costs money and holds no connection.
        async with tenant_session(tenant_id) as gate_session:
            quota = await require_ai_assist(gate_session, tenant_id=tenant_id)
            # WHOSE AI ANSWERS — the account's own model where it may serve this leg.
            # On the gate's session rather than a fourth one: it is a single indexed row,
            # it is needed before the first token is spent, and the alternative is opening
            # a connection of its own for one SELECT.
            tenant_leg = await account_assist_leg(gate_session)
    except ProblemError as refusal:
        yield _error_event(refusal)
        return

    # 3. THE RUN. The metering key is minted HERE, by the server, per attempt:
    #    `record_ai_assist_usage` accepts nothing else, because its idempotency is a
    #    switch that turns metering off (D-140).
    ref = new_assist_ref()
    spend: service.CopilotSpend | None = None
    filled: tuple[str, ...] = ()
    try:
        async for event in service.run_copilot(
            payload,
            # The gate's verdict, passed IN rather than re-read. It is False on every
            # path that reaches here — `require_ai_assist` RAISES at the ceiling — and
            # it is written as the READ so that this caller stays correct if the gate
            # ever learns to answer instead of raise.
            tenant_leg=tenant_leg,
            quota_exhausted=quota.at_ceiling,
        ):
            if event.text is not None:
                yield ServerSentEvent(event="text", data=CopilotTextEvent(delta=event.text))
            if event.fill is not None:
                filled = tuple(item.field_id for item in event.fill)
                yield ServerSentEvent(event="fill", data=CopilotFillEvent(items=list(event.fill)))
            if event.spend is not None:
                spend = event.spend
    except ProblemError as refusal:
        # The selector refused (no provider configured, or both legs down). Nothing was
        # paid for on this path — `assist_unavailable` is raised before a request — so
        # there is nothing to meter.
        yield _error_event(refusal)
        return
    except Exception:
        # A provider that died mid-answer. The person gets a problem body rather than a
        # stream that simply stops, and the operator gets the exception through the
        # ordinary log path. If the model had already answered, `spend` is None and the
        # money is unrecorded — which is why this arm logs rather than swallowing.
        log.exception("copilot_stream_failed", extra={"tenant_id": str(tenant_id)})
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

    # 4. THE METER AND THE AUDIT, in ONE transaction of their own — the record of a
    #    payment that has already happened. `meter_assist` never raises, and nothing
    #    between the run and the meter may: a completed answer is money spent whether or
    #    not it was any good.
    metered = False
    if spend is not None:
        async with tenant_session(tenant_id) as record_session:
            metering = await meter_assist(
                record_session,
                tenant_id=tenant_id,
                ref=ref,
                result=spend,
                feature=ASSIST_FEATURE_COPILOT,
                # The model the answer ran on, when the run knows it (D-478: the account's
                # own Gemini id). `None` on the Azure leg, where `meter_assist` reads the
                # live `azure_openai_model` setting — the model behind Azure's deployment is
                # an operator switch, not a per-run fact.
                model=spend.model,
            )
            metered = metering.metered
            await write_audit(
                record_session,
                action="copilot.ask",
                actor=principal,
                tenant_id=tenant_id,
                object_type="screen",
                # The ROUTE TEMPLATE the browser reported, which is a screen name and
                # not a record — the object here is "a screen", and there is no row to
                # point at.
                object_id=payload.screen.route,
                ip=client_request_ip(request),
                # Ids, names and COUNTS. No question, no answer, no field value — a
                # value is the one thing on this path `sanitize` exists to keep out of a
                # durable record (hard rule 6).
                #
                # A COUNT AND NOT A LIST OF FIELD IDS, and the reason is mechanical
                # rather than a judgement call: `write_audit`'s summary never reaches a
                # column at all (`audit_log` has none) — it goes to the log stream
                # through `core/logging.redact_mapping`, which collapses ANY sequence to
                # `"[N items]"`. A `filled_field_ids` key would therefore be a field name
                # promising something the record cannot hold, which is worse than not
                # recording it. What survives is what is asserted on.
                summary={
                    "realm": payload.screen.realm,
                    "provider": spend.capability.provider,
                    "fallback_reason": spend.capability.fallback_reason,
                    "metered": metered,
                    "ref": ref,
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
