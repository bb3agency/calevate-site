"""The two booking jobs behind the in-call call-back tool (D-514), and how they FAIL.

The endpoint acked the caller in milliseconds and wrote nothing, so everything that can
go wrong with "ring me back at four" goes wrong HERE, out of sight of the person who was
promised. That is what these tests are about: `tests/callback_tool_test.py` proves the
endpoint refuses what it must and queues what it may, and `tests/callback_dispatch_test.py`
proves the tick dials through the one gate. Between them sits the job, and its failure
ladder is the part nobody sees.

Four defects are pinned here, and each one is silent in production:

1. **A booking that never happened and never complained.** The engine fetch is the truth
   (D-31); when it fails transiently the job must ask arq to try again (`arq.Retry` and
   nothing else — arq 0.28 retries for `Retry`, `RetryJob` and `CancelledError` alone), and
   when it will never succeed it must ALARM rather than disappear. A caller who was told
   "we will call you at four" and a caller whose booking job died are indistinguishable to
   the caller.
2. **A call-back placed to our own header.** The number is the OTHER party and is chosen
   by direction: inbound → `from_e164`, outbound → `to_e164`. Reversed, the platform rings
   itself at four o'clock and the person waits. Both directions are asserted ON THE NUMBER
   that reached the row, because "a row was written" is true in the broken version too.
3. **A promise attributed to nobody.** An unmappable agent ref or a call with no number
   for the other party must end the job with an alarm — never a row on a guessed tenant
   (hard rule 1), never a silent success.
4. **A caller who changed their mind losing to the job that ran slower.** Two bookings in
   one conversation resolve to the LATER word whichever job commits first, and the loser
   says so (`superseded`) instead of dragging the promise backwards.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.callbacks import service as callbacks
from apps.api.core.errors import ProblemError
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.fake import FakeEngine
from apps.api.engine.vendor_http import EngineRejectedError
from apps.workers import callbacks as worker
from arq import Retry
from calevate_shared.engine import ExecutionSnapshot
from sqlalchemy import text
from tests.conftest import accept_agreements

pytestmark = pytest.mark.anyio

#: The person on the phone. Our own DLT header is the OTHER number in every snapshot
#: below, so a direction bug books this constant's opposite and the assertions catch it.
CALLER = "+919812345675"
OUR_HEADER = "+911140000000"


async def _routed_tenant() -> tuple[uuid.UUID, uuid.UUID, str]:
    """A tenant whose agent the engine's `engine_agent_ref` resolves to.

    That resolution is ALL these jobs need — they write a promise, they do not dial — so
    the fixture supplies exactly it rather than the fuller dialable tenant
    `tests/callback_dispatch_test.py` builds for the gate. Same shape as
    `tests/callback_test.py::_tenant`, including the agreements, which every later gate
    reads and no fixture may assume away.
    """
    created = await admin_service.create_organization(
        name="Callback Promises",
        slug=f"cbw-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    await accept_agreements(tenant_id)
    ref = f"fakeagent_cbw_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r WHERE id = :a"),
            {"r": ref, "a": agent_id},
        )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )
    return tenant_id, agent_id, ref


def _snap(
    execution_id: str,
    ref: str | None,
    *,
    direction: str = "inbound",
    from_e164: str | None = CALLER,
    to_e164: str | None = OUR_HEADER,
) -> ExecutionSnapshot:
    """A call IN PROGRESS. The tool fires mid-call, so `terminal` is false and there is
    no cost, no recording and no transcript — a snapshot built as a completed call would
    model the post-call pipeline's input, not this job's."""
    return ExecutionSnapshot(
        engine_call_id=execution_id,
        engine_agent_ref=ref,
        direction=direction,  # type: ignore[arg-type]
        status="in_progress",
        raw_status="in-progress",
        terminal=False,
        billable_ready=False,
        started_at=datetime.now(UTC) - timedelta(seconds=30),
        from_e164=from_e164,
        to_e164=to_e164,
        engine="fake",
    )


def _stage(monkeypatch: pytest.MonkeyPatch, snapshot: ExecutionSnapshot) -> None:
    """Make the fake engine answer `get_execution` with our call."""

    async def _get(self: FakeEngine, call_id: str) -> ExecutionSnapshot:
        return snapshot

    monkeypatch.setattr(FakeEngine, "get_execution", _get)


def _catch_alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    fired: list[tuple[str, str]] = []
    monkeypatch.setattr(worker, "alert", lambda stage, code, **kw: fired.append((stage, code)))
    return fired


def _breaking_engine(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    """An engine whose authenticated fetch always fails, patched at `get_engine` so the
    ladder is exercised on the job's own call rather than on a helper."""

    class _Broken:
        async def get_execution(self, execution_id: str) -> ExecutionSnapshot:
            raise exc

    monkeypatch.setattr(worker, "get_engine", lambda: _Broken())


async def _book(
    execution_id: str, *, requested_in: timedelta = timedelta(hours=4), **extra: Any
) -> str:
    payload: dict[str, Any] = {
        "engine": "fake",
        "execution_id": execution_id,
        "requested_at": (datetime.now(UTC) + requested_in).isoformat(),
        "booked_at": datetime.now(UTC).isoformat(),
        "note": "wants the evening slot",
        "language": "te",
    }
    payload.update(extra)
    return await worker.book_requested_callback({"job_try": 1}, payload)


async def _rows(tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    """Every promise on this tenant's books. Read through `tenant_session`, so a row
    written to the wrong account is invisible here rather than silently asserted about."""
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, agent_id, phone_e164, requested_at, status, note, "
                    "  source_call_id, lead_id FROM scheduled_callbacks "
                    "ORDER BY requested_at"
                )
            )
        ).mappings()
    return [dict(row) for row in rows]


# --- 1. the fetch that is the truth, and its ladder ---------------------------


async def test_a_transient_fetch_failure_asks_arq_to_try_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`arq.Retry` OR NOTHING. arq 0.28 retries a job for `Retry`, `RetryJob` and
    `CancelledError` and for no other exception — every other one sets `finish=True` and
    the job leaves the queue after ONE attempt. So a job that signalled "the vendor blipped,
    try again" by re-raising the vendor's own error would drop the promise on the first
    hiccup, with `max_tries` in the settings and nothing behind it. And nothing is alarmed:
    a blip that the ladder is about to absorb is not an operator's problem."""
    monkeypatch.setattr(worker, "_retry_after", lambda attempt: 30.0)
    fired = _catch_alerts(monkeypatch)
    _breaking_engine(
        monkeypatch,
        ProblemError(
            kind="dependency",
            code="engine_unreachable",
            title="Voice engine unreachable",
            detail="The voice platform did not respond.",
        ),
    )
    with pytest.raises(Retry) as raised:
        await _book("exec_transient")
    assert raised.value.defer_score is not None, "a retry with no defer hammers the vendor"
    assert fired == [], "a blip inside the ladder woke an operator"


async def test_a_fetch_that_will_never_succeed_alarms_rather_than_disappearing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caller was told we would ring them. A booking job that dies quietly leaves a
    person waiting by a phone and leaves us with nothing to look at — so a NON-transient
    failure (the engine's own considered verdict, `_is_transient`) alarms under a code
    that names the feature, and then re-raises so arq records the failure too."""
    fired = _catch_alerts(monkeypatch)
    _breaking_engine(monkeypatch, EngineRejectedError(status=400))
    with pytest.raises(ProblemError):
        await _book("exec_rejected")
    assert ("WORKER_TERMINAL", "in_call_callback_unresolved") in fired


async def test_the_ladder_ends_at_the_attempt_cap_instead_of_retrying_for_ever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A TRANSIENT failure past `WORKER_MAX_TRIES` stops being transient in practice: the
    promise has a time on it, and a job still asking for one more attempt an hour after the
    caller expected the phone to ring is worse than a job that said so. The cap is read
    from `core.queue` rather than restated here, so raising it moves this test with it."""
    fired = _catch_alerts(monkeypatch)
    _breaking_engine(
        monkeypatch,
        ProblemError(
            kind="dependency",
            code="engine_unreachable",
            title="Voice engine unreachable",
            detail="The voice platform did not respond.",
        ),
    )
    with pytest.raises(ProblemError):
        await worker.cancel_requested_callback(
            {"job_try": WORKER_MAX_TRIES}, {"engine": "fake", "execution_id": "exec_capped"}
        )
    assert ("WORKER_TERMINAL", "in_call_callback_unresolved") in fired


# --- 2. who the promise belongs to -------------------------------------------


async def test_an_execution_that_maps_to_no_agent_is_alarmed_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hard rule 1, at the one place an adapter could be tempted to guess. The engine's
    agent ref is the ONLY bridge to a tenant; when it resolves to nothing there is no
    account this promise could lawfully be written to, so both jobs stop and say so. The
    cancel job is asserted alongside because a cancellation that silently never happens is
    the same defect as a booking that silently never happens."""
    fired = _catch_alerts(monkeypatch)
    _stage(monkeypatch, _snap("exec_unmapped", f"fakeagent_nobody_{uuid.uuid4().hex[:8]}"))
    assert await _book("exec_unmapped") == "unattributable"
    assert (
        await worker.cancel_requested_callback(
            {"job_try": 1}, {"engine": "fake", "execution_id": "exec_unmapped"}
        )
        == "unattributable"
    )
    assert fired == [
        ("WORKER_TERMINAL", "in_call_callback_agent_unmapped"),
        ("WORKER_TERMINAL", "in_call_callback_agent_unmapped"),
    ]


async def test_a_call_with_no_number_for_the_other_party_is_alarmed_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A promise with no number is a row that can never be dialled and will sit in the
    client's list looking like a scheduled call. The alarm names the direction, which is
    the one fact that makes it diagnosable — and no number goes into the alert (hard rule
    6), which is why `detail` carries the direction and not the snapshot."""
    tenant_id, _agent_id, ref = await _routed_tenant()
    fired = _catch_alerts(monkeypatch)
    _stage(monkeypatch, _snap("exec_nonumber", ref, direction="inbound", from_e164=None))
    assert await _book("exec_nonumber") == "unattributable"
    assert ("WORKER_TERMINAL", "in_call_callback_unattributable") in fired
    assert await _rows(tenant_id) == []


# --- 3. WHICH number ----------------------------------------------------------


async def test_an_inbound_caller_is_rung_back_on_their_own_number_and_not_on_our_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**THE DEFECT THIS FILE EXISTS FOR.** On an inbound call the person is `from_e164`
    and our DLT header is `to_e164`; reading the wrong one books a call-back from the
    platform to the platform, and every other assertion anyone would write — a row exists,
    the tenant is right, the time is right — is TRUE in the broken version. So the
    assertion is on the number itself, and the header is asserted absent."""
    tenant_id, agent_id, ref = await _routed_tenant()
    _stage(monkeypatch, _snap("exec_inbound", ref, direction="inbound"))
    assert await _book("exec_inbound") == "booked"
    rows = await _rows(tenant_id)
    assert [row["phone_e164"] for row in rows] == [CALLER], "the platform booked itself"
    assert rows[0]["agent_id"] == agent_id
    assert rows[0]["note"] == "wants the evening slot"


async def test_an_outbound_call_books_the_number_we_dialled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the same rule, and it must be read the opposite way round: on an
    outbound call OUR header is `from_e164`. One direction asserted alone passes with the
    fields swapped, which is why both are here."""
    tenant_id, _agent_id, ref = await _routed_tenant()
    _stage(
        monkeypatch,
        _snap("exec_outbound", ref, direction="outbound", from_e164=OUR_HEADER, to_e164=CALLER),
    )
    assert await _book("exec_outbound") == "booked"
    assert [row["phone_e164"] for row in await _rows(tenant_id)] == [CALLER]


# --- 4. what the promise points at -------------------------------------------


async def test_the_promise_is_pointed_at_the_call_and_lead_it_was_made_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both pointers are OPTIONAL and both are worth having when they exist: without them
    a client reading "call-back at four" cannot get from it to the conversation that
    produced it. The `calls` row is written by the status webhook, which usually precedes
    an in-call tool call — so when it is there, it is linked."""
    tenant_id, agent_id, ref = await _routed_tenant()
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    call_id, lead_id = uuid7(), uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "created_at, updated_at) VALUES (:i, :t, :a, :p, 'Priya', 'inbound_call', "
                "'new', now(), now())"
            ),
            {"i": lead_id, "t": tenant_id, "a": agent_id, "p": CALLER},
        )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "from_e164, status, lead_id, created_at, updated_at) VALUES (:i, :t, :a, :e, "
                "'inbound', :p, 'in_progress', :l, now(), now())"
            ),
            {
                "i": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": execution_id,
                "p": CALLER,
                "l": lead_id,
            },
        )
        await session.commit()

    _stage(monkeypatch, _snap(execution_id, ref))
    assert await _book(execution_id) == "booked"
    row = (await _rows(tenant_id))[0]
    assert row["source_call_id"] == call_id
    assert row["lead_id"] == lead_id


async def test_a_promise_made_before_the_call_row_arrived_is_still_a_promise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE ARM THAT MUST NOT FAIL. The status webhook is at-most-once (D-31) and the
    extraction that writes the lead has certainly not run — the call is still in progress.
    Neither absence is worth failing for: what the dial needs is the number and the agent,
    and it has both. A job that raised on a missing `calls` row would drop the promises
    made on exactly the calls whose webhook was lost."""
    tenant_id, _agent_id, ref = await _routed_tenant()
    _stage(monkeypatch, _snap("exec_no_call_row", ref))
    assert await _book("exec_no_call_row") == "booked"
    row = (await _rows(tenant_id))[0]
    assert row["source_call_id"] is None and row["lead_id"] is None
    assert row["status"] == "scheduled"


async def test_an_earlier_booking_arriving_late_does_not_drag_the_promise_backwards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "Make it five, actually." Two bookings from one conversation, and the jobs may run
    in either order: the LATER WORD wins whichever commits first, and the loser reports
    `superseded` rather than an error. Without the outcome string, "the tool fired and
    nothing happened" is only answerable from a transcript."""
    tenant_id, _agent_id, ref = await _routed_tenant()
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    _stage(monkeypatch, _snap(execution_id, ref))
    later_said_at = datetime.now(UTC)
    assert (
        await _book(
            execution_id,
            requested_in=timedelta(hours=5),
            booked_at=later_said_at.isoformat(),
        )
        == "booked"
    )
    # The FIRST thing they said, arriving second.
    assert (
        await _book(
            execution_id,
            requested_in=timedelta(hours=4),
            booked_at=(later_said_at - timedelta(seconds=30)).isoformat(),
        )
        == "superseded"
    )
    rows = await _rows(tenant_id)
    assert len(rows) == 1, "one conversation, one promise"
    assert rows[0]["requested_at"] > later_said_at + timedelta(hours=4, minutes=30)


# --- 5. calling it off --------------------------------------------------------


async def test_calling_it_off_ends_every_live_promise_to_that_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EVERY live promise, not the one from this conversation, because that is what the
    caller meant: somebody who says "don't ring me back" while a call-back booked last
    week is still pending has not asked us to keep that one. It is NOT an opt-out — the
    number is not suppressed — and it is scoped to the tenant they are speaking to, which
    `tenant_session` makes structural rather than a WHERE clause."""
    tenant_id, agent_id, ref = await _routed_tenant()
    async with tenant_session(tenant_id) as session:
        for hours in (4, 30):
            await callbacks.book(
                session,
                callback_id=uuid7(),
                tenant_id=tenant_id,
                agent_id=agent_id,
                source_call_id=None,
                source_execution_id=f"exec_{uuid.uuid4().hex[:10]}",
                lead_id=None,
                phone_e164=CALLER,
                requested_at=datetime.now(UTC) + timedelta(hours=hours),
                booked_at=datetime.now(UTC),
                note=None,
                language=None,
            )
        await session.commit()

    _stage(monkeypatch, _snap("exec_cancel", ref))
    assert (
        await worker.cancel_requested_callback(
            {"job_try": 1}, {"engine": "fake", "execution_id": "exec_cancel"}
        )
        == "cancelled=2"
    )
    assert {row["status"] for row in await _rows(tenant_id)} == {"cancelled"}
    async with tenant_session(tenant_id) as session:
        suppressed = (
            await session.execute(
                text("SELECT count(*) FROM dnc_list WHERE phone_e164 = :p"), {"p": CALLER}
            )
        ).scalar()
    assert suppressed == 0, "'don't ring me back' was read as 'never call me again'"


# --- 6. hard rule 6 -----------------------------------------------------------


async def test_no_number_reaches_a_log_line_on_either_job(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Ids and counts. The number is the one thing both of these jobs are about and the
    one thing neither may log — including in the alert `detail`, which is why the
    unattributable alarm names the direction instead."""
    _tenant_id, _agent_id, ref = await _routed_tenant()
    _stage(monkeypatch, _snap("exec_quiet", ref))
    with caplog.at_level(logging.DEBUG):
        await _book("exec_quiet")
        await worker.cancel_requested_callback(
            {"job_try": 1}, {"engine": "fake", "execution_id": "exec_quiet"}
        )
    emitted = "\n".join(record.getMessage() + str(record.__dict__) for record in caplog.records)
    assert CALLER not in emitted, "a phone number reached the logs (hard rule 6)"
