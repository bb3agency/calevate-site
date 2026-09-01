"""A lead's own SENTENCE, and that every way of forgetting a lead reaches it (D-503/D-504).

**WHY THIS FILE ASSERTS A SENTENCE AND NEVER A ROW COUNT.** The defect this scope is most
exposed to leaves the rows exactly where they were. A DPDP erasure does not DELETE a lead —
it anonymizes it in place (`phone_e164` prefixed, `name = NULL`, `data = '{}'::jsonb`),
because `lead_events` and `calls` reference the row — so nothing cascades, and a projection
that was never reached keeps its `tsvector` and its vector while every count in the
certificate reads correct. `SELECT count(*) FROM caller_chunks` passes against that bug.
`tsv @@ plainto_tsquery('english', 'pooja')` does not.

So each test below takes one distinctive phrase out of the lead's captured answers, proves
the store can FIND it, performs the forgetting, and then proves the phrase is unreachable
by both keys and unrecoverable from the lexemes. "Unreachable" is asserted three ways,
because each catches a different half-fix:

* the SEARCH returns nothing — the property a client experiences;
* no `tsv` in the tenant matches the phrase — the sparse key really is empty, not merely
  filtered out of the result by a predicate somebody could remove;
* `embedding IS NULL` — an embedding is a copy of the sentence in a form no `tsv` check
  would notice, and it is substantially invertible with the model.

**THE VECTOR IS NEVER BOUGHT HERE, AND THE TEST IS STRONGER FOR IT.** No embedding price is
attested in a test environment, so `embedding_price_is_billable()` is False, the sweep buys
nothing and the search's dense arm is skipped (hard rule 7's pre-flight, checked BEFORE the
provider). What remains is the sparse arm over `to_tsvector('english', <the lead's own
words>)` — which is the caller's sentence as lexemes, and exactly the copy that survives an
erasure nobody wired.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance import tenant_erasure
from apps.api.core.errors import ProblemError
from apps.api.crm import routes as crm_routes
from apps.api.crm.lead_chunks import discover_lead_chunks
from apps.api.crm.lead_projection import LEAD_SUBJECT_KIND
from apps.api.crm.lead_search import search_leads
from apps.api.crm.schemas import LeadLensIn, LeadSearchIn
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.retrieval.caller_projections import registered_projections, store_chunks
from apps.workers.retention import (
    apply_retention,
    execute_deletion_request,
    execute_tenant_erasure,
)
from sqlalchemy import text
from tests.conftest import accept_agreements

#: The phrase under test. Rare enough that a match cannot be a coincidence, and it is a
#: CAPTURED ANSWER rather than a name or a number — the only class of lead data this scope
#: projects at all (`crm/lead_projection.py`).
SENTENCE = "wants a 3BHK with a pooja room facing east"

#: The lexeme the assertions hunt for. One ordinary English word from `SENTENCE`, so the
#: query is stemmed and configured exactly as the stored vector was
#: (`caller_projections.TS_CONFIG`) — a mismatch there returns an empty result rather than
#: an error, which is the failure this suite must not be able to mistake for success.
NEEDLE = "pooja room"

#: The client's capture list, as a real one looks: a text field and an enum that carry the
#: answer, a phone-hinted field that must NEVER be projected, and a number that must not be
#: either. `scripts/seed.VERTICAL_TEMPLATES["real_estate"]` is the shape this follows.
FIELDS: list[dict[str, Any]] = [
    {"key": "requirement", "label": "Requirement", "type": "text", "required": False},
    {"key": "preferred_location", "label": "Location", "type": "text", "required": False},
    {
        "key": "bhk_size",
        "label": "BHK",
        "type": "enum",
        "enum_values": ["1BHK", "2BHK", "3BHK", "4BHK+"],
        "required": False,
    },
    {"key": "budget_lakhs", "label": "Budget (lakhs)", "type": "number", "required": False},
    {
        "key": "alt_number",
        "label": "Alternate number",
        "type": "text",
        "reason": "a second phone number to reach them on",
        "required": False,
    },
]

#: The captured answers. `alt_number` and `budget_lakhs` are here to be EXCLUDED — the
#: exclusion tests below assert they never reach the store.
DATA = {
    "requirement": SENTENCE,
    "preferred_location": "Gachibowli",
    "bhk_size": "3BHK",
    "budget_lakhs": 95,
    "alt_number": "9876500099",
}

#: The schema VERSION the lead is captured under. Deliberately not 1: `lead_chunks` reads
#: `extraction_schemas` at the lead's own version rather than taking the latest, and a
#: fixture at version 1 would pass whether or not it did.
SCHEMA_VERSION = 7


async def _tenant_with_projected_lead(
    phone: str, *, days_ago: int = 0
) -> tuple[uuid.UUID, uuid.UUID]:
    """An account holding one lead, projected into `caller_chunks` by the real path.

    `days_ago` backdates the lead's `updated_at` BEFORE the projection runs, because that
    column is the lead's retention clock and `occurred_at` copies it — a lead projected
    today and backdated afterwards would carry today's clock and the retention arm would
    correctly refuse to expire it.
    """
    created = await admin_service.create_organization(
        name="Vector Realty",
        slug=f"vec-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    agent_id = uuid.UUID(str(created["agent_id"]))
    await accept_agreements(tenant_id)
    lead_id = uuid.uuid4()

    # `apply_retention` resolves its tenants from `engine_agent_routes` — the same global
    # bridge the poller uses, with no RLS exemption — so an account with rows and no
    # published agent is a shape production cannot produce and the sweep would skip.
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :ref, :t, :a, true, now(), now())"
            ),
            {"ref": f"vec_{lead_id.hex[:12]}", "t": tenant_id, "a": agent_id},
        )

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO extraction_schemas (id, tenant_id, agent_id, version, fields, "
                "created_at, updated_at) VALUES (:i, :t, :a, :v, CAST(:f AS jsonb), now(), now())"
            ),
            {
                "i": uuid.uuid4(),
                "t": tenant_id,
                "a": agent_id,
                "v": SCHEMA_VERSION,
                "f": json.dumps(FIELDS),
            },
        )
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, schema_version, created_at, updated_at) VALUES (:i, :t, :a, :p, 'Ravi', "
                "'inbound_call', 'new', CAST(:d AS jsonb), :v, :w, :w)"
            ),
            {
                "w": datetime.now(UTC) - timedelta(days=days_ago),
                "i": lead_id,
                "t": tenant_id,
                "a": agent_id,
                "p": phone,
                "d": json.dumps(DATA),
                "v": SCHEMA_VERSION,
            },
        )
        # THE REAL INGESTION PATH, minus the provider: the scope's own discovery and the
        # SHARED store. Writing rows by hand here would test a fixture rather than the
        # projection, and the projection is where the exclusions live.
        chunks = await discover_lead_chunks(session, 10)
        assert chunks, "the lead scope discovered nothing to project"
        [projection] = [p for p in registered_projections() if p.subject_kind == LEAD_SUBJECT_KIND]
        await store_chunks(session, tenant_id=tenant_id, projection=projection, chunks=chunks)
    return tenant_id, lead_id


async def _matching_chunks(tenant_id: uuid.UUID, needle: str) -> int:
    """How many of this tenant's projections still match `needle` on the SPARSE key."""
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM caller_chunks "
                        "WHERE tsv @@ plainto_tsquery('english', :q)"
                    ),
                    {"q": needle},
                )
            ).scalar_one()
        )


async def _live_vectors(tenant_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM caller_chunks "
                        "WHERE embedding IS NOT NULL OR tsv <> ''::tsvector"
                    )
                )
            ).scalar_one()
        )


async def test_the_lead_is_findable_by_what_the_caller_asked_for() -> None:
    """The control. Every "it is gone" assertion below is worthless without this one:
    a store that never held the sentence passes an erasure test trivially."""
    tenant_id, lead_id = await _tenant_with_projected_lead("+919876500101")
    assert await _matching_chunks(tenant_id, NEEDLE) == 1

    async with tenant_session(tenant_id) as session:
        found = await search_leads(session, tenant_id=tenant_id, question="3BHK in Gachibowli")
    assert [lead.id for lead in found.leads] == [lead_id]
    assert found.ranked == 1


async def test_the_projection_carries_no_phone_number_and_no_scalar() -> None:
    """The exclusions, asserted against the STORE and not against the pure function.

    `lead_projection_test.py` proves `project_field` refuses them; this proves nothing
    downstream put them back — a phone number in a `tsvector` is a phone number in an index
    (hard rule 6), and it is reachable by anyone who can search.
    """
    tenant_id, _ = await _tenant_with_projected_lead("+919876500102")
    assert await _matching_chunks(tenant_id, "9876500099") == 0, "an alternate number was indexed"
    assert await _matching_chunks(tenant_id, "95") == 0, "a numeric field was indexed"
    assert await _matching_chunks(tenant_id, "Ravi") == 0, "the caller's name was indexed"


async def test_a_dpdp_erasure_makes_the_sentence_unreachable() -> None:
    """§12, per caller. The lead row SURVIVES and is anonymized — so nothing cascades, and
    only an explicit arm reaches the vector store."""
    phone = "+919876500103"
    tenant_id, lead_id = await _tenant_with_projected_lead(phone)
    assert await _matching_chunks(tenant_id, NEEDLE) == 1

    request_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO deletion_requests (id, tenant_id, phone_e164, scope, requested_at, "
                "created_at) VALUES (:i, :t, :p, 'all', now(), now())"
            ),
            {"i": request_id, "t": tenant_id, "p": phone},
        )
    result = await execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )
    assert "erased" in result

    # 1. THE SENTENCE. Not a count of rows — the rows are still there, as tombstones.
    assert await _matching_chunks(tenant_id, NEEDLE) == 0
    assert await _matching_chunks(tenant_id, "Gachibowli") == 0
    # 2. NEITHER KEY SURVIVES. `tsv` is the sentence as lexemes and the embedding is the
    #    sentence as floats; forgetting one and keeping the other forgets nothing.
    assert await _live_vectors(tenant_id) == 0

    async with tenant_session(tenant_id) as session:
        # 3. THE SEARCH, which is what a person actually has. It must not merely rank the
        #    lead lower — it must not find it.
        found = await search_leads(session, tenant_id=tenant_id, question=SENTENCE)
        assert found.leads == ()
        lead = (
            await session.execute(
                text("SELECT phone_e164, data FROM leads WHERE id = :i"), {"i": lead_id}
            )
        ).first()
    # THE PREMISE OF THE WHOLE FILE, asserted rather than assumed: the lead row is still
    # here. If this ever fails, a cascade has started doing the work and these tests would
    # pass for the wrong reason.
    assert lead is not None, "a DPDP erasure must not delete the lead row"
    assert phone not in str(lead[0]) and lead[1] == {}


async def test_a_tenant_erasure_makes_the_sentence_unreachable() -> None:
    """End of engagement. It holds no phone numbers at all, so it cannot reach these rows
    by subject ref — the unconditional tenant arm is what covers them."""
    tenant_id, _ = await _tenant_with_projected_lead("+919876500104")
    assert await _matching_chunks(tenant_id, NEEDLE) == 1

    # THROUGH THE REAL FILING PATH. `execute_tenant_erasure` refuses to certify an
    # organisation it cannot mark deleted, and `request_tenant_erasure` is what establishes
    # the preconditions it checks — a hand-written row passes the INSERT and fails the
    # worker, which is a fixture testing itself.
    async with tenant_session(tenant_id) as session:
        # The precondition the filing path checks: an account is erasable only once it is
        # CHURNED (`tenant_erasure.REQUIRED_STATUS`). Set through the directory rather than
        # asserted away, so this test exercises the same gate production does.
        await session.execute(
            text("UPDATE organizations SET status = :s WHERE id = :t"),
            {"s": tenant_erasure.REQUIRED_STATUS, "t": tenant_id},
        )
    async with tenant_session(tenant_id) as session:
        record = await tenant_erasure.request_tenant_erasure(
            session, tenant_id=tenant_id, reason="engagement ended"
        )
    await execute_tenant_erasure({}, {"tenant_id": str(tenant_id), "request_id": str(record.id)})

    assert await _matching_chunks(tenant_id, NEEDLE) == 0
    assert await _live_vectors(tenant_id) == 0


async def test_the_lead_retention_clock_reaches_the_projection() -> None:
    """The third way a lead is forgotten, and the one with no request behind it.

    A projection carries `occurred_at = leads.updated_at`, so it expires on the tenant's own
    `lead` policy — the SAME clock `retention._LEAD_SQL` anonymizes the lead by, and never a
    day later. A vector that outlived the record it projects would make "leads are kept for
    N days" true of a table and false of a person, which is the sentence `DERIVED_COPIES`
    exists to keep honest.
    """
    # Past the default `lead` TTL (1095 days), so the tenant's own policy is what expires
    # it rather than a value this test invented.
    tenant_id, _ = await _tenant_with_projected_lead("+919876500105", days_ago=1200)
    assert await _matching_chunks(tenant_id, NEEDLE) == 1

    await apply_retention({})

    assert await _matching_chunks(tenant_id, NEEDLE) == 0
    assert await _live_vectors(tenant_id) == 0


# ── the two route seams the lens travels through ─────────────────────────────────────


async def test_the_table_route_answers_the_question_through_the_same_lens() -> None:
    """`ask` is a FIELD on the lens, not a second route, and this proves the branch keeps
    the rest of the lens intact.

    A client asking "3BHK in Gachibowli" inside "hot leads assigned to me" is asking ONE
    question. Two routes would have meant two column resolutions, two facet parsers and
    two places for the two to drift — so the semantic branch reuses every one of them and
    replaces only the ROWS and their ORDER. What it must therefore still return is the
    resolved column list, which is what the screen renders and what the CSV header is
    built from.
    """
    tenant_id, lead_id = await _tenant_with_projected_lead("+919876500131")

    async with tenant_session(tenant_id) as session:
        asked = await crm_routes._leads_page(
            session, LeadSearchIn(ask="3BHK in Gachibowli"), tenant_id=tenant_id
        )
        plain = await crm_routes._leads_page(session, LeadSearchIn(), tenant_id=tenant_id)

    assert [lead.id for lead in asked.items] == [lead_id]
    assert asked.total == 1
    # The columns are the lens's answer and must not depend on which arm produced the rows:
    # a semantic search that rendered different columns would be a second screen.
    assert [c.key for c in asked.columns] == [c.key for c in plain.columns]
    assert [c.key for c in asked.available_columns] == [c.key for c in plain.available_columns]


async def test_the_csv_export_refuses_a_question_rather_than_dropping_it() -> None:
    """The widest possible read of the narrowest possible request, refused BY NAME.

    `LeadLensIn` is shared by the table and the file. An `ask` the export silently dropped
    would hand a client who had narrowed their screen to four matching leads a CSV of
    their ENTIRE contact list with full phone numbers. The refusal is what makes the
    shared lens safe; without it the sharing is the bug.

    It is a refusal rather than an implementation because the honest export of a RANKING
    is not the "complete filtered set" a CSV promises — deciding what an exported ranking
    IS is a product answer, and until it exists the file must not pretend.
    """
    tenant_id, _ = await _tenant_with_projected_lead("+919876500132")

    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await crm_routes._export_and_summary(session, LeadLensIn(ask=NEEDLE))
        # The same lens WITHOUT the question exports normally, so the refusal is about the
        # question and not about the export being broken.
        export, summary = await crm_routes._export_and_summary(session, LeadLensIn())

    assert refused.value.code == "ask_cannot_be_exported"
    assert export.row_count == 1, "the filter-only export still produces the file"
    assert "ask" not in summary, "the audit row records ids, keys and counts — never the text"
