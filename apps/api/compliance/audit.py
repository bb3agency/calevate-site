"""Audit log writer with the tamper-evident hash chain (BACKEND-PATTERNS §7).

Each entry's hash = HMAC(secret, previous_hash + canonical(entry)). Writers are
serialized by a Postgres advisory lock held on the CALLER'S transaction, so the head
they read is the head they chain onto; the head itself is always the last row in
`audit_log` and lives nowhere else.

Why it earns its keep: DPDP disputes and support escalations both turn into "prove
nobody edited the record". Detecting tampering costs one HMAC per write.

`audit_log` is INSERT-only (hard rule 4) and NOT tenant-RLS'd — the admin realm reads
it across tenants, and reading it is itself audited.

DEVIATION FROM WHAT BACKEND-PATTERNS §5/§7 USED TO PRESCRIBE — a Redis mutex plus a
Redis-cached head for this exact chain. Recorded as **D-59** and both sections are now
amended in place, so this is the pattern rather than an exception to it. The argument is
repeated here rather than cited, so the next reader inherits it rather than the
conclusion:

- The Redis design cannot be made correct given §7's other, load-bearing decision —
  the entry is appended IN THE CALLER'S TRANSACTION. Correctness requires that no
  second writer read the head between our read and our COMMIT, and a TTL-bounded lock
  cannot cover a transaction of unknown length: a caller that takes 4s to commit
  outlives a 3s lease and the next writer chains onto the same head anyway. Making the
  Redis lock blocking-with-retry (the obvious repair of the bug this replaces, where a
  writer that failed `SET NX` proceeded regardless) fixes the ignoring, not the
  expiry.
- The cached head has the same shape of defect one level down. Written inside the
  caller's transaction it publishes a head that a ROLLBACK then erases — a durable
  break, because the next writer chains onto a row that does not exist. Written AFTER
  commit it is still wrong: a process that dies in the gap leaves the cache one entry
  behind and the next writer forks off a stale head. Validating the cache against the
  table is the query the cache existed to avoid.
- `pg_advisory_xact_lock` has neither failure mode. It is released by COMMIT or
  ROLLBACK — the two events that decide whether the row exists — so the lock's lifetime
  is exactly the window that needs protecting, there is no TTL to tune, and there is no
  second system whose outage forks the chain. This repo already reached the identical
  conclusion for `credit_ledger` (`billing/service.py::lock_tenant_credits`), including
  the `clock_timestamp()` ordering below; one way per problem.
  See https://www.postgresql.org/docs/16/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS
  ("locks can be either ... automatically released at the end of the current
  transaction").

What it costs, stated plainly: audit writers queue behind each other for the REMAINDER
of the holder's transaction, not just for the INSERT. That is inherent — releasing
earlier would let the next writer read a head whose row is not committed yet — and it
is why `write_audit` belongs late in a transaction. A caller that holds the lock and
then blocks on a row another audit writer holds will deadlock; Postgres detects that
and raises, which is a loud, recoverable failure rather than a silent fork.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.context import Principal
from apps.api.core.logging import get_logger, redact_mapping
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7

log = get_logger(__name__)

# One key for the whole chain — the chain is global, so the lock is too. Hashed the way
# every other advisory lock in this repo is hashed (`hashtextextended(key, 0)`), so the
# keyspace stays readable and nobody re-derives an integer by hand.
_CHAIN_LOCK_KEY = "audit:chain"
GENESIS = "0" * 64
# How many rows `verify_chain` pulls per round trip. Bounds memory on a long log without
# turning the walk into one query per entry.
_VERIFY_BATCH = 1000


def _chain_secret() -> bytes:
    """Derived from a real secret in prod. Local dev gets a constant so the chain is
    still verifiable end-to-end without a secrets manager."""
    settings = get_settings()
    material = settings.audit_chain_secret or f"local-dev:{settings.app_env}"
    return material.encode()


def _entry_hash(prev_hash: str, entry: dict[str, Any]) -> str:
    canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)
    return hmac.new(_chain_secret(), (prev_hash + canonical).encode(), hashlib.sha256).hexdigest()


async def lock_chain(session: AsyncSession) -> None:
    """Serialize every chain writer for the rest of this transaction.

    Take it BEFORE the head read, which is the read the write depends on. Re-entrant,
    so a transaction that appends two entries does not deadlock against itself.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": _CHAIN_LOCK_KEY},
    )


async def _current_head(session: AsyncSession) -> str:
    """The last entry's hash, read from the only place it is durable.

    Ordering matches `verify_chain`'s, and both match INSERT order because `at` is
    stamped with `clock_timestamp()` under the lock (see `write_audit`).

    One index read per audit write, inside the lock, so its cost is the width of the
    window every other audit writer is queued behind. `ix_audit_log_chain` on `(at, id)`
    (migration `d4a1e93b70c6`) makes it a descent to the rightmost leaf; before that
    index it planned as a parallel sequential scan, which also claimed two workers per
    audit write while holding the lock.
    """
    row = (
        await session.execute(
            text("SELECT entry_hash FROM audit_log ORDER BY at DESC, id DESC LIMIT 1")
        )
    ).first()
    return str(row[0]) if row and row[0] else GENESIS


async def write_audit(
    session: AsyncSession,
    *,
    action: str,
    actor: Principal | None = None,
    actor_type: str | None = None,
    tenant_id: UUID | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
    ip: str | None = None,
    summary: dict[str, Any] | None = None,
) -> None:
    """Append one entry IN THE CALLER'S TRANSACTION.

    That is deliberate: the audit row and the thing it describes commit together, so
    there is no window where a raw-transcript read happened but was not recorded.
    """
    resolved_actor_type = actor_type or (
        "admin" if actor and actor.is_admin else "user" if actor else "system"
    )
    entry_id = uuid7()
    payload: dict[str, Any] = {
        "id": str(entry_id),
        "actor_type": resolved_actor_type,
        "actor_id": str(actor.user_id) if actor and actor.user_id else None,
        "tenant_id": str(tenant_id) if tenant_id else None,
        "action": action,
        "object_type": object_type,
        "object_id": object_id,
    }
    if summary:
        # Depth-capped, length-capped, key-pattern-redacted before it leaves the
        # process (§7). It is NOT part of the hashed payload: `audit_log` has no
        # summary column, and hashing a field the row does not carry would make the
        # chain unverifiable. The summary goes to the log stream (the JSONL artifact
        # §7 describes), keyed by the same entry id.
        log.info("audit", extra={"entry_id": str(entry_id), **redact_mapping(summary)})

    # Read-then-write on the chain head: the lock has to come first and stay held
    # through COMMIT, or two writers chain onto the same entry (module docstring).
    await lock_chain(session)
    prev_hash = await _current_head(session)
    entry_hash = _entry_hash(prev_hash, payload)
    await session.execute(
        text(
            "INSERT INTO audit_log (id, actor_type, actor_id, tenant_id, action, "
            "object_type, object_id, ip, at, prev_hash, entry_hash, created_at) "
            "VALUES (:id, :actor_type, :actor_id, :tenant_id, :action, :object_type, "
            ":object_id, :ip, clock_timestamp(), :prev_hash, :entry_hash, "
            "clock_timestamp())"
        ),
        {
            "id": entry_id,
            "actor_type": resolved_actor_type,
            "actor_id": actor.user_id if actor else None,
            "tenant_id": tenant_id,
            "action": action,
            "object_type": object_type,
            "object_id": object_id,
            "ip": ip,
            "prev_hash": prev_hash,
            "entry_hash": entry_hash,
        },
    )
    # `clock_timestamp()`, NOT `now()`, for the same reason `credit_ledger` uses it
    # (billing/service.py): `now()` is TRANSACTION-start time, so a request that did
    # other work first stamps its entry EARLIER than one that started later and
    # committed first — even though the lock serialized them correctly. `verify_chain`
    # replays in `at` order, so the chain would read back out of write order and report
    # a link break that never happened. `clock_timestamp()` is evaluated at the INSERT,
    # under the lock, and is therefore strictly increasing along the chain.
    # (Entries written before this fix carry transaction-start times; a legacy pair that
    # interleaved that way is a real, permanent break in the replay order and will be
    # reported as one — the ledger is append-only, so it cannot be rewritten.)


#: How many individual breaks the verdict carries. Past this the count keeps rising but
#: the list stops growing, so one catastrophic event cannot turn a verdict into a
#: megabyte of JSON. Twenty is well past the point where an operator stops reading rows
#: and starts reading the count.
_MAX_REPORTED_BREAKS = 20

BreakKind = Literal["link", "content"]


@dataclass(frozen=True, slots=True)
class ChainBreak:
    """One place the recomputation disagreed with the table, and WHICH disagreement.

    Two different incidents were previously reported as one condition:

    * `content` — the row's own fields no longer hash to its own `entry_hash`, computed
      against the `prev_hash` THE ROW ITSELF CARRIES. Somebody edited this entry.
    * `link` — the row hashes correctly but names a predecessor that is not the entry
      before it. Somebody deleted or reordered entries, or (before `d4a1e93b70c6`'s
      sibling fix) two writers raced onto one head.

    An operator's next move differs completely between them, so a verdict that says only
    "broken here" has thrown away the half that decides what to do.
    """

    entry_id: str
    at: datetime
    kind: BreakKind


@dataclass(frozen=True, slots=True)
class ChainVerification:
    """What the recomputation found AND what it covered.

    The scope is part of the answer, not a footnote: `ok=True` over an unstated subset
    is the failure this shape exists to prevent — a green verdict that an operator
    reads as "the log is intact" when the walk stopped a thousand rows in and never
    looked at last night.
    """

    ok: bool
    first_bad_entry_id: str | None
    #: Every break found, oldest first, capped at `_MAX_REPORTED_BREAKS`.
    breaks: tuple[ChainBreak, ...]
    #: Total breaks, which is >= len(breaks) once the cap bites.
    breaks_found: int
    #: Entries actually recomputed. A break no longer stops the count.
    entries_checked: int
    #: True only when the walk reached the end of the log with nothing left unchecked.
    complete: bool
    #: The `at` range the walk covered — the human-readable form of the same claim.
    oldest_checked_at: datetime | None
    newest_checked_at: datetime | None


async def verify_chain(session: AsyncSession, *, limit: int | None = None) -> ChainVerification:
    """Walk the chain oldest-first from GENESIS, recompute every link, and REPORT EVERY
    BREAK rather than stopping at the first.

    Used by the compliance drill (OPERATIONS §6) and available to support when a client
    disputes a record.

    THE SCOPE. `limit=None` — the whole log — is the default because the previous
    default (1000) silently answered a different question than the one asked: past a
    thousand rows it verified only the oldest thousand, so every recent entry, which is
    the half anyone running this in anger cares about, went unchecked under a green
    verdict. A caller that wants a bound passes one and reads `complete` to see that it
    truncated. Rejected alternative: bounding to the NEWEST n instead. That is a sound
    check on its own but it cannot prove the window anchors to GENESIS, so it answers
    "was the recent past edited" rather than "is this ledger the one we wrote".

    WHY IT DOES NOT STOP AT THE FIRST BREAK, which is the harder call. Stopping is the
    obvious reading of "everything after a break is unverifiable", and it is wrong in
    two ways that matter more than the tidiness it buys:

    1. **It is a denial of verification.** One broken link early in the log makes the
       entire remainder unexamined — so the cheapest way to hide a change made last
       night is to also break something from six months ago. A tamper-evidence tool
       whose coverage an attacker can switch off from outside the window they care
       about is not evidence.
    2. **The remainder is not actually unverifiable.** What a break destroys is the
       proof that the following entries descend from GENESIS. It destroys nothing about
       whether they descend from EACH OTHER, or whether any individual row still hashes
       to its own recorded hash. Re-anchoring on the row that broke and continuing turns
       "unverifiable" into "verifiable, as a separate segment", which is strictly more
       information and costs one assignment.

    So the log is read as SEGMENTS: a break starts a new one, `breaks` names every
    boundary, and `ok` means there were none. An append-only ledger cannot be repaired
    (hard rule 4), so a real historical break — this repo has one, from the era when the
    chain lock was not consulted — is permanent, and a verifier that reported only it
    forever would be a permanently red light nobody reads. Naming all of them, with
    dates and kinds, is what lets an operator tell the known scar from tonight's wound.

    THE TWO KINDS ARE SEPARATED (`ChainBreak.kind`) because the recompute is run against
    the row's OWN `prev_hash` rather than against the expected one. A row that was edited
    fails that check no matter where it sits; a row that is merely misplaced passes it and
    fails the link check. Testing content against the EXPECTED prev — what this function
    used to do — conflates the two: every entry after a deletion reports as edited.
    """
    expected_prev = GENESIS
    checked = 0
    breaks: list[ChainBreak] = []
    breaks_found = 0
    oldest: datetime | None = None
    newest: datetime | None = None
    cursor: tuple[datetime, UUID] | None = None
    exhausted = False

    while limit is None or checked < limit:
        size = _VERIFY_BATCH if limit is None else min(_VERIFY_BATCH, limit - checked)
        # Keyset pagination on the same (at, id) order the chain is written in, served by
        # `ix_audit_log_chain`: OFFSET would re-scan the prefix on every batch, and a row
        # appended mid-walk would shift it.
        rows = (
            await session.execute(
                text(
                    "SELECT id, actor_type, actor_id, tenant_id, action, object_type, "
                    "object_id, prev_hash, entry_hash, at FROM audit_log "
                    + ("WHERE (at, id) > (:after_at, :after_id) " if cursor else "")
                    + "ORDER BY at ASC, id ASC LIMIT :limit"
                ),
                {"limit": size}
                | ({"after_at": cursor[0], "after_id": cursor[1]} if cursor else {}),
            )
        ).all()
        for row in rows:
            payload = {
                "id": str(row[0]),
                "actor_type": row[1],
                "actor_id": str(row[2]) if row[2] else None,
                "tenant_id": str(row[3]) if row[3] else None,
                "action": row[4],
                "object_type": row[5],
                "object_id": row[6],
            }
            row_prev = str(row[7]) if row[7] is not None else ""
            kind: BreakKind | None = None
            if _entry_hash(row_prev, payload) != row[8]:
                # The row does not hash to its own recorded hash: its FIELDS changed.
                # Checked first because an edited row also usually breaks the link, and
                # reporting the edit is the more actionable of the two.
                kind = "content"
            elif row_prev != expected_prev:
                # Intact row, wrong neighbour: something was deleted, reordered, or two
                # writers raced onto one head.
                kind = "link"
            if kind is not None:
                breaks_found += 1
                if len(breaks) < _MAX_REPORTED_BREAKS:
                    breaks.append(ChainBreak(entry_id=str(row[0]), at=row[9], kind=kind))
            # Re-anchor on this row either way, so the next entry is judged against the
            # log as it ACTUALLY is. Without this, one break cascades into a break report
            # on every single row after it and the count stops meaning anything.
            expected_prev = str(row[8])
            checked += 1
            oldest = oldest or row[9]
            newest = row[9]
            cursor = (row[9], row[0])
        if len(rows) < size:
            exhausted = True
            break

    return ChainVerification(
        ok=breaks_found == 0,
        # Kept as its own field rather than derived by the caller: it is what the console
        # names as the evidence, and `breaks[0]` is only the same thing while the cap has
        # not bitten.
        first_bad_entry_id=breaks[0].entry_id if breaks else None,
        breaks=tuple(breaks),
        breaks_found=breaks_found,
        entries_checked=checked,
        # True only when the walk ran out of log rather than out of `limit`.
        complete=exhausted,
        oldest_checked_at=oldest,
        newest_checked_at=newest,
    )


__all__ = [
    "GENESIS",
    "BreakKind",
    "ChainBreak",
    "ChainVerification",
    "lock_chain",
    "verify_chain",
    "write_audit",
]
