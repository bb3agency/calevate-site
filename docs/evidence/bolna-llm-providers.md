# Bolna LLM providers on the wire — what an OpenAI or Google in-call leg would actually send

**Lane L3.** Subject: hard rule 2. For the in-call leg we never call the model provider —
the engine does, with our key. So the binding contract is not OpenAI's or Google's
documentation; it is what **Bolna's provider system accepts on the wire**.

**Scope read end to end.** `bolna-findings/mirror/pages/providers.md`;
`providers/llm-model/{openai,gemini,azure-openai,anthropic,deepseek,openrouter}.md`;
`api-reference/providers/{overview,add,get,remove}.md`;
`api-reference/agent/create.md` and `api-reference/agent/v2/create.md`;
`agent-setup/llm-tab.md`; `concepts/{latency,choosing-providers}.md`;
`customizations/using-custom-llm.md`; `graph-agent/introduction.md`.

**Evidence rule.** Every claim below cites `bolna-findings/mirror/pages/<path>:<line>`.
Every one of those 17 pages was re-hashed against `bolna-findings/mirror/MANIFEST.json`
during this lane: **17/17 SHA-256 match, all status 200**. That is the
**VERIFIED-VENDOR-DOCS** class. Anything not on a vendor page is marked **REPORTED** and
carries the exact observation that would settle it. Nothing here is invented — a guessed
credential name 401s on the first turn of the first call, which is the defect class
D-31/D-32/D-350/D-417 exist for.

**Sibling report.** `docs/evidence/bolna-providers-llm.md` (D-417) is the Azure-focused
lane over the same pages. Nothing here contradicts it; this file is the non-Azure
provider surface it did not need to enumerate, plus two findings it did not carry
(§2.1 the `OPENAI` / `OPENAI_API_KEY` conflict, §6.2 the one-posture-at-a-time
constraint).

---

## 0. Headline, in the order that decides the work

1. **Bolna HAS a first-class Google provider, and the wire value is `google`, not
   `gemini`.** `providers/llm-model/gemini.md:20` (copy-pasteable `llm_config` body) and
   `:51` (Key settings table). So the Gemini in-call question is *not* closed by absence —
   it is open on residency, exactly as D-410 already recorded.
2. **OpenAI-direct is one credential entry; Google/Gemini is also one.** `OPENAI`
   (`providers.md:87`) and `GOOGLE` (`providers.md:108`), each a single
   `POST /providers`. Against Azure's four. Both sit under
   *"All these keys **must** be added for the respective provider."* (`providers.md:40`).
3. **⚠ NEW CONFLICT, NOT PREVIOUSLY RECORDED: the vendor spells the OpenAI credential
   entry two different ways.** `providers.md:87` says `OPENAI`; the published OpenAPI for
   the credential store uses `OPENAI_API_KEY` as its `example` in all three operations
   (`api-reference/providers/add.md:61`, `get.md:73`, `remove.md:39`). One of these is
   wrong and **this repository must not pick**. See §2.1 — it is a proposed OPERATIONS §2
   gate, modelled on 16f.
4. **Neither OpenAI nor Google carries Azure's deployment-resolution hazard.** The
   resolution paragraph exists on exactly one page — `azure-openai.md:69` — and it exists
   *because* Azure deployment names are freely chosen. On `openai` and `google` the model
   string is simply the model (`openai.md:60`, `gemini.md:52`).
5. **`SimpleLlmAgent.provider` has NO enum in the vendor's OpenAPI** — only
   `default: openai` / `example: openai` (`api-reference/agent/v2/create.md:795-798`;
   same at `api-reference/agent/create.md:457-460`). So the schema cannot enumerate the
   wire values for us, and a wrong string does **not** 400: it falls back to their default
   provider. That is what makes the per-provider quick-config blocks the only
   machine-readable source, and it is why a typo here is a silent misroute rather than an
   error.
6. **Reachable today: OpenAI-direct** — one key, one wire string, no unknowns except the
   §2.1 naming conflict, which one `GET /providers` settles.
   **Blocked: Google/Gemini** — not on a Bolna unknown (their side is fully documented and
   trivial) but on **residency**, which is ours: Bolna's Gemini leg is the AI Studio
   Developer API on a global host with no region field (recorded at
   `apps/api/engine/bolna.py::_llm_routing`, D-127/D-401), and their own page names no
   region anywhere.

---

## 1. Per-provider table — wire value, credentials, model spelling, resolution hazard

Every `provider` value below appears **twice per page** and in the same two places: once
inside a copy-pasteable `"llm_config"` JSON block ("Quick config"), and once in a "Key
settings" table row that quotes it in backticks with the type `string`. Both are
machine-readable forms. Where only a LABEL exists it is called out — that is the class of
evidence that produced the `azure` → `azure-openai` defect (D-417).

| Provider | Wire `provider` | Machine-readable evidence | Label-only evidence | Credential entries (`provider_name`) | `POST /providers` calls | Model spelling | Resolution hazard | Class |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| OpenAI | `openai` | `llm-model/openai.md:20` (JSON body), `:59` (Key settings) | "OpenAI" — `agent-setup/llm-tab.md:31`, `concepts/choosing-providers.md:63` | `OPENAI` (`providers.md:87`) — **but see §2.1**, the OAS example says `OPENAI_API_KEY` | **1** | the model itself, e.g. `gpt-5.4-mini` (`openai.md:60`) | **None documented.** No resolution paragraph on the page | VERIFIED-VENDOR-DOCS (credential NAME: **REPORTED**, conflicted) |
| Google Gemini | **`google`** (not `gemini`) | `llm-model/gemini.md:20` (JSON body), `:51` (Key settings) | "Google Gemini" — accordion title `providers.md:105`, card `choosing-providers.md:71` | `GOOGLE` (`providers.md:108`) | **1** | the model itself, e.g. `gemini-2.5-flash` (`gemini.md:52`) | **None documented.** No resolution paragraph on the page | VERIFIED-VENDOR-DOCS |
| Azure OpenAI | `azure-openai` | `llm-model/azure-openai.md:20`, `:59` | "Azure" dropdown/matrix — `llm-tab.md:31` (this is what D-410 wrongly read `azure` from) | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_MODEL`, `AZURE_OPENAI_API_BASE`, `AZURE_OPENAI_API_VERSION` (`providers.md:99-102`) | **4** | **the DEPLOYMENT id**, freely chosen (`azure-openai.md:60`, `:69`, `:97-98`) | **YES — the one hazard on the whole surface.** `azure-openai.md:69`: Bolna resolves the deployment name back to the model it serves, and *"A name it cannot resolve is treated as a non-GPT-5 model and gets the wrong defaults."* `:72`: with a custom deployment name an unsupported `reasoning_effort` *"is accepted when you create the agent and then fails on the call instead"* | VERIFIED-VENDOR-DOCS (`AZURE_OPENAI_API_VERSION` value: **open**, gate 16f) |
| Anthropic | `anthropic` | `llm-model/anthropic.md:20`, `:49` | "Anthropic" — `llm-tab.md:31`, `choosing-providers.md:67` | **NONE DOCUMENTED** — the LLMs tab of `providers.md` (`:83-137`) has no Anthropic accordion | **unknown** | the model itself, e.g. `claude-sonnet-5` (`anthropic.md:50`) | None documented | wire value VERIFIED-VENDOR-DOCS; credential **UNDOCUMENTED** (§6.1) |
| DeepSeek | `deepseek` | `llm-model/deepseek.md:24`, `:53` | card `choosing-providers.md:79` | **NONE DOCUMENTED** — no DeepSeek accordion in `providers.md` | **unknown** | the model itself, e.g. `deepseek-v4-flash` (`deepseek.md:54`) | None documented | wire value VERIFIED-VENDOR-DOCS; credential **UNDOCUMENTED** (§6.1) |
| OpenRouter | `openrouter` | `llm-model/openrouter.md:20`, `:56` | card `choosing-providers.md:83` | `OPENROUTER` (`providers.md:93`) | **1** | **`vendor/model` slug**, e.g. `openai/gpt-4o-mini` (`openrouter.md:21`, `:34`, `:57`) | None documented, but the slug namespace is OpenRouter's, not the model vendor's — a bare `gpt-4o-mini` is not a valid value here | VERIFIED-VENDOR-DOCS |
| Custom (OpenAI-compatible) | `custom` | `providers.md:129` (inside a full `llm_agent` example) | dashboard "Custom" — `customizations/using-custom-llm.md:43` | **NONE — and that is the finding.** The Custom LLM accordion (`providers.md:111-136`) is the only provider entry in the file with **no key table at all**; the documented flow takes exactly two values, `LLM URL` and `LLM Name` (`using-custom-llm.md:32-33`) | **0 (no documented credential path)** | free string alongside `base_url` (`providers.md:120`, `:132`) | n/a | VERIFIED-VENDOR-DOCS — this is why gate 16c retired the `custom` route |
| Groq | `groq` | `graph-agent/introduction.md:111` — *"Defaults to `groq` when a Groq key is configured"*. **This is the graph-agent ROUTING LLM, not `simple_llm_agent.llm_config.provider`** | "Groq" in the dashboard provider list — `llm-tab.md:31` | **NONE DOCUMENTED** | **unknown** | `llama-3.3-70b-versatile` is named as the Groq routing default (`graph-agent/introduction.md:112`) | n/a | **REPORTED** — no `providers/llm-model/groq.md` page exists (`llms.txt:45-50` lists six LLM pages and Groq is not among them) |

**Sarvam is not an LLM provider on this engine.** `providers/llm-model/` contains six
pages and none is Sarvam (`llms.txt:45-50`); `openrouter.md:89` points a reader at
"[Sarvam](/docs/providers/llm-model)" — the *directory*, which has no Sarvam page.
`providers.md:152-156` lists `SARVAM` under the **Synthesizer** tab only. This confirms
D-410's refusal of Sarvam-via-Custom-LLM from the vendor's side.

---

## 2. The credential store, exactly

The store is flat and untyped: `POST /providers` takes `{provider_name, provider_value}`,
both required strings (`api-reference/providers/add.md:55-68`). `GET /providers` returns
`{provider_id, provider_name, provider_value (MASKED), created_at}`
(`get.md:63-86`). `DELETE /providers/{provider_key_name}` removes one by NAME
(`remove.md:29-39`). There is **no per-provider object and no way to write several fields
in one call** — which is exactly why Azure is four installs and OpenAI/Google are one each.

Endpoints, verbatim (`api-reference/providers/overview.md:17-21`):

```
POST /providers
GET /providers
DELETE /providers/:provider_key_name
```

Nothing in the store is scoped to a provider "kind": a name is just a name. So a wrong
name does not error — it sits there, and the provider it was meant for authenticates with
nothing. **Count-before/count-after (`bolna.py::set_llm_credential`) is the only way to
learn what a second write under one name does**; the POST response `status` enum has
exactly one member, `added` (`add.md:73-79`), and documents no update semantics.

### 2.1 ⚠ OPEN — the OpenAI credential entry is spelled two ways by the same vendor

| Source | Value | Weight |
| --- | --- | --- |
| `providers.md:87` — LLMs tab, "OpenAI" accordion, *Property* column | `OPENAI` | The table is introduced by *"All these keys **must** be added for the respective provider."* (`providers.md:40`). This is the same table that produced the four **correct** Azure names (D-417), and it is consistent with every other single-key provider in the file: `OPENROUTER` `:93`, `GOOGLE` `:108`, `ELEVENLABS` `:143`, `CARTESIA` `:149`, `SARVAM` `:155`, `SMALLEST` `:161`, `DEEPGRAM` `:169`, `SONIOX` `:175`. |
| `api-reference/providers/add.md:61`, `get.md:73`, `remove.md:39` | `OPENAI_API_KEY` | An OpenAPI `example:`, not an `enum:` — an illustration, and the same spec omits `enum` on `provider`/`family` where it uses `enum` freely elsewhere (`agent_flow_type`, telephony). Weaker class. |

**On weight of evidence `OPENAI` is the better bet and `OPENAI_API_KEY` is probably an
OpenAPI author's placeholder.** That is a bet, not a fact, and this repository does not
ship bets in credential names — the Azure lesson (`AZURE` → `AZURE_OPENAI_API_KEY`) is
that a *plausible derivation* was wrong. **Proposed gate (OPERATIONS §2, modelled on
16f):** on a live Bolna account, `POST /providers` with `provider_name: "OPENAI"`, then
`GET /providers`, then create one agent with `provider: "openai"` and place one call. If
the call authenticates, `OPENAI` is right. If it 401s on the first turn, `DELETE
/providers/OPENAI` and repeat with `OPENAI_API_KEY`. **Blocked outside this repo on: a
Bolna account and an OpenAI API key.** Cost of guessing wrong: a 401 mid-sentence on a
live call — the exact failure `in_call_llm`'s second condition was written about.

### 2.2 Google/Gemini — one entry, no conflict

`providers.md:105-109`:

```
<Accordion title="Google Gemini">
  | Property | Description                |
  | -------- | -------------------------- |
  | `GOOGLE` | Your Google Gemini API key |
```

One entry, one `POST /providers`. The accordion *title* is the label "Google Gemini"; the
*Property* cell is the machine-readable name `GOOGLE`, and it matches the wire provider
value `google` (`gemini.md:20`, `:51`) in the same way `OPENROUTER`/`openrouter` and
`SARVAM`/`sarvam` do. **No open question on the Google credential name.**

Corroborated by the dashboard flow: `gemini.md:28` — *"connect it at
platform.bolna.ai/auth/google"* — `google`, not `gemini`, in the vendor's own URL.

---

## 3. Model strings and resolution

**Azure is the only provider where `model` is not the model.** The paragraph is worth
quoting because it is the whole hazard (`azure-openai.md:69`):

> Azure deployment names are chosen freely, so `model` here is often not the model name.
> Keep the underlying model name inside the deployment name — `prod-gpt-5.4-mini` rather
> than `prod-voice-01`. Bolna resolves the deployment to the model it serves, and that
> resolution is what selects GPT-5 handling and the right default `reasoning_effort`. A
> name it cannot resolve is treated as a non-GPT-5 model and gets the wrong defaults.

`openai.md` and `gemini.md` carry **no equivalent paragraph and no equivalent sentence
anywhere on the page**. Their model tables (`openai.md:38-49`, `gemini.md:34-41`) list
model names, and their Key settings rows describe `model` as *"Model to use"*
(`openai.md:60`, `gemini.md:52`) against Azure's *"Model/deployment name"*
(`azure-openai.md:60`). **On OpenAI and Google the model string is simply the model.**

Consequence for us, stated precisely: `ModelBinding`'s `addresses_a_deployment` is `True`
under `india-azure-openai` and would be `False` under any OpenAI-direct or Google posture —
which is already what `scripts/check_model_residency.py`'s `openai-direct` spec says
(`addresses_a_deployment=False`). The two-string (`addressed` vs `priced`) distinction
collapses to one string on those legs.

### 3.1 Models listed, current vs previous-gen

| Provider | Current | Marked "previous gen" / deprecated |
| --- | --- | --- |
| OpenAI (`openai.md:40-49`) | `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.5`, `gpt-5.5-pro`, `gpt-5.4`, **`gpt-5.4-mini` (their recommendation, `:46`, `:51`)** | `gpt-4.1`, `gpt-4.1-mini`, `gpt-4o` — *"Previous-gen; still available / Use if already deployed"* |
| Google (`gemini.md:36-41`) | `gemini-3.5-flash`, `gemini-3.1-pro`, `gemini-3.1-flash-lite`, `gemini-2.5-pro`, **`gemini-2.5-flash` (their recommendation, `:40`, `:43`)**, `gemini-2.5-flash-lite` | none marked |
| Azure (`azure-openai.md:40-47`) | `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.4-nano` | `gpt-4.1`, `gpt-4.1-mini`, `gpt-4o`, `gpt-4o-mini` — all four *"Previous gen; still available"* (this is what answered LEAD-A in the sibling report) |

### 3.2 Latency / TTFT guidance — this is a phone call

`concepts/latency.md:9` targets **sub-600ms end-to-end**, of which
`:24` budgets **LLM first token 100–400ms**, described at `:62` as *"the largest share of
latency"*. Their published TTFT table (`latency.md:64-69`):

| Provider | Typical TTFT |
| --- | --- |
| OpenAI `gpt-4.1-mini` | ~150ms |
| OpenAI `gpt-4.1` | ~200ms |
| Anthropic `claude-sonnet-4-20250514` | ~250ms |
| Google `gemini-2.5-flash` | ~150ms |

**`gemini-2.5-flash` and `gpt-4.1-mini` are quoted identically at ~150ms** — so on the
vendor's own numbers there is no latency argument between an OpenAI-direct leg and a
Google leg. `latency.md:127` adds *"Smaller models (gpt-4.1-mini, gemini-2.5-flash-lite)
have lower TTFT"*. `gemini.md:75` claims *"Comparable latency"* between the two families,
with Gemini ahead on multilingual and GPT ahead on English instruction-following
consistency — relevant to a Telugu-first product, and **REPORTED, not measured**.

**A GPT-5 trap that would bite a build lane immediately.** `openai.md:29` and
`azure-openai.md:29`: *"GPT-5-series models require `"temperature": 1`. Any other value is
rejected with `400 For GPT-5 models, temperature must be 1`"*, and the field defaults to
`0.1` when omitted. `apps/api/engine/bolna.py::_agent_body` sends `0.1` explicitly and
deliberately (compliance-prompt fidelity). **So any GPT-5.x model — including their
recommended `gpt-5.4-mini` — 400s at agent creation against our current body.** Choosing a
GPT-5 model is therefore a `temperature` change plus a comment rewrite, not a settings
edit. `reasoning_effort` compounds it: `openai.md:96` — *"For live calls, stay at `none` or
`low`. Each step up adds reasoning tokens before the first spoken word, which lands
directly in time-to-first-token"* — and `openai.md:71`, reasoning tokens come out of the
same `max_tokens` budget. Gemini has **no** `reasoning_effort` row (`gemini.md:49-55`).

---

## 4. The agent payload for a non-Azure provider

`SimpleLlmAgent` (`api-reference/agent/v2/create.md:787-929`), the fields that move:

| Field | Schema | Note |
| --- | --- | --- |
| `provider` | `type: string`, `default: openai`, `example: openai` — **no `enum`** (`:795-798`) | An unknown value does not 400; it routes to their default. Silent misroute, not an error. |
| `family` | `type: string`, `default: openai`, `example: openai` — **no `enum`** (`:799-802`) | Cosmetic. `providers.md:133` shows `"family": "llama"` on a custom leg — the only non-`openai` value the docs ever print. |
| `model` | `type: string`, `default: gpt-5.4-mini` (`:803-806`) | One slot. See §3. |
| `base_url` | `type: string`, `default: https://api.openai.com/v1` (`:898-901`) | **Present in the schema, and absent from every provider page's Key settings table** — including OpenAI's and Google's. Its only documented *use* is the custom route (`providers.md:120`). |
| `temperature` | `default: 0.1`, `example: 1` (`:826-835`) | GPT-5 → must be `1`. |
| `max_tokens` | `default: 100`, `example: 150` (`:817-825`) | On GPT-5 sent as `max_completion_tokens`, shared with reasoning tokens. |
| `reasoning_effort` | `enum: [none, minimal, low, medium, high, xhigh]`, nullable (`:836-847`) | GPT-5 only; per-model subsets at `openai.md:81-90`. |
| `verbosity` | `enum: [low, medium, high]` (`:855-866`) | GPT-5 only. |
| `use_responses_api` | `bool`, default false (`:867-874`) | Forced on for `gpt-5.4`/`5.5`/`5.6` regardless. |
| `presence_penalty`, `frequency_penalty`, `top_p`, `min_p`, `top_k` | present | *"Accepted for backwards compatibility. Not sent to OpenAI or Azure models."* (`:887-889` and passim) — dead weight on these legs. |

The provider quick-config blocks (`openai.md:16-25`, `gemini.md:16-25`) all carry the same
outer shape and **no `base_url`**:

```json
"llm_agent": {
  "agent_type": "simple_llm_agent",
  "agent_flow_type": "streaming",
  "llm_config": { "provider": "google", "model": "gemini-2.5-flash",
                  "max_tokens": 150, "temperature": 0.2 }
}
```

That is byte-for-byte the shape `apps/api/engine/bolna.py::_agent_body` already builds
(`bolna.py:2214-2237`), with `_llm_routing`'s keys spread inside `llm_config`.

### 4.1 What `_llm_routing` would need — read, not changed

`apps/api/engine/bolna.py:392-517` today:

- `models.llm_provider is None` → `{"provider": "openai", "family": "openai"}` (`:501-502`).
- otherwise → `{"provider": _AZURE_LLM_PROVIDER, "family": "openai"}` plus `base_url` when
  `models.llm_base_url` is set (`:503-516`).

Its second branch is written as `if provider is not None → Azure`, because
`LlmProvider = Literal["azure_openai"]` has exactly one member
(`packages/shared/src/calevate_shared/engine.py:737`). **Adding a provider turns that
`if` into a mapping** — one `dict[LlmProvider, str]` beside `_AZURE_LLM_PROVIDER`, keeping
"THE ONLY PLACE a Calevate LLM leg becomes a Bolna provider name" true (its own docstring,
`:395`).

Note the accidental correctness of the `None` arm: it already sends `provider: "openai"`,
which is the *correct wire value* for an OpenAI-direct leg. What it does **not** do is
install a credential, pin a model, or make any residency statement — so it is not an
OpenAI-direct posture, it is the vendor default written down (D-355).

---

## 5. What each provider costs us, as a change list (evidence only — no code was changed)

### 5.1 OpenAI-direct

| Site | Change |
| --- | --- |
| `calevate_shared.engine.LlmProvider` (`engine.py:737`) | `Literal["azure_openai"]` → add `"openai"`. Its comment says *"A second member arrives with a decision-log entry."* |
| `ModelConfig._llm_endpoint_is_coherent` (`engine.py:994-1034`) | The `elif self.llm_base_url:` arm currently refuses a base URL on any non-Azure leg. An OpenAI-direct leg has a **fixed** endpoint with no caller input, so the coherent rule is: `openai` requires `llm_base_url` to be exactly `openai_base_url()`, or to be absent. |
| `openai_base_url()` | **Does not exist.** `check_model_residency.POSTURES["openai-direct"]` already names it: `builder="openai_base_url"`, `builder_arity=0`, `builder_suffix=f"https://{OPENAI_DIRECT_HOST}/v1"` (`scripts/check_model_residency.py:340-361`). Arity 0 = a fixed vendor endpoint with no caller input. |
| `bolna._llm_routing` | `"openai"` → `{"provider": "openai", "family": "openai"}`. **No `base_url`** — it is the schema default (`v2/create.md:900`) and the page has no `base_url` row. |
| `bolna._AZURE_PROVIDER_KEYS` | Needs a sibling one-entry map. **Name unresolved — §2.1.** |
| `Settings.bolna_llm_credential_name` | `applies: live`; would move to `OPENAI` (or `OPENAI_API_KEY`). Already exists as the correction seam. |
| `agents/service.py::in_call_llm` | Reads `DECLARED_POSTURE.llm_provider` and `bind_model` (`service.py:574-579`) — under `openai-direct`, `bind_model` binds one string to both `addressed` and `priced`. |
| `_agent_body` temperature | `0.1` is fine on `gpt-4.1`/`gpt-4o` class; **400s on any GPT-5.x**. |
| Price table | `AZURE_LIST_PRICE_USD_PER_MTOK` has no OpenAI-direct sibling. |

**Unknowns: one, and it is small** (§2.1, the credential name). One `GET /providers`
settles it.

### 5.2 Google / Gemini

Bolna's side is *easier* than OpenAI's: `provider: "google"`, one credential `GOOGLE`, the
model string is the model, no resolution hazard, no `reasoning_effort`, no
temperature-must-be-1 trap, and TTFT quoted equal to `gpt-4.1-mini`. **Their side has no
open question at all.**

**Ours has the one that matters.** `check_model_residency.POSTURES` has **no Gemini
posture**, and one could not be written truthfully: Bolna's Gemini leg is
`genai.Client(api_key=…)` against `generativelanguage.googleapis.com` — a global host with
no region in it and no field to ask for one (recorded at `bolna.py:493-499`, D-127/D-401).
Nothing on `gemini.md` names a region, a residency control or a data-handling location;
compare `azure-openai.md:9`, `:81` which name residency explicitly, and
`choosing-providers.md:24`, `:57` which route "Enterprise / data residency" to Azure
OpenAI. **So a Gemini in-call leg is a `region=None` posture — the same "NO REGIONAL CLAIM
IS MADE OR CHECKABLE" warrant as `openai-direct`, with none of that posture's residency
argument having been made.** That is a founder/DPA decision, not an engineering one.

---

## 6. Open questions — nothing here is guessed

### 6.1 ⚠ Anthropic and DeepSeek have a documented wire value and NO documented credential entry

`anthropic.md:20`/`:49` and `deepseek.md:24`/`:53` give machine-readable `provider`
values, and both pages say *"To use your own … API key, connect it at
platform.bolna.ai/auth/{anthropic,deepseek}"* (`anthropic.md:28`, `deepseek.md:32`). But
the LLMs tab of `providers.md` (`:83-137`) has **five** accordions — OpenAI, OpenRouter,
Azure OpenAI, Google Gemini, Custom LLM — and neither Anthropic nor DeepSeek is one of
them, under a sentence that claims to enumerate what *"we currently have"* (`:39`).
Either the table is incomplete or those two are dashboard-OAuth-only with no API-installable
key. **Do not derive `ANTHROPIC`/`DEEPSEEK`** — that is exactly the derivation
(`AZURE`) that D-417 caught. **Settles it:** `GET /providers` on an account where the key
was connected through the console, and read the `provider_name` back. Out of scope for
this product regardless: neither is a candidate leg.

### 6.2 ⚠ Our posture mechanism is one-at-a-time — "optionality alongside Azure" does not typecheck

Not a vendor question, but it governs the whole task and is recorded here so a build lane
does not discover it late. `DECLARED_POSTURE_NAME` is **one** `Final` string literal
(`engine.py:794-800`), `POSTURES` is keyed on it, and
`scripts/check_model_residency.py` fails **both ways** — code that drifts from the
declaration, and a declaration edited to describe a tree that has not moved
(`check_model_residency.py:16-23`). Under a pinning posture it requires exactly one frozen
region constant; under a non-pinning one it requires **zero**, so `AZURE_LOCATION` cannot
sit in a tree whose declaration has moved to `openai-direct`. `ResidencyPosture`'s own
docstring: *"keeping both would have made the residency posture a CHOICE, and a posture
with two answers is two postures"* (`engine.py:714-717`).

So **adding `"openai"` to `LlmProvider` is legal and cheap; running two postures at once is
not a thing this tree can express.** Optionality here means *a switch that is one reviewed
commit* — which is precisely what D-432 bought — not two live legs. If two live legs are
genuinely wanted, that is a decision-log entry that changes what a posture *is*, and it
should be taken deliberately rather than discovered in a diff.

### 6.3 ⚠ `AZURE_OPENAI_API_VERSION` — unchanged, still open (gate 16f)

Carried forward from D-417, restated because §2.1 is modelled on it and because it is the
only Azure item still open: `providers.md:40` calls all four Azure entries mandatory;
`azure-openai.md:32` describes the same connection as needing *"your Azure endpoint URL,
API key, and deployment name"* — three things, no api-version. D-410 chose the v1 surface
precisely because it has no `api-version`. **No value is invented here.**

### 6.4 `base_url` on a non-Azure leg — is it read?

The schema has the field with an OpenAI default (`v2/create.md:898-901`); **no provider
page's Key settings table lists it**, and its only documented use is the custom route.
Harmless on OpenAI-direct (the default *is* the value we would send) and on Google (we
would send none). Recorded so nobody adds one hoping it routes. **Settles it:** publish one
agent with a deliberately wrong `base_url` and a valid provider, place one call, see
whether it reaches the endpoint or the vendor default.

### 6.5 Groq

`groq` appears as a machine-readable value only for the **graph-agent routing LLM**
(`graph-agent/introduction.md:111`), and as a dashboard label in the provider list
(`llm-tab.md:31`). There is no `providers/llm-model/groq.md` (`llms.txt:45-50`) and no
credential entry. **Whether `provider: "groq"` is valid on `simple_llm_agent` is
undocumented.** Not a candidate leg; recorded for completeness.

---

## 7. Manifest verification

All 17 pages cited above were re-hashed against `bolna-findings/mirror/MANIFEST.json`
during this lane: **17/17 SHA-256 match, HTTP status 200**. Spot values:

| Page | SHA-256 (first 16) |
| --- | --- |
| `providers.md` | `63231b2b7a0c5a33` |
| `providers/llm-model/openai.md` | `37564414f4b1decc` |
| `providers/llm-model/gemini.md` | `780698114af9607e` |
| `providers/llm-model/azure-openai.md` | `faeda3c225e378c7` |
| `api-reference/providers/add.md` | `58ae4bf242d30e5f` |
| `api-reference/agent/v2/create.md` | `69e3dd768f1c2996` |
| `concepts/latency.md` | `72bfee9ca4382cce` |

The mirror is read-only and was not edited, reformatted or moved by this lane.
