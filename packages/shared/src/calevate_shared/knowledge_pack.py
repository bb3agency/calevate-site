"""The in-call knowledge pack: what an agent knows, frozen at publish, loaded into RAM.

WHY A PACK AND NOT A QUERY (D-599). Under a rented engine the knowledge base was the
vendor's and retrieval happened inside their process. We run the loop now
(`apps/voice-worker/`, D-592), so retrieval is ours to place — and the measured facts put
it in memory rather than behind any network:

* The in-call budget is 100ms, and a round trip to the query-embedding endpoint alone is an
  ocean crossing (`apps/api/retrieval/embedding.py` posts to Azure East US 2).
* A store read per TURN buys a failure mode per turn — a timeout, a rate limit, a pool
  slot. An in-memory lookup has none of those and cannot be slow under concurrency,
  because there is no shared resource to contend for.
* The corpus is per-agent and small. Loading it once, while the phone is ringing, spends
  wall-clock nobody is waiting on.

So a pack is built ONCE at publish, stored immutably, fetched ONCE per session (or not at
all, when a warm container already holds it), and searched in-process on every turn.

CONTENT-ADDRESSED, FOR THE REASON `agent_config_versions` IS. The pack's id IS the hash of
its content, so a key can never mean two things. That is what makes it safe for a container
that Pipecat Cloud REUSES ACROSS SESSIONS to cache one: eviction is by key, and a key that
cannot be reused for different bytes cannot serve clinic A's knowledge into clinic B's call.
Tenancy at the process level, by construction rather than by discipline.

VERSION 1 CARRIED NO VECTORS AND VERSION 2 CARRIES THEM, BECAUSE THE MEASUREMENT THAT
RULED THEM OUT WAS ABOUT A **LOCAL ENCODER** AND NOT ABOUT DENSE RETRIEVAL. That reasoning
is kept verbatim because it is still true of the thing it was about — a query vector in-call
needs an encoder, and measured on an Intel Xeon @ 2.10GHz (AVX-512, 4 cores), GEMM-only
floor at `seq_len=32`:

    threads   bge-base (12L/768)   MiniLM-L6 (6L/384)
    1              78.7 ms              9.3 ms
    2              43.7 ms              5.0 ms
    4              25.6 ms              3.2 ms

The worker shares those cores with STT, TTS, VAD and smart-turn, so 1-2 threads is the real
budget, which rules out `bge-base` against a 100ms turn; and `bge-base-en-v1.5` is exactly
the model `docs/evidence/telugu-embedding-quality.md` found best on our query form.

**WHAT CHANGED IS THE CORPUS SIDE, AND IT CHANGED THE ARITHMETIC COMPLETELY.** A pack is
built ONCE at publish, on the control plane, where nobody is holding a phone. So the
PASSAGE vectors cost a call nothing at all: they are computed by the publisher and travel
in these bytes. Only the QUERY vector is left on the call path, and it is one hosted
request rather than an encoder in a latency-critical container.

**AND THE RECALL IT BUYS IS A DIFFERENT CAPABILITY, NOT AN IMPROVEMENT.** Measured against
the live Gemini API by the founder with their own key, 14 Sep 2026, `models/gemini-
embedding-001`, 3072 dimensions, n=24, English-only index (`scripts/gemini_embedding_
harness.py`; VENDOR-PUBLISHED via a founder-relayed live run, not fetchable from this
container):

    query form        recall@1   recall@3   MRR
    query_en            0.9583     1.0000   0.9722
    query_te            0.9583     1.0000   0.9792
    query_tenglish      1.0000     1.0000   1.0000

against the shipped lexical arm's 0.833 English, 0.583 Tenglish and **0.083 Telugu script,
22 of 24 answered `not_found`** (`tests/in_call_retrieval_recall_test.py`). A Telugu-script
question goes from two hits in twenty-four to twenty-three. That is not a better ranking of
the same answers — it is the removal of the English-paraphrase dependency the lexical index
has, which `docs/PIPECAT-MIGRATION.md` §9.4 records as load-bearing.

**SO THE PACK CARRIES VECTORS AND THE LEXICAL ARM IS STILL THE FAST PATH.** Version 2 adds
one optional field per entry and two declarations to the pack; the consumer
(`voice_worker/knowledge.py`) runs the dense arm ONLY where the lexical one already said it
had no answer. Nothing about the sub-millisecond `found` path changes
(`tests/in_call_lookup_latency_test.py`).

**WHY THE VECTOR IS BASE64 float32 AND NOT A JSON ARRAY OF NUMBERS.** 3072 floats rendered
as JSON decimals is ~60 KB per entry; as little-endian float32 it is 12,288 bytes, base64
16,384 characters. That was arithmetic when it was written and it is now WEIGHED
(`tests/in_call_lookup_latency_test.py`, 14 Sep 2026, against the bytes
`kb/pack.publish_pack` actually uploads): **63,775 B for one vector as JSON decimals against
16,382 B of serialised pack per entry for the encoded form**, and a 300-entry pack at 3072
dimensions is **5,003,292 B**. So the choice is worth 3.9x and the few-hundred-entry pack is
~5 MB rather than ~18 MB, fetched inside `voice_worker/storage.PACK_FETCH_BUDGET_S` while
the phone rings — and a pack that times out is answered `temporarily_unavailable`, which is
strictly worse than the lexical-only pack it replaced. ⚠ **WHETHER 5 MB FITS IN THAT BUDGET
IS STILL UNMEASURED**: the budget is an assumption (its own docstring says so), a size is
not a transfer time, and nobody has timed the fetch from `ap-south`.

float32 is also what every vector store holds; cosine over it is the industry default, and
the precision the JSON form would preserve is precision the ranking cannot use.

**THE VECTORS ARE NOT IN THE DIGEST AND THE EMBEDDING DECLARATION IS. THAT IS THE ONE
NON-OBVIOUS CHOICE IN THIS FILE, SO HERE IS THE WHOLE ARGUMENT.** A vector is a DERIVED
artefact of (text, model, width) and every one of those three inputs is already hashed, so
hashing the derivation adds no power to distinguish two corpora — except in one case:
whether the vendor returns bit-identical floats for identical input across calls is
**UNVERIFIED** (`ai.google.dev` is egress-blocked here and nobody has measured it). If it
does not, hashing the floats would mint a new pack id on every rebuild of unchanged
knowledge and invalidate every warm container, which is the exact defect `built_at` is
excluded for. Leaving them out is correct under either fact. What must NOT be lost is that
a pack embedded under a different model or a different width is a DIFFERENT pack — a
container holding the old build would otherwise serve it for the new digest and the dense
arm would silently compare vectors from two models — so `embedding_model` and
`embedding_dimensions` are hashed, and a re-embedding under a new model therefore mints a
new id and forces a fresh upload through `kb/pack.publish_pack`'s write-once skip.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import struct
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "PACK_FORMAT_VERSION",
    "PACK_OBJECT_PREFIX",
    "SUPPORTED_PACK_FORMAT_VERSIONS",
    "KnowledgePack",
    "PackEntry",
    "RetrievalOutcome",
    "decode_vector",
    "encode_vector",
    "pack_object_key",
    "parse_pack_object_key",
]

#: Bumped when the on-the-wire shape changes. What a BUILDER writes.
PACK_FORMAT_VERSION: Literal[2] = 2

#: What a READER accepts, which is deliberately not the same thing.
#:
#: **A VERSION WE DO NOT UNDERSTAND IS STILL REFUSED, AND THAT RULE HAS NOT MOVED.** The
#: reason it exists is that a half-understood corpus is worse than none: an agent that
#: silently lost entries cannot tell it is missing knowledge it thinks it has. Version 1 is
#: not half-understood — version 2 is a strict SUPERSET of it (one optional field on the
#: entry, two optional declarations on the pack), so a v1 pack read by a v2 worker is
#: understood completely and simply has no dense arm.
#:
#: **THE ALTERNATIVE WAS REFUSING v1, AND IT IS AN OUTAGE RATHER THAN A CAUTION.**
#: `agents.knowledge_pack_sha256` points at whatever was published last, and nothing
#: republishes on deploy. A reader that accepted only `PACK_FORMAT_VERSION` would answer
#: `temporarily_unavailable` to every question on every agent on every call, from the moment
#: this constant changed until each client happened to publish something — which is the
#: state the refusal rule was written to prevent, arrived at by obeying its words. Hard rule
#: 12's "satisfying the WORDS of an instruction while defeating its PURPOSE", in the small.
#:
#: A version is added here only when a reader in this tree can genuinely answer every
#: question from a pack of that version. Dropping one is how a format is retired.
SUPPORTED_PACK_FORMAT_VERSIONS: frozenset[int] = frozenset({1, 2})


def encode_vector(values: tuple[float, ...]) -> str:
    """One passage vector as base64 of LITTLE-ENDIAN float32. The pack's only binary field.

    `<` on the struct format is doing real work and is not decoration: `array('f').tobytes()`
    is NATIVE-endian, so a pack built on one architecture and read on another would decode to
    byte-swapped garbage — which does not raise, because any four bytes are a valid float.
    The failure would be a dense arm that ranks confidently and wrongly with nothing in any
    log. Pinning the byte order costs nothing and makes it unrepresentable.
    """
    return base64.b64encode(struct.pack(f"<{len(values)}f", *values)).decode("ascii")


def decode_vector(encoded: str, *, dimensions: int) -> tuple[float, ...] | None:
    """`encode_vector`'s inverse, or `None` for anything that is not exactly `dimensions`.

    **NONE RATHER THAN A RAISE, BECAUSE THE CALLER IS A PHONE CALL.** A truncated object, a
    pack whose declared width disagrees with what is stored, a field somebody hand-edited:
    all of them mean this entry has no usable vector, which is a state the dense arm already
    has (an entry without one is simply unreachable by it). An exception here would travel up
    through `load_session_knowledge`, which promises never to raise, and would cost the call
    its whole LEXICAL arm as well over one bad row.
    """
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(raw) != dimensions * 4:
        return None
    return struct.unpack(f"<{dimensions}f", raw)


#: WHAT THE TOOL ANSWERS, AND WHY IT IS FOUR WORDS RATHER THAN A LIST OF CHUNKS.
#:
#: The alternative — hand the model whatever ranked nearest and let it decide — has no
#: state in which the agent KNOWS IT DOES NOT KNOW. That is the state that matters on a
#: phone call: a store that is unreachable degrades into a model answering from its own
#: weights, in a client's name, about that client's business. Hard rule 5 makes an agent
#: answer truthfully about being an AI; this is the same posture extended to the client's
#: facts, and it is only expressible if the refusal has a NAME.
#:
#:   found                    answer ONLY from the passages returned
#:   not_found                say it is unavailable and offer a callback
#:   ambiguous                ask one clarifying question — do not guess between them
#:   temporarily_unavailable  say it cannot be verified right now; never improvise
#:
#: `not_found` and `temporarily_unavailable` are deliberately NOT one value. The first is
#: knowledge about the corpus ("we do not publish that"), the second is knowledge about
#: ourselves ("we cannot see the corpus"). A client hearing the first is being told a fact;
#: a client hearing the second is being told about an outage, and only one of those should
#: page anybody.
RetrievalOutcome = Literal["found", "not_found", "ambiguous", "temporarily_unavailable"]


class PackEntry(BaseModel):
    """One searchable unit: the chunk's own words, and the English gloss that finds them.

    `gloss` is the load-bearing field and it is not a translation for the caller's benefit
    — the agent answers in Telugu either way. It is a RETRIEVAL KEY, measured:
    `docs/evidence/telugu-embedding-quality.md` §4 records lexical BM25 scoring **0.042**
    against a Telugu-script corpus and **0.625** against an English one, on the Tenglish
    queries Sarvam's STT actually returns. The gloss is what turns the first number into
    the second.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: UUID
    document_id: UUID
    #: Which revision of the document this text came from, so an answer given on a call can
    #: be traced to the exact words that were published when it was given.
    document_version: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=4000)
    #: `None` where no gloss was produced. The entry is still searchable by its own words —
    #: which is the right answer for a corpus already written in English.
    gloss: str | None = Field(default=None, max_length=4000)
    #: This entry's passage vector, base64 of little-endian float32 (`encode_vector`), at
    #: the pack's declared `embedding_dimensions`. **v2, AND OPTIONAL EVEN THERE.**
    #:
    #: `None` on every v1 entry, on every pack built by a deployment that has no Gemini
    #: credential or no attested embedding price (`apps/api/kb/pack_vectors.py` — hard rule
    #: 7's pre-flight is asked BEFORE the provider is called, never after), and on any single
    #: entry a batch failed to embed. All three are the same fact to the reader: this entry
    #: is not reachable by the dense arm, and the lexical arm is unaffected.
    #:
    #: **WHAT IT IS A VECTOR OF IS THE SAME TEXT THE LEXICAL ARM INDEXES** — the entry's own
    #: words plus the English gloss — and not the gloss alone. The gloss is a retrieval key
    #: written for a WORD-MATCHING arm (`voice_worker/knowledge.py`'s module docstring has
    #: the 0.042 / 0.625 measurement it was written for); a dense model reads the source
    #: language directly, so throwing the client's own words away before embedding them
    #: would discard exactly the capability this arm was added for.
    vector_f32_b64: str | None = None


class KnowledgePack(BaseModel):
    """Everything one agent knows, frozen. Immutable, content-addressed, ~KB not MB.

    `content_sha256` IS the version: it is computed over the entries, so two packs with the
    same id are the same bytes and a cache keyed on it cannot be wrong. `built_at` is
    deliberately OUTSIDE the hash — a rebuild that changes nothing must not mint a new id,
    or every republish would invalidate every warm container for no reason.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    format_version: int = PACK_FORMAT_VERSION
    tenant_id: UUID
    agent_id: UUID
    #: The id. Derived by `digest()`; never supplied by a caller who could get it wrong.
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    built_at: datetime
    #: Which model produced every `PackEntry.vector_f32_b64` here, spelled as the WIRE spells
    #: it, and `None` when the pack carries no vectors at all.
    #:
    #: **IT IS IN THE DIGEST AND THE VECTORS ARE NOT** — the module docstring argues the
    #: whole trade. The short form: the floats are derived from (text, model, width), all
    #: three of which are hashed, and whether the vendor is bit-deterministic is UNVERIFIED;
    #: hashing a possibly-nondeterministic derivation would churn every warm container on a
    #: rebuild that changed nothing, while hashing the DECLARATION keeps the one property
    #: that matters — a pack embedded under a different model is a different pack.
    embedding_model: str | None = None
    #: How many float32 each vector holds. `None` exactly when `embedding_model` is.
    #:
    #: STORED RATHER THAN INFERRED FROM THE FIRST VECTOR'S LENGTH, because a reader that
    #: inferred it could not notice a truncated field: it would decode whatever was there at
    #: whatever width that implied and compare it against the query. Declaring the width is
    #: what makes `decode_vector` a CHECK rather than a parse.
    embedding_dimensions: int | None = Field(default=None, ge=1)
    entries: tuple[PackEntry, ...] = ()

    @model_validator(mode="after")
    def _embedding_declaration_is_whole(self) -> KnowledgePack:
        """The two embedding fields are one fact and must arrive together or not at all.

        A pack declaring a model with no width cannot be decoded; a pack declaring a width
        with no model cannot be compared against a query vector, because nothing says which
        encoder that query has to come from. Both are made unrepresentable here rather than
        handled at every reader.

        A vector on an entry with NO declaration is refused for the sharper version of the
        same reason: every reader would silently ignore it, which is a corpus that LOOKS
        embedded and is not — and a retrieval arm that quietly does not run is the failure
        mode this whole contract is shaped to avoid.
        """
        if (self.embedding_model is None) != (self.embedding_dimensions is None):
            raise ValueError(
                "embedding_model and embedding_dimensions are one declaration: set both "
                "(a pack with vectors) or neither (a pack without)"
            )
        if self.embedding_model is None and any(e.vector_f32_b64 for e in self.entries):
            raise ValueError(
                "this pack carries entry vectors but declares no embedding_model, so no "
                "reader could tell which encoder a query would have to come from"
            )
        return self

    @staticmethod
    def digest(
        tenant_id: UUID,
        agent_id: UUID,
        entries: tuple[PackEntry, ...],
        *,
        embedding_model: str | None = None,
        embedding_dimensions: int | None = None,
    ) -> str:
        """The content hash, over canonical JSON of the tenant, agent, entries and encoder.

        SORTED BY `chunk_id`, because a SELECT without an ORDER BY may return rows in any
        order and a hash that depends on row order would mint a new pack id for identical
        knowledge — invalidating every warm cache on a rebuild that changed nothing.
        `sort_keys` and tight separators for the same reason one layer down.

        **`vector_f32_b64` IS EXCLUDED FROM EVERY ENTRY AND THE ENCODER'S NAME IS INCLUDED.**
        The module docstring carries that argument in full; it is the same argument that puts
        `built_at` outside the hash, applied to the one other field whose bytes can change
        while the knowledge does not. The exclusion is written as a `del` on the dumped row
        rather than as `model_dump(exclude=...)` so that a FUTURE field is hashed by default
        and has to be argued out here — the safe direction, since a field wrongly hashed
        costs a cache miss and a field wrongly omitted costs an id two corpora can share.
        """
        dumped: list[dict[str, object]] = []
        for entry in sorted(entries, key=lambda e: str(e.chunk_id)):
            row = entry.model_dump(mode="json")
            del row["vector_f32_b64"]
            dumped.append(row)
        payload = {
            "format_version": PACK_FORMAT_VERSION,
            "tenant_id": str(tenant_id),
            "agent_id": str(agent_id),
            "embedding_model": embedding_model,
            "embedding_dimensions": embedding_dimensions,
            "entries": dumped,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


#: The one spelling of the prefix, shared by the builder, the parser, the collector and
#: `infra/object-lifecycle/apply_lifecycle.PACKS_PREFIX` (which cannot import this package
#: — it is a standalone operator script — and is pinned against it by
#: `tests/object_lifecycle_test.py` instead).
PACK_OBJECT_PREFIX: Final = "knowledge-packs/"
_PACK_OBJECT_SUFFIX: Final = ".json"


def pack_object_key(tenant_id: UUID, agent_id: UUID, content_sha256: str) -> str:
    """Where the pack lives in object storage.

    TENANT FIRST, so a bucket policy or a lifecycle rule can be written per tenant without
    parsing anything. The digest last and in the NAME rather than a version marker, because
    an immutable object needs no versioning from the store — a new pack is a new key, and
    the old one stays readable for any call still holding it.
    """
    return f"{PACK_OBJECT_PREFIX}{tenant_id}/{agent_id}/{content_sha256}.json"


def parse_pack_object_key(key: str) -> tuple[UUID, UUID, str] | None:
    """`(tenant_id, agent_id, content_sha256)` for a key this module wrote, else `None`.

    THE INVERSE OF `pack_object_key`, AND IT LIVES HERE FOR THAT REASON ALONE. The
    collector (`apps/workers/pack_gc.py`) deletes on the strength of what a key means, so
    the parse and the build must be one author's answer: a second spelling that agreed
    about today's keys and disagreed about some edge would either strand objects for ever
    or, far worse, attribute one agent's pack to another agent's reference set.

    **`None` IS A REFUSAL, NOT AN ERROR, AND THE ONE CALLER MAY NEVER DELETE ON IT.** An
    unparseable key under our prefix is something in our bucket that this function did not
    write; it is reported and left alone. Strictness is the whole value — the UUIDs are
    parsed rather than pattern-matched, and the digest must be exactly 64 lowercase hex
    characters, which is what `ck_agents_knowledge_pack_sha256_hex` already requires of the
    column the key is compared against (migration `b5d3a91e7c64`). A looser parse would let
    `.../deadbeef.json.bak` read as a pack.
    """
    if not key.startswith(PACK_OBJECT_PREFIX) or not key.endswith(_PACK_OBJECT_SUFFIX):
        return None
    body = key[len(PACK_OBJECT_PREFIX) : -len(_PACK_OBJECT_SUFFIX)]
    parts = body.split("/")
    if len(parts) != 3:
        return None
    raw_tenant, raw_agent, digest = parts
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        return None
    try:
        tenant_id = UUID(raw_tenant)
        agent_id = UUID(raw_agent)
    except ValueError:
        return None
    # `UUID("...")` accepts braces, urn: prefixes and stray hyphens, so a key that parses
    # is not yet a key WE wrote. Round-tripping is the only check that proves it.
    if pack_object_key(tenant_id, agent_id, digest) != key:
        return None
    return tenant_id, agent_id, digest
