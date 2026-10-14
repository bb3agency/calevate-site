"""What the voice platform's own agent reports: a caller's "do not call me again" (D-691),
and its notices that it took a lead or handed a conversation to a person.

ThinnestAI's agent puts a caller who asks not to be called again on the WORKSPACE's
do-not-call list and sends `contact.opted_out` with `data.phone`, `data.callId`,
`data.source` (always `"call"`), `data.optedOutAt` and `data.reason`, the caller's own words up to
160 characters or null (VERIFIED-VENDOR-DOCS, `thinnest-findings/mirror/snapshots/2026-10-13/
pages/api-reference/webhooks.md:85`, `:496-513`). The adapter reads it (`parse_opt_out`); the
words are redacted and kept as the consent ledger's evidence, and never logged (hard rule 6).

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
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, NoReturn, Protocol, runtime_checkable
from uuid import UUID

from arq import Retry
from calevate_shared.engine_scope import scope_of
from calevate_shared.events import EngineNotice, EngineOptOut, EngineProblem
from sqlalchemy import text

from apps.api.billing.engine_minutes import OWN_VOICE_RATE_KEYS
from apps.api.compliance.optout import DETECTED_BY_ENGINE, OptOutSignal, record_call_optout
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.engine.thinnest_workspace import in_workspace
from apps.api.reliability.engine_intake_keys import open_delivery
from apps.api.reliability.service import mark_inbox_failed, mark_inbox_processed
from apps.workers.redaction import redact

log = get_logger(__name__)

#: Enqueued by voice-runtime (`signed_intake.ENGINE_OPT_OUT_JOB`); equal by test.
ENGINE_OPT_OUT_JOB: Final = "ingest_engine_opt_out"

#: The evidence rule written to `consent_ledger`: the vendor's agent judged it, not a phrase
#: of ours, and the ledger has to say which.
ENGINE_OPT_OUT_RULE: Final = "engine_contact_opted_out"

#: The longest the caller's words are kept as evidence: the engine's own cap on `reason`
#: (160 characters, webhooks.md:496-513), measured after redaction.
OPT_OUT_REASON_MAX_CHARS: Final = 160

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


@runtime_checkable
class ReadsOptOuts(Protocol):
    """An adapter that turns a verified opt-out delivery into OUR `EngineOptOut`."""

    def parse_opt_out(self, payload: dict[str, Any]) -> EngineOptOut | None: ...


def _opt_out_of(document: bytes, *, ref: str) -> EngineOptOut:
    try:
        payload = json.loads(document)
    except ValueError as exc:
        raise _unreadable("the delivered document is not JSON") from exc
    engine = get_engine()
    if not isinstance(engine, ReadsOptOuts) or not isinstance(payload, dict):
        raise _unreadable(f"the {engine.name} adapter cannot read an opt-out")
    with in_workspace(scope_of(ref)):
        opt_out = engine.parse_opt_out(payload)
    if opt_out is None:
        raise _unreadable("the delivered document is not an opt-out")
    return opt_out


def _evidence_words(reason: str | None) -> str:
    """The caller's words as the consent ledger keeps them: through the transcript redactor
    first, then capped, as `optout.detect_opt_out` keeps its matched phrase. Empty when the
    engine kept none, which the evidence read shows as "no words were kept"."""
    if not reason:
        return ""
    return redact(reason).text[:OPT_OUT_REASON_MAX_CHARS]


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
    opt_out = _opt_out_of(
        open_delivery(delivery, engine=engine, execution_id=engine_call_id), ref=ref
    )
    phone = opt_out.phone
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
                    rule=ENGINE_OPT_OUT_RULE,
                    language="unknown",
                    turn_idx=None,
                    matched=_evidence_words(opt_out.reason),
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
    route = await _route_of(engine_name, str(payload["engine_agent_ref"]))
    attached = False
    if route is not None and notice.engine_call_id is not None:
        # On a handed call the notice names the agent the call was handed to, and arrives
        # on that agent's endpoint; it is filed on the call it carries either way.
        attached = await _file_signal(
            route,
            engine_call_id=notice.engine_call_id,
            kind=notice.kind,
            occurred_at=notice.occurred_at,
        )
    # Ids only (hard rule 6): what the vendor wrote about the lead is the caller's data,
    # and our own extraction over the transcript is the record of it.
    log.info(
        "engine_notice_received",
        extra={
            "engine": engine_name,
            "kind": notice.kind,
            "notice_id": notice.notice_id,
            "tenant_id": str(route.tenant_id) if route else None,
            "engine_call_id": notice.engine_call_id,
            "attached": attached,
        },
    )
    return notice.kind


async def ingest_engine_notice(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Normalise, attribute and record one `lead.captured` / `conversation.escalated`.

    Filed on the call it names (`call_engine_signals`, kind and time only) and logged by id.
    The lead itself is our own extraction's and the hand-over our own roster's, so nothing
    else consumes it.
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


@dataclass(frozen=True, slots=True)
class _Route:
    tenant_id: UUID
    agent_id: UUID
    #: The rate the agent was last published on; `byok_voice` or `byok_llm_voice` is Studio.
    rate_key: str | None


_ROUTE_FULL_SQL: Final = (
    "SELECT tenant_id, agent_id, engine_rate_key FROM engine_agent_routes "
    "WHERE engine = :engine AND engine_agent_ref = :ref"
)

_SIGNAL_SQL: Final = (
    "INSERT INTO call_engine_signals (id, tenant_id, agent_id, engine_call_id, kind, "
    "occurred_at, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, :kind, :at, "
    "now(), now()) ON CONFLICT (tenant_id, engine_call_id, kind) DO NOTHING RETURNING id"
)


async def _route_of(engine: str, ref: str) -> _Route | None:
    async with untenanted_session() as session:
        row = (await session.execute(text(_ROUTE_FULL_SQL), {"engine": engine, "ref": ref})).first()
    if row is None:
        return None
    return _Route(
        tenant_id=UUID(str(row[0])),
        agent_id=UUID(str(row[1])),
        rate_key=str(row[2]) if row[2] is not None else None,
    )


async def _file_signal(
    route: _Route, *, engine_call_id: str, kind: str, occurred_at: datetime | None
) -> bool:
    """Record one signal on its call. True the first time; a repeat of the same kind on the
    same call (a re-send, a second notice) changes nothing."""
    async with tenant_session(route.tenant_id) as session:
        inserted = (
            await session.execute(
                text(_SIGNAL_SQL),
                {
                    "id": uuid7(),
                    "tid": route.tenant_id,
                    "aid": route.agent_id,
                    "ecid": engine_call_id,
                    "kind": kind,
                    "at": occurred_at,
                },
            )
        ).scalar()
    return inserted is not None


# --- problems on a live call ----------------------------------------------------------

#: Enqueued by voice-runtime (`signed_intake.ENGINE_PROBLEM_JOB`); equal by test.
ENGINE_PROBLEM_JOB: Final = "ingest_engine_problem"


@runtime_checkable
class ReadsProblems(Protocol):
    """An adapter that turns a verified problem delivery into OUR `EngineProblem`."""

    def parse_problem(self, payload: dict[str, Any]) -> EngineProblem | None: ...


def _alarm_problem(problem: EngineProblem, route: _Route) -> None:
    ids = {"tenant_id": str(route.tenant_id), "agent_id": str(route.agent_id)}
    if problem.kind == "own_key_failed":
        # The platform never answers on its own providers for a job one of our keys holds:
        # no backup model, no backup voice (thinnest-findings/mirror/snapshots/2026-10-13/
        # pages/api-reference/bring-your-own-keys.md:171-178). Our keys there are the
        # Cartesia voice key (Studio) and, where it is switched on, our model key.
        alert(
            "WORKER_DELIVERY",
            "engine_call_own_key_failed",
            detail=(
                "the voice platform reported that one of our own keys failed on a live call "
                "(own_key_failed). There is no backup on our own keys: if the model key "
                "failed the caller heard the platform's apology instead of an answer, and if "
                "the voice key failed the agent did not speak. Check the keys the voice "
                "platform holds for us (ops Voices: Studio ready reads the voice key back) "
                "and the provider accounts behind them for quota, billing or a revoked key, "
                "then place a test call on this agent."
                + (
                    f' The voice platform said: "{problem.operator_detail}"'
                    if problem.operator_detail
                    else ""
                )
            ),
            episode=str(route.agent_id),
            **ids,
        )
    elif route.rate_key in OWN_VOICE_RATE_KEYS and problem.kind == "voice_failed":
        alert(
            "WORKER_DELIVERY",
            "studio_call_voice_failed",
            detail=(
                "a Studio call reported voice_failed: the caller may have heard silence or "
                "been cut off. Studio speaks on our own voice key and has no fallback voice. "
                "Check the Cartesia key and its balance in ops Voices (Studio ready reads the "
                "key back), then place a test call on this agent."
            ),
            episode=str(route.agent_id),
            **ids,
        )
    elif problem.kind == "voice_failed":
        alert(
            "WORKER_DELIVERY",
            "engine_call_voice_failed",
            detail=(
                "the voice platform reported that a call's voice connection failed: the caller "
                "may have heard silence or been cut off. If several agents report it, check "
                "the platform's status; otherwise place a test call on this agent."
            ),
            episode=str(route.agent_id),
            **ids,
        )
    elif problem.kind == "no_answer_from_model":
        alert(
            "WORKER_DELIVERY",
            "engine_call_model_unanswered",
            detail=(
                "the voice platform reported no_answer_from_model on a live call: the agent "
                "could not get an answer from the platform's model, even from its backup, and "
                "apologised to the caller. "
                "If it repeats, check the agent's model choice and the platform's status."
            ),
            episode=str(route.agent_id),
            **ids,
        )
    # `slow_reply` raises nothing on its own: the healer counts it against the agent.


async def _problem(payload: dict[str, Any]) -> str:
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
    if not isinstance(engine, ReadsProblems) or not isinstance(body, dict):
        raise _unreadable(f"the {engine.name} adapter cannot read a call problem")
    with in_workspace(scope_of(str(payload["engine_agent_ref"]))):
        problem = engine.parse_problem(body)
    if problem is None:
        raise _unreadable("the delivered document is not a call problem")
    route = await _route_of(engine_name, str(payload["engine_agent_ref"]))
    if route is None:
        log.warning("engine_problem_unattributable", extra={"engine": engine_name})
        return "unattributable"
    first = await _file_signal(
        route,
        engine_call_id=problem.engine_call_id,
        kind=problem.kind,
        occurred_at=problem.occurred_at,
    )
    if first:
        _alarm_problem(problem, route)
    log.info(
        "engine_problem_received",
        extra={
            "kind": problem.kind,
            "tenant_id": str(route.tenant_id),
            "agent_id": str(route.agent_id),
            "engine_call_id": problem.engine_call_id,
            "first": first,
        },
    )
    return problem.kind


async def ingest_engine_problem(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """File one `call.problem` on its call, and alarm the kinds an operator must act on."""
    attempt = int(ctx.get("job_try", 1))
    try:
        kind = await _problem(payload)
    except Exception as exc:
        await _abandon_notice(payload, exc, attempt)
    await _settle_inbox(payload.get("inbox_row_id"), error=None)
    return kind


__all__ = [
    "ENGINE_NOTICE_JOB",
    "ENGINE_OPT_OUT_JOB",
    "ENGINE_OPT_OUT_RULE",
    "ENGINE_PROBLEM_JOB",
    "ReadsNotices",
    "ReadsProblems",
    "ingest_engine_notice",
    "ingest_engine_opt_out",
    "ingest_engine_problem",
]
