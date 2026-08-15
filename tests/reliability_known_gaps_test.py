"""Reliability defects that are OPEN, recorded so they cannot be quietly rediscovered.

Every entry below was found while taking the ingest/outbox/poller path end to end, is
real, and could not be closed from inside that slice — each one names the specific reason
and the specific act that closes it. None of them is waiting on a vendor: they are
waiting on a file this slice was not allowed to touch, or on a migration that cannot be
written while other agents hold the single migration head.

**THE ASSERTION IS AN EQUALITY, in the shape `tests/engine_name_drift_test.py::
KNOWN_OPEN_COPIES` established.** Each key has a probe that answers "is this still true?"
and the test asserts the set of still-open gaps EQUALS the recorded set. So an entry
cannot outlive its defect — fixing one turns this file red and forces the entry's
deletion in the same change — and a comment or a TODO, which can, is not an option.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from apps.api.db.base import uuid7
from apps.api.db.session import untenanted_session
from apps.api.ops.routes import PlatformStateOut
from apps.api.reliability import service as rel
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Gap key → why it is open, and WHAT CLOSES IT. Delete an entry the moment its probe
#: below stops finding the defect; the equality assertion makes that mandatory.
#: **EMPTY, and every probe below outlives it.** All four gaps this file shipped with are
#: closed: the natural-key index is migration `b8d3f47c2a19`, the per-message retry
#: backoff and the `deferred` count are in `reliability/service.py`, and the two stale
#: docstrings name `_pipeline_settled`. The dict stays because the equality is what makes
#: the next recording honest — an entry added here without a fix is a claim somebody
#: looked, and one left after a fix fails just as loudly.
KNOWN_OPEN_RELIABILITY_GAPS: dict[str, str] = {}


async def _usage_events_lacks_a_natural_key_index() -> bool:
    """No UNIQUE index on `usage_events` covering the call and the unit it priced."""
    async with untenanted_session() as session:
        definitions = [
            str(row[0])
            for row in (
                await session.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE schemaname = 'public' AND tablename = 'usage_events'"
                    )
                )
            ).all()
        ]
    return not any("UNIQUE" in d and "call_id" in d and "unit_type" in d for d in definitions)


async def _outbox_retry_is_immediate() -> bool:
    """A message with budget left is re-claimable at once, with no wait on the row.

    Behavioural rather than a source grep: what matters is whether the next tick can pick
    it up, not how the SQL happens to spell it.
    """
    message_id = uuid7()
    marker = f"knowngap-{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO outbox_messages (id, queue, job, payload, status, attempt_count, "
                "created_at, updated_at) VALUES (:id, 'default', 'notify_hot_lead', "
                "CAST(:p AS jsonb), 'pending', 1, now(), now())"
            ),
            {"id": message_id, "p": f'{{"marker": "{marker}"}}'},
        )
        await rel.mark_outbox_failed(
            session, message_id=message_id, error="the receiver is gone", attempt_count=1
        )
        waiting = (
            await session.execute(
                text(
                    "SELECT locked_until IS NOT NULL AND locked_until > now() "
                    "FROM outbox_messages WHERE id = :id"
                ),
                {"id": message_id},
            )
        ).scalar()
        await session.execute(
            text("DELETE FROM outbox_messages WHERE id = :id"), {"id": message_id}
        )
    return not bool(waiting)


async def _platform_read_publishes_no_deferred_count() -> bool:
    """Nothing on the ops platform payload counts messages waiting on a backoff."""
    names = set(PlatformStateOut.model_fields)
    dlq = PlatformStateOut.model_fields["outbox_dead_letters"].annotation
    names |= set(getattr(dlq, "model_fields", {}))
    return not any("defer" in name or "waiting" in name for name in names)


async def _tests_still_name_the_old_probe() -> bool:
    """Any test file but THIS one that still spells `_already_completed`.

    Scanned rather than listed by name, so a third file that inherits the stale
    explanation is caught by the same equality instead of joining it silently.
    """
    return any(
        "_already_completed" in path.read_text(encoding="utf-8")
        for path in sorted((REPO_ROOT / "tests").glob("*_test.py"))
        if path.name != Path(__file__).name
    )


#: key → the probe that answers "is this gap still real?". Every probe is async so the
#: assertion below reads as one loop rather than as two kinds of entry.
#:
#: **THE PROBES OUTLIVE THEIR ENTRIES, DELIBERATELY, and the assertion below is shaped
#: for it.** This dict shipped required to EQUAL `KNOWN_OPEN_RELIABILITY_GAPS`, which
#: meant closing a gap deleted its probe along with its entry — and the predicate that
#: had just been proved able to detect the defect was thrown away at the exact moment it
#: became a regression test. It is a superset now: an entry must have a probe (a
#: recording with nothing to check it is a TODO), and a probe with no entry is a CLOSED
#: gap whose predicate must keep answering False. If it ever answers True again it shows
#: up as "open but not recorded" and fails on the same line, with the same message, as
#: the day it was found.
PROBES: dict[str, Callable[[], Awaitable[bool]]] = {
    "usage_events_has_no_natural_key_index": _usage_events_lacks_a_natural_key_index,
    "outbox_per_message_retry_has_no_backoff": _outbox_retry_is_immediate,
    "ops_console_cannot_see_deferred_outbox_messages": _platform_read_publishes_no_deferred_count,
    "existing_tests_name_a_probe_that_no_longer_exists": _tests_still_name_the_old_probe,
}


async def test_every_recorded_gap_is_still_open_and_no_other_is() -> None:
    """The equality. Fixing a gap fails here until its entry is deleted; recording a gap
    that is not real fails here immediately; and a gap that is fixed, unrecorded and then
    BROKEN AGAIN fails here too, because its probe was kept."""
    still_open = {key for key, probe in PROBES.items() if await probe()}

    unprobed = set(KNOWN_OPEN_RELIABILITY_GAPS) - set(PROBES)
    assert unprobed == set(), (
        f"these recorded gaps have no probe, so the equality below cannot close them: "
        f"{sorted(unprobed)}"
    )
    assert still_open == set(KNOWN_OPEN_RELIABILITY_GAPS), (
        "the recorded reliability gaps and the real ones disagree.\n"
        f"  fixed but still recorded: {sorted(set(KNOWN_OPEN_RELIABILITY_GAPS) - still_open)}\n"
        f"  open but not recorded:    {sorted(still_open - set(KNOWN_OPEN_RELIABILITY_GAPS))}"
    )


def test_every_gap_says_what_closes_it() -> None:
    """A recorded gap with no named remedy is a TODO wearing a test's clothes."""
    silent = [key for key, why in KNOWN_OPEN_RELIABILITY_GAPS.items() if "CLOSED BY" not in why]
    assert silent == [], f"these entries do not say what would close them: {silent}"
