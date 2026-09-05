"""`POST /v1/copilot/ask` — the in-app assistant, streamed — and `POST /v1/copilot/confirm`,
which is where a change the assistant proposed actually happens.

**THE FIRST STREAMING RESPONSE IN THIS API, and D-24 chose polling.** That decision is
about DATA FRESHNESS — the dashboard's `apps/web/src/lib/api/hooks.ts:4-16` polls a lead
list every 20s rather than holding a socket open for it — and it is untouched here. This is
not a subscription to changing state; it is one request whose answer is produced a token at
a time by a model, and the alternatives were measured against the same three tests
`crm/assist.py` applied to the re-summarise route:

* **A 202-and-poll shape needs somewhere to PUT the answer**, which is a table of
  model-written prose about a person's screen. `crm/assist.py:10-31` declines to build
  exactly that store so DPDP erasure and retention gain no new surface, and this feature
  does not get to re-open it. ⚠ `copilot_memories` (D-484 phase 4) is NOT that store and
  does not soften this bullet — it holds a redacted, truncated MEMORY of an exchange for
  the model's benefit, addressable by nobody, and it PAYS the price this paragraph is
  about (a retention category, an erasure arm, an RLS policy). See `ask_copilot`'s
  `Idempotency-Key` paragraph, which is where the difference decides something.
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

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.assist_leg import account_assist_leg
from apps.api.billing.ai_quota import new_assist_ref, require_ai_assist
from apps.api.compliance.audit import write_audit
from apps.api.copilot import memory, service, session_run, transcript, write_tools
from apps.api.copilot import prompt as prompt_module
from apps.api.copilot.context import live_state_block, viewer_for
from apps.api.copilot.sanitize import assert_redacted
from apps.api.copilot.schemas import (
    CopilotAskIn,
    CopilotConfirmIn,
    CopilotConfirmOut,
    CopilotConversationClearedOut,
    CopilotConversationOut,
    CopilotDoneEvent,
    CopilotFact,
    CopilotFillEvent,
    CopilotTextEvent,
)
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.crm.assist import ASSIST_FEATURE_COPILOT, meter_assist
from apps.api.db.session import tenant_session

log = get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["copilot"])

_DESCRIPTION = """\
Answers a question about the screen the caller is on, answers questions about the
account's own business by reading it (calls, leads, campaigns, agents, performance —
read-only, under the caller's own permissions and RLS scope), can fill that screen's
form fields, and can open another screen of the console. Streams `text/event-stream`:

* `event: text` · `data: {"delta": "..."}` — one fragment of the answer.
* `event: fill` · `data: {"items": [{"field_id": "...", "value": ...}]}` — at most one
  per response. Every item has been re-validated server-side against the `fields` this
  request declared: a field that is not `writable`, a `select` value outside its own
  `options`, or a wrong type refuses the WHOLE fill. Write these into local form state,
  highlight them, and offer one Undo; nothing is saved until the user presses Save.
* `event: proposal` · `data: {"token": "...", "tool": "...", "title": "...",
  "summary": "...", "object_type": "...", "object_id": "...", "current": "...",
  "proposed": "...", "cost": null|"...", "reversal": "...", "expires_at": "..."}` — at most
  one per response, and it is NOT a change. NOTHING HAS HAPPENED. This is a **Tier 2**
  action: one that reaches a caller or spends money, and therefore needs a person. Show
  `title`, `summary`, the `current` → `proposed` pair, `cost` when it is non-null and
  `reversal` always, and a Confirm button that posts `token` back, unchanged, to
  `POST /v1/copilot/confirm`. Doing nothing is a valid answer and leaves the world
  untouched; the token stops working at `expires_at`.
* `event: action` · `data: {"tool": "...", "title": "...", "detail": "...",
  "object_type": "...", "object_id": "...", "applied": true, "reversal": "...",
  "where": "..."}` — a **Tier 1** action that **has already happened**: reversible, reaching
  no caller, spending nothing. Render it as a RECEIPT and never as an offer — there is no
  token and no button. `reversal` says whether and how it can be taken back and `where`
  says where the result now lives; both are the server's own words. `applied: false` means
  the world was already in that state.
* `event: navigate` · `data: {"tool": "open_screen", "screen": "...", "route": "...",
  "where": "...", "detail": "...", "reversal": "..."}` — OPEN THIS SCREEN. At most one per
  response. A **Tier 1** frame: reversible (the back button), reaching no caller, spending
  nothing, so there is no token and no Confirm button — render it as a RECEIPT beside the
  answer, exactly like `action`. It is the one frame on this stream the browser must ACT
  on, and the only one where the server has decided WHERE but not WHEN.
  * `route` is a route TEMPLATE carrying a literal `{slug}` (`/c/{slug}/billing`) and is a
    constant read out of the server's own screen inventory — never assembled, and never
    anything the model wrote (the tool it comes from takes a screen NAME). Substitute your
    own slug, CHECK the result against your own navigation list, and refuse anything that
    is not in it; then change route with the app's own router. Never a full page load and
    never an external address.
  * **ASK BEFORE YOU MOVE IF THE SCREEN BEING LEFT MAY HOLD UNSAVED WORK.** The server
    knows a form exists; only you know whether it is dirty, and a half-typed campaign
    discarded by a screen change is work this assistant destroyed without asking. Prefer
    asking when you cannot tell.
  * `screen` and `where` are the console's own words for the destination and are what a
    person is told and a screen reader announces. `route` is never rendered or spoken.
* `event: step` · `data: {"id": "...", "tool": "...", "status":
  "running"|"done"|"refused"|"failed", "args": "...", "detail": null|"...",
  "elapsed_ms": null|123}` — one tool call as it happens, two frames per call sharing an
  `id`: `running` when it starts, then one terminal frame with `elapsed_ms`. Purely
  observational — dropping every one of them loses no outcome — and safe to render live so
  a person can see which of their data was read and how long it took.
* `event: done` · `data: {"disclosure": null|"...", "metered": true}` — `disclosure` is
  non-null when a substitute model answered and MUST be shown.
* `event: error` · `data: {problem+json}` — a refusal that happened after the stream
  opened. Permission, rate-limit and request-validation refusals arrive as ordinary
  problem+json responses with their real status instead.

`history` is what the browser replays and it still dies with the request — the server keeps
no thread. What IS kept is one redacted, capped memory row per answered question
(`copilot_memories`), which the assistant recalls on later questions from the same person;
it expires on the account's own `copilot_memory` retention policy and is destroyed by
offboarding. Metered against the account's AI allowance and refused before a token is spent
when that allowance is used up (`ai_quota_exceeded` opens the wallet dialog).
Requires `copilot:use` — held by owners and staff.\
"""


def _error_event(problem: ProblemError) -> ServerSentEvent:
    """A refusal as an SSE frame, carrying the SAME body the error handler would have
    written. One problem shape for the whole platform (BACKEND-PATTERNS §3), whether it
    left through a status line or through a stream."""
    return ServerSentEvent(event="error", data=problem.as_problem())


@router.post(
    "/copilot/ask",
    response_class=EventSourceResponse,
    openapi_extra=permission_meta("copilot:use"),
    summary="Ask the in-app assistant about this screen — streamed, metered, quota-gated",
    description=_DESCRIPTION,
)
async def ask_copilot(
    request: Request,
    payload: Annotated[CopilotAskIn, Body()],
    principal: Principal = Depends(requires("copilot:use")),
) -> AsyncIterator[ServerSentEvent]:
    """SUBJECT → GATE → RUN → METER, with the meter and the audit in their own transaction.

    **`copilot:use`, AND IT SAID `org:manage` UNTIL THE FOUNDER DECIDED STAFF MUST BE ABLE
    TO USE THE ASSISTANT.** Read what the old permission was actually doing before reading
    the swap as a relaxation. `org:manage` was never chosen because opening a chat panel is
    an owner's business — it was chosen because this route SPENDS the account's AI
    allowance and therefore needed a member of `MUTATING_PERMISSIONS` (the rule
    `tests/authz_audit_test.py::test_every_mutating_route_is_gated_by_a_mutating_permission`
    states over the whole table), and `org:manage` was the mutating permission a client
    role happened to hold. It carried billing, members and every organization setting as
    passengers.

    **SO THE PROPERTY MOVED WITH THE NAME: `copilot:use` IS ITSELF IN
    `MUTATING_PERMISSIONS`.** A D-22 read-only view-as session still cannot spend a
    client's allowance from a client screen — that refusal is the same refusal, from the
    same list, on the same line of `requires()`. What changed is only WHO ELSE may ask:
    `staff` now hold `copilot:use`, and hold nothing else they did not hold yesterday.

    Gating the thing that SPENDS the allowance more loosely than the panel that displays it
    (`GET /v1/billing/ai-quota`, `billing:read`) would be this product disagreeing with
    itself, and it still does not: `billing:read` is an owner's, and this is a permission
    whose whole content is "may open the assistant".

    ⚠ **THE ADMIN-REALM DEFERRAL RECORDED HERE IS CLOSED (D-499), AND THIS ROUTE IS STILL
    THE CLIENT'S.** What it said, and what was true when it said it: every AI surface in
    this repository is metered per TENANT — `require_ai_assist` takes a `tenant_id`,
    `record_ai_assist_usage` writes `usage_events` (a tenant-scoped RLS table) — so an
    operator with `principal.tenant_id is None` would have meant either spending the
    founder's Azure credential with no ledger row (hard rule 7 forbids it in as many words)
    or charging whichever client's page happened to be open for an operator's typing.

    **BOTH HALVES WERE ANSWERED, AND THE SECOND ONE WAS ANSWERED THE WAY THIS PARAGRAPH
    WAS ARGUING.** The ledger is `platform_ai_usage` (migration `f2c81a4d05e7`), written by
    `billing/platform_ai.py` under the cost name `admin_copilot`; and the founder settled
    who pays with one sentence — *"You never charge a client for your own support work"* —
    so an operator's copilot spend lands on the platform ledger on EVERY path, including
    inside a D-22 view-as session. No client's allowance can be moved by an operator, which
    is exactly the outcome the objection above wanted.

    THE ADMIN REALM IS SERVED BY `POST /v1/admin/copilot/ask` (`copilot/admin_routes.py`)
    AND NOT BY THIS ROUTE, for a mechanical reason and not a policy one: this route is
    `realm="any"`, and `current_any` resolves the admin realm only when an impersonation
    header is present, so an operator on `/admin/ops` is invisible to it. An operator
    INSIDE a view-as session still reaches this line and is still refused here —
    `copilot:use` is in `MUTATING_PERMISSIONS` and is deliberately NOT in
    `rbac.IMPERSONATION_PERMITTED_MUTATIONS` — because a client's own allowance is what
    this route spends. Their assistant is the admin one, on the admin route, on our money.

    **NO `Idempotency-Key`, WHERE `assist_call` REQUIRES ONE, AND THE DIFFERENCE IS WHAT A
    REPLAY WOULD HAVE TO BE.** That route's key works because its answer is one JSON object
    the idempotency record can store and hand back. This answer is a stream, and the only
    way to replay it is to keep the whole of it verbatim, addressable by a caller-supplied
    key. **`copilot_memories` IS NOT THAT STORE and must not be mistaken for it**: it holds
    a redacted, truncated MEMORY of the exchange for the model's benefit, not the byte
    sequence the browser rendered, and nothing addresses it by an idempotency key. A key that
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
    # Guaranteed by the dependency: a client principal always carries one, and the only
    # admin principal that reaches a `realm="any"` route is an impersonating one (which
    # carries the impersonated tenant) — and that one is refused a line earlier by
    # `copilot:use` being a mutating permission. There is therefore no reachable branch to
    # write here, and an unreachable `if` would be a coverage-excluded arm on a money path
    # (hard rule 10's note on suppressions).
    assert principal.tenant_id is not None
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
        # THE GUARD IS RUN OVER THE RENDERED SCREEN, NOT OVER A HAND-LISTED SUBSET OF THE
        # PAYLOAD, and that change closed a live leak rather than tidying one up.
        #
        # It used to enumerate: history, fact VALUES, field values, field labels, field
        # help. `render_screen` also emits the screen title and route, fact KEYS and
        # LABELS, field IDS, and — the one that mattered — every `<option>` value and
        # label. `campaigns/page.tsx` declares its "Calling from" select with
        # `label: number.e164`, so a phone number in E.164 was reaching Azure on every
        # question asked from the campaigns screen, past a guard whose entire job is that
        # it cannot. An enumeration that has to be kept in step with a renderer is the
        # defect class this repo treats as a defect; the renderer's own output cannot
        # drift from itself.
        #
        # Rendered ONCE here and rendered again inside `service.run_copilot`. That is a
        # deliberate cost: threading the block through the streaming path would put a
        # prompt fragment in the route's vocabulary, and the alternative — guarding a
        # subset — is the bug above.
        screen = prompt_module.render_screen(payload)
        prompt_module.assert_screen_fits(screen)
        assert_redacted(screen, *(turn.content for turn in payload.history))

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
            # 2b. MEMORY, ON THE GATE'S SESSION AND NOT A FOURTH ONE, for the reason
            #     `account_assist_leg` is here: it is a single indexed read, it is needed
            #     before the first token, and the alternative is opening a connection of
            #     its own. `recall` never raises (see its docstring) — a person whose
            #     memory query failed gets an answer without memory, never an error
            #     instead of an answer.
            #
            # ONLY THE CLIENT REALM WRITES OR READS ONE. `Principal.user_id` is a
            # `users.id` on this realm and an `admin_users.id` on the other, and
            # `copilot_memories.user_id` has a foreign key to `users`. A D-22 view-as
            # operator is already refused by `copilot:use` being in `MUTATING_PERMISSIONS`,
            # so this guard is unreachable today — and it is the difference between "this
            # cannot happen" and "this cannot happen because of a permission list two
            # modules away", on a path whose failure would be a foreign-key violation
            # inside a streaming response.
            remembered = (
                await memory.recall(
                    gate_session, user_id=principal.user_id, question=payload.question
                )
                if principal.realm == "client" and principal.user_id is not None
                else ()
            )
    except ProblemError as refusal:
        yield _error_event(refusal)
        return

    # 2b. WHAT IS HAPPENING IN THE BUSINESS, read in ITS OWN short session and closed
    #     before the first token. It never raises and it never blocks the answer: a
    #     failed snapshot yields "" and the copilot runs on the screen block alone, which
    #     is what it did before `context.py` existed. Deliberately AFTER the gate — a
    #     client at their ceiling is refused without paying for a snapshot nobody reads —
    #     and deliberately NOT on the gate's session, for the transaction-poisoning reason
    #     `live_state_block` states.
    #     WHO IS ASKING RIDES ALONG (D-522). The screen inventory is static and cached in
    #     the prefix; the person's role, the screen they are on and the screens their role
    #     cannot open are not, so they go in this block. All three are derived from the
    #     VERIFIED principal and the route — never from what the browser says about who it
    #     is — and none of them costs a query. `principal.role` is non-None for the same
    #     reason `tenant_id` is: `requires("copilot:use")` resolved a role to check it.
    assert principal.role is not None
    live = await live_state_block(
        tenant_id, viewer_for(role=principal.role, route=payload.screen.route)
    )
    # MEMORY REACHES THE MODEL AS A `fact`, WHICH IS THE SEAM AND NOT A SHORTCUT.
    # `facts` is already defined as "read-only context the browser volunteers" and
    # `prompt.py` already fences it; a recalled memory is read-only context of exactly that
    # kind, so it needs no new prompt section, no new schema field and no change to the
    # tool loop. Appended AFTER `assert_redacted` deliberately: this text has been through
    # `redact()` on the way IN (`memory.redacted_content` is the only writer), so
    # re-running the guard over it would only be able to fail on a row the database should
    # not contain, in the middle of answering somebody.
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

    # 3. THE RUN. The metering key is minted HERE, by the server, per attempt:
    #    `record_ai_assist_usage` accepts nothing else, because its idempotency is a
    #    switch that turns metering off (D-140).
    ref = new_assist_ref()
    # EVERY SPEND OF THIS RUN, NOT THE LAST ONE, AND THIS USED TO BE A SINGLE SLOT.
    #
    # `run_copilot` can emit MORE THAN ONE `CopilotSpend` in a turn: a leg that failed
    # before it streamed anything is re-selected under `provider_unavailable=True` and the
    # answer is finished on the disclosed Sarvam leg, which is a SECOND capability and a
    # second record. A single slot kept the last one, so the tokens the first leg had
    # already been paid for were never metered — hard rule 7, money paid to a provider with
    # no `usage_event` and no movement of the account's ceiling. Each gets its own `ref`,
    # because `record_ai_assist_usage`'s idempotency is keyed on it and two spends sharing
    # one ref would silently collapse into the first.
    spends: list[service.CopilotSpend] = []
    filled: tuple[str, ...] = ()
    proposed: str | None = None
    acted: list[str] = []
    #: The screen this answer opened, by NAME, or None. One at most (D-524). It is on the
    #: audit row because "the assistant moved me" is a thing a person may later ask about,
    #: and the `copilot.ask` row is the only record of it — navigation writes no row of its
    #: own, deliberately (`copilot/navigation.py`: an append-only hash chain is not where a
    #: screen change belongs).
    navigated: str | None = None
    # THE ANSWER, KEPT ONLY LONG ENOUGH TO REMEMBER IT. Accumulated rather than re-read,
    # because a stream has no "the answer" to read back; bounded by
    # `service.MAX_ANSWER_TOKENS` * `service.MAX_TURNS`, which is the same ceiling the
    # provider bill is under. It is truncated and redacted by `memory.redacted_content`
    # before it reaches a column and is never logged.
    answer_parts: list[str] = []

    # WHICH SIGN-IN RUN THIS ANSWER BELONGS TO (D-540). Read HERE, before the model call,
    # and not inside `_record`: the transcript row has to carry the run that was current
    # when the person ASKED, or a session that expired during a long answer would stamp
    # the turn with a run that had already ended and the next load would delete it.
    #
    # One small query against the credential store per question — timestamps only, no
    # token_hash, no session id (`copilot/session_run.py`) — which is noise beside the
    # model round trip this route is about to make.
    run_started_at = (
        await session_run.current_run_start(realm="client", subject_id=principal.user_id)
        if principal.user_id is not None
        else None
    )

    # 4. THE METER, THE AUDIT AND THE MEMORY, in ONE transaction of their own — the record
    #    of a payment that has already happened. `meter_assist` never raises, and nothing
    #    between the run and the meter may: a completed answer is money spent whether or
    #    not it was any good.
    #
    # **A CLOSURE, BECAUSE THERE ARE NOW FOUR WAYS OUT OF THE RUN AND ALL FOUR OWE THE
    # LEDGER THE SAME ROWS.** It was straight-line code after the `async for`, which meant
    # only the way out that WORKED reached it: a selector refusal, a provider that died
    # mid-answer, and a browser that closed the tab each returned or unwound past it. Three
    # of those are spend (the middle one certainly, the last one usually), so the ledger
    # was complete exactly when nothing had gone wrong. Every exit now calls this, and it
    # is IDEMPOTENT so passing through the `finally` after an arm that already called it
    # costs nothing.
    metered = False
    recorded = False
    #: Did the run finish on its own? False on a refusal, a provider failure and a
    #: disconnect — the three exits that used to skip the ledger entirely.
    completed = False

    async def _record() -> None:
        """Write this run's ledger rows, its audit row and its memory. Once, at most."""
        nonlocal metered, recorded
        if recorded:
            return
        recorded = True
        if not spends:
            # NOTHING WAS PAID FOR. A selector refusal raises before the first request, and
            # a disconnect during the first token has produced no usage figure to record.
            # Writing an audit row for a question nobody was charged for and nobody
            # answered would put a `copilot.ask` entry on the chain with no act behind it.
            return
        async with tenant_session(tenant_id) as record_session:
            # ONE `meter_assist` PER SPEND, EACH UNDER ITS OWN `ref`. The first keeps the
            # ref minted before the run so an operator correlating a log line to a ledger
            # row still finds it; a second leg gets a fresh one, because the idempotency of
            # `record_ai_assist_usage` is keyed on the ref and reusing it would discard the
            # second spend in the name of not double-charging the first.
            refs = [ref if index == 0 else new_assist_ref() for index in range(len(spends))]
            for spent, spend_ref in zip(spends, refs, strict=True):
                metering = await meter_assist(
                    record_session,
                    tenant_id=tenant_id,
                    ref=spend_ref,
                    result=spent,
                    feature=ASSIST_FEATURE_COPILOT,
                    # The model the answer ran on, when the run knows it (D-478: the
                    # account's own Gemini id). `None` on the Azure leg, where
                    # `meter_assist` reads the live `azure_openai_model` setting — the model
                    # behind Azure's deployment is an operator switch, not a per-run fact.
                    model=spent.model,
                )
                # TRUE IF ANY LEG WAS METERED. The flag reaches the browser as "this
                # question was charged for", and a run whose Azure leg was metered and whose
                # Sarvam fallback was not (D-36 prices that leg at zero) WAS charged for.
                metered = metered or metering.metered
            last = spends[-1]
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
                    # THE LEG THAT ANSWERED, and the COUNT of legs this run paid. One row
                    # per question is what an auditor reads, so a run that failed over says
                    # so with a number rather than by being two rows.
                    "provider": last.capability.provider,
                    "fallback_reason": last.capability.fallback_reason,
                    "spend_count": len(spends),
                    "metered": metered,
                    "ref": ref,
                    # WHETHER THE PERSON GOT THE WHOLE ANSWER. A run recorded from the
                    # `finally` was abandoned or interrupted, and an auditor reading a
                    # charge for an answer nobody saw needs to be able to tell.
                    "completed": completed,
                    "filled_field_count": len(filled),
                    # A COUNT AND THE NAMES of the TIER 1 actions this answer performed
                    # (D-500). Each already wrote its own `audit_log` row naming the person
                    # and the object it touched, inside `run_immediate`'s transaction; this
                    # is what the `copilot.ask` row says about the ANSWER, so a reader of
                    # one row can tell that a question changed something. Names only — the
                    # ids are in the rows the actions wrote. `redact_mapping` collapses any
                    # sequence to "[N items]" on the way to the log stream, which is why
                    # the count is stated separately rather than left to be derived from a
                    # field that will not be there.
                    "action_count": len(acted),
                    "actions": sorted(set(acted)),
                    # WHICH TOOL WAS PROPOSED, or None. A NAME and not the arguments: this
                    # row records that the assistant offered a change, and the row that
                    # records the change itself is written by `POST /v1/copilot/confirm`
                    # if — and only if — a person agreed to it.
                    "proposed_tool": proposed,
                    # WHICH SCREEN THIS ANSWER OPENED, or None. A name, never a route.
                    "navigated_to": navigated,
                },
            )
            # 5. THE MEMORY, in the SAME transaction as the meter and the audit, and that
            #    is the whole reason it is here rather than in a session of its own: a
            #    memory of an answer whose `usage_events` row rolled back is a memory of
            #    something that, as far as the ledger is concerned, never happened.
            #
            #    AFTER the audit, so a memory write can never be what stops an
            #    `audit_log` entry from landing. It writes ids, a screen name and prose
            #    that `memory.redacted_content` has already put through `redact()`; it
            #    never logs any of it (hard rule 6), and `remember_exchange` returns None
            #    rather than raising when there is nothing left to store.
            if principal.realm == "client" and principal.user_id is not None:
                # 5a. THE TRANSCRIPT (D-540), before the memory and in the same
                #     transaction, for the memory's own reason: a turn a person can
                #     scroll must not survive a rolled-back `usage_events` row.
                #
                #     BEFORE rather than after, and the order is the only thing to decide
                #     here: the transcript is what the PERSON sees and the memory is what
                #     the MODEL sees, so if one of the two is going to be lost to a
                #     failure between them it should be the one nobody can tell is
                #     missing. Neither raises.
                #
                #     `run_started_at` is None only when the subject has no live session,
                #     which cannot happen on a path that authenticated — it is treated as
                #     "do not store" rather than asserted away, because the alternative is
                #     writing a turn stamped with a run that does not exist and can
                #     therefore never be cleared.
                if run_started_at is not None:
                    await transcript.append_exchange(
                        record_session,
                        realm=transcript.CLIENT,
                        owner_id=principal.user_id,
                        tenant_id=tenant_id,
                        run_started_at=run_started_at,
                        screen_route=payload.screen.route,
                        question=payload.question,
                        answer="".join(answer_parts),
                    )
                await memory.remember_exchange(
                    record_session,
                    tenant_id=tenant_id,
                    user_id=principal.user_id,
                    screen_route=payload.screen.route,
                    question=payload.question,
                    answer="".join(answer_parts),
                    # Counts and names, exactly as the audit summary above — never a field
                    # value, never the model's prose beyond `content` itself.
                    meta={
                        "realm": payload.screen.realm,
                        "provider": last.capability.provider,
                        "filled_field_count": len(filled),
                    },
                )

    try:
        async for event in service.run_copilot(
            payload,
            # The gate's verdict, passed IN rather than re-read. It is False on every
            # path that reaches here — `require_ai_assist` RAISES at the ceiling — and
            # it is written as the READ so that this caller stays correct if the gate
            # ever learns to answer instead of raise.
            tenant_leg=tenant_leg,
            quota_exhausted=quota.at_ceiling,
            # WHO IS ASKING, for the read tools — the RETRIEVAL PORT INCLUDED. The tenant
            # id is what scopes the RLS session each tool opens for itself AND what scopes
            # the retrieval cache's keyspace; the role is what `tools.run_read_tool` judges
            # against the tool's own permission, BEFORE it opens one. Built from the
            # verified principal and never from the body — `payload.screen` is a
            # caller-composed description and is used for the prompt and the audit row,
            # never for authorization (`schemas.CopilotScreen`).
            #
            # THIS IS THE ONLY THING `search_knowledge` IS SCOPED BY, which is why it takes
            # no tenant, agent or source argument: the model can put a question in a tool
            # call and nothing else, so there is no argument it can send that reaches
            # another account's knowledge.
            tool_context=service.ToolContext(tenant_id=tenant_id, role=principal.role),
            live=live,
            # WHO THE ACTIONS RUN AS, and it is the verified principal itself rather than
            # a narrowing of it (D-500). `write_tools.actor_for` still performs that
            # narrowing, once, inside the loop — what changed is that a TIER 1 action also
            # writes an `audit_log` row in its own transaction, and `write_audit` names the
            # actor from a `Principal`. Never from the body: `payload.screen` is a
            # caller-composed description and is used for the prompt and the audit row,
            # never for authorization.
            principal=principal,
            # WHAT MAKES A TIER 1 ACTION'S IDEMPOTENCY KEY STABLE ACROSS A RETRY. The
            # QUESTION and the replayed history — see `write_tools.conversation_seed` for
            # why the metering `ref` above would have been exactly the wrong ingredient
            # (it is minted per attempt, so a retry gets a new one and the guard protects
            # nothing). Composed here because this is the layer that has the request.
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
                # PURELY OBSERVATIONAL and deliberately NOT accumulated: a step is a frame
                # the panel renders live, not an outcome, and nothing downstream of this
                # route — not the meter, not the audit summary, not the memory row — is
                # allowed to depend on one. It carries a bounded preview of a tool's
                # arguments and result, so it is also the one frame that must never be
                # logged or stored (hard rule 6); it is neither.
                yield ServerSentEvent(event="step", data=event.step)
            if event.action is not None:
                # A TIER 1 ACTION THAT HAS ALREADY HAPPENED (D-500). Its `audit_log` row was
                # written inside `run_immediate`, in the same transaction as the change, so
                # the record does not depend on this route reaching its meter.
                acted.append(event.action.tool)
                yield ServerSentEvent(event="action", data=event.action)
            if event.navigate is not None:
                # A SCREEN CHANGE (D-524). The NAME is kept for the audit row, not the
                # route: `object_id` already carries the route the person was ON, and a
                # screen name is this product's own vocabulary rather than a value.
                navigated = event.navigate.screen
                yield ServerSentEvent(event="navigate", data=event.navigate)
            if event.spend is not None:
                spends.append(event.spend)
        completed = True
    except ProblemError as refusal:
        # The selector refused before a request was made — `assist_unavailable` is raised
        # ahead of the first leg — so `spends` is empty and `_record` writes nothing. It is
        # still CALLED rather than skipped: "nothing was paid for on this path" was a claim
        # about `run_copilot`'s control flow made in the wrong file, and the emptiness of
        # the list is the same statement checked instead of asserted.
        await _record()
        yield _error_event(refusal)
        return
    except Exception:
        # A PROVIDER THAT DIED MID-ANSWER IS SPEND, AND THIS ARM USED TO THROW IT AWAY.
        # It returned before the metering block, so a run that really had sent tokens to
        # Azure and then failed was money paid with no `usage_event` behind it — invisible
        # to the account's ceiling and to the platform brake, which is the shape of metering
        # outage `meter_assist` fires an alert for when it can see one. `_record` runs first
        # so the ledger lands before the person is told; the log line stays, because the
        # failure itself is still something an operator should see.
        log.exception("copilot_stream_failed", extra={"tenant_id": str(tenant_id)})
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
        # THE CLIENT WENT AWAY. A browser that navigates or closes the tab makes
        # `sse-starlette` `aclose()` this generator, which throws `GeneratorExit` in at the
        # `yield` above — and every arm before this one is skipped, so an abandoned turn was
        # a turn we paid a provider for and nobody was charged. A `finally` is the only
        # construct that sees that exit. It never yields (which would be illegal here) and
        # `_record` is idempotent, so the ordinary paths that already recorded pass through
        # it for free.
        #
        # **SHIELDED, AND THAT IS THE WHOLE DIFFICULTY OF THIS ARM.** The disconnect usually
        # arrives as a cancellation of the task this generator runs in, so an unshielded
        # `await` here would be cancelled at the first suspension — in the middle of the
        # transaction, which is the one place a partial ledger write would be worse than
        # none. `shield` lets the record finish against a cancellation aimed at the caller.
        # It is not a guarantee: a loop already tearing down still loses it, and there is
        # no outbox on this surface to make it one. What it buys is that the ordinary
        # disconnect is recorded, and the extraordinary one is LOGGED rather than silent —
        # which is what an operator needs to tell "nobody was charged" from "we cannot say".
        try:
            await asyncio.shield(_record())
        except Exception:
            log.exception("copilot_meter_failed", extra={"tenant_id": str(tenant_id)})

    # 4. THE METER AND THE AUDIT ran in `_record` above, on whichever path got here.

    yield ServerSentEvent(
        event="done",
        data=CopilotDoneEvent(
            # THE LEG THAT ACTUALLY ANSWERED, which is the LAST spend and not the first: a
            # run that fell back to Sarvam owes the person that disclosure, and a run that
            # did not has one capability to name either way.
            disclosure=(service.disclosure_for(spends[-1].capability) if spends else None),
            metered=metered,
        ),
    )


_CONFIRM_DESCRIPTION = """\
Carry out the change the assistant proposed, after the person confirmed it.

Post back the `token` from an `event: proposal` frame, **unchanged**. The body carries
nothing else: the account, the person, the tool and every argument are inside the token's
signature, so there is nothing here a browser could edit and nothing a page could invent.

A token works ONCE and only for the account and the person it was minted for, and it stops
working five minutes after it was issued. Every refusal is a 403 with the same shape —
already confirmed, expired, tampered with, or minted elsewhere are deliberately not told
apart, so this endpoint cannot be used to learn which half of a token is wrong.

The change runs through exactly the service function the equivalent button on the screen
calls, so every refusal that button can get, this can get: `409` when a campaign is not
running, `404` when nothing of yours has that id. `applied: false` with a `200` is a real
answer — the world was already in that state and nothing was written.

Every change writes an `audit_log` row naming the person who confirmed it.
Requires `copilot:use`, and the tool's own permission on top of it.\
"""


@router.post(
    "/copilot/confirm",
    response_model=CopilotConfirmOut,
    openapi_extra=permission_meta("copilot:use"),
    summary="Do the change the assistant proposed — once, for the person who confirmed it",
    description=_CONFIRM_DESCRIPTION,
)
async def confirm_copilot_proposal(
    payload: Annotated[CopilotConfirmIn, Body()],
    session: Annotated[AsyncSession, Depends(db)],
    request: Request,
    principal: Principal = Depends(requires("copilot:use")),
) -> CopilotConfirmOut:
    """THE HUMAN-IN-THE-LOOP GATE, and it is this route existing at all.

    **`copilot:use` AT THE DOOR, AND THE TOOL'S OWN PERMISSION INSIDE — and the second
    half is what makes the first half safe to widen.** The door permission is
    `POST /v1/copilot/ask`'s, for its reason: a caller who cannot open the assistant must
    not be able to complete one of its sentences. It is not sufficient on its own and is
    not treated as such — `write_tools.confirm` re-checks the permission the equivalent
    BUTTON declares (`leads:write` for a lead's status, `leads:dispatch` for DNC and for
    pausing, `kb:write` for a knowledge entry), so this route can never be a way to do
    something the console would refuse.

    THAT SEPARATION IS WHY GIVING `staff` THE DOOR GAVE THEM NOTHING BEHIND IT. A staff
    member may now ask the assistant anything and may confirm exactly the changes their own
    role already admits: a lead's status, yes; a knowledge entry, only in an account whose
    owner switched staff curation on (`kb/curation.py`), because that is the answer
    `_may` gets for `kb:write` and it is the same answer the Add-Knowledge form gives.

    Both permissions are mutating, so a D-22 view-as session is refused at both.

    **`Depends(db)` HERE, WHERE `ask` TAKES NONE, AND THE DIFFERENCE IS THE PROVIDER.**
    `ask` must not hold a pooled connection across a model round trip, so it opens short
    sessions of its own. This route calls no model at all: it verifies a signature, burns
    an id and runs one service function. Holding one transaction across those is not a
    cost, it is the REQUIREMENT — the change and its `audit_log` row have to commit
    together or not at all (`compliance/audit.py` holds the chain lock to COMMIT), and two
    sessions could not give that.

    **NO `Idempotency-Key`.** `write_tools.confirm` burns the proposal's `jti` in Redis
    before executing, which is a stronger guarantee than the header's: the header stops one
    client retrying one request, the burn stops one DECISION being submitted twice by any
    means, including a second browser tab holding the same token.
    """
    return await write_tools.confirm(
        session,
        payload.token,
        principal=principal,
        ip=client_request_ip(request),
    )


_CONVERSATION_DESCRIPTION = """\
The conversation you are already having with the assistant, so it survives a refresh, a
navigation, and a browser you closed yesterday afternoon.

**It belongs to YOU, not to one device.** Sign in on a phone while a desktop tab is open
and both show the same thread — the desktop's copy simply does not know about the phone's
newest turn until it loads again, which is the whole of the concurrency story here:
there is no realtime channel and none is needed (see `load_copilot_conversation`).

**It ends when your LAST session ends.** Signing out on one device does not take the
thread away from another, but signing out of the last one does, and so does letting the
last one expire.

Turns come back oldest first, at most `limit` of them, newest page first: pass the `id`
of the oldest turn you hold as `before` to page backwards. `has_more` says whether
anything older exists. `content` is the REDACTED form — a screen value that looked like a
phone number was replaced by a placeholder before the question ever left the browser, and
the placeholder is what was stored.

Requires `copilot:use`.\
"""


@router.get(
    "/copilot/conversation",
    response_model=CopilotConversationOut,
    openapi_extra=permission_meta("copilot:use"),
    summary="The conversation you are already having — durable, per person, paged",
    description=_CONVERSATION_DESCRIPTION,
)
async def load_copilot_conversation(
    session: Annotated[AsyncSession, Depends(db)],
    principal: Principal = Depends(requires("copilot:use")),
    limit: Annotated[int, Query(ge=1, le=transcript.PAGE_MAX)] = transcript.PAGE_DEFAULT,
    before: Annotated[str | None, Query()] = None,
) -> CopilotConversationOut:
    """One page of this person's live conversation.

    **`copilot:use` ON A GET, AND IT IS IN `MUTATING_PERMISSIONS`.** That normally hides
    a read from a D-22 view-as session and normally costs a support person the screen the
    client is describing on the phone, which is what
    `tests/impersonation_reads_test.py::test_no_read_is_gated_on_a_permission_impersonation_refuses`
    exists to catch. Here it costs nothing, and the reason is a fact about the KEY rather
    than a view about support: this route is scoped on `principal.user_id`, and inside an
    impersonated session that value is the OPERATOR'S `admin_users.id` (`core/auth.py`
    builds the principal as `user_id=admin_id` with the client's `tenant_id`).
    `copilot_conversation_turns.user_id` is a foreign key to `users`, so an admin id can
    never appear in it — an impersonated read returns an EMPTY page under any permission,
    and `org:read` would buy the same empty page one round trip later. The path is in
    `ADMIN_CONSOLE_GETS` with that reasoning written out.

    What support CAN see of an assistant answer is what has always been reviewable: the
    `copilot.ask` audit row, naming the screen, the spend and any change the answer made.

    **LOAD ON MOUNT AND APPEND LOCALLY — THERE IS NO REALTIME SYNC, DELIBERATELY.** The
    question was asked and answered rather than assumed: what does a second device see?
    It sees everything up to the moment it loaded, and its own turns after that. Two
    devices used at once therefore diverge until one of them reloads, and the reason that
    is acceptable — where it would not be for, say, a shared lead list — is that this is
    ONE PERSON'S conversation with an assistant, and a person is not usually typing into
    two devices simultaneously. Buying convergence would mean a socket or a poll on every
    open panel (D-24 chose polling for changing state and this is not changing state), for
    a case that costs a reload when it happens. What is NOT left to chance is the store:
    both devices write to the same rows, so nothing is lost, and the second device's next
    load shows the first device's turns in their real order.

    **THE STALE RUN IS CLEARED BY THIS READ**, in this transaction, before anything is
    returned — see `transcript.load`. That is one of the two places "their last session
    ended" is actually observed; the other is the cron.
    """
    if principal.tenant_id is None or principal.user_id is None:
        # Unreachable through `requires("copilot:use")` on the client realm, which resolves
        # both. Raised rather than asserted because an empty page would be a LIE — "you
        # have no conversation" — told to somebody whose conversation we simply failed to
        # look up.
        raise ProblemError(
            kind="permission",
            code="copilot_conversation_not_yours",
            title="The assistant's conversation belongs to a person",
            detail="This credential is not a client-realm user, so it has no conversation.",
            remediation="Sign in to your own dashboard and open the assistant there.",
        )
    run_started_at = await session_run.current_run_start(
        realm="client", subject_id=principal.user_id
    )
    if run_started_at is None:
        # No live session, on a request that authenticated: only reachable if the session
        # ended between the auth dependency and this line. Answering with the empty page
        # is right — the conversation is over — and the next append will not resurrect it.
        return CopilotConversationOut(turns=[], has_more=False)
    page = await transcript.load(
        session,
        realm=transcript.CLIENT,
        owner_id=principal.user_id,
        run_started_at=run_started_at,
        limit=limit,
        before=transcript.turn_cursor(before),
    )
    return transcript.conversation_out(page)


@router.delete(
    "/copilot/conversation",
    response_model=CopilotConversationClearedOut,
    openapi_extra=permission_meta("copilot:use"),
    summary="Start again — forget this conversation on every device",
)
async def clear_copilot_conversation(
    session: Annotated[AsyncSession, Depends(db)],
    principal: Principal = Depends(requires("copilot:use")),
) -> CopilotConversationClearedOut:
    """Forget this person's whole conversation.

    **NO `audit_log` ROW, AND THAT IS HARD RULE 6 RATHER THAN AN OMISSION.** An audit
    entry naming "this person cleared their assistant conversation" records nothing anyone
    can act on and puts a per-person behavioural trail on the compliance chain; the rows
    it describes carry a client's staff prose and are deliberately not durable. What IS
    audited is every ANSWER (`copilot.ask`) and every CHANGE the assistant made
    (`copilot/write_tools.py`), and neither is touched by this.

    It clears every device, because there is one conversation and it belongs to the
    person. A second device discovers it on its next load, which is the same contract as
    every other turn.
    """
    if principal.user_id is None:
        raise ProblemError(
            kind="permission",
            code="copilot_conversation_not_yours",
            title="The assistant's conversation belongs to a person",
            detail="This credential is not a client-realm user, so it has no conversation.",
            remediation="Sign in to your own dashboard and open the assistant there.",
        )
    cleared = await transcript.clear(session, realm=transcript.CLIENT, owner_id=principal.user_id)
    return CopilotConversationClearedOut(cleared=cleared)


__all__ = ["router"]
