"""Append the audit row for one in-call/after-call ACTION invocation.

The execution layer (`apps/api/actions/execution.py`) enqueues this so the latency-critical
tool path writes no DB row of its own (hard rule 3). Here, off the caller's audio path, the
row is written to the append-only, tamper-evident `audit_log` (hard rule 4).

HARD RULE 6: the payload carries ids, the kind/provider and a short outcome code — never a
number, a message body or an external response. There is nothing here to redact because
nothing sensitive was queued.

**AND IT HAS A RETRY LADDER, WHICH IT DID NOT.** This job wrote one row and raised on any
failure, and a plain raise is TERMINAL under arq 0.28: `retry_jobs` honours `arq.Retry`,
`RetryJob` and `CancelledError` and nothing else, so `WorkerSettings.max_tries` never
reached this function. One lock timeout, one pool exhaustion, one connection recycled
underneath it, and the audit row for a tool the caller actually ran was gone — with the
tool itself already reported as succeeded, no outbox row behind it (the executor enqueues
directly, off the latency-critical path), and nothing anywhere that could notice. That is
the shape `settings.py` describes as failing in silence: a job that makes neither of the
two gestures — `raise Retry` while the budget lasts, `alert()` on the last attempt —
has no dead letter of any kind, because arq's own terminal warning only fires for a ladder
that was actually walked.

`audit_log` is append-only (hard rule 4) and `write_audit` inserts one row per call, so a
retry that lands after a partially-successful attempt is not a risk here: the transaction
either committed the row or it did not.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from arq import Retry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.actions.models import INVOCATION_SOURCES
from apps.api.compliance.audit import write_audit
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session

log = get_logger(__name__)

ACTION_AUDIT_JOB = "record_action_invocation"

# The audit action name a client-facing "action history" screen and any drift sweep filter
# on. Named once, here with the enqueuer's constant, so the two cannot drift.
ACTION_AUDIT_ACTION = "action_tool.invoked"

#: How long the per-action call log keeps a run (D-700).
INVOCATION_LOG_DAYS = 90

#: Seconds to wait before each retry, indexed by the attempt that just failed. One entry
#: shorter than the budget, because the last attempt has nothing after it — the shape
#: `notifications.RETRY_BACKOFF_S` and `outbound_webhooks.RETRY_BACKOFF_S` already use.
#: Short, because what this waits out is a database blip and nothing downstream is
#: blocked on the row: a longer ladder would only widen the window in which a deploy
#: takes the attempt with it.
RETRY_BACKOFF_S: tuple[float, ...] = (5.0, 20.0)


def _retry_after(attempt: int) -> float:
    index = min(attempt, len(RETRY_BACKOFF_S)) - 1
    return RETRY_BACKOFF_S[max(index, 0)]


async def _record_invocation(
    session: AsyncSession, *, tenant_id: UUID, payload: dict[str, Any]
) -> None:
    """The per-action call log row (D-700), in the same transaction as the audit row, so a
    retry that lands after a failed attempt writes both or neither. A source this table
    does not know (an older enqueuer) is logged as `in_call`, the only source there was."""
    source = str(payload.get("source") or "in_call")
    duration = payload.get("duration_ms")
    await session.execute(
        text(
            "INSERT INTO action_invocations (id, tenant_id, agent_id, tool_id, source, status, "
            "duration_ms, call_ref, created_at, updated_at) SELECT :id, :tid, t.agent_id, t.id, "
            ":src, :st, :ms, :ref, now(), now() FROM action_tools t WHERE t.id = :tool"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "tool": UUID(str(payload["tool_id"])),
            "src": source if source in INVOCATION_SOURCES else "in_call",
            "st": (str(payload.get("status") or "unknown"))[:64],
            "ms": int(duration) if isinstance(duration, int | float) else None,
            "ref": (str(payload.get("call_ref") or "") or None),
        },
    )
    # The log is a screen of recent runs, not a record (`audit_log` is the record): rows
    # past `INVOCATION_LOG_DAYS` for this action go as each new one arrives, on the
    # (tool_id, created_at) index, so no sweep is needed for a table holding no personal data.
    await session.execute(
        text(
            "DELETE FROM action_invocations WHERE tool_id = :tool "
            "AND created_at < now() - make_interval(days => :days)"
        ),
        {"tool": UUID(str(payload["tool_id"])), "days": INVOCATION_LOG_DAYS},
    )


async def record_action_invocation(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Write one audit row for an action invocation. Idempotency is not required — an
    over-count of a benign audit row is harmless, and the queue collapses obvious retries —
    so this stays a plain append rather than carrying a dedupe key.

    The ladder below is what makes `WorkerSettings.max_tries` reach this job at all; the
    module docstring says why a plain raise was the whole failure."""
    tenant_id = UUID(str(payload["tenant_id"]))
    tool_id = str(payload["tool_id"])
    attempt = int(ctx.get("job_try", 1) or 1)
    try:
        async with tenant_session(tenant_id) as session:
            await write_audit(
                session,
                action=ACTION_AUDIT_ACTION,
                actor=None,  # engine-initiated → actor_type "system"
                tenant_id=tenant_id,
                object_type="action_tool",
                object_id=tool_id,
                summary={
                    "agent_id": str(payload.get("agent_id") or ""),
                    "kind": str(payload.get("kind") or ""),
                    "provider": str(payload.get("provider") or ""),
                    "status": str(payload.get("status") or ""),
                    "source": str(payload.get("source") or ""),
                },
            )
            await _record_invocation(session, tenant_id=tenant_id, payload=payload)
    except Exception as exc:
        if attempt < WORKER_MAX_TRIES:
            # The one exception arq treats as "not finished" — see the module docstring.
            raise Retry(defer=_retry_after(attempt)) from exc
        # The ladder is spent and the invocation is now permanently unlogged. Ids and an
        # exception TYPE only: a psycopg error string can quote the row that broke it
        # (hard rule 6), and an alert body travels further than a log line.
        alert(
            "WORKER_TERMINAL",
            "action_audit_unrecorded",
            detail=(
                f"an action invocation was executed and its audit row could not be "
                f"written after {attempt} attempt(s) ({type(exc).__name__}); the "
                "invocation is missing from the audit trail and cannot be reconstructed"
            ),
            tenant_id=str(tenant_id),
            tool_id=tool_id,
        )
        raise
    log.info(
        "action_invocation_audited",
        extra={"tenant_id": str(tenant_id), "tool_id": tool_id, "status": payload.get("status")},
    )
    return str(payload.get("status") or "recorded")


__all__ = [
    "ACTION_AUDIT_ACTION",
    "ACTION_AUDIT_JOB",
    "RETRY_BACKOFF_S",
    "record_action_invocation",
]
