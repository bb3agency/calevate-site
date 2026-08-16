"""The producer half of D-126: a raw vendor document actually reaches the archive.

`storage.archive_payload` writes it, `calls.engine_payload_ref` names it and
`retention._erase_engine_payloads` destroys it — and until this slice all three guarded a
store nothing created. `tests/engine_payload_erasure_test.py` proves the ERASURE reaches
an object; every one of its cases writes that object itself. So the question no test could
answer was the one that decides whether any of it matters: **does a completed call leave an
archive behind at all?**

Four properties, and each is a separate way the seam can be open:

1. the post-call pipeline writes an object under the call's own erasure prefix;
2. the REFERENCE is committed before the PUT — `archive_payload` states that order as a
   contract, because the erasure gates its prefix listing on the column, so an object
   written first is one a DPDP request has no reason to look for;
3. what is stored is the VENDOR'S document, not our normalized snapshot;
4. the two halves meet: the erasure destroys exactly what the pipeline wrote.

Plus the two failure directions a debug artifact must never get wrong — a refused PUT may
not cost the client their lead, and nothing about the archive may reach a log (hard rule
6: this document is the caller's number and the transcript, verbatim).
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine.document import MAX_ENGINE_DOCUMENT_BYTES, engine_document
from apps.workers import pipeline, retention, storage
from calevate_shared.engine import ExecutionSnapshot
from sqlalchemy import text
from tests.conftest import FakeS3
from tests.pipeline_audit_test import _completed_call, _run_pipeline
from tests.smoke_pipeline_test import _seed_tenant  # noqa: F401  (fixture dependency chain)


@pytest.fixture(autouse=True)
def _stub_recording(monkeypatch: pytest.MonkeyPatch) -> None:
    """The recording copy is an environment concern; the archive is the subject. Same
    substitution `pipeline_audit_test` and `smoke_pipeline_test` both make."""

    async def _fake_copy(*, source_url: str, tenant_id: UUID, call_id: UUID) -> str:
        return f"recordings/{tenant_id}/{call_id}.wav"

    monkeypatch.setattr("apps.workers.pipeline.copy_recording", _fake_copy)


async def _ref(tenant_id: UUID, call_id: UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        value = (
            await session.execute(
                text("SELECT engine_payload_ref FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).scalar()
    return None if value is None else str(value)


# --- 1. the seam is closed ----------------------------------------------------------


async def test_a_completed_call_leaves_an_archived_vendor_document(s3: FakeS3) -> None:
    """THE TEST THAT DID NOT EXIST. Run the real pipeline; find bytes in the bucket.

    Asserted against the PREFIX the erasure lists rather than against the exact key, so a
    key-shape change that keeps the archive reachable passes and one that moves the object
    out of the erasure's reach fails — which is the failure D-126 was written for.
    """
    tenant_id, execution_id, call_id = await _completed_call("archive")

    await _run_pipeline(tenant_id, call_id, execution_id)

    prefix = storage.payload_call_prefix(tenant_id=tenant_id, call_id=call_id)
    archived = [key for key in s3.objects if key.startswith(prefix)]
    assert archived, (
        "a completed call archived nothing — `calls.engine_payload_ref` is a column with "
        "no writer and D-126's erasure arm guards an object that is never created"
    )
    assert await _ref(tenant_id, call_id) in archived, (
        "the column must name an object that is really there; a reference the erasure "
        "cannot resolve is the half of the contract that is allowed to be wrong, and the "
        "happy path is not it"
    )


async def test_the_bytes_in_the_bucket_are_the_adapters_bytes_unchanged(s3: FakeS3) -> None:
    """Property 3 as the PIPELINE's half of it.

    Whether the document is the vendor's own object rather than a re-render of our
    snapshot is a claim about ADAPTERS, and the conformance suite makes it of all four
    (`test_get_execution_carries_the_vendors_own_document_for_the_archive` — it has to,
    since a sabotage of one adapter proved a suite clause was the only thing that could
    catch it). What is left for this file is the claim about the WORKER: that whatever the
    adapter sealed is what lands in the bucket, byte for byte.

    Byte equality rather than a shape check on purpose. The pipeline is the one component
    here that could re-encode, wrap or prettify the document on the way past, and any of
    those would make the archive a rendering of the vendor's answer rather than the
    answer — which is the same defect as archiving our snapshot, arriving from our side.
    """
    tenant_id, execution_id, call_id = await _completed_call("shape")
    await _run_pipeline(tenant_id, call_id, execution_id)

    key = await _ref(tenant_id, call_id)
    assert key is not None
    sealed = (await pipeline.get_engine().get_execution(execution_id)).raw_document
    assert sealed is not None
    assert s3.objects[key] == sealed, (
        "the archived bytes are not the bytes the adapter sealed — something between the "
        "boundary and the bucket re-rendered the vendor's own document"
    )


async def test_the_reference_is_committed_before_the_object_is_put(s3: FakeS3) -> None:
    """Property 2 — the write ORDER, which `archive_payload` states as a contract.

    `retention._erase_engine_payloads` gates its prefix listing on a call carrying a
    reference. So a PUT that lands before the column is committed leaves a document
    holding the caller's number and transcript that a DPDP erasure has no reason to look
    for: the D-126 defect, reintroduced one crash at a time.

    Measured at the PUT rather than reasoned about, by reading the column from inside the
    archive call. Both orders satisfy every other assertion in this file, so nothing else
    here can tell them apart.
    """
    tenant_id, execution_id, call_id = await _completed_call("order")
    seen: list[str | None] = []
    real = storage.archive_payload

    async def _watching(**kwargs: Any) -> str | None:
        seen.append(await _ref(tenant_id, call_id))
        return await real(**kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(pipeline, "archive_payload", _watching)
        await _run_pipeline(tenant_id, call_id, execution_id)

    # "Nothing was PUT" rather than "the stage did not run" — the two are different
    # findings and the stage has a legitimate path that reaches neither (`none_offered`).
    assert seen, "no object was PUT at all, so there is no write order to check"
    assert seen[0] is not None, (
        "the object was PUT before `calls.engine_payload_ref` was committed — a crash in "
        "that window leaves an archived phone number and transcript that no erasure "
        "enumerates, which is exactly the D-126 defect"
    )


async def test_the_erasure_destroys_what_the_pipeline_wrote(s3: FakeS3) -> None:
    """The two halves, meeting. Every case in `engine_payload_erasure_test` stages its own
    object; this one stages nothing and erases what the PRODUCT produced.

    That difference is the whole point: a fixture-written object proves the erasure walks
    a prefix, and only a pipeline-written one proves the prefix it walks is the prefix the
    product writes to.
    """
    caller = f"+9198{uuid.uuid4().int % 100000000:08d}"
    tenant_id, execution_id, call_id = await _completed_call("fullcircle", caller=caller)
    await _run_pipeline(tenant_id, call_id, execution_id)
    key = await _ref(tenant_id, call_id)
    assert key is not None and key in s3.objects

    async with tenant_session(tenant_id) as session:
        erased = await retention._erase_engine_payloads(
            session, tenant_id=tenant_id, call_ids=[call_id]
        )

    assert erased >= 1
    assert key not in s3.objects, "the erasure did not reach the object the pipeline wrote"
    assert await _ref(tenant_id, call_id) is None


# --- 2. the two failure directions --------------------------------------------------


async def test_a_refused_archive_does_not_cost_the_client_their_lead(s3: FakeS3) -> None:
    """The archive is a debug artifact; the lead is the product.

    `archive_payload` is best-effort by design ("failing a call's pipeline because a debug
    artifact could not be written would be the tail wagging the dog"), and that promise is
    only real if the pipeline honours it — a stage that let a `ClientError` escape would
    turn one object-store blip into a retried, eventually-abandoned call.
    """
    tenant_id, execution_id, call_id = await _completed_call("refused")
    s3.fail = True

    await _run_pipeline(tenant_id, call_id, execution_id)

    s3.fail = False
    async with tenant_session(tenant_id) as session:
        leads = (
            await session.execute(
                text("SELECT count(*) FROM leads WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
    assert leads == 1, "a refused debug PUT must not cost the client their lead"


async def test_nothing_about_the_archive_reaches_a_log(
    s3: FakeS3, caplog: pytest.LogCaptureFixture
) -> None:
    """Hard rule 6 on the one stage that handles the raw document.

    The archived bytes ARE the caller's number and their words. Both failure paths in this
    seam log — `payload_archive_failed` and `engine_document_oversized` — and both are one
    edit away from carrying the thing they could not write. Measured over every record the
    whole pipeline emits, with the store FAILING, because that is the only state in which
    the warning fires at all: a green run measures nothing here.

    At the RECORD rather than at the formatted line, for the reason
    `engine_audit_test.test_no_adapter_logs_a_phone_number_a_transcript_or_an_extraction`
    gives: `tests/pii_logging_sweep_test.py` proves the log STREAM is clean (redaction
    lives in `JsonFormatter.format`); this asks whether this stage handed the logger the
    document, which is a bug even when the redactor happens to scrub it.
    """
    caller = "+919876500777"
    tenant_id, execution_id, call_id = await _completed_call("hardrule6", caller=caller)
    s3.fail = True

    with caplog.at_level("DEBUG"):
        await _run_pipeline(tenant_id, call_id, execution_id)

    s3.fail = False
    emitted = "\n".join(
        f"{record.getMessage()} {sorted(vars(record).items(), key=str)}"
        for record in caplog.records
    )
    assert caller not in emitted, "a phone number reached a log line (hard rule 6)"
    for turn in ("appointment kavali", "book chesanu"):
        assert turn not in emitted, f"transcript text reached a log line: {turn!r}"


def test_a_serialized_snapshot_cannot_carry_the_raw_document() -> None:
    """Hard rule 6, enforced by the TYPE rather than by everyone remembering.

    A snapshot is handed to span attributes, alerts and (in principle) a job payload, and
    every one of those paths ends in `model_dump`. The document is the caller's number and
    their words verbatim, so the field is declared `exclude=True` and `repr=False`: a dump
    cannot carry it and a repr cannot put it inside an exception message. This is the
    assertion that keeps the declaration from being quietly dropped — nothing else in the
    suite would notice, because every other behaviour is identical either way.
    """
    carrying = ExecutionSnapshot(
        engine_call_id="exec_1",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        raw_document=b'{"from_number":"+919876500123"}',
    )

    assert carrying.raw_document is not None, "the field itself still works in Python"
    assert "raw_document" not in carrying.model_dump()
    assert "919876500123" not in carrying.model_dump_json()
    assert "919876500123" not in repr(carrying)
    # And it survives the ONE path the pipeline actually uses to receive it.
    assert carrying.model_copy(update={"engine": "bolna"}).raw_document == carrying.raw_document


# --- 3. the size bound --------------------------------------------------------------


def test_an_oversized_vendor_document_is_refused_rather_than_truncated() -> None:
    """The cap, and the shape of the refusal.

    A truncated JSON document is not a smaller archive, it is an unparseable one — so the
    only thing half of it can still do is hold a caller's number. `engine_document`
    therefore answers None, the pipeline records `none_offered`, and no reference is
    committed for an object that was never written.
    """
    huge = {"transcript": "x" * (MAX_ENGINE_DOCUMENT_BYTES + 1)}

    assert engine_document(huge, engine="bolna") is None
    ordinary = engine_document({"id": "exec_1", "status": "completed"}, engine="bolna")
    assert ordinary is not None and len(ordinary) < MAX_ENGINE_DOCUMENT_BYTES


async def test_an_adapter_that_offers_no_document_writes_no_reference(s3: FakeS3) -> None:
    """The other end of the same rule. `engine_payload_ref` must never name an object the
    pipeline knew it was not going to write: the erasure's gate reads that column, and a
    reference minted for a document that does not exist buys a wasted prefix listing on
    every erasure for that call forever."""
    tenant_id, execution_id, call_id = await _completed_call("nodoc")
    real = pipeline.get_engine().get_execution

    async def _documentless(call: str) -> ExecutionSnapshot:
        return (await real(call)).model_copy(update={"raw_document": None})

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(pipeline.get_engine(), "get_execution", _documentless)
        await _run_pipeline(tenant_id, call_id, execution_id)

    assert await _ref(tenant_id, call_id) is None
    prefix = storage.payload_call_prefix(tenant_id=tenant_id, call_id=call_id)
    assert not [key for key in s3.objects if key.startswith(prefix)]


async def test_a_call_row_that_took_no_reference_gets_no_object_either(s3: FakeS3) -> None:
    """The conditional half of the ordering contract.

    "Commit the reference, then PUT" is only a contract if the PUT is CONDITIONAL on the
    commit having landed. It can fail to land — the call row is gone (a tenant erasure
    between the fetch and this stage), or RLS puts it out of reach — and the UPDATE
    reports that by touching zero rows rather than by raising. PUTting anyway would create
    exactly the object D-126 exists to make impossible: a caller's number and transcript
    under a prefix no `calls` row will ever name, so no DPDP erasure has any reason to
    list it.
    """
    tenant_id, execution_id, call_id = await _completed_call("norow")
    vanished = uuid7()

    outcome = await pipeline._archive_engine_document(
        tenant_id,
        vanished,
        execution_id,
        await pipeline.get_engine().get_execution(execution_id),
    )

    assert outcome == "call_row_absent"
    prefix = storage.payload_call_prefix(tenant_id=tenant_id, call_id=vanished)
    assert not [key for key in s3.objects if key.startswith(prefix)], (
        "an object was archived for a call no row references — unreachable by every "
        "erasure this platform has"
    )
    # And the real call is untouched: the guard must not be a blanket refusal.
    await _run_pipeline(tenant_id, call_id, execution_id)
    assert await _ref(tenant_id, call_id) is not None
