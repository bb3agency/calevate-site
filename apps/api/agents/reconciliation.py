"""The RECORD a scheduled drift sweep writes, and the summary an operator reads.

D-121 built the instrument and left it on-demand. `agents/publishing.py::engine_drift_for`
and `GET /v1/agents/{agent_id}/engine-state` ask the ENGINE what it is running and
compare it with our row — and nothing ran them on a schedule, so the two divergences that
instrument exists for were found only by whoever thought to open one agent's screen:

* somebody edited the agent in the VENDOR'S OWN DASHBOARD. Nothing of ours ran, so every
  table we own agrees with itself and is wrong;
* a publish failed on OUR side AFTER the vendor committed — a connection reset on the
  response — so our transaction rolled back to the previous script and the engine kept
  the new one. The divergence points the other way and no amount of re-reading our own
  tables finds it.

This module is the two halves a periodic sweep needs and the one an operator needs:
`claim_drift_batch` (what to look at next), `record_drift` (what we saw), and
`read_engine_drift` (how bad is it, platform-wide). The sweep itself is
`apps/workers/engine_reconciliation.py`.

**RECONCILIATION IS A READ, AND NOTHING HERE RE-PUBLISHES.** That is D-121's argument and
it is preserved deliberately rather than inherited: re-publishing over a drift overwrites
whatever the vendor's dashboard was used to change, which may have been the correct
emergency edit made while our console was unreachable. A sweep that "fixed" it would
silently undo an operator's incident response at 3am, platform-wide, on a schedule. What
this produces is a RECORD and an ALERT so a human decides with evidence. The only writes
below are to OUR observation columns; `VoiceEngine` is never asked to change anything.

WHY THE RECORD LIVES ON `engine_agent_routes`
---------------------------------------------
Because it is the row that already stands for one vendor-side agent object, and because
`agents` is FORCE-RLS'd: a global work queue ordered by staleness and a cross-tenant ops
summary are both unaskable from a tenant session, and the alternative — an RLS exemption
on `agents` — is a far larger hole than reusing the exemption that already exists for the
routing bridge. Migration `d4b8e1c73f05` carries the full argument, including why no
detail SENTENCE is stored here (hard rules 1 and 6: the un-RLS'd table holds a verdict
from a fixed vocabulary and two timestamps, never prose about a tenant's agent).

HARD RULE 2. Nothing here imports an adapter or sees a vendor field. The engine is
reached through `agents/publishing.py`, which consumes `AgentSnapshot`; what crosses into
this module is `EngineDrift`, which is ours.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import get_args
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.verification import VerifyState
from apps.api.db.result import rowcount_of

#: The five values `engine_agent_routes.drift_state` may hold, as the CHECK in migration
#: `d4b8e1c73f05` spells them. Derived from `VerifyState` rather than retyped, so a fifth
#: verdict added to the verification vocabulary cannot silently fail a DB constraint at
#: 03:00 — `tests/engine_drift_reconciliation_test.py` asserts this set equals the CHECK's.
#:
#: `not_applied` IS storable here, unlike in `agents.live_verify_state`. There it is a
#: refusal with a transaction to roll back; here recording the divergence is the entire
#: output, because there is nothing to refuse — the drift already happened.
DRIFT_STATES: frozenset[str] = frozenset(get_args(VerifyState)) | {"not_published"}

#: The verdicts an operator has to act on. `unreadable` and `unreachable` are NOT among
#: them and that is the `AgentSnapshot` doctrine held all the way to the alert: we could
#: not tell is not a mismatch, and an alarm that fires when a vendor is briefly slow is an
#: alarm somebody mutes before it ever catches a real dashboard edit.
DRIFT_STATES_OUT_OF_SYNC: frozenset[str] = frozenset({"not_applied"})


@dataclass(frozen=True, slots=True)
class DriftCandidate:
    """One vendor-side agent object the sweep may spend a round trip on."""

    tenant_id: UUID
    agent_id: UUID
    engine_agent_ref: str
    #: When it was last looked at, or None for never. Carried so the sweep can log the
    #: staleness it actually worked through rather than the staleness it hoped for.
    drift_checked_at: datetime | None


async def claim_drift_batch(
    session: AsyncSession, *, engine: str, limit: int
) -> list[DriftCandidate]:
    """The next `limit` vendor agent objects to reconcile, STALEST FIRST.

    THE BOUND, AND WHY IT IS AN ORDERING RATHER THAN A CURSOR. Every row this returns
    costs one vendor round trip, so an unbounded sweep is a self-inflicted rate-limit
    incident that arrives on a schedule — the shape `engine_drift_for` refused to build
    into the pending banner ("a banner that silently dialled the vendor on every page
    load would be a rate-limit incident wearing a reassurance"). `LIMIT` bounds the cost
    per tick; `ORDER BY drift_checked_at NULLS FIRST` is what makes the bound fair, and it
    needs no cursor, no offset and no state of its own: writing the timestamp is what
    moves a row to the back of the queue, so coverage is a consequence of the work rather
    than of a pointer somebody has to keep correct. A row that fails mid-sweep keeps its
    old timestamp and is therefore FIRST next tick, which is the behaviour a cursor would
    have had to be written to reproduce.

    `active` is the published-agent filter and it is the right one: `experiments.py` is
    the only writer that sets it false, on an agent whose arms were retired, and an
    inactive route is an object nobody publishes to any more. Spending a round trip on it
    is a round trip stolen from a live agent.

    `engine = :engine` is not decoration. A route left over from another vendor (the
    table's key is `(engine, engine_agent_ref)` precisely so both can coexist during a
    migration) would be read back through the CONFIGURED adapter, i.e. compared against
    the wrong platform's answer — a guaranteed false `not_applied` on every tick.

    NO ROW LOCK AND NO CLAIM STAMP. Both were considered and both are wrong here. A lock
    (`FOR UPDATE SKIP LOCKED`) buys single-flight against a concurrent sweep, and there
    cannot be one: the tick's wall-clock budget is smaller than its interval by
    construction (`apps/workers/engine_reconciliation.py` asserts it at import), and arq's
    `job_timeout` caps the rest. Stamping `drift_checked_at` up front to reserve the work
    would record a check that has not happened — a row reading "checked 30 seconds ago"
    for a vendor call that timed out is the precise lie `live_verified_at` stays NULL to
    avoid.
    """
    rows = (
        await session.execute(
            text(
                "SELECT tenant_id, agent_id, engine_agent_ref, drift_checked_at "
                "FROM engine_agent_routes "
                "WHERE active AND engine = :engine "
                # `engine_agent_ref` breaks the tie so a tick is reproducible: without it
                # every never-checked row sorts equal and the batch is whatever the plan
                # happened to emit, which makes a partial sweep untestable.
                "ORDER BY drift_checked_at NULLS FIRST, engine_agent_ref "
                "LIMIT :limit"
            ),
            {"engine": engine, "limit": limit},
        )
    ).all()
    return [
        DriftCandidate(
            tenant_id=UUID(str(row[0])),
            agent_id=UUID(str(row[1])),
            engine_agent_ref=str(row[2]),
            drift_checked_at=row[3],
        )
        for row in rows
    ]


async def record_drift(session: AsyncSession, *, engine: str, ref: str, state: str) -> bool:
    """Write down what the engine was observed to be holding. Returns False if the route
    vanished under us (an agent unpublished mid-sweep), which is not an error.

    `drift_detected_at` is the one column with a rule rather than a value, and the rule is
    what makes an age mean something: it is set on the FIRST tick that finds this object
    out of sync and left alone by every tick after, so it dates the run rather than the
    observation. `COALESCE(drift_detected_at, now())` is that rule in one expression —
    re-stamping it each tick would reset the clock every 30 minutes and report a
    fortnight-old vendor-console edit as "detected just now", which is the number an
    operator uses to decide whether this is a race or a real divergence.

    It clears the moment the object reads back `applied`, so a drift that was fixed —
    by a republish, or by somebody undoing their dashboard edit — stops being counted at
    the next observation rather than needing a hand to clear it.

    UNCONDITIONAL last-writer-wins, deliberately, where BACKEND-PATTERNS §5 would normally
    want a CAS. There is nothing to compare against: this statement records what a read
    at a known instant SAW, and an older observation cannot be more true than a newer one.
    A CAS here would refuse to write the current state of the world because a stale one
    disagreed with it.
    """
    result = await session.execute(
        text(
            "UPDATE engine_agent_routes SET drift_state = :state, drift_checked_at = now(), "
            "drift_detected_at = CASE WHEN :out_of_sync THEN COALESCE(drift_detected_at, now()) "
            "ELSE NULL END, updated_at = now() "
            "WHERE engine = :engine AND engine_agent_ref = :ref"
        ),
        {
            "state": state,
            "engine": engine,
            "ref": ref,
            "out_of_sync": state in DRIFT_STATES_OUT_OF_SYNC,
        },
    )
    return bool(rowcount_of(result))


@dataclass(frozen=True, slots=True)
class EngineDriftSummary:
    """How far the platform's agents have drifted from what we published — the ops read.

    COUNTS AND TIMESTAMPS ONLY (hard rule 6). Nothing here is derived from a prompt, a
    disclosure line or a phone number; the per-agent sentence lives behind
    `GET /v1/agents/{agent_id}/engine-state`, which is tenant-scoped and permissioned.
    The console gets a number and an age, which is what sizes a decision — the shape
    `DeadLetterQueue` established for the outbox.
    """

    #: Live vendor agent objects in scope for the sweep, on the configured engine.
    live_agents: int
    #: Objects the sweep has never reached. Distinct from `in_sync` for the reason
    #: `agents.live_verify_state`'s `unverified` is distinct from `unreachable`: an agent
    #: nobody has looked at must not be counted as one we looked at and liked.
    never_checked: int
    #: PROVEN divergence — the engine is running something else. The number that matters.
    out_of_sync: int
    #: Read back and matched.
    in_sync: int
    #: We could not tell: the adapter could not find the property, or the read failed.
    #: Reported separately from `out_of_sync` and never folded into it — see
    #: `DRIFT_STATES_OUT_OF_SYNC`.
    undetermined: int
    #: When the OLDEST currently-out-of-sync object was first seen to be wrong. None
    #: exactly when `out_of_sync` is 0 — not a sentinel timestamp, the argument
    #: `DeadLetterQueue.oldest_created_at` makes.
    oldest_drift_at: datetime | None
    #: The oldest `drift_checked_at` among objects that HAVE been checked. This is the
    #: sweep's own health: a number that stops moving means the cron is not running, and
    #: without it a platform whose worker died would report a serenely clean `out_of_sync`
    #: of zero forever. None when nothing has ever been checked.
    oldest_checked_at: datetime | None


async def read_engine_drift(session: AsyncSession, *, engine: str) -> EngineDriftSummary:
    """THE definition of "how far has the platform drifted" — one query, one instant.

    ONE aggregate rather than several counts, for `read_dead_letter_queue`'s reason: the
    parts must add up to the total by construction, so a sweep tick landing between two
    statements cannot publish a breakdown that contradicts itself. `now()` is a single
    value for the whole statement, so every row is classified against the same instant.

    Untenanted by design — `engine_agent_routes` is the listed, reasoned RLS exemption
    (`db/registry.py`) and this is a platform-wide question with no tenant whose answer it
    could be. That is exactly the property `report_stalled_pipeline` did NOT have before
    it was fixed, where an untenanted probe over a FORCE-RLS'd table reported a healthy
    system no matter how bad things were.
    """
    row = (
        await session.execute(
            text(
                "SELECT count(*) AS live, "
                "count(*) FILTER (WHERE drift_state IS NULL) AS never_checked, "
                "count(*) FILTER (WHERE drift_state = ANY(:out_of_sync)) AS out_of_sync, "
                "count(*) FILTER (WHERE drift_state = 'applied') AS in_sync, "
                "count(*) FILTER (WHERE drift_state IN ('unreadable', 'unreachable', "
                "'not_published')) AS undetermined, "
                "min(drift_detected_at) FILTER (WHERE drift_state = ANY(:out_of_sync)) "
                "AS oldest_drift, "
                "min(drift_checked_at) AS oldest_checked "
                "FROM engine_agent_routes WHERE active AND engine = :engine"
            ),
            {"engine": engine, "out_of_sync": sorted(DRIFT_STATES_OUT_OF_SYNC)},
        )
    ).one()
    # `.one()` rather than `.first()` plus an unreachable `row is None`: a bare aggregate
    # always returns exactly one row, so the guard could only ever be excluded from
    # coverage — and an excluded branch is one nobody will see fail. SQLAlchemy raises
    # `NoResultFound` if the impossible happens, pointing at this line.
    return EngineDriftSummary(
        live_agents=int(row[0]),
        never_checked=int(row[1]),
        out_of_sync=int(row[2]),
        in_sync=int(row[3]),
        undetermined=int(row[4]),
        oldest_drift_at=row[5],
        oldest_checked_at=row[6],
    )


__all__ = [
    "DRIFT_STATES",
    "DRIFT_STATES_OUT_OF_SYNC",
    "DriftCandidate",
    "EngineDriftSummary",
    "claim_drift_batch",
    "read_engine_drift",
    "record_drift",
]
