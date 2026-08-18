"""Audit log writer with the tamper-evident hash chain (BACKEND-PATTERNS §7).

Each entry's hash = HMAC(secret, previous_hash + canonical(entry)). Writers are
serialized by a Postgres advisory lock held on the CALLER'S transaction, so the head
they read is the head they chain onto; the head itself is always the last row in
`audit_log` and lives nowhere else.

Why it earns its keep: DPDP disputes and support escalations both turn into "prove
nobody edited the record". Detecting tampering costs one HMAC per write.

THE SECRET IS REQUIRED OUTSIDE `local` AND VERIFICATION WALKS A KEY RING. Both halves
are one change and neither works alone: requiring the secret is what stops a deployment
signing evidence with a constant printed in this file, and the ring is what stops that
requirement reporting the entire pre-existing history as tampered on the day it ships.
`_key_ring` carries the argument, including the three designs that were rejected.

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
from apps.api.core.settings import get_settings, resolve_hmac_key
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


# THE KEY THIS CHAIN WAS SIGNED WITH BEFORE THE SECRET WAS REQUIRED.
#
# `_chain_secret` used to read `audit_chain_secret or f"local-dev:{app_env}"` in EVERY
# environment, so a deployment that forgot the variable signed its tamper-evident ledger
# with a string printed in this repository. That is the defect this module now closes —
# but the entries it produced are in an append-only table (hard rule 4) and are not
# going anywhere, so the constant is not deleted. It is DEMOTED: generation 0 of the key
# ring, never used to sign again, kept so those rows still verify.
#
# It is not a secret and never was, so it needs no configuration and gets no length
# floor. What it is, is the honest record of a period during which the chain proved that
# nobody had edited it EXCEPT someone who read this file.
_LEGACY_KEY_TEMPLATE = "local-dev:{app_env}"


@dataclass(frozen=True, slots=True)
class _ChainKey:
    """One key the chain can be verified under. Higher generation = newer.

    A pair rather than a bare `bytes`, because the generation is what
    `_matching_generation` compares against its floor, and deriving it from a list index
    at the call site is exactly the kind of implicit invariant that survives until
    somebody reorders the ring.
    """

    generation: int
    material: bytes


def _active_key() -> bytes:
    """The key `write_audit` signs with, or a refusal.

    Fails closed outside `local`, matching `core/impersonation.py::_signing_key` and
    every other HMAC secret here (`core/settings.py::resolve_hmac_key` is the one
    ladder). The consequence is worth stating plainly because it is severe and
    deliberate: with no key, every audited action fails, and hard rule 5 puts
    raw-transcript reads and campaign launches on that list. That is the correct
    direction to fail — an unverifiable audit trail is not a degraded audit trail, it is
    an absent one — and `runtime_config_missing_keys` makes it a red readiness probe so
    the deployment never takes traffic in that state.
    """
    settings = get_settings()
    return resolve_hmac_key(
        settings.audit_chain_secret,
        env_var="AUDIT_CHAIN_SECRET",
        purpose="the audit hash chain",
        code="audit_chain_not_configured",
        title="The audit chain is not configured",
        local_fallback=_LEGACY_KEY_TEMPLATE.format(app_env=settings.app_env),
        app_env=settings.app_env,
    )


def _key_ring() -> tuple[_ChainKey, ...]:
    """Every key this deployment may verify an entry under, OLDEST FIRST.

    `generation == index`, and the LAST element is the active signing key.

    WHY A RING AT ALL — this is the half of the slice that is not about configuration.
    An append-only hash chain outlives its key. The moment the secret changes, every
    entry written before the change stops reproducing under the new one, and a verifier
    that knows only the current key reports the ENTIRE HISTORY as edited: not one break
    at the boundary, but `content` on every single prior row, because `_entry_hash` is
    recomputed per entry rather than only across links. Requiring the secret without
    this would therefore have made our own deploy manufacture the exact signal the
    ledger exists to produce — and an operator who learns that breaks come from deploys
    stops treating a break as evidence, which is the only thing this chain is for.

    So verification dispatches per entry on which key reproduces it, which is the
    established shape for versioned integrity in an append-only store: old rows verify
    under the old rules, new rows under the new ones, and nothing is rewritten. (The
    alternative that shows up alongside it in the literature — publish the rotation as a
    signed entry in the chain itself, countersigned by the outgoing key — is a better
    answer to "prove the rotation was authorised" and NOT an answer to this problem: it
    still leaves the pre-rotation entries needing the pre-rotation key to verify. It is
    additive, and it is not free, so it is not here.)

    REJECTED, and why each is worse:

    - **A generation column on `audit_log`.** The obvious version of this, and it buys
      exactly one thing the ring does not: it lets a row that verifies under NO
      available key be reported as "we lack this key" rather than "this row was edited".
      It buys nothing against forgery — a forger without the key cannot produce the hash
      whether or not the row declares which key it used — and it costs a migration on
      the hottest INSERT path in the compliance module, a change to the hashed payload
      (so the recomputation of every pre-migration row has to special-case its absence),
      and a NULL era that has to be trusted anyway. Since the ring always contains the
      legacy constant and the retired slot covers real rotations, "no available key" is
      unreachable through any supported path; the column would be schema paid for a
      diagnosis of a state we prevent.
    - **Accept the break and document it.** Not a boundary — see above, it is every
      historical row reported as tampered, permanently, in an append-only table. It
      would leave the endpoint red forever with a count in the tens of thousands, which
      is the "permanently red light nobody reads" failure `verify_chain` already argues
      against for the one real historical break.
    - **Re-anchor at migration time** (recompute and rewrite `entry_hash` under the new
      key). It is an UPDATE on an append-only ledger — hard rule 4, `APPEND_ONLY_TABLES`,
      and a database trigger that raises, so it would not even execute. It is also
      self-defeating: rewriting hashes from current row content launders any tampering
      that already happened into a clean chain, which is the one outcome strictly worse
      than a visible break.

    WHAT THE RING COSTS, stated plainly: an entry is accepted if ANY admissible key
    reproduces it, and generation 0 is public. Nothing here can make the fallback era
    retroactively tamper-evident — that evidence was never created. What is bounded is
    the future: `_matching_generation` refuses a key the chain has already moved past, so
    once one entry is signed by the active key, no later entry may claim generation 0.
    A forger holding the public constant can therefore only forge inside the prefix that
    was already forgeable, and `entries_under_retired_key` on the verdict is how an
    operator sees how large that prefix is.
    """
    settings = get_settings()
    legacy = _ChainKey(
        generation=0,
        material=_LEGACY_KEY_TEMPLATE.format(app_env=settings.app_env).encode(),
    )
    active = _active_key()
    if active == legacy.material:
        # No secret configured, which `_active_key` permits only under `local`. There is
        # one generation and it is the public one.
        return (legacy,)
    ring = [legacy]
    if settings.audit_chain_secret_retired:
        ring.append(
            _ChainKey(
                generation=len(ring),
                material=settings.audit_chain_secret_retired.encode(),
            )
        )
    ring.append(_ChainKey(generation=len(ring), material=active))
    return tuple(ring)


def _entry_hash(prev_hash: str, entry: dict[str, Any], key: bytes) -> str:
    canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)
    return hmac.new(key, (prev_hash + canonical).encode(), hashlib.sha256).hexdigest()


def _without_ip(entry: dict[str, Any]) -> dict[str, Any]:
    """The pre-D-312 payload shape: everything except `ip`.

    Entries written before `ip` joined the hash are signed over this shape and must keep
    verifying — an append-only ledger cannot be re-signed (hard rule 4), and a change
    that turned the whole existing log red would be indistinguishable from tampering on
    the day it deployed.

    IT IS NOT A DOWNGRADE PATH. Accepting the old shape lets an attacker keep a row that
    OMITS the ip from the hash; it does not let them produce one, because producing
    either shape needs the secret. The forgery this file already guards — generation 0's
    public key — is bounded by `floor` and is unaffected: both shapes are tried under the
    same admissible keys.
    """
    return {key: value for key, value in entry.items() if key != "ip"}


def _matching_generation(
    ring: tuple[_ChainKey, ...],
    prev_hash: str,
    entry: dict[str, Any],
    recorded: str,
    *,
    floor: int,
) -> int | None:
    """Which generation signed this entry, or None if no admissible key reproduces it.

    NEWEST FIRST, so a healthy log costs one HMAC per entry and only the pre-rotation
    prefix pays for a second.

    `floor` is the monotonicity rule and it is load-bearing rather than tidy. Generation
    0 is a PUBLIC constant, so without it a forger could edit any entry, re-sign it with
    the key from this file, and be accepted. Refusing a generation the chain has already
    moved past confines that to entries that precede the first entry signed by the
    active key — which is exactly the era that was already forgeable, and cannot be
    un-forged. Expressed as a bound on which keys are TRIED rather than as a separate
    check, so there is one place a key becomes admissible.
    """
    shapes = (entry, _without_ip(entry))
    for key in reversed(ring):
        if key.generation < floor:
            return None
        for shape in shapes:
            # `compare_digest` because this is a MAC comparison and the repo should not
            # have two idioms for that. No timing-attack claim is being made — the caller
            # is an operator-triggered walk, not an oracle — it is simply the correct
            # primitive.
            if hmac.compare_digest(_entry_hash(prev_hash, shape, key.material), recorded):
                return key.generation
    return None


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
    # BEFORE the lock, deliberately. A deployment with no usable key cannot write this
    # entry, and discovering that while holding `audit:chain` would queue every other
    # audit writer in the fleet behind a transaction that is going to roll back anyway.
    key = _active_key()
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
        # IN THE HASH SINCE D-312. SEC-COMP §5 asks each row for "actor, tenant, at, ip",
        # and `scripts/check_audit_ip.py` exists because the fourth field is the one that
        # answers WHERE an act came from — the question an impersonation dispute or a
        # breach timeline turns on. It was the only one of the four the chain did not
        # cover, so an insider with write access to this table could rewrite an
        # operator's source address and every hash still verified: tamper-EVIDENCE with a
        # hole exactly at the field somebody would want to change.
        #
        # `at` is deliberately still outside, and that is a constraint rather than an
        # oversight: it is stamped by `clock_timestamp()` inside the lock (see below),
        # so it does not exist until the INSERT, and computing it in Python to hash it
        # would move the chain's ordering off the database clock and onto whichever app
        # instance happened to serve the request. A reordering is what `verify_chain`'s
        # `link` break detects; an edited `at` therefore still shows up there, out of
        # order, which is not true of an edited `ip`.
        "ip": ip,
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
    entry_hash = _entry_hash(prev_hash, payload, key)
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
    #: Entries that verified under a RETIRED key rather than the active one — on most
    #: deployments, the era before `AUDIT_CHAIN_SECRET` was required, when the chain was
    #: signed with a constant printed in this repository (`_key_ring`).
    #:
    #: They are intact, so they are NOT breaks and they do not make `ok` false. What
    #: they are is weakly attested: anyone who could read the source could have produced
    #: them. That distinction only matters when the log is used as evidence, which is
    #: precisely when somebody needs to know it — so it travels with the verdict rather
    #: than living in a runbook. Zero on a deployment that has always been configured.
    entries_under_retired_key: int


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

    `content` MEANS "OUR WRITER WOULD NOT HAVE PRODUCED THIS HASH HERE", which is a
    slightly wider statement than "the fields were edited" and the width is deliberate.
    Since `_key_ring` exists, an entry is checked against every key the chain has not yet
    moved past, so a row fails `content` when its fields changed OR when it claims a key
    generation the chain had already retired — the downgrade a public generation-0 key
    would otherwise permit. The operator's next move is the same in both cases (this row
    was not written by `write_audit`), which is why they share a kind rather than
    growing a third that would have to be explained before it could be acted on.

    WHAT AN OPERATOR SEES AFTER THE DEPLOY THAT MADE `AUDIT_CHAIN_SECRET` REQUIRED:
    exactly the verdict they saw before it. A deployment that was already configured
    verifies every entry under the active key; one that had been running on the fallback
    verifies its history under generation 0 and everything after the deploy under the
    active key; a local box has only generation 0. In all three the break count is
    unchanged — the pre-existing, permanent scars this log already carries are still
    there and still exactly as many. The one thing that moves is
    `entries_under_retired_key`, which is a number, not an alarm.
    """
    # Resolved ONCE, before any row is read: a deployment with no usable key must refuse
    # the whole walk rather than report a log full of entries it merely could not check.
    ring = _key_ring()
    active_generation = ring[-1].generation

    expected_prev = GENESIS
    checked = 0
    breaks: list[ChainBreak] = []
    breaks_found = 0
    oldest: datetime | None = None
    newest: datetime | None = None
    cursor: tuple[datetime, UUID] | None = None
    exhausted = False
    # The oldest generation still admissible. Rises as the walk meets newer keys and
    # never falls — see `_matching_generation`.
    generation_floor = 0
    under_retired = 0

    while limit is None or checked < limit:
        size = _VERIFY_BATCH if limit is None else min(_VERIFY_BATCH, limit - checked)
        # Keyset pagination on the same (at, id) order the chain is written in, served by
        # `ix_audit_log_chain`: OFFSET would re-scan the prefix on every batch, and a row
        # appended mid-walk would shift it.
        rows = (
            await session.execute(
                text(
                    "SELECT id, actor_type, actor_id, tenant_id, action, object_type, "
                    "object_id, prev_hash, entry_hash, at, ip FROM audit_log "
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
                # `str()` because the column is `inet`-free TEXT but the driver may hand
                # back a non-str for a NULL-adjacent value; the writer hashed a plain
                # string or None, so the shapes must match exactly (D-312).
                "ip": str(row[10]) if row[10] is not None else None,
            }
            row_prev = str(row[7]) if row[7] is not None else ""
            # `""` for a NULL hash rather than `str(None)`: it can never equal a hex
            # digest either way, but one of them reads like a value and the other reads
            # like the absence it is.
            recorded = str(row[8]) if row[8] is not None else ""
            generation = _matching_generation(
                ring, row_prev, payload, recorded, floor=generation_floor
            )
            kind: BreakKind | None = None
            if generation is None:
                # No admissible key reproduces the row: its FIELDS changed, or it names
                # a retired key generation. Checked first because such a row also
                # usually breaks the link, and reporting the edit is the more actionable
                # of the two.
                kind = "content"
            elif row_prev != expected_prev:
                # Intact row, wrong neighbour: something was deleted, reordered, or two
                # writers raced onto one head.
                kind = "link"
            if kind is not None:
                breaks_found += 1
                if len(breaks) < _MAX_REPORTED_BREAKS:
                    breaks.append(ChainBreak(entry_id=str(row[0]), at=row[9], kind=kind))
            if generation is not None:
                # A key the chain has reached retires every older one for the remainder
                # of the walk. Raised only on entries that actually verified: letting a
                # break move the floor would hand a forger the ability to close the
                # window behind them.
                generation_floor = max(generation_floor, generation)
                if generation < active_generation:
                    under_retired += 1
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
        entries_under_retired_key=under_retired,
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
