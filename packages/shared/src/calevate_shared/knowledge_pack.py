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

NO VECTORS IN VERSION 1, AND THAT IS A MEASUREMENT RATHER THAN AN OMISSION. The dense arm
needs a query vector, and a query vector in-call needs a local encoder. Measured on an
Intel Xeon @ 2.10GHz (AVX-512, 4 cores), GEMM-only floor at `seq_len=32`:

    threads   bge-base (12L/768)   MiniLM-L6 (6L/384)
    1              78.7 ms              9.3 ms
    2              43.7 ms              5.0 ms
    4              25.6 ms              3.2 ms

The worker shares those cores with STT, TTS, VAD and smart-turn, so 1-2 threads is the real
budget — which rules out `bge-base` against a 100ms turn. And `bge-base-en-v1.5` is exactly
the model `docs/evidence/telugu-embedding-quality.md` found BEST on our query form (0.667 /
0.750 on Tenglish, beating multilingual-e5-large). The best dense arm is the one we cannot
afford in-call, and the affordable one has no Telugu number at all.

So version 1 carries TEXT ONLY and the lexical arm carries the search. That is not a
downgrade from a working dense arm — it is the arm the English gloss was written for, and
it needs no model, no download and no inference. Adding vectors later is a format version
bump, not a redesign.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "PACK_FORMAT_VERSION",
    "KnowledgePack",
    "PackEntry",
    "RetrievalOutcome",
    "pack_object_key",
]

#: Bumped when the on-the-wire shape changes. A worker that does not understand a version
#: must REFUSE the pack (`temporarily_unavailable`) rather than parse it partially — a
#: half-understood corpus is worse than none, because the agent cannot tell it is missing
#: knowledge it thinks it has.
PACK_FORMAT_VERSION: Literal[1] = 1


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
    entries: tuple[PackEntry, ...] = ()

    @staticmethod
    def digest(tenant_id: UUID, agent_id: UUID, entries: tuple[PackEntry, ...]) -> str:
        """The content hash, over canonical JSON of the tenant, agent and entries.

        SORTED BY `chunk_id`, because a SELECT without an ORDER BY may return rows in any
        order and a hash that depends on row order would mint a new pack id for identical
        knowledge — invalidating every warm cache on a rebuild that changed nothing.
        `sort_keys` and tight separators for the same reason one layer down.
        """
        payload = {
            "format_version": PACK_FORMAT_VERSION,
            "tenant_id": str(tenant_id),
            "agent_id": str(agent_id),
            "entries": [
                entry.model_dump(mode="json")
                for entry in sorted(entries, key=lambda e: str(e.chunk_id))
            ],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


def pack_object_key(tenant_id: UUID, agent_id: UUID, content_sha256: str) -> str:
    """Where the pack lives in object storage.

    TENANT FIRST, so a bucket policy or a lifecycle rule can be written per tenant without
    parsing anything. The digest last and in the NAME rather than a version marker, because
    an immutable object needs no versioning from the store — a new pack is a new key, and
    the old one stays readable for any call still holding it.
    """
    return f"knowledge-packs/{tenant_id}/{agent_id}/{content_sha256}.json"
