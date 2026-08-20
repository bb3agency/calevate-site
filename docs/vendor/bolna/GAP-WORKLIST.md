# Bolna docs → our tree: the reading order, and the leads already visible

> ## ⚠ SUPERSEDED AS A WORKLIST, 20 Aug 2026 — every lead below has been read out
>
> This file was written from ONE SENTENCE of index copy per page, before any page body
> existed in the repo. The bodies now exist (`bolna-findings/mirror/pages/`, 335 pages,
> hash-manifested) and ten audit lanes read them end to end; their reports are
> `docs/evidence/bolna-*.md` and the decisions are ROADMAP §6 **D-414 … D-424** with
> OPERATIONS §2 gates **9v, 21–27**. **Read the evidence files, not this one** — a lead is
> a guess about a page, and guesses that have been answered are the most misleading kind of
> document this repo can carry. Kept for provenance, and because how each guess FARED is
> itself evidence about reading index copy as specification.
>
> | Lead | Verdict from the page bodies | Where |
> |---|---|---|
> | **A** — our two Azure model ids absent from their Azure page | **WRONG, and it was the highest-stakes lead here.** Their Azure "Supported models" table lists all four `gpt-4o`/`gpt-4.1` variants including both *mini*s; the index sentence was a marketing summary of the top of a table, not an allow-list. No fork, no defect. **What the same pages DID find** was a real defect the lead never suspected: our wire `provider` string and our credential name were both wrong (D-417). | `bolna-providers-llm.md` §1–3 |
> | **B** — model landscape a generation ahead; BYOK may be pointless | **Half right, and the inference was wrong.** Our exact stack IS inside the flat-rate bundle — but *"When you bring your own keys (BYOK), Bolna does not charge for those components"* (`pricing/call-pricing.md:75`), so the 6¢ is a SUM, not a floor, and BYOK's cost case survives. What actually breaks the margin target is D-36's default TTS: `bulbul:v3` is NOT on the included list. | D-423, `bolna-executions-cost.md` §E |
> | **C** — Indian-server processing may retire gate 9's verdict | **It retired it in the OTHER direction.** Their default is the US for everything, India residency is an Enterprise purchase, and its requirements EXCLUDE BYOK — so buying it would move zero calls. Gate 9 now tests a decision, not a measurement. | D-415, `bolna-compliance-residency.md` §2, §5 |
> | **D** — a Violations API we had never heard of | **CONFIRMED and acted on.** Nothing pushes it, nothing signs it, and the only channel is a list endpoint; an hourly poller is built and gate 9v carries the five questions their pages do not answer. | D-416, `bolna-compliance-residency.md` §1 |
> | **E** — dispositions may be the extraction feature we built | **Not a switch, and the real find was elsewhere**: the adapter was passing the vendor's *category-nested* `extracted_data` into a field our tree reads as flat. | `bolna-kb-extraction.md` |
> | **§6 features with zero hits** | Read: graph agents (unused, and their debugging page yields the first number we have on in-call history — *"The response LLM only sees the most recent 50 messages"*, though it is stated of GRAPH agents and may not bind ours), Truecaller (per-client, unpriced, and it has a multi-day outage mode we do not model — gates 26/27), Web Call SDK, MCP/Skills, IVR/DTMF (documented, and DTMF is now pinned OFF because digits enter the transcript), CLI. | `bolna-subaccounts-platform.md`, `bolna-telephony.md` §7a, `bolna-call-flows.md` §5 |
> | **§7 gate rows** | Gates 7 (unit settled, currency not), 16f (field names settled, `api-version` open), 6 (delivery guarantee UNSETTLED, and the poller was 400ing on a missing required parameter), 8 (both KB blockers re-confirmed), 10, 12, 13, 25–27 — each answered or sharpened in the lane report named above. | `docs/evidence/bolna-*.md` |

**What this was.** 335 documentation pages is a directory nobody opens. This is the
worklist that turns them into answers: for each open gate, marked assumption, or suspected
gap, WHICH page settles it and WHAT to look for. Work top down — the order is by what it
costs us to be wrong, not by how their docs are organised.

**Evidence discipline, and it is the whole point of this file.** Everything below is
derived from ONE SENTENCE of index copy per page — the `llms.txt` description. That is
marketing prose, not an API contract, and this repository has been burned before by
treating a vendor's prose as a specification (D-31, D-32, D-350). So every row is a
**LEAD**, never a fact, and the column that matters is "what would settle it". Nothing
here may be written into a decision, a constant or a client-facing sentence until the page
body is read. `docs/vendor/bolna/mirror/README.md` says why the bodies are not here yet.

---

## 1. LEAD-A — Our two Azure model identifiers are BOTH absent from their Azure page

**This is the highest-stakes lead in the set and it lands directly on D-410.**

Their index says, of `providers/llm-model/azure-openai.md`:

> Use **GPT-5.4-mini, GPT-5.4, GPT-4.1, or GPT-4o** through Azure OpenAI for enterprise
> data residency and compliance.

Ours (`packages/shared/src/calevate_shared/engine.py:391`):

```python
AzureOpenAIModel = Literal["gpt-4o-mini", "gpt-4.1-mini"]
AZURE_OPENAI_DEFAULT_MODEL: Final = "gpt-4o-mini"
```

**Neither identifier appears in their sentence.** They name the full `gpt-4o` and
`gpt-4.1`; we ship only the *mini* variants of both. If their Azure provider validates the
model against a fixed allowlist, **every agent we publish is rejected at create time** and
the in-call leg does not work at all.

**Why it is a lead and not yet a defect.** On Azure you call a DEPLOYMENT id you chose,
not a model name — which is precisely what `engine.py` already argues ("`azure_openai_
deployment` is NOT `azure_openai_model`"). Their four names may be a dashboard dropdown
over a field that accepts any deployment string. That is the same open question as gate
16f, and this sentence raises its probability rather than answering it.

**What would settle it:** `pages/providers/llm-model/azure-openai.md` — does the page show
an API payload, and is the model field an enum or free text? Then
`pages/api-reference/providers/add.md` for the credential field names (gate 16f), and
`pages/agent-setup/llm-tab.md` for what the dashboard actually offers.

**If the allowlist is real, the decision is a fork, not a patch:** deploy `gpt-4o` /
`gpt-4.1` (higher cost — `AZURE_LIST_PRICE_USD_PER_MTOK` and every ₹/min figure move), or
move to `gpt-5.4-mini`, which is not priced in our tree at all.

## 2. LEAD-B — The model landscape has moved a generation past our assumptions

`providers/llm-model/openai.md` names **GPT-5.6 (Sol, Terra, Luna), GPT-5.5, GPT-5.4,
GPT-5.4-mini**; `anthropic.md` names **Claude Sonnet 5 / Haiku 4.5**; `gemini.md` names
**Gemini 3.x**; `deepseek.md` names **DeepSeek V4**. Our cost model, our default, and
D-410's whole comparison were written against the 4o/4.1 generation.

**What would settle it:** `pages/pricing/preferred-models.md` — "which ASR, LLM and TTS
models are bundled into Bolna's flat per-minute rate". That is gate 12's actual subject
and it decides whether BYOK is even the right posture: if a modern model is INCLUDED in
the flat rate, BYOK may be buying us cost and complexity for nothing.

## 3. LEAD-C — Bolna documents Indian-server processing, which may retire gate 9's verdict

Two pages we have never read:

- `enterprise/data-residency.md` — "store & process voice AI data in India"
- `enterprise/indian-server-configuration.md` — "**Configure your voice agent to process
  calls on Indian servers** for data residency compliance and lower latency"

OPERATIONS §2 gate 9 currently says: *"This is the one axis where LiveKit beats Bolna on
verified evidence today."* **That sentence may now be false**, and it is load-bearing —
D-31 chose Bolna with this as a known weakness.

**Read alongside** `concepts/security.md` ("where your data is stored"), because the DPA
and `/legal/*` describe processing locations to clients, and `docs/LEGAL-SURFACE.md` was
just rewritten around a residency claim that got weaker under Azure. If in-call processing
can be pinned to India, the residency story gets materially stronger — but note both pages
sit under `enterprise/`, so it may be gated behind a plan we are not on. That is a
commercial question for gate 12, not an engineering one.

## 4. LEAD-D — A Violations API exists and our tree has never heard of it

`api-reference/violations/{overview,list,submit}.md`: *"Manage and track call violations
… Submit a violation along with an evidence file … updates the violation status."*

Measured: `violation` appears in 67 files of our tree and in **zero** files under
`apps/api/engine/` or `docs/vendor/` — it is our own word for RLS and compliance
violations. Theirs is a different thing entirely, and it is **compliance-shaped on a
platform we place regulated Indian calls through**.

**Why this matters more than a missing feature.** If Bolna records violations against our
account and expects evidence submissions, that is an obligation with a clock on it that
nobody here is watching, and the first we would learn of it is enforcement. SECURITY-
COMPLIANCE §3 and the compliance gate are the surfaces it would touch.

**What would settle it:** the three pages, plus `compliance-application/introduction.md`
and `how-to-submit-guide.md` (CIN, GST, KYC — the documents a Principal Entity files).

## 5. LEAD-E — Dispositions may already be the extraction feature we built ourselves

`api-reference/dispositions/*` (8 pages): *"dispositions — the individual extraction units
that power the Extractions feature"*, with create, bulk-create, update, delete, and a
**`test` endpoint that runs them against a transcript before live calls**.

We have per-agent extraction schemas driving CRM columns, and `GEMINI_EXTRACTION_DEFAULT
is False` keeps the first pass on Sarvam over the RAW transcript. CLAUDE.md says to
configure engine built-ins over rebuilding them — but it also says raw transcripts are the
reason the first extraction pass is ours and stays ours.

**The question is not "should we switch"** — it is whether their `test` endpoint gives us
a cheap oracle for task #87 ("extraction quality has never been scored against a real
model"), which is still open. A vendor endpoint that scores extractions against a
transcript is exactly the harness that task lacks.

## 6. Features our tree has zero knowledge of

Measured by grep across `apps`, `packages`, `docs`, `scripts`, `runbooks`:

| Feature | Pages | Our hits | Why it might matter |
| --- | --- | --- | --- |
| Graph agents | 17 | **0** | A node-based alternative to one big prompt, with version history and a validator. Our prompt-versioning work (D-29 era) solved a neighbouring problem. |
| Truecaller verification | 1 | **0** | Displays business name + logo on outbound calls. Directly moves answer rates — the metric every campaign is judged on. |
| Web Call SDK | 1 | **0** | Browser-based calls to an agent. A demo surface for sales, and a way to run gate 8 probes without PSTN spend. |
| MCP server + Skills | 5 | **0** | Would have let this session query the account directly — if egress allowed it. |
| IVR agents / DTMF | 2 | partial | Keypad routing; relevant to inbound receptionist flows. |
| Bolna CLI | 29 | **0** | `bolna docs fetch` renders a docs page in a terminal — a second route to this mirror. |

Known already, no gap: Exotel (21 files), Vobiz (17), SIP trunking (8), sub-accounts (8),
`calling_guardrails` (D-351 exists because of it), auto-retry (5), OpenRouter (5).

## 7. Pages that map straight onto an open gate

Read these even if nothing above interests you.

| Our open item | Page(s) | What to extract |
| --- | --- | --- |
| **Gate 7** — cost unit and currency | `api-reference/openapi.yml`, `guides/post-call/polling-call-status-webhooks.md`, `api-reference/executions/get_execution.md` | Whether `total_cost` is still documented "in cents" while the prose says "account currency". This is the contradiction D-411 refuses on, and an INR-billed account meters NOTHING until it is settled. |
| **Gate 16f** — Azure credential fields | `api-reference/providers/add.md`, `api-reference/providers/get.md` | The exact field names `POST /providers` expects. The one marked assumption left in D-410. |
| **Gate 6** — webhook loss | `guides/post-call/polling-call-status-webhooks.md`, `list-phone-call-status.md`, `list-phone-call-hangup-status.md` | Retry semantics (D-352 flipped this once already), and the full status enum against `_VENDOR_STATUSES`. |
| **Gate 8** — KB, batches, tools | `api-reference/knowledgebase/*`, `getting-started/knowledge-base.md` | Whether `POST /knowledgebase` still cannot ingest our `KBSourceRef.text`, and whether `agent_id` linkage exists yet — D-354 set `BOLNA_CAPABILITIES.knowledge_base = False` on exactly these two facts. |
| **Gate 10** — agency model | `enterprise/sub-accounts.md`, `pricing/outbound-calling-concurrency.md`, `enterprise/concurrency-management.md` | Whether sub-accounts are Enterprise-only. The pricing page and the docs contradicted each other; our multi-tenant model lands earlier if they do not. |
| **Gate 12** — commercials | `pricing/call-pricing.md`, `pricing/preferred-models.md` | The BYOK platform fee — the single number that decides ₹3–3.6/min. |
| **D-350/D-353** — pagination | `api-reference/pagination.md`, `api-reference/limits.md` | `page_number`/`page_size`, max page size, and whether `has_more` is documented to be honest. |
| **TRD §5** — webhook trust | `api-reference/errors.md`, `api-reference/rate-limiting.md` | Whether they sign anything yet. Our receiver uses source-IP allowlist + execution-id dedupe *because* they do not. |
| **140/160-series** | `guides/inbound/obtaining-regulated-phone-numbers.md` | DLT registration and KYC as their platform actually runs it, against our PE/TM model. |
| **Changelog** | `changelog/*2026*.md` (8 pages) | Read newest-first. Everything above may already be answered in a release note. |

## 8. How to use this once the mirror is filled

1. Read §7's rows for gates 7 and 16f first — they are the two that block a pilot.
2. For each answer, do what CLAUDE.md requires: promote it to a decision-log entry with the
   evidence class (VERIFIED-VENDOR-DOCS), or leave it a marked assumption. Never a silent
   premise.
3. Where a page contradicts our code, the code moves or the gate gets stricter — not the
   comment.
4. Re-run `scripts/fetch_bolna_docs.py --refresh` before any pilot milestone. The manifest
   hashes make "what changed since we decided" a diff rather than a memory.
