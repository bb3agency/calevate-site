"""The audit hash chain under contention, and the walk that reads it back.

`write_audit` reads the chain head and then INSERTs an entry naming it. That is a
read-then-write, so it is only correct if nothing else can read the same head in
between. The Redis mutex it used to take was not that guarantee twice over: a writer
that failed `SET NX` proceeded ANYWAY (the flag was only ever consulted in the `finally`
that decided whether to release), and even a blocking version could not have covered
the window, because the entry commits in the CALLER'S transaction and a TTL lease
expires on its own schedule. Two writers therefore read head H0, both wrote
`prev_hash = H0`, and `verify_chain` reported the second one as tampered — a
tamper-evidence feature manufacturing its own tamper evidence.

Nothing in the suite exercised contention, which is why it survived: every existing
audit assertion writes one entry at a time, and one writer never races anybody.

**Deterministic, not a sleep race.** Each writer opens its own transaction and reports
that it is open; only when ALL of them are open — so every `now()` is already fixed and
every writer is about to read the head — does the barrier release them together. The
interleaving that breaks the chain is therefore forced on every run rather than waited
for, and the test is equally valid on a machine with one core.

**NOTHING HERE ASSERTS THAT THE WHOLE LOG IS INTACT, AND THAT IS DELIBERATE.** The suite
runs against a long-lived database whose `audit_log` is append-only and therefore still
carries the forks the old broken lock created — real, permanent, unrepairable. A test
that demanded a globally clean chain would pass only on a freshly migrated database,
which is exactly the shape that is green in CI and red on a developer's machine for a
reason that is not their fault. So every assertion below is a DELTA: what these writers
added, measured against what was already there. That is also the stronger claim — "the
log has no breaks" would have been satisfied by a database nobody had ever written to.
"""

from __future__ import annotations

import asyncio
import inspect
import itertools
import uuid

import pytest
from apps.api.compliance.audit import (
    _MAX_REPORTED_BREAKS,
    GENESIS,
    _active_key,
    _entry_hash,
    lock_chain,
    verify_chain,
    write_audit,
)
from apps.api.db.base import uuid7
from apps.api.db.session import untenanted_session
from sqlalchemy import text

WRITERS = 4


class _AbortError(Exception):
    """Raised to unwind a transaction the way a real failure would."""


async def _write_one(barrier: asyncio.Barrier, action: str) -> None:
    """One writer, in its own transaction, released with the others."""
    async with untenanted_session() as session:
        # Force the transaction open BEFORE the barrier. This is what makes the race
        # real rather than nominal: `now()` is transaction-start time, so after this
        # point every writer carries a start timestamp that is older than the commits
        # about to happen — the exact condition under which a chain ordered by `at`
        # reads back out of write order.
        await session.execute(text("SELECT 1"))
        await barrier.wait()
        await write_audit(session, action=action, actor_type="system")


async def _breaks_now() -> int:
    """How many breaks the log carries at this instant."""
    async with untenanted_session() as session:
        return (await verify_chain(session)).breaks_found


async def test_concurrent_writers_produce_one_unbroken_chain() -> None:
    """N writers racing on one head must add no break to the log."""
    marker = f"test.chain_race.{uuid.uuid4().hex[:12]}"
    barrier = asyncio.Barrier(WRITERS)

    before = await _breaks_now()
    await asyncio.gather(*(_write_one(barrier, f"{marker}.{i}") for i in range(WRITERS)))

    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, prev_hash, entry_hash FROM audit_log "
                    "WHERE action LIKE :like ORDER BY at ASC, id ASC"
                ),
                {"like": f"{marker}.%"},
            )
        ).all()
        verdict = await verify_chain(session)

    assert len(rows) == WRITERS, f"every writer must have landed its entry: {rows}"

    # The fork signature, asserted directly and not only through the verdict: two
    # entries naming the same predecessor is what "both read H0" looks like in the
    # table, and it is what the advisory lock exists to make impossible.
    prev_hashes = [row[1] for row in rows]
    assert len(set(prev_hashes)) == WRITERS, f"two entries chained onto one head: {prev_hashes}"

    # And they are chained to EACH OTHER in the order `verify_chain` replays them, which
    # is the second half of the fix: `at` is stamped with `clock_timestamp()` under the
    # lock, so replay order is write order.
    for earlier, later in itertools.pairwise(rows):
        assert later[1] == earlier[2], (
            f"entry {later[0]} does not chain onto its predecessor {earlier[0]}"
        )

    # The delta, which is the claim this file can actually make (module docstring).
    assert verdict.breaks_found == before, (
        f"the racing writers added {verdict.breaks_found - before} break(s): {verdict.breaks}"
    )
    assert verdict.entries_checked >= WRITERS, verdict
    assert verdict.complete, "the default walk covers the whole log"


async def test_a_rolled_back_writer_leaves_no_phantom_head() -> None:
    """A writer that aborts must leave the next one chaining onto the last COMMITTED
    entry.

    The Redis-cached head published `entry_hash` from inside the caller's uncommitted
    transaction, so a rollback erased the row while leaving the cache pointing at it —
    and the next writer chained onto a hash no row carried. That is a DURABLE break: the
    ledger is append-only, so nothing can repair it afterwards. The head now lives only
    in the table, where a rollback removes it along with the row.
    """
    marker = f"test.chain_rollback.{uuid.uuid4().hex[:12]}"

    before = await _breaks_now()

    with pytest.raises(_AbortError):
        async with untenanted_session() as doomed_session:
            await write_audit(doomed_session, action=f"{marker}.doomed", actor_type="system")
            # Aborting by raising, rather than by calling `rollback()` by hand, so the
            # transaction unwinds the way a real failure unwinds it.
            raise _AbortError

    async with untenanted_session() as session:
        await write_audit(session, action=f"{marker}.survivor", actor_type="system")

    async with untenanted_session() as session:
        survivor_prev = (
            await session.execute(
                text("SELECT prev_hash FROM audit_log WHERE action = :a"),
                {"a": f"{marker}.survivor"},
            )
        ).scalar()
        doomed_rows = (
            await session.execute(
                text("SELECT count(*) FROM audit_log WHERE action = :a"),
                {"a": f"{marker}.doomed"},
            )
        ).scalar()
        # "No phantom head" stated as the property itself rather than as a fixed value:
        # the head the survivor names must be a hash some row actually carries (or the
        # genesis). That holds no matter which other suite is writing entries alongside
        # this one, whereas comparing against a head captured a moment earlier would be
        # a race of the test's own making.
        prev_exists = (
            await session.execute(
                text("SELECT count(*) FROM audit_log WHERE entry_hash = :h"),
                {"h": survivor_prev},
            )
        ).scalar()
        verdict = await verify_chain(session)

    assert doomed_rows == 0, "the aborted writer's row must not exist"
    assert survivor_prev == GENESIS or prev_exists == 1, (
        f"the survivor chained onto a head no row carries: {survivor_prev}"
    )
    assert verdict.breaks_found == before, (
        f"the rollback added {verdict.breaks_found - before} break(s): {verdict.breaks}"
    )


async def test_the_verdict_states_what_it_covered() -> None:
    """A bounded walk must not read like a full one.

    The old default checked the OLDEST 1,000 entries and returned a bare `ok`, so on a
    longer log an operator got a green box that said nothing about last night. Scope is
    now part of the answer: a walk that stopped early says so.
    """
    async with untenanted_session() as session:
        await write_audit(session, action="test.chain_scope", actor_type="system")

    async with untenanted_session() as session:
        total = int((await session.execute(text("SELECT count(*) FROM audit_log"))).scalar() or 0)
        full = await verify_chain(session)
        bounded = await verify_chain(session, limit=1)

    assert full.complete
    # `>=`, not `==`: another suite may append while this one reads, and the ledger only
    # ever grows. What is being proved is that the walk covered everything counted, not
    # a stale thousand-row prefix of it.
    assert full.entries_checked >= total, (full.entries_checked, total)
    assert full.oldest_checked_at is not None and full.newest_checked_at is not None
    assert full.oldest_checked_at <= full.newest_checked_at

    assert bounded.entries_checked == 1
    assert not bounded.complete, "a truncated walk must never claim to have covered the log"

    # And the default must stay unbounded. This one is structural because the behaviour
    # it guards only appears past the old ceiling: proving it by writing 1,001 entries
    # would cost a minute of CI to assert a one-token property, and a future edit that
    # reintroduces `limit: int = 1000` would sail through a table this size otherwise.
    assert inspect.signature(verify_chain).parameters["limit"].default is None, (
        "a bounded default answers a smaller question in the same words"
    )


async def test_a_break_does_not_stop_the_walk() -> None:
    """One broken link must not switch off verification of everything after it.

    THE ATTACK THIS CLOSES. The walk used to return at the first mismatch, so the
    cheapest way to hide an edit made last night was to also damage something from six
    months ago: the verifier would report the old break forever and never reach the new
    one. Coverage an attacker can disable from outside the window they care about is not
    evidence. `audit_log` is also append-only, so a break is permanent — meaning that
    design additionally guaranteed a red light that could never go green again, on a
    panel whose whole job is to be read.

    THE SABOTAGE IS ROLLED BACK. The broken row is inserted inside a transaction that
    aborts, so it exists for the duration of the assertion and never lands. Writing a
    deliberately corrupt row into an append-only ledger to prove a point would leave
    every future run of this suite — and every future developer's `verify` — carrying a
    scar this test made.
    """
    marker = f"test.chain_segment.{uuid.uuid4().hex[:12]}"

    with pytest.raises(_AbortError):
        async with untenanted_session() as session:
            # Under the same lock a real writer takes, so nothing else interleaves with
            # the three rows below and the shape being asserted is the one built here.
            await lock_chain(session)
            await write_audit(session, action=f"{marker}.before", actor_type="system")

            # The break: a row whose `prev_hash` names nothing, inserted by hand rather
            # than through `write_audit`, which is exactly how a real one arrives.
            await session.execute(
                text(
                    "INSERT INTO audit_log (id, actor_type, action, at, prev_hash, "
                    "entry_hash, created_at) VALUES (gen_random_uuid(), 'system', :a, "
                    "clock_timestamp(), :bad, :bad, clock_timestamp())"
                ),
                {"a": f"{marker}.broken", "bad": "f" * 64},
            )
            # ...and a well-formed entry after it. `write_audit` reads the head, which is
            # now the corrupt row, so this one chains onto it correctly — the segment
            # after the break is internally sound, which is the property that makes
            # continuing worthwhile rather than merely tidy.
            await write_audit(session, action=f"{marker}.after", actor_type="system")

            # COUNTED BEFORE THE WALK, and compared with `>=` — the same discipline the
            # scope test above spells out, which this one did not follow. It read the
            # count AFTER `verify_chain` and asserted equality, so an audit row written
            # by any other suite in that window made `checked` exceed `entries_checked`
            # and failed a property that had not been violated. `audit_log` is global and
            # append-only; every suite in this repo writes to it.
            counted = (await session.execute(text("SELECT count(*) FROM audit_log"))).scalar() or 0
            verdict = await verify_chain(session)

            # The walk reached the END despite the break — the assertion the old
            # early-return could not have satisfied.
            assert verdict.complete, verdict
            assert verdict.entries_checked >= int(counted), (verdict.entries_checked, counted)
            assert not verdict.ok
            # The hand-written row fails on its own hash (`content`), because `f`*64 is
            # not the HMAC of its own payload. It is named, and the walk carried on.
            assert any(b.kind == "content" for b in verdict.breaks), verdict.breaks
            assert verdict.breaks_found >= 1

            raise _AbortError

    # And the sabotage really is gone, so the next test sees the log it started with.
    async with untenanted_session() as session:
        left_behind = (
            await session.execute(
                text("SELECT count(*) FROM audit_log WHERE action LIKE :like"),
                {"like": f"{marker}.%"},
            )
        ).scalar()
    assert left_behind == 0, "the sabotage must not survive the test that used it"


async def test_a_stale_head_is_reported_as_a_broken_link_not_as_an_edited_row() -> None:
    """An entry that hashes correctly but names the WRONG predecessor must be reported
    as `link`, never as `content`.

    The two kinds decide what an operator does next and are not interchangeable.
    `content` says "somebody edited this row's fields" and sends them looking for the
    edit; `link` says "the row is intact but the chain around it is not" and sends them
    looking for what is MISSING or misordered — a deleted entry, a reordered pair, or
    (the case staged here, and the one that really happened in this repo before the
    chain lock was consulted) two writers that both chained onto the same head. Because
    the recompute runs against the row's OWN `prev_hash`, this row passes the content
    check and can only be caught by the link check; testing content against the EXPECTED
    prev instead would conflate them and report every entry after a deletion as edited.

    THE SABOTAGE IS ROLLED BACK, for the reason `test_a_break_does_not_stop_the_walk`
    gives: `audit_log` is append-only (hard rule 4, and a trigger enforces it), so a
    scar made by a test could never be removed afterwards.
    """
    marker = f"test.chain_link.{uuid.uuid4().hex[:12]}"

    with pytest.raises(_AbortError):
        async with untenanted_session() as session:
            await lock_chain(session)
            before = (await verify_chain(session)).breaks_found

            await write_audit(session, action=f"{marker}.first", actor_type="system")
            stale_head = (
                await session.execute(
                    text("SELECT entry_hash FROM audit_log WHERE action = :a"),
                    {"a": f"{marker}.first"},
                )
            ).scalar()
            await write_audit(session, action=f"{marker}.second", actor_type="system")

            # The racing writer: it read the head before `.second` landed, so its row is
            # perfectly signed and points one entry too far back.
            orphan_id = uuid7()
            payload = {
                "id": str(orphan_id),
                "actor_type": "system",
                "actor_id": None,
                "tenant_id": None,
                "action": f"{marker}.raced",
                "object_type": None,
                "object_id": None,
            }
            await session.execute(
                text(
                    "INSERT INTO audit_log (id, actor_type, action, at, prev_hash, "
                    "entry_hash, created_at) VALUES (:id, 'system', :a, clock_timestamp(), "
                    ":prev, :hash, clock_timestamp())"
                ),
                {
                    "id": orphan_id,
                    "a": f"{marker}.raced",
                    "prev": str(stale_head),
                    "hash": _entry_hash(str(stale_head), payload, _active_key()),
                },
            )

            verdict = await verify_chain(session)

            assert verdict.breaks_found == before + 1, (
                "one misplaced entry is one break, not one per row after it"
            )
            named = [b for b in verdict.breaks if b.entry_id == str(orphan_id)]
            assert named, f"the misplaced entry must be named: {verdict.breaks}"
            assert named[0].kind == "link", (
                "an intact row in the wrong place is a broken LINK — calling it "
                f"`content` sends the investigation after an edit that never happened, "
                f"got {named[0].kind}"
            )
            assert named[0].at is not None, "a break an operator cannot date is a break"
            assert not verdict.ok

            raise _AbortError

    async with untenanted_session() as session:
        left_behind = (
            await session.execute(
                text("SELECT count(*) FROM audit_log WHERE action LIKE :like"),
                {"like": f"{marker}.%"},
            )
        ).scalar()
    assert left_behind == 0, "the sabotage must not survive the test that used it"


async def test_the_report_cap_bounds_what_is_listed_and_never_what_is_counted() -> None:
    """Past `_MAX_REPORTED_BREAKS` the verdict stops LISTING breaks. It must not stop
    COUNTING them.

    An operator reads two numbers off this verdict, and the cap is a trap for exactly
    one of them: a wholesale rewrite of the ledger would show up as a full list of 20
    and, if the count were capped too, as "20 breaks" — which reads like a bounded,
    survivable incident rather than the unbounded one it is. `breaks_found` is kept as
    its own field so the size of the damage survives the truncation of its detail.
    """
    marker = f"test.chain_cap.{uuid.uuid4().hex[:12]}"
    forged = _MAX_REPORTED_BREAKS + 3

    with pytest.raises(_AbortError):
        async with untenanted_session() as session:
            await lock_chain(session)
            before = (await verify_chain(session)).breaks_found

            for index in range(forged):
                await session.execute(
                    text(
                        "INSERT INTO audit_log (id, actor_type, action, at, prev_hash, "
                        "entry_hash, created_at) VALUES (gen_random_uuid(), 'system', :a, "
                        "clock_timestamp(), :bad, :bad, clock_timestamp())"
                    ),
                    {"a": f"{marker}.{index}", "bad": f"{index:02d}" + "f" * 62},
                )

            verdict = await verify_chain(session)

            assert verdict.breaks_found == before + forged, (
                "the count is the size of the damage and must not be truncated"
            )
            assert len(verdict.breaks) == _MAX_REPORTED_BREAKS, (
                "the listed detail is bounded, so a corrupt log cannot exhaust memory"
            )
            assert verdict.breaks_found > len(verdict.breaks), (
                "an operator must be able to see that the list is not the whole story"
            )
            assert verdict.first_bad_entry_id == verdict.breaks[0].entry_id

            raise _AbortError

    async with untenanted_session() as session:
        left_behind = (
            await session.execute(
                text("SELECT count(*) FROM audit_log WHERE action LIKE :like"),
                {"like": f"{marker}.%"},
            )
        ).scalar()
    assert left_behind == 0, "the sabotage must not survive the test that used it"
