"""The gap quotes an erasure destroys have to be ACCOUNTED FOR on the certificate.

**THE DEFECT.** `scrub_quotes_for_calls` was written because the knowledge-gap tables held
the caller's own question — copied out of `transcript_turns.text_redacted` at detection
time — and no erasure path reached them. Both erasure entry points call it now, and
`tests/knowledge_gap_erasure_test.py` proves the sentence really goes.

What neither path did was SAY so. `execute_deletion_request` wrote
`scope.knowledge_gap_quotes_erased` into the durable proof under a comment claiming it was
"ON THE CERTIFICATE, not just in the log … counted where they can see it" — and it was on
neither certificate:

* `deletion_proof.certificate` builds `scope` from a FIXED field list and does not list
  it, and `deletion_routes.ErasureScopeOut` (`extra="forbid"`) does not model it either,
  so the number stopped at the stored row;
* the tenant path was worse — `tenant_erasure._SCOPE_COUNTS` does not carry it and its
  `actions` had no sentence at all, so a client winding down was told less than had
  actually been done for their callers.

That is the shape this whole area keeps producing: a property asserted in a comment that
nothing measured. A certificate that under-states is not a safe error — its whole function
is to be the record of what was done, and a reader cannot tell "we did not report it" from
"we did not do it", which is exactly the ambiguity the gap tables were in before.

**THE FIX IS A SENTENCE IN `actions`, NOT A FIELD IN `scope`**, and that is the repository's
existing answer rather than a new one: `scope` is a whitelist both the renderer and the
response model enumerate, so a key added there is a wire-shape change, while `actions` is
`dict[str, str]` and passes through verbatim. `webhook_deliveries`, `engine_payloads` and
`campaign_contacts` all ride that route already, each with the same comment.

These tests run the REAL workers against a real database and assert on the rendered
certificate, not on the stored dict: the stored dict was never the thing that was broken.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance.deletion_proof import certificate
from apps.api.compliance.deletion_routes import ErasureProofOut
from apps.api.compliance.export import subject_ref
from apps.api.compliance.tenant_erasure import certificate as tenant_certificate
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.insights import service as insights
from apps.api.insights.detection import RedactedTurn
from apps.workers.retention import execute_deletion_request, execute_tenant_erasure
from sqlalchemy import text

pytestmark = pytest.mark.anyio

#: The caller's own words. Survives redaction intact — it names no identifier — which is
#: the reason the gap tables were the last copy of it after an erasure.
CALLER_WORDS = "Do you do IVF, my wife and I have been trying for six years?"
AGENT_WORDS = "I don't know about that, I'll have someone WhatsApp you."


def _phone() -> str:
    """A fresh subject per test: several suites share this database."""
    return f"+9198763{uuid.uuid4().int % 100000:05d}"


async def _org() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Gap Account Clinic",
        slug=f"ega-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :ref, :t, :a, true, now(), now())"
            ),
            {"ref": f"ega_{uuid.uuid4().hex[:12]}", "t": tenant_id, "a": agent_id},
        )
    return tenant_id, agent_id


async def _call_with_a_gap(tenant_id: uuid.UUID, agent_id: uuid.UUID, phone: str) -> uuid.UUID:
    """One completed call whose transcript left a quoted question in both gap tables."""
    call_id = uuid7()
    when = datetime.now(UTC) - timedelta(hours=2)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, started_at, ended_at, duration_s, created_at, updated_at) "
                "VALUES (:id, :t, :a, :e, 'inbound', 'completed', :phone, '+911140000000', "
                ":w, :w, 120, :w, :w)"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"ega_{uuid.uuid4().hex[:12]}",
                "phone": phone,
                "w": when,
            },
        )
    recorded = await insights.record_call_gaps(
        tenant_id=tenant_id,
        agent_id=agent_id,
        call_id=call_id,
        turns=[
            RedactedTurn(speaker="caller", text=CALLER_WORDS),
            RedactedTurn(speaker="agent", text=AGENT_WORDS),
        ],
    )
    assert recorded == 1, "fixture precondition: the detector stored the caller's question"
    return call_id


async def _file_request(tenant_id: uuid.UUID, phone: str) -> uuid.UUID:
    """The `deletion_requests` row the worker resolves the subject from.

    Written directly rather than through `request_erasure` so the test exercises the
    WORKER and its proof, with no outbox dispatcher in the way.
    """
    request_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO deletion_requests (id, tenant_id, phone_e164, subject_ref, scope, "
                "requested_at, created_at) VALUES (:id, :t, :p, :ref, 'all', now(), now())"
            ),
            {"id": request_id, "t": tenant_id, "p": phone, "ref": subject_ref(phone)},
        )
    return request_id


async def _proof(table: str, request_id: uuid.UUID, tenant_id: uuid.UUID) -> dict:
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text(f"SELECT proof FROM {table} WHERE id = :id"), {"id": request_id}
            )
        ).scalar()
    assert isinstance(stored, dict), "the worker wrote no proof"
    return stored


# --- the subject path ----------------------------------------------------------------


async def test_the_subject_certificate_states_the_gap_quotes_it_destroyed() -> None:
    """THE REGRESSION. The work happened and the document said nothing about it."""
    tenant_id, agent_id = await _org()
    phone = _phone()
    await _call_with_a_gap(tenant_id, agent_id, phone)
    request_id = await _file_request(tenant_id, phone)

    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(request_id)})

    stored = await _proof("deletion_requests", request_id, tenant_id)
    assert stored["scope"]["knowledge_gap_quotes_erased"] == 1, stored["scope"]

    document = certificate(stored)
    assert document is not None
    # It must survive the response model that ships it — `extra="forbid"`, so an
    # unmodelled key is a 500 on the one endpoint whose subject is a person who asked to
    # be erased.
    ErasureProofOut(**document)
    sentence = document["actions"].get("knowledge_gaps")
    assert sentence is not None, (
        "the certificate accounts for the knowledge-gap quotes nowhere: not in `scope` "
        "(the renderer builds that from a fixed field list) and not in `actions`. The "
        "erasure destroyed the caller's own question and the document does not say so."
    )
    assert "1" in sentence, sentence


async def test_the_count_is_not_in_the_rendered_scope_which_is_why_the_sentence_exists() -> None:
    """The reason the fix is a sentence and not a field, pinned so nobody undoes it.

    If `knowledge_gap_quotes_erased` is ever modelled on `ErasureScopeOut`, this test
    turns red and the sentence can be revisited in the same change — which is the
    conversation that should happen, rather than two half-answers coexisting.
    """
    tenant_id, agent_id = await _org()
    phone = _phone()
    await _call_with_a_gap(tenant_id, agent_id, phone)
    request_id = await _file_request(tenant_id, phone)
    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(request_id)})

    document = certificate(await _proof("deletion_requests", request_id, tenant_id))
    assert document is not None
    assert "knowledge_gap_quotes_erased" not in document["scope"], (
        "the count is now a first-class certificate field — good, but the `actions` "
        "sentence is then a second way of saying one thing (CLAUDE.md: one way per "
        "problem). Pick one and update this test."
    )


async def test_the_words_are_gone_which_is_what_the_sentence_attests_to() -> None:
    """The claim and the fact, in one test. A certificate whose sentence is true only
    because nobody checked is the failure this round exists to find."""
    tenant_id, agent_id = await _org()
    phone = _phone()
    await _call_with_a_gap(tenant_id, agent_id, phone)
    request_id = await _file_request(tenant_id, phone)
    await execute_deletion_request({}, {"tenant_id": str(tenant_id), "request_id": str(request_id)})

    async with tenant_session(tenant_id) as session:
        occurrences = (
            await session.execute(
                text("SELECT question_redacted, answer_redacted FROM knowledge_gap_occurrences")
            )
        ).all()
        aggregates = (
            await session.execute(
                text(
                    "SELECT example_question_redacted, example_answer_redacted FROM knowledge_gaps"
                )
            )
        ).all()
    haystack = " ".join(str(cell) for row in [*occurrences, *aggregates] for cell in row)
    assert CALLER_WORDS not in haystack, "the caller's question survived the erasure"
    assert AGENT_WORDS not in haystack, "the agent's reply to them survived the erasure"


# --- the tenant path -----------------------------------------------------------------


async def test_the_tenant_certificate_states_the_gap_quotes_it_destroyed() -> None:
    """The same account, at the end of an engagement. `_erase_tenant_calls` has scrubbed
    these quotes page by page all along and its certificate reported it in no field and
    no sentence."""
    tenant_id, agent_id = await _org()
    await _call_with_a_gap(tenant_id, agent_id, _phone())

    request_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = 'churned' WHERE id = :t"), {"t": tenant_id}
        )
        await session.execute(
            text(
                "INSERT INTO tenant_erasure_requests (id, tenant_id, reason, requested_at, "
                "created_at) VALUES (:id, :t, 'engagement ended', now(), now())"
            ),
            {"id": request_id, "t": tenant_id},
        )

    await execute_tenant_erasure({}, {"tenant_id": str(tenant_id), "request_id": str(request_id)})

    stored = await _proof("tenant_erasure_requests", request_id, tenant_id)
    assert stored["scope"]["knowledge_gap_quotes_erased"] == 1, stored["scope"]

    document = tenant_certificate(stored)
    assert document is not None
    sentence = document["actions"].get("knowledge_gaps")
    assert sentence is not None, (
        "the tenant erasure certificate accounts for the knowledge-gap quotes nowhere — "
        "not in `_SCOPE_COUNTS` and not in `actions` — while the erasure destroyed them"
    )
    assert "1" in sentence, sentence
