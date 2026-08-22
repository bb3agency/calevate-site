# Evidence — a direct Gemini adapter: does the objection that removed it still hold?

> ⚠ **SUPERSEDED IN PART — 22 August 2026, D-449.** This lane re-tests a removal whose
> residency half rested on the product having an India-inference requirement. D-449 moved
> the declared posture to `us-azure-openai` / `eastus2` and withdrew the India warranty, so
> **the residency leg of the Gemini refusal no longer discriminates** and should not be
> quoted as if it does. The other legs recorded here are untouched and are what the refusal
> now rests on: the 16 Oct 2026 retirement of `gemini-2.5-flash`, the successors' pricing,
> and the Developer API's unexpressible region. Nothing below was re-read.

> ⚠ **§3 IS UPGRADED AND §2 IS NARROWED — 22 August 2026, lane P-1
> (`docs/evidence/llm-provider-postures.md`).** §3's central claim, that the Gemini
> Developer API cannot express a region, was REPORTED here from search summaries. It is now
> **VERIFIED-VENDOR-DOCS from Google's own SDK**: `googleapis/python-genai` @ `66807187f212`,
> `google/genai/_api_client.py:681-682` — `raise ValueError('Gemini API does not support
> project/location.')`. Not "no region is documented" but "asking for one is a `ValueError`
> before a packet leaves the machine", and `bolna/llms/gemini_llm.py:48-49` (VERIFIED-OSS)
> shows the engine's Google leg is exactly that api-key client. **§2.2's ⚠ — which paragraph
> the human-reviewer sentence sits in — is NOT closed**; `ai.google.dev` is still
> egress-blocked. What P-1 adds is that Google's own issue tracker carries an **unanswered**
> question on the adjacent boundary (`google-gemini/gemini-cli#1472`: free-quota usage on a
> billed project), and that the EEA/CH/UK carve-out extending paid terms to free tiers
> **does not include India**. **§4.1's retirement calendar stands and P-1 makes it worse**:
> the engine disables thinking only on `gemini-2.5-flash` — the retiring model — and sends a
> non-zero thinking level on every `gemini-3.*` successor, where the tokens draw on
> `max_output_tokens` and can return a candidate with no `content` field at all.


**Lane**: L2 (research). **Read**: 22 Aug 2026. **Repo state**: read-only; this file is the
only thing the lane wrote.

**Scope**: whether the Gemini removal recorded in D-401 / D-406 / D-407 / D-410 is still
correct against Google's current terms and product surfaces, and if not, what specifically
changed. Decision rows are cited, not restated.

## Evidence classes used

| Class | Meaning here |
| --- | --- |
| **VERIFIED-VENDOR-DOCS** | Read in a vendor's own page or in the read-only Bolna mirror at `bolna-findings/mirror/`, cited page:line. |
| **REPORTED** | Search-engine summaries of vendor pages, or third-party pages. Wording may be a summary rather than the vendor's own sentence. |

### ⚠ EGRESS: nearly every Google documentation host is blocked here

Measured 22 Aug 2026 through the agent proxy. `EGRESS_BLOCKED` on CONNECT:

- `ai.google.dev` — the Gemini Developer API terms, logs policy, ZDR and OpenAI-compat pages
- `docs.cloud.google.com` — **where every `cloud.google.com/vertex-ai/...` doc now 301s to**
- `discuss.ai.google.dev` (Google's own dev forum)
- `artificialanalysis.ai`, `benchlm.ai`, `costgoat.com`, `curlscape.com`,
  `developer.puter.com`, `modelavailability.com`, `vorplabs.com`, `blevinscm.github.io`,
  `r.jina.ai`

Reachable: `cloud.google.com` (but it 301s to the blocked `docs.` host, so only the
redirect is observable), `github.com`.

**Consequence, stated plainly: not one word of Google's terms of service was read at its
own URL by this lane.** Everything in §2 below is **REPORTED** — search summaries of
`ai.google.dev/gemini-api/terms` and of the Vertex data-governance page. That is a weaker
class than the Bolna mirror this tree normally cites, and no conclusion in §2 should be
acted on commercially until a human opens those two URLs from an unblocked network. The
two URLs a human must open are named in §7.

---

## 1. The two products, kept apart

The single commonest error in this area, and the one D-401 exists to prevent.

| | **Gemini Developer API** | **Vertex AI Gemini** (renamed **Gemini Enterprise Agent Platform**, Google Cloud Next 2026) |
| --- | --- | --- |
| Host | `generativelanguage.googleapis.com` | `{location}-aiplatform.googleapis.com` (regional) or `aiplatform.googleapis.com` (global) |
| Key | AI Studio API key, static, long-lived | OAuth2 access token from a service account / ADC, ~1h default TTL |
| Region | **none — not expressible** | in the host *and* the `locations/` path segment |
| Terms | Gemini API Additional Terms of Service (free/paid split) | Google Cloud terms + Cloud Data Processing Addendum |

REPORTED, 22 Aug 2026, search summary of `docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/locations`
and `.../resources/locations`: *"The Gemini Developer API does not support explicit location
specification for data residency requirements. If this feature is important to you, you should
consider using the Agent Platform Gemini API (formerly Vertex AI) instead."*

REPORTED, 22 Aug 2026, search summary (`hermes-agent.nousresearch.com`, `docs.pageassist.xyz`):
*"At Google Cloud Next 2026, Vertex AI was renamed to the Gemini Enterprise Agent Platform.
The API endpoints, model IDs, and authentication are unchanged — only the product name
differs."* → the endpoint shapes D-400/D-404 recorded are still the current ones; only the
product name in Google's docs moved.

---

## 2. Data use and human review — the deciding question

### 2.1 Gemini Developer API, UNPAID tier

REPORTED, 22 Aug 2026, search summary of `https://ai.google.dev/gemini-api/terms`:

> When you use Unpaid Services, including Google AI Studio and the unpaid quota on Gemini
> API, Google uses the content you submit to the Services and any generated responses to
> provide, improve, and develop Google products and services and machine learning
> technologies, including Google's enterprise features, products, and services…
> To help with quality and improve their products, human reviewers may read, annotate, and
> process your API input and output. This includes disconnecting this data from your Google
> Account, API key, and Cloud project before reviewers see or annotate it.
> [Users should] not submit sensitive, confidential, or personal information to the Unpaid
> Services.

**The sentence CLAUDE.md quotes is confirmed, and it is a free-tier sentence.** The final
clause is the operative one for us: Google itself instructs callers not to submit personal
information to the unpaid tier. A caller's phone conversation with an SMB is personal
information under DPDP by definition.

### 2.2 Gemini Developer API, PAID tier

REPORTED, 22 Aug 2026, search summaries of the same page:

> When you use Paid Services, Google doesn't use your prompts (including associated system
> instructions, cached content, and files such as images, videos, or documents) or responses
> to improve our products.
> Google logs prompts and responses for a limited period of time, solely for the purpose of
> detecting violations of the Prohibited Use Policy and any required legal or regulatory
> disclosures.

REPORTED, 22 Aug 2026, search summary of `https://ai.google.dev/gemini-api/docs/usage-policies`
(abuse monitoring): data logged for abuse monitoring *"can be accessed for human review only
by authorized Google employees via an internal governance assessment and review management
platform"*, and Google *"retains the following data for fifty-five (55) days for the purposes
of detecting and preventing violations of the Prohibited Use Policy."*

**Finding, stated without hedging: on the PAID Developer API the training-and-open-human-review
objection is resolved.** The "human reviewers may read, annotate, and process" clause is
scoped to Unpaid Services. What survives on paid is a narrower thing: 55-day abuse logging,
readable by authorised Google employees under an internal governance process — the same
shape of clause Azure OpenAI carries.

⚠ One caution on the class of that finding. The first search summary this lane obtained
(query phrased around "paid tier … human reviewers") returned the human-review sentence
*attached to* the paid paragraph, and a second, more precisely phrased query returned it
attached to the unpaid paragraph with the paid paragraph explicitly excluded. Two summaries
of one page disagreed about which paragraph a sentence sits in. That is exactly the failure
class D-417 records (a label read for a wire value). **Treat §2.2 as unconfirmed until a
human reads the paragraph boundary at `ai.google.dev/gemini-api/terms`.**

### 2.3 Zero data retention — NEW since D-401/D-406 were written

REPORTED, 22 Aug 2026: a page now exists at `https://ai.google.dev/gemini-api/docs/zdr`
("Zero data retention in the Gemini Developer API"), and Google's own forum carries a thread
"How to request Zero Data Retention (ZDR) for a Gemini Developer API project?"
(`discuss.ai.google.dev/t/…/172806`). Search summary: *"When your request for ZDR for a
particular project is approved, all user content (prompts and responses) and identifiable
metadata (such as IP addresses and Google Account IDs) are cleared prior to logging, with the
resulting record marked as sanitized."*

So the 55-day abuse log is removable **by application and approval per project**, not by a
console toggle. It is a vendor-relationship task, not an engineering one.

### 2.4 Vertex AI / Gemini Enterprise Agent Platform

REPORTED, 22 Aug 2026, search summary of `cloud.google.com/vertex-ai/generative-ai/docs/data-governance`
(the page itself 301s to the blocked `docs.` host):

> Google won't use your data to train or fine-tune any AI/ML models without your prior
> permission or instruction.
> By default, Google foundation models cache inputs and outputs for Gemini models, with
> cached contents stored for up to 24 hours in the data center where the request was served.
> Data caching is enabled or disabled at the Google Cloud project level…
> To achieve zero data retention, you must disable data caching.
> Google may log prompts to detect potential abuse, but **only customers whose use isn't
> governed by an Invoiced Cloud Billing account are subject to prompt logging for abuse
> monitoring.**

Three consequences, and the third is the one that bites a two-person company:

1. No-training is the default on Vertex; no paid/free distinction exists there at all.
2. The 24-hour cache is **on by default** and is a project-level switch. A "zero retention"
   claim in a DPA that has not had caching disabled is false.
3. **Abuse-log exemption is gated on an Invoiced Cloud Billing account** — Google's
   enterprise invoicing arrangement, not the self-serve credit-card billing a founder
   "recharging as per usage" (D-400's verbatim founder quote) has. An SMB-scale Vertex
   account is therefore subject to prompt logging for abuse monitoring, same as the paid
   Developer API. Do not write "zero retention on Vertex" into a client DPA on the strength
   of the ZDR page alone.

### 2.5 Hard deletion on request (DPDP erasure)

**Nothing found that constitutes a vendor commitment to erase a specific end-user's content
on demand.** What exists is time-bounded retention (55 days Developer API; 24h cache +
abuse logs on Vertex) and the ZDR route, which prevents retention rather than reversing it.
For a DPDP erasure request naming one caller, the only answerable posture is "no content of
that caller is retained by the sub-processor beyond N days, and here is the ZDR approval."
This is the same open shape as the existing vendor-deletion gate; a Gemini adapter does not
close it and does not make it worse.

---

## 3. Regions — and the half that matters

REPORTED, 22 Aug 2026, search summaries of `docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/data-residency`
and `.../learn/locations`:

- *"Machine learning processing for Generative AI on Vertex AI services occurs within the
  specific region or multi-region where the request is made."* — the right half: this is
  about INFERENCE, not storage at rest.
- *"the AI/ML data location (data residency for ML processing, or DRZ) commitment is only
  supported in locations in the US and EU"* — **so `asia-south1` gets the behaviour, not the
  contractual commitment.** This is a real weakening of the D-400 posture and D-400 did not
  record it.
- *"Don't use the global endpoint if you have ML processing requirements, because you can't
  control or know which region your ML processing requests are sent to."* — unchanged since
  D-404 quoted it.
- Models listed as supporting ML processing in `asia-south1` (Mumbai): Gemini 2.5 Flash,
  2.5 Pro, 2.5 Flash-Lite, 2.5 Flash Image, 2.0 Flash, 2.0 Flash-Lite, and the embeddings
  models. `asia-south1` supports **Single Zone Provisioned Throughput only**.
- Gemini 3.5 Flash is reported available in `asia-south1` (REPORTED, `modelavailability.com`
  summary — host blocked, so this is one search summary and nothing else).
- **Gemini 3.6 Flash and 3.7 Flash run in the global region only, with no data residency**
  (REPORTED, summaries of `kie.ai`, `requesty.ai`, `aireiter.com`; 3.6 Flash GA 21 Jul 2026).

**Developer API: no region, still.** REPORTED as in §1 — no region in the host, no field to
ask for one. D-401's and D-406's residency objection to the Developer API is **unchanged and
still dispositive on its own.** Nothing in the paid tier, and nothing in ZDR, puts a region
in that request.

---

## 4. Models, prices, retirement — and the trap in the middle

All prices USD per 1M tokens, standard (non-batch, non-cached), **REPORTED** from search
summaries of pricing aggregators (every aggregator host this lane tried was egress-blocked;
these are the summaries, not the pages), 22 Aug 2026:

| Model | In | Out | Context | Region story |
| --- | --- | --- | --- | --- |
| `gemini-2.5-flash` | $0.30 | $2.50 (as priced in D-410) | 1M | `asia-south1` ✅ |
| `gemini-2.5-flash-lite` | ~$0.10 / $0.40 class (not confirmed this session) | | 1M | `asia-south1` ✅ |
| `gemini-3.1-flash-lite` | $0.25 | $1.50 | 1M | not established |
| `gemini-3.5-flash` | $1.50 | $9.00 | 1M | `asia-south1` reported ✅ |
| `gemini-3.5-flash-lite` | $0.30 | $2.50 | 1M | not established |
| `gemini-3.6-flash` | $1.50 | $7.50 ($0.15 cached in) | 1M | **global only, no residency** |

Compare `AZURE_LIST_PRICE_USD_PER_MTOK` (D-410): `gpt-4o-mini` $0.15 / $0.60. **Every Gemini
model that is both India-regional and current is more expensive per token than the incumbent,
and `gemini-3.5-flash` is 10x/15x it.**

### 4.1 ⚠ THE RETIREMENT CALENDAR IS BACK, AND IT IS EIGHT WEEKS OUT

REPORTED, 22 Aug 2026 (`benchr.org/deprecations/gemini-2-5-pro`,
`gcpstudyhub.com`, `github.blog/changelog/2026-07-02-…`):

> Google retires `gemini-2.5-pro` and `gemini-2.5-flash` on **October 16, 2026**… On Vertex
> AI, Google's own pages currently disagree: October 16 in release notes and **October 20**
> on the lifecycle page. If you are on the Gemini Enterprise Agent Platform the date is
> already hard: migrate by **October 20, 2026**. Google now names **Gemini 3.6 Flash** as the
> recommended replacement for Gemini 2.5 Flash.

This is BRD R-04's date, still live, on the vendor's side of the fence. D-410 deleted
`GEMINI_DEFAULT_LLM_RETIRES` and the CI test **because the product left Gemini**, not because
the date went away — and the date did not go away.

**The trap in full**: the only Gemini model that is (a) India-regional, (b) fast enough for
voice, and (c) cheap, is `gemini-2.5-flash`/`-lite` — and it retires in ~8 weeks. Its named
successor, `gemini-3.6-flash`, is **global-only with no data residency** and 5x the input
price. `gemini-3.5-flash` is regional but 5x the input price and 3.6x the output price of
2.5-flash. **Building a direct Gemini adapter for the in-call leg today means building onto
a model with a published retirement date and no compliant successor.**

### 4.2 TTFT — where Gemini genuinely wins

- Bolna's own docs, **VERIFIED-VENDOR-DOCS**, `bolna-findings/mirror/pages/concepts/latency.md:66-69`:
  `gpt-4.1-mini` ~150ms, `gemini-2.5-flash` ~150ms — a tie at the engine's own measurement.
  `latency.md:127` names `gpt-4.1-mini` and `gemini-2.5-flash-lite` together as the low-TTFT
  choices.
- REPORTED, 22 Aug 2026 (Artificial Analysis figures via search summary; host blocked):
  Gemini 2.5 Flash-Lite TTFT **0.29s**; GPT-4o-mini TTFT **1.07s** — ~3.7x.
- REPORTED, 22 Aug 2026, kwindla (Pipecat/Daily, voice-agent benchmarks), on X:
  *"All the Gemini 3 models so far are too slow to work well for voice agents. Gemini 2.5
  Flash was a *great* model for voice agents, when it was SOTA… Its big weakness was tool
  calling."* and elsewhere in the thread, TTFT ~1s for Gemini 3 against a needed **<700ms**.

**So the latency argument for Gemini is an argument for exactly the model that retires in
October, and the successor generation is reported as too slow for voice.** Note also the
tool-calling weakness: our in-call RAG tool endpoint depends on reliable function calling.

---

## 5. The wire contract

### 5.1 Gemini Developer API, OpenAI-compatible surface

**VERIFIED-VENDOR-DOCS (Microsoft's, not Google's)** — `github.com/MicrosoftDocs/azure-docs`,
`articles/api-management/openai-compatible-google-gemini-api.md`, read 22 Aug 2026 (github.com
is reachable; ai.google.dev is not):

- Base URL: `https://generativelanguage.googleapis.com/v1beta/openai`
- Path: `POST /chat/completions`
- Auth: `Authorization: Bearer <AI Studio API key>` — a **static** string.

Minimal streaming body:

```json
{ "model": "gemini-2.5-flash",
  "messages": [{"role":"system","content":"…"},{"role":"user","content":"…"}],
  "stream": true, "max_tokens": 150, "temperature": 0.2 }
```

REPORTED (github issue `twentyhq/twenty#16213`, and Google's developer blog summary): the
endpoint supports Chat Completions and Embeddings; **`store` and `stream_options` are
rejected**. So an OpenAI-shaped client that sends `stream_options: {"include_usage": true}`
to get token counts back — which is how you would price a call — errors. That is a real
adapter cost, not a formality.

### 5.2 Vertex, OpenAI-compatible surface

REPORTED, 22 Aug 2026 (summaries of `docs.cloud.google.com/vertex-ai/generative-ai/docs/start/openai`
and `.../migrate/openai/auth-and-credentials`; hosts blocked):

- Base URL: `https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}/endpoints/openapi`
  — identical to `vertex_openai_base_url()` as D-400 recorded it.
- `ENDPOINT_ID` is the literal `openapi` for Gemini models.
- Auth: OAuth2 access token, **~1 hour default TTL**, from a service-account JSON or ADC.

So D-404's whole finding is re-confirmed: **Vertex takes a rotating bearer, the Developer API
takes a static key, and that difference is the entire reason D-404 needed a cron and D-410
deleted it.** Rebuilding a Vertex leg rebuilds the rotation machinery D-410 deleted, in full.

---

## 6. What the engine supports

All **VERIFIED-VENDOR-DOCS**, `bolna-findings/mirror/` (never edited by this lane):

- `pages/providers.md:105-108` — Google Gemini takes **one** credential entry: `GOOGLE`,
  "Your Google Gemini API key". Compare Azure OpenAI at `providers.md:96-102`, which takes
  four. One key ⇒ this is the AI Studio / Developer API path. **D-401's central finding is
  re-verified in the mirror, and it is verified in the credential table, which is the
  machine-readable half rather than a matrix label** (the D-417 distinction).
- `pages/providers/llm-model/gemini.md:20-24` — wire value `"provider": "google"`,
  `"model": "gemini-2.5-flash"`. `gemini.md:28,79` — "To use your own Google API key, connect
  it at platform.bolna.ai/auth/google… API costs will be charged to your Google account."
  **There is no project field, no location field, no `base_url`.** A region is not merely
  unset in Bolna's Google provider; it is unexpressible — the same finding D-407 made against
  their source, now confirmed against their docs.
- `gemini.md:34-43` — models offered: `gemini-3.5-flash`, `gemini-3.1-pro`,
  `gemini-3.1-flash-lite`, `gemini-2.5-pro`, **`gemini-2.5-flash` (marked "Recommended —
  proven, stable, fast")**, `gemini-2.5-flash-lite`. Bolna is recommending, as of this
  mirror, the model Google retires on 16/20 Oct 2026.
- `pages/providers.md:112-135` — the `custom` route: `provider: "custom"` plus an
  OpenAI-compatible `base_url`. Still the only route in which a regional Vertex URL could be
  expressed, and its credential path is the one retired gate 16c never verified.

**Therefore, on the in-call leg, the engine offers exactly two Gemini shapes**: `provider:
"google"` (Developer API, no region, refused by D-401/D-406/D-407 on residency) or
`provider: "custom"` with a Vertex regional URL and a 1-hour bearer (the D-404 machinery
D-410 deleted). Nothing in Google's 2026 terms changes which two shapes exist.

---

## 7. What a human must open to upgrade §2 out of REPORTED

Both hosts are egress-blocked here; neither can be closed from inside this container.

1. `https://ai.google.dev/gemini-api/terms` — confirm which paragraph the "human reviewers
   may read, annotate, and process your API input and output" sentence sits in, and record
   the effective date. This is the single sentence the whole question turns on (§2.2 ⚠).
2. `https://cloud.google.com/vertex-ai/generative-ai/docs/data-governance` — confirm the
   "Invoiced Cloud Billing account" carve-out for abuse-monitoring logging (§2.4), because it
   decides whether an SMB-scale Vertex account can claim no prompt logging at all.

---

## 8. Conclusions

1. **The free-tier data-use objection is real, is confirmed, and is a free-tier objection.**
   Paid Developer API terms state Google does not use prompts or responses to improve its
   products; the human-reviewer-for-quality clause is reported as scoped to Unpaid Services,
   with a narrower 55-day abuse-log clause on paid, and an application-based ZDR route on top.
   D-401 already said this ("only ONE of them survives the founder paying"). **That row was
   right and remains right.**
2. **The residency objection is untouched by any of it.** The Developer API has no region in
   the host, no region in the path, and no field to ask for one, in 2026 as in D-401. For a
   phone call the transcript is the inference input, so a data-use commitment without a
   processing region does not answer DPDP or the DPA. **The refusal in D-401/D-406/D-407
   stands on its own, unchanged, and `test_a_bolna_google_provider_is_never_sent` should
   stay.**
3. **Vertex `asia-south1` is weaker than D-400 believed**: ML processing follows the regional
   endpoint, but the contractual DRZ commitment covers US and EU only, the 24-hour cache is
   on by default, and abuse-log exemption needs Invoiced Cloud Billing.
4. **The model calendar is the new, decisive fact.** `gemini-2.5-flash` — the only
   India-regional Gemini that is fast and cheap enough for voice — retires 16/20 Oct 2026,
   ~8 weeks out. Its named successor is global-only with no residency and 5x the input price;
   the regional successor is 5x/3.6x; and independent voice-agent benchmarking reports the
   whole Gemini 3 generation as too slow for voice (TTFT ~1s against a <700ms requirement).
5. **Do not put caller transcripts through a direct Gemini adapter.** Not on the Developer
   API at any tier (no region), and not on Vertex today (it rebuilds the deleted rotation
   machinery, onto a model with a published retirement date and no compliant successor).
6. **A direct Gemini adapter is defensible only on surfaces that never see caller data**, and
   this repository does not currently have one: the dashboard-AI leg is over redacted data
   but is still client data (D-127 G-1..G-7 bind it), and the first post-call extraction pass
   reads the RAW transcript and is pinned to Sarvam permanently (D-410, `GEMINI_EXTRACTION_DEFAULT
   is False`). There is no third surface. **So the honest answer is: build nothing.**
7. If the founder wants this reopened, the thing to reopen is not the adapter but **D-410's
   choice of vendor**, with the §7 attestations in hand, and it is a founder + DPA decision,
   never an implementation shortcut — the same sentence D-406 ends on.

## Sources

- https://ai.google.dev/gemini-api/terms (EGRESS-BLOCKED; REPORTED via search summaries, 22 Aug 2026)
- https://ai.google.dev/gemini-api/docs/usage-policies (EGRESS-BLOCKED; REPORTED)
- https://ai.google.dev/gemini-api/docs/zdr (EGRESS-BLOCKED; REPORTED)
- https://ai.google.dev/gemini-api/docs/logs-policy (EGRESS-BLOCKED; REPORTED)
- https://cloud.google.com/vertex-ai/generative-ai/docs/data-governance (301 → blocked host; REPORTED)
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/data-residency (EGRESS-BLOCKED; REPORTED)
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/locations (EGRESS-BLOCKED; REPORTED)
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start/openai (EGRESS-BLOCKED; REPORTED)
- https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/api-management/openai-compatible-google-gemini-api.md (READ 22 Aug 2026)
- https://github.com/twentyhq/twenty/issues/16213 (REPORTED)
- https://github.com/google-gemini/gemini-cli/issues/27984 (REPORTED; the D-404 global-endpoint short-circuit)
- https://benchr.org/deprecations/gemini-2-5-pro (REPORTED)
- https://github.blog/changelog/2026-07-02-upcoming-deprecation-of-gemini-2-5-pro-and-gemini-3-flash/ (REPORTED)
- https://gcpstudyhub.com/blog/google-is-retiring-gemini-2-5-on-agent-platform-what-you-need-to-know-and-do-before-october-2026 (REPORTED)
- https://x.com/kwindla/status/2056959360837030344 (REPORTED; voice-agent TTFT)
- https://artificialanalysis.ai/models/gemini-2-5-flash-lite, .../gpt-4o-mini (EGRESS-BLOCKED; REPORTED)
- https://kie.ai/blog/what-is-gemini-3-6-flash, https://www.requesty.ai/models/vertex/gemini-3.6-flash (REPORTED)
- `bolna-findings/mirror/pages/providers.md:96-135`, `pages/providers/llm-model/gemini.md:20-43,79`,
  `pages/concepts/latency.md:66-69,127`, `pages/concepts/choosing-providers.md:55,71-72` (VERIFIED-VENDOR-DOCS)
