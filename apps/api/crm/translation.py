"""Asking again for a call's English (founder decision 2, 11 Oct 2026).

The request side of `workers/call_translation`: a compare-and-swap of
`calls.translation_state` from `failed`/`unavailable` to `pending` and an outbox row in the
same transaction, so the state the screen polls and the job that will settle it share a
fate. Idempotent by that swap: a second press finds `pending` and queues nothing.
"""

from __future__ import annotations

from typing import Final, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.crm.schemas import TranslationState
from apps.api.reliability.service import enqueue_outbox

#: The ARQ name of `workers/call_translation.translate_call_job`.
TRANSLATE_CALL_JOB: Final = "translate_call_job"
#: States a "Try again" can start from. Every other state is answered as it stands.
RETRYABLE_STATES: Final = ("failed", "unavailable")


async def translation_state(session: AsyncSession, call_id: UUID) -> TranslationState:
    """The call's state, refusing a call with nothing to translate before any money is
    asked for."""
    row = (
        await session.execute(
            text(
                "SELECT c.translation_state, EXISTS (SELECT 1 FROM transcript_turns t "
                "WHERE t.call_id = c.id AND t.tenant_id = c.tenant_id) "
                "FROM calls c WHERE c.id = :cid"
            ),
            {"cid": call_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Call")
    if not row[1]:
        raise ProblemError.business_rule(
            "translation_nothing_to_translate",
            "This call has no conversation to put into English.",
        )
    return cast(TranslationState, str(row[0]))


async def request_translation(
    session: AsyncSession, *, tenant_id: UUID, call_id: UUID
) -> TranslationState:
    """Queue the call's English at the client's cost. Returns the state after the request:
    `pending` when this request queued it, or the state it found when there was nothing
    to retry (`pending`, `ready`, `not_needed`)."""
    claimed = (
        await session.execute(
            text(
                "UPDATE calls SET translation_state = 'pending', updated_at = now() "
                "WHERE id = :cid AND translation_state IN ('failed', 'unavailable') "
                "RETURNING id"
            ),
            {"cid": call_id},
        )
    ).first()
    if claimed is None:
        return await translation_state(session, call_id)
    await enqueue_outbox(
        session,
        job=TRANSLATE_CALL_JOB,
        payload={"tenant_id": str(tenant_id), "call_id": str(call_id), "payer": "client"},
    )
    return "pending"


__all__ = [
    "RETRYABLE_STATES",
    "TRANSLATE_CALL_JOB",
    "request_translation",
    "translation_state",
]
