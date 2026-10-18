"""A second reading of one call over its REDACTED transcript (D-127 G-2/G-5/G-6).

Asked of Pip since D-821 (`copilot/assist_actions.call_summarise_again`); this was the body
of `POST /v1/calls/{id}/assist`, moved unchanged in its order and its rules:

SUBJECT → GATE → RUN → METER (`crm/assist.py` argues each arrow). The subject is the
redacted transcript (`assist.load_assist_source`, which refuses a call with no transcript or
a turn with no redacted copy before any money is at stake); the gate is `require_ai_assist`,
which raises `ai_quota_exceeded` at the ceiling; the run is `run_assist` on the account's
own leg; every paid leg is metered under `resummarise` in its own transaction, a refused
paid leg too. The answer goes out through `crm.service.redacted_summary`, the same pass as
`calls.summary`. Nothing is stored: the call's own summary is the first pass over the raw
transcript and stays as it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.assist_leg import account_assist_leg
from apps.api.billing.ai_quota import new_assist_ref, require_ai_assist
from apps.api.core.errors import ProblemError
from apps.api.crm import assist, service
from apps.api.db.session import tenant_session
from apps.workers.extraction import run_assist


@dataclass(frozen=True, slots=True)
class SecondReading:
    #: May be empty: a completed run that produced nothing is an outcome the person is told.
    summary: str
    #: G-6: set exactly when something other than the assistant model answered.
    disclosure: str | None
    #: Whether this reached `usage_events` as the client's spend.
    metered: bool
    provider: str | None
    fallback_reason: str | None
    #: The metering key, for the audit row.
    ref: str


async def check_readable(session: AsyncSession, call_id: UUID) -> None:
    """The subject's refusals, without spending: no call, no transcript, a hole in it."""
    await assist.load_assist_source(session, call_id)


async def second_reading(session: AsyncSession, *, tenant_id: UUID, call_id: UUID) -> SecondReading:
    source = await assist.load_assist_source(session, call_id)
    quota = await require_ai_assist(session, tenant_id=tenant_id)
    ref = new_assist_ref()
    tenant_leg = await account_assist_leg(session)
    try:
        result = await run_assist(
            source.spec,
            # `text_redacted`, assembled by `crm/assist.py`, which never names the raw
            # column; `run_assist` re-runs `redact()` over it and refuses text that still
            # matches.
            source.transcript,
            tenant_leg=tenant_leg,
            quota_exhausted=quota.at_ceiling,
            languages=source.languages,
        )
    except ProblemError as refused:
        async with tenant_session(tenant_id) as record:
            await assist.meter_refusal(
                record,
                tenant_id=tenant_id,
                refusal=refused,
                feature=assist.ASSIST_FEATURE_RESUMMARISE,
            )
        raise
    # A completed run is money spent: recorded in its own transaction, so a later failure
    # cannot roll back the record of a payment already made.
    async with tenant_session(tenant_id) as record:
        charged_earlier = await assist.meter_earlier(
            record,
            tenant_id=tenant_id,
            earlier=result.earlier,
            feature=assist.ASSIST_FEATURE_RESUMMARISE,
        )
        metered = await assist.meter_assist(
            record, tenant_id=tenant_id, ref=ref, result=result, model=result.model
        )
    return SecondReading(
        summary=service.redacted_summary(result.output.summary) or "",
        disclosure=result.capability.disclosure,
        metered=metered.metered or charged_earlier,
        provider=result.capability.provider,
        fallback_reason=result.capability.fallback_reason,
        ref=ref,
    )


__all__ = ["SecondReading", "check_readable", "second_reading"]
