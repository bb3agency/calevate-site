"""Carrier status/hangup callbacks and the carrier's CDR: the carrier's half of a call.

    voice-runtime claims the callback → ingest_carrier_event
      resolve tenant + call → advance status (forward only) → [hangup] read_carrier_cdr
    read_carrier_cdr → fetch the CDR → record OUR cost for the carrier minute
    reconcile_carrier_cdrs (cron) → re-enqueue the CDR read for metered calls without one

WHAT THE CDR CHANGES ON THE LEDGER, AND WHAT IT DOES NOT. The post-call meter already wrote
the call's one `telephony_s` row at settlement, from the worker's measured connected time,
with `unit_cost_paid` NULL because the carrier had not priced it (D-648, `pipeline._meter`).
The client's minutes are billed off that row's `qty`. The CDR is the carrier's own charge for
the call, so it lands as ONE compensating row in the shape every correction on this
append-only ledger takes (`billing/cost_unit.py`): `unit_type = 'other'`, `qty = 1`,
`unit_cost_paid` = the carrier's INR charge, stamped at the call's own `occurred_at`. That
moves OUR cost and nothing a client is billed — no reader prices client minutes off an
`other` row — so a CDR can never double-bill. The carrier's `billsec` is recorded beside the
worker's seconds in `meta` (`billed_seconds_delta`), so a disagreement is a query rather than
a guess; making `billsec` the client's billable quantity would need a client-facing
adjustment entry and is a decision for the billing owner, not something this reader assumes.

The row is written only once the client-side `telephony_s` row exists. `_meter` decides
"already metered" by the presence of usage rows, and on a call without settlement legs ANY
row counts — a cost row landing first would make the meter skip the client's charge.

ONE CDR, ONE ROW. Keyed on `meta.cdr_ref` (`cdr:<carrier>:<carrier call id>`), checked under
`pipeline.lock_call_writes` in the same transaction as the insert, so overlapping reads of
the same CDR (the hangup path and the sweep) write one row between them.

TENANCY (hard rule 1). The tenant comes from the agent ref through `engine_agent_routes`
(`pipeline._resolve_agent`), never from the payload; every call read runs under that
tenant's RLS session, and the call found must belong to the agent the ref names.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal, NoReturn, cast, get_args
from uuid import UUID

from arq import Retry
from calevate_shared.carrier import CARRIER_EVENT_JOB, CarrierName, is_carrier
from calevate_shared.events import TERMINAL_STATUSES, CallStatus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.rates import MONEY_Q, ROUNDING
from apps.api.billing.service import LEDGER_RUNG_KEY
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES, enqueue, job_id_for
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.carrier import CarrierCallEvent, CarrierCdr, get_carrier
from apps.api.reliability.service import mark_inbox_failed, mark_inbox_processed
from apps.workers.pipeline import (
    _is_transient,
    _resolve_agent,
    _retry_after,
    _withdrawn_route_tenant,
    callable_tenants,
    lock_call_writes,
)

log = get_logger(__name__)

#: The CDR read, keyed per carrier call so the hangup path and the sweep collapse into one.
CDR_JOB: Final = "read_carrier_cdr"

#: `meta.kind` on the cost row a CDR writes; the sweep's "already read" test keys on it.
CARRIER_CDR_META_KIND: Final = "carrier_cdr"

#: The first CDR read waits this long after the hangup: the record exists only after the
#: call ends (`vobiz-findings/mirror/pages/cdr/get-cdr.md:25`), and the post-call meter it
#: must follow usually lands inside two minutes.
CDR_FIRST_READ_DELAY_S: Final = 60.0

#: Backoff between attempts, one entry per retry `WORKER_MAX_TRIES` leaves.
CALL_RESOLVE_BACKOFF_S: Final[tuple[float, ...]] = (20.0, 90.0)
CDR_RETRY_BACKOFF_S: Final[tuple[float, ...]] = (120.0, 300.0)

#: The sweep's window. AFTER leaves the hangup path its own retries first; HORIZON bounds how
#: far back a CDR is chased (a carrier that has not written one in a day is an incident the
#: `carrier_cdr_missing` alarm already raised, not a backlog).
CDR_SWEEP_AFTER: Final = timedelta(minutes=10)
CDR_SWEEP_HORIZON: Final = timedelta(hours=24)
CDR_SWEEP_PER_TENANT: Final = 50
CDR_SWEEP_BUDGET: Final = 500
CDR_SWEEP_MINUTES: Final = frozenset({4, 14, 24, 34, 44, 54})

#: Forward order of the live statuses; every terminal status ranks after all of them, and a
#: terminal status is never replaced — the worker's record of how the conversation ended
#: stands, and the carrier is the authority on the minute (the CDR), not on the outcome.
_LIVE_RANK: Final[dict[str, int]] = {"queued": 0, "ringing": 1, "in_progress": 2}
_TERMINAL_RANK: Final = len(_LIVE_RANK)

CdrVerdict = Literal["recorded", "recorded_unpriced", "already_recorded", "awaiting_metering"]


def _rank(status: str) -> int:
    return _TERMINAL_RANK if status in TERMINAL_STATUSES else _LIVE_RANK[status]


def statuses_behind(status: CallStatus) -> list[str]:
    """The statuses a call may move FROM to reach `status`: strictly earlier ones only."""
    target = _rank(status)
    return sorted(s for s in get_args(CallStatus) if _rank(s) < target)


def _ladder(backoff: tuple[float, ...], attempt: int) -> float:
    return backoff[max(0, min(attempt, len(backoff)) - 1)]


def cdr_ref(carrier: str, carrier_call_id: str) -> str:
    """The cost row's idempotency key: one per CDR."""
    return f"cdr:{carrier}:{carrier_call_id}"


def carrier_cost_inr(cdr: CarrierCdr) -> Decimal | None:
    """The carrier's charge as `unit_cost_paid`, or None when it may not be one (hard rule 7).

    Only a charge the carrier stated in INR qualifies; any other currency, or none, is NULL
    rather than a conversion we would be inventing. Quantized once, at the ledger's own
    scale, with the rounding named — the reported figure is kept verbatim in `meta`.
    """
    if cdr.total_cost_inr is None or (cdr.currency or "").upper() != "INR":
        return None
    if cdr.total_cost_inr < 0:
        return None
    return cdr.total_cost_inr.quantize(MONEY_Q, rounding=ROUNDING)


async def _fail_inbox(inbox_row_id: Any, error: str) -> None:
    """Mark the claimed inbox row failed, which leaves its key re-claimable."""
    if inbox_row_id:
        async with untenanted_session() as session:
            await mark_inbox_failed(session, row_id=UUID(str(inbox_row_id)), error=error)


async def _close_inbox(inbox_row_id: Any) -> None:
    if inbox_row_id:
        async with untenanted_session() as session:
            await mark_inbox_processed(session, row_id=UUID(str(inbox_row_id)))


# --- job 1: the callback ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _EventTarget:
    carrier: CarrierName
    fields: dict[str, str]
    engine_agent_ref: str | None
    call_id: UUID | None
    inbox_row_id: Any


@dataclass(frozen=True, slots=True)
class _CallRow:
    id: UUID
    agent_id: UUID
    carrier_call_id: str | None


def _event_target(payload: dict[str, Any]) -> _EventTarget:
    """The job's inputs, or a PERMANENT failure (a malformed payload never improves)."""
    try:
        carrier = str(payload["carrier"])
        fields = payload["fields"]
        if not is_carrier(carrier) or not isinstance(fields, dict):
            raise ValueError("carrier or fields")
        raw_call = payload.get("call_id")
        ref = payload.get("engine_agent_ref")
        return _EventTarget(
            carrier=cast(CarrierName, carrier),
            fields={str(k): str(v) for k, v in fields.items()},
            engine_agent_ref=str(ref) if ref else None,
            call_id=UUID(str(raw_call)) if raw_call else None,
            inbox_row_id=payload.get("inbox_row_id"),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise ProblemError(
            kind="validation",
            code="carrier_event_payload_invalid",
            title="Unusable carrier-event job payload",
            detail="The carrier event job was enqueued without a usable carrier or fields.",
        ) from exc


async def ingest_carrier_event(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Enqueued by voice-runtime for every claimed carrier callback (`CARRIER_EVENT_JOB`).

    The failure policy wraps the whole job, as `pipeline.ingest_engine_event`'s does: arq
    0.28 retries only for `arq.Retry`, so anything else is decided here — transient faults
    take the ladder, permanent ones alert — and the inbox row is closed LAST, once every
    side effect this event owes has been written or queued.
    """
    attempt = int(ctx.get("job_try", 1))
    hint = str(payload.get("carrier_call_id") or "unknown")
    try:
        return await _ingest_stages(_event_target(payload), attempt)
    except Retry:
        raise
    except Exception as exc:
        await _abandon_event(
            inbox_row_id=payload.get("inbox_row_id"), exc=exc, attempt=attempt, carrier_call_id=hint
        )


async def _abandon_event(
    *, inbox_row_id: Any, exc: Exception, attempt: int, carrier_call_id: str
) -> NoReturn:
    await _fail_inbox(inbox_row_id, type(exc).__name__)
    if _is_transient(exc) and attempt < WORKER_MAX_TRIES:
        raise Retry(defer=_retry_after(attempt)) from exc
    alert(
        "WORKER_TERMINAL",
        "carrier_event_ingest_abandoned",
        detail=(
            f"{type(exc).__name__} after {attempt} attempt(s)"
            if _is_transient(exc)
            else f"{type(exc).__name__} is permanent, not retried"
        ),
        carrier_call_id=carrier_call_id,
    )
    raise exc


async def _ingest_stages(target: _EventTarget, attempt: int) -> str:
    event = get_carrier(target.carrier).parse_event(target.fields)
    if event is None:
        await _close_inbox(target.inbox_row_id)
        return "no_call_named"

    engine_name = get_settings().engine
    async with untenanted_session() as session:
        resolved = await _resolve_agent(session, engine_name, target.engine_agent_ref)
    if resolved is None:
        await _report_unmapped(engine_name, target, event)
        return "unmapped"
    tenant_id, agent_id = resolved

    moved = False
    async with tenant_session(tenant_id) as session:
        call = await _find_call(session, tenant_id, target.call_id, event.carrier_call_id)
        if call is not None and call.agent_id == agent_id:
            moved = await _advance_status(session, tenant_id, call.id, event.status)
            if target.call_id is not None:
                await _record_carrier_call_id(session, tenant_id, call, event.carrier_call_id)

    if call is None:
        return await _unresolved(target, event, tenant_id, attempt)
    if call.agent_id != agent_id:
        alert(
            "WORKER_TERMINAL",
            "carrier_event_call_mismatch",
            detail="the call this carrier event names belongs to a different agent than its route",
            tenant_id=str(tenant_id),
            call_id=str(call.id),
            carrier_call_id=event.carrier_call_id,
        )
        await _fail_inbox(target.inbox_row_id, "call belongs to another agent")
        return "call_mismatch"

    outcome = f"{event.kind}:{'advanced' if moved else 'unchanged'}"
    if event.kind == "hangup":
        await enqueue_cdr_read(
            carrier=target.carrier,
            carrier_call_id=call.carrier_call_id or event.carrier_call_id,
            tenant_id=tenant_id,
            call_id=call.id,
            defer_s=CDR_FIRST_READ_DELAY_S,
        )
        outcome += ":cdr_enqueued"

    await _close_inbox(target.inbox_row_id)
    return outcome


async def _report_unmapped(engine_name: str, target: _EventTarget, event: CarrierCallEvent) -> None:
    """An event for an agent no route names: never invent a tenant, never drop it silently.

    The same two codes, and the same distinction, as `pipeline._ingest_stages`.
    """
    async with untenanted_session() as session:
        withdrawn_for = await _withdrawn_route_tenant(session, engine_name, target.engine_agent_ref)
    if withdrawn_for is not None:
        alert(
            "WORKER_TERMINAL",
            "engine_agent_route_withdrawn",
            detail=(
                f"carrier={target.carrier}; this account's routing was withdrawn and its number "
                "is still live — release it with the carrier"
            ),
            tenant_id=str(withdrawn_for),
            carrier_call_id=event.carrier_call_id,
        )
    else:
        alert(
            "WORKER_TERMINAL",
            "engine_agent_unmapped",
            detail=f"engine={engine_name} carrier={target.carrier}",
            carrier_call_id=event.carrier_call_id,
        )
    await _fail_inbox(target.inbox_row_id, "agent ref not mapped")


async def _unresolved(
    target: _EventTarget, event: CarrierCallEvent, tenant_id: UUID, attempt: int
) -> str:
    """No call row yet. Inbound rows are written by the worker during the call, so a
    callback can outrun it: retry on a ladder, then park.

    Parked loudly when it costs something to lose: a hangup (the call's end, and the only
    trigger of its CDR read) or any event naming one of OUR outbound calls, whose row
    `dispatch_call` committed before dialling. An inbound ring or stream event with no row
    is a caller who hung up before the worker connected, and the hangup that follows it
    carries the alarm if one is owed.
    """
    await _fail_inbox(target.inbox_row_id, "call not resolved")
    if attempt < WORKER_MAX_TRIES:
        raise Retry(defer=_ladder(CALL_RESOLVE_BACKOFF_S, attempt))
    if event.kind == "hangup" or target.call_id is not None:
        alert(
            "WORKER_TERMINAL",
            "carrier_event_call_unresolved",
            detail=(
                f"carrier={target.carrier} event={event.kind}: no call row "
                f"{'with our call id' if target.call_id else 'carries this carrier call id'} "
                f"after {attempt} attempts; its status and CDR cost were not recorded"
            ),
            tenant_id=str(tenant_id),
            carrier_call_id=event.carrier_call_id,
        )
    else:
        log.info(
            "carrier_event_unresolved",
            extra={"carrier_call_id": event.carrier_call_id, "kind": event.kind},
        )
    return "unresolved"


async def _find_call(
    session: AsyncSession, tenant_id: UUID, call_id: UUID | None, carrier_call_id: str
) -> _CallRow | None:
    """Outbound: OUR id from the callback path. Inbound: the carrier id the worker stored."""
    if call_id is not None:
        row = (
            await session.execute(
                text(
                    "SELECT id, agent_id, carrier_call_id FROM calls "
                    "WHERE id = :cid AND tenant_id = :tid"
                ),
                {"cid": call_id, "tid": tenant_id},
            )
        ).first()
    else:
        row = (
            await session.execute(
                text(
                    "SELECT id, agent_id, carrier_call_id FROM calls "
                    "WHERE carrier_call_id = :ccid AND tenant_id = :tid "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"ccid": carrier_call_id, "tid": tenant_id},
            )
        ).first()
    if row is None:
        return None
    return _CallRow(id=UUID(str(row[0])), agent_id=UUID(str(row[1])), carrier_call_id=row[2])


async def _advance_status(
    session: AsyncSession, tenant_id: UUID, call_id: UUID, status: CallStatus | None
) -> bool:
    """Move the call to `status` only from a strictly earlier one. True when it moved.

    A compare-and-swap on the current status, so a late `ringing` never un-answers a call
    and no carrier event rewrites a terminal status. `ended_at` is filled only if nothing
    wrote it: the worker's settlement measures the end itself and wins over this
    (`worker/service._UPSERT_CALL_SQL` prefers the incoming `ended_at`).
    """
    if status is None:
        return False
    row = (
        await session.execute(
            text(
                "UPDATE calls SET status = :status, updated_at = now(), "
                "  ended_at = CASE WHEN CAST(:ends AS boolean) "
                "    THEN COALESCE(ended_at, now()) ELSE ended_at END "
                "WHERE id = :cid AND tenant_id = :tid AND status = ANY(:behind) "
                "RETURNING id"
            ),
            {
                "status": status,
                "ends": status in TERMINAL_STATUSES,
                "cid": call_id,
                "tid": tenant_id,
                "behind": statuses_behind(status),
            },
        )
    ).first()
    return row is not None


async def _record_carrier_call_id(
    session: AsyncSession, tenant_id: UUID, call: _CallRow, carrier_call_id: str
) -> None:
    """Fill the outbound row's carrier id from the callback when the dial path did not.

    The first value written stands, as for every identity column on `calls`: a second,
    different id is logged rather than adopted.
    """
    if call.carrier_call_id is None:
        await session.execute(
            text(
                "UPDATE calls SET carrier_call_id = :ccid, updated_at = now() "
                "WHERE id = :cid AND tenant_id = :tid AND carrier_call_id IS NULL"
            ),
            {"ccid": carrier_call_id, "cid": call.id, "tid": tenant_id},
        )
    elif call.carrier_call_id != carrier_call_id:
        log.warning(
            "carrier_call_id_disagrees",
            extra={"call_id": str(call.id), "carrier_call_id": carrier_call_id},
        )


# --- job 2: the CDR -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _CdrTarget:
    carrier: CarrierName
    carrier_call_id: str
    tenant_id: UUID
    call_id: UUID


async def enqueue_cdr_read(
    *,
    carrier: CarrierName,
    carrier_call_id: str,
    tenant_id: UUID,
    call_id: UUID,
    defer_s: float | None = None,
) -> str | None:
    """Queue one CDR read. Keyed per carrier call, so a repeat collapses into the one queued."""
    return await enqueue(
        CDR_JOB,
        {
            "carrier": carrier,
            "carrier_call_id": carrier_call_id,
            "tenant_id": str(tenant_id),
            "call_id": str(call_id),
        },
        job_id=job_id_for(CDR_JOB, carrier, carrier_call_id),
        **({"_defer_by": defer_s} if defer_s else {}),
    )


def _cdr_target(payload: dict[str, Any]) -> _CdrTarget:
    try:
        carrier = str(payload["carrier"])
        carrier_call_id = str(payload["carrier_call_id"])
        if not is_carrier(carrier) or not carrier_call_id:
            raise ValueError("carrier or carrier call id")
        return _CdrTarget(
            carrier=cast(CarrierName, carrier),
            carrier_call_id=carrier_call_id,
            tenant_id=UUID(str(payload["tenant_id"])),
            call_id=UUID(str(payload["call_id"])),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise ProblemError(
            kind="validation",
            code="carrier_cdr_payload_invalid",
            title="Unusable CDR job payload",
            detail="The CDR job was enqueued without a usable carrier, call or tenant id.",
        ) from exc


async def read_carrier_cdr(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Read one call's CDR and record what the carrier charged us for it."""
    attempt = int(ctx.get("job_try", 1))
    hint = str(payload.get("carrier_call_id") or "unknown")
    try:
        return await _read_cdr(_cdr_target(payload), attempt)
    except Retry:
        raise
    except Exception as exc:
        if _is_transient(exc) and attempt < WORKER_MAX_TRIES:
            raise Retry(defer=_ladder(CDR_RETRY_BACKOFF_S, attempt)) from exc
        alert(
            "WORKER_TERMINAL",
            "carrier_cdr_read_abandoned",
            detail=(
                f"{type(exc).__name__} after {attempt} attempt(s); the sweep retries it"
                if _is_transient(exc)
                else f"{type(exc).__name__} is permanent, not retried"
            ),
            carrier_call_id=hint,
        )
        raise


async def _read_cdr(target: _CdrTarget, attempt: int) -> str:
    try:
        cdr = await get_carrier(target.carrier).fetch_cdr(target.carrier_call_id)
    except ProblemError as exc:
        if _is_transient(exc):
            raise
        # A carrier that cannot answer for a CDR at all (one with no reader) answers this
        # way for every call it ever carried; an alarm per call would be a storm, and the
        # refusal's code is the fact an operator needs.
        log.warning(
            "carrier_cdr_refused",
            extra={
                "carrier": target.carrier,
                "code": exc.code,
                "call_id": str(target.call_id),
            },
        )
        return f"refused:{exc.code}"
    if cdr is None:
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=_ladder(CDR_RETRY_BACKOFF_S, attempt))
        alert(
            "WORKER_DELIVERY",
            "carrier_cdr_missing",
            detail=(
                f"carrier={target.carrier} has not written a CDR for this call after "
                f"{attempt} reads; the sweep will ask again within the hour"
            ),
            tenant_id=str(target.tenant_id),
            call_id=str(target.call_id),
            carrier_call_id=target.carrier_call_id,
        )
        return "cdr_missing"

    verdict = await record_cdr_cost(target, cdr)
    if verdict == "awaiting_metering":
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=_ladder(CDR_RETRY_BACKOFF_S, attempt))
        # Not an alarm: an unmetered call is `report_stalled_pipeline`'s to raise, and the
        # sweep reads this CDR once the meter has run.
        log.info("carrier_cdr_awaiting_metering", extra={"call_id": str(target.call_id)})
    elif verdict == "recorded_unpriced":
        alert(
            "WORKER_TERMINAL",
            "carrier_cdr_cost_unpriced",
            detail=(
                f"carrier={target.carrier} CDR currency={cdr.currency or 'absent'}: recorded "
                "with unit_cost_paid NULL, so this call's carrier cost is missing from margin"
            ),
            tenant_id=str(target.tenant_id),
            call_id=str(target.call_id),
            carrier_call_id=target.carrier_call_id,
        )
    return verdict


async def record_cdr_cost(target: _CdrTarget, cdr: CarrierCdr) -> CdrVerdict:
    """Append the carrier-cost row for this CDR, at most once. See the module docstring."""
    ref = cdr_ref(target.carrier, target.carrier_call_id)
    async with tenant_session(target.tenant_id) as session:
        await lock_call_writes(session, target.call_id)
        stored = (
            await session.execute(
                text("SELECT carrier_call_id FROM calls WHERE id = :cid AND tenant_id = :tid"),
                {"cid": target.call_id, "tid": target.tenant_id},
            )
        ).first()
        if stored is None or stored[0] != target.carrier_call_id:
            raise ProblemError(
                kind="validation",
                code="carrier_cdr_call_mismatch",
                title="CDR does not name this call",
                detail="The call row is missing or carries a different carrier call id.",
            )
        already = (
            await session.execute(
                text(
                    "SELECT 1 FROM usage_events WHERE tenant_id = :tid AND call_id = :cid "
                    "AND unit_type = 'other' AND meta->>'cdr_ref' = :ref LIMIT 1"
                ),
                {"tid": target.tenant_id, "cid": target.call_id, "ref": ref},
            )
        ).first()
        if already:
            return "already_recorded"
        metered = (
            await session.execute(
                text(
                    "SELECT qty, occurred_at, meta->>:rung_key, meta->>'voice_tier' "
                    "FROM usage_events WHERE tenant_id = :tid AND call_id = :cid "
                    "AND unit_type = 'telephony_s' LIMIT 1"
                ),
                {"tid": target.tenant_id, "cid": target.call_id, "rung_key": LEDGER_RUNG_KEY},
            )
        ).first()
        if metered is None:
            return "awaiting_metering"
        metered_seconds, occurred_at, rung, voice = metered
        cost = carrier_cost_inr(cdr)
        meta = {
            "kind": CARRIER_CDR_META_KIND,
            "cdr_ref": ref,
            "carrier": target.carrier,
            "carrier_call_id": target.carrier_call_id,
            # The carrier's talk time (`billsec`) beside the seconds the client was billed
            # on; the delta is what a later billing decision about `billsec` would move.
            "billed_seconds": cdr.billed_seconds,
            "duration_seconds": cdr.duration_seconds,
            "metered_seconds": str(metered_seconds),
            "billed_seconds_delta": str(Decimal(cdr.billed_seconds) - Decimal(metered_seconds)),
            # Not `source_currency`: that key selects the rows `billing/cost_unit` restates.
            "currency": cdr.currency,
            "cost_reported": str(cdr.total_cost_inr) if cdr.total_cost_inr is not None else None,
            "hangup_cause": cdr.hangup_cause,
            # The rung and voice the call was metered on, so this cost lands beside them
            # rather than in the unattributed bucket.
            LEDGER_RUNG_KEY: rung,
            "voice_tier": voice,
            "issued_at": datetime.now(UTC).isoformat(),
        }
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, meta, created_at) VALUES (:id, :tid, :cid, "
                "'other', 1, :cost, :at, CAST(:meta AS jsonb), now())"
            ),
            {
                "id": uuid7(),
                "tid": target.tenant_id,
                "cid": target.call_id,
                "cost": cost,
                "at": occurred_at,
                "meta": json.dumps(meta),
            },
        )
    log.info(
        "carrier_cdr_recorded",
        extra={"call_id": str(target.call_id), "priced": cost is not None},
    )
    return "recorded" if cost is not None else "recorded_unpriced"


# --- the sweep ----------------------------------------------------------------

#: Finished, metered calls with a carrier id and no CDR cost row yet, oldest first.
_OWED_CDR_SQL: Final = (
    "SELECT c.id, c.carrier_call_id FROM calls c "
    "WHERE c.carrier_call_id IS NOT NULL AND c.status = ANY(:terminal) "
    "AND COALESCE(c.ended_at, c.updated_at) < now() - :after "
    "AND COALESCE(c.ended_at, c.updated_at) > now() - :horizon "
    "AND EXISTS (SELECT 1 FROM usage_events u WHERE u.call_id = c.id "
    "  AND u.unit_type = 'telephony_s') "
    "AND NOT EXISTS (SELECT 1 FROM usage_events u WHERE u.call_id = c.id "
    "  AND u.unit_type = 'other' AND u.meta->>'kind' = :kind) "
    "ORDER BY COALESCE(c.ended_at, c.updated_at), c.id LIMIT :cap"
)


async def reconcile_carrier_cdrs(ctx: dict[str, Any]) -> str:
    """Re-enqueue the CDR read for every metered call whose carrier cost is still unknown.

    The guarantee behind the hangup path: a callback the carrier never delivered, a read
    that ran out of retries before the meter landed, a CDR the carrier wrote late. The job
    key is the hangup path's, so a call both reach is read once, and arq's result window
    bounds a call that keeps failing to one attempt an hour.

    The carrier is the live switch's: `calls` records no carrier, so a call placed before
    the switch moved is asked of the new carrier, whose refusal the reader logs and drops.

    One tenant's failure is not the sweep's (R-4); every counter rides the return string.
    """
    started = time.monotonic()
    carrier = get_settings().carrier
    enqueued = 0
    unreached = 0
    truncated = False
    for tenant_id in await callable_tenants():
        if enqueued >= CDR_SWEEP_BUDGET:
            truncated = True
            break
        try:
            async with tenant_session(tenant_id) as session:
                rows = (
                    await session.execute(
                        text(_OWED_CDR_SQL),
                        {
                            "terminal": sorted(TERMINAL_STATUSES),
                            "after": CDR_SWEEP_AFTER,
                            "horizon": CDR_SWEEP_HORIZON,
                            "kind": CARRIER_CDR_META_KIND,
                            "cap": CDR_SWEEP_PER_TENANT,
                        },
                    )
                ).all()
            for call_id, carrier_call_id in rows:
                await enqueue_cdr_read(
                    carrier=carrier,
                    carrier_call_id=str(carrier_call_id),
                    tenant_id=tenant_id,
                    call_id=UUID(str(call_id)),
                )
                enqueued += 1
        except Exception:
            log.exception("carrier_cdr_sweep_failed", extra={"tenant_id": str(tenant_id)})
            unreached += 1

    if unreached or truncated:
        alert(
            "WORKER_DELIVERY",
            "carrier_cdr_sweep_incomplete",
            detail=(
                f"unreached={unreached} truncated={truncated}: enqueued={enqueued} is a floor; "
                "calls past the cut keep an unknown carrier cost until a later sweep reaches "
                "them — check the worker log for carrier_cdr_sweep_failed"
            ),
        )
    elapsed = time.monotonic() - started
    return f"enqueued={enqueued} unreached={unreached} truncated={truncated} took={elapsed:.1f}s"


__all__ = [
    "CARRIER_CDR_META_KIND",
    "CARRIER_EVENT_JOB",
    "CDR_JOB",
    "CDR_SWEEP_MINUTES",
    "carrier_cost_inr",
    "cdr_ref",
    "enqueue_cdr_read",
    "ingest_carrier_event",
    "read_carrier_cdr",
    "reconcile_carrier_cdrs",
    "record_cdr_cost",
    "statuses_behind",
]
