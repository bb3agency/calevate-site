"""The Supermemory seam: selection, tenancy, degradation, metering, and what is logged.

**THERE IS NO NETWORK IN THIS FILE AND THERE MUST NOT BE.** Supermemory is not installed
and `supermemory.ai` is egress-blocked from this container (`docs/PIPECAT-MIGRATION.md`
§8.5), so the vendor is faked at the ONE seam that touches a socket —
`supermemory.SupermemoryTransport` — and everything above it runs for real. That is the
same split `tests/retrieval_pgvector_test.py` takes at `chat.embed`, and it is the split
that matters here for a second reason: the whole adapter is written against a contract
nobody has read, so what is worth testing is precisely the behaviour on responses we
GUESSED wrong, which a fake transport can produce and a real one cannot be asked for.

WHAT EACH GROUP BELOW IS DEFENDING:

* **Selection** — a store is chosen by config, never by an edit, and naming one you have
  not configured must not take the dashboard down.
* **Tenancy** — §8.4 leaves the wall on our side, so the scope has to be unforgettable at
  a call site AND re-checked on the way back.
* **Degradation** — §8.5: box 3 being down degrades dashboard search and nothing else.
* **Money** — hard rule 7: no attested price, no provider; and a search whose cost cannot
  be recorded says so rather than recording a zero.
* **Logs** — hard rule 6: ids, counts and outcomes. Never the question, never a passage.
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
from apps.api.db.session import tenant_session
from apps.api.retrieval import service as retrieval_service
from apps.api.retrieval import supermemory as supermemory_module
from apps.api.retrieval.compiled_facts import CompiledFactsRetriever
from apps.api.retrieval.supermemory import (
    ASSIST_FEATURE_SUPERMEMORY_SEARCH,
    SupermemoryClient,
    SupermemoryRetriever,
    search_is_billable,
)
from apps.api.retrieval.supermemory_wire import (
    ASSUMED_CONTRACT,
    UNLABELLED_SOURCE,
    SupermemoryWireMismatchError,
    TenantScope,
    parse_search,
    search_payload,
)
from calevate_shared.retrieval import RetrievalProvider, RetrievalRequest
from sqlalchemy import text
from tests.kb_workflow_test import _tenant_with_published_agent

#: What an operator would name in `Settings.supermemory_embedding_model`. A stand-in, and
#: deliberately not a real vendor identifier: which model a box 3 install actually embeds
#: with is UNVERIFIED here (§8.3 — the documented env vars are reported ignored by upstream
#: issue #1336), and hard-coding one into a test would be the repetition hard rule 11 calls
#: laundering. What is under test is the price GATE, which does not care about the name.
_MODEL = "fixture-embedding-model"


@pytest.fixture
def attested_price() -> Any:
    """An operator attestation for `_MODEL`, installed and then removed.

    THE ONLY THING THAT MAKES THIS PROVIDER SELECTABLE. No embedding price has been read
    from a vendor page in this container, so `llm_price_is_billable` is False for every
    embedding model in the tree until somebody enters their own invoice figure — which
    makes this fixture the documentation of what an operator has to do before box 3 is ever
    queried, as well as the setup for the tests below.
    """
    attestation = LlmPriceAttestation(
        model=_MODEL,
        input_usd_per_mtok=Decimal("0.02"),
        # Equal to the input and it never multiplies anything: an embedding response has no
        # output tokens, so every `ai_assist_ktok_out` row this path writes is qty 0.
        output_usd_per_mtok=Decimal("0.02"),
        read_on=date(2026, 9, 14),
        attested_by="test",
        source="fixture",
    )
    install_llm_price_attestations(lambda: {_MODEL: attestation})
    yield attestation
    install_llm_price_attestations(None)


class FakeTransport:
    """Box 3, without a socket. Records what was sent; answers what it was told to.

    `raises` wins over `body`, so one class covers both "the vendor answered oddly" and
    "the vendor did not answer", which are the two halves of §8.5's degradation promise.
    """

    def __init__(self, body: dict[str, Any] | None = None, *, raises: Exception | None = None):
        self.body = body if body is not None else {"results": []}
        self.raises = raises
        self.sent: list[tuple[str, dict[str, Any]]] = []

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.sent.append((path, payload))
        if self.raises is not None:
            raise self.raises
        return self.body


class RecordingFallback:
    """The Postgres retriever's stand-in: it answers, and it remembers that it had to."""

    name = "fallback-store"
    capabilities = CompiledFactsRetriever.capabilities

    def __init__(self) -> None:
        self.retrieved: list[RetrievalRequest] = []
        self.epochs = 0

    async def retrieve(self, request: RetrievalRequest) -> Any:
        from calevate_shared.retrieval import RetrievalResult

        self.retrieved.append(request)
        return RetrievalResult(requested_tier=request.tier, served_tier="t0", provider=self.name)

    async def knowledge_epoch(self, request: RetrievalRequest) -> str:
        self.epochs += 1
        return "fallback-epoch"


def _record(tenant_id: uuid.UUID, *, text_value: str, **extra: Any) -> dict[str, Any]:
    """One vendor result in the ASSUMED shape, tagged for `tenant_id`."""
    record: dict[str, Any] = {
        ASSUMED_CONTRACT.text_key: text_value,
        ASSUMED_CONTRACT.result_tags_key: [f"tenant:{tenant_id}"],
        ASSUMED_CONTRACT.score_key: 0.9,
    }
    record.update(extra)
    return record


def _retriever(
    transport: FakeTransport, *, fallback: RetrievalProvider, session: Any = None
) -> SupermemoryRetriever:
    return SupermemoryRetriever(session, client=SupermemoryClient(transport), fallback=fallback)


# --- selection by config, never by an edit ------------------------------------------


async def test_the_provider_is_chosen_by_config_and_box_three_becomes_the_t3_member(
    monkeypatch: pytest.MonkeyPatch, attested_price: Any
) -> None:
    """`retrieval_provider = supermemory` swaps ONE member of the composite.

    The composite's own name is what a caller sees, so the assertion that matters is the
    member: T0 still answers out of the compiled block (which is what the agent speaks
    from) and the cold lookup is box 3.
    """
    tenant_id, _ = await _tenant_with_published_agent()
    settings = retrieval_service.get_settings()
    monkeypatch.setattr(settings, "retrieval_provider", "supermemory")
    monkeypatch.setattr(settings, "supermemory_base_url", "http://127.0.0.1:8765")
    monkeypatch.setattr(settings, "supermemory_api_key", "fixture-key")
    monkeypatch.setattr(settings, "supermemory_embedding_model", _MODEL)

    async with tenant_session(tenant_id) as session:
        provider = retrieval_service.get_retriever(session)
        assert provider.name == "knowledge"
        assert isinstance(provider._t3, SupermemoryRetriever)
        assert isinstance(provider._t0, CompiledFactsRetriever)


async def test_naming_the_store_without_configuring_it_serves_postgres_instead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A half-configured box 3 must not take knowledge search down.

    Four preconditions and the missing one is named in the log (`supermemory_t3`), which is
    BACKEND-PATTERNS §2's tolerant boot applied to a store: a deployment missing one input
    runs everything else. Asserted through `get_retriever` rather than through the factory,
    because the property a client depends on is that ASKING A QUESTION still works.
    """
    tenant_id, _ = await _tenant_with_published_agent()
    settings = retrieval_service.get_settings()
    monkeypatch.setattr(settings, "retrieval_provider", "supermemory")
    monkeypatch.setattr(settings, "supermemory_base_url", "http://127.0.0.1:8765")
    # No credential, and no attested price either.
    monkeypatch.setattr(settings, "supermemory_api_key", None)
    monkeypatch.setattr(retrieval_service, "embedding_leg", lambda: None)

    async with tenant_session(tenant_id) as session:
        assert retrieval_service.get_retriever(session).name == "compiled-facts"


async def test_the_default_provider_is_unchanged_by_adding_this_one() -> None:
    """Adding a provider must leave the current one working AND selected (§6 step 14/15).

    `kb_chunks` and the pgvector path retire in step 15, not here, so the shipped default
    is still the compiled block and nothing in this change moves it.
    """
    tenant_id, _ = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        assert retrieval_service.get_settings().retrieval_provider == "compiled-facts"
        assert retrieval_service.get_retriever(session).name == "compiled-facts"


# --- tenancy: ours to enforce, so it has to be unforgettable --------------------------


def test_no_wire_method_can_be_called_without_a_tenant_scope() -> None:
    """**THE STRUCTURAL PROOF.** A query for tenant A cannot be CONSTRUCTED without A.

    §8.4: the local build is single-tenant with one API key, so nothing on the server side
    stops an unscoped query — which makes "we always remember to pass the tenant" the whole
    control, and a control that rests on remembering is not one. Every public coroutine on
    the client therefore takes a `TenantScope` as its first positional parameter, and this
    reads the SIGNATURES rather than trusting today's call sites: a method added later
    without one fails here instead of shipping.
    """
    methods = [
        (name, member)
        for name, member in inspect.getmembers(SupermemoryClient, inspect.isfunction)
        if not name.startswith("_")
    ]
    assert methods, "the guard is vacuous if the client has no public methods"
    for name, member in methods:
        first = list(inspect.signature(member).parameters.values())[1]
        assert first.name == "scope", f"{name} does not take a tenant scope first"
        assert first.annotation == "TenantScope", f"{name}'s scope is not a TenantScope"
        assert first.default is inspect.Parameter.empty, f"{name}'s scope is defaultable"


def test_a_search_body_cannot_be_built_without_the_tenant_tag() -> None:
    """The filter we send. `TenantScope` is the only way to address the store, and the
    payload builder re-asserts the tag rather than trusting itself."""
    tenant_id, agent_id = uuid.uuid4(), uuid.uuid4()
    scope = TenantScope.for_request(
        RetrievalRequest(tenant_id=tenant_id, agent_id=agent_id, question="opening hours")
    )
    payload = search_payload(scope, question="opening hours", k=3)
    assert payload[ASSUMED_CONTRACT.container_tags_key] == [
        f"tenant:{tenant_id}",
        f"agent:{agent_id}",
    ]
    # The scope is a required positional of a type only the request can mint: there is no
    # string a call site could pass instead, and no default to fall through to.
    with pytest.raises(TypeError):
        search_payload(question="opening hours", k=3)  # type: ignore[call-arg]


def test_records_that_come_back_for_another_tenant_are_dropped() -> None:
    """**THE CHECK THAT MATTERS**: whether the server HONOURED the filter.

    A tag the server ignores, a contract key guessed wrong, or an index rebuilt without
    tags all produce a 200 full of a neighbour's rows — and against a single-tenant build
    that is not hypothetical, it is the default behaviour if our one assumed field name is
    wrong. Mine's tenant and the other tenant's rows come back together; only ours survives.
    """
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    scope = TenantScope.for_request(RetrievalRequest(tenant_id=mine, question="hours"))
    body = {
        ASSUMED_CONTRACT.results_key: [
            _record(mine, text_value="We open at 9am on weekdays."),
            _record(theirs, text_value="A dosa is 60 rupees."),
            {ASSUMED_CONTRACT.text_key: "no tags at all"},
        ]
    }
    passages, rejected = parse_search(body, scope=scope)
    assert [p.text for p in passages] == ["We open at 9am on weekdays."]
    assert rejected == 2


def test_the_adapter_declares_that_the_namespace_is_not_the_vendors_wall() -> None:
    """§8.4, as code rather than as prose.

    `per_tenant_namespace` False is the port's way of saying "tenancy is enforced only by
    our filter", and `tiered._union` ANDs that field — so a composite carrying this adapter
    reports False too rather than inheriting pgvector's FORCEd-RLS guarantee. `deletion_proof`
    is False for §8.4 reason 2: there is a second copy now and we cannot check their delete.
    """
    from apps.api.retrieval.tiered import KnowledgeRetriever

    assert SupermemoryRetriever.capabilities.per_tenant_namespace is False
    assert SupermemoryRetriever.capabilities.deletion_proof is False
    composite = KnowledgeRetriever(
        None, t3=_retriever(FakeTransport(), fallback=RecordingFallback())
    )
    assert composite.capabilities.per_tenant_namespace is False


async def test_the_query_that_goes_out_carries_the_asking_tenants_tag() -> None:
    """End to end through the adapter: what reached the wire was scoped to the asker."""
    tenant_id = uuid.uuid4()
    transport = FakeTransport({ASSUMED_CONTRACT.results_key: []})
    await _retriever(transport, fallback=RecordingFallback()).retrieve(
        RetrievalRequest(tenant_id=tenant_id, question="do you deliver", tier="t3")
    )
    ((path, payload),) = transport.sent
    assert path == ASSUMED_CONTRACT.search_path
    assert payload[ASSUMED_CONTRACT.container_tags_key] == [f"tenant:{tenant_id}"]


# --- degradation: box 3 is down, the dashboard still answers ---------------------------


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("box 3 is not listening"),
        httpx.ReadTimeout("box 3 is slow"),
        TimeoutError(),
    ],
    ids=["unreachable", "timeout", "cancelled"],
)
async def test_an_unreachable_box_three_falls_back_to_postgres(failure: Exception) -> None:
    """§8.5: "if it is down, calls do not notice and uploads do not notice — only dashboard
    search degrades to the Postgres fallback". The result NAMES the fallback, because the
    one observability field that says where an answer came from must not lie."""
    fallback = RecordingFallback()
    result = await _retriever(FakeTransport(raises=failure), fallback=fallback).retrieve(
        RetrievalRequest(tenant_id=uuid.uuid4(), question="do you deliver", tier="t3")
    )
    assert len(fallback.retrieved) == 1
    assert result.provider == "fallback-store"


async def test_a_response_shape_we_guessed_wrong_also_falls_back() -> None:
    """THE ONE THIS SEAM EXISTS FOR. Every wire fact here is ASSUMED, so the realistic
    failure is not an outage — it is a 200 in a shape `ASSUMED_CONTRACT` does not describe,
    and a client must not see a stack trace because we guessed a key name."""
    fallback = RecordingFallback()
    transport = FakeTransport({"data": [{"content": "We open at 9am."}]})
    result = await _retriever(transport, fallback=fallback).retrieve(
        RetrievalRequest(tenant_id=uuid.uuid4(), question="what time do you open", tier="t3")
    )
    assert len(fallback.retrieved) == 1
    assert result.provider == "fallback-store"


def test_the_parser_names_the_keys_it_actually_saw() -> None:
    """The correction has to be actionable: an operator holding this message can edit
    `ASSUMED_CONTRACT` without reading the parser. Keys only — never values (hard rule 6)."""
    scope = TenantScope.for_request(RetrievalRequest(tenant_id=uuid.uuid4(), question="q"))
    with pytest.raises(SupermemoryWireMismatchError) as caught:
        parse_search({"data": [], "total": 0}, scope=scope)
    assert "'data'" in str(caught.value) and "'total'" in str(caught.value)


async def test_the_epoch_comes_from_our_own_ledger_and_not_from_the_vendor() -> None:
    """The invalidation stamp must keep working while box 3 does not, and must cost no
    vendor round trip on a path that runs before the cache on every question (§8.4: the
    ledger stays ours precisely because it is the authority on what a tenant published)."""
    fallback = RecordingFallback()
    transport = FakeTransport(raises=httpx.ConnectError("down"))
    epoch = await _retriever(transport, fallback=fallback).knowledge_epoch(
        RetrievalRequest(tenant_id=uuid.uuid4(), question="hours")
    )
    assert epoch == "fallback-epoch"
    assert fallback.epochs == 1
    assert transport.sent == [], "the epoch must not touch the vendor"


# --- hard rule 7: the money --------------------------------------------------------


def test_an_unattested_price_makes_the_store_unselectable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pre-flight, one step earlier than the other embedding surfaces take it.

    A search embeds the question on our vendor account (§8.3 forbids a local encoder on
    box 2), so an unpriced leg is not a degraded search — it is a store we must not query
    at all, and `get_retriever` is where a store stops being queried. No figure is invented
    here: the only route to True is an operator's own invoice.
    """
    settings = retrieval_service.get_settings()
    monkeypatch.setattr(settings, "supermemory_embedding_model", _MODEL)
    assert search_is_billable() is False
    monkeypatch.setattr(settings, "supermemory_embedding_model", None)
    assert search_is_billable() is False


async def test_a_search_is_metered_against_the_tenant_with_a_real_unit_cost(
    attested_price: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hard rule 7: what the search cost reaches `usage_events` under its own feature name.

    Its own name rather than `kb_search_embedding` on `retrieval/embedding`'s argument: the
    same question over the same corpus costs a different amount through a different store,
    and comparing the two is the entire point of putting a store behind a switch.
    """
    tenant_id, _ = await _tenant_with_published_agent()
    settings = retrieval_service.get_settings()
    monkeypatch.setattr(settings, "supermemory_embedding_model", _MODEL)
    body = {
        ASSUMED_CONTRACT.results_key: [_record(tenant_id, text_value="We open at 9am.")],
        ASSUMED_CONTRACT.usage_key: {ASSUMED_CONTRACT.usage_tokens_key: 7},
    }
    async with tenant_session(tenant_id) as session:
        result = await _retriever(
            FakeTransport(body), fallback=RecordingFallback(), session=session
        ).retrieve(
            RetrievalRequest(tenant_id=tenant_id, question="what time do you open", tier="t3")
        )
        rows = (
            await session.execute(
                text(
                    "SELECT unit_type, qty, unit_cost_paid FROM usage_events "
                    f"WHERE meta->>'feature' = '{ASSIST_FEATURE_SUPERMEMORY_SEARCH}' "
                    "ORDER BY unit_type"
                )
            )
        ).all()
    assert result.provider == "supermemory"
    assert [(str(r[0]), Decimal(str(r[1]))) for r in rows] == [
        ("ai_assist_ktok_in", Decimal("0.007")),
        ("ai_assist_ktok_out", Decimal("0")),
    ]
    assert Decimal(str(rows[0][2])) > 0, "a metered row with no unit cost is an unmetered one"


async def test_a_response_with_no_usage_block_records_nothing_and_says_so(
    attested_price: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """**WHETHER THE VENDOR REPORTS USAGE AT ALL IS UNKNOWN**, so this is the path that will
    run if the assumption is wrong. The two rejected alternatives are both worse: a `0` is a
    row asserting the search was free, and a length-based estimate is an invented number
    reaching `unit_cost_paid`. ERROR, because unmetered spend is not a state to leave
    running — the answer is to correct the contract or set the provider back."""
    tenant_id, _ = await _tenant_with_published_agent()
    settings = retrieval_service.get_settings()
    monkeypatch.setattr(settings, "supermemory_embedding_model", _MODEL)
    body = {ASSUMED_CONTRACT.results_key: [_record(tenant_id, text_value="We open at 9am.")]}
    async with tenant_session(tenant_id) as session:
        with caplog.at_level(logging.ERROR, logger=supermemory_module.log.name):
            await _retriever(
                FakeTransport(body), fallback=RecordingFallback(), session=session
            ).retrieve(RetrievalRequest(tenant_id=tenant_id, question="hours", tier="t3"))
        rows = (
            await session.execute(
                text(
                    "SELECT count(*) FROM usage_events WHERE meta->>'feature' = "
                    f"'{ASSIST_FEATURE_SUPERMEMORY_SEARCH}'"
                )
            )
        ).scalar_one()
    assert rows == 0
    assert "supermemory_search_unmetered" in caplog.text


# --- hard rule 6: what reaches a log line ------------------------------------------


async def test_no_question_passage_or_credential_ever_reaches_a_log_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ids, counts and outcomes. The question is a person's own prose and a passage is a
    client's business knowledge; neither belongs in a log, on any of the three paths that
    log here — out-of-scope records, a degrade, and an unmetered search.
    """
    tenant_id, other = uuid.uuid4(), uuid.uuid4()
    question = "canyoudelivertokukatpallybeforesix"
    secret = "thefeeissixhundredrupeesflat"
    body = {
        ASSUMED_CONTRACT.results_key: [
            _record(tenant_id, text_value=secret),
            _record(other, text_value="a neighbour's own words"),
        ]
    }
    with caplog.at_level(logging.DEBUG):
        await _retriever(FakeTransport(body), fallback=RecordingFallback()).retrieve(
            RetrievalRequest(tenant_id=tenant_id, question=question, tier="t3")
        )
        await _retriever(
            FakeTransport(raises=httpx.ConnectError("connecting to http://box3:8765 failed")),
            fallback=RecordingFallback(),
        ).retrieve(RetrievalRequest(tenant_id=tenant_id, question=question, tier="t3"))
    # THE HAYSTACK IS THE RECORD'S EXTRAS, NOT `caplog.text`. Every log message in this tree
    # is a static token (`core/logging.py` pins that), so the rendered message could never
    # carry a question — the extras are where a careless field would put one, and
    # `caplog.text` does not contain them. Asserting against the message alone would be a
    # guard that passes whatever the code does.
    emitted = " ".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    assert "supermemory_records_out_of_scope" in emitted
    assert "supermemory_degraded_to_postgres" in emitted
    assert question not in emitted
    assert secret not in emitted
    # The transport's own error text quotes the host it was dialling; only the TYPE is ours
    # to log, because an HTTP error body quotes the request and the request is the question.
    assert "box3:8765" not in emitted
    assert "ConnectError" in emitted


# --- provenance: a citation a client can check -------------------------------------


def test_our_own_ingest_metadata_becomes_the_provenance_a_client_reads() -> None:
    """The label is the SOURCE's own name — what the client called the thing they uploaded
    — which is what makes a citation checkable by them. It travels in metadata WE would
    write at ingest (§6 step 15), so this pins the shape that side owes."""
    tenant_id, agent_id, source_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    scope = TenantScope.for_request(RetrievalRequest(tenant_id=tenant_id, question="hours"))
    body = {
        ASSUMED_CONTRACT.results_key: [
            _record(
                tenant_id,
                text_value="We open at 9am on weekdays.",
                **{
                    ASSUMED_CONTRACT.metadata_key: {
                        ASSUMED_CONTRACT.metadata_source_label: "Opening hours",
                        ASSUMED_CONTRACT.metadata_source_id: str(source_id),
                        ASSUMED_CONTRACT.metadata_agent_id: str(agent_id),
                        ASSUMED_CONTRACT.metadata_document_version: 3,
                    }
                },
            )
        ]
    }
    (passage,), rejected = parse_search(body, scope=scope)
    assert rejected == 0
    assert passage.provenance.label == "Opening hours"
    assert passage.provenance.source_id == source_id
    assert passage.provenance.agent_id == agent_id
    assert passage.provenance.document_version == 3
    assert passage.provenance.tier == "t3"


def test_a_record_with_no_metadata_of_ours_is_still_returned() -> None:
    """The rejected alternative was dropping it. Nothing writes our metadata yet (ingest is
    step 15), and punishing a metadata gap by telling a client we have nothing on file when
    we do is the wrong direction to fail in — the port already admits a `source_id` of
    None for the compiled block, for the same reason."""
    tenant_id = uuid.uuid4()
    scope = TenantScope.for_request(RetrievalRequest(tenant_id=tenant_id, question="hours"))
    body = {ASSUMED_CONTRACT.results_key: [_record(tenant_id, text_value="We open at 9am.")]}
    (passage,), rejected = parse_search(body, scope=scope)
    assert rejected == 0
    assert passage.provenance.label == UNLABELLED_SOURCE
    assert passage.provenance.source_id is None
