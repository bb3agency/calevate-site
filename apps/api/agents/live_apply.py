"""A saved setting reaches every live agent it changes, at once (D-720).

THE ONE SEAM. Whoever saves something that changes what a live agent's vendor-side config
should be (an ops console platform setting, a client setting, an agent's own change made
outside its publish) calls `queue_live_apply` in the SAME transaction as the write. That
records a `live_apply_runs` row and an outbox message; the worker
(`apps/workers/live_apply.py`) then brings every affected live agent to the state a publish
would produce right now. "Live" here includes a READY agent (paused with an engine agent,
D-838): the engine holds it, so it is republished as it stands and stays ready (D-876).
Nobody switches an agent off and on, and no campaign is paused.

HOW AN AGENT IS CONVERGED: `converge_agent`, which is `agents/service.publish_agent` (the
one publish path: compose, push, read back and score, D-64) followed by
`engine_settings.check_agent_settings` (the drift sweep's settings read-back and repair).
There is no second publish path here. `publish_agent` reads the APPLIED prompt
(`live_prompt_id`), so a client's script draft waiting behind "Put it live" is never
published by a settings change; the change rides on the script that is already live.

A CALL IN PROGRESS FINISHES ON WHAT IT STARTED WITH. On ThinnestAI a connected call keeps
the configuration it started with, for every agent field (ThinnestAI email of 12 Oct 2026,
VENDOR-STATED; OPERATIONS T-28).
The next call, including the next dial of a running campaign, starts on the new
settings.

SCOPES. `platform` walks every live agent on the active engine, `tenant` one client's, and
`agent` one. A run that has not started absorbs a later request it covers (its walk reads the
newer value anyway); a newer run supersedes the open runs it covers, so the fleet is not
walked twice for two saves a second apart.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.reliability.service import enqueue_outbox

log = get_logger(__name__)

Scope = Literal["platform", "tenant", "agent"]

#: The walk: one bounded batch per job, resumed from the run's cursor.
APPLY_JOB: Final = "apply_live_settings"
#: One agent's retry ladder, after the walk's own attempt failed on something transient.
AGENT_JOB: Final = "apply_live_agent"

#: Agents converged per walk job. Each is a publish (several vendor round trips) plus a
#: settings read-back, so 10 keeps one job well inside `WorkerSettings.job_timeout` (300s)
#: and lets other queued work interleave between batches of a platform-wide change.
BATCH_SIZE: Final = 10
#: How long a claimed run is held by the job walking it. Longer than one batch can take
#: under the job timeout, shorter than the resume cron's interval, so a worker that died
#: mid-batch is resumed by the next sweep.
LEASE_S: Final = 300
#: The failed agents listed on a run. The count is exact; the list is for the console.
MAX_FAILURES_KEPT: Final = 50
#: Codes a retry cannot change: our own refusals about the agent or the account.
PERMANENT_KINDS: Final = frozenset({"validation", "business_rule", "not_found", "permission"})
#: A maintenance window refuses every publish (D-544) and ends on its own; never a give-up.
MAINTENANCE_CODE: Final = "platform_maintenance"

_LOCK: Final = "SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"


def _check_target(scope: Scope, tenant_id: UUID | None, agent_id: UUID | None) -> None:
    ok = (
        (scope == "platform" and tenant_id is None and agent_id is None)
        or (scope == "tenant" and tenant_id is not None and agent_id is None)
        or (scope == "agent" and tenant_id is not None and agent_id is not None)
    )
    if not ok:
        raise ValueError(f"live apply scope {scope!r} names the wrong target")


async def queue_live_apply(
    session: AsyncSession,
    *,
    scope: Scope,
    reason: str,
    tenant_id: UUID | None = None,
    agent_id: UUID | None = None,
    requested_by: UUID | None = None,
) -> UUID:
    """Bring every live agent in `scope` up to date, after the caller's transaction commits.

    Call it in the transaction that writes the change; it does not commit. `reason` names
    what changed (a setting key, or a short source name such as `lead_calling`) and is shown
    to operators. Returns the run that will carry the change.
    """
    _check_target(scope, tenant_id, agent_id)
    # Serialises the coalesce-or-create decision per target: two saves for one client at
    # once must not both decide that no pending run covers them. Per target rather than
    # global, because the caller's transaction holds it until commit and one client's slow
    # save must not hold up another's. A race across targets costs a redundant walk only.
    lock_key = "live_apply:platform" if tenant_id is None else f"live_apply:{tenant_id}"
    await session.execute(text(_LOCK), {"key": lock_key})
    params: dict[str, Any] = {"scope": scope, "tid": tenant_id, "aid": agent_id}
    covering = (
        await session.execute(
            text(
                "UPDATE live_apply_runs SET reasons = CASE WHEN reasons ? :reason THEN reasons "
                "ELSE reasons || jsonb_build_array(CAST(:reason AS text)) END, "
                "updated_at = now() WHERE id = ("
                "SELECT id FROM live_apply_runs WHERE status = 'pending' AND ("
                "scope = 'platform' "
                "OR (scope = 'tenant' AND tenant_id = CAST(:tid AS uuid) "
                "AND CAST(:scope AS text) IN ('tenant', 'agent')) "
                "OR (scope = 'agent' AND agent_id = CAST(:aid AS uuid) "
                "AND CAST(:scope AS text) = 'agent')) "
                "ORDER BY created_at LIMIT 1) AND status = 'pending' RETURNING id"
            ),
            {**params, "reason": reason},
        )
    ).first()
    if covering is not None:
        log.info("live_apply_coalesced", extra={"run_id": str(covering[0]), "scope": scope})
        return UUID(str(covering[0]))

    run_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO live_apply_runs (id, scope, tenant_id, agent_id, reasons, "
            "requested_by) VALUES (:id, :scope, :tid, :aid, CAST(:reasons AS jsonb), :by)"
        ),
        {**params, "id": run_id, "reasons": json.dumps([reason]), "by": requested_by},
    )
    await session.execute(
        text(
            "UPDATE live_apply_runs SET status = 'superseded', superseded_by = :id, "
            "lease_until = NULL, updated_at = now() "
            "WHERE status IN ('pending', 'running') AND id <> :id AND ("
            "CAST(:scope AS text) = 'platform' "
            "OR (CAST(:scope AS text) = 'tenant' AND tenant_id = CAST(:tid AS uuid)) "
            "OR (CAST(:scope AS text) = 'agent' AND scope = 'agent' "
            "AND agent_id = CAST(:aid AS uuid)))"
        ),
        {**params, "id": run_id},
    )
    await enqueue_outbox(session, job=APPLY_JOB, payload={"run_id": str(run_id)})
    log.info(
        "live_apply_queued",
        extra={
            "run_id": str(run_id),
            "scope": scope,
            "tenant_id": str(tenant_id) if tenant_id else None,
            "agent_id": str(agent_id) if agent_id else None,
            "reason": reason,
        },
    )
    return run_id


#: The reason a deploy that changed the platform's own prompt text records, followed by the
#: text's revision (`platform_prompt_revision`).
PLATFORM_PROMPT_REASON: Final = "platform_prompt"


def platform_prompt_revision() -> str:
    """A short digest of the text every live agent carries that only a deploy can change: the
    platform layers `compose_engine_prompt` wraps around a script, how a script's sections
    compile to engine steps, our call rules (`CALL_INSTRUCTIONS`, D-850), the order of the
    greeting field and its salutations (`join_first_words`) and the
    call-behaviour values every agent is published with (`hosted_platform.PLATFORM_AGENT_VALUES`).

    Composed over reference agents rather than read from the constants, so a change in any
    section builder (registers, knowledge, the cannot-help rules) moves it too. Stable across
    processes: no ids, clocks or settings go in.
    """
    from calevate_shared.call_script import (
        CallScript,
        Capabilities,
        ConversationStage,
        native_steps,
        render_steps,
    )
    from calevate_shared.engine import (
        CALL_INSTRUCTIONS,
        INTRODUCTION_SALUTATIONS,
        SCREEN_CALL_INSTRUCTIONS,
        AgentConfig,
        compose_engine_prompt,
        join_first_words,
        sends_our_call_rules,
    )
    from calevate_shared.languages import offered_language_tags

    script = CallScript(
        schema_version=2,
        stages=[
            ConversationStage(
                id="ask", name="Ask", instruction="Ask what they need.", collect=["a", "b"]
            )
        ],
    )
    # Every offered language, so a change to any language's platform sentences moves it.
    primary, *extra = offered_language_tags()
    parts: list[str] = [render_steps(native_steps(script, can=Capabilities(True, False)))]
    # Every direction, with and without a business name, so a change to any wording of the
    # role sentence moves it too.
    references: tuple[tuple[bool, bool, Literal["inbound", "outbound", "both"], str], ...] = (
        (True, True, "inbound", "B"),
        (False, False, "outbound", ""),
        (True, False, "both", "B"),
    )
    for callbacks, in_knowledge, direction, business in references:
        cfg = AgentConfig(
            tenant_id="t",
            agent_id="a",
            name="A",
            business=business,
            direction=direction,
            language_primary=primary,
            languages_extra=list(extra),
            system_prompt="S",
            opening_line="O",
            call_is_recorded=True,
            facts_in_knowledge=in_knowledge,
            knowledge_tool="search_knowledge" if in_knowledge else None,
            callbacks_offered=callbacks,
            forwarded_line=not callbacks,
            # Memory on with our section (the third agent) and with the engine's (the first),
            # so a change to either rendering moves the revision.
            caller_memory_enabled=callbacks,
            caller_memory_in_engine=in_knowledge,
            # Our hand-over rule (D-847) is composed only under `ownRules`.
            engine_own_rules=callbacks,
            # A screen agent's steps and spelling (D-906) on the first and third.
            caller_has_screen=callbacks,
        )
        parts.append(compose_engine_prompt(cfg))
    # Our call rules (D-850), and which agents send them with the console's switch off: a
    # screen agent does (D-906), so a change to that rule republishes every live agent.
    parts += [CALL_INSTRUCTIONS, SCREEN_CALL_INSTRUCTIONS]
    for screen in (False, True):
        off = cfg.model_copy(
            update={"engine_call_instructions": False, "caller_has_screen": screen}
        )
        parts.append(f"ours with the switch off, screen {screen}: {sends_our_call_rules(off)}")
    # How the greeting field orders the opening line and the notices (D-861), and the
    # introduction with its salutation in each language that has one (D-865), which the
    # reference agents above cannot show: their script has no opening line.
    parts.append(join_first_words("N", "O", ai_notice="", language=primary))
    parts += [
        join_first_words("A N", "hello, O", ai_notice="A", language=language)
        for language in sorted(INTRODUCTION_SALUTATIONS)
    ]
    # The fixed call-behaviour values too (filler timing, interruptions, re-ask), so a deploy
    # that changes one republishes every live agent rather than each reading as drift.
    from apps.api.engine.hosted_platform import PLATFORM_AGENT_VALUES

    parts.append(json.dumps(PLATFORM_AGENT_VALUES, sort_keys=True))
    # Which agents a platform run converges: widening it (ready agents, D-876) walks the fleet
    # once more, so agents a narrower walk skipped are brought onto this build's text.
    from apps.api.agents.models import PUBLISHED_STATUSES

    parts.append(",".join(PUBLISHED_STATUSES))
    # The caller-memory statement in force (D-900): a new version pauses memory on every
    # account that accepted an older one, which only reaches the engine by a republish.
    from apps.api.compliance.caller_memory import CALLER_MEMORY_ATTESTATION_VERSION

    parts.append(f"caller_memory_statement:{CALLER_MEMORY_ATTESTATION_VERSION}")
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16]


async def queue_platform_prompt_apply(session: AsyncSession) -> UUID | None:
    """After a deploy, bring every live agent onto the platform prompt text this build
    carries, once per revision. Returns the run, or None when this revision was already
    queued by an earlier start (any status: a finished run is not repeated, and a failed
    agent is the run's own retry ladder and alarm, not a reason to walk the fleet again).

    Called at worker start. Without it a platform text change reaches an agent only on its
    next publish, and until then the drift sweep reports the agent's instructions as
    changed on the engine while nothing is wrong with them.
    """
    reason = f"{PLATFORM_PROMPT_REASON}:{platform_prompt_revision()}"
    # The same lock `queue_live_apply` takes for a platform run (re-entrant in one
    # transaction), so two workers starting together queue one run.
    await session.execute(text(_LOCK), {"key": "live_apply:platform"})
    seen = (
        await session.execute(
            text("SELECT 1 FROM live_apply_runs WHERE reasons ? :reason LIMIT 1"),
            {"reason": reason},
        )
    ).first()
    if seen is not None:
        return None
    return await queue_live_apply(session, scope="platform", reason=reason)


# The worker's own enqueues live here, beside the job names they spell, so every
# producer of these jobs names them as a module-level constant (`scripts/check_job_wiring`).


async def queue_walk(session: AsyncSession, run_id: UUID) -> None:
    """The next batch of a run's walk, through the outbox, in the caller's transaction."""
    await enqueue_outbox(session, job=APPLY_JOB, payload={"run_id": str(run_id)})


async def queue_agent_retry(
    session: AsyncSession, run_id: UUID, *, tenant_id: UUID, agent_id: UUID
) -> None:
    """One agent's retry ladder, through the outbox, in the caller's transaction."""
    await enqueue_outbox(
        session,
        job=AGENT_JOB,
        payload={"run_id": str(run_id), "tenant_id": str(tenant_id), "agent_id": str(agent_id)},
    )


async def resume_walk(run_id: UUID, *, tick: int) -> None:
    """Re-enqueue a stalled walk directly. Keyed per run and per resume tick: two workers
    resuming one run in one tick enqueue one job, a later tick is not deduped against a
    finished one, and the run's lease decides between any two that do run."""
    from apps.api.core.queue import enqueue, job_id_for

    await enqueue(
        APPLY_JOB,
        {"run_id": str(run_id)},
        job_id=job_id_for(APPLY_JOB, str(run_id), f"resume-{tick}"),
    )


# ------------------------------------------------------------------ the run's record


@dataclass(frozen=True, slots=True)
class LiveApplyRunView:
    id: UUID
    scope: Scope
    tenant_id: UUID | None
    agent_id: UUID | None
    reasons: list[str]
    status: str
    total: int | None
    applied: int
    failed: int
    retrying: int
    failures: list[dict[str, Any]]
    created_at: datetime
    finished_at: datetime | None
    superseded_by: UUID | None


_RUN_COLUMNS: Final = (
    "id, scope, tenant_id, agent_id, reasons, status, total, applied, failed, retrying, "
    "failures, created_at, finished_at, superseded_by"
)


def _view(row: Any) -> LiveApplyRunView:
    return LiveApplyRunView(
        id=row[0],
        scope=row[1],
        tenant_id=row[2],
        agent_id=row[3],
        reasons=list(row[4] or []),
        status=row[5],
        total=row[6],
        applied=int(row[7]),
        failed=int(row[8]),
        retrying=int(row[9]),
        failures=list(row[10] or []),
        created_at=row[11],
        finished_at=row[12],
        superseded_by=row[13],
    )


async def recent_runs(
    session: AsyncSession, *, scope: Scope | None = None, limit: int = 10
) -> list[LiveApplyRunView]:
    """The newest runs, newest first. Superseded runs are kept: they say what replaced them."""
    rows = (
        await session.execute(
            text(
                f"SELECT {_RUN_COLUMNS} FROM live_apply_runs "
                "WHERE CAST(:scope AS text) IS NULL OR scope = CAST(:scope AS text) "
                "ORDER BY created_at DESC LIMIT :limit"
            ),
            {"scope": scope, "limit": limit},
        )
    ).all()
    return [_view(row) for row in rows]


async def read_run(session: AsyncSession, run_id: UUID) -> LiveApplyRunView | None:
    row = (
        await session.execute(
            text(f"SELECT {_RUN_COLUMNS} FROM live_apply_runs WHERE id = :id"), {"id": run_id}
        )
    ).first()
    return _view(row) if row is not None else None


# ------------------------------------------------------------------ converging one agent

#: Live, or ready and not taking calls (D-838): both are agents the engine holds, and a ready
#: one skipped here kept the old platform text and settings while its Try it chat and trial
#: test calls ran them, and read as drift on every sweep (D-876).
_PUBLISHED_AGENT: Final = text(
    "SELECT name FROM agents WHERE id = :aid AND deleted_at IS NULL AND archived_at IS NULL "
    "AND status IN ('live', 'paused') AND engine_agent_ref IS NOT NULL"
)
_REF: Final = text("SELECT engine_agent_ref FROM agents WHERE id = :aid")

Outcome = Literal["applied", "not_live"]


class SettingsNotHeldError(Exception):
    """The agent was republished but its settings read back different. Retried like a
    vendor failure; never surfaced through a route, so not a `ProblemError`."""

    code: Final = "live_apply_settings_not_held"

    def __init__(self, drifted: tuple[str, ...]) -> None:
        super().__init__(", ".join(drifted))
        self.drifted = drifted


async def converge_agent(*, tenant_id: UUID, agent_id: UUID) -> tuple[Outcome, str | None]:
    """Republish one published agent, as it stands, from our rows and read its settings
    back. (outcome, name).

    Raises the publish's or the read-back's `ProblemError`; the caller decides whether a
    retry can help. A ready agent stays ready (`take_calls=False`); a draft, archived or
    deleted agent is left alone, since its first publish sends everything anyway.
    """
    from apps.api.agents.engine_settings import check_agent_settings
    from apps.api.agents.service import publish_agent
    from apps.api.db.session import tenant_session

    async with tenant_session(tenant_id) as session:
        name = (await session.execute(_PUBLISHED_AGENT, {"aid": agent_id})).scalar()
        if name is None:
            return "not_live", None
        await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id, take_calls=False)
        ref = (await session.execute(_REF, {"aid": agent_id})).scalar()
    if ref:
        checked = await check_agent_settings(
            tenant_id=tenant_id, agent_id=agent_id, engine_agent_ref=str(ref)
        )
        if checked is not None and checked.drifted and not checked.repaired:
            raise SettingsNotHeldError(checked.drifted)
    return "applied", str(name)


def is_permanent(exc: BaseException) -> bool:
    """A refusal a retry cannot change. A maintenance window is never permanent."""
    return (
        isinstance(exc, ProblemError)
        and exc.code != MAINTENANCE_CODE
        and exc.kind in PERMANENT_KINDS
    )


def failure_detail(exc: BaseException) -> dict[str, Any]:
    """Counts a failure record keeps beside its code: for a script over the engine's box,
    how long it is, the limit and its longest sections. Never text (hard rule 6)."""
    from apps.api.agents.engine_limits import PromptTooLongError
    from apps.api.agents.prompt_size import as_dict

    return as_dict(exc.size) if isinstance(exc, PromptTooLongError) else {}


#: What a recorded refusal means to the owner, for the codes a live apply records most. The
#: too-long sentence is `engine_limits.too_long_sentence`, built from the recorded counts.
HELD_BACK_MESSAGES: Final[dict[str, str]] = {
    "agreements_not_accepted": (
        "Your agent is still using its previous settings because this account's agreements "
        "are not accepted. The account owner accepts them on the Agreements & readiness "
        "screen; the update then goes live by itself."
    ),
}
HELD_BACK_GENERIC: Final = (
    "Your agent is still using its previous settings because the latest update could not be "
    "put on it. We have been told, and it is retried with the next change."
)


@dataclass(frozen=True, slots=True)
class HeldBack:
    """The newest update a live agent did not take, since it last went live."""

    code: str
    message: str
    failed_at: datetime | None
    total_chars: int | None = None
    limit_chars: int | None = None
    over_chars: int | None = None
    #: (label, chars) of the script's longest sections, for a script over the box.
    longest: tuple[tuple[str, int], ...] = ()


def held_back_from(failure: dict[str, Any], failed_at: datetime | None) -> HeldBack:
    from apps.api.agents.engine_limits import PROMPT_TOO_LONG, too_long_message

    code = str(failure.get("code", ""))
    over = failure.get("over_chars")
    if code == PROMPT_TOO_LONG and isinstance(over, int):
        message = too_long_message(over)
    else:
        message = HELD_BACK_MESSAGES.get(code, HELD_BACK_GENERIC)
    longest = tuple(
        (str(p.get("label", "")), int(p.get("chars", 0)))
        for p in failure.get("longest") or []
        if isinstance(p, dict)
    )
    return HeldBack(
        code=code,
        message=message,
        failed_at=failed_at,
        total_chars=failure.get("total_chars"),
        limit_chars=failure.get("limit_chars"),
        over_chars=over if isinstance(over, int) else None,
        longest=longest,
    )


_HELD_BACK: Final = text(
    "SELECT f.value, COALESCE(CAST(f.value->>'at' AS timestamptz), r.updated_at) AS at "
    "FROM live_apply_runs r CROSS JOIN LATERAL jsonb_array_elements(r.failures) AS f(value) "
    "WHERE f.value->>'agent_id' = :aid "
    "AND (CAST(:since AS timestamptz) IS NULL "
    "OR COALESCE(CAST(f.value->>'at' AS timestamptz), r.updated_at) > CAST(:since AS timestamptz)) "
    "ORDER BY at DESC LIMIT 1"
)


async def held_back(
    session: AsyncSession, *, agent_id: UUID, since: datetime | None
) -> HeldBack | None:
    """The newest live-apply refusal for `agent_id` recorded after `since` (when the agent
    last went live, `agents.live_verified_at`), or None. `session` may be untenanted: the
    caller has already proved the agent is its tenant's."""
    row = (await session.execute(_HELD_BACK, {"aid": str(agent_id), "since": since})).first()
    if row is None:
        return None
    return held_back_from(dict(row[0]), row[1])


def failure_code(exc: BaseException) -> str:
    if isinstance(exc, ProblemError | SettingsNotHeldError):
        return exc.code
    return exc.__class__.__name__


__all__ = [
    "AGENT_JOB",
    "APPLY_JOB",
    "BATCH_SIZE",
    "HELD_BACK_GENERIC",
    "HELD_BACK_MESSAGES",
    "LEASE_S",
    "MAINTENANCE_CODE",
    "MAX_FAILURES_KEPT",
    "HeldBack",
    "LiveApplyRunView",
    "Scope",
    "converge_agent",
    "failure_code",
    "failure_detail",
    "held_back",
    "held_back_from",
    "is_permanent",
    "queue_agent_retry",
    "queue_live_apply",
    "queue_walk",
    "read_run",
    "recent_runs",
    "resume_walk",
]
