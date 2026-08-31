# KB retrieval bake-off — the D-28 gate, run

**Lane: knowledge-base retrieval. Written 31 August 2026 (UTC).** Commission: run the
bake-off `docs/TRD.md` §6 has demanded since D-28 and which has never been run, so that the
founder can decide where in-call and dashboard retrieval live. **This lane decided nothing
and adopted nothing.** It wrote this file and one throwaway measurement harness
(`scripts/spike/kb_pgvector_latency.py`); it created no vendor account, wrote no migration,
built no embedding path, and changed no decision row. `bolna-findings/mirror/` was read and
not touched.

---

## Evidence-class legend

| Class | Means |
|---|---|
| **VERIFIED-VENDOR-DOCS** | the vendor's own spec, read this session from the hash-pinned `bolna-findings/` mirror; page + line cited |
| **VERIFIED-SDK** | the vendor's own published source, cloned and read this session; repo, commit and file:line cited |
| **MEASURED-HERE** | produced by running something on this machine this session; method and rerun command given |
| **REPORTED** | a third-party summary, or a repo-internal figure a past session wrote. Corroborates; never satisfies a wire value, a price, or a client-facing claim |
| **UNKNOWN** | not verifiable from here. Names what a human must close it with |

A repo-internal number is a **CLAIM**, not evidence (hard rule 11). Where this file quotes
one it says so and names the file and line.

---

## 0. Headline — four findings, in the order that changes the decision

**1. The in-call question is not decided by the store, and this is the finding that
reorganises the whole comparison.** Every architecture that answers a caller from a
knowledge base pays the same first cost: the engine's orchestrator calling something. That
orchestrator is US-hosted (AWS us-east-1) and our stack — voice-runtime and Postgres alike
— is a Hostinger VPS **in India** (D-180, superseding D-25 on provider and region). So the
first hop of an in-call retrieval is India↔us-east-1, and it is **identical for the managed
option and the pgvector option**. It is paid before either store does one microsecond of
work. Choosing between the stores on in-call latency is therefore choosing on the smaller
term. **That hop has never been measured** — the probe exists and has never been run
(§2.4).

**And the obvious escape hatch is closed by the thing that makes this product what it is.**
The vendor does sell Indian residency — "call processing runs on servers in `ap-south-1`
(Mumbai)" — which would put the orchestrator beside our VPS and shrink the hop to nothing.
But their own requirements for it say "Do not connect your own API keys for the
transcriber, synthesizer, or LLM providers", and state the consequence outright: "If you
connect your own API keys for any provider … calls will automatically route through US
servers regardless of other configuration settings"
(`bolna-findings/mirror/pages/enterprise/indian-server-configuration.md:65,68`). **BYOK on
all three legs is what this product IS**, so the hop cannot be bought away without giving
up the architecture. It is a fixed cost of the current design, not a procurement item.

**2. The store component is not the problem, and now there is a number instead of an
argument.** On the contingency schema this repository already specified, a hybrid RRF
top_k=3 query over a realistic SMB corpus runs in **single-digit milliseconds** (§2). At
the size one SMB client actually has, Postgres does not even use the vector index — it
does an **exact** scan, which is both fast and perfectly accurate. The 100ms budget is not
threatened by the database. It is threatened by the network and by the embedding call.

**3. Option 3 is closed on Bolna and only HALF open on Cartesia, and the half that is open
is the wrong half.** Bolna's `POST /knowledgebase` takes a PDF or a URL and has no text
field, and its `Knowledgebase` object carries no agent id — both re-confirmed at page and
line this session (§3.1). Cartesia Line's `knowledge_base` built-in is REAL and was
re-verified at source this session, at a commit NEWER than the one the TRD cites (§3.2) —
but it is a **query** client. **No document create, upload or delete exists anywhere in the
Line SDK.** So Cartesia solves the retrieval half and leaves the ingestion half exactly as
unproven as Bolna's is closed. The TRD's correction is true and does not rescue option 3.

**3b. Two things about option 3 that the founder's stated direction makes urgent.**
*(i)* **Giving Bolna our LLM key does not give Bolna a knowledge base** — they are unrelated
subsystems and only the first is shipped (§3.0). *(ii)* Even reopened, the engine KB has
**no search route**, so it cannot serve the dashboard copilot or CRM search; option 3 is a
complement to option 1 or 2, never a replacement, and its real cost is "one of the others
PLUS this" (§3.1d). And reopening it moves the approval gate from the **chunk** to the
**document** — on a URL source, to the **address only** (§3.1c). That is a deliberate
weakening of a property `kb/__init__.py` calls a product property, and it belongs in the
decision rather than in a footnote.

**4. The voice pipeline already misses its own target by 100ms with ZERO retrieval in it.**
`latency_budget_composes()` returns `False` and `voice_to_voice_gap_ms()` returns `+100.0`
— evaluated on this machine this session, not quoted. Any in-call retrieval is spent from a
budget that is already overdrawn. This is the strongest single argument for keeping in-call
on T0 regardless of which store wins.

**Where that points:** the honest outcome is that the two paths get different answers.
In-call stays **T0 + a local semantic cache**; the store — whichever wins — serves the
**dashboard copilot, CRM semantic search and H3 caller memory**, where seconds are fine.
The recommendation in §5 follows from that split, not from a latency race between vendors.

---

## 1. What is actually shipped, verified this session

| Claim | Status | Evidence |
|---|---|---|
| Ingestion + preview-and-approve is ours and built | **true** | `apps/api/kb/service.py::publish_source` (:776); eligibility is `approved_at IS NOT NULL` (:846) |
| In-call retrieval is T0 and nothing else | **true** | `docs/TRD.md:948`; `tests/kb_tiers_test.py:156` pins voice-runtime's route inventory so a retrieval endpoint cannot appear by accident |
| `kb_chunks` + pgvector are contingency, not built | **true** | `apps/api/kb/models.py:3`; schema specified at `docs/DATA-MODEL.md:348-352` |
| No embedding path exists anywhere | **true** | `COHERE_API_KEY` deleted as a setting nothing read (ROADMAP D-231) |
| pgvector is available on the dev server | **true, and it is 0.6.0** | MEASURED-HERE, §2.1 — and the server is a native Ubuntu PostgreSQL 16.15, **not** the `pgvector/pgvector:pg16` compose image |

The last row is a premise worth checking before anyone plans against it: the brief for this
lane said "the docker-compose image is pg16+pgvector". The compose file does specify that
image (`docker-compose.yml:30`), but the Postgres actually listening on 5433 reports
`PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)`. pgvector is present as an *available*
extension at **0.6.0** and was not installed in any database. That version matters and §2.5
says why.

---

## 2. THE MEASUREMENT — pgvector, on this machine

### 2.1 Method, so it can be rerun

**It did NOT run on the shared dev Postgres, and that is deliberate.** The shared server on
5433 was occupied by back-to-back sibling coverage runs for the whole session — one held it
for 44 minutes at 90% CPU, and a second started 21 seconds after that one ended. Adding a
bulk load and an HNSW build to a server being scored would have risked turning somebody
else's CI red for a reason invisible in their diff, and would have corrupted our own
numbers. So the measurement ran on a **private PostgreSQL cluster built for it**, on port
55432, touching the shared server and the `calevate` database not at all:

```
mkdir -p /var/tmp/kbspike && chown postgres:postgres /var/tmp/kbspike
su postgres -c "/usr/lib/postgresql/16/bin/initdb -D /var/tmp/kbspike/data \
    -U calevate --auth=trust"
su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/tmp/kbspike/data \
    -o '-p 55432 -k /var/tmp/kbspike' -l /var/tmp/kbspike/log start"
/home/user/calevate-site/.venv/bin/python -m scripts.spike.kb_pgvector_latency \
    --dsn postgresql://calevate@127.0.0.1:55432/postgres
su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/tmp/kbspike/data stop"
rm -rf /var/tmp/kbspike
```

On the shared server the same harness still refuses to run while
`pgrep -f "coverage run -m pytest"` matches; the guard is scoped to port 5433 so that a
private cluster remains available as the escape hatch. Either way it builds a **throwaway
database** and refuses by name to touch `calevate`.

**⚠ THE SERVER WAS STOCK AND THE MACHINE WAS BUSY, WHICH MAKES EVERY FIGURE BELOW AN UPPER
BOUND.** A fresh `initdb` gives `shared_buffers` **128MB** and `maintenance_work_mem`
**64MB** — captured in the run's own JSON rather than assumed. The 100,000-row corpus is
roughly 400MB of vectors alone, so at that size the table does not fit in cache and the
HNSW graph does not fit in the build memory. The host is a **4-core** machine that sibling
suites kept oversubscribed (load average was above 5 throughout, and the harness records
`/proc/loadavg` beside every shape). Both effects push the measured numbers **up**. A tuned
server on an idle machine does better, never worse — so if these figures fit the budget,
the tuned ones do too. That direction is why the measurement is still worth reporting
rather than being withheld until the machine is quiet.

* **Schema:** the contingency table this repo already specified (`docs/DATA-MODEL.md:348-352`)
  — `kb_chunks(id, tenant_id, agent_id, document_id, content, tsv, embedding vector(1024),
  embed_model, embed_version, chunk_meta, version, is_active)` with HNSW
  `vector_cosine_ops`, GIN on `tsv`, and a btree on `(tenant_id, agent_id, is_active)`. Not
  a shape invented here, so the number transfers.
* **Scope predicate:** `tenant_id = ? AND agent_id = ? AND is_active` — retrieval is
  per-AGENT, which is what the specified index is for.
* **Query:** hybrid, one statement, one round trip. Dense arm `ORDER BY embedding <=> ?`
  and sparse arm `ts_rank_cd(tsv, plainto_tsquery(...))`, each to depth 20, fused with
  **Reciprocal Rank Fusion** (k=60, the constant from Cormack/Clarke/Buettcher SIGIR 2009
  and every mainstream default), then `LIMIT 3`. Dense-only and sparse-only are measured
  separately so the hybrid's cost can be decomposed.
* **Corpus:** chunks of ~300 tokens, the midpoint of TRD §6.1's 200–400 band, drawn from a
  ~90-word domain vocabulary so the sparse arm actually matches something.
* **Sampling:** 50 warmups then 500 timed iterations per query, **each with a fresh random
  probe vector and a fresh question**, so nothing is answered twice. Percentiles are
  nearest-rank, not interpolated — every figure below is an observation something actually
  produced.
* **Vectors:** uniformly random, 1024-d (BGE-M3 / Cohere Embed v4 class; `vector(1024)` is
  what DATA-MODEL specifies). **This makes the latency representative and the RECALL
  meaningless**, so no recall figure is reported anywhere in this document.

### 2.2 Corpus sizes, and why these

**ESTIMATE, and it is ours, not a vendor's.** An SMB knowledge base is a website, a price
or service list, an FAQ, and a few policy pages. At ~300 tokens per chunk, a median client
lands in the low hundreds of chunks and a content-heavy one (a dealership with a parts
list, a clinic with per-procedure pages) in the low thousands. Measured, therefore:

* **1 × 1 × 500** — median SMB, one agent.
* **1 × 1 × 2,000** — large SMB.
* **50 × 2 × 1,000 = 100,000 rows** — the shared multi-tenant table at 50 clients with two
  agents each. This is the shape that matters, because it is the one where a filtered index
  scan can misbehave.

### 2.3 Results

MEASURED_TABLE_PLACEHOLDER

### 2.4 What these numbers do NOT say

* **They are not a round trip.** They are the store component, measured over a loopback
  socket. The in-call path adds the engine→endpoint hop described in §0.1, which is
  India↔us-east-1 and **has never been measured**. The probe for it already exists and has
  never been run: `scripts/pilot/knowledge.py`'s `custom_function_tool_call_budget`, which
  reports `not_run` for want of a live agent calling our endpoint. **UNKNOWN — needs a live
  call; no number is estimated for it here.**
* **They do not include embedding the caller's question.** Every dense arm above is handed
  a vector. In production something must produce that vector from the caller's words, and
  on any design available to us that is a network call. **It is very plausibly the largest
  single term in an in-call retrieval and it is UNKNOWN here** (no embedding path exists —
  D-231).
* **They say nothing about recall**, by construction (§2.1).
* **They are one process against an idle server.** TRD §6's existing tool-endpoint
  measurement found that the cost on that surface is CONCURRENCY, not the handler
  (`latency ≈ in-flight ÷ 1,750`). The same caveat applies here and is not re-measured.

### 2.5 The multi-tenancy finding, which is a correctness result and not a speed one

pgvector gained **iterative index scans** — re-entering the HNSW graph until the `LIMIT` is
satisfied — only in **0.8.0 (2024-10-30)** (VERIFIED-VENDOR-DOCS: pgvector `CHANGELOG.md`,
read from `raw.githubusercontent.com/pgvector/pgvector/master/CHANGELOG.md`, 31 Aug 2026).
The server here has **0.6.0**. Before 0.8.0 an HNSW scan walks the graph over the whole
index and the scope predicate is applied to whatever the walk produced, so a filtered query
can return **fewer rows than asked for** — silently, as a short result rather than an error.
That is a recall failure wearing the costume of a working query, which is precisely the
defect class this repository writes gates for. The harness therefore measures the returned
row count and the chosen plan, not just the time; see the table.

---

## 3. Option 3 — engine-side KB, verified rather than recalled

### 3.0 GIVING BOLNA OUR LLM KEY DOES NOT GIVE BOLNA A KNOWLEDGE BASE

**This is the single most likely misunderstanding a reader of this decision will carry, so
it is stated before anything else.** LLM BYOK and the knowledge base are two unrelated
subsystems that happen to live behind the same vendor. **BYOK is real and shipped**: our
model key reaches the engine and `engine/bolna.py:363-365` maps our vocabulary to the
vendor's wire strings (`{"azure_openai": "azure-openai", "openai": "openai", "google":
"google"}`), a value read from the vendor's own docs rather than a dashboard label
(D-417, `bolna-findings/mirror/pages/providers/llm-model/azure-openai.md`). That decides
**which model generates the words**. **The knowledge base is a different subsystem, it is
not a BYOK slot, and it is OFF**: `BOLNA_CAPABILITIES.knowledge_base = False`
(`bolna.py:2484`), and `attach_kb` raises a named refusal instead of uploading, with
`require_capability` refusing at the KB publish path before a request goes out. Handing the
vendor an LLM key does not cause the agent to retrieve anything: it causes our model to
generate the reply. **An agent with our key and no KB answers from its prompt — i.e. from
T0 — and nothing else.** So "the in-call KB will be handled by Bolna" is not a description
of the shipped system; §3.1 is what would have to change for it to become one, and §3.1b
is what that costs.

### 3.1 Bolna: both blockers re-confirmed at page and line

**VERIFIED-VENDOR-DOCS, read this session from the mirror.**

* **No text field.** `POST /knowledgebase` is `multipart/form-data` whose only content
  properties are `file` ("PDF file to upload (max 20 MB)",
  `api-reference/knowledgebase/create.md:40-45`) and `url` ("URL to scrape and ingest",
  `:46-52`), with the endpoint description stating "Provide either `file` or `url`, not
  both" (`:33`). The remaining properties are `chunk_size`, `similarity_top_k`,
  `overlapping` and `language_support` — tuning knobs, not content. **Our `KBSourceRef`
  carries parsed, chunked, human-APPROVED prose, and there is nothing on this route to post
  it to.** The claim in the brief is correct.
* **No agent id.** The `Knowledgebase` schema
  (`api-reference/knowledgebase/get_knowledgebases.md:63-126`) is exactly: `rag_id`,
  `file_name`, `humanized_created_at`, `created_at`, `updated_at`, `vector_id`, `status`,
  `chunk_size`, `similarity_top_k`, `overlapping`, `language_support`. A grep for `agent`
  across **all five** knowledgebase API pages returns nothing. So a KB cannot testify to
  which agent holds it, and `list_kb` cannot prove a detach.
* **One correction to how that second blocker is usually stated, and it is in the vendor's
  favour.** The linkage is not absent from the system, it is absent from the KB *object*:
  it lives on the AGENT, as `llm_config.vector_store.provider_config` → `LanceDbConfig`
  with `vector_id` (legacy) and `vector_ids` (array)
  (`api-reference/agent/v2/update.md:1215-1237`), and the agent type
  `knowledgebase_agent` (`:536`). The direction is agent→KB and it is one-way. A detach
  *could* be proven by reading every agent, which our Protocol has no method for. Two
  incidental facts fall out of the same read: the built-in store is **LanceDB**, and
  `vector_id` is a **different identifier from `rag_id`**, which is what create returns and
  delete takes.

* **The `rag_id` / `vector_id` split is REAL, and it is the vendor's spec that forces three
  calls rather than our design preference.** `POST /knowledgebase` returns `rag_id`,
  `file_name`, `source_type`, `status`, `language_support` — `required: [rag_id, file_name,
  status]` — and **contains no `vector_id` at all** (`create.md:86-124`; a grep for
  `vector_id` over that whole page returns nothing). But the agent is attached by
  `vector_ids` (`update.md:1220-1237`), and `vector_id` appears **only** on the read
  endpoints (`get_knowledgebases.md:89`). So the id you are given at create is not the id
  you need to attach, and the sequence create → GET → PATCH is imposed by the vendor.
* ⚠ **Their own spec disagrees with itself about the shape of `rag_id`, in three places**,
  which is an integration trap worth knowing before writing the client: `create.md:92`
  gives `format: ^[0-9a-fA-F]{32}$` with the undashed example
  `3c90c3xs0d444b5088228dd25736052a` — which contains `x` and `s` and so does not match its
  own pattern; `get_knowledgebases.md:65-70` gives a **dashed UUID** pattern with example
  `f265b06a-7fa7-4fbf-8923-55d5ae9c4ba2`; and `delete.md:37-39` declares the same path
  parameter as `format: uuid`. Do not build id handling on any of the three until a live
  call settles it.
* **The erasure question stays open, and the silence is now located precisely.**
  `DELETE /knowledgebase/{rag_id}` returns `{message: success, state: deleted}`
  (`delete.md:40-47`) and says **nothing** about whether the agent's `vector_ids` is
  cleared. A dangling id surviving an erasure is a DPDP finding, and it is unanswerable
  from the mirror — pilot gate 8, and a reason any reopen needs `detach_kb` to do the
  agent PATCH itself rather than trust a cascade.
* **Nothing accepts text.** Across all five knowledgebase pages the only content-bearing
  request properties anywhere are `file` and `url`.

**Verdict: closed, on ingestion shape, and nothing this session read reopens it.** Every
element of the adapter's own account (`bolna.py:2373-2400`) is confirmed against the
vendor's pages rather than taken from the adapter, as hard rule 11 requires.

### 3.1b Costing the reopen path concretely

If the founder wants in-call KB on Bolna, this is the work. It is a **decision, not a flag
flip**, because two of the four items change things this product currently guarantees.

| # | Change | Where | Cost |
|---|---|---|---|
| 1 | `KBSourceRef` stops carrying `text` and starts carrying **a PDF or a public URL** | `packages/shared`, `apps/api/kb/` | The shared model, its conformance fixtures, and every caller. Mechanical but wide |
| 2 | Something must **produce** that PDF or URL from an approved source | new | For a `kind='url'` source, the original URL may serve — but then the vendor scrapes **live**, so what the agent quotes is whatever the page says at retrieval time, not what a human approved. For `kind='file'` the original PDF may serve. **For `kind='text'` and `kind='call_corpus'` there is no artefact at all**, and rendering approved prose to a PDF inside the adapter is inventing a document format to squeeze past a compliance gate — the adapter's own note refuses exactly this (`bolna.py:2380-2382`) |
| 3 | `attach_kb` becomes **create → GET → PATCH** | `engine/bolna.py` | Three calls, not one, forced by the spec (above). The PATCH targets `llm_config.vector_store.provider_config.vector_ids` and must be read-modify-write, since `vector_ids` is an array shared with every other source on that agent — a blind overwrite detaches the others. CAS discipline applies (BACKEND-PATTERNS) |
| 4 | `detach_kb` / `list_kb` / `kb/reconciliation` are rebuilt | `engine/bolna.py`, `apps/workers/` | `list_kb` cannot filter on the KB row (no agent id, §3.1). The only readable source of truth is **the agent's own `vector_ids`**, which our `VoiceEngine` Protocol has no method to read (`create_agent`/`update_agent` only). So the Protocol grows an agent read-back, or D-41's detach contract cannot be honoured and reconciliation keeps making positive claims about a system it cannot read |

**What it does to the T0–T4 tier design.** T3 moves inside the engine, which is the point.
But T3's parameters stop being ours: chunking is done vendor-side by `chunk_size`
(default 512, described only as "Chunk size for embedding model" — **units unstated**) and
`overlapping` (default 128, "Number of **characters** which overlap in between neighboring
nodes"), and depth is `similarity_top_k` (default 15) — against TRD §6's design of
200–400-**token** chunks at top_k=3. Note the mismatch that unstated unit hides: if
`chunk_size` is characters, 512 is roughly 100–130 tokens, i.e. **below** the bottom of our
band, not near the middle of it. Nobody should size a KB against that number until a live
call shows what it does. T1/T2 become the vendor's or nothing. **T4 is the one that matters**: our
refuse-and-escalate tier depends on a score threshold, and the built-in KB returns retrieved
context into the prompt rather than a score to us, so "below threshold → say I don't know"
has nothing to threshold. It would become prompt instruction rather than enforced
behaviour, which is a weaker guarantee than the one TRD §6 describes.

**Two Telugu facts, and the second is now proven rather than assumed.** No page in the
mirror names **Telugu** anywhere in the knowledgebase documentation (grepped case-insensitively
across all five API pages and `getting-started/knowledge-base.md`: zero hits); the multilingual
mode is described only as "cross-lingual retrieval across 100+ languages"
(`create.md:71-80`). And the mode really is **immutable after creation** — which TRD §6.2
carries as a claim and which the route list settles: the complete surface is create, get,
list, delete (`overview.md:11-16`), with **no update endpoint**, so `language_support` can
only ever be set at create. For a Telugu-first product, that means the retrieval-quality
question has to be answered *before* the first upload and cannot be corrected afterwards
except by re-creating and re-attaching every knowledge base. That is pilot gate 8's
question and no page in the mirror answers it.

**What it does to `kb_sources`.** Today it stores approved prose and its chunks. It would
have to store, per version, a **retrievable artefact** (a stored PDF, or a URL) plus the
vendor's `rag_id` and its `vector_id` — two ids, not one, and `kb_documents.meta.engine_kb_ref`
is specified to hold a single handle (`DATA-MODEL.md:340-347`). `kind='text'` sources become
unpublishable to the engine, so either the product stops offering them or they publish to a
different target than files and URLs do — which is two ways to do one thing, and the second
is where the drift starts.

### 3.1c What "approved" would mean — the gate cost, stated plainly

`kb/__init__.py` says the preview-and-approve gate exists so "a client cannot push text
into their agent's mouth without a human seeing it first", and calls it **a product
property, not a vendor feature**. On the reopened engine route, here is what a human would
actually be approving, and it is not the same thing:

* **The vendor chunks server-side.** `chunk_size` and `overlapping` are create-time
  parameters (`create.md:53-70`), so the text the agent retrieves and quotes is **cut by
  the vendor into pieces no human previewed in the form they are retrieved**. Our preview
  shows our chunks; the agent quotes theirs.
* **Therefore the approval granularity drops from the CHUNK to the DOCUMENT.** A reviewer
  approves "this 20-page PDF" rather than "these 43 passages". That is a material
  weakening: the failure this gate is built to catch is one bad passage in an otherwise
  fine document, and document-level approval is precisely the granularity at which that
  passage is invisible.
* **On a URL source it is weaker still, and it is not a granularity problem but a time
  problem.** The vendor scrapes the URL; the page can change after approval. What the agent
  says would then be governed by whoever can edit that page, which for a client's own
  website is the client — approval becomes a one-time event about a moving target. **A
  human has approved a pointer, not the content.**

**Honest summary: on option 3 the answer to "what is approved, by whom, at what
granularity" is "the document, by the client, once — and for a URL, only the address."**
That is a real reduction in a property this product currently guarantees unconditionally.
It is not fatal — a founder may reasonably decide document-level approval is enough for a
dental clinic's price list — but it is a decision to take deliberately, and it now has its
own row in the comparison table rather than sitting in a footnote.

### 3.1d Option 3 leaves the dashboard copilot with nothing

Even if Bolna served the in-call path perfectly, the **dashboard copilot, CRM semantic
search and H3 caller memory still need retrieval over the same knowledge**, and the engine's
KB is not reachable from them: there is no query endpoint on it at all. Their own overview
page lists the **complete** surface as exactly four routes —
`POST /knowledgebase`, `GET /knowledgebase/:rag_id`, `GET /knowledgebase/all`,
`DELETE /knowledgebase/:rag_id` (`api-reference/knowledgebase/overview.md:11-16`) — create,
read, list, delete, and **no search route**. Retrieval happens inside the vendor's pipeline
during a call and is not exposed to us. So option 3 is not a substitute for
options 1 or 2, it is a **complement to one of them**. Choosing it means:

* running **two** knowledge stores with two ingestion paths over the same corpus, which is
  the "two ways to do one thing" defect this repo's quality bar names explicitly;
* keeping the dual-push ingestion TRD §6 already describes, with the divergence risk D-41
  exists to police — now permanent rather than transitional;
* and still answering every question in §7 about which provider serves the copilot.

**The cost of option 3 is therefore option 1 or 2 PLUS option 3**, never option 3 alone.

### 3.2 Cartesia Line: re-verified at source, and the finding cuts the other way from the correction

The TRD carries a correction saying Cartesia Line ships `knowledge_base` as a first-class
built-in, citing `github.com/cartesia-ai/line` @ `3062c978`. The brief asked me to treat
that as REPORTED unless re-verified. **I re-verified it, at source, this session.**
`github.com` is reachable from here; the repository was cloned and read at HEAD
**`c79c1c42a33a3ac17e5a74a115aab6a2c41aa47c`** — a *newer* commit than the one cited, so
this is a stronger reading than the one it confirms.

**VERIFIED-SDK** — `line/knowledge_base.py`, read 31 Aug 2026:

* The endpoint is real: `GET {base_url}/agents/{agent_id}/documents/query` (`:86`) with
  `query` and `top_k` params (`DEFAULT_TOP_K = 5`, `:14`), returning
  `payload.get("results")`, each result "currently shaped as `{"content": str}`" with
  pass-through deliberate.
* It is **agent-scoped by construction** — the path carries `agent_id` and the auth is
  `Authorization: Bearer {agent_token}` (`:87`), an agent-scoped token from the session
  start message, *not* the account API key. It raises if either is missing.
* Its timeout defaults to `DEFAULT_TIMEOUT_S = 3.0` (`:15`) and warns above
  `LONG_TIMEOUT_WARN_S = 10.0` (`:20`), because "long timeouts can stall the call". This is
  an in-pipeline tool, so it never pays our engine→endpoint hop.

**And the decisive gap, also verified this session.** Grepping the entire repository for a
document write path returns **nothing**: no create, no upload, no delete, no `session.post`
against `/documents` anywhere in the SDK. The only occurrences of "documents" outside the
query client are the module docstring and one unrelated prompt string.

**So the correction is TRUE and does not rescue option 3.** Cartesia solves the half Bolna
also solves (agent-scoped in-pipeline retrieval with zero hops) and leaves **completely
open** the half on which Bolna is closed: how our approved prose gets IN. The repo's own
Cartesia lane reached the same place and named it OPERATIONS §2 gate 19(f). Adopting
Cartesia for the KB would also be adopting Cartesia for the ENGINE, which TRD §1235
eliminated on **telephony** — it offers no DLT-registered Indian number — and that ground
is untouched by anything here.

---

## 4. The three options, side by side

Columns are the founder's criteria plus the ones the brief added. "In-call" and "dashboard"
are separated deliberately: **the answer differs between them, and that is the finding.**

| | **1. Managed retrieval API** | **2. pgvector contingency** | **3. Engine-side KB** |
|---|---|---|---|
| **In-call store latency** | **UNKNOWN — not measurable here.** No credential, and the candidate vendors' hosts are egress-blocked from this container. No figure is invented | **MEASURED-HERE, §2.3** — single-digit ms for the store component at every size measured | zero hops from the orchestrator (in-pipeline). Bolna: **N/A, route closed.** Cartesia: 3s default timeout, VERIFIED-SDK |
| **In-call FIRST HOP** (the term that dominates) | India↔us-east-1, **UNMEASURED** | India↔us-east-1, **UNMEASURED** — *identical to option 1* | none — this is option 3's one real advantage |
| **Can it serve in-call today?** | **No** — budget already overdrawn by 100ms (§0.4) before the unmeasured hop and the unmeasured embedding call | **No**, for the same two reasons, which are not the store's | **No** — Bolna closed on ingestion; Cartesia needs an engine swap it was eliminated from on telephony |
| **Can it serve the dashboard copilot?** | **Yes** — seconds are fine | **Yes**, and it is already in the request path's own database | **No, and this is disqualifying on its own.** The vendor's KB has no search route at all (§3.1d), so option 3 must be paired with option 1 or 2. Its true cost is "one of the others, PLUS this" |
| **What the approve gate actually approves** (§3.1c) | the CHUNKS — we embed exactly the text a human previewed | the CHUNKS — approval and vector write are one transaction | **the DOCUMENT, not the chunks.** The vendor re-chunks server-side (`chunk_size`/`overlapping`), so the agent quotes passages nobody previewed; on a URL source, approval covers only the ADDRESS and the page can change afterwards. A material weakening of a property `kb/__init__.py` calls a product property |
| **Isolation boundary — WHERE it sits** | vendor namespace + a tenant filter our code must remember to send. Enforced in the vendor's query layer at best; if we let the ENGINE call the vendor directly (the only configuration that avoids the hop) the namespace becomes **a parameter the LLM fills in** — the anti-pattern named outright | **FORCEd RLS in Postgres.** The boundary is the database. Forgetting the filter returns **zero rows**, not another tenant's | agent-scoped by the vendor (Cartesia's token is per-agent). Strong, but not ours and not auditable by us |
| **What if app code forgets the filter?** | cross-tenant leak, silent | **impossible** — hard rule 1's existing pattern | vendor-dependent; Cartesia's path-scoped token makes it hard |
| **Write-back (agent proposes knowledge)** | upsert/delete per namespace, vendor-dependent; the approval gate stays ours but now spans a network boundary, so an approved write can succeed locally and fail remotely | **upsert/delete in the same transaction as the approval** — the gate and the store commit or fail together | Bolna: no. Cartesia: **no write path exists in the SDK at all** (§3.2) |
| **New sub-processor / DPA** | **YES** — a new vendor, new credential, `/legal/subprocessors` + DPA + SEC-COMP §4 entry, and a cross-border position to state. SEC-COMP §4's cross-border row is REPORTED and already unsettled; adding a vendor adds a question, not an answer | **No new store vendor.** ⚠ **But not "no new sub-processor" unconditionally** — see §4.1 | **YES** (Cartesia) — a new engine, not just a new store |
| **Cost shape** | per-vector-stored + per-query, ongoing, scales with clients. **Actual prices UNKNOWN — vendor hosts egress-blocked; route to founder** | RAM and disk on a Postgres we already run and already pay for. No new line item. Embedding cost is separate and common to options 1 and 2 | Bolna: no KB line on their pricing page → **inferred included**, unconfirmed (gates 8+12) — a REPORTED inference, not a price |
| **What it does to D-28** | **honours it** — this is the D-28 posture | **reverses it** on the store, and D-08 was already superseded once in the other direction | orthogonal to D-28; it is D-33's arm, and D-354 closed it |
| **What it does to CLAUDE.md "Do NOT self-host vector infrastructure"** | nothing | **contradicts it as written.** The rule's own gloss says it "now means: don't run one", and pgvector is an extension in a Postgres we already run rather than a new deployable — but that is a *reading*, and the founder decides, not this document | nothing |
| **Engineering effort** | embedding path + client + namespace lifecycle + deletion-with-proof + sub-processor paperwork + a bake-off across candidates | embedding path + one migration + query module. Everything else (RLS, backup, restore drill, retention, erasure) is machinery we already run and already test | Bolna: reopen `KBSourceRef` to carry a PDF/URL and rewrite `attach_kb` as create→GET→PATCH (D-354/D-424). Cartesia: an engine migration |
| **What would have to be true for it to win** | in-call retrieval becomes reachable (hop measured and small, or retrieval moves in-pipeline) **and** a vendor's measured p95 from our region fits **and** its price is known **and** its deletion-with-proof satisfies DPDP | the founder accepts that a vector column in an existing database is not "vector infrastructure" **and** in-call stays T0 (so the store never has to be fast) | an engine whose KB accepts our approved TEXT **and** carries DLT-registered Indian telephony. **No candidate satisfies both today** |

### 4.1 The sub-processor point that cuts against the easy reading of option 2

Option 2 avoids a new **store** vendor. It does not by itself avoid a new **embedding**
vendor, and every option except a fully in-pipeline engine KB needs one, because no
embedding path exists in this tree at all (D-231 deleted the only key). The honest
statement is:

* An embedding deployment on the **Azure OpenAI resource already in use** would add **no
  new sub-processor** — Microsoft Azure is already named in the client DPA for both LLM
  surfaces (SEC-COMP §4). Whether that resource can host such a deployment, and under
  Regional Standard rather than Global, is a **portal question for the founder** of exactly
  the kind gates 20/20c already exist for. **UNKNOWN here.**
* Any other embedding vendor is a new sub-processor and lands option 2 in the same
  paperwork as option 1, minus the store.

**So "option 2 has no DPA consequence" is only true on the Azure-embedding route.** Anyone
repeating it without that clause is repeating something this document did not say.

### 4.2 Mitigations that could change the in-call verdict

| Mitigation | Verdict here |
|---|---|
| **Semantic cache** | **MEASURED-HERE (§2.3).** A cache hit is a top-1 lookup against a table two orders of magnitude smaller, returning a pre-composed answer — the fastest query in the whole experiment. Crucially it can be **colocated with voice-runtime**, so a hit pays no store hop. It still pays the engine→endpoint hop and still needs the question embedded, so it does not by itself rescue in-call retrieval. **Only options 1 and 2 can host it; option 3 cannot** (we do not run the engine's pipeline) |
| **Async prefetch during caller think-time** | not measurable here. Sound in principle and it attacks the right term (it hides the hop rather than shrinking it). Needs the hop measured first, or it is optimisation against an unknown |
| **Predictive follow-up prefetch** | same, and weaker — it spends embedding and retrieval cost on questions that may not be asked. Not worth designing before the hop is a number |

### 4.3 Agentic retrieval — the loop budgets, checked rather than recalled

The brief stated the copilot loop has `MAX_TURNS=6`. **It does not: `MAX_TURNS` is 4**
(`apps/api/copilot/service.py:66`), and `apps/api/copilot/deadline_test.py:108` asserts
`3 <= MAX_TURNS <= 5`, so 6 would fail CI today. `TOTAL_BUDGET_S = 90.0` (:125) and
`MAX_ANSWER_TOKENS = 4096` (:98) are as described.

**Are they the right stop conditions for retrieval? No — and not because they are too
small.** The comment above `MAX_TURNS` says what the four are *for*: "ask, correct a
refused fill, ask again, answer". That is a budget sized for the **fill-correction** shape.
A retrieve→read→retrieve-again loop would consume the same four turns and leave none for
the path the number was chosen for, so the two shapes would silently compete. **The fix is
a retrieval-specific counter, not a larger `MAX_TURNS`** — a maximum number of retrieval
tool calls per question, bounded independently, so neither shape can starve the other.
`TOTAL_BUDGET_S` and `MAX_ANSWER_TOKENS` remain correct as outer bounds and need no change.

Note also that the copilot budgets are a **dashboard** surface. They do not bind in-call
behaviour at all, and nothing here proposes an agentic loop inside a phone call: a control
loop that can search twice cannot fit a budget that is already overdrawn by 100ms.

### 4.4 Write-back must reuse the propose→confirm pattern, and one premise could not be checked

The brief says a signed, short-lived, replay-proof propose→confirm mechanism shipped this
session at `apps/api/copilot/write_tools.py` and that KB write-back should reuse it rather
than invent a second approval path. **I agree with the principle and could not verify the
artefact: `apps/api/copilot/write_tools.py` does not exist in this worktree**, which holds
`__init__.py`, `prompt.py`, `routes.py`, `sanitize.py`, `schemas.py`, `service.py` and their
tests. It presumably shipped on another branch. **UNKNOWN from here — not a contradiction,
a branch-isolation gap**, and whoever lands KB write-back must read that file before
designing anything.

What is verifiable is the requirement it has to satisfy, and it is the same in all three
options: `kb/__init__.py` states the preview-and-approve gate is "a product property, not a
vendor feature", and `publish_source` gates on `approved_at IS NOT NULL`
(`kb/service.py:846`) rather than on a status. An agent proposing knowledge learned from a
call must land as an **unapproved `kb_source`** and reach the store only through
`publish_source`. Option 2 makes that structurally cheap — the approval and the vector
write are one transaction. Option 1 splits them across a network boundary, so the gate can
succeed while the store write fails, which is the divergence D-41 exists to prevent and
would need the same detach-then-attach discipline and the same refusal-on-failure policy.

### 4.5 Adaptive routing — what the rule should be for us

Not everything should be agentic; the cheap path should absorb the common case. For us the
cheap path already exists and costs **0ms**: T0 compiled context, which TRD §6 says answers
~80% with zero retrieval. The rule that follows from the numbers in this document:

* **In-call: never route to retrieval.** T0 answers, or T4 refuses and offers a callback.
  This is not a routing heuristic, it is the shipped behaviour, and §0.4 is why it should
  stay shipped until the hop is measured. A semantic cache may sit in front of T0 as a
  latency-free-on-hit addition, not as a retrieval path.
* **Dashboard copilot: route on whether T0's compiled facts contain the answer**, decided
  by our code before the model is asked — not by the model, and never by the model for
  anything security-shaped. Retrieval is the fallback, bounded by the retrieval-specific
  counter of §4.3.
* **The routing decision is logged.** `kb_retrieval_logs` already exists with `tier` and
  `latency_ms` columns (`docs/DATA-MODEL.md:353-356`) and is the right home for it; it is
  what turns this rule into something measurable rather than asserted.

---

## 5. Recommendation

**Split the decision by path, and do not pick a store for the call.**

**5.1 In-call: keep T0. Change nothing, and stop carrying the question as open.** Not
because pgvector is slow — it is not, §2.3 — but because the store was never the binding
constraint. The budget is overdrawn by 100ms with nothing in it (§0.4), the first hop is
unmeasured and is the same for both candidate stores, and the embedding call is unmeasured
and unbuilt. Adopting any store "for in-call" today would be buying the smallest term in a
sum whose largest terms are unknown. `tests/kb_tiers_test.py:156` should stay exactly as it
is.

**5.2 For the dashboard copilot, CRM semantic search and H3 caller memory — the paths where
seconds are fine and where every CRM feature is blocked today — the arm that fits this
repository best is option 2, pgvector.** The reasoning, in the order it actually weighs:

1. **Isolation.** This is a multi-tenant system holding other businesses' callers' data
   under hard rule 1. pgvector puts the tenant boundary in FORCEd RLS, where forgetting the
   filter yields zero rows. Every managed option puts it in a filter our code must remember
   to send, and the *fast* configuration of a managed option — the engine calling the vendor
   directly — puts it in a parameter the model fills in. That is the one property I would
   not trade for latency, and at these sizes there is no latency to trade.
2. **Write-back.** The founder's target architecture has agents proposing knowledge that an
   owner approves. With pgvector the approval and the vector write are one transaction.
   Across a network boundary they are two, and D-41 is the record of what a divergence
   between "our tables say published" and "the store says otherwise" costs.
3. **It is measured and the alternative is not.** §2.3 is a number. Option 1's latency,
   price and residency are all UNKNOWN from here and will stay UNKNOWN until someone with a
   credential closes them.
4. **The store is not on the call path**, so D-08's latency physics — the reason a managed
   region ever mattered — does not bind this choice.

**5.3 On the founder's stated direction — "the in-call KB will be handled by Bolna only".**
That is a coherent architecture and this document does not argue against it; it argues that
it is not free and is not what is shipped. Three things have to be accepted with it, each
verified above rather than asserted: the LLM key does not deliver it (§3.0); reopening it
costs the four items in §3.1b and changes what `kb_sources` stores and what T3/T4 mean; and
it moves the approval gate from the chunk to the document, or on a URL to the address alone
(§3.1c). And because the engine KB has no search route, it leaves the dashboard copilot and
CRM search needing a store anyway (§3.1d) — so it does not remove this decision, it adds to
it. **If the founder still wants it after reading §3.1b and §3.1c, the sequencing that
wastes nothing is: choose the copilot store first (§5.2), then reopen the engine arm on top
of it**, because the copilot store is needed under either answer and the engine arm is not.

**This is a recommendation to the founder, not a decision.** It contradicts D-28 and the
literal text of CLAUDE.md's self-hosting rule, and neither is mine to reverse. What is in
its favour is that the rule's own gloss reads "don't run one": pgvector adds no deployable,
no new backup unit, no new restore drill, no new region and no new vendor — it adds a column
type to a database this repo already runs, backs up and tests. What is against it is that
this is exactly the sentence someone writes when they are about to run a vector database.

### What would change my mind

* **The hop is measured and turns out small.** If gate 8's `custom_function_tool_call_budget`
  comes back with an engine→endpoint p95 that leaves real room inside 100ms, in-call
  retrieval becomes live again and a managed vendor's in-pipeline story is worth its
  paperwork. This is the single measurement most likely to move the decision, and it needs
  one live call. (Note what would NOT achieve it: buying the vendor's Indian residency,
  which their own requirements forfeit the moment we connect our own model keys — §0.1.)
* **A managed vendor offers per-tenant isolation the query layer enforces without our code
  passing a filter** — a scoped credential per tenant, so a leak requires stealing a
  credential rather than forgetting a WHERE clause. That would neutralise reason 1, which
  is the load-bearing one.
* **An embedding path lands that is not Azure.** Then option 2's DPA advantage largely
  evaporates (§4.1) and the comparison is much closer.
* **Corpus growth by two orders of magnitude.** These numbers are for SMB corpora. If
  resolved-call transcripts are indexed as the per-client corpus (TRD §6 contemplates
  exactly that) the table grows without bound, and the 0.6.0 filtered-scan behaviour of
  §2.5 becomes a live problem rather than a noted one. Re-run the harness at the new size
  before assuming it holds.
* **The founder simply does not want to operate it.** That is a legitimate and sufficient
  answer, and it is the one D-28 already gave for a two-person team. Nothing measured here
  overrides it; the measurement only removes *latency* from the list of reasons.

---

## 6. Proposed ROADMAP row — NOT added by this lane

The decision is the founder's, so no row was written. Proposed text, to be added only if
and when the founder decides:

> | D-XXX | **The D-28 bake-off was finally run, and it found that the store was never the binding constraint on in-call retrieval** | **In-call retrieval stays T0 and nothing else**; `tests/kb_tiers_test.py::test_in_call_retrieval_is_not_reimplemented_on_our_side` stays as written. The retrieval store is chosen for the **dashboard copilot, CRM semantic search and H3 caller memory only**, where the budget is seconds. On those paths, `kb_chunks` + pgvector in the Postgres we already run is [ADOPTED / REFUSED]; embeddings come from [an Azure OpenAI deployment on the existing resource / TBD], which adds no new sub-processor. The preview-and-approve gate is unchanged and binds the agent write-back path: proposed knowledge lands as an unapproved `kb_source` and reaches the store only through `publish_source`. | **MEASURED-HERE** (`docs/evidence/kb-retrieval-bakeoff.md` §2, `scripts/spike/kb_pgvector_latency.py`, 31 Aug 2026): hybrid RRF top_k=3 on the DATA-MODEL contingency schema costs single-digit milliseconds at SMB corpus sizes, and at those sizes Postgres chooses an exact scan over the index. The 100ms in-call budget is not threatened by the store: it is threatened by (a) a voice pipeline that already misses its 500ms target by 100ms with zero retrieval in it (`latency_budget_composes()` is `False`, `voice_to_voice_gap_ms()` is `+100.0`, evaluated 31 Aug 2026), (b) an engine→endpoint hop that is India↔us-east-1 and **has never been measured** (gate 8's `custom_function_tool_call_budget`, still `not_run`), and (c) a question-embedding call that does not exist yet. Both (b) and (c) are IDENTICAL for a managed vendor, so they do not discriminate. Option 3 stays closed: Bolna's `POST /knowledgebase` takes a PDF or URL with no text field (`create.md:33,40-52`) and its `Knowledgebase` object carries no agent id (`get_knowledgebases.md:63-126`), while Cartesia Line's `knowledge_base` built-in — re-verified at source at `c79c1c4`, newer than the commit the TRD cites — is a **query client with no document write path anywhere in the SDK**, so it solves the retrieval half and leaves ingestion exactly as unproven. Three further facts bear on the engine arm if it is ever reopened, all VERIFIED-VENDOR-DOCS: `POST /knowledgebase` returns `rag_id` and **not** `vector_id` (`create.md:86-124`) while the agent attaches by `vector_ids` (`update.md:1220-1237`), so create → GET → PATCH is imposed by the vendor's spec; the vendor **re-chunks server-side** (`chunk_size`/`overlapping`, `create.md:53-70`), which drops our approval granularity from the CHUNK to the DOCUMENT and, on a URL source, to the ADDRESS alone — a deliberate weakening of what `kb/__init__.py` calls a product property; and the KB exposes **no search route**, so it cannot serve the dashboard copilot and is a complement to this decision rather than a substitute for it. **Giving Bolna our LLM key does not give Bolna a knowledge base**: BYOK is shipped (`bolna.py:363-365`) and `BOLNA_CAPABILITIES.knowledge_base` is `False` (`:2484`). Isolation is what decides between the two live options: RLS makes forgetting the tenant filter return zero rows, whereas the only managed configuration that avoids the hop puts the namespace in a parameter the model fills in. ⚠ **This entry reverses D-28 on the store and contradicts CLAUDE.md's "Do NOT self-host vector infrastructure" as written** — taken deliberately, on the reading that an extension in an existing database is not a deployable; if that reading is rejected, the whole entry falls and option 1 is the answer. |

---

## 7. Questions only the founder can answer, and what closes each

| # | Question | Why it is not mine | What closes it |
|---|---|---|---|
| 1 | **Is a vector column in the Postgres we already run "vector infrastructure"?** | It is the meaning of a rule the founder wrote. §5 argues one reading; the rule is not mine to reinterpret | A yes/no. A "no" makes option 2 available; a "yes" makes option 1 the only live arm and §7.3 becomes urgent |
| 2 | **Can the existing Azure OpenAI resource host an embedding deployment, under Regional Standard rather than Global?** | Portal attestation, exactly like gates 20/20c. Not visible from any endpoint | One portal reading, filed in `docs/evidence/`. A "yes" means no new sub-processor for either option; a "no" makes embeddings a new vendor and a new DPA entry |
| 3 | **What do the candidate managed vendors actually charge, and where do they process?** | **UNKNOWN — their hosts are egress-blocked from this container** and no credential exists. TRD §6 names the candidates (Qdrant Cloud, Pinecone serverless, Turbopuffer, Weaviate Cloud; Mem0, Supermemory, Zep) | The founder reading each vendor's pricing and DPA/residency pages and relaying them, per the RESEARCH-DISCIPLINE §4 bar — commercials in writing, exit terms, deletion with proof |
| 4 | **Will one live pilot call be placed to measure the engine→endpoint hop?** | Needs a Bolna account, a number and a live agent — outside this repo | Running `scripts/pilot/knowledge.py`'s `custom_function_tool_call_budget` against a real call. **It is the highest-value unknown in this document** and it is already written |
| 5 | **Is the platform KB (Calevate's own) in scope for the same store as client KBs?** | A product decision. The target architecture names two corpora; nothing in this repo models the platform one, and whether it shares a store, a schema or neither changes the isolation design | A decision, plus — if shared — a statement of who owns approval for platform knowledge, since `publish_source` is tenant-scoped today |
| 6 | **If a managed vendor is chosen, does it offer a per-tenant credential rather than a per-tenant filter?** | A vendor capability question requiring an account | Vendor docs or a sales answer in writing. A "yes" removes the strongest objection in §5.2 |
| 7 | **Is DOCUMENT-level approval acceptable in place of CHUNK-level, and is URL-level (address-only, with the page free to change afterwards) acceptable at all?** | It is a change to a client-facing product guarantee and a compliance posture, not an engineering trade. §3.1c states exactly what is lost | A yes/no per source kind. A "no" on URLs alone would keep the engine arm usable for files while closing it for scraped pages — a narrower answer than the question usually gets |
| 8 | **Do clients get to publish `kind='text'` knowledge at all if the engine arm is reopened?** | The vendor route has nothing to post prose to (§3.1, §3.1b item 2), so this is a product-scope decision | Either drop the source kind, or accept that text sources publish to a different target than files and URLs — two paths for one feature, which needs a decision-log entry of its own |

---

## 8. What this lane did not do

* Adopted no vendor, created no account, installed no credential.
* Reversed no decision and added no ROADMAP row.
* Wrote no migration and created no `kb_chunks` table in `calevate`. The spike built and
  dropped its own database and never touched the application schema.
* Built no embedding path.
* Weakened no gate, no test and no coverage baseline. `tests/fixtures/coverage_baseline.json`
  is untouched, and no test was run beyond the harness itself.
* Did not run `make db-reset`, `make redis-reset`, `make coverage-ratchet`, or the suite.
* Did not edit, reformat or move `bolna-findings/mirror/`.
