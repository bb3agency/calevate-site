"""The REFERENCE-AWARE knowledge-pack collector (D-611) — the half a bucket rule cannot do.

WHAT WAS ACTUALLY MISSING, BECAUSE THE OBVIOUS ANSWER IS WRONG
--------------------------------------------------------------
`knowledge-packs/` already has an object-lifecycle rule
(`infra/object-lifecycle/policy.json`, `knowledge-packs-growth-ceiling-not-retention`),
and that rule is a growth CEILING at 2555 days rather than a reclamation mechanism. It is
deliberately that long, and three files say so in three places for the same reason: **S3
expiry is measured from an object's CREATION, and a pack is rebuilt only when a client's
knowledge changes.** So the pack a live agent answers out of gets OLDER the longer that
client's price list has been correct, and any expiry short enough to reclaim space would
delete the live pack of the best-behaved client on the platform first. The symptom is an
agent that retrieves nothing while every screen reports its knowledge as published.

**AGE IS THEREFORE NOT THE PREDICATE. REFERENCE IS, AND AGE IS ONLY A GRACE ON TOP OF IT.**
This module deletes a pack when `agents.knowledge_pack_sha256` names no such object — the
question a bucket rule cannot ask, because a bucket rule cannot read a database. A pack
that is two years old and still referenced is LIVE and is never touched; a pack that was
superseded an hour ago is unreferenced and is still not touched, because of the grace
below. `tests/pack_gc_test.py::test_a_stale_but_referenced_pack_is_never_collected` is
that distinction, pinned.

WHY A GRACE AT ALL, GIVEN THE PREDICATE IS REFERENCE
----------------------------------------------------
`kb/pack.refresh_published_pack` writes the OBJECT BEFORE the POINTER COMMITS, on purpose
(the other order puts a pointer to nothing in a column the call path trusts). So for the
width of one publish transaction a pack is legitimately unreferenced and about to be
referenced, and a collector that raced it would delete the pack of the client who just
pressed publish. `PACK_GRACE_S` is what makes that race impossible rather than unlikely:
an object must have been in the store for seven days before it is eligible, and a pointer
that has not committed in seven days is never going to.

It also covers the smaller window between this sweep's own listing and its own delete, and
it is why the listing is taken BEFORE the reference read rather than after — an object in
the listing existed before every reference we then go on to read, so anything referenced at
any instant up to the read is protected. The grace is the guarantee; the ordering is a belt.

⚠ **THE ONE RESIDUAL RACE, STATED RATHER THAN HIDDEN.** A session assembles a call by
reading `agents.knowledge_pack_sha256` (`voice_worker/config.load_session_config`) and then
fetching that object. If a republish lands between this sweep's reference read and that
session's pointer read, the session gets the NEW digest and is unaffected; if it lands
before, the session holds the OLD digest while this sweep may already have judged it
unreferenced. The exposure is the milliseconds between one session's config read and its
pack fetch, on the single tick that follows the republish, and the failure is one call's
`temporarily_unavailable` on a knowledge tool — self-healing on the next call, alarmed by
the worker, and strictly smaller than the exposure the same session already has to a
storage blip. It is not closed by re-reading references before the delete, which would
narrow the window and not remove it; it is closed only by never deleting, which is the
state this module exists to end.

WHAT IT REFUSES TO DELETE, AND WHY EACH REFUSAL IS FAIL-CLOSED
---------------------------------------------------------------
Every judgement this module makes is "delete", so every uncertainty resolves to "keep":

* **A key it did not write.** `parse_pack_object_key` round-trips or refuses; something
  under our prefix that this platform did not put there is reported, never removed.
* **A tenant it could not enumerate.** Objects are only eligible when their `{tenant}`
  segment appears in the organization directory this tick actually read. Deleting on
  ABSENCE would mean a truncated or failed directory read wipes the live pack of every
  tenant it missed — the single most expensive mistake available here — so absence is a
  FINDING and never a licence. The cost is that a CLOSED tenant's packs are never
  collected by this sweep; that residue is named in the report below and belongs in the
  closure path, which positively knows the tenant is gone.
* **An object whose age the store did not report.** Age unknown is not age zero.
* **Anything at all, if the reference read was incomplete.** The directory walk is
  all-or-nothing: one tenant session that raises aborts the tick before a single delete.

`MAX_DELETIONS_PER_TICK` is the last backstop and is not a performance knob — it bounds
the blast radius of a defect in everything above to one tick's worth, which leaves an
operator an alarm and a day rather than an empty prefix.

WHAT IT WRITES: nothing. No table, no ledger, no marker column. The objects are
content-addressed and write-once, so a pack this sweep removes and a client then
republishes is simply re-uploaded under the same key (`publish_pack`'s existing skip
becomes a write again) — which makes the whole operation idempotent and re-drivable with
no state to keep in step.

HARD RULE 6: counts, tenant ids and agent ids. Never a key in a log line (a pack key is
three ids and a digest, which is fine, but `storage.delete_objects` already refuses to log
keys for the prefixes where it is not, and one rule per module beats two).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from arq import Retry
from calevate_shared.knowledge_pack import PACK_OBJECT_PREFIX, parse_pack_object_key
from sqlalchemy import text

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import admin_session, tenant_session
from apps.workers.storage import StoredObject, delete_objects, objects_under

log = get_logger(__name__)

#: How long an object must have been in the store before it is eligible, whatever its
#: reference state. Seven days, and the number is chosen against the LONGEST thing it has
#: to cover rather than the likeliest: the publish transaction whose object lands before
#: its pointer commits (seconds), this sweep's own listing-to-delete window (minutes), and
#: any redrive of a failed publish that has not yet retried. Seven days is three orders of
#: magnitude above all three and costs almost nothing in space — a client republishing
#: daily keeps a week of superseded packs instead of a year's.
PACK_GRACE_S: Final = 7 * 24 * 60 * 60

#: The blast-radius bound. Not a page size — the listing and the delete are both already
#: batched — but a ceiling on how wrong one tick may be. A backlog larger than this drains
#: over consecutive days, which is the correct speed for a job whose mistakes are
#: irreversible.
MAX_DELETIONS_PER_TICK: Final = 2000

#: The schedule, read from here by `settings.py` so the cron and the reasoning cannot
#: drift. 05:07 — after the hours the fleet already uses (02:33 trials, 03:17 expiry,
#: 03:40 retention, 04:05 the TLS probe, 04:40 the account KB sweep) and off every
#: recurring minute (:12/:42 gloss, :19/:49 index sync, :23 KB drift, :25 copilot).
PACK_GC_HOUR: Final = frozenset({5})
PACK_GC_MINUTE: Final = frozenset({7})

#: Every agent in the fleet that points at a pack, as `(tenant_id, agent_id, digest)`.
#: `IS NOT NULL` because a NULL pointer is an agent that has published nothing and
#: protects no object; including it would put `None` in a set of digests for no reader.
_POINTERS_SQL: Final = """
SELECT id, knowledge_pack_sha256 FROM agents WHERE knowledge_pack_sha256 IS NOT NULL
"""

#: The directory, and `admin_session` rather than `untenanted_session` for the reason
#: `dispatcher._all_tenants` records in full: `organizations` carries its own FORCEd policy
#: matching on `id`, so a session with no GUC set sees no clients at all — this sweep would
#: read an empty fleet, find every pack unattributable, and collect nothing forever.
#:
#: NO `deleted_at IS NULL` FILTER, and the direction of that choice is the point: a
#: soft-deleted tenant's agents still hold pointers, and excluding them here would make
#: their live packs look unreferenced. Every filter narrows the PROTECTED set, so this
#: query takes none.
_DIRECTORY_SQL: Final = "SELECT id FROM organizations ORDER BY id"


@dataclass(frozen=True, slots=True)
class PackGcPlan:
    """What one tick decided, before anything was deleted.

    Separated from the doing so the distinction this whole module rests on — referenced
    against unreferenced — is a pure function over a listing and a reference set, provable
    without a bucket, a database or a clock.
    """

    collect: tuple[str, ...] = ()
    referenced: int = 0
    too_new: int = 0
    unattributable: tuple[str, ...] = field(default=())

    @property
    def deferred(self) -> int:
        """Eligible objects this tick will not reach, because of the per-tick ceiling."""
        return max(0, len(self.collect) - MAX_DELETIONS_PER_TICK)


def plan_pack_collection(
    objects: list[StoredObject],
    *,
    references: set[tuple[UUID, UUID, str]],
    known_tenants: set[UUID],
    now: datetime,
) -> PackGcPlan:
    """Score one listing against one reference set. Pure; deletes nothing.

    `references` is `(tenant_id, agent_id, content_sha256)` and NOT a bare set of digests,
    because the key carries all three and a digest-only comparison would let one agent's
    live pointer protect a different agent's object — two agents in one tenant publishing
    the same corpus produce the same digest under different keys, and after this sweep the
    surviving object would be whichever one nobody was pointing at.
    """
    collect: list[str] = []
    unattributable: list[str] = []
    referenced = too_new = 0

    for obj in objects:
        parsed = parse_pack_object_key(obj.key)
        if parsed is None:
            unattributable.append(obj.key)
            continue
        tenant_id, agent_id, digest = parsed
        if tenant_id not in known_tenants:
            unattributable.append(obj.key)
            continue
        if (tenant_id, agent_id, digest) in references:
            referenced += 1
            continue
        # Age unknown is not age zero: a store that reported no timestamp is one we cannot
        # prove the grace against, and the grace is the only thing standing between this
        # sweep and a publish that is still in flight.
        if obj.last_modified is None or (now - obj.last_modified).total_seconds() < PACK_GRACE_S:
            too_new += 1
            continue
        collect.append(obj.key)

    # Deterministic, so a tick that hits the ceiling drains the same objects in the same
    # order rather than sampling a different slice each day and finishing none of them.
    collect.sort()
    return PackGcPlan(
        collect=tuple(collect),
        referenced=referenced,
        too_new=too_new,
        unattributable=tuple(sorted(unattributable)),
    )


async def fleet_pack_references() -> tuple[set[tuple[UUID, UUID, str]], set[UUID]]:
    """Every live pack pointer in the fleet, and the tenants we positively enumerated.

    ALL-OR-NOTHING BY CONSTRUCTION: there is no try/except here and there must not be. A
    tenant session that raises takes the whole tick with it, because a reference set that
    is quietly missing one client's agents is a licence to delete that client's live packs
    — the one failure this module may not have. The retry ladder in `sweep_knowledge_packs`
    is what turns that into a deferral instead of a loss.

    One `tenant_session` per organization, which is `apply_retention`'s fleet shape and is
    affordable at a daily cadence: `agents` has no cross-tenant read anywhere in this
    repository and this sweep is not the place to grant the first one (hard rule 1 —
    `kb/orphans._claims` is the exception, and it exists only because `engine_kb_routes`
    was given an explicit RLS exemption in its own migration for an account that is
    genuinely shared).
    """
    async with admin_session() as session:
        tenant_ids = [UUID(str(row[0])) for row in await session.execute(text(_DIRECTORY_SQL))]

    references: set[tuple[UUID, UUID, str]] = set()
    for tenant_id in tenant_ids:
        async with tenant_session(tenant_id) as session:
            rows = await session.execute(text(_POINTERS_SQL))
            references |= {(tenant_id, UUID(str(aid)), str(digest)) for aid, digest in rows}
    return references, set(tenant_ids)


async def _sweep() -> str:
    # THE LISTING IS TAKEN FIRST, and the order is load-bearing — see the module docstring.
    # Every object below existed before every pointer read after it, so a pointer that
    # commits during this function protects its object rather than missing it.
    objects = await objects_under(PACK_OBJECT_PREFIX)
    references, known_tenants = await fleet_pack_references()
    plan = plan_pack_collection(
        objects, references=references, known_tenants=known_tenants, now=datetime.now(UTC)
    )

    doomed = plan.collect[:MAX_DELETIONS_PER_TICK]
    deleted = await delete_objects(doomed)
    log.info(
        "knowledge_pack_gc",
        extra={
            "listed": len(objects),
            "referenced": plan.referenced,
            "too_new": plan.too_new,
            "unattributable": len(plan.unattributable),
            "deleted": deleted,
            "deferred": plan.deferred,
        },
    )

    if plan.unattributable:
        alert(
            # WORKER_STALL for `sweep_kb_orphans`' reason: the enum answers "where in the
            # pipeline did this die", and this is a scheduled sweep reporting a bad state
            # of the world rather than a worker dying.
            "WORKER_STALL",
            "knowledge_pack_residue_unattributable",
            detail=(
                f"{len(plan.unattributable)} object(s) under knowledge-packs/ name no "
                "tenant this platform can enumerate, or are not keys this platform wrote. "
                "Nothing has been deleted: this sweep only removes packs it can positively "
                "attribute to a live tenant, so these will accumulate until somebody looks"
            ),
        )
    return f"listed={len(objects)} deleted={deleted} deferred={plan.deferred}"


async def sweep_knowledge_packs(ctx: dict[str, Any]) -> str:
    """THE JOB. One prefix listing, scored against every live pointer in the fleet.

    IDEMPOTENT AND KEYED: it writes no row, and the objects it removes are
    content-addressed and write-once, so a second run over the same state finds the same
    objects already gone and deletes nothing. The cron's own arq id dedupes two workers
    racing one tick.

    THE RETRY LADDER is `sweep_kb_orphans`', for a sharper reason. arq retries for
    `arq.Retry` and nothing else, and the two failures this job is most likely to suffer —
    a store listing that times out, and a tenant session that cannot be opened — are
    exactly the ones that must not be allowed to mean "nothing reclaimed until tomorrow"
    AND must not be allowed to mean "collect against a partial reference set". Both abort
    before any delete, so a retry is free and a give-up costs only space.
    """
    try:
        return await _sweep()
    except Exception as exc:
        log.warning(
            "knowledge_pack_gc_failed",
            extra={"reason": exc.__class__.__name__, "attempt": ctx.get("job_try")},
        )
        attempt = int(ctx.get("job_try", 1) or 1)
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=30 * attempt) from exc
        alert(
            "WORKER_TERMINAL",
            "knowledge_pack_gc_abandoned",
            detail=(
                f"{exc.__class__.__name__} after {attempt} attempt(s); superseded in-call "
                "knowledge packs are not being reclaimed and the prefix grows by one "
                "object per publish per agent until this runs again. Nothing has been "
                "deleted and no agent has lost its knowledge — the sweep aborts before "
                "its first delete on any failure"
            ),
        )
        raise


__all__ = [
    "MAX_DELETIONS_PER_TICK",
    "PACK_GC_HOUR",
    "PACK_GC_MINUTE",
    "PACK_GRACE_S",
    "PackGcPlan",
    "fleet_pack_references",
    "plan_pack_collection",
    "sweep_knowledge_packs",
]
