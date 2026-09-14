"""What one in-call knowledge lookup actually costs, and what a real pack actually weighs.

**WHY THIS FILE EXISTS: THE NUMBER WAS QUOTED IN THREE PLACES AND REPRODUCIBLE IN NONE.**
`0.501 ms p50` travelled from an ad-hoc run into `voice_worker/session.py`,
`docs/PIPECAT-MIGRATION.md` §8.1 and decision D-599, and no harness in `tests/` or
`scripts/` could produce it again. Hard rule 11 calls that a REPORTED figure being re-stated
as fact — the same shape as the retirement date in `model_lifecycle.py` that the rule was
written for. So the measurement is committed here, with its corpus, and the figures those
three places carry are now this file's rather than a past session's.

`tests/retrieval_latency_test.py` is the pattern followed — measure, print, caveat, assert
only properties — and `tests/ack_harness.py` is the estimator, so a lookup number and an ack
number remain comparable. A second percentile implementation is how two measurements of one
system stop being about the same thing.

**MEASURED HERE, 14 Sep 2026**, on the development container (Intel Xeon @ 2.10GHz, 4 vCPU,
shared with everything else running on it) — n=500 warm sequential samples per row after 25
discarded warm-ups, over a 400-entry synthetic pack, via the real `SessionKnowledge.search`:

    | row                          | p50 (ms) | p95 (ms) | max (ms) |
    |------------------------------|----------|----------|----------|
    | `found` (query hits an entry)|   0.31   |   0.34   |   1.58   |
    | `not_found` (nothing matches)|   0.06   |   0.07   |   0.09   |
    | index build (n=30, off-turn) |  12.39   |  12.52   |  12.62   |

**A CONTENDED BOX, so these are upper bounds, and they move by tens of percent between runs
on this machine alone** — two further runs of the identical harness gave `found` p50 0.27 /
p95 0.30 and p50 0.34 / p95 0.51. The `max` column is the tell: 1.58 ms against a 0.34 ms
p95 is one sample that waited for the scheduler, not a slow lookup. Re-run with `-s` to
print the distribution of the run in front of you; that, and not the table, is the number
for the machine you are on.

**WHAT THIS SAYS ABOUT THE PUBLISHED 0.501 ms.** It is the same order of magnitude and it is
not reproducible: it named no corpus, no sample count and no machine, so nothing can be
compared against it. An independent re-measurement on this container (400-entry synthetic
pack, n=500) reported p50 0.221 / p95 0.305 / max 8.46 — also the same order, also from a
different corpus. Three runs agreeing on the order and on nothing else is exactly what an
uncommitted benchmark produces. The claim that survives all three, and the only one the
call path needs, is the one asserted below: a lookup is TWO ORDERS OF MAGNITUDE inside the
100 ms in-call budget, and it costs no network.

The measured path INCLUDES the operator log line `search` emits, because that is the path a
turn runs. Its cost was separately below the run-to-run noise of the lookup itself.

**NO MILLISECOND FIGURE IS ASSERTED AS A THRESHOLD**, for `tool_endpoint_budget_test.py`'s
reason: a latency bound on a shared runner measures the runner, flaps, and is eventually
deleted along with the guarantee it carried. What IS asserted is a ratio so large that no
contention this box can produce reaches it, plus one ordering that is a property of the
index rather than of the clock.

**AND THE PACK SIZE, which was arithmetic in a docstring until now.** `docs/PIPECAT-
MIGRATION.md` §8.1a and `calevate_shared.knowledge_pack`'s docstring both state ~16 KB per
3072-dimension entry and ~5 MB at a few hundred entries. Measured against a real serialised
pack (`model_dump_json().encode()`, the exact bytes `kb/pack.publish_pack` uploads), 300
entries at 3072 dimensions: **5,003,292 bytes — 16,678 B per entry, of which 16,382 B is the
base64 vector.** The arithmetic was right. The JSON-decimal alternative it was compared
against is 63,775 bytes for one vector, so the encoding choice is worth ~3.9x, not a guess.

**WHAT THIS FILE DOES NOT AND CANNOT MEASURE**, stated so nobody reads a green run as
covering it:

* `voice_worker/storage.PACK_FETCH_BUDGET_S` (2.0 s) — **UNMEASURED.** Nobody has timed a
  fetch from a Pipecat Cloud `ap-south` container to the bucket, and this container is
  neither. It is labelled an assumption where it lives and stays labelled.
* `voice_worker/embedding.EMBED_BUDGET_S` (1.2 s) — **UNMEASURED.** The only timings anyone
  has are through this container's egress proxy against an invalid key, which exercises TLS
  and a 4xx rather than the embedding.
* The 100 ms in-call budget itself, which is END-TO-END from the caller and has no part that
  can be produced in-process — `scripts/pilot/latency.py` refuses the same fold.
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final
from uuid import UUID, uuid5

import pytest
from calevate_shared.knowledge_pack import KnowledgePack, PackEntry, encode_vector
from tests import ack_harness
from voice_worker.knowledge import LexicalIndex, SessionKnowledge

#: TRD §6.2's in-call retrieval budget, restated rather than imported for
#: `retrieval_latency_test.py`'s reason (there is nothing to import — it lives in prose).
IN_CALL_BUDGET_MS: Final[float] = 100.0

#: The margin the one latency assertion below demands: a lookup must come in at least this
#: many times inside the budget. Measured headroom is ~290x on `found` p95, so 10x leaves
#: room for a box an order of magnitude slower than this one before it says anything — which
#: is the point. A tighter ratio would be a millisecond threshold wearing a ratio's clothes.
BUDGET_SAFETY_FACTOR: Final[float] = 10.0

#: The size the published figure was about (D-599: "MEASURED on a 400-entry pack"), kept so
#: this harness answers the same question rather than a neighbouring one.
LOOKUP_CORPUS_ENTRIES: Final[int] = 400

#: The size the pack-weight claim is about (`knowledge_pack.py`: "a few-hundred-entry pack
#: ... ~5 MB"), and the width `embedding.EMBEDDING_DIMS` declares.
PACK_SIZE_ENTRIES: Final[int] = 300
EMBEDDING_DIMENSIONS: Final[int] = 3072

#: Warm samples per row, and the warm-ups thrown away. `ack_harness.measure_sequential`'s
#: discipline, applied to a callable that is not an HTTP request: the first calls fault in
#: the tokeniser's compiled regexes and the combining-mark table, and a cold sample inside a
#: warm distribution moves the max by an amount nobody can separate out afterwards.
SAMPLES: Final[int] = 500
WARMUP: Final[int] = 25

#: A fixed namespace, so ids are derived rather than typed and two runs build byte-identical
#: packs. Same discipline (and shape) as `tests/in_call_retrieval_recall_test.py`.
_NS: Final[UUID] = UUID("0199c0de-0000-7000-8000-0000000000bb")

#: Syllables the entry names are built from. Coined rather than drawn from a word list so
#: that each entry owns a token no other entry has — which is what makes a query land on ONE
#: entry and the row above measure `found` rather than a shrug. Ordinary shop facts, no
#: vertical: a corpus about one industry would also be a corpus about its vocabulary.
_SYLLABLES: Final[tuple[str, ...]] = (
    "ba", "chi", "du", "ga", "he", "ja", "ko", "la",
    "mi", "na", "pu", "ra", "se", "ta", "vi", "ya",
)  # fmt: skip

_TOPICS: Final[tuple[str, ...]] = (
    "delivery slots",
    "UPI payments",
    "parking passes",
    "gift wrapping",
    "bulk orders",
    "returns",
    "warranty cards",
    "installation visits",
    "store timings",
    "tailoring",
)


def _counter_name(position: int) -> str:
    """A unique three-syllable name per position, deterministic in `position`."""
    return (
        _SYLLABLES[position % 16]
        + _SYLLABLES[(position // 16) % 16]
        + _SYLLABLES[(position // 256) % 16]
    )


def _entries(count: int, *, dimensions: int | None = None) -> tuple[PackEntry, ...]:
    """`count` entries of plausible shop knowledge, optionally carrying passage vectors.

    The vectors are RANDOM and that is correct for both things they are used for here: the
    serialised size of a float32 is the same whatever it holds, and nothing in this file
    ranks by them. A real embedding would make the file depend on a vendor it must not.
    """
    numbers = random.Random(7)
    built: list[PackEntry] = []
    for position in range(count):
        name = _counter_name(position)
        built.append(
            PackEntry(
                chunk_id=uuid5(_NS, f"chunk:{position}"),
                document_id=uuid5(_NS, f"doc:{position}"),
                document_version=1,
                text=(
                    f"The {name} counter handles {_TOPICS[position % len(_TOPICS)]} for the "
                    f"{name} branch. Ask at the {name} desk between ten and six on working "
                    f"days."
                ),
                gloss=None,
                vector_f32_b64=(
                    None
                    if dimensions is None
                    else encode_vector(tuple(numbers.uniform(-1.0, 1.0) for _ in range(dimensions)))
                ),
            )
        )
    return tuple(built)


def _pack(entries: tuple[PackEntry, ...], *, embedding_model: str | None = None) -> KnowledgePack:
    tenant_id = uuid5(_NS, "tenant")
    agent_id = uuid5(_NS, "agent")
    dimensions = None if embedding_model is None else EMBEDDING_DIMENSIONS
    return KnowledgePack(
        tenant_id=tenant_id,
        agent_id=agent_id,
        content_sha256=KnowledgePack.digest(
            tenant_id,
            agent_id,
            entries,
            embedding_model=embedding_model,
            embedding_dimensions=dimensions,
        ),
        built_at=datetime(2026, 9, 14, tzinfo=UTC),
        embedding_model=embedding_model,
        embedding_dimensions=dimensions,
        entries=entries,
    )


def _session(pack: KnowledgePack) -> SessionKnowledge:
    """A loaded session over `pack`, built the way `load_session_knowledge` builds one.

    Constructed directly rather than through the loader because the loader's job is the
    fetch and the cache, and neither is on the per-turn path this file times.
    """
    return SessionKnowledge(
        tenant_id=pack.tenant_id,
        agent_id=pack.agent_id,
        pack=pack,
        index=LexicalIndex(pack.entries),
        requested_digest=pack.content_sha256,
    )


def _measure(operation: Callable[[int], object], n: int, *, warmup: int) -> dict[str, float]:
    """`n` warm samples of `operation`, taking the iteration number so each can differ.

    A DIFFERENT query per sample, on purpose: repeating one question would measure the CPU
    cache holding one posting list warm, which is not what a call does.
    """
    for index in range(warmup):
        operation(index)
    samples: list[float] = []
    for index in range(n):
        started = time.perf_counter()
        operation(index)
        samples.append((time.perf_counter() - started) * 1000)
    return ack_harness.distribution(samples)


def test_one_in_call_lookup_is_measured_and_orders_of_magnitude_inside_the_budget(
    capsys: pytest.CaptureFixture[str],
) -> None:
    entries = _entries(LOOKUP_CORPUS_ENTRIES)
    session = _session(_pack(entries))

    def found_query(index: int) -> None:
        name = _counter_name(index % LOOKUP_CORPUS_ENTRIES)
        answer = session.search(f"what does the {name} counter handle")
        assert answer.outcome == "found", (name, answer.outcome)

    def missing_query(index: int) -> None:
        # A name no entry carries (the `zz` suffix is not a token in this corpus), asked in
        # a full sentence so the tokeniser does the same work it does on a real question.
        answer = session.search(
            f"does the {_counter_name(index)}zz kiosk sell umbrellas on sundays"
        )
        assert answer.outcome == "not_found", answer.outcome

    found = _measure(found_query, SAMPLES, warmup=WARMUP)
    missing = _measure(missing_query, SAMPLES, warmup=WARMUP)
    # Off the turn entirely — it happens once, at session start, while the phone is ringing.
    # Reported so the "build once, search many" split has a number on both sides; n is small
    # because each sample walks the whole corpus.
    build = _measure(lambda _: LexicalIndex(entries), 30, warmup=3)

    for label, distribution in (("found", found), ("not_found", missing), ("build", build)):
        ack_harness.assert_well_formed(label, distribution)

    # PROPERTY, NOT MEASUREMENT (1): a query whose terms are in no posting list never enters
    # the scoring loop at all, so it cannot cost more than one that does. True at any clock
    # speed, and it is the assertion that would catch a "cheap" refusal path quietly growing
    # a scan — which is the shape of regression this arm is actually exposed to.
    assert missing["p50"] <= found["p50"], (missing, found)

    # PROPERTY, NOT MEASUREMENT (2): the ratio, never the millisecond. See the module
    # docstring for why `BUDGET_SAFETY_FACTOR` is 10 and not something that looks tighter.
    ceiling = IN_CALL_BUDGET_MS / BUDGET_SAFETY_FACTOR
    assert found["p95"] < ceiling, (
        f"a lookup at p95 {found['p95']}ms is no longer an order of magnitude inside the "
        f"{IN_CALL_BUDGET_MS:.0f}ms in-call budget — measure the box before editing this"
    )

    with capsys.disabled():
        print(f"\n  in-call lookup, {LOOKUP_CORPUS_ENTRIES}-entry pack. Budget", end=" ")
        print(f"{IN_CALL_BUDGET_MS:.0f}ms, for scale only:")
        print(f"  search -> found      : {found}")
        print(f"  search -> not_found  : {missing}")
        print(f"  LexicalIndex build   : {build}  (once per session, off the turn)")


def test_a_real_serialised_pack_at_3072_dimensions_weighs_what_the_docs_claim(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The bytes `kb/pack.publish_pack` uploads, weighed rather than derived.

    Both figures this pins were arithmetic in prose: ~16 KB per entry and ~5 MB for a
    few-hundred-entry pack. Arithmetic is not a measurement — it silently omits the JSON
    scaffolding, the text, the ids — so what is weighed here is `model_dump_json().encode()`,
    which is exactly what the writer hands the store.
    """
    with_vectors = _pack(
        _entries(PACK_SIZE_ENTRIES, dimensions=EMBEDDING_DIMENSIONS),
        embedding_model="models/gemini-embedding-001",
    )
    without_vectors = _pack(_entries(PACK_SIZE_ENTRIES))

    dense_bytes = len(with_vectors.model_dump_json().encode())
    lexical_bytes = len(without_vectors.model_dump_json().encode())
    per_entry = dense_bytes / PACK_SIZE_ENTRIES
    vector_bytes = (dense_bytes - lexical_bytes) / PACK_SIZE_ENTRIES

    # One vector rendered the way the rejected design would have rendered it. Recomputed
    # rather than quoted, so the ~3.9x the encoding buys is re-derived on every run.
    numbers = random.Random(7)
    as_decimals = len(
        json.dumps([numbers.uniform(-1.0, 1.0) for _ in range(EMBEDDING_DIMENSIONS)]).encode()
    )

    # PROPERTY: base64 float32 is 4 bytes per dimension before encoding and 4/3 of that
    # after, which is arithmetic that cannot drift — asserted so a future format change to
    # the vector field cannot pass this file silently.
    assert round(vector_bytes) == 16382, vector_bytes
    # PROPERTY: the encoding choice `knowledge_pack.py` argues for is worth at least 3x. The
    # exact ratio is a measurement and is printed; that it is large is the design claim.
    assert as_decimals > 3 * (EMBEDDING_DIMENSIONS * 4 * 4 / 3), as_decimals
    # PROPERTY: a pack of this size fits in a few MB, which is the premise
    # `PACK_FETCH_BUDGET_S` rests on. Loose by design — it is a sanity bound on the format,
    # not a size budget, and there is no measured fetch to set one against.
    assert dense_bytes < 16_000_000, dense_bytes

    with capsys.disabled():
        print(f"\n  serialised pack, {PACK_SIZE_ENTRIES} entries @ {EMBEDDING_DIMENSIONS}d:")
        print(f"  with vectors (v2)    : {dense_bytes:,} B  ({dense_bytes / 1e6:.3f} MB)")
        print(f"  without vectors (v1) : {lexical_bytes:,} B")
        print(f"  per entry            : {per_entry:,.0f} B, of which {vector_bytes:,.0f} B")
        print(f"  same vector as JSON  : {as_decimals:,} B  ({as_decimals / 16384:.1f}x)")
