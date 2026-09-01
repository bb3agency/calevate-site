"""The embedding vocabulary: which model, how wide, what it costs, and what it refuses.

WHY THIS IS ITS OWN MODULE AND NOT A CONSTANT IN THE ADAPTER. Three surfaces need the same
four facts and must never disagree about them: the migration that sizes the column, the
sweep that fills it, and the retriever that embeds a question to compare against it. A
vector written at one width and searched at another is not an error Postgres reports — it
is `ERROR: different vector dimensions` on the lucky path and a silently wrong ranking on
the unlucky one — so the width has one author.

THE MODEL AND THE WIDTH, VERIFIED AT SOURCE. `text-embedding-3-small` is one of the three
identifiers the vendor's own OpenAPI enumerates for `POST /embeddings`, and the same schema
carries the `dimensions` request field: *"The number of dimensions the resulting output
embeddings should have. Only supported in `text-embedding-3` and later models."*
(VERIFIED-VENDOR-SPEC: `openai/openai-openapi` `openapi.yaml` @ `master`, `CreateEmbedding
Request`, lines 34336-34358, fetched from `raw.githubusercontent.com` on 1 September 2026.)

**THAT FIELD IS WHY `EMBEDDING_DIMS` IS SENT RATHER THAN ASSUMED, AND IT IS ALSO THE EXIT
CLAUSE.** This repository has not read a vendor page stating the model's NATIVE width, and
`platform.openai.com` and `azure.microsoft.com` are both egress-blocked from this container
(measured 1 Sep 2026), so "1536 is the default" would be a claim with no source behind it
(hard rule 11). Instead the request NAMES the width it wants and `check_width` refuses
anything else, so the number in the column type is the number we asked for rather than a
number we believed. The same field is what makes a later narrowing free: these models are
Matryoshka-style, so 512 or 768 is a re-request, not a re-embedding — the property that
keeps a move to a managed vendor cheap, since the vendor is handed whatever width we choose
at export time.

WHAT THIS MODULE DOES NOT DECIDE: whether a client may search (that is
`retrieval/service.get_retriever`), what a chunk is (`kb/service.chunk_text`), and what a
token costs (`billing/rates.llm_inr_per_ktok` — the one door to `unit_cost_paid`).
"""

from __future__ import annotations

from typing import Final

from apps.api.billing.rates import llm_price_is_billable
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.workers.chat import ChatLeg
from apps.workers.extraction import azure_credentials

log = get_logger(__name__)

#: The model, spelled as the wire spells it. Metered under this name — never under the
#: Azure DEPLOYMENT id, which is an operator's free choice and which
#: `billing/rates.llm_inr_per_ktok` publishes no price for (the D-410/D-417 distinction
#: `workers/kb_gloss.py` already makes on the chat leg).
EMBEDDING_MODEL: Final = "text-embedding-3-small"

#: The width every vector in `kb_chunks.embedding` has, sent as the request's `dimensions`
#: and re-checked on the way back. 1536 because it is the width the column was built at and
#: the width the bake-off's plan analysis transfers to; the value is OURS, requested
#: explicitly, not a vendor default this repository has read.
#:
#: Under pgvector's own limit for an HNSW index on `vector` (2,000 dimensions) with room to
#: spare, which is what lets the index exist at all at this width.
EMBEDDING_DIMS: Final = 1536

#: `usage_events.meta.feature` for INGESTION embedding — the sweep that vectorises approved
#: chunks (`apps/workers/kb_embeddings.py`).
#:
#: `crm/assist.ASSIST_FEATURE_KB_GLOSS`'s argument, applied a second time and for the same
#: reason: this is background spend that NO CLIENT ACTION TRIGGERS, its quantity is a
#: function of how much knowledge a client UPLOADS rather than of how much they USE, and an
#: operator asking "what did we spend on the client's behalf" cannot answer it if a sweep is
#: filed under an interactive surface. It is deliberately NOT the same name as the gloss:
#: the two run on the same corpus and the same trigger but at different unit prices, and one
#: name would make the two curves unseparable in the only ledger that has them.
ASSIST_FEATURE_KB_EMBED: Final = "kb_embed"

#: `usage_events.meta.feature` for QUERY-TIME embedding — one vector per dashboard search.
#:
#: A SEPARATE NAME FROM INGESTION, and the split is the point rather than bookkeeping
#: neatness. Ingestion is paid once per chunk and is bounded by what a client uploads; this
#: is paid once per QUESTION and is bounded by how much they use the assistant. They are two
#: different cost curves on one model, and an operator sizing either one needs to see it
#: alone. (Who ultimately PAYS for the query side is an open founder question; until it is
#: answered this lands on the tenant's AI ceiling like every other thing their own click
#: caused, which is the existing rule rather than a new one.)
ASSIST_FEATURE_KB_SEARCH: Final = "kb_search_embedding"

#: Wall clock for one embedding request. Nobody is waiting on the sweep; the dashboard
#: search is, which is why this is short — a hung provider costs a slow tool call, not a
#: hung copilot turn.
EMBED_TIMEOUT_S: Final = 20.0

#: The most texts one request carries. The vendor's own schema bounds `input` at 2,048
#: array items (`openapi.yaml`, `CreateEmbeddingRequest`, read 1 Sep 2026); this is far
#: below it because the thing being bounded here is not the vendor's limit but OUR blast
#: radius — one failed request re-does at most this many chunks on the next tick, and one
#: request's tokens are one `usage_events` row.
EMBED_BATCH: Final = 32


def embedding_price_is_billable() -> bool:
    """May an embedding's cost reach `unit_cost_paid`? **THIS IS HARD RULE 7's PRE-FLIGHT.**

    Asked BEFORE a provider is called, never after, and that ordering is the whole value of
    the function. `record_ai_assist_usage` derives the price from the model and RAISES for a
    model nobody priced — correct, and fatal in a worker: the raise rolls back the
    transaction that also holds the state change, so the chunk returns to `pending` and the
    next tick pays the provider again to reach the same raise. An unpriced embedding leg
    would therefore buy vectors for ever and record none of them. Checking first turns that
    loop into one log line and no spend.

    `billing/rates.llm_price_is_billable` is asked rather than a second rule written here:
    it is total, never raises, and already encodes the only two grounds this repository
    accepts (an operator attested it, or the catalogue figure was read from the vendor).
    Neither ground is met for this model by any constant in this tree — no embedding price
    has been read from a vendor page here, and none is invented — so today this is True only
    once an operator has entered the figure from their own Azure invoice
    (`ops/model_pricing.set_model_price`).
    """
    return llm_price_is_billable(EMBEDDING_MODEL)


def embedding_leg() -> ChatLeg | None:
    """Where an embedding request goes, or None when this deployment cannot make one.

    THE SAME RESOURCE, REGION AND CREDENTIAL AS EVERY OTHER LANGUAGE CALL (D-410/D-449), so
    this adds NO sub-processor: `extraction.azure_credentials()` is the one reader of the
    three Azure credential fields and `calevate_shared.engine.azure_openai_base_url` is the
    one endpoint builder `scripts/check_model_residency.py` grants the host literal to.

    **THE DEPLOYMENT IS ITS OWN FIELD AND CANNOT BE THE CHAT ONE.** On Azure a model is
    served under a deployment id an operator chose, and an embedding model is a different
    deployment from a chat model however they are named — posting `text-embedding-3-small`
    input to the chat deployment is a 400 at best. So `azure_openai_embedding_deployment`
    is read here and the chat deployment returned by `azure_credentials()` is deliberately
    discarded.

    Returns None rather than raising for `azure_credentials`' reason: a deployment with no
    embedding deployment configured runs every other queue and every other tier, and this is
    a configuration state an operator already sees rather than an incident.
    """
    credentials = azure_credentials()
    if credentials is None:
        return None
    resource, api_key, _chat_deployment = credentials
    deployment = (get_settings().azure_openai_embedding_deployment or "").strip()
    if not deployment:
        return None
    # Imported here rather than at module scope only so the residency check's one-builder
    # rule reads at the call site; there is no cycle to avoid.
    from calevate_shared.engine import azure_openai_base_url

    return ChatLeg(
        url=f"{azure_openai_base_url(resource)}/embeddings",
        api_key=api_key,
        wire_model=deployment,
        dialect="openai",
    )


__all__ = [
    "ASSIST_FEATURE_KB_EMBED",
    "ASSIST_FEATURE_KB_SEARCH",
    "EMBEDDING_DIMS",
    "EMBEDDING_MODEL",
    "EMBED_BATCH",
    "EMBED_TIMEOUT_S",
    "embedding_leg",
    "embedding_price_is_billable",
]
