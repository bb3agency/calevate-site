"""The RECORD the periodic KB drift sweep writes, and the summary an operator reads.

D-41 built the instrument and left it on the PUBLISH PATH. `kb/service.publish_source`
asks the engine what it is holding (`_reconcile_engine_state`) and refuses to publish onto
an agent carrying a copy no row of ours mentions — and nothing asks that question at any
other time, so the two divergences it exists to catch are found only by whoever publishes
next. For a knowledge base that is not "soon": a client pastes their price list once and
does not touch it again for months.

    A VENDOR-DASHBOARD EDIT   somebody adds, replaces or deletes a knowledge base in
                              Bolna's own console. Nothing of ours ran, so every table we
                              own agrees with itself and is wrong.
    A LOST-RESPONSE PUBLISH   the vendor took the attach and our COMMIT failed after it.
                              Our rows rolled back; the engine kept the document. The
                              divergence points the other way and re-reading our own
                              tables can never find it. `publish_source` says so in its
                              own last paragraph: "a COMMIT that fails after a successful
                              attach leaves the engine holding a document none of our rows
                              mention. `_reconcile_engine_state` cannot prevent that —
                              nothing here can".

This module is the two halves a periodic sweep needs plus the one an operator needs:
`claim_kb_drift_batch` (what to look at next), `record_kb_drift` (what we saw), and
`read_kb_drift` (how bad is it, platform-wide). The sweep itself is
`apps/workers/kb_reconciliation.py`. It is deliberately the same shape, the same table and
the same doctrine as `agents/reconciliation.py` — one way per problem, so an operator who
has read one panel can read the other.

**RECONCILIATION IS A READ, AND NOTHING HERE RE-PUBLISHES OR DETACHES.** D-121 argues
this for the agent sweep and every clause transfers: re-publishing over a drift overwrites
whatever the vendor's dashboard was used to change, which may have been the correct
emergency edit made while our console was the thing that was down. It transfers with FORCE
here, because the repair a KB drift superficially invites is `detach_kb` — an irreversible
delete at the vendor of a document our tables, by hypothesis, cannot describe. A sweep
that "tidied up" would destroy the only copy of the text somebody added by hand. What this
produces is a RECORD and an ALERT so a human decides with evidence.

WHY THE RECORD LIVES ON `engine_agent_routes`, and not on `kb_sources`: migration
`a7c31e05b8d4` carries the argument. In short, the unit of observation is one
`list_kb(agent_ref)` round trip — an AGENT, not a source — and the engine-side extra copy
has no `kb_sources` row to be written on at all; `kb_sources` is also FORCE-RLS'd, so
neither the global staleness queue nor the cross-tenant ops summary could be asked of it.

HARD RULE 2. Nothing here imports an adapter or sees a vendor field. What crosses into
this module is a `list[EngineKBRef]` — an alias for `str`, our own type — and a set of
handles read from our own tables.

HARD RULE 6. A verdict from a fixed vocabulary, two timestamps and counts. No source
name, no chunk, no handle: `EngineKBRef` is a vendor-issued opaque id and is still not
stored here, because this table is globally readable and the per-agent detail belongs on
a tenant-scoped surface.
"""

from __future__ import annotations

from collections.abc import Collection, Set
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.result import rowcount_of

#: The six values `engine_agent_routes.kb_drift_state` may hold, as the CHECK in migration
#: `a7c31e05b8d4` spells them. `tests/kb_drift_reconciliation_test.py` asserts this set
#: against the LIVE constraint rather than against the migration's source, so a verdict
#: added here and not there is a sweep that starts failing every write at 00:23 with
#: nothing on any screen to explain it.
KB_DRIFT_STATES: frozenset[str] = frozenset(
    {"in_sync", "unaccounted", "missing", "divergent", "unreadable", "unreachable"}
)

#: The verdicts an operator has to act on. `unreadable` and `unreachable` are NOT among
#: them, and that is `agents/reconciliation.DRIFT_STATES_OUT_OF_SYNC`'s doctrine held all
#: the way to the alert: "we could not tell" is not evidence, and an alarm that fires when
#: a vendor is briefly slow is an alarm somebody mutes before it ever catches a real
#: dashboard edit. They are still counted, still recorded per agent, and still on the ops
#: console — where a rising `undetermined` reads as a vendor problem rather than as a
#: fleet of agents answering from unapproved text.
KB_DRIFT_STATES_OUT_OF_SYNC: frozenset[str] = frozenset({"unaccounted", "missing", "divergent"})


def classify_kb_drift(
    *, attached: Collection[str] | None, recorded: Set[str], listing_attributes_by_agent: bool
) -> str:
    """One agent's verdict, from what the engine listed and what our rows recorded.

    A pure function on two sets, so the whole decision is testable without a database or a
    vendor, and so the interesting case below cannot be re-derived slightly differently by
    the next reader.

    BOTH DIRECTIONS ARE DETECTED, and they are different failures:

    * `attached - recorded` — the engine holds a document NO row of ours names. The agent
      can answer a caller from text no human approved, which is precisely what the FLOWS §7
      approval gate exists to prevent, and the next publish will refuse with
      `kb_engine_out_of_sync` rather than stack a second copy. THE DANGEROUS DIRECTION.
    * `recorded - attached` — we believe a document is attached and the engine does not
      list it. The agent knows LESS than was approved: T3 retrieval finds nothing and it
      refuses-and-escalates (T4) where it should have quoted a price. Also the state that
      makes the NEXT publish fail — `_require_addressable` and `kb_detach_failed` both fire
      on a handle the engine no longer has.

    THE ONE CASE THAT IS NOT EVIDENCE, AND WHY IT IS SINGLED OUT
    -----------------------------------------------------------
    An EMPTY listing for an agent we believe holds documents is the signature of two very
    different worlds, and we cannot tell them apart from this call:

    1. every one of that agent's documents really was deleted at the vendor;
    2. the vendor's listing does not attribute rows to agents at all, so the adapter's
       per-agent filter matches nothing and EVERY agent lists empty.

    World 2 is not hypothetical: `apps/api/engine/bolna.py::list_kb` reads
    `GET /knowledgebase/all` and keeps rows whose `agent_id` equals the ref, and whether
    that field exists is pilot gate 8's `kb_list_carries_agent_linkage` — still open,
    because Bolna publishes no OpenAPI spec and every body on that path is a hand-
    maintained claim (`scripts/pilot/knowledge.py`). `_reconcile_engine_state` already
    refuses to draw any conclusion from a listing it could not obtain, for the same reason
    stated the same way: "It can prove a divergence; it can never prove the absence of
    one."

    So the caller supplies `listing_attributes_by_agent`: a POSITIVE CONTROL observed in
    the same tick — did the vendor's listing return anything at all for any agent we
    asked about? If it did, the linkage field exists and an empty answer for THIS agent is
    real evidence. If nothing in the tick listed anything, the honest verdict is
    `unreadable`, which is counted as undetermined and does not alert.

    The rejected alternative was to report `missing` and let an operator work it out.
    Under world 2 that is a fleet-wide false alarm arriving on a schedule — every agent
    with knowledge, every tick, forever — which is the specific failure the
    `unreadable`/`not_applied` split exists to prevent. Erring the other way costs one
    detection (an agent whose ONLY source was deleted at the vendor, in a tick where no
    other agent listed anything) and reports it as "we could not tell", which is true.

    `attached is None` means the read itself failed and is `unreachable` — kept apart from
    `unreadable` for the reason `agents/verification.py` keeps them apart: "the vendor
    refused us" and "the vendor answered and the answer decides nothing" are different
    things to go and look at.
    """
    if attached is None:
        return "unreachable"
    on_engine = frozenset(attached)
    if not on_engine and recorded and not listing_attributes_by_agent:
        return "unreadable"
    unaccounted = bool(on_engine - recorded)
    absent = bool(recorded - on_engine)
    if unaccounted and absent:
        return "divergent"
    if unaccounted:
        return "unaccounted"
    if absent:
        return "missing"
    return "in_sync"


async def handles_if_no_publish_in_flight(
    session: AsyncSession, *, agent_id: UUID
) -> frozenset[str] | None:
    """This agent's recorded handles, or None if a publish holds the floor right now.

    THE WINDOW THIS EXISTS FOR IS GUARANTEED, NOT MERELY POSSIBLE. `publish_source`
    detaches every copy of a source BEFORE attaching its replacement (D-41's ordering, and
    it is the correct one — the alternative leaves the agent free to answer from either
    version). So there is a stretch of every single publish in which the engine holds
    strictly FEWER documents than our rows record, while the rows that would explain it
    are still uncommitted. A sweep that listed during it would file a routine update as
    `missing` and, on the far side of the attach, as `unaccounted`. That is not a rare
    race to be absorbed by the next tick; it is a false verdict this sweep would produce
    on demand, every time a client updated a price list.

    The publisher already holds `pg_advisory_xact_lock(publish_lock_key(agent))` from
    before its first engine call until COMMIT or ROLLBACK, so the whole inconsistent
    stretch is exactly the stretch in which that lock is held. `pg_try_advisory_xact_lock`
    is therefore the entire instrument: it returns immediately, and a False answer means
    "somebody is mid-publish, come back next tick" — which costs nothing, because a row
    the sweep skipped keeps its old `kb_drift_checked_at` and is first in the next batch.

    **TRY, NEVER WAIT.** The blocking form would work and is wrong: it would make an
    operator's Publish button queue behind a background job they did not ask for, which
    is a cost `_lock_agent_publishes` accepts between two publishes (both of which a human
    is waiting on) and should not accept for a sweep.

    THE CALLER MUST READ TWICE, and this function cannot do that for it: the engine round
    trip happens between the two reads and this module may not make one (hard rule 2).
    Holding one transaction open across the vendor call was the alternative and it is
    worse on both counts — it pins a pooled connection for the length of a third party's
    response, and it blocks the publisher for that same length. Two short reads that
    bracket the listing, plus the requirement that they agree, close the window without
    doing either: a publish overlapping READ ONE or READ TWO fails the try-lock, and one
    that begins and commits strictly between them changes the handle set (`attach_kb`
    mints a fresh handle on every call — the Protocol says so), so the two reads disagree
    and the agent is skipped. `apps/workers/kb_reconciliation.py::_observe_one` is that
    caller and the only one.
    """
    from apps.api.kb.service import publish_lock_key, recorded_handles_of_agent

    acquired = (
        await session.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": publish_lock_key(agent_id)},
        )
    ).scalar()
    if not acquired:
        return None
    return frozenset(await recorded_handles_of_agent(session, agent_id))


@dataclass(frozen=True, slots=True)
class KbDriftCandidate:
    """One vendor-side agent object whose knowledge the sweep may spend a round trip on."""

    tenant_id: UUID
    agent_id: UUID
    engine_agent_ref: str
    #: When its knowledge was last looked at, or None for never. Carried so the sweep can
    #: log the staleness it actually worked through rather than the staleness it hoped for.
    kb_drift_checked_at: datetime | None


async def claim_kb_drift_batch(
    session: AsyncSession, *, engine: str, limit: int
) -> list[KbDriftCandidate]:
    """The next `limit` vendor agent objects whose knowledge to reconcile, STALEST FIRST.

    Every clause here is `agents/reconciliation.claim_drift_batch`'s and is load-bearing
    for the same reasons — `LIMIT` bounds the cost per tick, `ORDER BY kb_drift_checked_at
    NULLS FIRST` makes the bound fair with no cursor to keep correct (writing the timestamp
    is what moves a row to the back of the queue, so a row that failed mid-sweep is FIRST
    next tick), `active` keeps a round trip from being stolen from a live agent by one
    nobody publishes to any more, and `engine = :engine` stops a route left over from
    another vendor being compared against the wrong platform's answer.

    The ONE difference is the column, and it is the whole reason this is a second function
    rather than a parameter on the first: `drift_checked_at` is the agent sweep's queue
    position. Sharing it would make each sweep push the other's unread rows out of reach.
    """
    rows = (
        await session.execute(
            text(
                "SELECT tenant_id, agent_id, engine_agent_ref, kb_drift_checked_at "
                "FROM engine_agent_routes "
                "WHERE active AND engine = :engine "
                # `engine_agent_ref` breaks the tie so a tick is reproducible: without it
                # every never-checked row sorts equal and the batch is whatever the plan
                # happened to emit, which makes a partial sweep untestable.
                "ORDER BY kb_drift_checked_at NULLS FIRST, engine_agent_ref "
                "LIMIT :limit"
            ),
            {"engine": engine, "limit": limit},
        )
    ).all()
    return [
        KbDriftCandidate(
            tenant_id=UUID(str(row[0])),
            agent_id=UUID(str(row[1])),
            engine_agent_ref=str(row[2]),
            kb_drift_checked_at=row[3],
        )
        for row in rows
    ]


async def record_kb_drift(session: AsyncSession, *, engine: str, ref: str, state: str) -> bool:
    """Write down what the engine was observed to be holding. Returns False if the route
    vanished under us (an agent unpublished mid-sweep), which is not an error.

    `kb_drift_detected_at` carries `record_drift`'s rule, and the rule is what makes an age
    mean something: set on the FIRST tick that finds this agent out of sync, left alone by
    every tick after, cleared the moment it reads back in sync. `COALESCE(..., now())` is
    that rule in one expression — re-stamping it each tick would report a fortnight-old
    dashboard edit as "detected just now", which is the number an operator uses to decide
    whether this is a publish that raced the sweep or a real divergence.

    UNCONDITIONAL last-writer-wins, deliberately, where BACKEND-PATTERNS §5 would normally
    want a CAS: there is nothing to compare against. This records what a read at a known
    instant SAW, and an older observation cannot be more true than a newer one. A CAS here
    would refuse to write the current state of the world because a stale one disagreed.
    """
    result = await session.execute(
        text(
            "UPDATE engine_agent_routes SET kb_drift_state = :state, "
            "kb_drift_checked_at = now(), kb_drift_detected_at = CASE WHEN :out_of_sync "
            "THEN COALESCE(kb_drift_detected_at, now()) ELSE NULL END, updated_at = now() "
            "WHERE engine = :engine AND engine_agent_ref = :ref"
        ),
        {
            "state": state,
            "engine": engine,
            "ref": ref,
            "out_of_sync": state in KB_DRIFT_STATES_OUT_OF_SYNC,
        },
    )
    return bool(rowcount_of(result))


@dataclass(frozen=True, slots=True)
class KbDriftSummary:
    """How far the platform's published knowledge has drifted from what we approved.

    COUNTS AND TIMESTAMPS ONLY (hard rule 6), the shape `EngineDriftSummary` established.
    Nothing here is derived from a source name, a chunk or a handle.
    """

    #: Live vendor agent objects in scope for the sweep, on the configured engine.
    live_agents: int
    #: Objects whose knowledge the sweep has never reached. Distinct from `in_sync` for
    #: the reason `never_checked` is distinct there: an agent nobody has looked at must
    #: not be counted as one we looked at and liked.
    never_checked: int
    #: PROVEN divergence in either direction. The number that matters.
    out_of_sync: int
    #: The engine holds exactly what our rows say it holds.
    in_sync: int
    #: We could not tell — the read failed, or the listing was empty and nothing in the
    #: tick proved the vendor attributes its listing by agent. Reported separately and
    #: never folded into `out_of_sync`; see `KB_DRIFT_STATES_OUT_OF_SYNC`.
    undetermined: int
    #: When the OLDEST currently-diverged agent was first seen to be wrong. None exactly
    #: when `out_of_sync` is 0 — not a sentinel timestamp.
    oldest_drift_at: datetime | None
    #: The oldest `kb_drift_checked_at` among agents that HAVE been checked. This is the
    #: sweep's own pulse: a number that stops moving means the cron is not running, and
    #: without it a platform whose worker died would report a serenely clean `out_of_sync`
    #: of zero forever. None when nothing has ever been checked.
    oldest_checked_at: datetime | None


async def read_kb_drift(session: AsyncSession, *, engine: str) -> KbDriftSummary:
    """THE definition of "how far has the published knowledge drifted" — one query.

    ONE aggregate rather than several counts, for `read_engine_drift`'s reason: the parts
    must add up to the total BY CONSTRUCTION, so a sweep tick landing between two
    statements cannot publish a breakdown that contradicts itself. `now()` is a single
    value for the whole statement, so every row is classified against the same instant.

    Untenanted by design — `engine_agent_routes` is the listed, reasoned RLS exemption
    (`db/registry.py`) and this is a platform-wide question with no tenant whose answer it
    could be.
    """
    row = (
        await session.execute(
            text(
                "SELECT count(*) AS live, "
                "count(*) FILTER (WHERE kb_drift_state IS NULL) AS never_checked, "
                "count(*) FILTER (WHERE kb_drift_state = ANY(:out_of_sync)) AS out_of_sync, "
                "count(*) FILTER (WHERE kb_drift_state = 'in_sync') AS in_sync, "
                "count(*) FILTER (WHERE kb_drift_state = ANY(:undetermined)) AS undetermined, "
                "min(kb_drift_detected_at) FILTER (WHERE kb_drift_state = ANY(:out_of_sync)) "
                "AS oldest_drift, "
                "min(kb_drift_checked_at) AS oldest_checked "
                "FROM engine_agent_routes WHERE active AND engine = :engine"
            ),
            {
                "engine": engine,
                "out_of_sync": sorted(KB_DRIFT_STATES_OUT_OF_SYNC),
                # Derived rather than listed, so a seventh verdict added to the vocabulary
                # lands in one of the two buckets instead of silently vanishing from a
                # panel whose parts are then required to sum to its total.
                "undetermined": sorted(KB_DRIFT_STATES - KB_DRIFT_STATES_OUT_OF_SYNC - {"in_sync"}),
            },
        )
    ).one()
    # `.one()` rather than `.first()` plus an unreachable `row is None`: a bare aggregate
    # always returns exactly one row, so the guard could only be excluded from coverage —
    # and an excluded branch is one nobody will see fail.
    return KbDriftSummary(
        live_agents=int(row[0]),
        never_checked=int(row[1]),
        out_of_sync=int(row[2]),
        in_sync=int(row[3]),
        undetermined=int(row[4]),
        oldest_drift_at=row[5],
        oldest_checked_at=row[6],
    )


__all__ = [
    "KB_DRIFT_STATES",
    "KB_DRIFT_STATES_OUT_OF_SYNC",
    "KbDriftCandidate",
    "KbDriftSummary",
    "claim_kb_drift_batch",
    "classify_kb_drift",
    "handles_if_no_publish_in_flight",
    "read_kb_drift",
    "record_kb_drift",
]
