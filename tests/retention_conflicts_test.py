"""The three recorded retention conflicts, settled as far as engineering may settle them.

Three questions were open against `apps/workers/retention.py`, all of them live in code.
This file is the answer to each, written so a compliance reviewer can read the test name
and the assertion message and know what the platform actually does.

**1. Which TTLs are real?** SEC-COMP §4 once promised one set of numbers (180 / 730 / 730)
while `scripts/seed.DEFAULT_RETENTION_POLICIES` shipped another (90 / 365 / 1095). The
running code obeys the *rows*, the rows come from the seed, and `/legal/privacy` §9
published the seed's numbers — so the document's §4 table was the only outlier. **D-462
reconciled it**: §4 now states the enforced-and-published defaults, so doc, seed and notice
agree. The tests pin what ships and pin the doc's account of it, so the two cannot drift
apart again in silence; the guard that used to assert the divergence now asserts the
agreement (see `test_the_document_and_the_seed_now_agree_reconciled_by_d_462`).

**2. Erasure versus the TRAI 90-day recording floor.** These point opposite ways for one
concrete row: a recording younger than 90 days whose subject has asked to be erased. The
tests establish that the outcome is DETERMINISTIC and not a function of which worker ran
last — erase-then-sweep and sweep-then-erase reach the same state — and that the
certificate now names the collision instead of leaving "recording pointer cleared" to
carry it. The legal question stays a legal question: SEC-COMP forbids making the
pointer-clear conditional on age before it is decided, so the code does not.

**3. Does `calls.summary` need its own `data_category`?** No — and these tests are why.
The summary is on the transcript's clock, to the day, and the one mechanism that could
have made it outlive the transcript (landing in `call_extractions.data`, which expires on
the much longer LEAD clock) is closed by the extraction validator dropping unknown keys.

And one defect the investigation turned up: a call the engine never dated was invisible
to every arm of the sweep, forever. That has a section of its own below.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance.export import subject_ref
from apps.api.db.session import get_engine, tenant_session, untenanted_session
from apps.workers import retention
from apps.workers.retention import (
    RECORDING_FLOOR_DAYS,
    REDACTED_MARK,
    apply_retention,
    execute_deletion_request,
    sweep_tenant,
)
from calevate_shared.extraction import ExtractionField, ExtractionSchemaSpec, validate_extraction
from scripts.seed import DEFAULT_RETENTION_POLICIES
from sqlalchemy import event, text
from tests.conftest import FakeS3, accept_agreements

DOC = Path(__file__).resolve().parents[1] / "docs" / "SECURITY-COMPLIANCE.md"

# Model-written prose about what the caller said. Distinctive enough that a leak of it
# into a log line or a proof certificate is unmistakable.
SUMMARY = "Caller said her mother has chest pain and asked for Dr Rao on Tuesday"
TRANSCRIPT = "naaku appointment kavali, ma amma ki gunde noppi"


# --------------------------------------------------------------------------- fixtures


async def _org() -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant with the shipped retention defaults and a published agent.

    The engine route is the bridge `publish_agent` writes in the same transaction as
    `agents.engine_agent_ref`; `_due_tenants` resolves the sweep's worklist from it, so a
    tenant with call rows and no route is a shape production cannot produce.
    """
    created = await admin_service.create_organization(
        name="Retention Conflicts",
        slug=f"rcf-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, in the shape `arm_agent_for_outbound` established. Every dial, launch and
    # publish gate now refuses an organisation that has not accepted them, so a fixture
    # without this reports `agreements_not_accepted` in place of the answer under test.
    await accept_agreements(uuid.UUID(str(created["id"])))
    tenant_id, agent_id = created["id"], created["agent_id"]
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :ref, :t, :a, true, now(), now())"
            ),
            {"ref": f"rcf_{uuid.uuid4().hex[:12]}", "t": tenant_id, "a": agent_id},
        )
    return tenant_id, agent_id


async def _call(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    days_ago: int,
    phone: str = "+919876500041",
    dated: bool = True,
    duration_s: int = 90,
) -> uuid.UUID:
    """One completed call with a recording pointer, a transcript turn and a summary.

    `dated=False` writes `ended_at = NULL` — the shape the Bolna adapter produces when
    the execution payload carries neither `ended_at` nor `updated_at`
    (`apps/api/engine/bolna.py:_snapshot`), which the pipeline's
    `ended_at = COALESCE(EXCLUDED.ended_at, calls.ended_at)` then preserves.
    """
    call_id = uuid.uuid4()
    when = datetime.now(UTC) - timedelta(days=days_ago)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, started_at, ended_at, duration_s, recording_url, summary, "
                "created_at, updated_at) VALUES (:id, :t, :a, :e, 'inbound', 'completed', "
                ":phone, '+911140000000', :w, :ended, :dur, 'recordings/x.wav', :s, :w, :w)"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"rcf_{call_id.hex[:10]}",
                "phone": phone,
                "w": when,
                "ended": when if dated else None,
                "dur": duration_s,
                "s": SUMMARY,
            },
        )
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "text_redacted, created_at, updated_at) VALUES (:i, :t, :c, 0, 'caller', "
                ":txt, :txt, :w, :w)"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "c": call_id, "txt": TRANSCRIPT, "w": when},
        )
    return call_id


async def _state(tenant_id: uuid.UUID, call_id: uuid.UUID) -> tuple[Any, ...]:
    """(recording_url, summary, first turn's text) — the three things a TTL is about."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT c.recording_url, c.summary, "
                    "  (SELECT t.text FROM transcript_turns t WHERE t.call_id = c.id "
                    "   ORDER BY t.idx LIMIT 1) "
                    "FROM calls c WHERE c.id = :c"
                ),
                {"c": call_id},
            )
        ).first()
    assert row is not None
    return tuple(row)


async def _file_request(tenant_id: uuid.UUID, phone: str) -> uuid.UUID:
    request_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO deletion_requests (id, tenant_id, phone_e164, subject_ref, scope, "
                "requested_at, created_at) VALUES (:i, :t, :p, :r, 'all', now(), now())"
            ),
            {"i": request_id, "t": tenant_id, "p": phone, "r": subject_ref(phone)},
        )
    return request_id


async def _proof(tenant_id: uuid.UUID, request_id: uuid.UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT proof FROM deletion_requests WHERE id = :i"), {"i": request_id}
            )
        ).first()
    assert row is not None and row[0] is not None
    document: dict[str, Any] = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    return document


# ============================================================ 1. WHICH TTLs ARE REAL


# SEVEN, not four, and each addition closed a store of personal data that sat outside
# every policy a tenant could set. D-179 added `engine_payload` and `kb` (LEGAL-SURFACE
# F-2 and F-3); migration d4a9c17e6b02 added `copilot_memory` in the same shape, for the
# in-app assistant's memory of what a client's own staff asked it. None of the three is
# part of the open divergence the section below tracks — SEC-COMP §4 promises nothing
# about any of them — but all three are pinned here for the reason the other four are:
# this dict is the row a client actually gets.
SHIPPED_TTLS = {
    "recording": 90,
    "transcript": 365,
    "lead": 1095,
    "consent_log": 2555,
    "engine_payload": 90,
    "kb": 365,
    "copilot_memory": 180,
    # What an agent remembers about a CALLER between calls (D-507). The same pair as
    # `copilot_memory` and not the transcript's 365: a memory exists to outlive the call,
    # so the call's period is the wrong clock for it, and a caller — unlike a client's own
    # staff — never chose us, which is why the shorter of the two numbers wins.
    "caller_memory": 180,
}


def test_the_shipped_retention_defaults_are_exactly_these_numbers() -> None:
    """`DEFAULT_RETENTION_POLICIES` is not documentation — it is the row a tenant gets
    and therefore the number `apply_retention` obeys. Pinned here so a change to it is a
    change to a test with the DPA's name on it."""
    assert {p["data_category"]: p["ttl_days"] for p in DEFAULT_RETENTION_POLICIES} == SHIPPED_TTLS
    assert SHIPPED_TTLS["recording"] >= RECORDING_FLOOR_DAYS, "the seed cannot ship below TRAI"


async def test_a_real_tenant_gets_those_rows_and_the_sweep_reads_them_back() -> None:
    """One step further than the constant: the onboarding path writes these rows, under
    RLS, and they are what the probe reads. This is the number a client actually has."""
    tenant_id, _ = await _org()
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT data_category, ttl_days, action FROM retention_policies")
            )
        ).all()
    assert {str(r[0]): int(r[1]) for r in rows} == SHIPPED_TTLS
    assert {str(r[0]): str(r[2]) for r in rows} == {
        "recording": "delete",
        "transcript": "anonymize",
        "lead": "anonymize",
        "consent_log": "anonymize",
        # Destroy, all three of them: an opaque vendor document, a chunk of a client's
        # price list (D-179) and a sentence a person typed at their console (migration
        # d4a9c17e6b02) have no anonymized form worth keeping. A blanked copilot memory
        # would still be recalled into a prompt and still cost tokens while saying nothing.
        "engine_payload": "delete",
        "kb": "delete",
        "copilot_memory": "delete",
        # Four of them, since D-507. There is no anonymised form of a distilled sentence
        # either, and a blanked memory would still be recalled into a prompt.
        "caller_memory": "delete",
    }


def test_the_document_and_the_seed_now_agree_reconciled_by_d_462() -> None:
    """The tripwire, fired and then retired — D-462 CLOSED the gap it guarded.

    This was a KNOWN-GAP guard: SEC-COMP §4 once quoted 180 days for recordings and 24
    months for transcripts/leads while the seed shipped 90 / 365 / 1095, and the section
    declared that divergence OPEN. The guard was written to fail if EITHER half moved
    without the other — "close it in the code without the doc, or in the doc without the
    code, and this fails and names the other half." D-462 closed the doc half (§4's row
    and the narrative now state the seed's enforced-and-published numbers), so the gap is
    closed and this test now asserts AGREEMENT rather than divergence. It must never be
    flipped back to assert a disagreement — that would re-open a settled reconciliation.
    """
    document = DOC.read_text(encoding="utf-8")
    collapsed = " ".join(document.split())

    # The divergence is no longer DECLARED: the OPEN QUESTION about retention defaults is
    # gone, replaced by the RESOLVED note that records D-462.
    open_question = "OPEN QUESTION — the retention defaults in this document and the ones in the"
    assert open_question not in document, (
        "the retention-defaults divergence was reconciled by D-462; it must not be re-declared open"
    )
    assert "RESOLVED (D-462)" in document, (
        "the reconciliation must stay recorded, not silently dropped"
    )

    # Every shipped TTL is now named as the default in the reconciled section — the doc
    # describes the codebase that actually runs.
    for category, ttl in SHIPPED_TTLS.items():
        assert f"{category} {ttl} days" in collapsed, (
            f"SEC-COMP no longer states the shipped {category} TTL of {ttl} days"
        )

    # The stale figures survive ONLY as explicitly-historical quotes (the F-5 note and the
    # RESOLVED block), never as a live default the doc still promises.
    for stale in ("default 180", "24 months"):
        for line in document.splitlines():
            if stale in line:
                assert any(
                    marker in line for marker in ("stale", "once carried", "F-5", "superseded")
                ), f"a stale retention figure ({stale!r}) reads as a live promise: {line.strip()!r}"


async def test_the_ttl_that_runs_is_the_policy_row_not_a_constant_in_the_worker() -> None:
    """Whatever the founder decides, the mechanism must be the row. A tenant on a
    bespoke 200-day transcript policy gets 200 days — no clamp, no default, no opinion
    of the worker's own (the recording floor is the single exception, and it is a floor,
    not a default)."""
    tenant_id, agent_id = await _org()
    young = await _call(tenant_id, agent_id, days_ago=150)
    old = await _call(tenant_id, agent_id, days_ago=250)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE retention_policies SET ttl_days = 200 WHERE data_category = 'transcript'")
        )

    await sweep_tenant(tenant_id)

    # Only the transcript category is under test here; both calls are long past the
    # 90-day recording TTL, so both lost their pointers and that is the correct answer.
    assert (await _state(tenant_id, young))[1:] == (SUMMARY, TRANSCRIPT)
    assert (await _state(tenant_id, old))[1:] == (None, REDACTED_MARK)


# ================================================ 2. ERASURE vs THE TRAI 90-DAY FLOOR


async def test_the_sweep_will_not_clear_a_recording_inside_the_floor() -> None:
    """Half the collision, stated alone: a tenant may not configure its way below 90
    days, and even a policy row that somehow claimed less would not move this."""
    tenant_id, agent_id = await _org()
    call_id = await _call(tenant_id, agent_id, days_ago=RECORDING_FLOOR_DAYS - 30)

    await sweep_tenant(tenant_id)

    assert (await _state(tenant_id, call_id))[0] == "recordings/x.wav"


async def test_erasure_clears_the_pointer_inside_the_floor_and_counts_the_collision(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The other half. DPDP's right is exercised against a 10-day-old recording.

    What the code does, unchanged: clears the pointer at any age. SEC-COMP records that
    as the shipped position and forbids making it conditional on age before the decision
    is taken, so this test asserts the erasure still happens — it is not a licence to
    start refusing.

    What is new is that the collision is COUNTED rather than passing unremarked: the job
    reports `floor_recordings=` and logs a warning, so "how often do §1 and §4 actually
    collide?" has an answer for whoever resolves it.
    """
    phone = "+919876500042"
    tenant_id, agent_id = await _org()
    call_id = await _call(tenant_id, agent_id, days_ago=10, phone=phone)
    request_id = await _file_request(tenant_id, phone)

    with caplog.at_level(logging.WARNING):
        result = await execute_deletion_request(
            {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
        )

    assert (await _state(tenant_id, call_id))[0] is None, "the pointer goes, at any age"
    assert "floor_recordings=1" in result
    warnings = [r for r in caplog.records if r.getMessage() == "erasure_within_recording_floor"]
    assert len(warnings) == 1 and getattr(warnings[0], "recordings", None) == 1
    # ...and the count is now DURABLE as well as logged. It used to live only on the job
    # result and this warning, which meant the certificate had to disclaim it: after the
    # pointer clear nothing can reconstruct which recordings were young. The proof
    # carries it under the key both halves agreed on; `tests/erasure_floor_count_test.py`
    # follows it the rest of the way to the document a client hands over.
    assert (await _proof(tenant_id, request_id))["scope"]["recordings_within_trai_floor"] == 1


async def test_an_erasure_outside_the_floor_reports_no_collision(
    caplog: pytest.LogCaptureFixture, s3: FakeS3
) -> None:
    """The count is a statement about THIS request, not boilerplate. A recording old
    enough that retention would have expired it anyway raises no conflict, and a signal
    that fired on every request would be read by nobody."""
    phone = "+919876500043"
    tenant_id, agent_id = await _org()
    await _call(tenant_id, agent_id, days_ago=400, phone=phone)
    request_id = await _file_request(tenant_id, phone)

    with caplog.at_level(logging.WARNING):
        result = await execute_deletion_request(
            {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
        )

    assert "floor_recordings=0" in result
    assert not [r for r in caplog.records if r.getMessage() == "erasure_within_recording_floor"]


async def test_the_outcome_does_not_depend_on_which_worker_ran_last() -> None:
    """THE point of this section. Two identical subjects inside the floor: one is swept
    then erased, the other erased then swept. If precedence were accidental — a matter of
    ordering between a nightly tick and a queued job — these two rows would end
    differently, and which of a client's callers got erased would depend on the clock.

    They do not. The sweep cannot touch a recording inside the floor and erasure always
    can, so the end state is the same either way, and it is the same as erasure alone.
    """
    phone_a = "+919876500044"
    phone_b = "+919876500045"
    tenant_id, agent_id = await _org()
    call_a = await _call(tenant_id, agent_id, days_ago=20, phone=phone_a)
    call_b = await _call(tenant_id, agent_id, days_ago=20, phone=phone_b)
    request_a = await _file_request(tenant_id, phone_a)
    request_b = await _file_request(tenant_id, phone_b)

    # A: retention first, then the erasure.
    await sweep_tenant(tenant_id)
    result_a = await execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_a)}
    )

    # B: the erasure first, then retention.
    result_b = await execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_b)}
    )
    await sweep_tenant(tenant_id)

    erased = (None, None, REDACTED_MARK)
    assert await _state(tenant_id, call_a) == erased
    assert await _state(tenant_id, call_b) == erased
    assert "floor_recordings=1" in result_a and "floor_recordings=1" in result_b, (
        "the collision was reported in both orderings, or the report depends on which "
        "worker ran first"
    )
    for request_id in (request_a, request_b):
        proof = await _proof(tenant_id, request_id)
        assert len(proof["scope"]["calls"]) == 1 and proof["scope"]["transcript_turns_erased"] == 1


async def test_the_retention_sweep_never_re_dates_a_call_to_dodge_the_floor(
    s3: FakeS3,
) -> None:
    """The tempting shortcut, closed. `updated_at` moves when the sweep touches a row,
    so a clock keyed on it would let one sweep push the next one out. Both the floor and
    the TTLs are measured from when the CALL happened, and a swept row stays expired."""
    tenant_id, agent_id = await _org()
    call_id = await _call(tenant_id, agent_id, days_ago=400)

    first = await sweep_tenant(tenant_id)
    second = await sweep_tenant(tenant_id)

    assert first["recordings"] == 1 and first["summaries"] == 1
    assert second["recordings"] == 0 and second["summaries"] == 0, (
        "nothing left to do, not deferred"
    )
    assert await _state(tenant_id, call_id) == (None, None, REDACTED_MARK)


# ============================================== 3. DOES calls.summary NEED A CATEGORY?


async def test_a_swept_transcript_never_leaves_a_summary_that_narrates_it() -> None:
    """The leak this question is about, checked directly: after the transcript ages out,
    is there still model-written prose on file describing what the caller said?"""
    tenant_id, agent_id = await _org()
    call_id = await _call(tenant_id, agent_id, days_ago=400)

    await sweep_tenant(tenant_id)

    _, summary, turn = await _state(tenant_id, call_id)
    assert turn == REDACTED_MARK
    assert summary is None, "the transcript was erased and its retelling was left on file"


async def test_summary_and_transcript_expire_on_the_same_day_not_merely_the_same_policy() -> None:
    """A shared category is only a shared clock if both are measured the same way. One
    day inside the TTL: both present. One day past it: both gone. That is what makes a
    separate `summary` data_category unnecessary rather than merely unimplemented."""
    tenant_id, agent_id = await _org()
    inside = await _call(tenant_id, agent_id, days_ago=364)
    outside = await _call(tenant_id, agent_id, days_ago=366)

    await sweep_tenant(tenant_id)

    # Recording pointers are gone from both (a 90-day TTL, and these are ~a year old);
    # the pair under test is the summary and the turns.
    assert (await _state(tenant_id, inside))[1:] == (SUMMARY, TRANSCRIPT)
    assert (await _state(tenant_id, outside))[1:] == (None, REDACTED_MARK)


def test_the_summary_cannot_ride_the_lead_clock_by_landing_in_the_extraction() -> None:
    """The ONE mechanism that could make a summary outlive its transcript, closed.

    `call_extractions.data` expires on the LEAD clock — 1095 days against the
    transcript's 365 — because it is the client's CRM. The model is asked for `summary`
    in the same JSON object as the schema fields (`build_extraction_prompt`), so if the
    validator passed unknown keys through, that prose would be stored under the longer
    category and the retention promise about transcripts would be false by three years.

    It does not: `validate_extraction` keeps `spec.fields` and drops the rest, and
    `_persist_extraction` writes `calls.summary` from the separate `summary` attribute.
    """
    spec = ExtractionSchemaSpec(
        fields=[ExtractionField(key="symptom", label="Symptom", type="text", required=False)]
    )
    outcome = validate_extraction(
        spec,
        {
            "symptom": "chest pain",
            "summary": SUMMARY,
            "sentiment": "negative",
            "notes": TRANSCRIPT,
        },
    )
    assert outcome.data == {"symptom": "chest pain"}
    assert "summary" not in outcome.data
    assert SUMMARY not in json.dumps(outcome.data)
    assert TRANSCRIPT not in json.dumps(outcome.data)


async def test_erasure_takes_the_summary_with_the_transcript_too() -> None:
    """The same question on the DPDP path rather than the TTL path: an erasure that
    redacted the turns and left the summary would certify a removal that did not
    happen."""
    phone = "+919876500046"
    tenant_id, agent_id = await _org()
    call_id = await _call(tenant_id, agent_id, days_ago=3, phone=phone)
    request_id = await _file_request(tenant_id, phone)

    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(request_id)})

    assert await _state(tenant_id, call_id) == (None, None, REDACTED_MARK)


def test_the_derived_copy_map_still_names_a_category_the_schema_allows() -> None:
    """`DERIVED_COPIES` is the declaration a reviewer reads. Filing `calls.summary` under
    an invented `summary` category would be a copy that no `retention_policies` row can
    match — the CHECK constraint enumerates four categories, so a fifth is a migration
    (and someone else's territory), not a constant in this module."""
    assert retention.DERIVED_COPIES == {
        "transcript": (
            "calls.summary",
            # The knowledge-gap quote columns are transcript text under another name:
            # the detector copies the caller's question and the agent's deflection out of
            # `transcript_turns.text_redacted`. They were in NO category, which is why
            # nothing expired them and no erasure reached them — the failure this pair of
            # entries exists to make impossible to reintroduce silently. Filed under
            # `transcript` rather than a fifth category, for this test's own reason.
            "knowledge_gap_occurrences.question_redacted",
            "knowledge_gaps.example_question_redacted",
            # THE VECTOR AND THE LEXEMES (D-503). `caller_chunks` stores no content and is
            # still a copy of the transcript: an embedding is derived from the text by a
            # deterministic function of it and is substantially invertible, and `tsv` is
            # literally the caller's words as lexemes.
            "caller_chunks.tsv+embedding (transcript scopes)",
        ),
        # `caller_memories.fact` AND the caller-memory scope's chunks USED TO SIT IN THE
        # TUPLE ABOVE, on the argument that a memory is distilled from what the caller said
        # and so rides the clock of the words it came from — plus this test's own point,
        # that a fifth category is a migration and a number the founder has to give. D-507
        # gave the number (180/`delete`) and `e1a4d70c9b52` writes the row for every
        # organisation that already existed, so what remains of that argument is its
        # weakest half: the PURPOSE of a memory is to outlive the call, which makes the
        # call's clock the wrong one rather than a convenient one. A fifth category is
        # still a migration; this is what one looks like when it is warranted.
        "caller_memory": (
            "caller_chunks.tsv+embedding (caller memory scope)",
            "caller_memories.fact",
        ),
        # `webhook_deliveries.payload_ref` names the object holding the CRM payload we
        # POSTed to a client's endpoint (D-23) — the same fields as
        # `call_extractions.data`, so the same category and the same clock. Filed under
        # `lead` rather than a fifth category for exactly the reason above.
        "lead": (
            "call_extractions.data",
            "webhook_deliveries.payload_ref",
            # The same projection table under the CRM clock: a lead's chunks are the same class
            # of thing as `call_extractions.data`. One table, two clocks, decided by the row's
            # own `retention_category` — which the projection registry sets from
            # `models.SUBJECT_RETENTION`, so a scope cannot choose its own.
            "caller_chunks.tsv+embedding (lead scope)",
        ),
    }
    assert set(retention.DERIVED_COPIES) <= set(SHIPPED_TTLS)


# ======================================= 4. THE CALL THE ENGINE NEVER DATED (defect)


async def test_a_call_with_no_ended_at_still_ages_out(s3: FakeS3) -> None:
    """The defect this investigation found.

    `calls.ended_at` is nullable and comes from the vendor: the Bolna adapter takes it
    from `ended_at` or `updated_at` in the execution payload and yields None when neither
    is there, and the pipeline's upsert preserves that NULL. Everything else about the
    call still lands — recording pointer, transcript turns, summary.

    Every predicate in this sweep compared `ended_at` to a cutoff, and NULL compares to
    nothing. So a call the engine never dated matched no probe and no statement, and kept
    its recording, its transcript and its summary FOREVER — a retention obligation
    switched off by a missing vendor field, silently, with no counter and no alert.
    """
    tenant_id, agent_id = await _org()
    call_id = await _call(tenant_id, agent_id, days_ago=900, dated=False)

    counts = await sweep_tenant(tenant_id)

    assert await _state(tenant_id, call_id) == (None, None, REDACTED_MARK), (
        "a 900-day-old call kept everything because the engine never sent an ended_at"
    )
    assert counts["recordings"] == 1 and counts["summaries"] == 1 and counts["transcripts"] == 1


async def test_the_fallback_clock_cannot_expire_a_recording_before_the_trai_floor(
    s3: FakeS3,
) -> None:
    """The direction of the guess matters. With no `ended_at` the clock falls back to our
    own `created_at` PLUS the metered duration — the latest moment the call plausibly
    ended — so an undated recording is retained a little too long rather than deleted a
    little too early. On a statutory minimum, only one of those is survivable."""
    tenant_id, agent_id = await _org()
    just_inside = await _call(
        tenant_id, agent_id, days_ago=RECORDING_FLOOR_DAYS - 1, dated=False, duration_s=3600
    )
    just_outside = await _call(
        tenant_id, agent_id, days_ago=RECORDING_FLOOR_DAYS + 1, dated=False, duration_s=3600
    )

    await sweep_tenant(tenant_id)

    assert (await _state(tenant_id, just_inside))[0] == "recordings/x.wav"
    assert (await _state(tenant_id, just_outside))[0] is None


async def test_an_undated_call_is_visible_to_the_probe_not_just_to_the_statements() -> None:
    """The probe decides whether any statement runs at all. If it still could not see an
    undated call, the fix above would be dead code on every tenant whose only expired
    rows are undated ones."""
    tenant_id, agent_id = await _org()
    await _call(tenant_id, agent_id, days_ago=900, dated=False)

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(retention._PROBE_SQL),
                {
                    "floor": RECORDING_FLOOR_DAYS,
                    "mark": REDACTED_MARK,
                    "anon": retention.ANONYMIZED_PHONE[:9],
                },
            )
        ).all()
    work = {str(r[0]): bool(r[3]) for r in rows}
    assert work["recording"] and work["transcript"], work


async def test_a_dated_call_is_measured_by_its_own_ended_at_exactly_as_before() -> None:
    """The fallback must not become a second clock for rows that already have one. A call
    created long ago and ended recently (a row re-dated by the reconciliation poller, or
    simply a long-running dispatch) is measured from `ended_at`, so nothing that was
    inside its TTL yesterday fell out of it because of this change."""
    tenant_id, agent_id = await _org()
    call_id = uuid.uuid4()
    created = datetime.now(UTC) - timedelta(days=900)
    ended = datetime.now(UTC) - timedelta(days=5)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, started_at, ended_at, duration_s, recording_url, summary, "
                "created_at, updated_at) VALUES (:id, :t, :a, :e, 'inbound', 'completed', "
                "'+919876500047', '+911140000000', :ended, :ended, 90, 'recordings/x.wav', :s, "
                ":created, :created)"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"rcf_{call_id.hex[:10]}",
                "ended": ended,
                "created": created,
                "s": SUMMARY,
            },
        )

    await sweep_tenant(tenant_id)

    recording, summary, _ = await _state(tenant_id, call_id)
    assert recording == "recordings/x.wav" and summary == SUMMARY


# ================================================== 5. THE INDEPENDENT VERIFICATIONS


# LogRecord's own attributes (`relativeCreated` is a float with a long digit run, which
# a phone-shaped regex happily matches). What a log line CARRIES is its message and the
# `extra` mapping the caller passed, so that is what gets inspected below.
_STANDARD_LOG_ATTRS = frozenset(vars(logging.LogRecord("n", 20, "p", 1, "m", None, None)))


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    return {k: v for k, v in vars(record).items() if k not in _STANDARD_LOG_ATTRS}


async def test_resolving_the_worklist_costs_one_query_however_many_clients_there_are(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression that took the tick from 62s to 5.9s, pinned at its root rather
    than at its symptom: the worklist is ONE statement against the global routing
    bridge, not a query (or a session) per organization. Adding clients cannot add
    statements to this step, because there is only ever one.
    """
    seen: list[str] = []
    engine = get_engine().sync_engine

    def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        seen.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", record)
    try:
        await retention._due_tenants()
    finally:
        event.remove(engine, "before_cursor_execute", record)

    worklist = [s for s in seen if "engine_agent_routes" in s]
    assert len(worklist) == 1, seen
    assert "organizations" not in " ".join(seen), "the sweep reads the client directory again"


def test_the_proof_hash_and_the_export_reference_are_one_function_in_two_places() -> None:
    """An auditor lines an access request up against an erasure by hash. The export path
    derives `subject_ref` and the worker derives the proof's `subject_hash`; they are
    separate definitions on purpose (the worker holds no handle into `compliance/`), so
    the only thing keeping them equal is a test that says so."""
    for number in ("+919876500048", "+911140000000", "+919000000001", retention.ANONYMIZED_PHONE):
        assert retention._hash(number) == subject_ref(number), number
    assert len(subject_ref(retention.ANONYMIZED_PHONE)) == 32


async def test_the_certificate_hash_is_the_one_an_access_request_would_produce() -> None:
    """The same fact end to end: file an erasure, run it, and the hash on the filed
    certificate is what `subject_ref(phone)` returns — which is also the column that
    survives the number being cleared."""
    phone = "+919876500049"
    tenant_id, agent_id = await _org()
    await _call(tenant_id, agent_id, days_ago=30, phone=phone)
    request_id = await _file_request(tenant_id, phone)

    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(request_id)})

    proof = await _proof(tenant_id, request_id)
    assert proof["subject_hash"] == subject_ref(phone)
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT phone_e164, subject_ref FROM deletion_requests WHERE id = :i"),
                {"i": request_id},
            )
        ).first()
    assert row is not None and row[0] is None and row[1] == subject_ref(phone)
    assert phone not in json.dumps(proof), "the certificate became another copy of the number"


async def test_no_phone_transcript_or_extraction_payload_reaches_the_logs(
    caplog: pytest.LogCaptureFixture, s3: FakeS3
) -> None:
    """Hard rule 6, over both jobs at once and over the whole log record — the message,
    every `extra` field, and anything a formatter would render. A retention sweep and an
    erasure both walk personal data by definition; what they may emit is ids and counts.
    """
    phone = "+919876500050"
    tenant_id, agent_id = await _org()
    await _call(tenant_id, agent_id, days_ago=400, phone=phone)
    old_lead_phone = "+919876500051"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, created_at, updated_at) VALUES (:i, :t, :a, :p, 'Ravi', 'inbound_call', "
                "'new', CAST(:d AS jsonb), now() - interval '1200 days', "
                "now() - interval '1200 days')"
            ),
            {
                "i": uuid.uuid4(),
                "t": tenant_id,
                "a": agent_id,
                "p": old_lead_phone,
                "d": json.dumps({"name": "Ravi", "callback": old_lead_phone}),
            },
        )
    request_id = await _file_request(tenant_id, phone)

    with caplog.at_level(logging.DEBUG):
        # `apply_retention`, not `sweep_tenant`: the sweep's own log line is written by
        # the job entrypoint, and it is the line that ships.
        await apply_retention({})
        await execute_deletion_request(
            {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
        )

    emitted = "\n".join(
        f"{record.getMessage()} {_extras(record)}"
        for record in caplog.records
        if not record.name.startswith("sqlalchemy")
    )
    assert "retention_sweep" in emitted and "deletion_executed" in emitted, (
        "neither job logged at all — this test would then be vacuous"
    )
    for secret in (phone, old_lead_phone, TRANSCRIPT, SUMMARY, "Ravi"):
        assert secret not in emitted, f"{secret!r} reached the log stream"
    # Digit runs long enough to be an Indian mobile, in any shape, from any module —
    # scanned over the log text with UUIDs REMOVED FIRST.
    #
    # THE STRIP IS NOT A WEAKENING, IT IS THE FIX FOR A ONE-IN-ELEVEN FALSE ALARM.
    # A uuid7/uuid4 renders as hex, and hex contains decimal digits, so a `9` followed by
    # nine more digits occurs inside an ordinary id — measured at **0.245% per id**, and
    # this assertion scans a log carrying ~40 of them, which is a **~9% chance per run**.
    # It fired for real: `tenant_id 01a00bbb-f055-7893-9ee2-492121909153` matched on its
    # tail `92121909153`, reddening CI with a message that reads as a hard-rule-6 breach —
    # the most alarming false alarm this suite can produce, and the kind that teaches
    # somebody to re-run until green.
    #
    # It cannot hide a real number. A phone is `+91` plus ten digits with no dashes; the
    # pattern removed here is the 8-4-4-4-12 hex layout, which no phone number can take.
    # Anything phone-shaped survives the strip and is still caught.
    without_ids = re.sub(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", "<id>", emitted)
    assert not re.search(r"\+?9\d{9,}", without_ids), without_ids
