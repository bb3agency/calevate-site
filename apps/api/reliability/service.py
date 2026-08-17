"""The reliability triad (BACKEND-PATTERNS §4) + the CAS primitive (§5).

Three mechanisms, one idea: **at-least-once delivery plus idempotent consumers is
effectively exactly-once**, and every claim is a conditional UPDATE whose `rowcount ==
0` means "another worker won" — never an exception, never a lock held across a
network call.

- **Idempotency** guards client-initiated mutations (call-this-lead, campaign launch,
  KB publish): the same key replays the stored response instead of dialling twice.
- **Outbox** makes side effects survive a crash: the row is written in the SAME
  transaction as the domain write, so "lead created but notification lost" cannot
  happen. A separate dispatcher publishes it.
- **Inbox** dedupes provider events. Bolna webhooks are at-most-once and unsigned
  (D-31), so this is where an execution_id becomes a single unit of work.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from apps.api.core.alerting import alert, record_outbox_dlq_depth, record_outbox_lag
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings, resolve_hmac_key
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of

log = get_logger(__name__)

IDEMPOTENCY_TTL = timedelta(hours=24)
OUTBOX_MAX_ATTEMPTS = 5
OUTBOX_BATCH = 50

# How long a PROCESSING claim may go untouched before it is treated as ABANDONED
# rather than in-flight.
#
# Both claim tables have a state that means "someone is working on this": a crash
# between the claim and its completion leaves that state behind with nobody behind it,
# and without a lease it is permanent — 24h for an idempotency key (until the TTL
# sweep), forever for an inbox row. The client retrying gets `409 in flight` for a
# request that is not in flight, and an at-most-once engine event is answered
# "duplicate" and never processed.
#
# The number is the longest a legitimate holder can live: ARQ's `job_timeout` is 300s
# (apps/workers/settings.py) and an API request dies long before that, so ten minutes
# of silence cannot be an attempt that is still running. Past it the claim is taken
# over by CAS — the same treatment §4 already prescribes for a FAILED record, applied
# to the case where the holder never got far enough to record its own failure.
CLAIM_LEASE = timedelta(minutes=10)

# The outbox's own lease — the same doctrine, a different unit of work, so a different
# number (migration 7c04ab5f9e26).
#
# A claimed outbox row is held for exactly as long as it takes to hand one job to Redis
# and write one status row: milliseconds. Two minutes is roughly a thousand times the
# p99, so a lease cannot lapse under a dispatcher that is merely slow — while still
# returning an ABANDONED message to the queue well inside the outbox-lag SLO, which the
# ten-minute `CLAIM_LEASE` would not.
#
# What happens if it lapses under a live dispatcher anyway: the row is claimed a second
# time and the job is enqueued twice with the SAME `job_id_for(job, message.id)`, which
# ARQ dedupes. The lease is a liveness mechanism, not the exactly-once one.
OUTBOX_CLAIM_LEASE = timedelta(minutes=2)


def body_hash(payload: Any) -> str:
    """Stable hash of a request/event body. Sorted keys so key order is not a
    'different request'."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def scope_key(*, tenant_id: UUID | None, user_id: UUID | None) -> str:
    """HMAC fingerprint of tenant/user — RAW IDS ARE NEVER STORED in the idempotency
    table (§4). Two tenants sending the same Idempotency-Key stay independent.

    IS A GUESSABLE FINGERPRINT A FORGERY PROBLEM? No, and the reason is worth recording
    because the shape invites the opposite conclusion. `scope` is never accepted from
    the wire: both call sites (`crm/routes.py`) derive it from `principal.tenant_id` /
    `principal.user_id`, which come from a verified token. So an attacker who can
    PREDICT another tenant's fingerprint still has no way to SUBMIT it, and cannot
    collide with their idempotent write. The uniqueness constraint is reached only
    through a value the server computed for the authenticated caller.

    WHAT A GUESSABLE KEY DID COST is the pseudonymity, which is the only reason this is
    an HMAC and not `f"{tenant_id}:{user_id}"`. §4 forbids storing the raw ids; a keyed
    hash is a pseudonym only while the key is secret, because an identifier space that
    someone holding the database can enumerate is an identifier space they can hash and
    match (EDPS/AEPD, "Introduction to the hash function as a personal data
    pseudonymisation technique" — the fix for a reversible plain hash is to enlarge the
    preimage space with a secret key, which is what HMAC is doing here). With the old
    `local-dev:{app_env}` fallback in force, this column was a rename of two ids rather
    than a pseudonym for them.

    ITS OWN SECRET, no longer the audit chain's — `calevate_shared.config` carries the
    argument. The short version is that this value must be STABLE (changing it makes
    every in-flight Idempotency-Key miss its record, so a retry re-executes: a second
    real phone call for `POST /v1/leads/{id}/call`) while the audit chain's key is the
    one that now has a rotation story. Sharing meant an audit rotation silently placed
    duplicate calls.
    """
    settings = get_settings()
    material = resolve_hmac_key(
        settings.idempotency_scope_secret,
        env_var="IDEMPOTENCY_SCOPE_SECRET",
        purpose="idempotency scope fingerprints",
        code="idempotency_not_configured",
        title="Idempotent requests are not configured",
        local_fallback=f"calevate-local-dev-idempotency-scope-key:{settings.app_env}",
        app_env=settings.app_env,
    )
    return hmac.new(material, f"{tenant_id}:{user_id}".encode(), hashlib.sha256).hexdigest()


# --- Idempotency --------------------------------------------------------------

IdempotencyState = Literal["fresh", "replay"]


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    state: IdempotencyState
    record_id: UUID
    response_status: int | None = None
    response_payload: dict[str, Any] | None = None


async def claim_idempotency(
    session: AsyncSession,
    *,
    scope: str,
    route: str,
    method: str,
    key: str,
    request_hash: str,
) -> IdempotencyClaim:
    """Returns `fresh` (caller does the work) or `replay` (caller returns the stored
    response with `Idempotent-Replayed: true`).

    409s, both deliberate:
    - same key + DIFFERENT body → the client reused a key for a new request;
    - status PROCESSING and claimed within `CLAIM_LEASE` → genuinely still in flight.

    A FAILED record, or a PROCESSING one whose holder has been silent for longer than
    the lease, is re-claimed by CAS: a crashed attempt must not own the key until the
    TTL sweep.
    """
    record_id = uuid7()
    inserted = await session.execute(
        text(
            "INSERT INTO idempotency_records (id, scope_key, route, method, idempotency_key, "
            "request_hash, status, expires_at, created_at, updated_at) "
            "VALUES (:id, :scope, :route, :method, :key, :hash, 'processing', :expires, "
            "now(), now()) "
            "ON CONFLICT (scope_key, route, method, idempotency_key) DO NOTHING "
            "RETURNING id"
        ),
        {
            "id": record_id,
            "scope": scope,
            "route": route,
            "method": method,
            "key": key,
            "hash": request_hash,
            "expires": datetime.now(UTC) + IDEMPOTENCY_TTL,
        },
    )
    if inserted.first() is not None:
        return IdempotencyClaim(state="fresh", record_id=record_id)

    existing = (
        await session.execute(
            text(
                "SELECT id, request_hash, status, response_status, response_payload "
                "FROM idempotency_records WHERE scope_key = :scope AND route = :route "
                "AND method = :method AND idempotency_key = :key"
            ),
            {"scope": scope, "route": route, "method": method, "key": key},
        )
    ).first()
    if existing is None:  # pragma: no cover — TTL sweep raced the conflict
        return IdempotencyClaim(state="fresh", record_id=record_id)

    found_id, found_hash, status, response_status, response_payload = existing
    if found_hash != request_hash:
        raise ProblemError.conflict(
            "idempotency_key_reused",
            "This Idempotency-Key was already used for a different request body.",
            remediation="Use a fresh key for a new request.",
        )
    if status in ("processing", "failed"):
        # CAS the record back to processing; whoever wins retries.
        #
        # FAILED is the easy case: the previous attempt recorded its own defeat. A
        # PROCESSING record OLDER THAN THE LEASE is the same situation seen from the
        # other side — the attempt died before it could record anything — and it must
        # be recoverable for the same reason: otherwise one crashed request owns the
        # key until the 24h TTL sweep and every retry is refused as "in flight".
        # A recent PROCESSING record really is in flight and still gets its 409.
        retried = await session.execute(
            text(
                "UPDATE idempotency_records SET status = 'processing', updated_at = now() "
                "WHERE id = :id AND (status = 'failed' OR "
                "(status = 'processing' AND updated_at < now() - :lease))"
            ),
            {"id": found_id, "lease": CLAIM_LEASE},
        )
        if rowcount_of(retried) == 0:
            raise ProblemError(
                kind="conflict",
                code="idempotent_request_in_flight",
                title="Request already in progress",
                detail="An identical request is still being processed.",
                remediation="Retry in a few seconds.",
                headers={"Retry-After": "3"},
            )
        return IdempotencyClaim(state="fresh", record_id=found_id)

    return IdempotencyClaim(
        state="replay",
        record_id=found_id,
        response_status=response_status,
        response_payload=response_payload,
    )


async def complete_idempotency(
    session: AsyncSession,
    *,
    record_id: UUID,
    response_status: int,
    response_payload: dict[str, Any],
) -> None:
    await session.execute(
        text(
            "UPDATE idempotency_records SET status = 'completed', response_status = :status, "
            "response_payload = CAST(:payload AS jsonb), updated_at = now() WHERE id = :id"
        ),
        {"id": record_id, "status": response_status, "payload": json.dumps(response_payload)},
    )


async def fail_idempotency(session: AsyncSession, *, record_id: UUID) -> None:
    await session.execute(
        text("UPDATE idempotency_records SET status = 'failed', updated_at = now() WHERE id = :id"),
        {"id": record_id},
    )


async def sweep_idempotency(session: AsyncSession) -> int:
    result = await session.execute(text("DELETE FROM idempotency_records WHERE expires_at < now()"))
    return int(rowcount_of(result) or 0)


# --- Outbox -------------------------------------------------------------------


#: The one worker fleet this deployment runs, written into `outbox_messages.queue`.
#:
#: THE PARAMETER THAT USED TO CHOOSE THIS IS GONE, and that is step 1 of a two-step
#: deprecation (hard rule 8), not a simplification (P6.8). Six call sites passed
#: `queue="notifications"` or `queue="default"`; the column is NOT NULL and
#: `claim_outbox_batch` selects it — and then `dispatch_outbox` published WITHOUT it and
#: `WorkerSettings` sets no `queue_name`, so every job landed on arq's single default
#: queue regardless. **It read as routing and routed nothing**, which is the shape that
#: makes an operator believe notifications are isolated from CRM deliveries when they are
#: sharing one worker's ten slots — a belief that costs most on the night it matters.
#:
#: It was also a SECOND ENCODING of a fact already on the row: every call site chose the
#: value as a pure function of `job`. So there was nothing to preserve.
#:
#: HONOURING IT WAS THE OTHER FORK AND IS DELIBERATELY NOT TAKEN TODAY. arq routes by
#: `enqueue_job(_queue_name=...)` consumed by a worker whose `WorkerSettings.queue_name`
#: matches, and one worker consumes exactly one queue — so honouring this column means a
#: SECOND DEPLOYABLE (container, deploy step, CI job) for a platform with no clients yet,
#: which ROADMAP §6 requires a decision for and CLAUDE.md's "monolith module before new
#: service" argues against. Worse, passing `_queue_name` today with no worker consuming
#: that queue would silently stop every notification. D-162 records the fork and names
#: what closes it: the column is dropped, or a second fleet arrives with a filter on it.
OUTBOX_FLEET = "default"


async def enqueue_outbox(
    session: AsyncSession,
    *,
    job: str,
    payload: dict[str, Any],
) -> UUID:
    """Write the side effect in the CALLER'S transaction. Do not commit here — the
    whole point is that this row and the domain write share a fate."""
    message_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO outbox_messages (id, queue, job, payload, status, attempt_count, "
            "created_at, updated_at) VALUES (:id, :queue, :job, CAST(:payload AS jsonb), "
            "'pending', 0, now(), now())"
        ),
        {"id": message_id, "queue": OUTBOX_FLEET, "job": job, "payload": json.dumps(payload)},
    )
    return message_id


async def enqueue_outbox_once(
    session: AsyncSession,
    *,
    job: str,
    payload: dict[str, Any],
    dedupe_key: str,
) -> UUID | None:
    """`enqueue_outbox`, but this exact side effect happens AT MOST ONCE, ever.

    Returns the new message id, or `None` if the promise was already on the books.

    WHAT THIS REPLACED, AND WHY THE REPLACEMENT IS STRONGER (P6.7). Three call sites used
    to ask `SELECT 1 FROM outbox_messages WHERE job = :job AND payload @> :matcher` and
    then insert if it came back empty. Two problems, and the cheap one is the visible one:

      * `outbox_messages` has no index on `job` and no GIN on `payload`, so every probe
        was a sequential scan of a table nothing prunes, and `LIMIT 1` does not help
        because the common case — no prior enqueue — reads every row before it can say so.
      * it is a check-then-write, correct only for as long as every caller remembers to
        hold `lock_call_writes` first. `ON CONFLICT DO NOTHING` against a UNIQUE index is
        correct without that, because the database is the one deciding.

    The lock stays where it is: it serializes the OTHER read-then-writes in the same
    transaction (`_meter`'s append-only ledger, the lead status flip), and this key is not
    a reason to remove it. What changed is that this promise no longer depends on it.

    THE KEY IS THE CALLER'S, and it must name the side effect rather than the row — a
    key containing a fresh uuid is a key that dedupes nothing. Existing keyspaces:
    `hot-lead:{lead_id}:{call_id}`, `hot-lead-whatsapp:{lead_id}:{call_id}`,
    `campaign-escalation:{contact_id}`. Prefix a new one so a reader of the column can
    tell what promised it.

    NOT FOR FAN-OUT. A side effect that legitimately writes several rows (the CRM fan-out
    writes one per subscribed endpoint) uses `enqueue_outbox` and answers "already done?"
    from its own domain row — `calls.crm_notified_at` is that answer for the CRM path.
    """
    message_id = uuid7()
    row = (
        await session.execute(
            text(
                "INSERT INTO outbox_messages (id, queue, job, payload, dedupe_key, status, "
                "attempt_count, created_at, updated_at) VALUES (:id, :queue, :job, "
                "CAST(:payload AS jsonb), :dedupe_key, 'pending', 0, now(), now()) "
                # The conflict target is the PARTIAL index, so it must be spelled as the
                # same predicate: naming the column alone does not match a partial index
                # and Postgres answers with "no unique or exclusion constraint matching
                # the ON CONFLICT specification"
                # (postgresql.org/docs/16/sql-insert.html#SQL-ON-CONFLICT).
                "ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING "
                "RETURNING id"
            ),
            {
                "id": message_id,
                "queue": OUTBOX_FLEET,
                "job": job,
                "payload": json.dumps(payload),
                "dedupe_key": dedupe_key,
            },
        )
    ).first()
    return message_id if row is not None else None


@dataclass(frozen=True, slots=True)
class OutboxMessageRow:
    id: UUID
    #: Always `OUTBOX_FLEET`, and READ BY NOTHING — `dispatch_outbox` never branches on
    #: it. Carried here rather than dropped from the claim so the column's one consumer
    #: is where a filter would go on the day D-162 closes by growing a second fleet; if
    #: it closes the other way, this field and the column go in the same change. A reader
    #: meeting `row.queue` and assuming it decides where the job runs is the exact
    #: misreading the column's comment in `models.py` exists to prevent.
    queue: str
    job: str
    payload: dict[str, Any]
    attempt_count: int


def _claim_engine(session: AsyncSession) -> AsyncEngine:
    """The engine the caller's session is bound to.

    `claim_outbox_batch` cannot run inside the caller's transaction (see its docstring),
    so it needs a second connection — and it must come from the SAME engine, or a test
    that binds its own would have its claim land in a different database than its
    assertions.
    """
    bind = session.bind
    return bind if isinstance(bind, AsyncEngine) else bind.engine


async def claim_outbox_batch(
    session: AsyncSession, *, limit: int = OUTBOX_BATCH
) -> list[OutboxMessageRow]:
    """Oldest-first claim by conditional UPDATE, **committed on its own connection**.

    The commit is the point, and it is why `session` is used only for its engine. The
    claim's whole job is to record, DURABLY, that this message has now been attempted:

        the bump used to live in the dispatcher's transaction, which does not commit
        until after the publish. A SIGKILL there rolled it back with everything else and
        the row returned to `pending` with `attempt_count = 0` — so a message whose
        payload is what kills the worker looped forever on a retry budget that reset
        every pass, and the DLQ this function's docstring promised was unreachable.

    An uncommitted write is not durable; there is no version of this that does not
    commit. But committing the bump ALONE would be a different bug: the commit drops the
    `FOR UPDATE` locks, and while the row still says `pending` those locks are the only
    thing making the claim exclusive. So the same statement that commits the bump also
    writes the lease. After the commit, exclusivity is carried by `locked_until` — a
    durable fact on the row — instead of by a lock that dies with the process holding it.
    `FOR UPDATE SKIP LOCKED` still does its job for the window BEFORE the commit, where
    two dispatchers' claim statements overlap.

    A lapsed lease needs no reaper: the next tick's claim query selects the row again,
    with its `attempt_count` where the dead worker left it, which is exactly how a poison
    message now walks to the DLQ instead of looping. `_dead_letter_exhausted_claims`
    below is the last step of that walk.

    MATERIALIZED + a tiebreak on `id` for the same reason as the campaign dispatcher's
    claim: `WHERE id IN (SELECT ... LIMIT :n FOR UPDATE SKIP LOCKED)` lets the planner
    rescan the LIMIT subquery per candidate row, and outbox rows enqueued in one
    transaction share `created_at` to the microsecond — so each rescan breaks the tie
    differently and the batch comes back larger than `limit`. Here that is a latency
    spike rather than corruption, but `limit` should mean what it says.
    """
    engine = _claim_engine(session)
    async with engine.begin() as conn:
        await _dead_letter_exhausted_claims(conn)
        rows = (
            await conn.execute(
                text(
                    "WITH picked AS MATERIALIZED ("
                    "  SELECT id FROM outbox_messages WHERE status = 'pending' "
                    "  AND (locked_until IS NULL OR locked_until <= now()) "
                    "  ORDER BY created_at, id LIMIT :limit FOR UPDATE SKIP LOCKED"
                    ") "
                    "UPDATE outbox_messages o SET attempt_count = o.attempt_count + 1, "
                    "locked_until = now() + :lease, updated_at = now() FROM picked "
                    "WHERE o.id = picked.id "
                    "RETURNING o.id, o.queue, o.job, o.payload, o.attempt_count"
                ),
                {"limit": limit, "lease": OUTBOX_CLAIM_LEASE},
            )
        ).all()
    return [
        OutboxMessageRow(id=r[0], queue=r[1], job=r[2], payload=r[3] or {}, attempt_count=r[4])
        for r in rows
    ]


async def _dead_letter_exhausted_claims(conn: AsyncConnection) -> None:
    """Retire messages that spent the whole budget without ever reporting an outcome.

    `mark_outbox_failed` is the only other route to the DLQ, and it is a route only a
    worker that SURVIVED its attempt can take. A message that kills its dispatcher never
    reports anything, so before the lease existed it looped, and with the lease alone it
    would loop more slowly and with an ever-growing `attempt_count`. This closes it: a
    row whose lease has lapsed and whose attempts are spent is a dead letter, and saying
    so is what makes "walks to the DLQ" true rather than aspirational.

    Only unleased rows are eligible, so a dispatcher still working on its final attempt
    is never retired out from under itself. `last_error` is preserved when there is one —
    a real error from a previous try explains more than this note does.
    """
    retired = (
        await conn.execute(
            text(
                "UPDATE outbox_messages SET status = 'failed', locked_until = NULL, "
                "last_error = COALESCE(last_error, :note), updated_at = now() "
                "WHERE status = 'pending' AND attempt_count >= :max "
                "AND (locked_until IS NULL OR locked_until <= now()) "
                "RETURNING id"
            ),
            {"max": OUTBOX_MAX_ATTEMPTS, "note": "claim abandoned; budget spent with no outcome"},
        )
    ).all()
    if retired:
        # One alert for the tick, not one per row: a dispatcher crash-looping on a bad
        # batch would otherwise page ops fifty times about one incident.
        alert(
            "OUTBOX_DISPATCH",
            "outbox_dead_letter",
            detail=f"{len(retired)} abandoned claim(s) exhausted their attempt budget",
        )


async def mark_outbox_published(session: AsyncSession, *, message_id: UUID, job_id: str) -> None:
    # `locked_until = NULL` on every terminal transition, so a non-null lease means
    # "claimed right now, or abandoned" and never "resolved a while ago".
    await session.execute(
        text(
            "UPDATE outbox_messages SET status = 'published', job_id = :job_id, "
            "published_at = now(), locked_until = NULL, updated_at = now() "
            "WHERE id = :id AND status = 'pending'"
        ),
        {"id": message_id, "job_id": job_id},
    )


# How long a message waits before its next attempt, per attempt already spent. The shape
# is the same real backoff `pipeline.RETRY_BACKOFF_S` and `outbound_webhooks.
# RETRY_BACKOFF_S` use, and the numbers are sized against THIS loop's tick rather than
# against a worker's.
#
# The dispatcher runs every 10 seconds, so an unheld budget of five attempts is spent in
# 50 seconds — less than a Redis restart. Linear on the attempt count and capped, the
# budget covers 30+60+90+120 = five minutes of a receiver being away before the message is
# dead-lettered, which is the difference between "a blip" and "an operator has to replay
# the outbox by hand".
#
# **ONE BACKOFF, BOTH FAILURE KINDS, and the name says so.** These shipped as
# `OUTBOX_SYSTEMIC_BACKOFF_*` because `defer_outbox_claim` was the only caller: a queue
# outage got a wait and a message whose own publish failed got none, so it burned five
# attempts in fifty seconds against a receiver that was merely restarting. The two cases
# still differ in the way that matters — a systemic failure does not COUNT against the
# poison budget and a per-message one does — but "how long to wait before trying again"
# is one question and had no business having two answers, one of them zero.
OUTBOX_RETRY_BACKOFF_S = 30
OUTBOX_RETRY_BACKOFF_CAP_S = 300

# The wait, as SQL, spelled once. Both writers below interpolate this rather than
# repeating `make_interval`, so the two branches cannot drift into different curves —
# which is exactly how the per-message branch came to have no curve at all.
#
# `GREATEST(attempt_count, 1)` because `claim_outbox_batch` has already bumped the
# counter by the time either caller runs, so the first failure is attempt 1 and waits one
# base interval rather than none.
_BACKOFF_INTERVAL_SQL = (
    "make_interval(secs => LEAST(:backoff_base * GREATEST(attempt_count, 1), :backoff_cap))"
)

_BACKOFF_PARAMS = {
    "backoff_base": OUTBOX_RETRY_BACKOFF_S,
    "backoff_cap": OUTBOX_RETRY_BACKOFF_CAP_S,
}


async def mark_outbox_failed(
    session: AsyncSession, *, message_id: UUID, error: str, attempt_count: int
) -> None:
    """< OUTBOX_MAX_ATTEMPTS stays pending (retried after a backoff); at the ceiling it
    goes to `failed` — the outbox DLQ — and alerts. Ops replays a DLQ row by flipping it
    back to pending with an audit note.

    `AND status = 'pending'` is the CAS guard (§5), and it is load-bearing rather than
    decorative: without it a late failure report drags a message that has ALREADY been
    published back to pending, and the next dispatcher tick queues its job a second
    time. For `deliver_outbound_webhook` that is a duplicate POST into a client's CRM.
    The alert fires only when the row actually moved, so a lost race cannot page ops
    about a dead letter that does not exist.

    **THE RETRY BRANCH HOLDS THE MESSAGE, and this is the half that was missing.** It
    used to write `locked_until = NULL` on both branches, on the argument that a message
    returned to `pending` while still holding its two-minute claim lease would stall for
    the whole lease. That argument was right about the LEASE and wrong about the
    conclusion: releasing the claim and scheduling the next attempt are different acts,
    and doing the first alone made the next attempt immediate. A message whose receiver
    is restarting was then re-tried on the very next 10-second tick and spent its whole
    five-attempt budget in fifty seconds — the identical failure `defer_outbox_claim`
    exists to prevent, one message at a time instead of a batch at a time.

    So the lease is REPLACED rather than cleared: `locked_until` moves to the backoff,
    which is shorter than the claim lease at the first attempt and longer later, and
    `claim_outbox_batch` already skips rows whose `locked_until` is in the future. The
    two uses of one visibility timestamp are the established shape here and in every
    Postgres-backed queue (`defer_outbox_claim` cites them).

    The TERMINAL branch still clears it, and must: `locked_until = NULL` on every
    terminal transition is what lets a non-null lease mean "claimed right now, or
    abandoned" and never "resolved a while ago" — and a dead letter holding a lease would
    be invisible to `replay_dead_letters`' successor if that ever grew a liveness check.
    """
    terminal = attempt_count >= OUTBOX_MAX_ATTEMPTS
    result = await session.execute(
        text(
            "UPDATE outbox_messages SET status = :status, last_error = :error, "
            # NULL when terminal, the backoff when there is budget left. Written as one
            # CASE rather than two statements so the status and the wait can never
            # disagree about which branch this is.
            "locked_until = CASE WHEN :terminal THEN NULL "
            f"ELSE now() + {_BACKOFF_INTERVAL_SQL} END, "
            "updated_at = now() WHERE id = :id AND status = 'pending'"
        ),
        {
            "id": message_id,
            "status": "failed" if terminal else "pending",
            "terminal": terminal,
            "error": error[:500],
            **_BACKOFF_PARAMS,
        },
    )
    if terminal and rowcount_of(result):
        alert(
            "OUTBOX_DISPATCH",
            "outbox_dead_letter",
            detail=error[:200],
            message_id=str(message_id),
        )


async def defer_outbox_claim(session: AsyncSession, *, message_ids: list[UUID], error: str) -> int:
    """Hand claimed messages back to the queue, held off for a backoff — no status move.

    THE FAILURE THIS SEPARATES OUT. `mark_outbox_failed` counts a publish failure against
    the MESSAGE's poison budget, which is right when the message is what failed and wrong
    when the QUEUE is: a Redis restart makes every row in the batch fail identically, and
    at a 10-second tick with five attempts the entire outbox is dead-lettered in under a
    minute. Nothing was ever wrong with those messages, and recovering them costs a
    step-up-confirmed operator replay (`ops/routes.py::replay_outbox`).

    So a systemic failure gets a WAIT instead of a verdict. The attempt the claim already
    charged still stands — an uncommitted attempt is how a poison message loops forever,
    which `claim_outbox_batch` argues at length — but the next one is not spent ten
    seconds later.

    `locked_until` carries the wait, and that is the established shape rather than a new
    column: a single visibility timestamp doing double duty as lease and as retry
    backoff is how Postgres-backed queues do it (SQS's ChangeMessageVisibility is the
    same primitive, and `river`, `pgmq` and `graphile-worker` all schedule a retry by
    pushing one `visible_at`/`scheduled_at` column forward). `claim_outbox_batch` already
    skips rows whose `locked_until` is in the future, so nothing downstream changes.

    `AND status = 'pending'` is the CAS guard (§5): a message another dispatcher
    published while this batch was failing must not be pulled back under a lease.
    """
    if not message_ids:
        return 0
    result = await session.execute(
        text(
            "UPDATE outbox_messages SET "
            f"locked_until = now() + {_BACKOFF_INTERVAL_SQL}, "
            "last_error = :error, updated_at = now() "
            "WHERE id = ANY(:ids) AND status = 'pending'"
        ),
        {"ids": message_ids, "error": error[:500], **_BACKOFF_PARAMS},
    )
    return int(rowcount_of(result) or 0)


@dataclass(frozen=True, slots=True)
class DeadLetterJobDepth:
    """One `job`'s share of the dead-letter queue."""

    job: str
    depth: int
    # The oldest dead letter OF THIS JOB. Age is the cheapest signal of what a replay
    # actually does: re-sending a ten-minute-old webhook is a retry, and re-sending a
    # week-old one is a client's CRM receiving a lead they have already worked.
    oldest_created_at: datetime


@dataclass(frozen=True, slots=True)
class DeadLetterQueue:
    """How deep the outbox DLQ is, what is in it, how old the head of it is — and how
    many messages are neither published nor dead but WAITING.

    COUNTS AND JOB NAMES ONLY, and that is a hard-rule-6 boundary rather than an
    omission: `outbox_messages.payload` is JSONB carrying lead fields, phone numbers and
    extraction output, so nothing derived from it may leave this function. `job` is an
    ARQ job name — a code identifier, fixed at enqueue — and a count is a count.
    """

    depth: int
    # None exactly when `depth` is 0. Not folded into a sentinel time: "the queue is
    # empty" and "the oldest is the epoch" are different facts and a caller must not have
    # to know which one a magic value means.
    oldest_created_at: datetime | None
    by_job: tuple[DeadLetterJobDepth, ...]
    # THE OUTBOX'S THIRD STATE, and the one an operator used to be unable to see.
    #
    # `defer_outbox_claim` hands a batch back with `locked_until` in the future when the
    # QUEUE failed rather than the message — so during a Redis outage the backlog grows
    # as `pending`-with-a-future-lease and `depth` stays honestly at zero. The console
    # published only `depth`, which meant it truthfully reported "no dead letters" for
    # the whole five minutes of tolerated downtime that `OUTBOX_RETRY_BACKOFF_S`
    # buys — and an operator looking at it mid-incident read "nothing is wrong". The
    # backoff made the outage survivable and simultaneously made it invisible.
    #
    # Counted rather than broken down by job on purpose: a systemic deferral hits every
    # job in the batch identically, so a per-job split of it would be a breakdown of
    # which jobs happened to be in the outbox, not of what is wrong. `by_job` stays what
    # it has always been — the DLQ's composition, which is what sizes a replay.
    deferred: int


async def read_dead_letter_queue(session: AsyncSession) -> DeadLetterQueue:
    """THE definition of "how deep is the DLQ" — one query, one instant, two readers.

    `record_outbox_metrics` publishes `depth` as the `outbox_dlq_depth` metric and
    `GET /v1/ops/platform` publishes the whole thing to the console, so the number an
    operator sees before confirming a replay and the number the alert fires on are the
    same number by construction. The metric used to run its own `count(*)` here; a second
    definition of a queue's depth is the kind of duplication that is correct on the day it
    is written and disagrees the first time either side grows a predicate.

    ONE GROUPED AGGREGATE, not a `count(*)` plus a `GROUP BY`. The total is the sum of the
    parts rather than a separately measured number, so a dispatcher tick landing between
    two statements cannot publish a breakdown that does not add up to its own total — the
    same one-instant argument `read_halt_state` makes for the halt and its reason, applied
    inside one payload rather than across two rows.

    The scan covers `failed` plus the DEFERRED slice of `pending`, both of which
    `ix_outbox_pending (status, created_at)` serves, and grouping adds a sort over rows
    the DLQ-depth alert exists to keep few. It is not free on the dispatcher's 10-second
    tick, and it is still the right trade: a marginally cheaper metric query that can
    drift from the operator's readout is the more expensive of the two.

    **THE DEFERRED COUNT RIDES THE SAME AGGREGATE, and that is the whole reason it is
    here rather than in a second function.** A `deferred` measured by its own statement
    could be read a tick later than `depth`, and the two numbers exist precisely to be
    read against each other: "0 dead, 214 deferred" is a queue outage in progress and
    "214 dead, 0 deferred" is one that already burned through the budget. Two instants
    can spell the first as the second. `now()` is a single value for the whole statement
    (it is the transaction timestamp), so "in the future" means the same instant for
    every row it classifies.
    """
    rows = (
        await session.execute(
            text(
                "SELECT job, "
                "count(*) FILTER (WHERE status = 'failed') AS depth, "
                "min(created_at) FILTER (WHERE status = 'failed') AS oldest, "
                "count(*) FILTER (WHERE status = 'pending') AS deferred "
                "FROM outbox_messages "
                # A deferred message is a PENDING one holding a lease into the future.
                # That is also what a claimed, in-flight message looks like for the
                # milliseconds a dispatcher holds it, and the overlap is accepted rather
                # than papered over: there is no column that tells a two-minute
                # `OUTBOX_CLAIM_LEASE` apart from a 30-second backoff, both being one
                # `locked_until` by deliberate design (`defer_outbox_claim` argues why).
                # An idle system therefore reads 0 and a system in trouble reads the
                # backlog; a healthy busy one can read a handful. Adding a column to
                # disambiguate would buy precision on a number nobody alerts on, at the
                # cost of a migration on the hot dispatch path.
                "WHERE status = 'failed' "
                "OR (status = 'pending' AND locked_until IS NOT NULL AND locked_until > now()) "
                # Biggest first — an operator sizing a replay reads the largest share
                # first — then by name so equal shares render in a stable order rather
                # than shuffling between polls. Ordered on the DLQ share specifically:
                # this ordering exists to rank `by_job`, which is dead letters only.
                "GROUP BY job ORDER BY count(*) FILTER (WHERE status = 'failed') DESC, job"
            )
        )
    ).all()
    by_job = tuple(
        DeadLetterJobDepth(job=row[0], depth=int(row[1]), oldest_created_at=row[2])
        for row in rows
        # A job with ONLY deferred messages has no share of the DLQ, and listing it at
        # depth 0 with a null `oldest_at` would put a job on the replay breakdown that a
        # replay would not touch. `DeadLetterJobDepth.oldest_created_at` is non-optional
        # for the same reason: there is no such thing as the oldest of nothing.
        if int(row[1]) > 0
    )
    return DeadLetterQueue(
        depth=sum(entry.depth for entry in by_job),
        oldest_created_at=min((entry.oldest_created_at for entry in by_job), default=None),
        by_job=by_job,
        deferred=sum(int(row[3]) for row in rows),
    )


async def record_outbox_metrics(session: AsyncSession) -> None:
    row = (
        await session.execute(
            text(
                "SELECT COALESCE(EXTRACT(EPOCH FROM (now() - MIN(created_at))), 0) "
                "FROM outbox_messages WHERE status = 'pending'"
            )
        )
    ).first()
    record_outbox_lag(float(row[0]) if row else 0.0)
    # The metric reads the SAME aggregate the ops console does — see
    # `read_dead_letter_queue` on why this is not a local `count(*)` any more.
    record_outbox_dlq_depth((await read_dead_letter_queue(session)).depth)


async def replay_dead_letters(
    session: AsyncSession, *, job: str | None = None, limit: int = 100
) -> int:
    """The ops "replay dead letter" action. Attempts reset so the message gets a fresh
    budget; the caller writes the audit note.

    `job` scopes the run to one kind of side effect; `None` means every job, which is what
    this function has always done and still does. The scope is a bound on the blast
    radius, and the LIMIT is why it is worth having rather than a nicety: 100 OLDEST rows
    across every job means a flood of dead-lettered emails can consume the whole run while
    the CRM webhooks an operator came to recover stay parked, and the operator reads
    `replayed: 100` as success. Scoping makes "replay the thing I am here about" reachable
    in one act instead of N runs of the wrong one.

    ONE definition of replay, not two: the scope is a predicate inside the same statement,
    so the ordering, the claim and the CAS guard below are identical whether or not it is
    set. A separate `replay_one_job` would be the second definition, and the first time
    the guard changed only one of them would get it.

    Claimed exactly like `claim_outbox_batch`, and for the same three reasons:

    - **MATERIALIZED + `ORDER BY created_at, id`** — dead letters written by one batch
      share `created_at` to the microsecond, and `LIMIT` inside `WHERE id IN (SELECT
      ...)` is only honoured while the planner does not rescan the subquery. A total
      ordering plus a materialized CTE makes `limit` mean `limit` under every plan.
    - **`FOR UPDATE SKIP LOCKED`** — two operators clicking replay, or a replay racing
      the dispatcher, must not fight over the same rows.
    - **`AND o.status = 'failed'` on the UPDATE itself** — the subquery's filter is not
      a guard. Under READ COMMITTED the outer UPDATE blocks on a concurrent writer's
      lock and, on waking, re-checks only its OWN WHERE clause; without the status in
      it, a message that was dead when the CTE ran and published by the time the lock
      was granted is flipped back to pending and delivered twice.

    The `job` predicate deliberately does NOT get the same treatment, and the asymmetry is
    the point: `status` is re-checked on the outer UPDATE because it CHANGES under us —
    `mark_outbox_published` and the dispatcher both write it — while `job` is written once
    by `enqueue_outbox` and by no UPDATE anywhere in this codebase. Repeating an immutable
    predicate would imply it can move and teach the next reader the wrong lesson about
    which columns need a CAS.

    The cast is not decoration: an untyped NULL parameter leaves Postgres unable to infer
    the type of `:job` in `IS NULL` and the statement fails to prepare
    (postgresql.org/docs/16/typeconv-func.html — parameter types are resolved before
    execution, and a bare `NULL` has none).
    """
    result = await session.execute(
        text(
            "WITH picked AS MATERIALIZED ("
            "  SELECT id FROM outbox_messages WHERE status = 'failed' "
            "  AND (CAST(:job AS text) IS NULL OR job = CAST(:job AS text)) "
            "  ORDER BY created_at, id LIMIT :limit FOR UPDATE SKIP LOCKED"
            ") "
            "UPDATE outbox_messages o SET status = 'pending', attempt_count = 0, "
            "locked_until = NULL, updated_at = now() FROM picked "
            "WHERE o.id = picked.id AND o.status = 'failed'"
        ),
        {"limit": limit, "job": job},
    )
    return int(rowcount_of(result) or 0)


# --- Webhook inbox ------------------------------------------------------------

InboxState = Literal["claimed", "duplicate"]


@dataclass(frozen=True, slots=True)
class InboxClaim:
    state: InboxState
    row_id: UUID


async def claim_inbox_event(
    session: AsyncSession,
    *,
    provider: str,
    event_key: str,
    payload_hash: str,
    event_name: str | None = None,
) -> InboxClaim:
    """Durable dedupe. Same (provider, event_key) with a DIFFERENT payload_hash is a
    409 — that is a spoof or corruption signal, not a retry (§4).

    A previously FAILED row — or a PROCESSING row abandoned for longer than
    `CLAIM_LEASE` — is re-claimable via CAS: engine events are at-most-once, so
    neither a failed nor a crashed processing attempt may permanently poison the key.
    """
    row_id = uuid7()
    inserted = await session.execute(
        text(
            "INSERT INTO webhook_inbox_events (id, provider, event_key, payload_hash, status, "
            "event_name, created_at, updated_at) VALUES (:id, :provider, :key, :hash, "
            "'processing', :name, now(), now()) "
            "ON CONFLICT (provider, event_key) DO NOTHING RETURNING id"
        ),
        {
            "id": row_id,
            "provider": provider,
            "key": event_key,
            "hash": payload_hash,
            "name": event_name,
        },
    )
    if inserted.first() is not None:
        return InboxClaim(state="claimed", row_id=row_id)

    existing = (
        await session.execute(
            text(
                "SELECT id, payload_hash, status FROM webhook_inbox_events "
                "WHERE provider = :provider AND event_key = :key"
            ),
            {"provider": provider, "key": event_key},
        )
    ).first()
    if existing is None:  # pragma: no cover
        return InboxClaim(state="claimed", row_id=row_id)

    found_id, found_hash, status = existing
    if found_hash != payload_hash:
        # NOT an error we swallow: an identical event id with different content means
        # someone is replaying a doctored payload at an unsigned endpoint (D-31).
        alert("ROUTE_HANDLER", "webhook_payload_mismatch", provider=provider, event_key=event_key)
        raise ProblemError.conflict(
            "webhook_payload_mismatch",
            "This event id was already received with different content.",
        )
    if status in ("failed", "processing"):
        # FAILED = the consumer recorded its own defeat. PROCESSING past the lease =
        # the consumer died before it could. Both mean nobody is doing this work, and
        # for an at-most-once engine event (D-31) "nobody is doing this work and the
        # key says duplicate" is a silently dropped call.
        #
        # This was not hypothetical: `tenancy/clerk_webhooks.py` (deleted in D-177) COMMITTED the
        # claim, then does the mirroring in a later transaction with no failure path
        # that marks the row failed — so any exception there leaves PROCESSING behind
        # and every retry of that svix-id was answered "duplicate".
        #
        # A recent PROCESSING row is a real concurrent delivery and still dedupes.
        retried = await session.execute(
            text(
                "UPDATE webhook_inbox_events SET status = 'processing', updated_at = now() "
                "WHERE id = :id AND (status = 'failed' OR "
                "(status = 'processing' AND updated_at < now() - :lease))"
            ),
            {"id": found_id, "lease": CLAIM_LEASE},
        )
        if rowcount_of(retried):
            return InboxClaim(state="claimed", row_id=found_id)
    # Make the retry visible: the activity view's "deduplicated" count is this
    # counter, and without it a vendor retrying fifteen times looks like one quiet
    # arrival and a client concluding that events vanish.
    await session.execute(
        text(
            "UPDATE webhook_inbox_events SET duplicate_count = duplicate_count + 1, "
            "updated_at = now() WHERE id = :id"
        ),
        {"id": found_id},
    )
    return InboxClaim(state="duplicate", row_id=found_id)


async def mark_inbox_enqueued(session: AsyncSession, *, row_id: UUID) -> None:
    await session.execute(
        text(
            "UPDATE webhook_inbox_events SET status = 'enqueued', enqueued_at = now(), "
            "updated_at = now() WHERE id = :id AND status = 'processing'"
        ),
        {"id": row_id},
    )


async def mark_inbox_processed(session: AsyncSession, *, row_id: UUID) -> None:
    await session.execute(
        text(
            "UPDATE webhook_inbox_events SET status = 'processed', processed_at = now(), "
            "updated_at = now() WHERE id = :id"
        ),
        {"id": row_id},
    )


async def mark_inbox_failed(session: AsyncSession, *, row_id: UUID, error: str) -> None:
    await session.execute(
        text(
            "UPDATE webhook_inbox_events SET status = 'failed', last_error = :error, "
            "updated_at = now() WHERE id = :id"
        ),
        {"id": row_id, "error": error[:500]},
    )


__all__ = [
    "IDEMPOTENCY_TTL",
    "OUTBOX_CLAIM_LEASE",
    "OUTBOX_MAX_ATTEMPTS",
    "OUTBOX_RETRY_BACKOFF_CAP_S",
    "OUTBOX_RETRY_BACKOFF_S",
    "DeadLetterJobDepth",
    "DeadLetterQueue",
    "IdempotencyClaim",
    "InboxClaim",
    "OutboxMessageRow",
    "body_hash",
    "claim_idempotency",
    "claim_inbox_event",
    "claim_outbox_batch",
    "complete_idempotency",
    "defer_outbox_claim",
    "enqueue_outbox",
    # Was missing while three modules imported it — `__all__` here is the module's
    # statement of its own surface, and a name absent from it reads as internal to the
    # next person deciding whether they may call it.
    "enqueue_outbox_once",
    "fail_idempotency",
    "mark_inbox_enqueued",
    "mark_inbox_failed",
    "mark_inbox_processed",
    "mark_outbox_failed",
    "mark_outbox_published",
    "read_dead_letter_queue",
    "record_outbox_metrics",
    "replay_dead_letters",
    "scope_key",
    "sweep_idempotency",
]
