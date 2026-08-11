"""Post-call pipeline (TRD §8, FLOWS §6). Idempotent, keyed by call.

    ingest_engine_event → (authenticated fetch is the TRUTH)
      persist call → recording copy → transcript + redaction → extraction →
      lead upsert → metering → hot-lead notification

Three properties this file exists to guarantee:

1. **The webhook is a hint, the fetch is the truth** (D-31). Every job re-reads the
   execution from the engine rather than trusting the payload that woke it. That is
   what makes a duplicate webhook, a poller rediscovery and a manual replay all
   converge on the same result.
2. **`completed` is the trigger, not `disconnected`.** Cost, recording and transcript
   are null until then (TRD §5), so a pipeline that fired on disconnect would meter
   zeros and store an empty transcript. `snapshot.billable_ready` is that gate.
3. **Every step is re-runnable.** Upserts, not inserts; CAS on status transitions;
   `usage_events` written once per (call, unit) because the ledger is append-only and
   a double-run would double-bill (hard rule 4 + 7).

SLO: lead visible in the client dashboard under 2 minutes after hangup — measured with
`record_pipeline_lag`, not assumed.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from calevate_shared.engine import ExecutionSnapshot
from calevate_shared.extraction import ExtractionSchemaSpec
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.service import charge_for_call, plan_tier_of
from apps.api.core.alerting import alert, record_pipeline_lag, record_reconciliation_repair
from apps.api.core.logging import get_logger
from apps.api.core.queue import enqueue, job_id_for
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.reliability.service import enqueue_outbox, mark_inbox_failed, mark_inbox_processed
from apps.workers.extraction import extract_call
from apps.workers.redaction import redact
from apps.workers.storage import StorageUnavailableError, copy_recording

log = get_logger(__name__)

POSTCALL_JOB = "run_post_call_pipeline"
INGEST_JOB = "ingest_engine_event"

# Hot-lead rule (FLOWS §6): these reach the owner within 2 minutes.
HOT_LEAD_STATUSES = frozenset({"hot"})
HOT_LEAD_FIELD_TRIGGERS: dict[str, frozenset[str]] = {
    "urgency": frozenset({"emergency", "urgent"}),
    "intent": frozenset({"buy", "book"}),
}


# --- tenant resolution --------------------------------------------------------


async def _resolve_agent(
    session: AsyncSession, engine: str, engine_agent_ref: str | None
) -> tuple[UUID, UUID] | None:
    """engine_agent_ref → (tenant_id, agent_id). The ONLY bridge from their id space to
    ours; an adapter must never guess a tenant (hard rule 1).

    Reads `engine_agent_routes`, not `agents`: at this point there is no session and no
    tenant, so the lookup is inherently cross-tenant — and `agents` is FORCE-RLS'd and
    stays that way. The routing table exists precisely so this resolution never needs
    an RLS exemption.
    """
    if not engine_agent_ref:
        return None
    row = (
        await session.execute(
            text(
                "SELECT tenant_id, agent_id FROM engine_agent_routes "
                "WHERE engine_agent_ref = :ref AND engine = :engine AND active"
            ),
            {"ref": engine_agent_ref, "engine": engine},
        )
    ).first()
    return (row[0], row[1]) if row else None


# --- job 1: ingest ------------------------------------------------------------


async def ingest_engine_event(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Enqueued by the voice-runtime receiver and by the reconciliation poller.

    Does the minimum that must happen synchronously with the event: fetch the truth,
    resolve the tenant, upsert the call row so the dashboard's live tile is right, and
    hand off to the heavy pipeline only once the engine says the call is complete.
    """
    engine_name = str(payload.get("engine") or "fake")
    execution_id = str(payload["execution_id"])
    inbox_row_id = payload.get("inbox_row_id")

    engine = get_engine()
    try:
        snapshot = await engine.get_execution(execution_id)
    except Exception as exc:
        if inbox_row_id:
            async with untenanted_session() as session:
                await mark_inbox_failed(
                    session, row_id=UUID(str(inbox_row_id)), error=type(exc).__name__
                )
        raise

    # The snapshot's ref wins over the webhook's: the fetch is the truth (D-31), and
    # the poller path has no webhook payload at all.
    agent_ref = snapshot.engine_agent_ref or payload.get("engine_agent_ref")
    async with untenanted_session() as session:
        resolved = await _resolve_agent(session, engine_name, agent_ref)
    if resolved is None:
        # An event for an agent we do not know: never invent a tenant, never drop it
        # silently. This is how a mis-provisioned agent gets noticed on day one.
        alert(
            "WORKER_TERMINAL",
            "engine_agent_unmapped",
            detail=f"engine={engine_name}",
            execution_id=execution_id,
        )
        if inbox_row_id:
            async with untenanted_session() as session:
                await mark_inbox_failed(
                    session, row_id=UUID(str(inbox_row_id)), error="agent ref not mapped"
                )
        return "unmapped"

    tenant_id, agent_id = resolved
    call_id = await _upsert_call(tenant_id, agent_id, snapshot)

    if inbox_row_id:
        async with untenanted_session() as session:
            await mark_inbox_processed(session, row_id=UUID(str(inbox_row_id)))

    if snapshot.billable_ready:
        await enqueue(
            POSTCALL_JOB,
            {
                "tenant_id": str(tenant_id),
                "call_id": str(call_id),
                "engine": engine_name,
                "execution_id": execution_id,
            },
            job_id=job_id_for(POSTCALL_JOB, str(call_id)),
        )
        return "pipeline_enqueued"
    return f"awaiting_completion:{snapshot.raw_status}"


async def _upsert_call(tenant_id: UUID, agent_id: UUID, snapshot: ExecutionSnapshot) -> UUID:
    """Idempotent by `engine_call_id`. Status only ever moves forward: a late `ringing`
    webhook arriving after `completed` must not un-complete a finished call."""
    direction = snapshot.direction
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "from_e164, to_e164, status, started_at, ended_at, duration_s, "
                    "created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, :dir, :from_e, "
                    ":to_e, :status, :started, :ended, :dur, now(), now()) "
                    "ON CONFLICT (engine_call_id) DO UPDATE SET "
                    "  status = EXCLUDED.status, "
                    "  started_at = COALESCE(calls.started_at, EXCLUDED.started_at), "
                    "  ended_at = COALESCE(EXCLUDED.ended_at, calls.ended_at), "
                    "  duration_s = COALESCE(EXCLUDED.duration_s, calls.duration_s), "
                    "  updated_at = now() "
                    "WHERE calls.status NOT IN ('completed', 'failed', 'no_answer', 'busy', "
                    "'voicemail') OR EXCLUDED.status = 'completed' "
                    "RETURNING id"
                ),
                {
                    "id": call_id,
                    "tid": tenant_id,
                    "aid": agent_id,
                    "ecid": snapshot.engine_call_id,
                    "dir": direction,
                    "from_e": snapshot.from_e164,
                    "to_e": snapshot.to_e164,
                    "status": snapshot.status,
                    "started": snapshot.started_at,
                    "ended": snapshot.ended_at,
                    "dur": snapshot.duration_s,
                },
            )
        ).first()
        if row is not None:
            return UUID(str(row[0]))
        # The conflict's WHERE clause refused the update (terminal row already there):
        # read the existing id rather than treating it as an error.
        existing = (
            await session.execute(
                text("SELECT id FROM calls WHERE engine_call_id = :ecid"),
                {"ecid": snapshot.engine_call_id},
            )
        ).first()
    if existing is None:  # pragma: no cover — only reachable on a concurrent delete
        raise RuntimeError("call row vanished during upsert")
    return UUID(str(existing[0]))


# --- job 2: the pipeline ------------------------------------------------------


async def run_post_call_pipeline(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    tenant_id = UUID(str(payload["tenant_id"]))
    call_id = UUID(str(payload["call_id"]))
    execution_id = str(payload["execution_id"])
    started = time.perf_counter()

    snapshot = await get_engine().get_execution(execution_id)

    # STEP 1 — recording first, always. Everything else can be recomputed.
    if snapshot.recording_url:
        try:
            key = await copy_recording(
                source_url=snapshot.recording_url, tenant_id=tenant_id, call_id=call_id
            )
            async with tenant_session(tenant_id) as session:
                await session.execute(
                    text(
                        "UPDATE calls SET recording_url = :key, updated_at = now() "
                        "WHERE id = :id AND tenant_id = :tid"
                    ),
                    {"key": key, "id": call_id, "tid": tenant_id},
                )
        except StorageUnavailableError as exc:
            # Re-raise so ARQ retries: a lost recording is unrecoverable and TRAI's
            # 90-day floor is our obligation.
            alert("WORKER_DELIVERY", "recording_copy_failed", detail=str(exc), call_id=str(call_id))
            raise

    # STEP 2 — transcript + redaction. `text_redacted` is the default view (hard rule 5).
    transcript_text = await _persist_transcript(tenant_id, call_id, snapshot)

    # STEP 3 — extraction against the agent's schema.
    spec, schema_version, agent_id, direction = await _load_call_context(tenant_id, call_id)
    needs_extraction = bool(spec.fields or transcript_text)
    extraction = await extract_call(spec, transcript_text) if needs_extraction else None

    if extraction is not None:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "INSERT INTO call_extractions (id, tenant_id, call_id, schema_version, data, "
                    "model, valid, errors, created_at, updated_at) VALUES (:id, :tid, :cid, :ver, "
                    "CAST(:data AS jsonb), :model, :valid, CAST(:errors AS jsonb), now(), now())"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "cid": call_id,
                    "ver": schema_version,
                    "data": _json(extraction.data),
                    "model": None,
                    "valid": extraction.valid,
                    "errors": _json(extraction.errors) if extraction.errors else None,
                },
            )
            await session.execute(
                text(
                    "UPDATE calls SET summary = :summary, sentiment = :sentiment, "
                    "outcome_tag = :outcome, updated_at = now() "
                    "WHERE id = :id AND tenant_id = :tid"
                ),
                {
                    "summary": extraction.summary or None,
                    "sentiment": extraction.sentiment,
                    "outcome": extraction.outcome_tag,
                    "id": call_id,
                    "tid": tenant_id,
                },
            )

    # STEP 4 — lead upsert (+ repeat-caller flag on phone match).
    lead_id = await _upsert_lead(
        tenant_id,
        agent_id,
        call_id,
        snapshot,
        direction=direction,
        data=extraction.data if extraction else {},
        schema_version=schema_version,
    )

    # STEP 5 — metering. Append-only, written once per (call, unit).
    if snapshot.cost is not None:
        await _meter(tenant_id, call_id, snapshot)

    # STEP 6 — notifications, through the OUTBOX so a crash cannot lose them.
    if lead_id is not None and extraction is not None:
        await _maybe_notify_hot_lead(tenant_id, lead_id, call_id, extraction.data)

    lag = time.perf_counter() - started
    record_pipeline_lag(lag, stage="post_call")
    log.info("pipeline_complete", extra={"call_id": str(call_id), "duration_s": round(lag, 2)})
    return "ok"


def _json(value: Any) -> str:
    import json

    return json.dumps(value, default=str)


async def _persist_transcript(tenant_id: UUID, call_id: UUID, snapshot: ExecutionSnapshot) -> str:
    """Store raw + redacted turns. Idempotent on (call_id, idx) so a re-run rewrites
    rather than duplicates."""
    if not snapshot.transcript:
        return ""
    lines: list[str] = []
    async with tenant_session(tenant_id) as session:
        for turn in snapshot.transcript:
            redacted = redact(turn.text)
            lines.append(f"{turn.speaker}: {turn.text}")
            await session.execute(
                text(
                    "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                    "text_redacted, lang, start_ms, end_ms, created_at, updated_at) VALUES "
                    "(:id, :tid, :cid, :idx, :speaker, :text, :redacted, :lang, :start, :end, "
                    "now(), now()) ON CONFLICT (call_id, idx) DO UPDATE SET "
                    "text = EXCLUDED.text, text_redacted = EXCLUDED.text_redacted, "
                    "updated_at = now()"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "cid": call_id,
                    "idx": turn.idx,
                    "speaker": turn.speaker,
                    "text": turn.text,
                    "redacted": redacted.text,
                    "lang": turn.lang,
                    "start": turn.start_ms,
                    "end": turn.end_ms,
                },
            )
    return "\n".join(lines)


async def _load_call_context(
    tenant_id: UUID, call_id: UUID
) -> tuple[ExtractionSchemaSpec, int, UUID, str]:
    """The call's agent, its direction, and the schema ACTIVE AT EXTRACTION TIME.

    Direction comes from the stored call row rather than being re-derived: it decides
    which number belongs to the lead, and getting it wrong would file an outbound call
    under our own caller id.

    Leads render by the schema version stored on the row, so a later schema edit never
    rewrites an old lead (TRD §7).
    """
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT c.agent_id, c.direction, es.version, es.fields FROM calls c "
                    "JOIN agents a ON a.id = c.agent_id "
                    "LEFT JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
                    "WHERE c.id = :cid AND c.tenant_id = :tid"
                ),
                {"cid": call_id, "tid": tenant_id},
            )
        ).first()
    if row is None:
        raise RuntimeError(f"call {call_id} not found for schema load")
    agent_id, direction, version, fields = row[0], str(row[1]), row[2], row[3]
    if not fields:
        empty = ExtractionSchemaSpec(version=version or 1, fields=[])
        return empty, version or 1, agent_id, direction
    spec = ExtractionSchemaSpec.model_validate({"version": version or 1, "fields": fields})
    return spec, spec.version, agent_id, direction


async def _upsert_lead(
    tenant_id: UUID,
    agent_id: UUID,
    call_id: UUID,
    snapshot: ExecutionSnapshot,
    *,
    direction: str,
    data: dict[str, Any],
    schema_version: int,
) -> UUID | None:
    """One lead per (tenant, phone, agent). A second call from the same number updates
    the lead and flips `is_repeat_caller` — that flag is what makes the repeat-caller
    context injection (FLOWS §3) possible later.

    THE LEAD'S PHONE IS THE OTHER PARTY: the caller on inbound, the recipient on
    outbound. Keying on the wrong end would file every outbound call under our own
    number and collapse a tenant's whole CRM into one lead.
    """
    caller = snapshot.from_e164 if direction == "inbound" else snapshot.to_e164
    if not caller:
        return None
    lead_id = uuid7()
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, "
                    "status, data, schema_version, first_call_id, last_call_id, call_count, "
                    "is_repeat_caller, created_at, updated_at) VALUES (:id, :tid, :aid, :phone, "
                    ":name, :source, 'new', CAST(:data AS jsonb), :ver, :cid, :cid, 1, false, "
                    "now(), now()) "
                    "ON CONFLICT (tenant_id, phone_e164, agent_id) DO UPDATE SET "
                    "  data = leads.data || EXCLUDED.data, "
                    "  schema_version = EXCLUDED.schema_version, "
                    "  name = COALESCE(EXCLUDED.name, leads.name), "
                    "  last_call_id = EXCLUDED.last_call_id, "
                    "  call_count = leads.call_count + 1, "
                    "  is_repeat_caller = true, "
                    "  updated_at = now() "
                    "RETURNING id"
                ),
                {
                    "id": lead_id,
                    "tid": tenant_id,
                    "aid": agent_id,
                    "phone": caller,
                    "name": data.get("name") or data.get("caller_name"),
                    "source": "inbound_call" if direction == "inbound" else "campaign",
                    "data": _json(data),
                    "ver": schema_version,
                    "cid": call_id,
                },
            )
        ).first()
        resolved_id = UUID(str(row[0])) if row else None
        if resolved_id is not None:
            await session.execute(
                text(
                    "UPDATE calls SET lead_id = :lid, updated_at = now() "
                    "WHERE id = :cid AND tenant_id = :tid"
                ),
                {"lid": resolved_id, "cid": call_id, "tid": tenant_id},
            )
            await session.execute(
                text(
                    "INSERT INTO lead_events (id, tenant_id, lead_id, type, payload, actor, "
                    "created_at, updated_at) VALUES (:id, :tid, :lid, 'call', "
                    "CAST(:payload AS jsonb), 'system', now(), now())"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "lid": resolved_id,
                    "payload": _json({"call_id": str(call_id), "status": snapshot.status}),
                },
            )
    return resolved_id


async def _meter(tenant_id: UUID, call_id: UUID, snapshot: ExecutionSnapshot) -> None:
    """Write the cost ledger. Append-only (hard rule 4), so the guard against a
    double-run is a pre-check, not an upsert: a compensating entry is the only fix
    after the fact."""
    cost = snapshot.cost
    if cost is None:
        return
    async with tenant_session(tenant_id) as session:
        tier = await plan_tier_of(session, tenant_id)
        already = (
            await session.execute(
                text(
                    "SELECT 1 FROM usage_events WHERE call_id = :cid AND tenant_id = :tid LIMIT 1"
                ),
                {"cid": call_id, "tid": tenant_id},
            )
        ).first()
        if already:
            return

        duration_s = Decimal(snapshot.duration_s or 0)
        meta = _json(
            {
                "engine": snapshot.engine,
                "engine_call_id": snapshot.engine_call_id,
                "source_currency": cost.source_currency,
                "source_amount": str(cost.source_amount) if cost.source_amount else None,
                # The fx rate used AT CAPTURE — without it the row cannot be re-derived.
                "fx_rate": str(cost.fx_rate) if cost.fx_rate else None,
            }
        )
        rows: list[tuple[str, Decimal, Decimal | None]] = [
            ("telephony_s", duration_s, cost.network_inr),
            ("platform_min", duration_s / Decimal(60), cost.platform_inr),
            ("stt_s", duration_s, cost.stt_inr),
        ]
        if cost.tts_inr is not None:
            rows.append(("tts_chars", Decimal(0), cost.tts_inr))
        if cost.llm_inr is not None:
            rows.append(("llm_tok_out", Decimal(0), cost.llm_inr))

        for unit_type, qty, unit_cost in rows:
            await session.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                    "unit_cost_paid, occurred_at, meta, created_at) VALUES (:id, :tid, :cid, "
                    ":unit, :qty, :cost, :at, CAST(:meta AS jsonb), now())"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "cid": call_id,
                    "unit": unit_type,
                    "qty": qty,
                    "cost": unit_cost,
                    "at": snapshot.ended_at or datetime.now(UTC),
                    "meta": meta,
                },
            )

        # Prepaid credits move with the metering, keyed by call_id so a pipeline
        # re-run cannot double-charge (D-39). Managed tenants are invoiced against a
        # retainer instead, which `charge_for_call` reads from plan_tier.
        if tier in ("self_serve", "trial"):
            await charge_for_call(
                session, tenant_id=tenant_id, call_id=call_id, amount_inr=cost.total_inr
            )

        # spend_state is the pre-dispatch gate (TRD §9): caps are enforced BEFORE a
        # call is placed, so this counter has to move with the ledger.
        month = (snapshot.ended_at or datetime.now(UTC)).strftime("%Y-%m")
        await session.execute(
            text(
                "INSERT INTO spend_state (tenant_id, month, minutes_used, spend_used, capped, "
                "created_at, updated_at) VALUES (:tid, :month, :minutes, :spend, false, now(), "
                "now()) ON CONFLICT (tenant_id) DO UPDATE SET "
                "  minutes_used = CASE WHEN spend_state.month = EXCLUDED.month "
                "    THEN spend_state.minutes_used + EXCLUDED.minutes_used "
                "    ELSE EXCLUDED.minutes_used END, "
                "  spend_used = CASE WHEN spend_state.month = EXCLUDED.month "
                "    THEN spend_state.spend_used + EXCLUDED.spend_used "
                "    ELSE EXCLUDED.spend_used END, "
                "  month = EXCLUDED.month, updated_at = now()"
            ),
            {
                "tid": tenant_id,
                "month": month,
                "minutes": duration_s / Decimal(60),
                "spend": cost.total_inr,
            },
        )


async def _maybe_notify_hot_lead(
    tenant_id: UUID, lead_id: UUID, call_id: UUID, data: dict[str, Any]
) -> None:
    """Hot-lead rules key off the FIXED status enum and the schema's own fields (D-21).
    The notification goes through the outbox so a worker crash cannot lose it."""
    triggered = [
        key
        for key, values in HOT_LEAD_FIELD_TRIGGERS.items()
        if str(data.get(key, "")).lower() in values
    ]
    if not triggered:
        return
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE leads SET status = 'hot', updated_at = now() "
                "WHERE id = :lid AND tenant_id = :tid AND status = 'new'"
            ),
            {"lid": lead_id, "tid": tenant_id},
        )
        await enqueue_outbox(
            session,
            queue="notifications",
            job="notify_hot_lead",
            payload={
                "tenant_id": str(tenant_id),
                "lead_id": str(lead_id),
                "call_id": str(call_id),
                "triggers": triggered,
            },
        )


# --- job 3: reconciliation ----------------------------------------------------


async def reconcile_executions(ctx: dict[str, Any]) -> str:
    """The guarantee of record (D-31), not a safety net.

    Bolna delivers webhooks at most once with no retries, so an event lost to a deploy,
    a network blip or a 500 is lost forever at the webhook layer. This runs every 10
    minutes, lists executions since the last window, and re-drives anything we have no
    completed call row for. Every repair it makes is a webhook we never received —
    which is why it emits a metric rather than passing quietly.
    """
    engine = get_engine()
    since = datetime.now(UTC) - timedelta(minutes=30)
    try:
        snapshots = await engine.list_executions(since=since)
    except Exception as exc:  # engine down: the next tick retries
        alert("WORKER_DELIVERY", "reconciliation_fetch_failed", detail=type(exc).__name__)
        return "engine_unavailable"

    repaired = 0
    for snapshot in snapshots:
        if not snapshot.billable_ready:
            continue
        async with untenanted_session() as session:
            known = (
                await session.execute(
                    text(
                        "SELECT 1 FROM calls WHERE engine_call_id = :ecid "
                        "AND status = 'completed' LIMIT 1"
                    ),
                    {"ecid": snapshot.engine_call_id},
                )
            ).first()
        if known:
            continue
        await enqueue(
            INGEST_JOB,
            {
                "engine": engine.name,
                "execution_id": snapshot.engine_call_id,
                "raw_status": snapshot.raw_status,
                "engine_agent_ref": None,
                "source": "reconciliation",
            },
            job_id=job_id_for(INGEST_JOB, engine.name, snapshot.engine_call_id, "reconcile"),
        )
        record_reconciliation_repair(kind="missing_call")
        repaired += 1

    if repaired:
        log.warning("reconciliation_repaired", extra={"count": repaired})
    return f"repaired={repaired}"


__all__ = [
    "INGEST_JOB",
    "POSTCALL_JOB",
    "ingest_engine_event",
    "reconcile_executions",
    "run_post_call_pipeline",
]
