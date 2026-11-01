"""The embedding leg is Gemini (D-952): which model, which width, which endpoint, which task.

The wire is faked with `httpx.MockTransport`; nothing here reaches Google.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.agents.llm_models import install_dashboard_data_use_reader
from apps.api.billing.rates import LlmPriceAttestation, install_llm_price_attestations
from apps.api.core.settings import get_settings
from apps.api.retrieval import embedding
from apps.workers import chat, gemini_native
from calevate_shared.engine import EMBEDDING_MODELS, google_native_base_url

_KEY = "gk-test"


@pytest.fixture
def google_ready(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Our Gemini key installed and the Google data-use attestation recorded."""
    monkeypatch.setattr(get_settings(), "gemini_api_key", _KEY, raising=False)
    install_dashboard_data_use_reader(lambda: frozenset({"google"}))
    yield
    install_dashboard_data_use_reader(None)


def test_the_encoder_is_gemini_at_the_width_the_columns_hold() -> None:
    spec = EMBEDDING_MODELS[embedding.EMBEDDING_MODEL]
    assert embedding.EMBEDDING_MODEL == "gemini-embedding-2"
    assert spec.provider == "google"
    assert spec.dimensions == embedding.EMBEDDING_DIMS == 1536
    assert list(EMBEDDING_MODELS) == [embedding.EMBEDDING_MODEL], "one encoder, not a chain"


def test_the_leg_is_gemini_native_batch_embed_on_our_key(google_ready: None) -> None:
    leg = embedding.embedding_leg()
    assert leg is not None
    assert leg.url == f"{google_native_base_url()}/models/gemini-embedding-2:batchEmbedContents"
    assert leg.url.startswith("https://generativelanguage.googleapis.com/v1beta/models/")
    assert leg.wire_model == "gemini-embedding-2"
    assert leg.api_key == _KEY
    assert chat.provider_of(leg) == "google"


def test_no_leg_without_the_google_data_use_attestation(monkeypatch: pytest.MonkeyPatch) -> None:
    """FAILS IF: a client's knowledge, calls or leads can reach Google before an operator has
    recorded that our project is on a tier Google does not train on."""
    monkeypatch.setattr(get_settings(), "gemini_api_key", _KEY, raising=False)
    install_dashboard_data_use_reader(lambda: frozenset())
    try:
        assert embedding.embedding_leg() is None
    finally:
        install_dashboard_data_use_reader(None)


def test_azure_credentials_do_not_make_an_embedding_leg(monkeypatch: pytest.MonkeyPatch) -> None:
    """One encoder: with Azure configured and no Gemini key there is nothing to embed with."""
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", "calevate-eus2", raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "az-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "gpt-4o-mini", raising=False)
    monkeypatch.setattr(settings, "gemini_api_key", None, raising=False)
    install_dashboard_data_use_reader(lambda: frozenset({"google"}))
    try:
        assert embedding.embedding_leg() is None
    finally:
        install_dashboard_data_use_reader(None)


def test_the_price_gate_opens_only_on_an_attested_figure() -> None:
    """The catalogue's Gemini price is VENDOR-PUBLISHED and filed unverified, so no embedding
    is bought until an operator attests it (hard rule 7)."""
    install_llm_price_attestations(None)
    assert not EMBEDDING_MODELS[embedding.EMBEDDING_MODEL].price.evidence.verified
    assert embedding.embedding_price_is_billable() is False
    install_llm_price_attestations(
        lambda: {
            embedding.EMBEDDING_MODEL: LlmPriceAttestation(
                model=embedding.EMBEDDING_MODEL,
                input_usd_per_mtok=Decimal("0.20"),
                output_usd_per_mtok=None,
                read_on=date(2026, 11, 1),
                attested_by="test",
                source="fixture",
            )
        }
    )
    try:
        assert embedding.embedding_price_is_billable() is True
    finally:
        install_llm_price_attestations(None)


_LEG = chat.ChatLeg(
    url="https://example.invalid/v1beta/models/gemini-embedding-2:batchEmbedContents",
    api_key=_KEY,
    wire_model="gemini-embedding-2",
    dialect="google",
)


async def _round_trip(
    answer: dict[str, Any], *, task: gemini_native.EmbedTask = "document", status: int = 200
) -> tuple[gemini_native.EmbeddingOutcome, httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=answer)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = await gemini_native.embed(
            _LEG, ["first", "second"], task=task, dimensions=3, timeout_s=5, client=client
        )
    return outcome, seen[0]


async def test_a_batch_round_trip_sends_the_documented_body_and_reads_vectors_in_order() -> None:
    outcome, request = await _round_trip(
        {
            "embeddings": [{"values": [0.1, 0.2, 0.3]}, {"values": [0.4, 0.5, 0.6]}],
            "usageMetadata": {"promptTokenCount": 17},
        }
    )
    assert str(request.url) == _LEG.url
    assert request.headers["x-goog-api-key"] == _KEY
    assert "authorization" not in request.headers
    assert json.loads(request.content) == {
        "requests": [
            {
                "model": "models/gemini-embedding-2",
                "content": {"parts": [{"text": f"title: none | text: {text}"}]},
                "embedContentConfig": {"outputDimensionality": 3},
            }
            for text in ("first", "second")
        ]
    }
    assert outcome.vectors == ((0.1, 0.2, 0.3), (0.4, 0.5, 0.6))
    assert outcome.usage is not None
    assert (outcome.usage.prompt_tokens, outcome.usage.output_tokens) == (17, 0)


async def test_a_question_carries_the_query_prefix_and_a_passage_the_document_one() -> None:
    _, query = await _round_trip({"embeddings": []}, task="query")
    _, document = await _round_trip({"embeddings": []}, task="document")
    texts = [
        [r["content"]["parts"][0]["text"] for r in json.loads(req.content)["requests"]]
        for req in (query, document)
    ]
    assert texts == [
        ["task: search result | query: first", "task: search result | query: second"],
        ["title: none | text: first", "title: none | text: second"],
    ]


def test_a_document_title_is_the_context_prefix_and_is_kept_to_one_line() -> None:
    body = gemini_native.embed_request(
        "gemini-embedding-2",
        ["Sunday 9 to 12", "Free parking"],
        task="document",
        dimensions=3,
        titles=["Clinic\nhours", None],
    )
    assert [r["content"]["parts"][0]["text"] for r in body["requests"]] == [
        "title: Clinic hours | text: Sunday 9 to 12",
        "title: none | text: Free parking",
    ]
    with pytest.raises(ValueError):
        gemini_native.embed_request(
            "gemini-embedding-2", ["a"], task="document", dimensions=3, titles=[]
        )


async def test_an_unusable_vector_ends_the_answer_rather_than_shifting_a_neighbour_in() -> None:
    """FAILS IF: input 1 is handed input 2's vector, or a NaN reaches pgvector."""
    for bad in ({"values": ["NaN", 1.0, 1.0]}, {"values": ["x", None, 1.0]}, {}):
        outcome, _ = await _round_trip({"embeddings": [bad, {"values": [1.0, 1.0, 1.0]}]})
        assert outcome.vectors == ()


async def test_an_answer_without_usage_is_unmetered_not_free() -> None:
    outcome, _ = await _round_trip({"embeddings": [{"values": [1.0, 1.0, 1.0]}]})
    assert outcome.vectors == ((1.0, 1.0, 1.0),)
    assert outcome.usage is None


async def test_a_refused_batch_raises_as_a_refusal_of_this_input() -> None:
    with pytest.raises(httpx.HTTPStatusError) as raised:
        await _round_trip({"error": {"code": 400}}, status=400)
    assert chat.refused_this_input(raised.value)
