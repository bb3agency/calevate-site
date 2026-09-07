"""The handover brief is reachable by an erasure and by the clock (D-533).

**THE HOLE THESE TESTS PIN.** `workers/handoff.py::_record` writes two columns of
model-written prose about a live conversation — `reason` (why this caller asked for a
person) and `summary` (what had been said so far) — against `source_call_id` and beside
the number that rang. The string `handoff_attempts` appeared in NONE of
`workers/retention.py`, `compliance/deletion.py`, `compliance/deletion_proof.py` or
`compliance/tenant_erasure.py`, and no `retention_policies` category named it. So the
brief survived BOTH clocks: no erasure reached it, and a table no category names never
expires.

**"IT IS REDACTED ON WRITE" IS NOT A DEFENCE**, and the repo's own precedent refutes it:
`knowledge_gap_occurrences.question_redacted` is redacted on write too, and it is scrubbed
by `scrub_quotes_for_calls` for the reason that function spells out — redaction removes
IDENTIFIERS from a sentence and leaves the SENTENCE. That is why every assertion below is
on the caller's WORDS and not on a phone number.

**`destination_e164` IS DELIBERATELY UNTOUCHED**, and one test asserts it, because a
silent decision is one the next reader re-opens: that column is a member of the CLIENT'S
staff on their own mobile — a different data principal, on a different lawful basis —
whose number a caller's §12 request cannot speak for, and the same number is on
`agent_handoff_members` regardless. Staff numbers end with the ENGAGEMENT.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance.deletion import request_erasure
from apps.api.compliance.tenant_erasure import request_tenant_erasure
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.retention import (
    execute_deletion_request,
    execute_tenant_erasure,
    sweep_tenant,
)
from sqlalchemy import text

pytestmark = pytest.mark.anyio

#: The model's own words. Both survive `workers/redaction.redact` intact — they name no
#: identifier — which is the whole point: this is a caller's account of their problem.
REASON = "Caller is upset about a bill and asked to speak to the manager"
SUMMARY = "She says the scan her husband had last month was charged twice"


def _phone() -> str:
    """A fresh subject per test: several suites share this database."""
    return f"+9198761{uuid.uuid4().int % 100000:05d}"


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Handoff Clinic",
        slug=f"handoff-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def _call(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, phone: str, days_ago: int = 0
) -> tuple[uuid.UUID, str]:
    call_id, engine_call_id = uuid7(), f"hoff_{uuid.uuid4().hex[:12]}"
    when = datetime.now(UTC) - timedelta(days=days_ago)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "status, from_e164, to_e164, started_at, ended_at, duration_s, "
                "created_at, updated_at) VALUES (:id, :t, :a, :e, 'inbound', 'completed', "
                ":p, '+911140000000', :w, :w, 90, :w, :w)"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": engine_call_id,
                "p": phone,
                "w": when,
            },
        )
    return call_id, engine_call_id


async def _handoff(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    execution_id: str,
    call_id: uuid.UUID | None,
    staff: str = "+919000011111",
    started_ago_days: int = 0,
) -> uuid.UUID:
    """One settled handover, shaped exactly as `workers/handoff.py::_record` writes it."""
    attempt_id = uuid7()
    when = datetime.now(UTC) - timedelta(days=started_ago_days)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO handoff_attempts (id, tenant_id, agent_id, source_execution_id, "
                "source_call_id, destination_e164, started_at, reason, summary, outcome, "
                "settled_at, leg_duration_s, created_at, updated_at) "
                "VALUES (:i, :t, :a, :ex, :cid, :dest, :w, :reason, :summary, 'connected', "
                ":w, 42, :w, :w)"
            ),
            {
                "i": attempt_id,
                "t": tenant_id,
                "a": agent_id,
                "ex": execution_id,
                "cid": call_id,
                "dest": staff,
                "w": when,
                "reason": REASON,
                "summary": SUMMARY,
            },
        )
    return attempt_id


async def _row(tenant_id: uuid.UUID, attempt_id: uuid.UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT reason, summary, destination_e164, outcome, leg_duration_s "
                    "FROM handoff_attempts WHERE id = :i"
                ),
                {"i": attempt_id},
            )
        ).first()
    assert row is not None, (
        "the row was deleted — it is the client's record that a handover happened, "
        "which is not the caller's data"
    )
    return {
        "reason": row[0],
        "summary": row[1],
        "destination_e164": row[2],
        "outcome": row[3],
        "leg_duration_s": row[4],
    }


async def _erase_subject(tenant_id: uuid.UUID, phone: str) -> str:
    async with tenant_session(tenant_id) as session:
        record = await request_erasure(session, tenant_id=tenant_id, phone_e164=phone)
    return await execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(record.id)}
    )


async def _proof(tenant_id: uuid.UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        proof = (
            await session.execute(
                text("SELECT proof FROM deletion_requests ORDER BY created_at DESC LIMIT 1")
            )
        ).scalar()
    assert isinstance(proof, dict)
    return proof


# ============================================================================
# 1. The per-subject erasure (DPDP §12)
# ============================================================================


async def test_the_erasure_removes_the_models_account_of_what_the_caller_wanted() -> None:
    """THE REGRESSION. Asserted on the SENTENCES, not on a row count: the defect was never
    a missing row, it was a surviving sentence, and a count assertion would have passed
    against the bug."""
    tenant_id, agent_id = await _tenant()
    phone = _phone()
    call_id, execution_id = await _call(tenant_id, agent_id, phone=phone)
    attempt_id = await _handoff(tenant_id, agent_id, execution_id=execution_id, call_id=call_id)

    result = await _erase_subject(tenant_id, phone)

    assert "handoff_briefs=1" in result, result
    row = await _row(tenant_id, attempt_id)
    assert row["reason"] is None, "the reason the caller asked for a person survived"
    assert row["summary"] is None, "the summary of what the caller said survived"


async def test_the_handover_record_itself_survives_because_it_is_the_clients_own() -> None:
    """Cleared, not deleted — `scrub_quotes_for_calls`' choice for the same reason. The
    fact that a handover happened, who took it and how it ended is the client's
    operational record, and a stranger's erasure request must not move it."""
    tenant_id, agent_id = await _tenant()
    phone = _phone()
    call_id, execution_id = await _call(tenant_id, agent_id, phone=phone)
    attempt_id = await _handoff(tenant_id, agent_id, execution_id=execution_id, call_id=call_id)

    await _erase_subject(tenant_id, phone)

    row = await _row(tenant_id, attempt_id)
    assert row["outcome"] == "connected"
    assert row["leg_duration_s"] == 42


async def test_the_staff_members_number_is_not_erased_by_a_callers_request() -> None:
    """THE DECISION, ASSERTED so nobody re-opens it silently.

    `destination_e164` is a member of the CLIENT'S staff on their own mobile. They are a
    different data principal on a different lawful basis; this request was made by the
    CALLER and cannot speak for them. Clearing it would delete the client's record of
    which of their people took the call while removing nothing of the caller's — and the
    same number is on `agent_handoff_members` regardless, so it would not even be a
    deletion. Staff numbers end with the ENGAGEMENT, not with one caller's §12 request.
    """
    tenant_id, agent_id = await _tenant()
    phone = _phone()
    staff = "+919000022222"
    call_id, execution_id = await _call(tenant_id, agent_id, phone=phone)
    attempt_id = await _handoff(
        tenant_id, agent_id, execution_id=execution_id, call_id=call_id, staff=staff
    )

    await _erase_subject(tenant_id, phone)

    assert (await _row(tenant_id, attempt_id))["destination_e164"] == staff


async def test_a_brief_whose_call_link_was_never_back_filled_is_still_reached() -> None:
    """THE BELT, and it closes a real gap rather than decorating one.

    `source_call_id` is nullable: `_record` writes the row while the call is still ringing
    and only `settle_handoff` back-fills it. A handover on a call this request DID find,
    whose pipeline never ran, is joined to it by nothing but the execution id the two rows
    share — so matching on `source_call_id` alone would leave the brief as the last
    surviving account of the conversation.
    """
    tenant_id, agent_id = await _tenant()
    phone = _phone()
    _call_id, execution_id = await _call(tenant_id, agent_id, phone=phone)
    attempt_id = await _handoff(tenant_id, agent_id, execution_id=execution_id, call_id=None)

    await _erase_subject(tenant_id, phone)

    row = await _row(tenant_id, attempt_id)
    assert row["reason"] is None and row["summary"] is None


async def test_another_callers_brief_is_untouched() -> None:
    """The scoping: the statement takes a call/execution predicate, and somebody else's
    handover on the same tenant must be left exactly as it was."""
    tenant_id, agent_id = await _tenant()
    subject, bystander = _phone(), _phone()
    subject_call, subject_exec = await _call(tenant_id, agent_id, phone=subject)
    other_call, other_exec = await _call(tenant_id, agent_id, phone=bystander)
    mine = await _handoff(tenant_id, agent_id, execution_id=subject_exec, call_id=subject_call)
    theirs = await _handoff(tenant_id, agent_id, execution_id=other_exec, call_id=other_call)

    await _erase_subject(tenant_id, subject)

    assert (await _row(tenant_id, mine))["reason"] is None
    untouched = await _row(tenant_id, theirs)
    assert untouched["reason"] == REASON and untouched["summary"] == SUMMARY


async def test_the_certificate_names_the_handover_brief() -> None:
    """SEC-COMP §4: what the erasure did is enumerated in the certificate rather than left
    to inference. The count rides `actions`, which passes through verbatim — `scope` is a
    whitelist two renderers enumerate field by field, so a key added there is a wire-shape
    change."""
    tenant_id, agent_id = await _tenant()
    phone = _phone()
    call_id, execution_id = await _call(tenant_id, agent_id, phone=phone)
    await _handoff(tenant_id, agent_id, execution_id=execution_id, call_id=call_id)

    await _erase_subject(tenant_id, phone)

    sentence = (await _proof(tenant_id))["actions"]["handoff_attempts"]
    assert sentence.startswith("1 handover brief(s)"), sentence
    assert "staff" in sentence, (
        "the certificate must say why the number that rang was not erased, or a reader "
        "will read the omission as an oversight"
    )


async def test_the_certificate_never_carries_the_words_it_certifies_gone() -> None:
    """Hard rule 6 does not stop being true inside a compliance artefact."""
    tenant_id, agent_id = await _tenant()
    phone = _phone()
    call_id, execution_id = await _call(tenant_id, agent_id, phone=phone)
    await _handoff(tenant_id, agent_id, execution_id=execution_id, call_id=call_id)

    await _erase_subject(tenant_id, phone)

    rendered = str(await _proof(tenant_id))
    assert REASON not in rendered and SUMMARY not in rendered


async def test_a_re_run_reports_the_work_once() -> None:
    """Idempotent by predicate, for `call_extractions`' reason: arq re-runs this job on
    any storage failure, and a re-run must not report a second, larger count."""
    tenant_id, agent_id = await _tenant()
    phone = _phone()
    call_id, execution_id = await _call(tenant_id, agent_id, phone=phone)
    await _handoff(tenant_id, agent_id, execution_id=execution_id, call_id=call_id)

    first = await _erase_subject(tenant_id, phone)
    second = await _erase_subject(tenant_id, phone)

    assert "handoff_briefs=1" in first, first
    assert "handoff_briefs=0" in second, second


# ============================================================================
# 2. The clock (the sweep the brief was also outside of)
# ============================================================================


async def test_the_brief_expires_on_the_transcript_clock() -> None:
    """`DERIVED_COPIES`: a retelling of the conversation lives and dies with the turns it
    paraphrases. Before this the table was in no category at all, so nothing expired it."""
    tenant_id, agent_id = await _tenant()
    old_call, old_exec = await _call(tenant_id, agent_id, phone=_phone(), days_ago=400)
    young_call, young_exec = await _call(tenant_id, agent_id, phone=_phone(), days_ago=10)
    old = await _handoff(
        tenant_id, agent_id, execution_id=old_exec, call_id=old_call, started_ago_days=400
    )
    young = await _handoff(
        tenant_id, agent_id, execution_id=young_exec, call_id=young_call, started_ago_days=10
    )

    counts = await sweep_tenant(tenant_id)

    assert counts["handoff_briefs"] == 1, counts
    assert (await _row(tenant_id, old))["reason"] is None
    assert (await _row(tenant_id, young))["reason"] == REASON


async def test_a_brief_with_no_call_row_still_expires_on_its_own_started_at() -> None:
    """The nullable-FK trap `_call_clock` already learned once: a missing foreign field
    must not switch a retention obligation off. `settle_handoff` back-fills
    `source_call_id`, so a handover whose pipeline never ran has none — and would have
    been the row that never expires."""
    tenant_id, agent_id = await _tenant()
    orphan = await _handoff(
        tenant_id,
        agent_id,
        execution_id=f"orphan_{uuid.uuid4().hex[:10]}",
        call_id=None,
        started_ago_days=400,
    )

    await sweep_tenant(tenant_id)

    assert (await _row(tenant_id, orphan))["reason"] is None


# ============================================================================
# 3. The tenant-wide erasure (FLOWS §9)
# ============================================================================


async def test_offboarding_clears_every_brief_and_says_so() -> None:
    """A tenant erasure that left them would keep a model's account of every caller who
    asked for a person, for a client that no longer exists."""
    tenant_id, agent_id = await _tenant()
    call_id, execution_id = await _call(tenant_id, agent_id, phone=_phone())
    attempt_id = await _handoff(tenant_id, agent_id, execution_id=execution_id, call_id=call_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = 'churned' WHERE id = :t"), {"t": tenant_id}
        )
        record = await request_tenant_erasure(session, tenant_id=tenant_id, reason="offboarding")

    await execute_tenant_erasure({}, {"tenant_id": str(tenant_id), "request_id": str(record.id)})

    assert (await _row(tenant_id, attempt_id))["reason"] is None
    async with tenant_session(tenant_id) as session:
        proof = (
            await session.execute(
                text("SELECT proof FROM tenant_erasure_requests WHERE id = :r"), {"r": record.id}
            )
        ).scalar()
    assert isinstance(proof, dict)
    assert proof["actions"]["handoff_attempts"].startswith("1 handover brief(s)")
