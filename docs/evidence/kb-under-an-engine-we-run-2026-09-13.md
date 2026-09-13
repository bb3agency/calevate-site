# The knowledge base under an engine we run

**Date:** 13 September 2026. **Status:** EVIDENCE. It answers three questions and
deliberately decides none of them — two are the founder's, and the third needs a
measurement nobody has taken.

## 0. What this is built on

| Input | What it establishes | Class |
|---|---|---|
| `pipecat-ai==1.10.0` source, clone at `f67c18af` | Pipecat ships no knowledge base | VERIFIED-OSS |
| `docs/TRD.md` §6 + the 15 Aug 2026 measurement | The server half of the 100ms budget, and what is still unmeasured | MEASURED / UNKNOWN |
| D-33, D-354, D-502, D-28 (`docs/ROADMAP.md` §6) | Where in-call retrieval stands and why | DECISION |
| `docs/evidence/kb-retrieval-bakeoff.md` §5.2 | The store bake-off D-502 adopted | VERIFIED-OSS |
| Founder-supplied research, 13 Sep 2026 | The Qdrant proposal and the retrieval contract | THIRD-PARTY |

## 1. THE FINDING THAT FORCES THE QUESTION

**Pipecat has no knowledge base, and this is read from source rather than from a
documentation index.** In the pinned 1.10.0 tree, `src/pipecat/services/` contains one
directory that is memory-shaped — `mem0`, a third-party *conversational memory* vendor,
not a document store — and the only file in the entire source naming `knowledge_base` is
`services/heygen/api_interactive_avatar.py`, an avatar API. There is no ingestion, no
chunking, no embedding, no vector store and no retrieval processor.

That is not a gap in Pipecat. Pipecat is a pipeline framework; a KB is an application
concern. But it means **the thing D-31 rented along with the engine does not exist on the
other side of this migration**, and every KB question this product had settled by pointing
at a vendor is now ours to answer.

## 2. WHERE OUR KB ACTUALLY STANDS, WHICH IS NOT WHERE MOST PEOPLE THINK

Three facts, all repo-internal and all verifiable, and the third surprises people:

1. **The ingestion and store side is already ours and already built.** `kb_sources`,
   `kb_documents`, `kb_uploads`, `kb_chunks`, `kb_models` and `kb_retrieval_logs` exist;
   `kb_chunks` is pgvector in the Postgres we already run, back up and drill (D-502,
   reversing D-28's managed-service half).
2. **The port the research proposes already exists.** Its suggested `KnowledgeStore`
   Protocol is `calevate_shared.retrieval.RetrievalProvider`
   (`packages/shared/src/calevate_shared/retrieval.py:247`), reached through
   `apps/api/retrieval/service.get_retriever` (`:51`), with a capability selector beside
   it. D-502's own text says those two exist precisely "to keep to one adapter" when the
   store changes. A second abstraction would be the defect the quality bar names — two
   ways of doing one thing, both working.
3. **T3 — cold retrieval during a call — ALREADY HAS NO HOME AT ALL.** `docs/TRD.md`
   states it plainly: D-33 kept T3 out of our layer, and **D-354 then closed the engine's
   own route too**. What remains on the audio path is T0, a static block compiled from the
   client's own facts into the prompt, and nothing else.

Point 3 is the one that reframes the whole question. The research document proposes
building an in-call KB "so it works like Bolna's". **We were not using Bolna's.**

## 3. QUESTION ONE — does in-call retrieval move into the worker?

### What D-33 and D-502 actually rested on

D-502's ground for leaving in-call retrieval alone was explicit, and it was **not** that
the store is slow:

> Not because the store is slow (it is not) but because it was never the binding
> constraint: the voice pipeline already misses its own target by 100ms with ZERO
> retrieval in it, **the engine→endpoint hop is India↔us-east-1 and has never been
> measured**, and both of those are identical for every candidate store.

Both halves of that ground are changed by this migration, and one is deleted outright.

**The engine→endpoint hop is the thing that disappears.** It existed because the
orchestrator ran in `us-east-1` and our tool endpoint ran in India, so an in-call
retrieval was an ocean round trip inside a 100ms budget. Under D-592 the conversation loop
runs in **our own container** — `apps/voice-worker/`, on Pipecat Cloud `ap-south` — and a
retrieval is a function call, or at worst a query to a database in the same region. The
"+150–400ms" estimate D-33 was written against is an estimate of a hop that no longer
exists in that form.

### What is measured, and what is not

The server half of the budget **has** been measured (15 Aug 2026, `tests/tool_endpoint_
budget_test.py`, against the real handler and real Redis, nothing stubbed):

| in flight | 1 | 8 | 24 | 96 | 250 |
|---|---|---|---|---|---|
| ack p50 (ms) | 0.9 | 6.3 | 15.1 | 48.5 | 143.0 |
| ack p95 (ms) | 0.9 | 6.8 | 17.1 | 51.1 | 187.7 |

At one call in flight: **p50 1.0ms, p95 1.4ms, max 3.8ms over n=500, reaching Postgres
zero times — 1.4% of the budget.** The cost is concurrency, not the handler: ~1,750 acks/s
per process, so 100ms arrives at roughly **175 concurrent in-flight tool calls per
process**, which is a process-count question rather than a latency one.

**The round trip has never been measured.** Pilot gate 8
(`scripts/pilot/knowledge.py::custom_function_tool_call_budget`) is still NOT RUN. So the
quantity D-33 turned on is precisely the quantity nobody has.

### What this document concludes, and what it refuses to

**The constraint that made in-call retrieval expensive is the one this migration removes,
and the measurement that would settle it has never been taken.** That is the honest
statement. It is not "move T3 into the worker" — an unmeasured hop replaced by an
unmeasured query is not progress, it is the same UNKNOWN in a new place.

What can be said without measuring: the budget's server half is 1.4% at realistic width,
the ocean is gone, and a pgvector query against the same Postgres the worker already
reaches is a plausible fit inside 100ms. What cannot: whether it *is*, on real Telugu
audio, at real concurrency, with query embedding included — and **query-embedding
generation, not vector search, is the part most likely to dominate**, which is the one
genuinely useful warning in the founder's research.

### ⚠ A guard that will NOT catch this

`tests/kb_tiers_test.py` pins in-call retrieval two ways: an EQUALITY on voice-runtime's
mounted route inventory, and a token scan for `kb_documents` / `kb_sources` /
`knowledge_base` across `apps/voice-runtime/**.py`. **Both are scoped to
`apps/voice-runtime`.** Retrieval landing in `apps/voice-worker/` — which is where it
would land — trips neither. The guard is not wrong; its subject moved. If the tier moves,
the guard must move with it in the same change, or D-33 gets reversed by accident a second
time, which is the exact failure that test exists to prevent.

## 4. QUESTION TWO — does D-502 hold, or fall?

The research recommends a **dedicated Mumbai VPS running Qdrant**, with the main server
doing no parsing, embedding, indexing or search. That is, precisely, what D-502 refuses:

> What the rule protects is "no new deployable, no new backup unit, no new restore drill,
> no new region, no new vendor" — and `pgvector` is an EXTENSION in the Postgres this repo
> already runs, backs up and drills, so `kb_chunks` adds none of those. **A managed vector
> cloud, a self-hosted Qdrant/Weaviate container, or a second database still do, and are
> still refused.**

And the founder's own condition is recorded as part of that decision: adopt pgvector now,
move to Pinecone or Weaviate **if the compute load makes it necessary once there are
clients**. There are zero clients and zero calls.

### What the research argues, fairly stated

Three arguments, and they are not empty:

1. **Colocation.** Qdrant in Mumbai beside a Mumbai worker is closer than a database
   wherever ours is. — But our Postgres is already the store, and where the worker's
   packets actually land is `pre-build-blockers` §3.6, a MEASUREMENT nobody has taken.
   Colocation is an argument about a number nobody has.
2. **Blast radius.** Ingestion CPU should not compete with the website. — True, and it is
   an argument for an ingestion worker with resource limits, which is a different change
   from a second datastore. We already run ARQ workers.
3. **Hybrid retrieval.** Dense plus sparse in one engine. — Postgres does full-text
   natively beside pgvector; this is not a reason to add a deployable.

### What would have to be true for D-502 to fall

Stated so the question can be closed with evidence rather than preference:

- A **measured** pgvector p95 (query embedding + search + serialization) that does not fit
  the in-call budget on the worker's real network path — not an estimate, and not a
  benchmark on a different dataset.
- Or a measured ingestion load that degrades the main Postgres under real client
  documents, after an ingestion worker with CPU limits has been tried.
- Or a client requirement (a DPA, a certification, an SLA) that the current store cannot
  meet.

**None of the three is currently true, and none can be made true before the first call.**
Until one is, D-502 holds, and this document does not recommend reversing it. If the
founder chooses to reverse it anyway that is a legitimate call — it should be taken as a
decision with its ground recorded, not inherited from a research summary's headline.

## 5. QUESTION THREE — the retrieval contract

This is the genuinely new idea in the research and it should be adopted whatever happens
to questions one and two, because it is about what the agent SAYS, not about where bytes
live.

A retrieval tool returns one of four states rather than a bag of chunks:

```
found                    answer only from the retrieved evidence
not_found                say it is unavailable and offer a callback
ambiguous                ask one clarifying question
temporarily_unavailable  say it cannot be verified — never improvise
```

**Why this is a compliance property and not a UX one.** The alternative — stuffing loosely
related chunks into the prompt and letting the model decide — has no state in which the
agent knows it does not know. `temporarily_unavailable` is the one that matters: a store
that is down currently degrades into a model answering from its own weights, on a phone
call, in a client's name. A named state is what lets hard rule 5's posture extend from
"answers truthfully about being an AI" to "does not invent a fact about the client's
business".

It also composes with what already exists: `RetrievalResult` is already the port's return
type, and a state enum on it is an additive change to a Protocol with one implementation.

## 6. WHAT THE RESEARCH ADDS THAT WE DO NOT HAVE

Worth taking, independent of the store question:

- **Hybrid retrieval** — vector plus full-text, for the terms embeddings lose: names,
  prices, phone numbers, Latin-transliterated Telugu.
- **Cross-language retrieval** — one canonical English corpus, queried with the original,
  normalized and transliterated forms, answered in Telugu. Avoids storing every document
  three times, which is the naive alternative.
- **Retrieval during the endpointing window** — if the caller says a keyword, retrieval
  can run *while smart turn is still waiting for them to finish*. This interlocks directly
  with the `stop_secs` work in `apps/voice-worker/voice_worker/pipeline.py`: it converts
  part of a silence budget we are already paying into useful time. It is the single
  cheapest latency idea in the document.
- **Provenance on every passage** — document id and version, so we can say which document
  supported which answer on which call.

Already ours, and named here so nobody rebuilds them: the store port, pgvector,
tenant-scoped isolation (hard rule 1 makes a model-supplied `tenant_id` structurally
impossible, not merely discouraged), and the static clinic profile in the prompt — which
is T0, already compiled and stored.

## 7. WHAT STEP 3 ALREADY SETTLED, SO IT IS NOT RE-ARGUED

`apps/api/engine/pipecat.py` (D-597) implements `attach_kb`, `detach_kb`, `list_kb` and
`list_account_kb` as **real writes and reads** against `pipecat_kb_objects` — not the
refusals the contract inventory's §9.1 predicted. So the *binding* side of the
Bolna-shaped KB contract survives the migration intact: an agent still references KB ids,
objects still outlive the agent that referenced them, and `list_account_kb` still answers
the orphan question. **Nothing about T0 changed and `tests/kb_tiers_test.py` passes
unchanged.**

What is NOT built, and is what questions one to three are about: anything that retrieves
during a call.

## 8. WHAT CLOSES EACH QUESTION

| # | Question | What closes it |
|---|---|---|
| 1 | Does in-call retrieval move into the worker? | Pilot gate 8's round-trip measurement, plus a measured pgvector p95 INCLUDING query embedding from the worker's real network position. Both need a running worker; neither needs a carrier. |
| 2 | Does D-502 hold? | One of §4's three conditions becoming true, measured. Until then it holds. A reversal on preference is the founder's to take and should be its own decision row. |
| 3 | The four-state retrieval contract | Nothing. It is additive, it is a compliance improvement, and it can be built before either other question is answered. |

**UNKNOWN, in those words.** The in-call round trip (pilot gate 8, NOT RUN). pgvector's
p95 including query embedding, from the worker (no worker has run). Where the carrier
terminates media (`pre-build-blockers` §3.6, and the founder has ruled it not a gate). None
of the three is filled with a plausible number here.
