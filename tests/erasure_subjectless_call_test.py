"""A call whose caller was never identified holds the same PII and no erasure can reach it.

THE SEQUENCE. An inbound call arrives on a carrier that sends no calling party, or sends
one our client cannot parse (`voice_worker/carrier.CallerIdentity`, states
`withheld_by_carrier` / `unparsed_by_client`). `calls.from_e164` stays NULL. The call is
recorded and transcribed like any other, so the person's VOICE and their WORDS are on
file. The person then exercises DPDP §12 and gives the business their number.

`execute_deletion_request` finds calls by `from_e164 = :phone OR to_e164 = :phone OR
erased_subject_ref = :ref`. None of the three can match a row with NULL in both number
columns, so the transcript and the recording survive the erasure and the certificate is
issued anyway.

What is asserted here:

1. the gap is REACHABILITY and not wording — the erasure completes, reports zero calls,
   and the transcript and recording pointer are byte-for-byte intact;
2. the same content IS destroyed when the identical call carries the number, so what the
   first case demonstrates is the missing subject and not a broken fixture;
3. the certificate a data principal is handed names this case, so nobody reads a
   completed erasure as a complete one.
"""

from __future__ import annotations

import uuid
from typing import Any

from apps.api.compliance.deletion import (
    ERASURE_EXCEPTIONS,
    UNIDENTIFIED_COUNT_KEY,
    UNIDENTIFIED_OUTCOME,
    request_erasure,
)
from apps.api.compliance.deletion_proof import certificate
from apps.api.db.session import tenant_session
from apps.workers.retention import REDACTED_MARK, execute_deletion_request
from sqlalchemy import text
from tests.campaigns_test import _tenant

CALLER_LINE = "naa peru Ravi, mee shop ekkada undi"
RECORDING_KEY = "recordings/subjectless/ravi.wav"


async def _call_with_caller(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, from_e164: str | None
) -> uuid.UUID:
    """An inbound call that was recorded and transcribed, with or without a known caller.

    `to_e164` is the BUSINESS's own line on an inbound call, so it is left NULL here for
    the same reason production leaves it NULL: the settlement path records the parties it
    learned, and a call nobody was identified on has neither.
    """
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "status, from_e164, to_e164, started_at, ended_at, duration_s, "
                "recording_url, summary, created_at, updated_at) "
                "VALUES (:id, :t, :a, :e, 'inbound', 'completed', :frm, NULL, "
                "now() - interval '10 minutes', now(), 60, :rec, :sum, now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"exec_{uuid.uuid4().hex[:12]}",
                "frm": from_e164,
                "rec": RECORDING_KEY,
                "sum": "Caller Ravi asked for the shop address.",
            },
        )
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "text_redacted, created_at, updated_at) "
                "VALUES (:id, :t, :c, 0, 'caller', :txt, :txt, now(), now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "c": call_id, "txt": CALLER_LINE},
        )
    return call_id


async def _content(tenant_id: uuid.UUID, call_id: uuid.UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        turns = (
            (
                await session.execute(
                    text("SELECT text FROM transcript_turns WHERE call_id = :c ORDER BY idx"),
                    {"c": call_id},
                )
            )
            .scalars()
            .all()
        )
        row = (
            await session.execute(
                text("SELECT recording_url, summary FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).first()
    assert row is not None
    return {"turns": list(turns), "recording_url": row[0], "summary": row[1]}


async def _erase(tenant_id: uuid.UUID, phone: str) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        made = await request_erasure(session, tenant_id=tenant_id, phone_e164=phone)
    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(made.id)})
    return made.id


async def _proof(tenant_id: uuid.UUID, request_id: uuid.UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT proof, completed_at FROM deletion_requests WHERE id = :r"),
                {"r": request_id},
            )
        ).first()
    assert row is not None
    assert row[1] is not None, "the erasure reported itself complete"
    return dict(row[0])


async def test_an_unidentified_caller_s_call_survives_their_own_erasure() -> None:
    """RED before the fix: the transcript, the summary and the recording pointer all stay."""
    subject = f"+9198765{uuid.uuid4().int % 100000:05d}"
    tenant_id, agent_id = await _tenant()

    subjectless = await _call_with_caller(tenant_id, agent_id, from_e164=None)
    identified = await _call_with_caller(tenant_id, agent_id, from_e164=subject)

    request_id = await _erase(tenant_id, subject)
    proof = await _proof(tenant_id, request_id)

    # 2 — the control. The identical call WITH the number is destroyed, so the fixture
    # writes content an erasure really does reach.
    after_identified = await _content(tenant_id, identified)
    assert after_identified["turns"] == [REDACTED_MARK], after_identified
    assert after_identified["recording_url"] is None, after_identified

    # 1 — and the one without it is untouched. This is the defect: the same person's
    # words and the pointer to the sound of their voice, under a completed certificate.
    after_subjectless = await _content(tenant_id, subjectless)
    assert after_subjectless["turns"] == [CALLER_LINE], after_subjectless
    assert after_subjectless["recording_url"] == RECORDING_KEY, after_subjectless
    assert after_subjectless["summary"] is not None, after_subjectless
    # The proof names one call — the identified one. The subjectless call is absent from
    # the certificate entirely: not listed as reached, not listed as missed.
    assert len(proof["scope"]["calls"]) == 1, proof


async def test_the_certificate_names_the_calls_no_number_can_find() -> None:
    """The limitation register must carry this case; a silent one over-claims.

    Keyed on the OUTCOME word rather than on prose, so rewording the paragraph cannot
    quietly drop the disclosure the register exists to make. Asserted on the RENDERED
    document as well as the register, because the register is only a promise until the
    certificate a data principal is handed actually carries it.
    """
    subject = f"+9198765{uuid.uuid4().int % 100000:05d}"
    tenant_id, agent_id = await _tenant()
    await _call_with_caller(tenant_id, agent_id, from_e164=None)

    request_id = await _erase(tenant_id, subject)
    stored = await _proof(tenant_id, request_id)
    doc = certificate(stored)
    assert doc is not None

    assert UNIDENTIFIED_OUTCOME in {e.outcome for e in ERASURE_EXCEPTIONS}
    entry = next(e for e in doc["not_erased"] if e["outcome"] == UNIDENTIFIED_OUTCOME)
    # The count, and it is the one that makes the entry a report rather than a caveat.
    assert entry["count"] == 1, doc["not_erased"]
    assert doc["scope"][UNIDENTIFIED_COUNT_KEY] == 1, doc["scope"]


async def test_a_proof_written_before_anything_counted_does_not_render_as_none() -> None:
    """Absent is not zero. A `0` here would certify a search that never ran."""
    stored = {"subject_hash": "x", "executed_at": "2026-01-01T00:00:00+00:00", "scope": {}}
    doc = certificate(stored)
    assert doc is not None
    entry = next(e for e in doc["not_erased"] if e["outcome"] == UNIDENTIFIED_OUTCOME)
    assert entry["count"] is None, entry
    assert "does not say whether this business holds any" in entry["why"], entry
