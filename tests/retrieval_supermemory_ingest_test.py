"""The WRITE half of box 3: ingestion, withdrawal, erasure, money and convergence.

**THERE IS NO NETWORK IN THIS FILE AND THERE MUST NOT BE**, for
`tests/retrieval_supermemory_test.py`'s reason: Supermemory is not installed and
`supermemory.ai` is egress-blocked from this container (`docs/PIPECAT-MIGRATION.md` §8.5),
so the vendor is faked at the one seam that touches a socket — `SupermemoryTransport` — and
everything above it, including the real publish path and the real erasure worker, runs for
real against the real database.

WHAT EACH GROUP DEFENDS:

* **Ingestion** — a client publishing knowledge puts it in box 3, tagged, with the metadata
  the read side cites back to them.
* **Tenancy** — §8.4 leaves the wall on our side, so a WRITE must be impossible to express
  without a scope, not merely discouraged.
* **Withdrawal and erasure** — content a client retracted leaves; a DPDP erasure takes
  everything of theirs and REFUSES to issue a certificate it cannot stand behind.
* **Failure** — box 3 being down must not fail a publish, and must not lose the work either.
* **Money** — hard rule 7: no attested price, no writes at all; and an ingest whose cost
  cannot be recorded says so rather than recording a zero.
* **Logs** — hard rule 6: ids and counts. Never the client's prose.
"""

from __future__ import annotations

import inspect
import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.billing.rates import LlmPriceAttestation, install_llm_price_attestations
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from apps.api.retrieval import supermemory_index
from apps.api.retrieval.supermemory import SupermemoryClient
from apps.api.retrieval.supermemory_index import (
    ASSIST_FEATURE_SUPERMEMORY_INGEST,
    purge_tenant_index,
)
from apps.api.retrieval.supermemory_wire import (
    ASSUMED_CONTRACT,
    TenantScope,
    delete_payload,
    ingest_payload,
    parse_search,
)
from apps.workers import kb_index_sync, retention
from sqlalchemy import text
from tests.kb_workflow_test import _tenant_with_published_agent

#: The stand-in an operator would name in `Settings.supermemory_embedding_model`, and
#: deliberately not a real vendor identifier — which model a box 3 install actually embeds
#: with is UNVERIFIED here (§8.3). What is under test is the price GATE, not the name.
_MODEL = "fixture-embedding-model"

#: The client's own prose. Distinctive so a log assertion can look for it.
_BODY = "Consultation costs 500 rupees and Sunday is closed."


@pytest.fixture
def attested_price() -> Any:
    """An operator attestation for `_MODEL`. **The only thing that makes box 3 writable.**

    No embedding price has been read from a vendor page in this container, so
    `llm_price_is_billable` is False for every embedding model in the tree until somebody
    enters their own invoice figure — which makes this fixture the documentation of what an
    operator must do before one byte is written to box 3.
    """
    attestation = LlmPriceAttestation(
        model=_MODEL,
        input_usd_per_mtok=Decimal("0.02"),
        output_usd_per_mtok=Decimal("0.02"),
        read_on=date(2026, 9, 15),
        attested_by="test",
        source="fixture",
    )
    install_llm_price_attestations(lambda: {_MODEL: attestation})
    yield attestation
    install_llm_price_attestations(None)


class FakeVendor:
    """Box 3, without a socket. Records every body; answers what it was told to.

    `raises` wins over the bodies, so one class covers "the vendor answered oddly" and "the
    vendor did not answer" — the two halves of §8.5's degradation promise, on the write side.
    """

    def __init__(self, *, raises: Exception | None = None, usage: bool = True) -> None:
        self.raises = raises
        self.usage = usage
        self.ingests: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []

    async def post(
        self, path: str, payload: dict[str, Any], *, timeout_s: float = 8.0
    ) -> dict[str, Any]:
        if self.raises is not None:
            raise self.raises
        if path == ASSUMED_CONTRACT.ingest_path:
            self.ingests.append(payload)
        elif path == ASSUMED_CONTRACT.delete_path:
            self.deletes.append(payload)
        else:  # pragma: no cover - a path this suite does not exercise
            raise AssertionError(f"unexpected path {path}")
        return {"usage": {"promptTokens": 120}} if self.usage else {}


@pytest.fixture
def box3(monkeypatch: pytest.MonkeyPatch, attested_price: Any) -> FakeVendor:
    """A configured, priced, reachable box 3. Patched at the TRANSPORT and nowhere else.

    The publish path builds its own indexer through `supermemory_indexer`, which is the
    point: what is under test is the real constructor's four preconditions and the real
    call site, with only the socket replaced.
    """
    vendor = FakeVendor()
    _configure(monkeypatch, vendor)
    return vendor


def _configure(monkeypatch: pytest.MonkeyPatch, vendor: FakeVendor) -> None:
    settings = supermemory_index.get_settings()
    monkeypatch.setattr(settings, "supermemory_base_url", "http://127.0.0.1:8765")
    monkeypatch.setattr(settings, "supermemory_api_key", "fixture-key")
    monkeypatch.setattr(settings, "supermemory_embedding_model", _MODEL)
    monkeypatch.setattr(supermemory_index, "HttpxTransport", lambda *, base_url, api_key: vendor)


async def _publish(tenant_id: uuid.UUID, agent_id: uuid.UUID, *, body: str = _BODY) -> uuid.UUID:
    """Submit, approve and publish one source through the REAL path. Returns its id."""
    async with tenant_session(tenant_id) as session:
        source = await kb_service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Fees", body=body
        )
    async with tenant_session(tenant_id) as session:
        await kb_service.approve_source(session, source_id=source["id"], approved_by=None)
        await kb_service.publish_source(session, tenant_id=tenant_id, source_id=source["id"])
    return uuid.UUID(str(source["id"]))


async def _ledger(tenant_id: uuid.UUID) -> list[Any]:
    async with tenant_session(tenant_id) as session:
        return list(
            (
                await session.execute(
                    text(
                        "SELECT document_id, source_id, agent_id, content_sha256 "
                        "FROM kb_index_documents ORDER BY document_id"
                    )
                )
            ).all()
        )


# --- ingestion: a publish reaches the store -------------------------------------------


async def test_publishing_a_source_writes_its_chunks_into_box_three_with_the_tenant_scope(
    box3: FakeVendor,
) -> None:
    """The half that did not exist. A client publishes; box 3 holds it, tagged.

    THE TAGS ARE THE ASSERTION, not the count: §8.4 makes the container tag the ONLY thing
    separating this client's documents from the next one's, because the local build is
    single-tenant with one API key. A document written untagged is invisible to its own
    tenant's scoped query and unreachable by the erasure that would have to remove it.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish(tenant_id, agent_id)

    assert box3.ingests, "publishing knowledge wrote nothing to the store that serves search"
    for body in box3.ingests:
        assert body[ASSUMED_CONTRACT.container_tags_key] == [
            f"tenant:{tenant_id}",
            f"agent:{agent_id}",
        ]
        assert body[ASSUMED_CONTRACT.content_key]
    # And the ledger records exactly what was sent, which is what every later difference is
    # measured against.
    ledger = await _ledger(tenant_id)
    assert len(ledger) == len(box3.ingests)
    assert {str(row[0]) for row in ledger} == {
        body[ASSUMED_CONTRACT.document_id_key] for body in box3.ingests
    }


async def test_the_metadata_written_at_ingest_is_the_provenance_a_search_reads_back(
    box3: FakeVendor,
) -> None:
    """The round trip that makes a citation possible, asserted end to end.

    The write side and the read side use the same four contract keys, so this feeds an
    ingest body back through `parse_search` as if the vendor had returned it. A test that
    only checked the keys were present would pass while the two halves disagreed about
    which key means what.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish(tenant_id, agent_id)
    sent = box3.ingests[0]

    scope = TenantScope.for_publish(tenant_id=tenant_id, agent_id=agent_id)
    record = {
        ASSUMED_CONTRACT.text_key: sent[ASSUMED_CONTRACT.content_key],
        ASSUMED_CONTRACT.result_tags_key: sent[ASSUMED_CONTRACT.container_tags_key],
        ASSUMED_CONTRACT.metadata_key: sent[ASSUMED_CONTRACT.metadata_key],
        ASSUMED_CONTRACT.score_key: 0.9,
    }
    passages, rejected = parse_search({"results": [record]}, scope=scope)
    assert rejected == 0
    assert passages[0].provenance.label == "Fees"
    assert passages[0].provenance.agent_id == agent_id
    assert passages[0].provenance.document_version == 1
    assert passages[0].provenance.source_id is not None


# --- tenancy: a write cannot be expressed without a scope ------------------------------


def test_no_write_body_can_be_built_without_a_tenant_scope() -> None:
    """**THE STRUCTURAL PROOF ON THE WRITE SIDE.** §8.4 leaves the wall on our side, and an
    unscoped WRITE is worse than an unscoped read: a document filed under nobody is invisible
    to its own tenant's query AND unreachable by the tag-scoped delete an erasure sends. The
    scope is a required positional of a type no string can stand in for, and each builder
    re-reads the tag out of the body it just built."""
    scope = TenantScope.for_publish(tenant_id=uuid.uuid4(), agent_id=uuid.uuid4())
    body = ingest_payload(
        scope,
        document_id=uuid.uuid4(),
        content="Sunday is closed.",
        source_id=uuid.uuid4(),
        source_label="Fees",
        document_version=1,
    )
    assert body[ASSUMED_CONTRACT.container_tags_key][0] == scope.tenant_tag
    assert delete_payload(scope)[ASSUMED_CONTRACT.container_tags_key][0] == scope.tenant_tag

    with pytest.raises(TypeError):
        ingest_payload(  # type: ignore[call-arg]
            document_id=uuid.uuid4(),
            content="Sunday is closed.",
            source_id=uuid.uuid4(),
            source_label="Fees",
            document_version=1,
        )
    with pytest.raises(TypeError):
        delete_payload()  # type: ignore[call-arg]


def test_the_signature_guard_now_covers_the_write_methods_too() -> None:
    """`test_no_wire_method_can_be_called_without_a_tenant_scope` reads SIGNATURES, so it
    covers a method added later by construction. This asserts the covered set actually GREW
    — a guard that silently stopped seeing the write half would still be green."""
    names = {
        name
        for name, member in inspect.getmembers(SupermemoryClient, inspect.isfunction)
        if not name.startswith("_")
    }
    assert {"search", "ingest", "forget"} <= names
    for name in ("ingest", "forget"):
        first = list(inspect.signature(getattr(SupermemoryClient, name)).parameters.values())[1]
        assert first.name == "scope" and first.default is inspect.Parameter.empty


# --- withdrawal and erasure ------------------------------------------------------------


async def test_withdrawing_a_source_takes_its_documents_out_of_the_index(
    box3: FakeVendor,
) -> None:
    """A client retracts a price list; it stops being findable in the store search reads.

    This is the half a silent failure would hide: the source disappears from every screen,
    from the prompt and from the pack, and would go on answering dashboard questions out of
    box 3 with nothing anywhere saying so.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    source_id = await _publish(tenant_id, agent_id)
    written = {body[ASSUMED_CONTRACT.document_id_key] for body in box3.ingests}

    async with tenant_session(tenant_id) as session:
        await kb_service.withdraw_source(session, tenant_id=tenant_id, source_id=source_id)

    assert box3.deletes, "a withdrawn source was left in the search index"
    deleted = {
        document_id
        for body in box3.deletes
        for document_id in body.get(ASSUMED_CONTRACT.delete_ids_key, [])
    }
    assert deleted == written
    # The tag rides on the delete too — the only thing between a wrong id and a delete that
    # lands in somebody else's documents.
    assert box3.deletes[0][ASSUMED_CONTRACT.container_tags_key][0] == f"tenant:{tenant_id}"
    assert await _ledger(tenant_id) == []


async def test_a_tenant_erasure_removes_everything_of_theirs_and_leaves_the_neighbour(
    box3: FakeVendor,
) -> None:
    """DPDP §8, through the REAL worker. Everything of this tenant's leaves box 3.

    The neighbour half is the one that cannot be assumed: the purge is scoped by our own
    ledger and by a tag the server is not known to enforce, so a statement missing its
    tenant predicate would empty the whole platform's rows and nothing would fail.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish(tenant_id, agent_id)
    neighbour_id, neighbour_agent = await _tenant_with_published_agent()
    await _publish(neighbour_id, neighbour_agent)
    assert await _ledger(tenant_id)

    request_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = 'churned', updated_at = now() WHERE id = :t"),
            {"t": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO tenant_erasure_requests (id, tenant_id, reason, requested_at, "
                "created_at) VALUES (:id, :t, 'engagement ended', now(), now())"
            ),
            {"id": request_id, "t": tenant_id},
        )
    result = await retention.execute_tenant_erasure(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )
    assert result != "not_found"

    assert await _ledger(tenant_id) == [], "an erased account's index rows survived"
    assert await _ledger(neighbour_id), "the erasure emptied a neighbour's ledger"
    # The vendor was asked for a SCOPE-WIDE delete, not a list of ids: a purge that named
    # only what the ledger remembered would leave anything written before it behind.
    purge = box3.deletes[-1]
    assert purge[ASSUMED_CONTRACT.container_tags_key] == [f"tenant:{tenant_id}"]
    assert ASSUMED_CONTRACT.delete_ids_key not in purge

    async with tenant_session(tenant_id) as session:
        proof = (
            await session.execute(
                text("SELECT proof FROM tenant_erasure_requests WHERE id = :r"), {"r": request_id}
            )
        ).scalar()
    scope = dict(proof)["scope"]  # type: ignore[index]
    assert scope["indexed_documents_purged"] >= 1
    # The certificate says what was done AND what it is not: we cannot verify their delete
    # (`deletion_proof` is False), so it must not read as a proof.
    sentence = dict(proof)["actions"]["search_index"]  # type: ignore[index]
    assert "accepted request rather than a confirmed removal" in sentence


async def test_an_erasure_refuses_to_certify_a_copy_it_cannot_reach(
    monkeypatch: pytest.MonkeyPatch, box3: FakeVendor
) -> None:
    """Box 3 wrote documents; the credential is then gone. The erasure RAISES.

    The alternative is the one thing a compliance document may not be: a certificate
    covering content nobody can delete. Raising rolls the whole erasure back, so
    `organizations.deleted_at` stays NULL and arq's retry redoes it once an operator has
    restored the credential.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish(tenant_id, agent_id)
    monkeypatch.setattr(supermemory_index.get_settings(), "supermemory_api_key", None)

    async with tenant_session(tenant_id) as session:
        with pytest.raises(RuntimeError, match="cannot reach"):
            await purge_tenant_index(session, tenant_id=tenant_id)
    assert await _ledger(tenant_id), "the record of the unreachable copy was destroyed"


async def test_a_deployment_that_never_used_box_three_erases_without_complaint() -> None:
    """The other side of the same branch: no credential and no rows is nothing owed, not a
    failure. Every deployment that has not adopted box 3 takes this path on every erasure."""
    tenant_id, _ = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        assert await purge_tenant_index(session, tenant_id=tenant_id) == 0


def test_the_erasure_coverage_guard_can_see_this_table() -> None:
    """The ledger is reached FROM an erasure entrypoint, and the guard proves it by walking
    the call graph rather than by reading a docstring. `handoff_attempts` and
    `outbox_messages` are in that file because both were missed by a human reading."""
    from scripts.check_erasure_coverage import erasure_reach

    reach = erasure_reach()
    assert not reach.blind_spots
    assert "kb_index_documents" in reach.tables


# --- failure: the publish survives, and the work is not lost ---------------------------


async def test_box_three_being_down_does_not_fail_a_publish_and_the_sweep_converges(
    monkeypatch: pytest.MonkeyPatch, attested_price: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """§8.5's promise on the write side, and the reconciliation that makes it honest.

    A derived index must not veto the authored record it derives from — the publish COMMITS
    — but "does not fail" must not mean "is forgotten". Nothing was written to the ledger,
    so the difference still stands, and the sweep sends exactly the documents the publish
    could not. That is the property a worklist would not have: it consumes the event.
    """
    down = FakeVendor(raises=httpx.ConnectError("box 3 is down"))
    _configure(monkeypatch, down)
    tenant_id, agent_id = await _tenant_with_published_agent()

    with caplog.at_level(logging.ERROR):
        await _publish(tenant_id, agent_id)
    assert await _ledger(tenant_id) == [], "the ledger claimed a write the vendor refused"
    assert any(
        record.__dict__.get("code") == "supermemory_index_sync_failed" for record in caplog.records
    ), "a divergence between the corpus and the index was not reported to anybody"

    # The client's knowledge is live in our own store the whole time — the publish landed.
    async with tenant_session(tenant_id) as session:
        live = (
            await session.execute(text("SELECT count(*) FROM kb_chunks WHERE is_active"))
        ).scalar_one()
    assert live >= 1

    recovered = FakeVendor()
    _configure(monkeypatch, recovered)
    summary = await kb_index_sync.sync_knowledge_index({})
    # FILTERED TO THIS TENANT, because the sweep is fleet-wide and the suite's database
    # holds other tenants' corpora — which is itself the behaviour under test one level up.
    mine = [
        body
        for body in recovered.ingests
        if f"tenant:{tenant_id}" in body[ASSUMED_CONTRACT.container_tags_key]
    ]
    assert mine, "the sweep did not re-send what the failed publish could not"
    assert "ingested=" in summary
    assert len(await _ledger(tenant_id)) == len(mine)

    # AND IT IS A DIFFERENCE, NOT A WORKLIST: a second tick over a settled corpus sends
    # nothing, which is what makes the sweep affordable at all.
    settled = FakeVendor()
    _configure(monkeypatch, settled)
    await kb_index_sync.sync_knowledge_index({})
    assert settled.ingests == [] and settled.deletes == []


async def test_a_source_deleted_by_retention_is_still_withdrawn_from_the_index(
    monkeypatch: pytest.MonkeyPatch, box3: FakeVendor
) -> None:
    """THE CASE A CASCADE WOULD HAVE SWALLOWED, and the reason the ledger holds no FK.

    Retention DELETEs `kb_sources`; `kb_documents` and `kb_chunks` cascade with it and the
    vendor's copy does not. If the ledger row had cascaded too, the only record that box 3
    still holds this client's text would have been destroyed by the same statement that made
    it true — and no publish event would ever fire again to notice.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    source_id = await _publish(tenant_id, agent_id)
    written = len(box3.ingests)
    assert written

    async with tenant_session(tenant_id) as session:
        await session.execute(text("DELETE FROM kb_sources WHERE id = :s"), {"s": source_id})
    assert len(await _ledger(tenant_id)) == written, "the tombstone cascaded away with its row"

    sweeper = FakeVendor()
    _configure(monkeypatch, sweeper)
    await kb_index_sync.sync_knowledge_index({})
    assert sweeper.deletes, "a deleted source's documents were left in the index for ever"
    assert await _ledger(tenant_id) == []


# --- money: hard rule 7 ----------------------------------------------------------------


async def test_nothing_is_written_until_an_operator_has_attested_a_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**THE PRE-FLIGHT, ASKED BEFORE THE STORE IS EVER WRITTEN TO.** Ingestion buys an
    embedding and the vendor's own extraction pass; a price nobody attested has no path to
    `unit_cost_paid`, so the answer is not "meter it later" — it is that the write does not
    happen. The publish itself is unaffected, which is the whole point of the posture."""
    unattested = FakeVendor()
    _configure(monkeypatch, unattested)
    install_llm_price_attestations(None)
    tenant_id, agent_id = await _tenant_with_published_agent()

    await _publish(tenant_id, agent_id)

    assert unattested.ingests == [], "an unpriced embedding was bought anyway"
    assert await _ledger(tenant_id) == []


async def test_a_metered_ingest_writes_the_usage_it_was_told_about(box3: FakeVendor) -> None:
    """The tokens the vendor reported, on the client's own AI quota — never an estimate."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _publish(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT count(*) FROM usage_events "
                    "WHERE meta->>'feature' = :f AND meta->>'model' = :m"
                ),
                {"f": ASSIST_FEATURE_SUPERMEMORY_INGEST, "m": _MODEL},
            )
        ).scalar_one()
    assert rows >= 1


async def test_an_ingest_with_no_usage_block_records_nothing_and_says_so(
    monkeypatch: pytest.MonkeyPatch, attested_price: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """**WHETHER THE VENDOR REPORTS USAGE AT ALL IS UNKNOWN** — nobody here has read a
    response. A `0` would be a ledger row asserting the document was embedded for free and
    an estimate from the text's length would be a number we invented reaching
    `unit_cost_paid`, so the answer is an ERROR and no row."""
    silent = FakeVendor(usage=False)
    _configure(monkeypatch, silent)
    tenant_id, agent_id = await _tenant_with_published_agent()

    with caplog.at_level(logging.ERROR):
        await _publish(tenant_id, agent_id)

    assert silent.ingests, "the document was not written at all"
    assert any(record.message == "supermemory_ingest_unmetered" for record in caplog.records)
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM usage_events WHERE meta->>'feature' = :f"),
                {"f": ASSIST_FEATURE_SUPERMEMORY_INGEST},
            )
        ).scalar_one()
    assert rows == 0, "an unmeterable purchase was recorded with an invented quantity"


# --- hard rule 6 -----------------------------------------------------------------------


async def test_nothing_on_this_path_logs_a_client_word(
    box3: FakeVendor, caplog: pytest.LogCaptureFixture
) -> None:
    """The text goes to the vendor; it does not go to our logs. Ids and counts only.

    Checked over the WHOLE publish path rather than over one call site, because the leak
    this guards against is a well-meaning `extra={"content": ...}` added to any of the three
    modules the publish now touches.
    """
    tenant_id, agent_id = await _tenant_with_published_agent()
    with caplog.at_level(logging.DEBUG):
        source_id = await _publish(tenant_id, agent_id)
        async with tenant_session(tenant_id) as session:
            await kb_service.withdraw_source(session, tenant_id=tenant_id, source_id=source_id)

    rendered = "\n".join(
        f"{record.getMessage()} {sorted(record.__dict__.items(), key=str)}"
        for record in caplog.records
    )
    assert "500 rupees" not in rendered
    assert "Sunday is closed" not in rendered
