"""The in-call opt-out job — the BELT half of `compliance/optout.py`'s two layers.

voice-runtime's `/tools/v1/opt-out` acks the engine's tool call in milliseconds and
queues this (hard rule 3: no DB writes there, no tenant resolution, no vendor fetch).
Everything that actually costs something happens here, in a worker, exactly as the
webhook receiver hands its work to `ingest_engine_event`.

**The tool payload is a HINT; the fetch is the truth** (D-31). The endpoint is unsigned
and IP-allowlisted, so a payload-supplied phone number would let anyone inside that
allowlist suppress an arbitrary number on an arbitrary tenant — a denial-of-service
against a client's own contact list, dressed as compliance. So the ONLY thing carried
across the queue is the execution id, and the number, the direction and the tenant are
read back from the engine and from our own routing table.

**A tool call cannot be trusted to be the only one.** The model may invoke it twice, the
engine may retry it, and the post-call transcript pass will see the same request again
minutes later. All three converge on `record_call_optout`, whose dedupe is what makes
that safe (see its docstring); the ARQ job id is keyed on the execution so the common
case does not even reach the database twice.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from arq import Retry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.optout import (
    DETECTED_IN_CALL,
    OptOutSignal,
    record_call_optout,
)
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine

# The ingest job's retry ladder, its transience verdict and its tenant resolution, used
# rather than restated. They are private to `pipeline` by convention, not by intent: this
# module asks the identical three questions of the identical engine, and a second copy of
# "is another attempt capable of a different outcome" is where the two would drift.
from apps.workers.pipeline import _is_transient, _resolve_agent, _retry_after

log = get_logger(__name__)

OPTOUT_JOB = "record_in_call_optout"

# The tool call's own evidence rule id. It is not a phrase match — the ENGINE's model
# decided this was an opt-out — and the ledger has to say so, because "a model judged it"
# and "these words were said" are different strengths of evidence to whoever defends the
# suppression later.
TOOL_RULE = "engine_tool_call"

# How much of the engine's `reason` string is kept. It is model-generated text about what
# the caller said, so it is evidence — and it is also unauthenticated free text on an
# unsigned endpoint, so it is bounded before it is stored.
_REASON_CHARS = 80


def tool_signal(*, reason: str | None, language: str | None) -> OptOutSignal:
    """The in-call path's `OptOutSignal`. No turn index — see the field's comment."""
    return OptOutSignal(
        rule=TOOL_RULE,
        language=(language or "unknown")[:8],
        turn_idx=None,
        matched=(reason or "")[:_REASON_CHARS],
    )


async def record_in_call_optout(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Suppress the number of the call currently in progress.

    Returns a short outcome string (arq stores it), which is what makes "the tool fired
    and nothing happened" answerable without a transcript.
    """
    engine_name = str(payload.get("engine") or "fake")
    execution_id = str(payload["execution_id"])
    attempt = int(ctx.get("job_try", 1))

    engine = get_engine()
    try:
        snapshot = await engine.get_execution(execution_id)
    except Exception as exc:
        if _is_transient(exc) and attempt < WORKER_MAX_TRIES:
            raise Retry(defer=_retry_after(attempt)) from exc
        # Loudly, and then let it fail: the caller asked to be left alone and this layer
        # did not manage it. The post-call transcript pass is the braces — it runs off a
        # different trigger and a different read — but an operator should know that the
        # fast half missed, because the gap between them is the window a campaign can
        # still dial in.
        alert(
            "WORKER_TERMINAL",
            "in_call_optout_unresolved",
            detail=f"{type(exc).__name__} after {attempt} attempt(s)",
            execution_id=execution_id,
        )
        raise

    async with untenanted_session() as session:
        resolved = await _resolve_agent(session, engine_name, snapshot.engine_agent_ref)
    if resolved is None:
        alert(
            "WORKER_TERMINAL",
            "in_call_optout_agent_unmapped",
            detail=f"engine={engine_name}",
            execution_id=execution_id,
        )
        return "unmapped"
    tenant_id, _agent_id = resolved

    subject = snapshot.from_e164 if snapshot.direction == "inbound" else snapshot.to_e164
    if not subject:
        alert(
            "WORKER_TERMINAL",
            "in_call_optout_unattributable",
            detail=f"direction={snapshot.direction}",
            execution_id=execution_id,
        )
        return "unattributable"

    signal = tool_signal(reason=payload.get("reason"), language=payload.get("language"))
    async with tenant_session(tenant_id) as session:
        # The call row usually exists already — `ingest_engine_event` upserts it on the
        # first status webhook, which precedes any in-call tool call. When a webhook was
        # lost it does not, and the evidence row is written with a NULL call_id rather
        # than not at all: the suppression is the obligation, the call reference is
        # context. The consequence is honest and small — the post-call pass, which WILL
        # have a call id, writes a second evidence row for the same request rather than
        # deduping against this one. Two rows saying the same true thing beats one
        # missing suppression, and the ledger is append-only either way.
        call_id = await _call_id_for(session, tenant_id, snapshot.engine_call_id)
        record = await record_call_optout(
            session,
            tenant_id=tenant_id,
            raw_phone=subject,
            call_id=call_id,
            detected_by=DETECTED_IN_CALL,
            signal=signal,
        )
    return "recorded" if record.evidence_written else "already"


async def _call_id_for(session: AsyncSession, tenant_id: UUID, engine_call_id: str) -> UUID | None:
    row = (
        await session.execute(
            text("SELECT id FROM calls WHERE engine_call_id = :ecid AND tenant_id = :tid"),
            {"ecid": engine_call_id, "tid": tenant_id},
        )
    ).first()
    return UUID(str(row[0])) if row else None


__all__ = ["OPTOUT_JOB", "TOOL_RULE", "record_in_call_optout", "tool_signal"]
