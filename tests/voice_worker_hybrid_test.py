"""The hybrid arm: when the dense pass runs, when it must not, and what it does when it fails.

**NO NETWORK ANYWHERE IN THIS FILE.** `voice_worker.knowledge.QueryEmbedder` is a Protocol
for exactly this reason, and every embedder here is a handful of lines that returns a vector
from a dict. The production one (`voice_worker.embedding.GeminiQueryEmbedder`) is exercised
separately against an `httpx.MockTransport`, so the wire shape and the ranking are proved
apart — a test that needed both to be right at once would fail for two reasons and diagnose
neither.

**THE FIXTURE VECTORS ARE FIVE-DIMENSIONAL AND HAND-WRITTEN, WHICH IS DELIBERATE.** The real
encoder returns 3,072 floats whose geometry nobody in this repository can predict; a test
built on one would be asserting Google's behaviour rather than ours. Five orthogonal
unit vectors make every cosine in these tests something a reader can compute in their head,
so when an assertion fails it names OUR defect. Whether a real Telugu question lands near a
real English passage is a RECALL question and it was answered by measurement, not by a test
(`scripts/gemini_embedding_harness.py`, founder-run 14 Sep 2026: 0.9583 on Telugu script
against this index's 0.083).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from calevate_shared.knowledge_pack import (
    PACK_FORMAT_VERSION,
    SUPPORTED_PACK_FORMAT_VERSIONS,
    KnowledgePack,
    PackEntry,
    decode_vector,
    encode_vector,
    pack_object_key,
)
from loguru import logger
from voice_worker.embedding import EMBEDDING_DIMS, EMBEDDING_MODEL, GeminiQueryEmbedder
from voice_worker.knowledge import (
    DENSE_MIN_COSINE,
    DenseIndex,
    PackCache,
    QueryVector,
    SessionKnowledge,
    load_session_knowledge,
)
from voice_worker.pipeline import knowledge_tool_payload

TENANT = UUID("0199c0de-0000-7000-8000-0000000000aa")
AGENT = UUID("0199c0de-0000-7000-8000-0000000000ab")

HOURS_DOC = UUID("0199c0de-0002-7000-8000-000000000001")
DELIVERY_DOC = UUID("0199c0de-0002-7000-8000-000000000002")
CONSULT_FEE_DOC = UUID("0199c0de-0002-7000-8000-000000000003")
REPAIR_FEE_DOC = UUID("0199c0de-0002-7000-8000-000000000004")

#: The fake encoder's model name and width. They are the pack's declaration AND the
#: embedder's, and `DenseIndex.usable_with` compares the two — so a test that wants a
#: mismatch changes one of them and nothing else.
FAKE_MODEL = "fake-embedder-v1"
FAKE_DIMS = 5

#: Four orthogonal directions, one per document, in a FIVE-dimensional space. The fifth
#: dimension is not spare and is not decoration: in a 4-space spanned by four axes every unit
#: vector has a component of at least 0.5 on one of them, so "points nowhere near anything in
#: this corpus" would be unrepresentable and the floor could not be tested at all.
_AXES: dict[str, tuple[float, ...]] = {
    "hours": (1.0, 0.0, 0.0, 0.0, 0.0),
    "delivery": (0.0, 1.0, 0.0, 0.0, 0.0),
    "consult_fee": (0.0, 0.0, 1.0, 0.0, 0.0),
    "repair_fee": (0.0, 0.0, 0.0, 1.0, 0.0),
}

#: The fifth axis: cosine 0.0 to every passage in the corpus. A question about something this
#: business simply does not do.
_NOWHERE: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0, 1.0)

#: A direction 45° between the two fee axes: cosine 0.707 to both, which is above
#: `DENSE_MIN_COSINE` and inside `AMBIGUITY_MARGIN` of itself. That is the shape of a caller
#: who named a CATEGORY rather than a thing, and it is what the dense `ambiguous` test uses.
_BETWEEN_FEES: tuple[float, ...] = (0.0, 0.0, 1 / math.sqrt(2), 1 / math.sqrt(2), 0.0)


def _entry(document_id: UUID, text: str, axis: str | None) -> PackEntry:
    return PackEntry(
        chunk_id=UUID(int=abs(hash((document_id, text))) % (1 << 120)),
        document_id=document_id,
        document_version=1,
        text=text,
        gloss=None,
        vector_f32_b64=None if axis is None else encode_vector(_AXES[axis]),
    )


def shop_entries(*, vectors: bool = True) -> tuple[PackEntry, ...]:
    """One hardware shop's published knowledge. English text so the LEXICAL arm is live and
    the tests can assert that it, and not the dense one, answered."""

    def axis(name: str) -> str | None:
        return name if vectors else None

    return (
        _entry(HOURS_DOC, "The shop is open from 9 am to 8 pm every day.", axis("hours")),
        _entry(
            DELIVERY_DOC,
            "Free delivery is available within Kukatpally for orders above two thousand rupees.",
            axis("delivery"),
        ),
        _entry(CONSULT_FEE_DOC, "Consultation charge is five hundred rupees.", axis("consult_fee")),
        _entry(REPAIR_FEE_DOC, "Repair charge is five hundred rupees.", axis("repair_fee")),
    )


def build_pack(
    entries: tuple[PackEntry, ...],
    *,
    model: str | None = FAKE_MODEL,
    dimensions: int | None = FAKE_DIMS,
    format_version: int = PACK_FORMAT_VERSION,
) -> KnowledgePack:
    return KnowledgePack(
        format_version=format_version,
        tenant_id=TENANT,
        agent_id=AGENT,
        content_sha256=KnowledgePack.digest(
            TENANT,
            AGENT,
            entries,
            embedding_model=model,
            embedding_dimensions=dimensions,
        ),
        built_at=datetime(2026, 9, 14, 6, 0, tzinfo=UTC),
        embedding_model=model,
        embedding_dimensions=dimensions,
        entries=entries,
    )


class DictFetcher:
    def __init__(self, pack: KnowledgePack) -> None:
        self.objects = {
            pack_object_key(pack.tenant_id, pack.agent_id, pack.content_sha256): (
                pack.model_dump_json().encode()
            )
        }

    async def fetch(self, object_key: str) -> bytes | None:
        return self.objects.get(object_key)


class FakeEmbedder:
    """A `QueryEmbedder` that looks its answer up. Records every question it was asked, which
    is how the "did the arm fire?" assertions are made without reading a log."""

    def __init__(
        self,
        answers: dict[str, tuple[float, ...]] | None = None,
        *,
        model: str = FAKE_MODEL,
        dimensions: int = FAKE_DIMS,
        tokens: int | None = 7,
    ) -> None:
        self._answers = answers or {}
        self._model = model
        self._dimensions = dimensions
        self._tokens = tokens
        self.asked: list[str] = []

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, question: str) -> QueryVector | None:
        self.asked.append(question)
        values = self._answers.get(question)
        return None if values is None else QueryVector(values=values, tokens=self._tokens)


class DeadEmbedder:
    """Every way a hosted encoder can fail, collapsed into the one answer the contract
    allows: `None`, never an exception."""

    def __init__(self, *, model: str = FAKE_MODEL, dimensions: int = FAKE_DIMS) -> None:
        self._model = model
        self._dimensions = dimensions
        self.asked: list[str] = []

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, question: str) -> QueryVector | None:
        self.asked.append(question)
        return None


async def load_shop(
    pack: KnowledgePack | None = None, cache: PackCache | None = None
) -> SessionKnowledge:
    pack = pack or build_pack(shop_entries())
    return await load_session_knowledge(
        tenant_id=TENANT,
        agent_id=AGENT,
        content_sha256=pack.content_sha256,
        fetcher=DictFetcher(pack),
        cache=cache or PackCache(),
    )


# ---------------------------------------------------------------------------------------
# The encoding, and what the digest does and does not cover.
# ---------------------------------------------------------------------------------------


def test_a_vector_survives_the_round_trip_and_a_wrong_width_is_refused() -> None:
    values = (0.5, -0.25, 1.0, 0.0)
    encoded = encode_vector(values)
    assert decode_vector(encoded, dimensions=4) == values
    # The width is a CHECK, not a parse: the same bytes read at another width are refused
    # rather than reinterpreted, because any four bytes are a valid float and a silent
    # reinterpretation would rank confidently and wrongly.
    assert decode_vector(encoded, dimensions=3) is None
    assert decode_vector(encoded, dimensions=8) is None
    assert decode_vector("not base64 at all !!", dimensions=4) is None


def test_the_digest_ignores_the_floats_and_notices_the_encoder() -> None:
    """A rebuild whose vectors moved keeps its id; a rebuild under another encoder does not.

    The first half is what stops a possibly-nondeterministic vendor from invalidating every
    warm container on a republish that changed no knowledge (the same defect `built_at` is
    excluded for). The second is what stops a container holding the old build from serving it
    for the new digest and comparing two models' vectors.
    """
    entries = shop_entries()
    jittered = tuple(
        entry.model_copy(update={"vector_f32_b64": encode_vector((0.9, 0.1, 0.0, 0.0))})
        for entry in entries
    )
    same = KnowledgePack.digest(
        TENANT, AGENT, entries, embedding_model=FAKE_MODEL, embedding_dimensions=FAKE_DIMS
    )
    assert (
        KnowledgePack.digest(
            TENANT, AGENT, jittered, embedding_model=FAKE_MODEL, embedding_dimensions=FAKE_DIMS
        )
        == same
    )
    assert (
        KnowledgePack.digest(
            TENANT, AGENT, entries, embedding_model="other-encoder", embedding_dimensions=FAKE_DIMS
        )
        != same
    )
    assert (
        KnowledgePack.digest(
            TENANT, AGENT, entries, embedding_model=FAKE_MODEL, embedding_dimensions=8
        )
        != same
    )


def test_half_an_embedding_declaration_is_unrepresentable() -> None:
    entries = shop_entries(vectors=False)
    with pytest.raises(ValueError, match="one declaration"):
        build_pack(entries, model=FAKE_MODEL, dimensions=None)
    with pytest.raises(ValueError, match="one declaration"):
        build_pack(entries, model=None, dimensions=FAKE_DIMS)
    # And a corpus that LOOKS embedded but declares no encoder is refused outright, because
    # every reader would silently ignore it.
    with pytest.raises(ValueError, match="no reader could tell"):
        build_pack(shop_entries(), model=None, dimensions=None)


# ---------------------------------------------------------------------------------------
# THE TRIGGER. This is the part of the design that decides what a turn costs.
# ---------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_dense_arm_does_not_fire_when_the_lexical_arm_found_it() -> None:
    """The fast path is the product: a `found` must not buy a network round trip.

    Asserted on the embedder's own record rather than on a log line, so it is a statement
    about what was SPENT and not about what was printed.
    """
    session = await load_shop()
    embedder = FakeEmbedder({"delivery in Kukatpally?": _AXES["hours"]})

    answer = await session.answer("delivery in Kukatpally?", embedder=embedder)

    assert answer.outcome == "found"
    assert answer.arm == "lexical"
    assert answer.embedding_tokens is None
    assert embedder.asked == []
    # And the passage is the one the WORDS matched, not the one the (deliberately wrong)
    # vector pointed at — proof the dense arm did not merely fail to change the outcome.
    assert "delivery" in answer.passages[0].text.lower()


@pytest.mark.asyncio
async def test_the_dense_arm_fires_on_not_found_and_answers_from_the_vector() -> None:
    """The measured case, in miniature: a question sharing no informative word with the
    corpus is `not_found` lexically and is answered by the dense arm."""
    session = await load_shop()
    question = "షాప్ ఎన్ని గంటలకు తెరుస్తారు?"
    assert session.search(question).outcome == "not_found"

    embedder = FakeEmbedder({question: _AXES["hours"]})
    answer = await session.answer(question, embedder=embedder)

    assert answer.outcome == "found"
    assert answer.arm == "dense"
    assert answer.embedding_tokens == 7
    assert embedder.asked == [question]
    assert answer.passages[0].provenance.source_id == HOURS_DOC
    # Provenance still travels: a pack is frozen at publish, so a dense answer names the
    # revision it quoted exactly as a lexical one does.
    assert answer.passages[0].provenance.document_version == 1


@pytest.mark.asyncio
async def test_the_dense_arm_fires_on_ambiguous_and_can_stay_ambiguous() -> None:
    """`ambiguous` is a trigger, and the dense arm applies the SAME margin rule to its own
    ranking — a caller who named a category named a category however the passages ranked."""
    session = await load_shop()
    assert session.search("What is the charge?").outcome == "ambiguous"

    embedder = FakeEmbedder({"What is the charge?": _BETWEEN_FEES})
    answer = await session.answer("What is the charge?", embedder=embedder)

    assert embedder.asked == ["What is the charge?"]
    assert answer.outcome == "ambiguous"
    assert answer.arm == "dense"
    assert len(answer.passages) == 2
    assert {passage.provenance.source_id for passage in answer.passages} == {
        CONSULT_FEE_DOC,
        REPAIR_FEE_DOC,
    }


@pytest.mark.asyncio
async def test_a_dense_pass_below_the_floor_leaves_the_lexical_answer_standing() -> None:
    """The arm can only ADD. A question the corpus genuinely has nothing near stays
    `not_found` — the nearest vector is not evidence, for the same reason the top BM25 score
    is not."""
    session = await load_shop()
    question = "Do you run a helicopter charter service?"
    assert session.search(question).outcome == "not_found"

    embedder = FakeEmbedder({question: _NOWHERE})
    answer = await session.answer(question, embedder=embedder)

    assert session.dense is not None
    assert max(score for _position, score in session.dense.search(_NOWHERE)) < DENSE_MIN_COSINE
    assert embedder.asked == [question]  # it DID fire, and it DID decline
    assert answer.outcome == "not_found"
    assert answer.arm == "lexical"
    assert answer.passages == ()


# ---------------------------------------------------------------------------------------
# Failure: the one place this arm may make a turn worse, and it does so honestly.
# ---------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_dead_embedder_yields_temporarily_unavailable_and_never_raises() -> None:
    """Once we consult a second arm we have said the first is not authoritative. Passing
    `not_found` through would tell the caller the business publishes nothing about it, on
    the strength of our own outage."""
    session = await load_shop()
    question = "షాప్ ఎన్ని గంటలకు తెరుస్తారు?"
    embedder = DeadEmbedder()

    answer = await session.answer(question, embedder=embedder)

    assert embedder.asked == [question]
    assert answer.outcome == "temporarily_unavailable"
    assert answer.arm == "dense_failed"
    assert answer.passages == ()
    assert answer.embedding_tokens is None


@pytest.mark.asyncio
async def test_an_embedder_that_raises_is_a_defect_the_contract_does_not_absorb() -> None:
    """Stated as a test so the contract is not merely a docstring: `QueryEmbedder.embed` must
    not raise, and the production embedder is what guarantees it (every failure path in
    `GeminiQueryEmbedder.embed` returns `None`). A raising embedder is a BROKEN
    implementation of the Protocol, and this test pins that we did not paper over it with a
    try/except that would also swallow a defect in our own ranking."""

    class RaisingEmbedder:
        model = FAKE_MODEL
        dimensions = FAKE_DIMS

        async def embed(self, question: str) -> QueryVector | None:
            raise RuntimeError("a Protocol implementation that breaks its contract")

    session = await load_shop()
    with pytest.raises(RuntimeError):
        await session.answer("షాప్ ఎన్ని గంటలకు తెరుస్తారు?", embedder=RaisingEmbedder())


@pytest.mark.asyncio
async def test_an_encoder_the_pack_was_not_built_with_is_refused_before_it_is_paid_for() -> None:
    """Two models' vectors of the same width dot-product happily and mean nothing. The
    refusal is BEFORE `embed`, so it costs nothing as well as meaning nothing."""
    session = await load_shop()
    question = "షాప్ ఎన్ని గంటలకు తెరుస్తారు?"

    wrong_model = FakeEmbedder({question: _AXES["hours"]}, model="some-other-encoder")
    assert (await session.answer(question, embedder=wrong_model)).outcome == "not_found"
    assert wrong_model.asked == []

    wrong_width = FakeEmbedder({question: _AXES["hours"]}, dimensions=8)
    assert (await session.answer(question, embedder=wrong_width)).outcome == "not_found"
    assert wrong_width.asked == []


# ---------------------------------------------------------------------------------------
# Old packs. A format bump must not be an outage on every agent that has not republished.
# ---------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_version_one_pack_still_answers_lexically() -> None:
    assert 1 in SUPPORTED_PACK_FORMAT_VERSIONS
    v1 = build_pack(shop_entries(vectors=False), model=None, dimensions=None, format_version=1)
    session = await load_shop(pack=v1)

    assert session.unavailable_reason is None
    assert session.available
    assert session.dense is not None and len(session.dense) == 0

    answer = await session.answer("delivery in Kukatpally?", embedder=FakeEmbedder())
    assert answer.outcome == "found"
    assert answer.arm == "lexical"

    # And its misses stay misses rather than becoming outages: with no vectors to compare
    # against, the arm declines before any spend and the lexical word stands.
    embedder = FakeEmbedder({"helicopter charter?": _AXES["hours"]})
    miss = await session.answer("helicopter charter?", embedder=embedder)
    assert miss.outcome == "not_found"
    assert miss.arm == "lexical"
    assert embedder.asked == []


@pytest.mark.asyncio
async def test_a_version_two_pack_with_no_vectors_behaves_exactly_like_version_one() -> None:
    """The state of a deployment with no attested embedding price: a current pack, no
    declaration, no dense arm, and byte-for-byte today's answers."""
    plain = build_pack(shop_entries(vectors=False), model=None, dimensions=None)
    session = await load_shop(pack=plain)
    embedder = FakeEmbedder({"helicopter charter?": _AXES["hours"]})

    assert (await session.answer("helicopter charter?", embedder=embedder)).arm == "lexical"
    assert embedder.asked == []


# ---------------------------------------------------------------------------------------
# Hard rule 6, on the arm that sends the question over a network.
# ---------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_dense_path_logs_no_question_no_passage_and_no_similarity() -> None:
    session = await load_shop()
    question = "షాప్ ఎన్ని గంటలకు తెరుస్తారు?"
    captured: list[str] = []

    def sink(message: Any) -> None:
        captured.append(str(message) + repr(message.record["extra"]))

    handler = logger.add(sink, level="DEBUG")
    try:
        answer = await session.answer(question, embedder=FakeEmbedder({question: _AXES["hours"]}))
        failed = await session.answer(question, embedder=DeadEmbedder())
    finally:
        logger.remove(handler)

    assert answer.arm == "dense" and failed.arm == "dense_failed"
    blob = "\n".join(captured)
    assert blob
    for forbidden in (
        question,
        "The shop is open from 9 am to 8 pm every day.",
        "Kukatpally",
    ):
        assert forbidden not in blob
    # What an operator DOES get: the arm, the outcome and the quantity that was bought.
    assert "dense" in blob and "dense_failed" in blob
    assert "embedding_tokens" in blob


# ---------------------------------------------------------------------------------------
# The tool payload, which is what the model actually sees.
# ---------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_tool_payload_carries_the_dense_answer_and_its_guidance() -> None:
    session = await load_shop()
    question = "షాప్ ఎన్ని గంటలకు తెరుస్తారు?"

    payload = await knowledge_tool_payload(
        session,
        question,
        pack_configured=True,
        embedder=FakeEmbedder({question: _AXES["hours"]}),
    )
    assert payload["outcome"] == "found"
    assert payload["passages"][0]["source_id"] == str(HOURS_DOC)

    dead = await knowledge_tool_payload(
        session, question, pack_configured=True, embedder=DeadEmbedder()
    )
    assert dead["outcome"] == "temporarily_unavailable"
    assert dead["passages"] == []
    # The guidance the model reads must be the one that forbids claiming the business has no
    # answer — that distinction is the whole reason the word is not `not_found`.
    assert "did not look" in dead["guidance"]


@pytest.mark.asyncio
async def test_no_embedder_is_the_complete_off_state() -> None:
    session = await load_shop()
    question = "షాప్ ఎన్ని గంటలకు తెరుస్తారు?"
    payload = await knowledge_tool_payload(session, question, pack_configured=True)
    assert payload["outcome"] == "not_found"


# ---------------------------------------------------------------------------------------
# The production embedder, against a fake transport. Wire shape only — no socket.
# ---------------------------------------------------------------------------------------


def _gemini_embedder(handler: Any) -> GeminiQueryEmbedder:
    return GeminiQueryEmbedder(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        api_key="not-a-real-key",
        model="test-model",
        dimensions=4,
    )


@pytest.mark.asyncio
async def test_the_gemini_embedder_reads_the_openai_embeddings_shape() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "data": [{"index": 0, "embedding": [0.0, 1.0, 0.0, 0.0]}],
                "usage": {"prompt_tokens": 11},
            },
        )

    result = await _gemini_embedder(handler).embed("when do you open")

    assert result == QueryVector(values=(0.0, 1.0, 0.0, 0.0), tokens=11)
    # The route and the auth scheme, both VERIFIED-LIVE on 14 Sep 2026 against the real host.
    assert seen["url"].endswith("/v1beta/openai/embeddings")
    assert seen["auth"] == "Bearer not-a-real-key"
    assert '"dimensions": 4' in seen["body"] or '"dimensions":4' in seen["body"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "handler"),
    [
        ("timeout", lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("too slow"))),
        ("transport", lambda request: (_ for _ in ()).throw(httpx.ConnectError("no route"))),
        ("server_error", lambda request: httpx.Response(503, text="upstream unavailable")),
        ("unauthorized", lambda request: httpx.Response(401, json={"error": "bad key"})),
        ("not_json", lambda request: httpx.Response(200, text="<html>nope</html>")),
        ("no_data", lambda request: httpx.Response(200, json={"usage": {"prompt_tokens": 3}})),
        (
            "wrong_width",
            lambda request: httpx.Response(200, json={"data": [{"embedding": [1.0, 0.0]}]}),
        ),
    ],
)
async def test_every_embedder_failure_is_none_and_never_an_exception(
    name: str, handler: Any
) -> None:
    """The Protocol's one hard promise, proved over every shape of failure this leg has.

    `wrong_width` is here because it is the one that would NOT raise on its own: a provider
    that ignores `dimensions` returns a perfectly valid 200, and comparing that vector
    against 3,072-wide passage vectors is the confident-and-wrong failure with nothing in any
    log. Refusing it is what makes 'the field is accepted, the truncation is not proven' safe
    to ship.
    """
    assert await _gemini_embedder(handler).embed("when do you open") is None


def test_the_worker_and_the_publisher_agree_about_the_encoder() -> None:
    """The two constants are restated rather than imported across the monolith boundary
    (`voice_worker` must not import `apps.api`), so this is what stops them drifting — a
    mismatch would silently disable the dense arm on every pack in production and the only
    symptom would be recall going back to 0.083."""
    from apps.api.kb.pack_vectors import EMBEDDING_DIMS as PUBLISH_DIMS
    from apps.api.kb.pack_vectors import EMBEDDING_MODEL as PUBLISH_MODEL

    assert EMBEDDING_MODEL == PUBLISH_MODEL
    assert EMBEDDING_DIMS == PUBLISH_DIMS


def test_the_publish_leg_refuses_to_buy_a_price_this_repository_cannot_attest() -> None:
    """Hard rule 7's pre-flight, asserted rather than trusted.

    ⚠ It also records a fact about the deployment this runs in: the Gemini embedding price is
    UNVERIFIED here (`ai.google.dev` is egress-blocked) and no operator attestation exists in
    a test process, so the pack builder is a no-op and the dense arm is OFF. If this ever
    starts returning True in CI, somebody has put an unverified figure into the catalogue and
    the money path opened without the argument being had.
    """
    from apps.api.kb.pack_vectors import pack_embedding_is_billable

    assert pack_embedding_is_billable() is False


@pytest.mark.asyncio
async def test_the_pack_builder_makes_a_plain_pack_when_it_may_not_buy_vectors() -> None:
    """`embed_entries` returns its input unchanged and declares no encoder — so the pack is
    byte-identical to what a deployment with no Google key builds, which is the state every
    deployment is in until an operator attests the price."""
    from apps.api.kb.pack_vectors import embed_entries

    entries = shop_entries(vectors=False)
    attached, model = await embed_entries(None, tenant_id=TENANT, entries=entries)  # type: ignore[arg-type]

    assert attached is entries
    assert model is None
    assert all(entry.vector_f32_b64 is None for entry in attached)


def test_an_empty_corpus_needs_no_encoder_and_asks_for_no_price() -> None:
    dense = DenseIndex(build_pack((), model=None, dimensions=None))
    assert len(dense) == 0
    assert dense.search(_AXES["hours"]) == []
    assert not dense.usable_with(model=FAKE_MODEL, dimensions=FAKE_DIMS)
