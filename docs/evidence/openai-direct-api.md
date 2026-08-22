# OpenAI direct — the API as it actually is on 22 Aug 2026

**Lane.** L1. Question: what would a **direct OpenAI adapter** cost us and buy us, on the
two surfaces that would use one — the **in-call leg** (Bolna holds our key, BYOK) and the
**dashboard/worker leg** (we make the HTTP call ourselves, over redacted data). Today both
run on Azure OpenAI in South India (D-410, D-417).

**Date read: 22 August 2026.** Every claim below carries its source and its evidence class.

---

## 0. What the egress proxy blocked, and what that does to this report

**Every OpenAI-owned documentation host is blocked in this environment.** Measured
22 Aug 2026, both through `curl` and through the fetch tool, which use different egress
paths and agreed:

| Host | Result |
| --- | --- |
| `platform.openai.com` | `CONNECT` → **403**; fetch tool → `EGRESS_BLOCKED` |
| `developers.openai.com` | blocked (both paths) |
| `openai.com` (incl. `/api/pricing/`, `/enterprise-privacy/`) | blocked (both paths) |
| `help.openai.com` | blocked (both paths) |
| `cookbook.openai.com` | blocked |
| `api.openai.com` | blocked — **we cannot make a live call to verify anything** |
| `status.openai.com` | blocked |

So **the pricing page, the API reference, the data-controls guide, the enterprise-privacy
page and the DPA were all unreadable directly.** Anything sourced from them below is
**REPORTED** — search-engine summaries and third-party pages — and is marked as such.

**Two first-party sources were reachable and carry the load of this report:**

1. **`pypi.org/pypi/openai/json`** — package metadata (HTTP 200).
2. **`github.com/openai/openai-python`**, cloned shallow to
   `/home/user/openai/openai-python` at `main`, 22 Aug 2026. This is **OpenAI's own
   repository**, and critically its `src/openai/types/**` files carry the header
   *"File generated from our OpenAPI spec by Castiron"* — they are a **mechanical
   projection of the OpenAPI specification**, not prose. For wire values, model
   identifiers and enum membership this is the **strongest** evidence class available,
   stronger than the docs site: it is the machine-readable value, not a human-readable
   label. That is precisely the distinction D-417 was written about — `"azure"` vs
   `"azure-openai"` was a label read where a wire value was needed. Class:
   **VERIFIED-VENDOR-DOCS**.

**What this means for the report's shape.** The wire contract, the model list, the
regional endpoints, the auth headers and the SDK version are **hard**. Prices, retention
periods, ZDR terms, rate-limit numbers and the SLA are **REPORTED** and must not be
written into code or contracts without a human opening the blocked pages.

---

## 1. The wire contract

### 1.1 Responses is the primary API; Chat Completions is not being taken away

> "The primary API for interacting with OpenAI models is the **Responses API**."
> "The previous standard (**supported indefinitely**) for generating text is the Chat
> Completions API."
>
> — `openai/openai-python`, `README.md:27,47`, read 22 Aug 2026.
> Class: **VERIFIED-VENDOR-DOCS**.

The phrase **"supported indefinitely"** is the vendor's own, in their own README, and it
is the answer to the migration-risk question: **Chat Completions carries no sunset.** What
*was* deprecated is the **Assistants API** (sunset 26 Aug 2026 — REPORTED, multiple
third-party pages incl. a Microsoft Q&A thread), which is a different thing and is not on
any path we would take. Responses is "recommended for all new projects" (REPORTED, search
summary of `platform.openai.com/docs/guides/migrate-to-responses`, blocked to us).

**Read for us:** a direct adapter should be written against **Responses**. Chat Completions
is the safe fallback and is not a liability.

### 1.2 Endpoints

From `openai/openai-python`, `src/openai/resources/responses/api.md:167-171,183,195` and
`api.md:94-98,104` (the HTTP verb and path are in each entry's `title=` attribute), read
22 Aug 2026. Class: **VERIFIED-VENDOR-DOCS**.

```
POST   /responses                      create           (stream=true supported)
GET    /responses/{response_id}        retrieve
DELETE /responses/{response_id}        delete           <-- see §4.5
POST   /responses/{response_id}/cancel cancel
POST   /responses/compact              compact
GET    /responses/{response_id}/input_items
POST   /responses/input_tokens         count input tokens without generating

POST   /chat/completions               create
GET    /chat/completions/{id}          retrieve
DELETE /chat/completions/{id}          delete
```

Base URL is `https://api.openai.com/v1` (§3.1). Note this is the **same shape** as the
Azure v1 surface we already build in `azure_openai_base_url()` — `.../openai/v1` — which
is why an adapter is cheap: the path suffixes are identical.

### 1.3 Minimal streaming request body for one voice turn

Field names and types taken from
`src/openai/types/responses/response_create_params.py` (generated from the OpenAPI spec),
read 22 Aug 2026. Class: **VERIFIED-VENDOR-DOCS**.

```http
POST https://api.openai.com/v1/responses
Authorization: Bearer sk-...
Content-Type: application/json

{
  "model": "gpt-5.4-mini",
  "instructions": "<composed system prompt>",
  "input": "<caller utterance>",
  "stream": true,
  "max_output_tokens": 150,
  "reasoning": { "effort": "none" },
  "service_tier": "default",
  "store": false,
  "prompt_cache_key": "<tenant/agent scoped, NOT a phone number>",
  "safety_identifier": "<hash, never raw identity>"
}
```

Every field above is a real member of the create-params model. Notes that matter:

- **`input` accepts a bare string** (`input: Union[str, ResponseInputParam]`,
  `response_create_params.py:84`) — no `messages` array needed for a simple turn. The
  system prompt goes in **`instructions`** (`:96`), a separate top-level field, not a
  message with `role: "system"`.
- **`store`** — *"Whether to store the generated model response for later retrieval via
  API"* (`:243-244`). **This is the retention switch on our side of the wire.** See §4.
- **`safety_identifier`** — *"a stable identifier ... We recommend hashing their username
  or email address, **in order to avoid sending us any identifying information**"*
  (`:206-213`). The vendor themselves tell you to hash it. A raw E.164 here would violate
  Hard Rule 6 and their own guidance simultaneously.
- **`prompt_cache_key`** — *"Replaces the `user` field"* (`:158-162`). The legacy `user`
  field (`:322`) still exists; do not use it.

### 1.4 Streaming semantics

**Server-Sent Events.** `README.md:347-349`: *"We provide support for streaming responses
using Server Side Events (SSE)."* Class: **VERIFIED-VENDOR-DOCS**.

The stream is a **typed event stream, not a delta-only stream** — there are **59** distinct
`response_*_event.py` types in `src/openai/types/responses/`. The one that carries spoken
text is:

```python
class ResponseTextDeltaEvent(BaseModel):
    """Emitted when there is an additional text delta."""
    content_index: int
    delta: str            # <-- the text
    item_id: str
    logprobs: List[Logprob]
    output_index: int
    sequence_number: int  # <-- monotonic; use for ordering/dedupe
    type: Literal["response.output_text.delta"]
```

— `src/openai/types/responses/response_text_delta_event.py:35-58`, read 22 Aug 2026.
Class: **VERIFIED-VENDOR-DOCS**.

**This is a genuine difference from Chat Completions and an adapter must not paper over
it.** Chat Completions streams `choices[0].delta.content`; Responses streams *typed
events* with an explicit `sequence_number` and lifecycle events
(`response.created` → `response.in_progress` → deltas → `response.completed`). For a voice
runtime the `sequence_number` is a gift — it gives ordering and duplicate detection for
free, which the Chat Completions stream does not.

`stream_options` exists (`:246-247`) and includes `include_obfuscation: bool` (`:405`).

---

## 2. Models available today

### 2.1 The authoritative list

`src/openai/types/shared/chat_model.py` and `.../responses_model.py`, generated from the
OpenAPI spec, read 22 Aug 2026. Class: **VERIFIED-VENDOR-DOCS**. This is the *complete*
enum; anything not in it is not a current model identifier.

Current generation (families, newest first):

| Identifier | Notes |
| --- | --- |
| `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna` | newest generation; **no `-mini`/`-nano` in the 5.6 line** |
| `gpt-5.6-cyber` | present in `ResponsesModel`/`AllModels` only, not `ChatModel` |
| `gpt-5.5`, `gpt-5.5-2026-04-23` | flagship 5.5 |
| `gpt-5.5-pro`, `gpt-5.5-pro-2026-04-23` | Responses-only |
| `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.4-nano` (all `-2026-03-17`) | **the current small/fast tier lives here** |
| `gpt-5.3-chat-latest` | |
| `gpt-5.2`, `gpt-5.2-pro`, `gpt-5.1`, `gpt-5.1-mini`, `gpt-5.1-codex`, `gpt-5.1-codex-max` | |
| `gpt-5`, `gpt-5-mini`, `gpt-5-nano` (`-2025-08-07`) | |
| `gpt-4.1`, `gpt-4.1-mini`, `gpt-4.1-nano` | **still present** — our `AZURE_OPENAI_DEFAULT_MODEL` peers |
| `gpt-4o`, `gpt-4o-mini` | still present |
| `gpt-daybreak-blue-latest`, `gpt-daybreak-red-latest` | Responses-only, undocumented to us |

**The structurally important fact for us:** there is **no `gpt-5.5-mini` and no
`gpt-5.6-mini`**. The newest *cheap-and-fast* identifier is **`gpt-5.4-mini`**, dated
`2026-03-17`. A design that assumes "there will always be a mini of the newest flagship"
is wrong against this list.

Still listed (not removed): the whole `o1`/`o3`/`o4-mini` reasoning line, `gpt-4-turbo`,
`gpt-4`, `gpt-4-32k` and the entire `gpt-3.5-turbo` family. **Presence in this enum is not
a statement that a model is a good idea** — `gpt-3.5-turbo-0301` is in there.

**Deprecation seen in-flight:** `openai-python` 3.1.0 (14 Aug 2026) shipped
*"**api:** deprecate Sora video APIs"* (`CHANGELOG.md`, PR #3610). Not our surface, but it
shows the deprecation channel is live and lands in the SDK changelog — that is a cheap
thing for us to watch, and it is reachable from here when the docs site is not.

### 2.2 Prices — **REPORTED, and this is the weakest section in the file**

`openai.com/api/pricing/` is blocked. The following is a **search-engine summary of
third-party pricing trackers**, read 22 Aug 2026. USD per 1M tokens.

| Model | Input | Cached input | Output |
| --- | --- | --- | --- |
| `gpt-5.6-sol` | $5.00 | $0.50 | $30.00 |
| `gpt-5.6-terra` | $2.00 | — | $12.00 |
| `gpt-5.6-luna` | $0.20 | — | $1.20 |
| `gpt-5.5` | $5.00 | — | $30.00 |
| `gpt-5.4` | $2.50 | — | $15.00 |
| `gpt-5.4-mini` | $0.75 | — | $4.50 |
| `gpt-5.4-nano` | $0.20 | — | $1.25 |

Sources (all third-party): `morphllm.com/openai-api-pricing`, `devtk.ai`,
`aipricing.guru/openai-pricing/`, `cloudzero.com/blog/openai-pricing/`.
Class: **REPORTED**. The trackers agree with each other, which raises confidence but does
not change the class — they may share an upstream. **Do not put these numbers in
`unit_cost_paid` (Hard Rule 7) until a human reads the pricing page.**

One structural observation that *is* checkable and worth recording: on the 5.6 family
**output is exactly 6× input** at every tier. `gpt-5.6-luna` at $0.20/$1.20 is roughly
**one quarter the input price of `gpt-5.4-mini`** while being a newer model — if that
holds, the cheap tier moved and `gpt-5.4-mini` is no longer the cost floor.

### 2.3 Context windows — **REPORTED, but corroborated in-tree**

Bolna's own mirror carries a context table
(`bolna-findings/mirror/pages/providers/llm-model/openai.md:38-50`, class
**VERIFIED-VENDOR-DOCS** for *Bolna's* claim about OpenAI, which is second-hand as to
OpenAI):

- `gpt-5.6-*`, `gpt-5.5`, `gpt-5.5-pro`, `gpt-5.4`, `gpt-4.1`, `gpt-4.1-mini` — **1M tokens**
- `gpt-5.4-mini` — **400K tokens**
- `gpt-4o` — **128K tokens**

Every one of these is far beyond a phone call. Context window is **not** a decision input
for the in-call leg; it might matter for dashboard summarization over long transcripts.

---

## 3. Latency and regions — **the section that decides the in-call leg**

### 3.1 The named regional endpoints, exhaustively

This is the single most valuable finding in the lane, and it is **VERIFIED-VENDOR-DOCS of
the strongest kind** — machine-readable, generated from the OpenAPI spec, four days old.

`openai-python` **3.3.0** (18 Aug 2026) shipped
*"**feat:** support named data-residency endpoints"* (`CHANGELOG.md`, PR #3646). The
implementation, in full, from `src/openai/_data_residency.py`, read 22 Aug 2026:

```python
DataResidency = Literal["global", "us", "eu", "ae"]

_DATA_RESIDENCY_BASE_URLS: dict[DataResidency, str] = {
    "global": "https://api.openai.com/v1",
    "us":     "https://us.api.openai.com/v1",
    "eu":     "https://eu.api.openai.com/v1",
    "ae":     "https://ae.api.openai.com/v1",
}
```

and its contract test pins the set closed:

```python
def test_public_type() -> None:
    assert set(get_args(DataResidency)) == {region for region, _ in REGIONS}
```

— `tests/test_data_residency_contract.py:13-19,27-29`.

> **There are exactly four named endpoints: `global`, `us`, `eu`, `ae`.
> There is no India endpoint. There is no `in.api.openai.com`.**
> An invalid region does not reach the network — `resolve_data_residency` raises
> `ValueError("Invalid `data_residency`; expected one of 'global', 'us', 'eu', or 'ae'")`
> locally (`_data_residency.py:38-39`, and `test_unknown_regions_fail_locally`).

Also pinned by the same module: `data_residency` is **mutually exclusive** with `base_url`,
`websocket_base_url` and `provider` (`:30-37`). You cannot half-configure it, and you
cannot point a "residency" client at your own gateway. That is good hygiene on their part
and it means the setting is honest.

**This is a residency guard we could actually assert on**, in the same spirit as
`scripts/check_model_residency.py`: unlike `<resource>.openai.azure.com`, which names no
region and forced us into human portal attestation (gates 20 / 20c), `eu.api.openai.com`
puts the region **back in the hostname**. The irony is complete and useless to us: the
region we need is the one that does not exist.

### 3.2 Where inference actually runs

**REPORTED**, from search summaries of `openai.com/index/introducing-data-residency-in-asia/`,
`openai.com/index/expanding-data-residency-access-to-business-customers-worldwide/`,
`help.openai.com/en/articles/9903489-...`, `computerworld.com/article/4096675/`,
`techcrunch.com/2025/05/08/...`, `dig.watch`, read 22 Aug 2026 — all hosts blocked to us:

- **At-rest data residency** covers a long list including **India**, expanded 27 Oct 2025,
  explicitly aimed at DPDP localisation.
- **Inference residency is a separate, much shorter list.** On **16 Jan 2026** OpenAI added
  in-region **GPU inference** — **US or Europe only** — and **that did not extend to India**.
- The consistent phrasing across sources: the residency expansion targets *"data that is
  stored or is at rest and **not** data that is being used for inference by a model, whose
  default location continues to be the **US**."*

**The SDK corroborates this independently and mechanically.** If India had inference
residency, there would be an `in` entry in `_DATA_RESIDENCY_BASE_URLS`. There is not. Two
sources of different classes agreeing is the strongest position available under the
blockade.

> ### The distinction that decides this
>
> **D-410's record is CONFIRMED and unchanged as of 22 Aug 2026: OpenAI's India residency
> covers storage at rest only; inference runs outside India.**
>
> For a phone call this is not a technicality. The caller's speech, transcribed, **is the
> inference input**. There is no state in which the transcript is "at rest in India" and
> also being reasoned over — it is in the request body, and the request body goes to a US
> GPU. Storage-at-rest residency describes what happens to a copy *afterwards*. It says
> nothing about the leg that matters.
>
> Note also: even the *at-rest* India option is described in every source as attaching to
> **ChatGPT Enterprise/Edu workspaces and eligible API projects** via a Project setting —
> i.e. it is an account-level entitlement, not a request parameter. Nothing in the wire
> contract of §1 lets a caller assert it per-request.

### 3.3 TTFT — the reasoning dial dominates everything else

`service_tier` is a real request field. Its complete value set, from
`src/openai/types/responses/service_tier.py` (generated), read 22 Aug 2026, class
**VERIFIED-VENDOR-DOCS**:

```python
ServiceTier = Optional[Literal["auto", "default", "flex", "scale", "priority", "fast", "ultrafast"]]
```

and its own documentation, from `src/openai/types/responses/response.py:405-423`:

- `auto` — uses the **Project setting**; unless configured, `default`.
- `default` — standard pricing and performance.
- `flex` — Flex Processing (cheaper, slower).
- `fast` / `priority` — *"opt-in to Fast mode at the request level"*; **the response
  reports `service_tier=priority` regardless of which of the two you sent** — a real
  gotcha for anything that asserts the echo equals the request.
- `ultrafast` — *"the **access-controlled** Ultrafast Processing service tier. This tier is
  currently available for **`gpt-5.6-sol`**"*.

Two things follow. **`ultrafast` is gated and bound to the most expensive model in the
lineup** ($5/$30 per 1M, REPORTED) — it is not a cheap latency win. And `auto` reads a
**Project-level** setting, which means the latency tier of a call can be changed by
somebody in a dashboard without touching our config; if we ever use this, pin it
explicitly, never `auto`.

**Measured TTFT — REPORTED**, Artificial Analysis via search summary, `gpt-5.6-luna`,
read 22 Aug 2026 (`artificialanalysis.ai/models/gpt-5-6-luna-*/providers`):

| reasoning effort | time to first **answer** token |
| --- | --- |
| low | **1.85 s** |
| high | 16.98 s |
| xhigh | 43.02 s |
| max | 137.80 s |

These are third-party and include reasoning tokens before the first answer token, so they
are not a clean network TTFT. **But the shape is unambiguous and it is corroborated
first-hand in our own tree**: Bolna's mirror says *"Reasoning effort is usually the biggest
single lever"* and *"For live calls, stay at `none` or `low`. Each step up adds reasoning
tokens before the first spoken word, which lands directly in time-to-first-token"*
(`bolna-findings/mirror/pages/providers/llm-model/openai.md:93,117`).

**Even the best row is 1.85 s at `low`.** For a phone turn that is already at the edge.
`reasoning.effort = "none"` is not a tuning preference on this product — it is a
requirement, and any adapter must set it explicitly rather than inherit a default.

**Physical latency is not in these numbers.** India → US round trip is ~200–250 ms
baseline on every one of the (typically several) turns in a call, and it is unavoidable
because there is no India endpoint (§3.1). Azure South India does not pay it. Nothing in
the model choice recovers it.

---

## 4. Data use, retention and deletion

**This whole section is REPORTED.** `openai.com/enterprise-privacy/`,
`developers.openai.com/api/docs/guides/your-data` and the DPA were all blocked. Sources are
search-engine summaries of those pages plus third-party trackers, read 22 Aug 2026. **None
of it is contract-grade. A human must open these pages before we rely on any of it.**

### 4.1 Training

Consistent across every source: **API data is not used to train models by default**, and
business/Enterprise data requires explicit opt-in. Enterprise and Team accounts operate
under a DPA that contractually prohibits training on organizational data.
Sources: `openai.com/enterprise-privacy/` (summarised), `meetily.ai/llm-privacy/openai`,
`usercentrics.com`, `januscompliance.co.uk`. Class: **REPORTED**.

### 4.2 Default retention

**Up to 30 days** for API inputs and outputs, for abuse monitoring, then deleted "unless we
are legally required to retain them". Access during that window is restricted to authorized
employees and **specialized third-party contractors under confidentiality agreements** for
engineering support, abuse investigation and legal compliance. Class: **REPORTED**, same
sources.

**Flag for the compliance lane:** "third-party contractors may review content" is a
**sub-processor disclosure** under DPDP, and 30 days is a **retention floor we do not
control**. Both need to appear in any DPA analysis; neither is exotic (Azure has an
analogous abuse-monitoring window) but neither can be assumed away.

### 4.3 Zero Data Retention

**REPORTED**, sources: `openai.com/index/offering-zero-data-retention-for-frontier-models/`
(blocked, summarised), `theregister.com` 20 Aug 2026 (blocked, summarised),
`axios.com` 19 Aug 2026, `gbhackers.com`, `scalevise.com`, `casrai.org`.

- ZDR means prompts and responses are **not retained after the request is processed**, and
  content is not available to OpenAI personnel for review.
- **ZDR is endpoint-specific, not account-wide.** Approval for one endpoint does not cover
  every product. This is the detail most likely to bite: an adapter could be ZDR on
  `/responses` and not on something else it also calls.
- Eligibility is **enterprise/API customers with a qualifying use-case, by approval** — not
  a checkbox.
- **Announced 19 Aug 2026 (three days ago): "Private Safety Processing"**, extending ZDR to
  frontier models while still doing abuse detection — pattern detection across related
  interactions without personnel access to content. **This is brand new and moving.**
  Anything written about ZDR today has a short shelf life.

### 4.4 ZDR collides with the newest models — first-party, and nobody would guess it

This one is **VERIFIED-VENDOR-DOCS** and it is the sharpest thing in §4. From
`src/openai/types/responses/response_create_params.py:179-197`, read 22 Aug 2026,
documenting `prompt_cache_retention`:

> *"For `gpt-5.5`, `gpt-5.5-pro`, and future models, **only `24h` is supported**."*
>
> *"For older models that support both `in_memory` and `24h`, the default depends on your
> organization's data retention policy: Organizations without ZDR enabled default to `24h`.
> **Organizations with ZDR enabled default to `in_memory`** when `prompt_cache_retention`
> is not specified."*

**Read that pairing carefully.** ZDR's behaviour on the prompt cache is to fall back to
`in_memory`. But on `gpt-5.5` **and every model after it**, `in_memory` is not available —
**only `24h` is**. So on the newest models a **prompt prefix can persist for up to 24 hours
in a cache**, and the ZDR-implied `in_memory` escape does not exist there.

For a caller transcript this is exactly the wrong direction: the prompt prefix on an
in-call turn contains the conversation so far. **Whether ZDR overrides this, refuses these
models, or coexists with a 24h cache is not answerable from any source we can reach**, and
it is the single most important thing a human should ask OpenAI directly. It is also not a
question anyone would think to ask from the marketing pages — it only surfaces in a
generated type stub.

### 4.5 Hard deletion on request

There **is** a real deletion primitive at the API level:

```
DELETE /responses/{response_id}
DELETE /chat/completions/{completion_id}
```

— `src/openai/resources/responses/api.md:169`, `api.md:98`, read 22 Aug 2026. Class:
**VERIFIED-VENDOR-DOCS**.

And there is a way to never create the object: **`store: false`** on the request
(`response_create_params.py:243-244`).

**But note precisely what these do and do not cover.** They delete the *stored response
object* — the thing you opted into with `store: true`. They say **nothing** about the
30-day abuse-monitoring copy (§4.2), which is a separate retention path on OpenAI's side.
`store: false` + `DELETE` gives us a clean story for the **retrievable** artifact; it does
**not** by itself discharge a DPDP erasure obligation against the abuse-monitoring copy.
**Only ZDR appears to address that**, and ZDR's terms are REPORTED and approval-gated.

**Our operating posture would have to be `store: false` on every call**, because the
alternative is that OpenAI holds a retrievable copy of a caller transcript that our
deletion pipeline has to know about and reach. That is a whole erasure surface we do not
currently have with the Azure leg, and the cheapest way to not have it is to never create
it.

---

## 5. Rate limits and reliability — **REPORTED**

Sources: search summaries of `platform.openai.com` limits docs (blocked) plus
`inference.net/content/openai-rate-limits-guide/`, `codewords.ai`, `devtk.ai`,
`scriptbyai.com`, `respan.ai`, read 22 Aug 2026.

- **Four independent dimensions**: RPM, TPM, RPD, TPD. Exceeding **any one** returns 429.
- **Tiers are gated on cumulative spend**, not time. Illustrative (older model, but the
  shape is the point): Tier 1 ≈ 500 RPM / 30K–200K TPM; Tier 5 ≈ 10,000 RPM / 30M TPM.
- **429 carries `x-ratelimit-remaining-*` and `retry-after-ms` headers.** Read them; do not
  invent a backoff.
- **Uptime SLA: 99.9% monthly, and only on Scale Tier / negotiated Enterprise.**
  Pay-as-you-go has **no contractual uptime guarantee**. The SLA explicitly **excludes
  latency and throughput on all tiers** — i.e. there is *no* commitment on the one property
  that matters for a phone call. Remedy is service credits, claimed by the customer with
  evidence, not automatic.

**Client-side reliability is first-party and good** (`README.md:728-733,757-758`, class
**VERIFIED-VENDOR-DOCS**): the SDK retries **2 times by default with exponential backoff**,
on connection errors, **408, 409, 429 and ≥500**. Default timeout is **10 minutes** —
**absurd for a voice turn and it must be overridden**; timed-out requests are themselves
retried twice, so a naive config can burn 30 minutes on one turn.

**Tier-1 exposure is the practical risk for us**, not the SLA: a new account starts at the
bottom tier, and a campaign dispatch burst is exactly the traffic shape that finds an RPM
ceiling.

---

## 6. SDK and auth

All **VERIFIED-VENDOR-DOCS**, read 22 Aug 2026.

**Package**: `openai`, **version 3.3.1**, published **2026-08-19**, `requires_python
>=3.10` (`pypi.org/pypi/openai/json`). Compatible with our Python 3.12.

**Release cadence is fast and should be pinned**: 2.49.0 → 3.3.1 in **23 days**
(`CHANGELOG.md`). Twelve releases in under a month.

**⚠ `openai` 3.0.0 (12 Aug 2026) is a BREAKING major**, and it is the kind that breaks
things adjacent to it. From `CHANGELOG.md`:

> **⚠ BREAKING CHANGES** — *"**HTTPX2 is now the default HTTP client, and `httpx` is no
> longer installed automatically.** Applications using custom HTTPX clients, transports, or
> configuration objects must migrate to their HTTPX2 equivalents or use the temporary,
> runtime-only legacy HTTPX escape hatch."*

The SDK now imports `httpx2` throughout (visible in `_data_residency.py`, `_client.py`) and
`timeout` takes an `httpx2.Timeout`. **This is a dependency-tree event, not just an API
change** — anything in our tree that pins or configures `httpx` interacts with it, and the
escape hatch is described by the vendor as *temporary*. It is also a **supply-chain item
under Hard Rule 9**: `httpx2` is a new transitive dependency arriving via a major bump,
and 3.3.1's own release notes are *"**deps:** update dependencies with published security
fixes"*.

**Auth** — `src/openai/_client.py:584,610-611`:

```python
{"Authorization": f"Bearer {api_key}"}
{
  "OpenAI-Organization": self.organization if self.organization is not None else Omit(),
  "OpenAI-Project":      self.project      if self.project      is not None else Omit(),
}
```

- **One static bearer token.** No `api-version`, no deployment-name indirection, no key
  rotation machinery.
- **`OpenAI-Organization` / `OpenAI-Project` are OPTIONAL** — omitted entirely when unset.
  Needed only to disambiguate a multi-org/multi-project key. **But note §3.2 and §3.3: the
  residency entitlement and the `service_tier: auto` default are both described as
  *Project* settings**, so if we ever depend on either, the project header stops being
  optional in practice.
- Env vars (`_client.py:185-190`): `OPENAI_API_KEY`, `OPENAI_ADMIN_KEY`, `OPENAI_ORG_ID`,
  `OPENAI_PROJECT_ID`, `OPENAI_WEBHOOK_SECRET`, `OPENAI_BASE_URL`. **All six must be added
  to `tests/conftest._no_ambient_credentials`** if we adopt this — derived, not retyped
  (CLAUDE.md Hard Rule 10).
- **New in 3.x: workload identity** (`README.md:74-228`) — K8s service-account tokens,
  Azure managed identity, GCP ID tokens, X.509 mTLS (which defaults to
  `https://mtls.api.openai.com/v1`). Removes the long-lived-key problem where the caller
  can hold a cloud identity. **Irrelevant to the in-call leg** — Bolna holds the key there
  and cannot present our workload identity — but genuinely interesting for the worker leg.

**Errors** (`README.md:684-693`) — typed by status, which maps cleanly onto our RFC-9457
ladder:

| Status | Exception |
| --- | --- |
| 400 | `BadRequestError` |
| 401 | `AuthenticationError` |
| 403 | `PermissionDeniedError` |
| 404 | `NotFoundError` |
| 422 | `UnprocessableEntityError` |
| 429 | `RateLimitError` |
| ≥500 | `InternalServerError` |
| — | `APIConnectionError`, `APITimeoutError` |

Every response object carries `_request_id` from the `x-request-id` header
(`README.md:695-714`) — **an id, not content, so it is safe to log under Hard Rule 6** and
should be logged on every failure.

---

## 7. The in-call leg: what Bolna actually needs

This is checkable **in-tree**, against the mirror, and it is the one place where OpenAI
direct is unambiguously *simpler* than what we have. Class: **VERIFIED-VENDOR-DOCS**
(mirror, SHA-256 in `MANIFEST.json`), read 22 Aug 2026.

**Credentials — one entry versus four.**
`bolna-findings/mirror/pages/providers.md:83-87`:

| Property | Description |
| --- | --- |
| `OPENAI` | Your OpenAI API key |

against `providers.md:96-102` for Azure — `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_MODEL`,
`AZURE_OPENAI_API_BASE`, `AZURE_OPENAI_API_VERSION`.

**The friction claim in the brief is confirmed, and so is the specific unknown.** The
store is `{provider_name, provider_value}`, so Azure is **four** `POST /providers` calls
and OpenAI direct is **one** — and that one credential has **no `AZURE_OPENAI_API_VERSION`
analogue**, which means **adopting OpenAI direct would close OPERATIONS §2 gate 16f by
deleting the field rather than answering it.** It would also delete the deployment-name
indirection entirely: `"model": "gpt-5.4-mini"` is the model, not an id someone chose in a
portal that resolves back to a model.

**Wire config** (`providers/llm-model/openai.md:17-27`):

```json
"llm_agent": {
  "agent_type": "simple_llm_agent",
  "agent_flow_type": "streaming",
  "llm_config": {
    "provider": "openai",
    "model": "gpt-5.4-mini",
    "max_tokens": 150,
    "temperature": 1
  }
}
```

`provider` is **`"openai"`** — lowercase, in a JSON code block, i.e. the machine-readable
form, which is the evidence class D-417 requires. Note it is **not** the same string as the
credential property (`OPENAI`, uppercase); those are two different namespaces and must not
be derived from one another.

**Three traps recorded in the same page**, each of which would be a live-call defect:

1. **`temperature` must be exactly `1` on all GPT-5 models.** Anything else fails agent
   creation with `400 For GPT-5 models, temperature must be 1`, **and the field defaults to
   `0.1` when omitted** — so it must be sent explicitly (`openai.md:29-31`). A silent
   default of `0.1` means *omitting* the field is the failure mode.
2. **`max_tokens` is sent as `max_completion_tokens` on GPT-5**, and **reasoning tokens
   come out of the same budget** — at effort above `none`, reasoning can consume most of a
   150-token cap and **truncate the spoken reply** (`openai.md:72-75`). Truncating an
   agent's sentence mid-call is a compliance-adjacent failure for us, given Hard Rule 5.
3. **`gpt-5.4`/`5.5`/`5.6` are routed through the Responses API automatically by Bolna**,
   because function calling combined with `reasoning_effort` is rejected on Chat
   Completions for those models (`openai.md:114-116`). Our `custom` tool-calling
   assumptions must be read against Responses semantics, not Chat Completions.

And Bolna's own one-line characterisation of the alternative, in their "Related" list
(`openai.md:149`):

> *"Azure OpenAI — OpenAI models with **enterprise data residency**"*

The vendor whose engine we rent describes the two routes exactly the way this report
concludes.

---

## 8. What we still cannot answer, and what would settle it

Ordered by how much it matters. **None of these is an engineering task** — every one needs
something outside this repo (CLAUDE.md tempo rule: name the external blocker).

1. **Does ZDR permit `gpt-5.5`+ at all, given `prompt_cache_retention` admits only `24h`
   there (§4.4)?** This is the deepest unknown and it came out of a generated type stub, not
   a policy page. **Settles it:** a written answer from OpenAI sales/support on a ZDR
   application. *Blocker: vendor account + ZDR application.*
2. **Exact ZDR scope and eligibility for our use-case, endpoint by endpoint (§4.3).** ZDR
   is per-endpoint and approval-gated, and "Private Safety Processing" is **three days
   old**. **Settles it:** the signed DPA + ZDR addendum naming `/responses`.
   *Blocker: commercial term.*
3. **The DPA's sub-processor list and the third-party-contractor review clause (§4.2).**
   Needed for the DPDP filing regardless of which provider wins. **Settles it:** a human
   reading `openai.com/enterprise-privacy/` and the DPA. *Blocker: blocked host — needs a
   human on an unblocked network, ~10 minutes.*
4. **Real prices (§2.2).** Everything here is third-party. **Settles it:** the same human,
   the same ten minutes, on `openai.com/api/pricing/`. *Blocker: blocked host.* Until then
   nothing from §2.2 may reach `unit_cost_paid`.
5. **Measured TTFT from India to `api.openai.com` at `reasoning.effort: "none"`, on
   `gpt-5.4-mini` and `gpt-5.6-luna`.** Every latency number here is third-party and none
   includes our network path. **Settles it:** one afternoon with a real key from a Mumbai
   host, compared head-to-head against the current Azure South India deployment.
   *Blocker: vendor account.* **This is the only experiment that could change the §3
   conclusion, and it can only narrow the gap, not close it — the India→US round trip is
   physics.*
6. **Whether an India inference region is on the roadmap.** The at-rest India launch
   (Oct 2025) was explicitly DPDP-motivated, and the US/EU inference launch (Jan 2026) shows
   they are building the capability region by region. **Settles it:** ask, on the same sales
   call as (1) and (2). *Blocker: vendor conversation.* **A dated commitment would reopen
   this entire question; nothing else in this file would.**
7. **Whether Bolna's `openai` provider accepts `reasoning_effort: "none"` end to end**, and
   whether their auto-routing to Responses (§7.3) changes the streaming events our
   voice-runtime sees. **Settles it:** the same `GET /providers` → `POST /providers` →
   `GET` sequence already queued for the Azure work, run once against `OPENAI`.
   *Blocker: none — this is ours, and it is API calls.*

---

## 9. Verbatim source list

**VERIFIED-VENDOR-DOCS** — OpenAI's own repository, cloned `main` @ 22 Aug 2026 to
`/home/user/openai/openai-python`; files under `src/openai/types/**` are generated from the
OpenAPI specification:

- `README.md` — 27, 47, 347-349, 684-693, 695-714, 728-733, 757-758, 74-228
- `CHANGELOG.md` — 3.3.1, 3.3.0 (#3646), 3.2.0, 3.1.0 (#3610, #3617), 3.0.0 breaking
- `src/openai/_data_residency.py` — complete file
- `src/openai/_client.py` — 152-197, 584, 610-611
- `src/openai/types/shared/chat_model.py`, `.../responses_model.py`, `.../all_models.py`
- `src/openai/types/responses/response_create_params.py` — 45-322
- `src/openai/types/responses/response.py` — 405-423
- `src/openai/types/responses/service_tier.py`
- `src/openai/types/responses/response_text_delta_event.py` — 35-58
- `src/openai/resources/responses/api.md` — 167-171, 183, 195; `api.md` — 94-98, 104
- `tests/test_data_residency_contract.py` — 13-19, 27-29, 66-71
- `pypi.org/pypi/openai/json` — version 3.3.1, 2026-08-19, `requires_python >=3.10`

**VERIFIED-VENDOR-DOCS** — Bolna mirror, in-tree, SHA-256 per page in `MANIFEST.json`:

- `bolna-findings/mirror/pages/providers.md` — 83-87 (OpenAI), 96-102 (Azure)
- `bolna-findings/mirror/pages/providers/llm-model/openai.md` — 9, 17-31, 38-50, 72-75,
  80-93, 114-116, 117, 149

**REPORTED** — search summaries only; every OpenAI-owned host below was **blocked**:

- `openai.com/api/pricing/` · `openai.com/enterprise-privacy/` ·
  `openai.com/index/offering-zero-data-retention-for-frontier-models/` ·
  `openai.com/index/introducing-data-residency-in-asia/` ·
  `openai.com/index/expanding-data-residency-access-to-business-customers-worldwide/` ·
  `openai.com/api-scale-tier/` · `developers.openai.com/api/docs/guides/your-data` ·
  `developers.openai.com/api/docs/deprecations` ·
  `platform.openai.com/docs/guides/migrate-to-responses` ·
  `help.openai.com/en/articles/9903489-data-residency-and-inference-residency-for-chatgpt`
- Third-party: `morphllm.com/openai-api-pricing` · `devtk.ai` · `aipricing.guru` ·
  `cloudzero.com/blog/openai-pricing/` · `artificialanalysis.ai/models/gpt-5-6-luna-*` ·
  `inference.net/content/openai-rate-limits-guide/` · `codewords.ai/blog/openai-api-rate-limits` ·
  `devhelm.io/sla/openai` · `theregister.com` (20 Aug 2026) · `axios.com` (19 Aug 2026) ·
  `computerworld.com/article/4096675/` · `techcrunch.com/2025/05/08/` · `dig.watch` ·
  `meetily.ai/llm-privacy/openai` · `januscompliance.co.uk` · `usercentrics.com`
