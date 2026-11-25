"""Free-trial TEST CALLS: one outbound call to a number the client types (D-697).

A trial account has no number of its own, so every test call rings from ONE shared Calevate
number held in our developer workspace (`Settings.trial_caller_number`). The order:

1. the dial gate, `compliance.service.check_dispatch(trial_call=True)`, which asks the trial's
   own limits (ended, free minutes, today's cap) beside the ordinary rules: the halt, the
   account, the agent and its truthful answers (hard rule 5), the no-cold-calls pledge, the
   agreements, calling hours, India only, the do-not-call list and consent;
2. `agents.service.dispatch_call(trial=...)`, which holds the platform's one trial line in
   the intent transaction (`_hold_trial_line`), lends the shared number to this agent for
   calling out while the number's own line stays the never-answering trial line agent, gives
   the agent the phone surface (`campaigns.engine_numbers.lend_trial_line`), and places the
   call naming the agent, with `from` = the shared number and the per-call
   `maxCallSeconds` override. An agent that only answers calls opens with a "calling you"
   line instead of its greeting (`service.trial_call_first_words`, founder 23 Oct 2026).

The line is released by the call ending (its `calls` row leaving `queued`/`ringing`/
`in_progress`), or by the row ageing out at `trial_access.trial_line_horizon()`.

After the first payment the same route places the owner's PAID test call (D-859,
`agents/paid_test_calls.py`), billed like any call. Once the account holds a number of its
own in its workspace, EVERY test call rings from that number (D-1020, founder 18 Nov 2026):
through the engine agent already there (a live line's, a running campaign's, the agent's
own), or through a short-lived test holder made there for the call (a draft line's, a draft
campaign's, the agent's test copy), kept an hour for a repeat and then given back by the
hourly sweep (`workers/campaign_engine_agents`). When the workspace has no free engine agent
for that holder, it is made in our developer workspace and the call rings from the shared
number instead, and the answer says so (`shared_fallback`). Before the account has a number,
paid tests that need a holder ring from the shared number (D-1018).

An agent holds no engine agent of its own once its lines and campaigns hold them (D-1019), so
its plain test call is the "Just the business" call through its test copy.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final, Literal, TypeVar
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.paid_test_calls import (
    own_number_call_seconds,
    own_test_workspace,
    read_paid_test_access,
    refresh_test_copy,
)
from apps.api.agents.workspace_slots import SLOTS_FULL_CODES
from apps.api.billing.first_payment import has_paid
from apps.api.compliance.audit import write_audit
from apps.api.compliance.service import check_dispatch
from apps.api.compliance.trial_access import read_trial_access
from apps.api.core.alerting import record_compliance_block
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings, resolve_hmac_key
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.engine.outage import engine_outage, phone_service_down
from apps.api.engine.vendor_http import EngineRejectedError
from apps.api.ingest.service import normalize_phone
from apps.api.reliability.service import (
    body_hash,
    claim_idempotency,
    complete_idempotency,
    fail_idempotency,
    mark_idempotency_in_doubt,
    scope_key,
)

log = get_logger(__name__)

TRIAL_CALL_ROUTE: Final = "/v1/trial/calls"

#: Trial calls ring from a number held on ThinnestAI; no other engine carries them.
TRIAL_CALL_ENGINES: Final = frozenset({"thinnest"})

NOT_READY_RULE: Final = "trial_calling_not_ready"
NOT_READY_REASON: Final = "Test calls are not available yet. Please try again later."


_Held = TypeVar("_Held")


@dataclass(frozen=True, slots=True)
class TrialCallResult:
    status: Literal["queued", "blocked"]
    call_handle: str | None = None
    blocked_reason: str | None = None
    blocked_rule: str | None = None
    #: Our `calls.id` for a placed call, so the screen follows that one call by id.
    call_id: UUID | None = None
    #: The number the call rings from when it is the shared trial number, E.164. None on a
    #: paid account's call from its own line, whose number the engine picks.
    caller_number: str | None = None
    #: A paying account with its own number was rung from the shared test number because its
    #: workspace had no free engine agent for this test's holder (D-1020).
    shared_fallback: bool = False

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> TrialCallResult:
        """A stored idempotent answer; one stored before `call_id` existed lacks both keys."""
        call_id = payload.get("call_id")
        return cls(
            status="queued" if payload.get("status") == "queued" else "blocked",
            call_handle=payload.get("call_handle"),
            blocked_reason=payload.get("blocked_reason"),
            blocked_rule=payload.get("blocked_rule"),
            call_id=UUID(call_id) if call_id else None,
            caller_number=payload.get("caller_number"),
            shared_fallback=payload.get("shared_fallback") is True,
        )


def trial_calling_ready() -> bool:
    """Is test calling set up on this deployment: the right engine and a shared number?"""
    settings = get_settings()
    return settings.engine in TRIAL_CALL_ENGINES and bool(settings.trial_caller_number)


def _bad_number() -> ProblemError:
    return ProblemError(
        kind="validation",
        code="trial_call_number_invalid",
        title="Enter an Indian mobile or phone number",
        detail="Test calls go to Indian numbers only, written as 98765 43210 or +91 98765 43210.",
        remediation="Check the number and try again.",
    )


#: The audit action for "this number is mine" (D-855).
NUMBER_ATTESTED_ACTION: Final = "trial.number_attested"


def own_number_ref(tenant_id: UUID, phone_e164: str) -> str:
    """A keyed hash of the number an owner said is theirs: the audit row can show the same
    number was attested again without holding it (hard rule 6; an unkeyed hash of an Indian
    number reverses by enumeration). Keyed like `forwarding/save_number.caller_ref`, with the
    idempotency-scope secret, which never rotates, so one number always gives one ref."""
    settings = get_settings()
    material = resolve_hmac_key(
        settings.idempotency_scope_secret,
        env_var="IDEMPOTENCY_SCOPE_SECRET",
        purpose="own-number attestations",
        code="idempotency_not_configured",
        title="Idempotent requests are not configured",
        local_fallback=f"calevate-local-dev-idempotency-scope-key:{settings.app_env}",
        app_env=settings.app_env,
    )
    message = f"own-number:{tenant_id}:{phone_e164}".encode()
    return hmac.new(material, message, hashlib.sha256).hexdigest()


async def attest_own_number(*, principal: Principal, number: str, ip: str | None) -> None:
    """Record that the person placing a test call said the number is their own (founder,
    23 Oct 2026: a tick, not a code sent to the phone). In the hash-chained audit log, by
    keyed reference only.

    In its own transaction, committed before the dial, never on the request's. An audit
    write holds the chain's advisory lock until its transaction ends
    (`compliance.audit.lock_chain`); on the request's transaction that is until the
    response, across the vendor round trip, and `place_trial_call` records the placed call
    in a transaction of its own, which then waited on that lock until `statement_timeout`
    cancelled it: a rung phone answered 503 `database_busy` (D-863). The tick is a
    statement about the number, true whether or not the dial goes ahead, so committing it
    first loses nothing."""
    assert principal.tenant_id is not None
    tenant_id = principal.tenant_id
    phone = normalize_phone(number)
    if phone is None:
        raise _bad_number()
    async with tenant_session(tenant_id) as attest_session:
        await write_audit(
            attest_session,
            action=NUMBER_ATTESTED_ACTION,
            actor=principal,
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            ip=ip,
            summary={"number_ref": own_number_ref(tenant_id, phone)},
        )


async def place_trial_call(
    session: AsyncSession,
    *,
    principal: Principal,
    tenant_id: UUID | None = None,
    agent_id: UUID,
    number: str,
    idempotency_key: str,
    ip: str | None = None,
    own_number_attested: bool = False,
    business: bool = False,
    line_id: UUID | None = None,
    campaign_id: UUID | None = None,
) -> TrialCallResult:
    """Gate, then place, one test call. `blocked` is an answer, not an exception.

    `tenant_id` is the client's own (its principal) or, for an operator's smoke call from
    the admin console, the tenant named in the path; the gate is the same either way.
    `own_number_attested`: the owner ticked "this number is my own" on this request, which
    lets the call ring outside 09:00-21:00 IST (`check_dispatch`).

    `business`: the agent page's "Just the business" call. It rings through the agent's
    business-only test copy (`agents/business_only`); the gate, the caps and the billing are
    the same. A plain test call of an agent holding no engine agent of its own (D-1019) is
    this call.

    `line_id` rings through that inbound line's own engine agent, `agent_id` being the
    line's voice (Phase 3b). Every gate is the same: the dial gate on the agent, the trial's
    limits, its Studio minutes, a paid account's daily cap. A draft line is put on the
    platform as a test holder first (`inbound/publish.line_test_dial`); a live line rings
    through the engine agent its callers reach.

    `campaign_id` rings through that campaign's own engine agent (D-1003), `agent_id` being its
    voice: published as a test holder first (`campaigns/engine_agent.campaign_test_dial`), so
    a campaign is heard as it would call and the agent is never touched. A running or paused
    campaign rings through its own engine agent.

    Where it rings from is the module's rule: the client's own number on a paying account
    holding one (a line's from one of its numbers, a campaign's from its calling number,
    anything else from the account's first), with the shared test number when its workspace
    has no room for the holder; the shared test number otherwise. A paying account's test
    call is billed like any call (`OwnerTestDial`); from its own number it may run to the
    agent's own longest-call setting (`own_number_call_seconds`), and on the shared number it
    is cut at that line's per-call limit, since the one number serves every account in turn."""
    if sum((business, line_id is not None, campaign_id is not None)) > 1:
        raise ValueError("a test call rings the business copy, a line or a campaign, one of them")
    tenant_id = tenant_id or principal.tenant_id
    assert tenant_id is not None
    phone = normalize_phone(number)
    if phone is None:
        raise _bad_number()
    # Before the idempotency claim and every engine request: while the engine is not
    # answering, a press costs one clear sentence rather than a ten-second timeout, an
    # unconfirmed dial holding the shared test line, and a key stuck "in flight".
    if (await engine_outage()).failing:
        raise phone_service_down()
    # A paid account's own test call rings from its own number, so only the engine is asked;
    # every call on the shared trial line needs that number too.
    paid_account = await has_paid(session, tenant_id=tenant_id)
    # A paying account with a number of its own rings every test call from it (D-1020).
    own = paid_account and await own_test_workspace(session, tenant_id=tenant_id) is not None
    # The request's own `business` stays what the idempotency key is checked against.
    through_copy = business or (
        line_id is None
        and campaign_id is None
        and await _holds_own_engine_agent(session, agent_id) is False
    )
    on_trial_line = not own and (
        through_copy
        or not paid_account
        or await _tests_on_shared_line(session, line_id=line_id, campaign_id=campaign_id)
    )
    if not (
        trial_calling_ready() if on_trial_line else get_settings().engine in TRIAL_CALL_ENGINES
    ):
        return TrialCallResult(
            status="blocked", blocked_reason=NOT_READY_REASON, blocked_rule=NOT_READY_RULE
        )

    async with tenant_session(tenant_id) as claim_session:
        claim = await claim_idempotency(
            claim_session,
            scope=scope_key(tenant_id=tenant_id, user_id=principal.user_id),
            route=TRIAL_CALL_ROUTE,
            method="POST",
            key=idempotency_key,
            request_hash=body_hash(
                {
                    "agent_id": str(agent_id),
                    "number": phone,
                    **({"business": business} if business else {}),
                    **({"line_id": str(line_id)} if line_id is not None else {}),
                    **({"campaign_id": str(campaign_id)} if campaign_id is not None else {}),
                }
            ),
        )
    if claim.state == "replay" and claim.response_payload:
        return TrialCallResult.from_payload(claim.response_payload)

    async def release() -> None:
        async with tenant_session(tenant_id) as fail_session:
            await fail_idempotency(fail_session, claim=claim)

    try:
        decision = await check_dispatch(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            phone_e164=phone,
            trial_call=True,
            own_number_attested=own_number_attested,
            through_line=line_id is not None or campaign_id is not None,
            campaign_id=campaign_id,
            through_test_copy=through_copy,
        )
        access = await read_trial_access(session, tenant_id=tenant_id)
        # After the first payment: the owner's test call from the account's own number (D-859).
        # A line's test call never takes the agent's own line, so the agent's is not asked.
        paid = (
            await read_paid_test_access(
                session, tenant_id=tenant_id, agent_id=agent_id if line_id is None else None
            )
            if access is None
            else None
        )
    except Exception:
        await release()
        raise

    async def blocked(rule: str | None, reason: str | None) -> TrialCallResult:
        record_compliance_block(rule=rule or "unknown")
        result = TrialCallResult(status="blocked", blocked_reason=reason, blocked_rule=rule)
        async with tenant_session(tenant_id) as done_session:
            await complete_idempotency(
                done_session,
                claim=claim,
                response_status=200,
                response_payload=_payload(result),
            )
        return result

    if not decision.allowed:
        return await blocked(decision.rule, decision.reason)
    if paid is not None and paid.blocker is not None:
        return await blocked(*paid.blocker)
    if paid is None and access is None:
        return await blocked(NOT_READY_RULE, NOT_READY_REASON)

    from apps.api.agents.service import (
        CampaignDial,
        CopyTestDial,
        DialUnconfirmedError,
        LineTestDial,
        OwnerTestDial,
        TrialDial,
        caller_lines,
        dial_was_not_placed,
        dispatch_call,
    )

    # Whether a holder this test needs was made in our workspace because the client's had no
    # free engine agent (D-1020): the call then rings from the shared test number, and the
    # screen says why.
    shared_fallback = False

    async def slots_full(refused: ProblemError) -> TrialCallResult:
        # The full workspace's own refusal, said instead of "not available yet" when there is
        # no shared number to fall back to: the owner can free a setup, but cannot set ours.
        reason = " ".join(part for part in (refused.detail, refused.remediation) if part)
        return await blocked(refused.code, reason)

    async def ready(make: Callable[[bool], Awaitable[_Held]]) -> _Held | ProblemError:
        """The holder this test rings through: made in the client's workspace when the account
        tests from its own number, else in ours. A full client workspace (our pre-check, or
        the platform's own 409, `create-agent.md:654-668` in the 2026-10-19 mirror) falls back
        to ours; the refusal itself when that needs the shared number and none is set."""
        nonlocal shared_fallback
        try:
            try:
                return await make(own)
            except ProblemError as refused:
                if not (own and refused.code in SLOTS_FULL_CODES):
                    raise
                if not trial_calling_ready():
                    return refused
            log.info("test_call_slots_full_fallback", extra={"tenant_id": str(tenant_id)})
            shared_fallback = True
            return await make(False)
        except Exception:
            await release()
            raise

    line_test: LineTestDial | None = None
    if line_id is not None:
        from apps.api.inbound.publish import line_test_dial

        made_line = await ready(
            lambda in_client: line_test_dial(
                tenant_id=tenant_id, line_id=line_id, in_client=in_client
            )
        )
        if isinstance(made_line, ProblemError):
            return await slots_full(made_line)
        line_test = made_line
        try:
            no_number = (
                paid is not None
                and not line_test.developer
                and not await caller_lines(session, agent_id=agent_id, dial_ref=line_test.ref)
            )
        except Exception:
            await release()
            raise
        if no_number:
            return await blocked(LINE_TEST_NO_NUMBER_RULE, LINE_TEST_NO_NUMBER_REASON)

    campaign_test: CampaignDial | None = None
    if campaign_id is not None:
        from apps.api.campaigns.engine_agent import campaign_test_dial

        made_campaign = await ready(
            lambda in_client: campaign_test_dial(
                tenant_id=tenant_id, campaign_id=campaign_id, in_client=in_client
            )
        )
        if isinstance(made_campaign, ProblemError):
            return await slots_full(made_campaign)
        campaign_test = made_campaign

    # Which test copy of the agent the call rings through, if any: "Just the business" for a
    # plain test of an agent holding no engine agent of its own (D-1019); the agent's own
    # config for a paid account's agent that cannot ring itself (D-859, option A), always so
    # once the account has a number (D-1020). A paid agent on its own number, or one not yet
    # moved out of our workspace on an account with no number, rings through its own.
    copy_business: bool | None = None
    if through_copy:
        copy_business = True
    elif (
        paid is not None
        and campaign_test is None
        and line_test is None
        and paid.line in ("trial_line_own", "trial_line_copy")
        and (own or paid.line == "trial_line_copy")
    ):
        copy_business = False
    copy_ref: str | None = None
    if copy_business is not None:
        business_copy = copy_business
        # Republished first so it never lags the agent.
        made_copy = await ready(
            lambda in_client: refresh_test_copy(
                tenant_id=tenant_id, agent_id=agent_id, business=business_copy, in_client=in_client
            )
        )
        if isinstance(made_copy, ProblemError):
            return await slots_full(made_copy)
        copy_ref = made_copy

    # The shared test line: every free-trial call, and a paid one rung through an engine agent
    # in our developer workspace. Anything else rings from the client's own number through an
    # engine agent in its workspace: a running or paused campaign's, a live line's, the
    # agent's own, or a test holder made there for this call.
    on_shared = paid is None or (
        (campaign_test is not None and campaign_test.developer)
        or (line_test is not None and line_test.developer)
        or (copy_ref is not None and (not own or shared_fallback))
        or (
            copy_ref is None
            and campaign_test is None
            and line_test is None
            and paid.line == "trial_line_own"
        )
    )
    if paid is None:
        assert access is not None  # refused above otherwise
        call_seconds = access.call_seconds
    elif on_shared:
        # That one number serves every account's test calls in turn (D-904).
        call_seconds = get_settings().trial_call_max_seconds
    else:
        call_seconds = own_number_call_seconds(await _agent_call_cap(session, agent_id))
    trial: TrialDial | None = None
    copy_test: CopyTestDial | None = None
    # Billed like any call, wherever it rings from (D-859).
    owner_test = (
        None
        if paid is None
        else OwnerTestDial(
            max_call_seconds=call_seconds, daily_cap=paid.daily_cap, day_start=paid.day_start
        )
    )
    if on_shared:
        caller_number = get_settings().trial_caller_number
        if caller_number is None:
            # Checked before anything was readied; only a campaign that stopped in between,
            # or the setting cleared meanwhile, lands here.
            return await blocked(NOT_READY_RULE, NOT_READY_REASON)
        trial = TrialDial(
            from_e164=caller_number,
            max_call_seconds=call_seconds,
            agent_ref=copy_ref or (campaign_test.ref if campaign_test is not None else None),
        )
    elif copy_ref is not None:
        copy_test = CopyTestDial(ref=copy_ref)
    # A campaign's test from the client's number rings from the number its calls ring from.
    campaign_number = (
        await _campaign_number(session, campaign_test.campaign_id)
        if campaign_test is not None and trial is None
        else None
    )
    tester_name = (
        await _tester_name(session, principal=principal, campaign_id=campaign_test.campaign_id)
        if campaign_test is not None
        else None
    )
    reserved: list[UUID] = []

    async def note_call_id(_intent: AsyncSession, call_id: UUID) -> None:
        reserved.append(call_id)

    # Committed before the phone can ring: from here the key is never re-run unless a
    # failure proves no line was seized (`crm/lead_dial.place_lead_call`'s rule).
    async with tenant_session(tenant_id) as doubt_session:
        await mark_idempotency_in_doubt(doubt_session, claim=claim)
    try:
        handle = await dispatch_call(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            lead_id=None,
            phone_e164=phone,
            lead_name=tester_name,
            on_reserved=note_call_id,
            trial=trial,
            owner_test=owner_test,
            # The gate let this one ring outside the window, so the engine must too (D-866).
            rings_at_any_hour=own_number_attested,
            line_test=line_test,
            campaign=campaign_test,
            copy_test=copy_test,
            number_id=campaign_number,
        )
    except DialUnconfirmedError as unconfirmed:
        raise ProblemError(
            kind="dependency",
            code="dial_unconfirmed",
            title="We could not confirm whether the test call was placed",
            detail="The call may have started anyway.",
            remediation="Wait a minute and check your calls before trying again.",
        ) from unconfirmed
    except Exception as refused:
        if dial_was_not_placed(refused):
            await release()
        if isinstance(refused, EngineRejectedError) and refused.setup_refused:
            # Our set-up at the voice platform, which the client cannot fix and the
            # `engine_dial_setup_refused` alarm has already paged us about.
            raise _not_placed_on_our_side() from refused
        raise

    result = TrialCallResult(
        status="queued",
        call_handle=handle,
        call_id=reserved[0],
        caller_number=trial.from_e164 if trial is not None else None,
        shared_fallback=shared_fallback and trial is not None,
    )
    async with tenant_session(tenant_id) as record_session:
        await write_audit(
            record_session,
            action="trial.test_call_placed",
            actor=principal,
            tenant_id=tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip=ip,
            summary={
                "engine": get_engine().name,
                "max_call_seconds": str(call_seconds),
                "paid": str(paid is not None),
                "shared_line": str(trial is not None),
                **({"shared_fallback": "True"} if result.shared_fallback else {}),
                **({"line_id": str(line_id)} if line_id is not None else {}),
                **({"campaign_id": str(campaign_id)} if campaign_id is not None else {}),
            },
        )
        await complete_idempotency(
            record_session,
            claim=claim,
            response_status=200,
            response_payload=_payload(result),
        )
    log.info("trial_call_placed", extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id)})
    return result


TRIAL_CALL_NOT_PLACED: Final = "trial_call_not_placed"

#: A paid account's line test rings from one of its own numbers; with none in the line's
#: workspace there is nothing it can ring from yet.
LINE_TEST_NO_NUMBER_RULE: Final = "line_test_no_number"
LINE_TEST_NO_NUMBER_REASON: Final = "Get a number first. Test calls ring from your own number."


async def _tester_name(
    session: AsyncSession, *, principal: Principal, campaign_id: UUID
) -> str | None:
    """The name of the client user placing a campaign's test call, sent as the call's
    `{{lead_name}}` where the campaign's list carries names (D-1045): its script greets a
    known contact by name, so a nameless test is asked what a real call already has. None,
    and the call stays nameless, for an operator's call, a user with no name on file, or a
    name holding a digit, which may be a phone number."""
    if principal.realm != "client" or principal.user_id is None:
        return None
    row = (
        await session.execute(
            text(
                "SELECT u.name FROM users u WHERE u.id = :uid AND u.deactivated_at IS NULL "
                "AND EXISTS (SELECT 1 FROM campaign_contacts cc WHERE cc.campaign_id = :cid "
                "AND btrim(coalesce(cc.name, '')) <> '')"
            ),
            {"uid": principal.user_id, "cid": campaign_id},
        )
    ).first()
    name = " ".join(str(row[0] or "").split()) if row is not None else ""
    if not name or any(ch.isdigit() for ch in name):
        return None
    return name


async def _tests_on_shared_line(
    session: AsyncSession, *, line_id: UUID | None, campaign_id: UUID | None
) -> bool:
    """Will this test call ring from the shared test line whatever the account (D-1018)? A
    draft line's, and a campaign's that is not running or paused: their test holders are made
    in our developer workspace. Asked before the gate, so a platform with no shared line set
    up refuses before anything is readied."""
    from apps.api.agents.service import CAMPAIGN_HOLDING_STATUSES

    if line_id is not None:
        published = await session.execute(
            text("SELECT published_at IS NULL FROM inbound_lines WHERE id = :lid"),
            {"lid": line_id},
        )
        return bool(published.scalar_one_or_none())
    if campaign_id is not None:
        status = await session.execute(
            text("SELECT status FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
        )
        found = status.scalar_one_or_none()
        return found is not None and found not in CAMPAIGN_HOLDING_STATUSES
    return False


async def _campaign_number(session: AsyncSession, campaign_id: UUID) -> UUID | None:
    """The number a campaign's calls ring from (`campaigns.number_id`), if it chose one."""
    value = (
        await session.execute(
            text("SELECT number_id FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
        )
    ).scalar_one_or_none()
    return None if value is None else UUID(str(value))


async def _holds_own_engine_agent(session: AsyncSession, agent_id: UUID) -> bool | None:
    """Does the agent still hold an engine agent of its own (D-1019)? None for an agent this
    account does not have, which the dial gate words."""
    value = (
        await session.execute(
            text(
                "SELECT engine_agent_ref IS NOT NULL FROM agents "
                "WHERE id = :aid AND deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).scalar()
    return None if value is None else bool(value)


async def _agent_call_cap(session: AsyncSession, agent_id: UUID) -> int | None:
    value = (
        await session.execute(
            text("SELECT max_call_duration_s FROM agents WHERE id = :aid"), {"aid": agent_id}
        )
    ).scalar()
    return None if value is None else int(value)


def _not_placed_on_our_side() -> ProblemError:
    return ProblemError(
        kind="dependency",
        code=TRIAL_CALL_NOT_PLACED,
        title="We couldn't place this test call",
        detail=(
            "This is a problem on our side, not with your agent or the number you entered. "
            "We've been told and are fixing it."
        ),
        remediation="Please try again later.",
        status=503,
    )


def _payload(result: TrialCallResult) -> dict[str, str | bool | None]:
    return {
        "status": result.status,
        "call_handle": result.call_handle,
        "blocked_reason": result.blocked_reason,
        "blocked_rule": result.blocked_rule,
        "call_id": str(result.call_id) if result.call_id else None,
        "caller_number": result.caller_number,
        "shared_fallback": result.shared_fallback,
    }


__all__ = [
    "LINE_TEST_NO_NUMBER_REASON",
    "LINE_TEST_NO_NUMBER_RULE",
    "NOT_READY_REASON",
    "NOT_READY_RULE",
    "TRIAL_CALL_ENGINES",
    "TRIAL_CALL_ROUTE",
    "TrialCallResult",
    "place_trial_call",
    "trial_calling_ready",
]
