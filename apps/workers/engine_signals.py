"""What the voice platform's own agent reports: a caller's "do not call me again" (D-691),
and its notices that it took a lead or handed a conversation to a person.

ThinnestAI's agent puts a caller who asks not to be called again on the WORKSPACE's
do-not-call list and sends `contact.opted_out` with `data.phone`, `data.callId`,
`data.source` (always `"call"`) and `data.optedOutAt` (VERIFIED-VENDOR-DOCS,
`thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/webhooks.md:85`).

OUR list decides who is dialled, per client (founder decision, 8 Oct 2026). So the number is
filed on the list of the client whose agent heard the request — the tenant of the route the
delivery was signed for — through `compliance.optout.record_call_optout`, the one writer every
other opt-out path uses, so the suppression, its consent-ledger evidence and its audit row land
together and a replay is a no-op. It is never pushed back to the vendor's workspace-wide list,
which every client shares.

The dispatch gate reads `dnc_list` on every dial, so the suppression is in force from this
job's commit — before the next dispatch tick (hard rule 5).
"""

from __future__ import annotations

import json
from typing import Any, Final, NoReturn, Protocol, runtime_checkable
from uuid import UUID

from arq import Retry
from calevate_shared.engine_scope import scope_of
from calevate_shared.events import EngineNotice
from sqlalchemy import text

from apps.api.compliance.optout import DETECTED_BY_ENGINE, OptOutSignal, record_call_optout
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.engine.thinnest_workspace import in_workspace
from apps.api.reliability.engine_intake_keys import open_delivery
from apps.api.reliability.service import mark_inbox_failed, mark_inbox_processed

log = get_logger(__name__)

#: Enqueued by voice-runtime (`signed_intake.ENGINE_OPT_OUT_JOB`); equal by test.
ENGINE_OPT_OUT_JOB: Final = "ingest_engine_opt_out"

#: The evidence rule written to `consent_ledger`: the vendor's agent judged it, not a phrase
#: of ours, and the ledger has to say which.
ENGINE_OPT_OUT_RULE: Final = "engine_contact_opted_out"

_RETRY_AFTER_S: Final = (30.0, 120.0)

_ROUTE_SQL: Final = (
    "SELECT tenant_id FROM engine_agent_routes WHERE engine = :engine AND engine_agent_ref = :ref"
)
_CALL_SQL: Final = "SELECT id FROM calls WHERE engine_call_id = :ecid"


def _unreadable(detail: str) -> ProblemError:
    return ProblemError(
        kind="validation",
        code="engine_delivery_unreadable",
        title="A queued engine delivery could not be read",
        detail=detail,
    )


def _phone_of(document: bytes) -> str | None:
    try:
        payload = json.loads(document)
    except ValueError as exc:
        raise _unreadable("the delivered document is not JSON") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    phone = data.get("phone") if isinstance(data, dict) else None
    return phone if isinstance(phone, str) and phone else None


async def _tenant_of(engine: str, ref: str) -> UUID | None:
    """The client whose agent heard it. The route outlives a pause and an archive, so a
    late delivery for a retired agent still finds its owner."""
    async with untenanted_session() as session:
        tenant = (await session.execute(text(_ROUTE_SQL), {"engine": engine, "ref": ref})).scalar()
    return UUID(str(tenant)) if tenant is not None else None


def _unattributable(*, ground: str, engine_call_id: str, tenant_id: UUID | None) -> None:
    # THE IN-CALL OPT-OUT CODE, not a new one: same condition, same operator action (add the
    # number by hand), and `core/alarm_severity` already has its rung.
    alert(
        "WORKER_TERMINAL",
        "in_call_optout_unattributable",
        detail=(
            "The voice platform's agent recorded a caller's request not to be called again, "
            f"and it could not be filed on a client's do-not-call list ({ground}). Find the "
            "call on the voice platform and add the number to that client's list by hand. "
            "The platform itself will not ring the number again."
        ),
        engine_call_id=engine_call_id,
        tenant_id=str(tenant_id) if tenant_id else "unknown",
    )


async def _record(payload: dict[str, Any]) -> str:
    engine = str(payload["engine"])
    engine_call_id = str(payload["execution_id"])
    ref = str(payload["engine_agent_ref"])
    delivery = payload.get("delivery")
    if not isinstance(delivery, dict):
        raise _unreadable("the job carried no delivery")
    phone = _phone_of(open_delivery(delivery, engine=engine, execution_id=engine_call_id))
    tenant_id = await _tenant_of(engine, ref)
    if tenant_id is None:
        _unattributable(ground="no_route", engine_call_id=engine_call_id, tenant_id=None)
        return "unattributable"
    if phone is None:
        _unattributable(ground="no_phone", engine_call_id=engine_call_id, tenant_id=tenant_id)
        return "unattributable"
    async with tenant_session(tenant_id) as session:
        call_id = (await session.execute(text(_CALL_SQL), {"ecid": engine_call_id})).scalar()
        try:
            record = await record_call_optout(
                session,
                tenant_id=tenant_id,
                raw_phone=phone,
                call_id=UUID(str(call_id)) if call_id is not None else None,
                detected_by=DETECTED_BY_ENGINE,
                signal=OptOutSignal(
                    rule=ENGINE_OPT_OUT_RULE, language="unknown", turn_idx=None, matched=""
                ),
            )
        except ProblemError as exc:
            if exc.code != "optout_phone_invalid":
                raise
            _unattributable(
                ground="not_suppressible", engine_call_id=engine_call_id, tenant_id=tenant_id
            )
            return "unattributable"
    log.info(
        "engine_optout_recorded",
        extra={
            "tenant_id": str(tenant_id),
            "call_id": str(call_id) if call_id else None,
            "newly_suppressed": record.newly_suppressed,
        },
    )
    return "recorded"


async def _settle_inbox(inbox_row_id: Any, *, error: str | None) -> None:
    if not inbox_row_id:
        return
    async with untenanted_session() as session:
        if error is None:
            await mark_inbox_processed(session, row_id=UUID(str(inbox_row_id)))
        else:
            await mark_inbox_failed(session, row_id=UUID(str(inbox_row_id)), error=error)


async def _abandon(payload: dict[str, Any], exc: Exception, attempt: int) -> NoReturn:
    """Mark the inbox row failed (re-claimable), then retry or stop loudly — the ingest
    job's ladder (`pipeline._abandon_ingest`). An opt-out we did not file is a person we may
    ring, so the stop pages through `engine_optout_abandoned`."""
    await _settle_inbox(payload.get("inbox_row_id"), error=type(exc).__name__)
    permanent = isinstance(exc, ProblemError) and exc.kind == "validation"
    if not permanent and attempt < WORKER_MAX_TRIES:
        raise Retry(defer=_RETRY_AFTER_S[min(attempt, len(_RETRY_AFTER_S)) - 1]) from exc
    alert(
        "WORKER_TERMINAL",
        "engine_optout_abandoned",
        detail=(
            f"{type(exc).__name__} after {attempt} attempt(s): a caller's request not to be "
            "called again, heard by the voice platform's agent, was not filed on the client's "
            "do-not-call list. Re-send the delivery from the endpoint in the vendor console, "
            "or add the number to the client's list by hand."
        ),
        engine_call_id=str(payload.get("execution_id") or "unknown"),
    )
    raise exc


async def ingest_engine_opt_out(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """File a `contact.opted_out` delivery on the hearing client's do-not-call list."""
    attempt = int(ctx.get("job_try", 1))
    try:
        outcome = await _record(payload)
    except Exception as exc:
        await _abandon(payload, exc, attempt)
    # Closed last: `processed` is what makes the event permanently deduped.
    await _settle_inbox(payload.get("inbox_row_id"), error=None)
    return outcome


# --- the engine's notices -----------------------------------------------------------

#: Enqueued by voice-runtime (`signed_intake.ENGINE_NOTICE_JOB`); equal by test.
ENGINE_NOTICE_JOB: Final = "ingest_engine_notice"


@runtime_checkable
class ReadsNotices(Protocol):
    """An adapter that turns a verified notice delivery into OUR `EngineNotice`."""

    def parse_notice(self, payload: dict[str, Any]) -> EngineNotice | None: ...


async def _notice(payload: dict[str, Any]) -> str:
    engine_name = str(payload["engine"])
    unit = str(payload["execution_id"])
    delivery = payload.get("delivery")
    if not isinstance(delivery, dict):
        raise _unreadable("the job carried no delivery")
    document = open_delivery(delivery, engine=engine_name, execution_id=unit)
    try:
        body = json.loads(document)
    except ValueError as exc:
        raise _unreadable("the delivered document is not JSON") from exc
    engine = get_engine()
    if not isinstance(engine, ReadsNotices) or not isinstance(body, dict):
        raise _unreadable(f"the {engine.name} adapter cannot read a notice")
    with in_workspace(scope_of(str(payload["engine_agent_ref"]))):
        notice = engine.parse_notice(body)
    if notice is None:
        raise _unreadable("the delivered document is not a notice")
    tenant_id = await _tenant_of(engine_name, str(payload["engine_agent_ref"]))
    # Ids only (hard rule 6): what the vendor wrote about the lead is the caller's data,
    # and our own extraction over the transcript is the record of it.
    log.info(
        "engine_notice_received",
        extra={
            "engine": engine_name,
            "kind": notice.kind,
            "notice_id": notice.notice_id,
            "tenant_id": str(tenant_id) if tenant_id else None,
            "engine_call_id": notice.engine_call_id,
        },
    )
    return notice.kind


async def ingest_engine_notice(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Normalise, attribute and record one `lead.captured` / `conversation.escalated`.

    Recorded as an id-only log line and nothing more: no surface of ours consumes these
    yet (the lead is our own extraction's, the hand-over our own roster's), so the seam ends
    at the record rather than at a guess about what the vendor's `data` holds.
    """
    attempt = int(ctx.get("job_try", 1))
    try:
        kind = await _notice(payload)
    except Exception as exc:
        await _abandon_notice(payload, exc, attempt)
    await _settle_inbox(payload.get("inbox_row_id"), error=None)
    return kind


async def _abandon_notice(payload: dict[str, Any], exc: Exception, attempt: int) -> NoReturn:
    await _settle_inbox(payload.get("inbox_row_id"), error=type(exc).__name__)
    permanent = isinstance(exc, ProblemError) and exc.kind == "validation"
    if not permanent and attempt < WORKER_MAX_TRIES:
        raise Retry(defer=_RETRY_AFTER_S[min(attempt, len(_RETRY_AFTER_S)) - 1]) from exc
    log.warning(
        "engine_notice_abandoned",
        extra={"reason": type(exc).__name__, "attempt": attempt},
    )
    raise exc


__all__ = [
    "ENGINE_NOTICE_JOB",
    "ENGINE_OPT_OUT_JOB",
    "ENGINE_OPT_OUT_RULE",
    "ReadsNotices",
    "ingest_engine_notice",
    "ingest_engine_opt_out",
]
