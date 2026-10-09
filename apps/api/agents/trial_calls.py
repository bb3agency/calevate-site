"""Free-trial TEST CALLS: one outbound call to a number the client types (D-697).

A trial account has no number of its own, so every test call rings from ONE shared Calevate
number held in our developer workspace (`Settings.trial_caller_number`). The order:

1. the dial gate, `compliance.service.check_dispatch(trial_call=True)`, which asks the trial's
   own limits (ended, free minutes, today's cap) beside the ordinary rules: the halt, the
   account, the agent and its truthful answers (hard rule 5), the no-cold-calls pledge, the
   agreements, calling hours, India only, the do-not-call list and consent;
2. `agents.service.dispatch_call(trial=...)`, which holds the platform's one trial line in
   the intent transaction (`_hold_trial_line`), lends the shared number to this agent with
   nothing answering it (`campaigns.engine_numbers.lend_trial_line`), and places the call
   with `from` = the shared number and the per-call `maxCallSeconds` override.

The line is released by the call ending (its `calls` row leaving `queued`/`ringing`/
`in_progress`), or by the row ageing out at `trial_access.trial_line_horizon()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.compliance.service import check_dispatch
from apps.api.compliance.trial_access import read_trial_access
from apps.api.core.alerting import record_compliance_block
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
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
_NOT_PLACED: Final = frozenset({"trial_line_busy", "trial_line_unavailable"})


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
    if not trial_calling_ready():
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
    except Exception:
        await release()
        raise
    if not decision.allowed or access is None:
        record_compliance_block(rule=decision.rule or "unknown")
        result = TrialCallResult(
            status="blocked", blocked_reason=decision.reason, blocked_rule=decision.rule
        )
        async with tenant_session(tenant_id) as done_session:
            await complete_idempotency(
                done_session,
                record_id=claim.record_id,
                response_status=200,
                response_payload=_payload(result),
            )
        return result

    from apps.api.agents.service import (
        DialUnconfirmedError,
        TrialDial,
        dial_was_not_placed,
        dispatch_call,
    )

    settings = get_settings()
    assert settings.trial_caller_number is not None  # `trial_calling_ready` above
    try:
        handle = await dispatch_call(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            lead_id=None,
            phone_e164=phone,
            trial=TrialDial(
                from_e164=settings.trial_caller_number, max_call_seconds=access.call_seconds
            ),
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
            summary={"engine": get_engine().name, "max_call_seconds": str(access.call_seconds)},
        )
        await complete_idempotency(
            record_session,
            record_id=claim.record_id,
            response_status=200,
            response_payload=_payload(result),
        )
    log.info("trial_call_placed", extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id)})
    return result


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
