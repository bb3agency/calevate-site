"""Passage vectors for one knowledge pack, computed at PUBLISH and never on a call.

**WHY THIS EXISTS AND WHY IT IS HERE RATHER THAN IN THE WORKER.** `voice_worker/knowledge.py`
answers most questions by word-matching in well under a millisecond with no network
(`tests/in_call_lookup_latency_test.py`), and the arm it cannot serve is a question written
in a script the index does not contain: measured at **0.083 recall@1, 22 of 24 answered
`not_found`** on Telugu script
(`tests/in_call_retrieval_recall_test.py`). A dense arm fixes that — 1.000 on the same
corpus at n=24, founder-run against the live Gemini API on 15 Sep 2026 (and 0.9583 on the
same corpus on the previous encoder; n=24 separates neither, and neither is a guarantee) —
but only if there is a
vector to compare against, and computing a few hundred of those is not something a container
holding a live phone call may do. So the CORPUS side is computed once, here, by the publisher
who is not on anybody's clock, and travels inside the pack
(`calevate_shared.knowledge_pack.PackEntry.vector_f32_b64`). The call path is then one
QUERY vector, on the turns the lexical arm already gave up on.

**HARD RULE 7 IS THE FIRST THING THIS MODULE DOES, NOT THE LAST.** `retrieval/embedding.
embedding_price_is_billable` established the shape and this follows it exactly rather than
inventing a second one: ask `billing/rates.llm_price_is_billable` BEFORE a provider is
called, and if the answer is no, build the pack with no vectors and log it. Asking afterwards
is what produces an append-only row with an invented `unit_cost_paid` or — worse — a leg that
buys vectors for ever and records none of them.

⚠ **THE GEMINI EMBEDDING PRICE IS UNVERIFIED IN THIS REPOSITORY AND NOTHING HERE INVENTS
ONE.** `ai.google.dev` is egress-blocked from this container (`docs/PIPECAT-MIGRATION.md`
§10.4 re-measured it 14 Sep 2026). The catalogue now CARRIES a figure for this model
(`calevate_shared.engine.EMBEDDING_MODELS`, $0.20 per 1M input tokens, VENDOR-PUBLISHED and
founder-relayed) — and that changes NOTHING about what may be billed, which is the whole
design: its `Evidence.verified` is False, so hard rule 7 gives it no path to
`unit_cost_paid` and `llm_price_is_billable` is True for it only once an OPERATOR has
entered the figure from their own invoice in the ops console
(`POST /v1/ops/embedding-prices/{model}` -> `ops/model_pricing.attest_embedding_price`).
Until then this module is a no-op that says so in one log line, every pack is built exactly
as it is today, and the in-call dense arm is off. That is the deliberate state, not an
unfinished one: the seam is complete and the input it waits on is outside this repository.

**HARD RULE 6.** A chunk's text and a client's gloss are conversation-adjacent content and
neither is logged. What is logged is the tenant, the agent, counts, a model name and an
exception TYPE — never a provider's error body, which quotes the request, and the request
is the client's own published words.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from calevate_shared.engine import google_openai_compat_base_url
from calevate_shared.knowledge_pack import PackEntry, encode_vector
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.ai_quota import new_assist_ref, record_ai_assist_usage
from apps.api.billing.rates import llm_price_is_billable
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.workers import chat

log = get_logger(__name__)

#: The embedding model, spelled as the WIRE spells it — `models/`-prefixed, which is how
#: Google's OpenAI-compatibility surface names its models and is NOT how the chat leg's
#: `gemini-2.5-flash-lite` is spelled. Metered under this exact string, so the ledger names
#: what was bought rather than a friendlier alias nothing else uses.
#:
#: **EVIDENCE: VENDOR-PUBLISHED, founder-relayed, 15 Sep 2026.** It was DISCOVERED from the
#: live `GET /v1beta/openai/models` listing by `scripts/gemini_embedding_harness.py` (which
#: refuses to name a model from memory for exactly this reason) and reported back with the
#: recall table the whole design rests on. It has NOT been read from a vendor page in this
#: container — `ai.google.dev` is egress-blocked — so this is a relayed live reading, not
#: VERIFIED-VENDOR-DOCS, and it is labelled rather than upgraded by repetition (hard rule 11).
#:
#: ⚠ **THIS WAS `models/gemini-embedding-001` UNTIL D-608 (15 Sep 2026), AND THE MOVE IS A
#: PRICE MOVE RATHER THAN A QUALITY ONE.** `-001` HAS NO PRICE on the vendor's pricing page
#: at all, and a model nobody publishes a price for can never be attested against an invoice
#: line — so `pack_embedding_is_billable()` could never have become True for it and this
#: whole leg was unreachable by construction. `gemini-embedding-2` is listed at $0.20 per 1M
#: INPUT tokens standard ($0.10 batch), with NO OUTPUT CHARGE (Google pricing page dated
#: 2026-09-11, read by the founder and relayed; the host is egress-blocked here and nothing
#: in this session re-fetched it — the figure reaches money ONLY through the operator
#: attestation, never from a constant).
#:
#: **THE MEASUREMENT IS A WASH AND MUST NOT BE READ AS AN UPGRADE.** The founder ran
#: `scripts/gemini_embedding_harness.py` against the live API on 15 Sep 2026 with this model:
#: dimensions 3072, n=24, recall@1 **1.000 English / 1.000 Telugu script / 0.958
#: Telugu-in-Latin** (MRR 0.9635). The prior run on `-001` was 0.958 / 0.958 / 1.000 on the
#: same corpus. n=24 is far too small to separate those, and **1.000 is not a guarantee** —
#: it is 24 questions. What the pair of runs DOES support is the only claim this design
#: rests on: a dense arm answers Telugu script, where the committed lexical-only measurement
#: is **0.083** (`tests/in_call_retrieval_recall_test.py`).
#:
#: **CHANGING THIS STRING INVALIDATES EVERY PUBLISHED PACK, DELIBERATELY AND SAFELY.** The
#: encoder's name is inside the pack id (`KnowledgePack.digest`), so `kb/pack
#: .agents_with_stale_packs` reads every pack built under the old encoder as stale and the
#: gloss sweep rebuilds each one ONCE — after which the digest matches and the agent is not
#: selected again. On a deployment with no attested price (every deployment today) both the
#: old and the new declaration are `None`, so nothing is stale and nothing rebuilds.
#: `tests/kb_gloss_pack_refresh_test.py` proves both halves.
EMBEDDING_MODEL: Final = "models/gemini-embedding-2"

#: The width every pack vector has, SENT as the request's `dimensions` and re-checked on the
#: way back — `retrieval/embedding.EMBEDDING_DIMS`' rule, for its reason: the number in the
#: pack is the number we asked for rather than a number somebody believed.
#:
#: **3072 BECAUSE THAT IS THE WIDTH THE MEASUREMENT WAS TAKEN AT**, and nothing else. The
#: founder's run reports `dimensions: 3072` beside 0.9583 / 0.9583 / 1.0000. Narrowing it is
#: one changed integer and would shrink the pack fourfold, and it is deliberately NOT taken
#: here: whether this model truncates gracefully is UNVERIFIED, and a narrower width whose
#: recall nobody has measured would silently replace the only numbers this design has. That
#: is a measurement to run (`scripts/gemini_embedding_harness.py` takes a corpus and would
#: take a width), not an optimisation to guess.
#:
#: ⚠ **THE FIELD IS ACCEPTED, THE TRUNCATION IS NOT PROVEN.** `dimensions` passes the
#: endpoint's body parser — VERIFIED-LIVE from this container, 14 Sep 2026, using the
#: two-request discrimination `copilot/service.py` documents (`{"zzz_not_a_param": true}`
#: is refused by NAME, `{"dimensions": 768}` fails only on the credential). That proves the
#: request is well-formed, not that the vendor honours it; `_vectors_for` refuses any row
#: that comes back at another width, which is what makes the difference safe.
EMBEDDING_DIMS: Final = 3072

#: `usage_events.meta.feature` for pack embedding. ITS OWN NAME, beside
#: `retrieval/embedding.ASSIST_FEATURE_KB_EMBED` rather than reusing it, and the split is
#: that constant's own argument applied once more: they run on the same corpus at the same
#: trigger but they are two different purchases at two different unit prices, on two
#: different vendors, for two different consumers (the dashboard's pgvector index; the
#: worker's in-memory pack). One name would make the two curves unseparable in the only
#: ledger that has them, which is the exact reason ingestion and query were split.
ASSIST_FEATURE_PACK_EMBED: Final = "kb_pack_embed"

#: Wall clock for one batch. Generous because NOBODY IS WAITING: this runs on the publish
#: path, behind a client who has just clicked "publish" on a document, and the alternative
#: to waiting is a pack with no dense arm until the next publish. It is bounded at all for
#: `storage.PACK_FETCH_BUDGET_S`' reason — a provider that accepts the connection and then
#: stops talking must not hold the publish open for as long as the socket lives.
EMBED_TIMEOUT_S: Final = 60.0

#: Passages per request. The vendor's own limit for this route is UNKNOWN (egress-blocked),
#: so this is OUR blast radius rather than their ceiling: one failed batch costs at most this
#: many entries their vector, and the pack is still built and still answers lexically. Array
#: `input` is VERIFIED-LIVE as well-formed on this route (same probe, same date); that the
#: vendor returns one row per input in `index` order is not proven from here, which is why
#: `chat.embed` re-establishes the order from `index` and `_vectors_for` refuses a short
#: return rather than zipping what came back against what went out.
EMBED_BATCH: Final = 16


def pack_embedding_is_billable() -> bool:
    """May a pack embedding's cost reach `unit_cost_paid`? Asked BEFORE the provider, always.

    `billing/rates.llm_price_is_billable` is asked rather than a second rule being written
    here: it is total, never raises, and already encodes the only two grounds this repository
    accepts (an operator attested it, or the catalogue figure was read from the vendor).
    Neither is met for `EMBEDDING_MODEL` by any constant in this tree today — the catalogue
    figure is `verified=False`, see the module docstring — so this is False until an operator
    enters the figure.
    """
    return llm_price_is_billable(EMBEDDING_MODEL)


def pack_embedding_declaration(entries: tuple[PackEntry, ...]) -> str | None:
    """Which encoder a pack built from `entries` WILL declare — answered without buying one.

    **THIS EXISTS BECAUSE THE STALENESS SCAN HAS TO ASK THE QUESTION AND MUST NOT PAY FOR
    THE ANSWER** (`kb/pack.agents_with_stale_packs`, which argues the whole trade). The
    encoder's name is inside the pack id (`KnowledgePack.digest`), so anything comparing a
    recorded id against the one an agent's corpus implies needs the encoder BEFORE it has a
    pack — and the only other way to learn it is to call `embed_entries`, which spends real
    money per agent per tick to recompute a declaration that is a property of this
    deployment's configuration rather than of the corpus.

    So the two free pre-flights `embed_entries` already runs are named once, here, and both
    callers read them: hard rule 7's price question (`pack_embedding_is_billable`, asked
    before a provider is ever addressed) and whether a credential exists at all
    (`embedding_leg`). Neither touches the network, neither writes a ledger row, and
    `attested_llm_prices()` is an in-process read.

    **IT IS A PREDICTION IN ONE DIRECTION ONLY, AND THAT ASYMMETRY IS DELIBERATE.** A `None`
    here is certain — nothing downstream can conjure a vector out of no price or no key — and
    a model name here is "this is what will be declared IF any vector lands". The one state
    where the prediction and the outcome differ is a deployment that is configured to embed
    and whose provider refused EVERY batch: `embed_entries` then declares nothing, the pack
    is built with no dense arm, and a scan reading this stays one tick behind it. That is the
    right way round. It costs the failing deployment a rebuild attempt per glossed agent per
    tick and buys it the dense arm the moment the provider answers again — and a refused
    request buys no vectors, so it is not billable and reaches no `usage_events` row.
    """
    if not entries or not pack_embedding_is_billable() or embedding_leg() is None:
        return None
    return EMBEDDING_MODEL


def declared_dimensions(model: str | None) -> int | None:
    """`EMBEDDING_DIMS` beside a declared encoder, `None` without one.

    The pack's two embedding fields are ONE fact and a pack carrying half of it is refused
    (`KnowledgePack._embedding_declaration_is_whole`), so the pairing is spelled once rather
    than at each site that has a model and needs a width.
    """
    return None if model is None else EMBEDDING_DIMS


def embedding_leg() -> chat.ChatLeg | None:
    """Where a pack-embedding request goes, or `None` when this deployment cannot make one.

    THE SAME CREDENTIAL, ENDPOINT AND DIALECT AS EVERY OTHER GEMINI CALL IN THIS TREE, so
    this adds NO sub-processor and no second residency story: `Settings.gemini_api_key` is
    what `copilot/service._provider_leg` reads, and `google_openai_compat_base_url()` is the
    ONE constructor `scripts/check_model_residency.py` grants the Developer API host literal
    to. A second URL built here would be the exact thing that guard exists to refuse.

    `None` rather than a raise for `retrieval/embedding.embedding_leg`'s reason: a deployment
    with no Google key publishes knowledge, serves calls and runs every other queue. It is a
    configuration state an operator already sees, not an incident.
    """
    api_key = (get_settings().gemini_api_key or "").strip()
    if not api_key:
        return None
    return chat.ChatLeg(
        url=f"{google_openai_compat_base_url()}/embeddings",
        api_key=api_key,
        wire_model=EMBEDDING_MODEL,
        dialect="google",
    )


def embedding_input(entry: PackEntry) -> str:
    """What gets embedded for one entry: the client's own words AND the English gloss.

    **ONE STRING, THE SAME BAG THE LEXICAL ARM INDEXES** (`LexicalIndex._entry_tokens` joins
    them the same way and for the same reason). Two alternatives were available and both are
    worse:

    * **The gloss alone.** It is an English paraphrase written as a key for a WORD-MATCHING
      arm; a dense model reads Telugu directly, and the whole point of this arm is that it
      does not need the paraphrase. Embedding only the gloss would rebuild the
      English-paraphrase dependency `docs/PIPECAT-MIGRATION.md` §9.4 calls load-bearing, in
      the one place that was about to remove it.
    * **The client's text alone.** An agent's corpus is often already English, and a gloss,
      where one exists, is a second phrasing of the same fact — free recall for a question
      phrased the other way round.
    """
    return entry.text if entry.gloss is None else f"{entry.text}\n{entry.gloss}"


async def _vectors_for(
    session: AsyncSession, *, tenant_id: UUID, leg: chat.ChatLeg, batch: tuple[PackEntry, ...]
) -> dict[int, str]:
    """One request: position-in-batch → encoded vector, for the rows that came back usable.

    **METERED WHETHER OR NOT THE VECTORS ARE USABLE.** We paid for the request; a refused
    width is our problem and not a discount. `retrieval/embedding.embed_query_vector` makes
    the same call and the reasoning is identical — `tokens_out=0` is the truth about an
    embedding rather than a default, because the vendor's `usage` block has no output half.

    A width that disagrees drops the ROW and not the batch: one malformed vector among
    sixteen is one entry the dense arm cannot reach, which is a state the format already has.
    """
    outcome = await chat.embed(
        leg,
        [embedding_input(entry) for entry in batch],
        dimensions=EMBEDDING_DIMS,
        timeout_s=EMBED_TIMEOUT_S,
    )
    if outcome.usage is not None:
        await record_ai_assist_usage(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            tokens_in=outcome.usage.prompt_tokens,
            tokens_out=0,
            model=EMBEDDING_MODEL,
            feature=ASSIST_FEATURE_PACK_EMBED,
        )
    return {
        position: encode_vector(vector)
        for position, vector in enumerate(outcome.vectors)
        if position < len(batch) and len(vector) == EMBEDDING_DIMS
    }


async def embed_entries(
    session: AsyncSession, *, tenant_id: UUID, entries: tuple[PackEntry, ...]
) -> tuple[tuple[PackEntry, ...], str | None]:
    """`entries` with vectors attached where one could be bought, and the model that made them.

    Returns `(entries, None)` UNCHANGED — same objects, same order — whenever there is
    nothing to embed, no price, or no credential. That triple is why the return carries the
    model name rather than the caller deriving it: "this pack declares an encoder" and "this
    deployment has an encoder configured" are different facts, and only the first belongs in
    the pack (`KnowledgePack._embedding_declaration_is_whole` refuses a pack that confuses
    them).

    **A PROVIDER FAILURE COSTS THE DENSE ARM AND NEVER THE PUBLISH.** `refresh_published_pack`
    already argues the posture at length for the object store: the knowledge base is the
    client's authored record and a derived artefact must not be able to veto the thing it
    derives from. A batch that raises is logged by TYPE and skipped; its entries keep
    `vector_f32_b64 = None`, every other batch stands, and the pack is published with a
    partial dense arm rather than not at all. The next publish re-embeds from scratch.

    **THE DECLARATION IS MADE WHENEVER ANY VECTOR LANDED**, not when all of them did — a pack
    with 300 of 320 entries embedded is a pack whose dense arm works on 300 entries, and the
    contract already treats a missing vector as "unreachable by that arm".
    """
    model = pack_embedding_declaration(entries)
    leg = embedding_leg()
    if model is None or leg is None:
        # The GROUND is logged separately from the decision, because the decision is now one
        # expression shared with the staleness scan and an operator still has to be able to
        # tell "nobody has attested the price" from "nobody has installed the key" — two
        # different people fix those. An empty corpus is neither and says nothing.
        if entries and not pack_embedding_is_billable():
            log.info(
                "knowledge_pack_embedding_unpriced",
                extra={"tenant_id": str(tenant_id), "model": EMBEDDING_MODEL},
            )
        elif entries:
            log.info("knowledge_pack_embedding_no_provider", extra={"tenant_id": str(tenant_id)})
        return entries, None

    encoded: dict[int, str] = {}
    failed_batches = 0
    for start in range(0, len(entries), EMBED_BATCH):
        batch = entries[start : start + EMBED_BATCH]
        try:
            found = await _vectors_for(session, tenant_id=tenant_id, leg=leg, batch=batch)
        # Broad on purpose and narrowed nowhere: every way a hosted encoder can fail ends in
        # the same outcome for this pack, and none of them may reach the publish. The TYPE is
        # logged and the message is not — a provider's body quotes the request, and the
        # request is the client's published text.
        except Exception as failure:
            failed_batches += 1
            log.warning(
                "knowledge_pack_embedding_batch_failed",
                extra={"tenant_id": str(tenant_id), "error": type(failure).__name__},
            )
            continue
        encoded.update({start + position: value for position, value in found.items()})

    if not encoded:
        log.warning(
            "knowledge_pack_embedding_empty",
            extra={
                "tenant_id": str(tenant_id),
                "entries": len(entries),
                "failed_batches": failed_batches,
            },
        )
        return entries, None

    log.info(
        "knowledge_pack_embedded",
        extra={
            "tenant_id": str(tenant_id),
            "entries": len(entries),
            "vectors": len(encoded),
            "failed_batches": failed_batches,
            "model": EMBEDDING_MODEL,
            "dimensions": EMBEDDING_DIMS,
        },
    )
    return (
        tuple(
            entry
            if position not in encoded
            else entry.model_copy(update={"vector_f32_b64": encoded[position]})
            for position, entry in enumerate(entries)
        ),
        model,
    )


__all__ = [
    "ASSIST_FEATURE_PACK_EMBED",
    "EMBEDDING_DIMS",
    "EMBEDDING_MODEL",
    "EMBED_BATCH",
    "EMBED_TIMEOUT_S",
    "declared_dimensions",
    "embed_entries",
    "embedding_input",
    "embedding_leg",
    "pack_embedding_declaration",
    "pack_embedding_is_billable",
]
