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
`agents/paid_test_calls.py`): from the agent's own number in the account's own workspace,
billed like any call, never from the shared number.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.paid_test_calls import (
    DAILY_CAP_RULE,
    read_paid_test_access,
    refresh_test_copy,
)
from apps.api.billing.first_payment import has_paid
from apps.api.compliance.audit import write_audit
from apps.api.compliance.service import check_dispatch
from apps.api.compliance.trial_access import TRIAL_STUDIO_MINUTES_USED_RULE, read_trial_access
from apps.api.core.alerting import record_compliance_block
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings, resolve_hmac_key
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.engine.vendor_http import EngineRejectedError
from apps.api.ingest.service import normalize_phone
from apps.api.reliability.service import (
    body_hash,
    claim_idempotency,
    complete_idempotency,
    fail_idempotency,
    scope_key,
)

log = get_logger(__name__)

TRIAL_CALL_ROUTE: Final = "/v1/trial/calls"

#: Trial calls ring from a number held on ThinnestAI; no other engine carries them.
TRIAL_CALL_ENGINES: Final = frozenset({"thinnest"})

NOT_READY_RULE: Final = "trial_calling_not_ready"
NOT_READY_REASON: Final = "Test calls are not available yet. Please try again later."

#: Refusals raised before anything rang, after which the client's retry must be allowed.
_NOT_PLACED: Final = frozenset(
    {"trial_line_busy", "trial_line_unavailable", TRIAL_STUDIO_MINUTES_USED_RULE, DAILY_CAP_RULE}
)


@dataclass(frozen=True, slots=True)
class TrialCallResult:
    status: Literal["queued", "blocked"]
    call_handle: str | None = None
    blocked_reason: str | None = None
    blocked_rule: str | None = None


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


async def attest_own_number(
    session: AsyncSession, *, principal: Principal, number: str, ip: str | None
) -> None:
    """Record that the person placing a test call said the number is their own (founder,
    23 Oct 2026: a tick, not a code sent to the phone). In the hash-chained audit log, by
    keyed reference only."""
    assert principal.tenant_id is not None
    phone = normalize_phone(number)
    if phone is None:
        raise _bad_number()
    await write_audit(
        session,
        action=NUMBER_ATTESTED_ACTION,
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="organization",
        object_id=str(principal.tenant_id),
        ip=ip,
        summary={"number_ref": own_number_ref(principal.tenant_id, phone)},
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
) -> TrialCallResult:
    """Gate, then place, one test call. `blocked` is an answer, not an exception.

    `tenant_id` is the client's own (its principal) or, for an operator's smoke call from
    the admin console, the tenant named in the path; the gate is the same either way."""
    tenant_id = tenant_id or principal.tenant_id
    assert tenant_id is not None
    phone = normalize_phone(number)
    if phone is None:
        raise _bad_number()
    # A paid account's test call rings from its own number, so only the engine is asked.
    paid_account = await has_paid(session, tenant_id=tenant_id)
    if not (get_settings().engine in TRIAL_CALL_ENGINES if paid_account else trial_calling_ready()):
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
            request_hash=body_hash({"agent_id": str(agent_id), "number": phone}),
        )
    if claim.state == "replay" and claim.response_payload:
        return TrialCallResult(**claim.response_payload)

    async def release() -> None:
        async with tenant_session(tenant_id) as fail_session:
            await fail_idempotency(fail_session, record_id=claim.record_id)

    try:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone, trial_call=True
        )
        access = await read_trial_access(session, tenant_id=tenant_id)
        # After the first payment: the owner's test call from the account's own number (D-859).
        paid = (
            await read_paid_test_access(session, tenant_id=tenant_id, agent_id=agent_id)
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
                record_id=claim.record_id,
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
        DialUnconfirmedError,
        OwnerTestDial,
        TrialDial,
        dial_was_not_placed,
        dispatch_call,
    )

    trial: TrialDial | None = None
    owner_test: OwnerTestDial | None = None
    if paid is not None:
        call_seconds = paid.max_call_seconds
        owner_test = OwnerTestDial(
            max_call_seconds=call_seconds, daily_cap=paid.daily_cap, day_start=paid.day_start
        )
        if paid.line in ("trial_line_own", "trial_line_copy"):
            # Before the client has a number of its own: the shared trial line, through the
            # agent's developer-workspace engine agent, republished first when it is the test
            # copy so it never lags the agent (D-859, option A).
            try:
                dial_ref = (
                    await refresh_test_copy(tenant_id=tenant_id, agent_id=agent_id)
                    if paid.line == "trial_line_copy"
                    else None
                )
            except Exception:
                await release()
                raise
            caller_number = get_settings().trial_caller_number
            assert caller_number is not None  # `read_paid_test_access` refused otherwise
            trial = TrialDial(
                from_e164=caller_number, max_call_seconds=call_seconds, agent_ref=dial_ref
            )
    else:
        assert access is not None  # refused above otherwise
        caller_number = get_settings().trial_caller_number
        assert caller_number is not None  # `trial_calling_ready` above
        call_seconds = access.call_seconds
        trial = TrialDial(from_e164=caller_number, max_call_seconds=call_seconds)
    try:
        handle = await dispatch_call(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            lead_id=None,
            phone_e164=phone,
            trial=trial,
            owner_test=owner_test,
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
        if dial_was_not_placed(refused) or (
            isinstance(refused, ProblemError) and refused.code in _NOT_PLACED
        ):
            await release()
        if isinstance(refused, EngineRejectedError) and refused.setup_refused:
            # Our set-up at the voice platform, which the client cannot fix and the
            # `engine_dial_setup_refused` alarm has already paged us about.
            raise _not_placed_on_our_side() from refused
        raise

    result = TrialCallResult(status="queued", call_handle=handle)
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
            },
        )
        await complete_idempotency(
            record_session,
            record_id=claim.record_id,
            response_status=200,
            response_payload=_payload(result),
        )
    log.info("trial_call_placed", extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id)})
    return result


TRIAL_CALL_NOT_PLACED: Final = "trial_call_not_placed"


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


def _payload(result: TrialCallResult) -> dict[str, str | None]:
    return {
        "status": result.status,
        "call_handle": result.call_handle,
        "blocked_reason": result.blocked_reason,
        "blocked_rule": result.blocked_rule,
    }


__all__ = [
    "NOT_READY_REASON",
    "NOT_READY_RULE",
    "TRIAL_CALL_ENGINES",
    "TRIAL_CALL_ROUTE",
    "TrialCallResult",
    "place_trial_call",
    "trial_calling_ready",
]
