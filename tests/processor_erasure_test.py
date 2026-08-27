"""The erasure obligations that leave this building, and the claim we must not make (D-433).

An erasure deletes our rows and our bytes and issues a certificate. The voice platform
keeps its own copy of the recording and the transcript, and
`docs/evidence/subprocessor-erasure-reach.md` §1 enumerates every `DELETE` route that
platform documents: none reaches an execution at subject granularity.

These tests hold three lines:

1. **The register may not quietly re-narrow.** The certificate's whole value is that it
   states what an erasure could NOT do; the failure this file exists to catch is someone
   deleting a limitation to make a document read better.
2. **Hard rule 6 on `vendor_refs`.** The column exists so an operator can quote vendor ids
   at a support desk. It is JSONB and would take anything, so the ban on phone numbers is
   tested in BOTH places it is enforced — the Python writer and the database CHECK.
3. **The task cannot be closed by accident.** Every transition is guarded on the state it
   comes from, so re-running an operator command cannot launder an obligation.

Run: uv run pytest tests/processor_erasure_test.py -q
"""

from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance import deletion
from apps.api.compliance.processor_erasure import (
    OVERDUE_AFTER_DAYS,
    PROCESSORS,
    VendorRefRejectedError,
    assert_vendor_refs_are_id_shaped,
    open_tasks_for_request,
    overdue_tasks,
    record_answer,
    record_request_sent,
)
from apps.api.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

# Only the DB-backed tests are async; the register and hard-rule-6 guards are pure, so
# the mark is applied per-test rather than to the module (a module-wide asyncio mark on a
# sync test is a pytest warning and, worse, reads as if it were doing something).
asyncio_test = pytest.mark.asyncio

# A real Bolna execution id, from the vendor's own worked example
# (`bolna-findings/mirror/pages/api-reference/executions/get_execution.md:53`). It is the
# regression fixture for the false positive the first version of the digit rule had:
# "7140255" is a 7-digit run, and a rule that refused digit RUNS refused this.
_REAL_EXECUTION_ID = "b7140255-af33-4608-8e97-04dd944b8e48"


async def _tenant() -> UUID:
    created = await admin_service.create_organization(
        name="Erasure Reach",
        slug=f"proc-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"]))


# ---------------------------------------------------------------------------
# 1. The register: the claim we are not entitled to make
# ---------------------------------------------------------------------------


def test_the_register_names_every_processor_that_holds_call_content() -> None:
    """The over-claim this whole change exists to remove.

    The register used to name the voice engine and stop. Sarvam receives the call audio
    and the RAW transcript; Azure OpenAI receives the caller's conversation turn by turn.
    A certificate that lists what an erasure could not reach while omitting two processors
    holding the conversation is misleading by omission — the "control that reports success
    for work it did not do" failure this repository cares most about.
    """
    prose = " ".join(deletion.ERASURE_LIMITATIONS).lower()
    assert "speech service" in prose
    assert "language model" in prose
    outcomes = {e.outcome for e in deletion.ERASURE_EXCEPTIONS}
    assert deletion.PROCESSOR_OUTCOME in outcomes
    assert deletion.ENGINE_OUTCOME in outcomes


def test_the_register_no_longer_calls_the_vendor_api_undocumented() -> None:
    """SABOTAGE GUARD: the stale evidence class.

    "Undocumented" invites the next reader to go looking for a deletion API. The
    documentation is complete, mirrored and hash-verified, and it documents NO
    subject-granular deletion — an enumerated absence, not an open question. Reverting to
    the old word would send somebody on a search that has already been done.
    """
    prose = " ".join(deletion.ERASURE_LIMITATIONS).lower()
    assert "undocumented" not in prose, (
        "the vendor's deletion surface is enumerated in "
        "docs/evidence/subprocessor-erasure-reach.md §1, not unknown"
    )


def test_the_engine_entry_states_the_granularity_and_not_just_a_shrug() -> None:
    """An operator has to know WHY there is no deletion, because the reason decides what
    they do next: the vendor can delete a whole agent, so a TENANT erasure has a remedy a
    subject erasure does not."""
    entry = next(e for e in deletion.ERASURE_EXCEPTIONS if e.outcome == deletion.ENGINE_OUTCOME)
    assert "agent" in entry.why.lower()
    # The REMEDY, not the gate number. `authority` is rendered on the client's own
    # data-rights screen and reaches a data principal and a regulator through them, so it
    # cites what that reader can open — the vendor's published documentation and the
    # contractual fix — while `OPERATIONS §2` gate 12(f)/36 stays in the source comment
    # above the entry, where the person who closes it reads.
    assert "contract" in entry.authority.lower()
    assert "published" in entry.authority.lower()


# ---------------------------------------------------------------------------
# 2. Hard rule 6, in both places it is enforced
# ---------------------------------------------------------------------------


def test_a_phone_number_is_refused_as_a_vendor_reference() -> None:
    """The near-miss this column was designed around: the consent ledger's evidence field
    was found storing raw phone numbers. This column is JSONB and would take one."""
    with pytest.raises(VendorRefRejectedError, match="entirely digits"):
        assert_vendor_refs_are_id_shaped(["919876543210"])


def test_transcript_text_is_refused_as_a_vendor_reference() -> None:
    with pytest.raises(VendorRefRejectedError, match="id-shaped"):
        assert_vendor_refs_are_id_shaped(["caller asked to be removed from the list"])


def test_a_real_execution_id_is_accepted() -> None:
    """THE REGRESSION. The first version of the digit rule refused any 7+ digit run
    anywhere, and this id contains "7140255" — so it rejected the vendor's own documented
    example on the first test row. A control that refuses legitimate work is worse than
    one that is merely absent, because it fails silently in production."""
    assert_vendor_refs_are_id_shaped([_REAL_EXECUTION_ID])


def test_a_rejected_reference_is_raised_and_never_filtered_away() -> None:
    """Dropping the bad entry would leave a task naming fewer executions than the erasure
    found, and an operator would send the vendor an incomplete list believing it complete."""
    with pytest.raises(VendorRefRejectedError):
        assert_vendor_refs_are_id_shaped([_REAL_EXECUTION_ID, "919876543210"])


@asyncio_test
async def test_the_database_refuses_a_phone_number_even_without_the_python_writer() -> None:
    """The Python guard protects the callers that use it; the CHECK protects the table.

    Written as raw SQL on purpose — this is the path a migration, an incident-time INSERT
    or a future writer that forgot the helper would take.
    """
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(IntegrityError, match="vendor_refs_carry_no_phone_number"):
            await session.execute(
                text(
                    "INSERT INTO processor_erasure_tasks "
                    "(id, tenant_id, request_ref, request_kind, processor, subject_ref, "
                    " vendor_refs) VALUES "
                    "(gen_random_uuid(), :tid, gen_random_uuid(), 'subject', "
                    " 'voice_engine', 'abc123', '[\"919876543210\"]')"
                ),
                {"tid": tenant_id},
            )


@asyncio_test
async def test_the_database_refuses_free_text_in_vendor_refs() -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(IntegrityError, match="vendor_refs_are_id_shaped"):
            await session.execute(
                text(
                    "INSERT INTO processor_erasure_tasks "
                    "(id, tenant_id, request_ref, request_kind, processor, subject_ref, "
                    " vendor_refs) VALUES "
                    "(gen_random_uuid(), :tid, gen_random_uuid(), 'subject', "
                    " 'voice_engine', 'abc123', '[\"ring me on 98765 43210\"]')"
                ),
                {"tid": tenant_id},
            )


@asyncio_test
async def test_a_subject_task_cannot_exist_without_naming_its_subject() -> None:
    """A task with no `subject_ref` is one an operator cannot tie back to an erasure."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(IntegrityError, match="a_subject_task_names_its_subject"):
            await session.execute(
                text(
                    "INSERT INTO processor_erasure_tasks "
                    "(id, tenant_id, request_ref, request_kind, processor, vendor_refs) "
                    "VALUES (gen_random_uuid(), :tid, gen_random_uuid(), 'subject', "
                    " 'voice_engine', '[]')"
                ),
                {"tid": tenant_id},
            )


# ---------------------------------------------------------------------------
# 3. The lifecycle
# ---------------------------------------------------------------------------


@asyncio_test
async def test_opening_tasks_is_idempotent_across_a_retry() -> None:
    """The erasure job has a retry ladder. A replay must not hand an operator the same
    vendor request twice — two tasks would be two emails and two clocks for one copy."""
    tenant_id = await _tenant()
    request_ref = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        first = await open_tasks_for_request(
            session,
            tenant_id=tenant_id,
            request_ref=request_ref,
            request_kind="subject",
            subject_ref="abc123",
            vendor_refs=[_REAL_EXECUTION_ID],
        )
        second = await open_tasks_for_request(
            session,
            tenant_id=tenant_id,
            request_ref=request_ref,
            request_kind="subject",
            subject_ref="abc123",
            vendor_refs=[_REAL_EXECUTION_ID],
        )
    assert first == len(PROCESSORS)
    assert second == 0


@asyncio_test
async def test_the_operator_path_records_the_request_and_the_answer() -> None:
    tenant_id = await _tenant()
    request_ref = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await open_tasks_for_request(
            session,
            tenant_id=tenant_id,
            request_ref=request_ref,
            request_kind="subject",
            subject_ref="abc123",
            vendor_refs=[_REAL_EXECUTION_ID],
            processors=("voice_engine",),
        )
        tasks = await overdue_tasks(session, tenant_id=tenant_id, min_days=0)
        assert len(tasks) == 1
        assert tasks[0].vendor_refs == [_REAL_EXECUTION_ID]
        task_id = tasks[0].id

        assert await record_request_sent(session, task_id=task_id, vendor_reference="TCK-1")
        assert await record_answer(session, task_id=task_id, outcome="confirmed", note=None)
        # Answered tasks leave the outstanding list — which is what makes the alarm
        # quiet down for the right reason rather than by being silenced.
        assert await overdue_tasks(session, tenant_id=tenant_id, min_days=0) == []


@asyncio_test
async def test_a_task_cannot_be_marked_sent_twice() -> None:
    """Re-running the operator command must not reset the clock on an obligation."""
    tenant_id = await _tenant()
    request_ref = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await open_tasks_for_request(
            session,
            tenant_id=tenant_id,
            request_ref=request_ref,
            request_kind="subject",
            subject_ref="abc123",
            vendor_refs=[_REAL_EXECUTION_ID],
            processors=("voice_engine",),
        )
        task_id = (await overdue_tasks(session, tenant_id=tenant_id, min_days=0))[0].id
        assert await record_request_sent(session, task_id=task_id, vendor_reference=None)
        assert not await record_request_sent(session, task_id=task_id, vendor_reference=None)


@asyncio_test
async def test_an_unsent_task_cannot_be_answered() -> None:
    """A task nobody asked about cannot have an answer. Allowing it would let an operator
    close an obligation they never discharged."""
    tenant_id = await _tenant()
    request_ref = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await open_tasks_for_request(
            session,
            tenant_id=tenant_id,
            request_ref=request_ref,
            request_kind="subject",
            subject_ref="abc123",
            vendor_refs=[_REAL_EXECUTION_ID],
            processors=("voice_engine",),
        )
        task_id = (await overdue_tasks(session, tenant_id=tenant_id, min_days=0))[0].id
        assert not await record_answer(session, task_id=task_id, outcome="confirmed", note=None)


@asyncio_test
async def test_a_refusal_is_a_recordable_outcome_and_not_an_error() -> None:
    """A vendor saying "we cannot delete one caller's executions" is the most important
    thing anyone will learn on this axis. Burying it in a failure path would lose it."""
    tenant_id = await _tenant()
    request_ref = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await open_tasks_for_request(
            session,
            tenant_id=tenant_id,
            request_ref=request_ref,
            request_kind="subject",
            subject_ref="abc123",
            vendor_refs=[_REAL_EXECUTION_ID],
            processors=("voice_engine",),
        )
        task_id = (await overdue_tasks(session, tenant_id=tenant_id, min_days=0))[0].id
        await record_request_sent(session, task_id=task_id, vendor_reference=None)
        assert await record_answer(
            session, task_id=task_id, outcome="refused", note="no per-subject deletion"
        )
        status = (
            await session.execute(
                text("SELECT status FROM processor_erasure_tasks WHERE id = :tid"),
                {"tid": task_id},
            )
        ).scalar()
    assert status == "refused"


@asyncio_test
async def test_a_fresh_task_is_not_yet_overdue() -> None:
    """The alarm must page on a neglected obligation, not on a normal vendor turnaround."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await open_tasks_for_request(
            session,
            tenant_id=tenant_id,
            request_ref=uuid.uuid4(),
            request_kind="subject",
            subject_ref="abc123",
            vendor_refs=[_REAL_EXECUTION_ID],
            processors=("voice_engine",),
        )
        assert await overdue_tasks(session, tenant_id=tenant_id) == []
        assert OVERDUE_AFTER_DAYS == 30


# ---------------------------------------------------------------------------
# 4. The wiring — a table nobody writes is a defect that looks like progress
# ---------------------------------------------------------------------------


@asyncio_test
async def test_a_real_erasure_opens_a_voice_platform_task_naming_the_executions() -> None:
    """END TO END, through the actual worker.

    The failure this catches is the one CLAUDE.md calls a defect that looks like
    progress: a table, a runbook, an alarm and a script, and nothing in production
    writing a row. If `execute_deletion_request` stops opening tasks, every other test in
    this file still passes and the obligation silently stops being recorded.
    """
    from apps.workers.retention import execute_deletion_request

    tenant_id = await _tenant()
    phone = f"+9198{uuid.uuid4().int % 100000000:08d}"
    execution_id = str(uuid.uuid4())
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(
                text("SELECT id FROM agents WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                " status, from_e164, to_e164, started_at, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :t, :a, :e, 'inbound', 'completed', :p, :p, "
                " now(), now(), now())"
            ),
            {"t": tenant_id, "a": agent_id, "e": execution_id, "p": phone},
        )
        request_id = (
            await session.execute(
                text(
                    "INSERT INTO deletion_requests (id, tenant_id, phone_e164, subject_ref, "
                    " scope, requested_at, created_at) "
                    "VALUES (gen_random_uuid(), :t, :p, :r, 'all', now(), now()) "
                    "RETURNING id"
                ),
                {"t": tenant_id, "p": phone, "r": "deadbeef"},
            )
        ).scalar()

    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(request_id)})

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT processor, status, vendor_refs FROM processor_erasure_tasks "
                    "WHERE request_ref = :r"
                ),
                {"r": request_id},
            )
        ).all()
    # Exactly one, and it is the platform whose copy a person can actually get deleted.
    assert [r.processor for r in rows] == ["voice_engine"]
    assert rows[0].status == "open"
    # The vendor's OWN execution id, which is what makes the request actionable rather
    # than a letter asking them to find "some calls".
    assert rows[0].vendor_refs == [execution_id]


@asyncio_test
async def test_a_settled_obligation_records_when_the_vendor_answered() -> None:
    """`answered_at` has a reader, and it is the one that matters.

    Before a client tells a data principal "the platform deleted its copy", somebody has
    to be able to say WHEN it confirmed. The certificate cannot carry that — it is issued
    weeks earlier and hard rule 4 forbids back-filling a stored proof — so the settled
    view is where the answer lives. A column written and never read would let that
    question go unanswerable while looking fine.
    """
    from apps.api.compliance.processor_erasure import settled_tasks

    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await open_tasks_for_request(
            session,
            tenant_id=tenant_id,
            request_ref=uuid.uuid4(),
            request_kind="subject",
            subject_ref="abc123",
            vendor_refs=[_REAL_EXECUTION_ID],
            processors=("voice_engine",),
        )
        task_id = (await overdue_tasks(session, tenant_id=tenant_id, min_days=0))[0].id
        assert await settled_tasks(session, tenant_id=tenant_id) == []
        await record_request_sent(session, task_id=task_id, vendor_reference=None)
        await record_answer(session, task_id=task_id, outcome="confirmed", note=None)
        settled = await settled_tasks(session, tenant_id=tenant_id)
    assert [t.status for t in settled] == ["confirmed"]
    assert settled[0].answered_at is not None


@asyncio_test
async def test_an_unanswered_vendor_obligation_pages_with_its_own_alarm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sweep query runs, and it pages SEPARATELY from the stuck-job alarm.

    Two reasons this is a behavioural test and not a wiring assertion. First, the query
    is raw SQL that nothing else executes, so a typo in it would surface only in
    production, on the alarm guarding a statutory right. Second, the two alarms mean
    opposite things — `erasure_requests_overdue` says a job of OURS was lost and the fix
    is to re-queue it; `processor_erasure_overdue` says the erasure ran perfectly and a
    vendor copy is still there, where re-queueing does nothing. Merging them would make
    an operator do the wrong thing.
    """
    from apps.workers import dispatcher

    calls: list[tuple[str, str, str]] = []

    def _capture(stage: str, code: str, detail: str = "", **_: object) -> None:
        calls.append((stage, code, detail))

    tenant_id = await _tenant()

    async def _one() -> list[UUID]:
        return [tenant_id]

    monkeypatch.setattr(dispatcher, "alert", _capture)
    monkeypatch.setattr(dispatcher, "_all_tenants", _one)

    async with tenant_session(tenant_id) as session:
        await open_tasks_for_request(
            session,
            tenant_id=tenant_id,
            request_ref=uuid.uuid4(),
            request_kind="subject",
            subject_ref="abc123",
            vendor_refs=[_REAL_EXECUTION_ID],
            processors=("voice_engine",),
        )
        # Age it past the vendor clock. Backdating is the only way to test a 30-day
        # bound without a 30-day test.
        await session.execute(
            text(
                "UPDATE processor_erasure_tasks SET opened_at = now() - "
                "make_interval(days => :d) WHERE tenant_id = :t"
            ),
            {"d": OVERDUE_AFTER_DAYS + 1, "t": tenant_id},
        )

    await dispatcher.report_overdue_erasures({})

    raised = [c for c in calls if c[1] == "processor_erasure_overdue"]
    assert raised, "an unanswered vendor erasure obligation must page"
    detail = raised[0][2]
    # The halves are reported apart: `unasked` is ours to fix, `unanswered` is the
    # vendor's, and an operator who cannot tell them apart chases the wrong one.
    assert "1 never sent to the processor" in detail
    assert "runbooks/processor-erasure.md" in detail
    # And it must NOT masquerade as a stuck job.
    assert not [c for c in calls if c[1] == "erasure_requests_overdue"]


# --- the three argument guards, which are the API's edge and not decoration -----------
#
# WHY THESE ARE TESTED RATHER THAN DELETED OR WAIVED. All three are `raise ValueError`
# arms on a hard-rule-5 surface, and the coverage ratchet found them unexercised. The
# ratchet's own guidance is to ask first whether a defensive branch should exist at all —
# an unreachable arm usually means the data was already validated upstream. These are
# reachable: `request_kind` and `processor` are strings a caller chooses, `outcome` is a
# string an OPERATOR chooses through the ops route, and each names a column value that a
# compliance officer later reads back as fact. A typo that reached the INSERT would write
# an obligation nobody queries for, which is the failure mode this whole module exists to
# make impossible.
#
# Each also asserts that NOTHING WAS WRITTEN, which is the half a bare `pytest.raises`
# would miss: the guard's value is not that it raises, it is that it raises BEFORE the
# statement that would have persisted the bad value.


async def _task_count(tenant_id: UUID) -> int:
    async with tenant_session(tenant_id) as session:
        result = await session.execute(
            text("SELECT count(*) FROM processor_erasure_tasks WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
        return int(result.scalar_one())


@asyncio_test
async def test_an_unknown_request_kind_is_refused_before_anything_is_written() -> None:
    """`request_kind` is written to a column a certificate is later derived from.

    Only "subject" and "tenant" mean anything downstream — `overdue_tasks` and the
    runbook both branch on them — so a third value would open an obligation that no
    report counts and no operator is paged about.
    """
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ValueError, match="unknown request_kind 'organisation'"):
            await open_tasks_for_request(
                session,
                tenant_id=tenant_id,
                request_ref=uuid.uuid4(),
                request_kind="organisation",
                subject_ref="abc123",
                vendor_refs=[_REAL_EXECUTION_ID],
            )
    assert await _task_count(tenant_id) == 0


@asyncio_test
async def test_an_unknown_processor_is_refused_before_anything_is_written() -> None:
    """`PROCESSORS` is role-keyed — "voice_engine", "speech", "llm" — never vendor-named.

    That is what lets a vendor swap on any leg happen without a migration, and it is also
    why a typo here is dangerous rather than merely wrong: a task filed against a
    processor no report enumerates is an erasure obligation that silently never comes due.
    """
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ValueError, match="unknown processor 'azure'"):
            await open_tasks_for_request(
                session,
                tenant_id=tenant_id,
                request_ref=uuid.uuid4(),
                request_kind="subject",
                subject_ref="abc123",
                vendor_refs=[_REAL_EXECUTION_ID],
                processors=("voice_engine", "azure"),
            )
    # NOT merely "it raised": the good processor is named FIRST in the tuple, so this
    # asserts the call is refused WHOLE rather than half-applied. It failed when written,
    # because the check used to sit inside the loop and `voice_engine` was already
    # inserted by the time `azure` was reached — a partial open is the worst outcome
    # available here, some obligations filed and one lost, behind an exception that does
    # not say which. The fix hoisted the validation above the loop; this line is what
    # keeps it there.
    assert await _task_count(tenant_id) == 0


@asyncio_test
async def test_an_outcome_that_is_neither_confirmed_nor_refused_is_rejected() -> None:
    """The outcome vocabulary is closed because "refused" must stay legible.

    `record_answer`'s docstring makes the point that a vendor refusal is the most
    important thing anyone learns on this axis. A free-text third outcome — "partial",
    "pending", "n/a" — is how that distinction gets lost, so the function refuses one
    rather than storing it.
    """
    tenant_id = await _tenant()
    request_ref = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await open_tasks_for_request(
            session,
            tenant_id=tenant_id,
            request_ref=request_ref,
            request_kind="subject",
            subject_ref="abc123",
            vendor_refs=[_REAL_EXECUTION_ID],
            processors=("voice_engine",),
        )
        task_id = (
            await session.execute(
                text(
                    "SELECT id FROM processor_erasure_tasks "
                    "WHERE request_ref = :r AND processor = 'voice_engine'"
                ),
                {"r": str(request_ref)},
            )
        ).scalar_one()
        await record_request_sent(session, task_id=task_id, vendor_reference="TICKET-1")

        with pytest.raises(ValueError, match="outcome must be confirmed or refused"):
            await record_answer(session, task_id=task_id, outcome="partial", note=None)

        # The task is untouched: still awaiting an answer, so it still shows up as
        # overdue and still pages. A guard that raised AFTER the UPDATE would have
        # settled the obligation on its way out.
        status = (
            await session.execute(
                text("SELECT status FROM processor_erasure_tasks WHERE id = :t"),
                {"t": str(task_id)},
            )
        ).scalar_one()
        assert status == "requested"
