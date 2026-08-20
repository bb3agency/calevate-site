# Bolna — knowledge base, dispositions/extractions, and multilingual, against the real docs

**Date:** 2026-08-20.
**Evidence class:** VERIFIED-DOCS — the vendor's own hosted documentation, mirrored at
`bolna-findings/mirror/pages/`. Every claim below cites a file and quotes the line.
**Lane:** `api-reference/knowledgebase/` (5), `api-reference/dispositions/` (8),
`getting-started/knowledge-base.md`, `guides/prompting/` (3), `customizations/` (6),
`guides/writing-prompts-in-non-english-languages.md`. All read end to end.
**Subject:** `apps/api/kb/`, `apps/workers/kb_reconciliation.py`, `apps/workers/extraction.py`,
`scripts/eval.py`, `scripts/pilot/fidelity.py`, `apps/api/engine/bolna.py`,
`packages/shared/src/calevate_shared/engine.py`.

**Headline.** Gate 8's two blockers both still hold, and one of them needs re-wording
rather than re-deciding. D-354's record of them is accurate — it already knew about
`vector_ids` — so `BOLNA_CAPABILITIES.knowledge_base` stays `False` and **no capability
constant changes.** One real defect was found and fixed, in the extraction half rather
than the KB half: the adapter passed the vendor's *category-nested* `extracted_data`
through into a field our whole tree reads as flat, which made pilot gate 7 fail calls
that fully succeeded.

---

## 1. Gate 8 — verdict on the two blockers

### Blocker (a) — `POST /knowledgebase` cannot ingest `KBSourceRef.text` — **STILL HOLDS**

`bolna-findings/mirror/pages/api-reference/knowledgebase/create.md:31-33`:

> `description: >- Create knowledgebase from a PDF file or URL. Provide either `file` or `url`, not both.`

The request body is `multipart/form-data` with exactly these properties
(`create.md:36-80`): `file` — *"PDF file to upload (max 20 MB). Required if `url` is not
provided"*; `url` — *"URL to scrape and ingest as knowledgebase"*; `chunk_size`;
`similarity_top_k`; `overlapping`; `language_support`. **There is no prose/text field.**

`getting-started/knowledge-base.md:70` says the same for the dashboard:

> `Only `.pdf` files are supported for document upload.`

Our `KBSourceRef` (`packages/shared/src/calevate_shared/engine.py::KBSourceRef`) carries
`text: str` — *"parsed, chunked and approved"* prose. There is still nothing on that
route that takes it. **Unchanged since D-354.**

### Blocker (b) — "no `agent_id` linkage" — **STILL HOLDS, but the sentence is imprecise and should be replaced**

Two separate facts, and gate 8's current wording collapses them:

1. **On the knowledgebase object: still no agent linkage of any kind.** The
   `Knowledgebase` schema (`get_knowledgebase.md:55-118`, identical in
   `get_knowledgebases.md:63-126`) has exactly: `rag_id`, `file_name`,
   `humanized_created_at`, `created_at`, `updated_at`, `vector_id`, `status`,
   `chunk_size`, `similarity_top_k`, `overlapping`, `language_support`. **No `agent_id`.**
   So `list_kb`'s per-agent filter still has nothing to filter on, and the "World 2"
   failure `apps/api/kb/reconciliation.py::classify_kb_drift` describes is still the real one.

2. **On the agent object: linkage exists, is fully specified, and D-354 already said so.**
   `api-reference/agent/v2/create.md:1302-1319`:

   > `LanceDbConfig: properties: vector_id: … "Vector id of a single knowledgebase (legacy, use `vector_ids` for multiple)"` / `vector_ids: … "Array of vector ids to use multiple knowledgebases simultaneously"`

   reached via `agent_config.tasks[].tools_config.llm_agent` with
   `agent_type: "knowledgebase_agent"` (`create.md:615-620`) and
   `llm_config.vector_store.provider_config` (`create.md:930-942`, `1290-1301`;
   `provider` enum is `lancedb`).

**So the honest statement is not "there is no linkage" — it is "the linkage is on the
agent, keyed by `vector_id`, and `attach_kb` never wrote it."** That is exactly what
D-354 recorded, and nothing in the mirror moves it.

### What the mirror adds that D-354 could not have known

| # | Fact | Citation | Why it matters |
|---|---|---|---|
| 1 | **`vector_id` is not returned by create.** The `POST /knowledgebase` 200 response carries only `rag_id`, `file_name`, `source_type`, `status`, `language_support` | `create.md:86-127` | Attaching a freshly-created KB to an agent needs a **second call** (`GET /knowledgebase/{rag_id}`) purely to learn the `vector_id`. Any future `attach_kb` is create → get → patch agent, not create → patch |
| 2 | **`rag_id` has two contradictory formats in two pages.** Create declares `format: ^[0-9a-fA-F]{32}$` (32 hex, no dashes); Get declares the dashed-UUID pattern | `create.md:89-93` vs `get_knowledgebase.md:57-62` | Ambiguity, reported not guessed. A client that validates `rag_id` as a UUID would reject the create response |
| 3 | **`error` is a real status the GET schema does not enumerate.** Create's enum is `[processing, processed, error]`; the `Knowledgebase` schema's is `[processing, processed]`; the dashboard table documents `error` | `create.md:110-114` vs `get_knowledgebase.md:87-93` vs `getting-started/knowledge-base.md:140` | Any future ingestion poller must treat `error` as reachable from GET despite the schema. `getting-started:144`: *"If status shows **"error"**, try re-uploading the file"* |
| 4 | **`language_support: multilingual` exists and is immutable** | `create.md:70-80`; `getting-started:120-122` | See §4 — this is the Telugu question |
| 5 | **Multiple KBs per agent: confirmed** | `overview.md:7` *"Agents can use multiple knowledgebases simultaneously"*; `getting-started:178`; `create.md:1310-1315` (`vector_ids`) | T3 could address several sources at once if the capability were ever re-opened |
| 6 | **Ingestion is async and its latency is documented nowhere** | `create.md:107-109` *"Initially the status would be `processing`"*; `build-with-ai/mcp-tool-list.md:78` *"Processing is async — check progress with `get_knowledgebase`"* | Gate 8's ingestion-latency probe is still unmeasured. No SLO, no ceiling, no polling interval published |

### DPDP erasure — **the one KB question the docs do NOT answer**

`DELETE /knowledgebase/{rag_id}` is documented (`delete.md:30-47`) and returns
`{message: success, state: deleted}`. What it says about the agent's dangling reference
is: **nothing at all.** The description is one line — *"Delete a knowledgebase"* — with no
statement about `vector_ids`.

The contrast inside the same API is what makes this a real gap rather than pedantry.
`dispositions/delete.md:39-41` explicitly promises the cascade:

> `Permanently delete a disposition and remove its link to any associated agents.`

The knowledgebase delete page makes no such promise. So an erasure that deletes the
document may leave the agent's `vector_store.provider_config.vector_ids` pointing at a
dead vector id, with unknown call-time behaviour. **This is D-41's question (b), still
open, and it is now open on a sharper footing:** we know the field it would dangle in.
Nothing here should be guessed — it is a gate 8 probe.

### Verdict

**`BOLNA_CAPABILITIES.knowledge_base` stays `False`. No diff to
`packages/shared/src/calevate_shared/engine.py` is proposed.** Blocker (a) is confirmed
verbatim and is on its own fatal. Re-opening still needs what D-354 named and the mirror
confirms: `KBSourceRef` carrying a PDF or a public URL instead of prose, and `attach_kb`
becoming a three-call sequence ending in a PATCH of the agent's `vector_ids`. That
changes the T0–T4 tier design and what `kb_sources` stores, so it stays a decision.

**Our KB code is correct as it stands — no gap found.** Specifically:
`apps/workers/kb_reconciliation.py:272-280` already short-circuits the whole sweep on
`if not engine.capabilities.has("knowledge_base")` and logs
`kb_drift_sweep_no_knowledge_base`, so the sweep does **not** burn a round trip or record
`unreachable` per agent per tick. All three adapter methods refuse through
`require_capability` (`apps/api/engine/bolna.py`). The `unreadable`/`not_applied` positive
control in `apps/api/kb/reconciliation.py` is exactly right for the world the docs
describe.

---

## 2. Dispositions — can the `test` endpoint close task #87?

### What the endpoint actually is

`api-reference/dispositions/overview.md:11`:

> **Extractions** is the Bolna feature that automatically captures structured data from call transcripts after every call. Each extraction is configured as one or more **dispositions** — individual questions posed to an LLM against the transcript — grouped under named **categories**.

`dispositions/test.md:34-37`:

> Run all dispositions linked to the specified agent against a provided transcript and return the grouped results. Useful for validating your disposition setup before going live.

Request: `transcript` (string, `maxLength: 50000`, **required**) and optional `call_date`
(`test.md:80-97`). Response: `extracted_data`, grouped by category then disposition name.

### It maps onto our extraction schema cleanly

| Ours (`calevate_shared.extraction.ExtractionField`) | Theirs (`dispositions/create.md:88-153`) |
|---|---|
| `key` / `label` | `name` |
| `description` | `question` (*"The prompt sent to the LLM to evaluate the transcript"*) |
| `type: enum` + `enum_values` | `is_objective: true` + `objective_options[{value, condition}]` |
| `type: text` | `is_subjective: true`, `subjective_type: text` |
| `type: number` | `subjective_type: numeric` |
| `type: bool` | `subjective_type: boolean` |
| *(no equivalent)* | `subjective_type: regex` + `pattern` — e.g. `^\d{10}$`, *"10-digit phone number"* |
| *(no equivalent)* | `category` — a grouping level we do not have |
| *(no equivalent)* | per-field `model` (default `gpt-4.1-mini`) |

`POST /dispositions/bulk` is atomic (`bulk-create.md:34-36`: *"Either all dispositions are
created and linked, or none are"*), so a whole schema can be pushed in one call.

### Verdict: **a candidate third `--provider`, NOT an oracle, and it does not close #87**

Three reasons, in order of decisiveness.

1. **It does not remove #87's blocker; it substitutes one external credential for
   another.** `scripts/eval.py:55-57` states the blocker precisely: *"Task #87 … is blocked
   outside this repo on egress and a Sarvam key; the HARNESS half is not, and it is here."*
   The test endpoint needs a **Bolna account with a real `agent_id`** (`test.md:60-61`:
   *"403 — Access denied — agent does not belong to your account"*) **and egress to
   `api.bolna.ai`**, which D-350 records as proxy-blocked from this environment. Under
   CLAUDE.md's rule that only out-of-repo blockers wait, this is a *vendor account* — the
   same class of blocker #87 already sits behind, not a way around it.

2. **We are not missing an oracle. We are missing a model.** An oracle supplies ground
   truth. `tests/fixtures/golden_transcripts.json` already carries it — 110 cases with
   `expect` and the harder `expect_absent`, per-field, with a failure taxonomy
   (`capture_miss` waivable, `capture_wrong`/`restraint` never). What #87 lacks is a real
   extractor to score *against* that truth. Bolna's endpoint is one such extractor. It
   would be a **third `--provider`**, alongside `sarvam` and `azure` — genuinely useful as
   a cross-check on `capture_wrong`, and not a shortcut past the credential.

3. **Two hard rules and one measurement problem constrain any wiring.**
   - **Hard rule 2.** An extractor in `apps/workers/extraction.py` that speaks
     `{"Category": {"Name": {"subjective": …}}}` puts vendor payload shapes outside
     `apps/api/engine/`. It has to enter through the adapter — see §3, which is the same
     boundary and the same nesting.
   - **Raw transcripts are PII.** Sending one to Bolna is a processor disclosure, and it
     is the same shape as D-127's G-2 inversion. A **fixtures-only** path is defensible
     because `tests/eval_quality_test.py` mechanically enforces that every number in the
     golden set is synthetic and every name surname-less; a **production** path is not,
     and must not be built.
   - **`objective_options` needs a natural-language `condition` per value
     (`create.md:207-212`), which our schema does not carry.** Synthesizing one means
     writing a prompt we did not write — so a score would partly measure our
     condition-generator, not their model. Any provider built on this must record the
     generated conditions in the evidence file or the comparison is not honest.

**One further ambiguity, reported not guessed.** `overview.md:29` promises *"Every result
includes a confidence score (0.0–1.0) and an explanation"*, and `using-extractions.md:337-347`
documents `confidence`, `confidence_label`, `reasoning_subjective`, `reasoning_objective`,
`validation`. But the `test` endpoint's own response schema
(`test.md:110-118`) declares **only** `subjective` and `objective`. The prose says the
format is *"the same as post-call execution data"*; the schema says it is narrower.
Whether `confidence` is available from `test` — which is the field that would make a
`confidence`-weighted comparison possible — is **not settled by these pages.**

**Nothing was wired.** Building an HTTP provider against a response schema that
contradicts its own prose, with no server to check it against, is precisely the defect
class D-31/D-32/D-350 exist for.

---

## 3. THE DEFECT FOUND AND FIXED — `extracted_data` is nested by category and we read it as flat

### What is wrong

`ExecutionSnapshot.engine_extracted` is a **flat** `{field_name: value}` map. That is what
every consumer reads it as, and what `tests/pilot_fidelity_test.py:311,323,581` pins
(`engine_extracted={"lead_name": "Ravi Kumar"}`).

Bolna's `extracted_data` is **two levels deep, keyed by category first.** Three
independent statements in my lane:

- `guides/prompting/using-extractions.md:349` — *"Results are nested by category and extraction name under `extracted_data`"*, with the worked example at `:351-367`.
- `using-extractions.md:487-509` — the `GET /executions/{execution_id}` example: `extracted_data → "Agent Handover" → "Agent Handover Needed" → {subjective, objective, confidence, …}`.
- `dispositions/test.md:105-107` — *"Results grouped by category and disposition name … in the same format as post-call execution data."*

`apps/api/engine/bolna.py` did `engine_extracted=payload.get("extracted_data") or {}` —
straight through, nesting and all.

### What it cost

`scripts/pilot/fidelity.py:434` does `extracted_field_names=tuple(sorted(snapshot.engine_extracted))`
— the one thing every consumer does with this field. On the real payload that returns
**category names**, labelled "field names".

`fidelity.py:784-800` then compares that tuple against the field names an operator lists
as `expects_extracted_fields`:

```python
missing = [f for f in wanted if f not in observation.extracted_field_names]
```

An operator who configures dispositions `Call Outcome` and `Customer Email` under
categories `Lead Quality` and `Contact Info`, and lists those two field names, gets
`extracted_field_names == ("Contact Info", "Lead Quality")` and therefore
`missing == ["Call Outcome", "Customer Email"]` — **pilot gate 7 FAILS a call in which
every field arrived, and names every one of them as absent.** In the no-expectations
branch (`:809-813`) it prints the tenant's category names into the operator's evidence
file under *"carrying these field NAMES"*.

A false FAIL on a gate is worse than no gate: it is read as the vendor failing, on
evidence we produced. This is the same defect class as D-359 (`direction` read from a
field that does not exist) and D-361 (invented timestamps).

**Secondary:** a non-dict `extracted_data` raised `ValidationError` out of `_snapshot`,
taking down the whole snapshot for an unreadable sub-field. Confirmed during sabotage —
see below.

### The fix

`flatten_extracted_data` in `apps/api/engine/bolna.py` — **in the adapter, because hard
rule 2 is a rule about vocabulary as much as imports.** `scripts/pilot/fidelity.py`
learning that a value keyed `subjective` implies its parent is a category is this file's
knowledge leaking into a caller that must keep working on a different engine.

- **Both shapes**, because the vendor says there are two: `using-extractions.md:18` calls
  this *"The **new** Extractions feature … powered by the Dispositions API"*, so an
  account may still hold agents whose payload is flat. A top-level entry is a CATEGORY
  only when its value is a mapping **all** of whose values carry `subjective` or
  `objective`. Matching on the leaf keys rather than on nesting depth means a flat field
  whose value happens to be a dict is not mistaken for a category, and requiring *every*
  member means a dict with one unrelated `objective` key does not swallow its siblings.
- **Value is `objective` first, then `subjective`** — both are documented as the answer
  (`using-extractions.md:341-342`); `objective` is the pre-defined selection, i.e. the
  CRM-column-shaped one.
- **`confidence`, `confidence_label`, `reasoning_*`, `validation` are dropped.** They are
  the vendor's account of itself, not the extracted value — and the reasoning fields are
  free text the model wrote *about what the caller said* (hard rule 6).
- **A duplicate field name across two categories keeps both.** Bolna scopes disposition
  names to their category, so two may both be "Notes"; last-wins would silently drop an
  extracted value. The second becomes `"<Category> / <Name>"`. The first keeps the bare
  name so the common case still matches what an operator lists.
- **A non-dict payload returns `{}`**, which is what "no extraction ran" already means to
  every consumer.

**This does not move the first post-call extraction.** `GEMINI_EXTRACTION_DEFAULT is
False` is untouched; nothing in `apps/workers/extraction.py` was edited; the golden
fixtures were not touched. This is purely the adapter reading the vendor's own answer
correctly.

---

## 4. Multilingual — a real product gap, and a hard-rule-5 trap waiting for whoever closes it

### Telugu is supported, and D-41's one-way door is not narrowed

Telugu `te` is in every list: `customizations/multilingual-languages-support.md:145`
(`| Telugu | `te` |`), `multilingual-config-reference.md:187`,
`auto-switch-multilingual-messages.md:134`. The Sarvam transcriber enum in the agent API
carries `te-IN` (`api-reference/agent/v2/create.md:1078-1092`), which is **exactly the
spelling `AgentConfig.language_primary` already sends** — so our top-level transcriber
language is correct, no defect.

### THE GAP: `languages_extra` is collected, stored, and never reaches the engine

- Written: `apps/api/admin/intake.py:493-497` (`UPDATE agents SET … languages_extra = :langs`).
- Stored: `apps/api/agents/models.py:96`; on the contract at
  `AgentConfig.languages_extra` in `packages/shared/src/calevate_shared/engine.py`.
- Read back for display: `apps/api/admin/intake.py:663,682`.
- **Deliberately excluded from the compiled prompt** — `apps/api/admin/intake.py:317-319`
  says so in as many words: *"No escalation numbers and no language list: neither is a
  fact the agent says."*
- **Never read by the adapter.** `grep -n "languages_extra" apps/api/engine/bolna.py`
  returns nothing. The only language the engine payload carries is
  `"language": cfg.language_primary` (transcriber).
- **`grep -rn "multilingual" apps packages` returns nothing at all.**

So a client answers "which languages does this business work in?" in intake step 3,
picks Telugu + Hindi + English, and gets a **single-language agent**. That is a column
nobody reads reaching the engine as nothing — the half-wired shape CLAUDE.md names
directly.

Bolna supports precisely this, and it is fully specified
(`customizations/multilingual-config-reference.md`): `multilingual_config` inside
`tools_config` on the first task, with `enabled`, `active_language`, `languages`
(**minimum 2**, `:49`), `switch_tool_description`, and per-language `transcriber`,
`synthesizer` (**required**, `:90`), `system_prompt`, `handoff_message`, `agent_name`.
Bolna injects a `switch_language` tool and runs detection in parallel (`:106`).

### THE TRAP — read this before building it

**`multilingual_config.languages.<code>.system_prompt` is a SEPARATE prompt that Bolna
makes active while the agent speaks that language** (`:91`: *"Prompt activated while the
agent speaks this language"*; `:108`: *"the transcriber, synthesizer, and active system
prompt all switch together"*).

Our compliance invariant lives in exactly one string.
`compose_engine_prompt` in `packages/shared/src/calevate_shared/engine.py` is, in full:

```python
parts = [cfg.opening_line.strip(), cfg.system_prompt, TRUTHFUL_ANSWER_DIRECTIVE]
```

**So a naive `multilingual_config` — per-language prompts composed without the directive —
produces an agent that, once it switches to Telugu, is running a prompt with no
truthfulness directive in it. That is a hard rule 5 breach, on the Telugu leg, of a
Telugu-first product.** And it would not be caught: `AgentSnapshot` has **no language
field at all**, and `carries_prompt_marker` reads a single `system_prompt`
(`AgentSnapshot.carries_prompt_marker`), so the publish read-back and the drift sweep would both report
the agent as compliant.

Worse, the per-language `system_prompt` is **optional** (`:87-91`) and the docs do not
say what an agent uses when it is omitted. Omitting it and hoping Bolna falls back to the
base prompt is exactly the unverified-premise pattern D-31/D-32 exist to forbid.

**Nothing was built.** Closing this needs, at minimum: a per-language prompt column, the
directive composed into every one of them, per-language voice selection
(`ModelConfig` has one `tts_voice`), a `te-IN` → `te` conversion for the `languages` map
keys while per-language `transcriber.language` is resolved by Bolna itself (`:97`: *"Sarvam
`hi` becomes `hi-IN`"*), and `AgentSnapshot` growing a per-language read-back so the drift
judge can see all of them. **This is OURS — no external blocker — and it is a product
decision, not a flag flip.** It is the largest single finding in this lane.

### Multilingual KB — the Telugu question is narrower than gate 8 states

Gate 8 currently says *"Telugu is NOT named in their multilingual mode (Hindi/Tamil
are)"*. That is still literally true — the only enumeration is the dashboard dropdown
label *"Multilingual (Hindi, Tamil, etc.)"* (`getting-started/knowledge-base.md:61,95`).
But the API description is far broader (`create.md:73-77`):

> enables cross-lingual retrieval across 100+ languages. This allows you to upload documents in any language and query them in any language.

**Ambiguity, reported not guessed:** "100+ languages" almost certainly covers Telugu, but
no page enumerates it, so it stays a probe rather than a fact. The immutability is
confirmed verbatim (`getting-started:120-122`):

> Choose the language support mode **before** uploading. Existing knowledge bases cannot be switched between default and multilingual — you'll need to create a new one.

### Auto-switch and per-turn language

`auto-switch-multilingual-messages.md:35` — detection runs *"After **3 conversation
turns**"*, and covers only three system message types (user-online check, hangup, tool-call
wait), each configured as a `{lang: text}` map (`:59-107`), with an English → first-available
fallback (`:113-119`). We configure none of these today.

Note for extraction quality: `TranscriptTurn.lang` exists
(`packages/shared/src/calevate_shared/events.py:82`) but the Bolna adapter never sets it —
the vendor's transcript is a flat prefix-tagged string with no per-turn language. On a
code-mixed Telugu call every turn arrives `lang=None`. Not a defect today (nothing reads
it), but it is why a multilingual call cannot be scored per-language.

---

## 5. Precise transcripts — no gap found

`customizations/capturing-precise-transcripts.md:13`:

> Rather than storing the entire response generated by the language model, Bolna intelligently retains only the portion that was actually delivered before the interruption.

`:17`: *"This behavior is enabled by default for all Bolna voice agents and requires no
configuration."*

This is **good** for us and needs nothing: the truncation happens before we ever see the
payload, so `parse_transcript` receives a shorter agent turn and our extraction reads what
the caller actually heard. `apps/api/engine/bolna.py::parse_transcript` handles it
correctly — prefix-tagged lines, unprefixed continuations appended, non-dialogue prefixes
counted as lost rather than glued on (D-260). **No change needed.**

One consequence worth recording: because truncation is silent and unconfigurable, we
cannot distinguish "the agent was interrupted" from "the agent said only that much". No
field reports it. Any future barge-in metric has to come from our own side.

---

## 6. Everything else read in this lane, with no gap found

- **`guides/prompting/prompting-guide.md`** — variables `{name}`, `@` prompt modules,
  Browse Modules library. Their **Optional** module category includes *"Knowledge Base,
  … Extraction Schema, … Compliance Healthcare, Compliance Finance"* (`:97`) — vendor-authored
  compliance prompt blocks. **We must not use those**: hard rule 5's invariant is ours,
  server-side, and a vendor-supplied compliance block is a compliance claim we did not
  write and cannot verify. Noted so nobody reaches for them.
  `:166` recommends *"Azure / gpt-4.1-mini cluster"* for the LLM — consistent with D-410.
- **`guides/prompting/using-context.md`** — `user_data` maps to `{var}` in the prompt;
  system variables `agent_id`, `execution_id`, `call_sid`, `from_number`, `to_number`,
  `current_date`, `current_time`, `timezone`. `:158`: *"CSV columns are passed as-is
  without validation."* Nothing we depend on.
- **`guides/writing-prompts-in-non-english-languages.md`** — write in native script, not
  romanized. **Worth flagging against our own fixtures:** our golden transcripts are
  deliberately *code-mixed romanized* because that is what Sarvam Saaras returns
  (`tests/fixtures/golden_transcripts.json` `_doc`). That is about STT **output**; this
  page is about prompt **input**. They do not conflict, but a future Telugu per-language
  prompt must be in Telugu script (`te` native), not romanized.
- **`customizations/identify-incoming-callers.md`** — inbound caller lookup via a GET
  endpoint receiving `contact_number`, `agent_id`, `execution_id`, or CSV, or a
  **publicly accessible** Google Sheet. The CSV and Sheet routes put customer phone
  numbers in a third-party spreadsheet with no access control — **not usable under DPDP**.
  The Internal-API route (Bearer auth) is the only one that could ever be; we do not use
  any of them today.
- **`customizations/using-custom-llm.md`** — confirms the `custom` route is dashboard-driven
  (LLM URL + name, then refresh). D-410 deliberately uses first-class `provider: "azure"`
  instead. No change.
- **`api-reference/dispositions/{list,get,update,delete}.md`** — copy-on-write on update is
  the notable one (`update.md:16`): editing a shared disposition through a scoped
  `agent_id` **creates a new id** and returns `201`, and `:19` warns *"update your
  reference to the new ID"*. Anything we ever build against dispositions must re-read the
  id after an update. Delete cascades the agent link (`delete.md:39-41`).

---

## 7. Proposed replacement text for the OPERATIONS §2 gate 8 row

*(Not applied — `docs/OPERATIONS.md` is owned centrally. Replace the existing gate 8 row
with this.)*

> | 8 S | KB + campaigns + tools + H1 handling [expanded, D-33] | **BOTH D-354 BLOCKERS RE-CONFIRMED AGAINST THE VENDOR'S OWN DOCS (2026-08-20, `docs/evidence/bolna-kb-extraction.md`); THE CAPABILITY STAYS `False`.** (a) `POST /knowledgebase` is still `multipart/form-data` taking `file` (PDF ≤ 20 MB) **or** `url`, "not both", with **no text field** — it cannot ingest `KBSourceRef.text` (`bolna-findings/mirror/pages/api-reference/knowledgebase/create.md:31-80`). (b) The `Knowledgebase` schema still carries **no `agent_id`** (`get_knowledgebase.md:55-118`), so `list_kb`'s per-agent filter still matches nothing — but the old wording "no agent linkage" is wrong and is replaced: the linkage exists **on the AGENT**, as `llm_agent.agent_type="knowledgebase_agent"` + `llm_config.vector_store.provider_config.vector_ids`, keyed by `vector_id` (`api-reference/agent/v2/create.md:930-942,1290-1319`). **NEW, and it changes the shape of any re-opening:** `POST /knowledgebase` does **not** return `vector_id` (`create.md:86-127`), so `attach_kb` would be create → `GET /knowledgebase/{rag_id}` → PATCH the agent — three calls, not two. **STILL UNANSWERED AND THE ONE THING THIS GATE MUST MEASURE: does `DELETE /knowledgebase/{rag_id}` clear the agent's `vector_ids`?** The delete page says only "Delete a knowledgebase" (`knowledgebase/delete.md:30-47`) while the *dispositions* delete page in the same API explicitly promises "remove its link to any associated agents" (`dispositions/delete.md:39-41`) — the silence is conspicuous, and a dangling `vector_id` after an erasure is a DPDP finding. **Telugu + multilingual KB:** the mode is confirmed immutable at creation ("cannot be switched … create a new one", `getting-started/knowledge-base.md:120-122`) and the API claims "cross-lingual retrieval across 100+ languages" (`create.md:73-77`) — but **no page enumerates Telugu**; the only list is the dashboard label "Multilingual (Hindi, Tamil, etc.)". So measure Telugu retrieval quality **and** latency in `multilingual` mode against the fallback in the same session. **Ingestion latency is documented nowhere** — status goes `processing` → `processed`/`error` with no SLO and no polling interval published; measure it. Note `error` is reachable but is **absent from the GET schema's enum** (`create.md:110-114` vs `get_knowledgebase.md:87-93`), and `rag_id`'s format contradicts itself between the two pages (32-hex vs dashed UUID). **What this gate primarily measures remains the FALLBACK** (TRD §6.2): retrieval quality and latency through OUR managed vector service behind the in-call RAG tool endpoint, whose 100ms budget is measured as `tool_ack_ms` (`apps/voice-runtime/tool_routes.py`). Test a custom function to our endpoint and record the tool-call p95 (**no timeout is documented — the ceiling is unmeasured**). Create a 10-contact batch; verify retry policy + per-contact statuses. Capture every response as an adapter fixture. **In-call working memory (H1, TRD §6.1):** does Bolna truncate or summarise conversation history at a window limit, and does it enable provider context caching on BYOK keys? |

---

## 8. For the founder

1. **Multilingual is a real product gap and it is ours to close** (§4). A Telugu-first
   product publishes single-language agents while the engine supports per-language
   prompts, voices and switching. The blocker is not the vendor — it is that our data
   model has one prompt and one voice. **Closing it without composing
   `TRUTHFUL_ANSWER_DIRECTIVE` into every per-language prompt is a hard rule 5 breach the
   drift sweep cannot see.** Decide whether to build it; do not let it be built casually.
2. **Task #87 still needs a credential, and now there are two ways to buy one** (§2): a
   Sarvam key, or a Bolna account (which also unblocks gates 3, 7, 8, 10, 12 and 16f).
   The Bolna account scores more gates per rupee. The disposition `test` endpoint is worth
   having as a third `--provider`, fixtures-only, once an account exists.
3. **DPDP erasure has one unanswered vendor question** (§1): whether deleting a
   knowledgebase clears the agent's reference. It is moot while the capability is `False`,
   and it becomes blocking the moment anyone re-opens it.
