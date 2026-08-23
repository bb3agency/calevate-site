# Making OpenAI-direct and Gemini selectable — the vendor facts, per-claim evidence class

**Lane P-2. Read 23 August 2026 (UTC).** Commission, in the founder's framing: *we are
making OpenAI-direct and Google-Gemini models selectable for clients; nail down the vendor
facts with the evidence class labelled on every single claim.*

**Scope.** Vendor facts only — the engine's supported model lists at wire level, the
credential contract, the per-family request traps, price, and retirement. Not a design and
not a decision. This lane wrote **one file, this one**, and touched nothing else.

**The short answer, so the reader knows what the evidence is for.**

1. **No OpenAI price can be verified from this container, and that is now measured on two
   egress paths against five OpenAI-owned hosts including one nobody here had tried
   (`developers.openai.com`, which is where OpenAI's pricing page has MOVED).** Every
   OpenAI figure below is **REPORTED**. `LlmModelSpec.__post_init__` therefore keeps every
   OpenAI model unselectable by construction, and it is right to.
2. **One Google-owned pricing page IS reachable and was fetched in full** —
   `cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing`, HTTP 200,
   2,862,008 bytes. This is new; the prior lane recorded every Google host as blocked.
   **But it prices the VERTEX / Agent Platform surface, and the engine's `google` leg is
   the Gemini DEVELOPER API** (`genai.Client(api_key=...)`, one key named `GOOGLE`). So it
   is VERIFIED-VENDOR-DOCS for a surface **we would not be billed on**. It corroborates
   the REPORTED Developer-API figures to the cent on four models — which raises confidence
   and **does not change the evidence class**. Hard rule 7 is still unsatisfied for the
   Gemini Developer API.
3. **The D-456 Gemini silence claim RE-VERIFIES, holds, and is now stronger than when it
   was written** — it gains a fourth independent piece of evidence: the engine's own source
   names the outcome, in an error log, as a *"Dead turn"* (§C.2.6). It also gains three
   refinements that make it more precise, one of which slightly widens it. **It is not
   mitigable from our side on any `gemini-3.*` model today.**
4. **Azure retirement dates are the only dated vendor facts in this file** and they are
   Microsoft's, read at the same pinned commit `model_lifecycle.py` already carries. They
   do **not** govern the OpenAI-direct leg. Gemini retirement is REPORTED throughout.

---

## 0. Evidence classes, egress measured today, integrity checked

### 0.1 Classes used below (unchanged from `llm-provider-postures.md` §0.1)

| Class | Means here |
| --- | --- |
| **VERIFIED-VENDOR-DOCS** | Read in the vendor's own publication. For Bolna: the hash-pinned in-tree mirror, cited `page:line`, SHA-256 re-checked. For Microsoft: `MicrosoftDocs/azure-ai-docs`, the repository `learn.microsoft.com` is published FROM, at a named commit. For Google: a page fetched from a `google.com`-owned host at a named URL, or a generated type stub in Google's own SDK repository at a named commit. |
| **VERIFIED-OSS** | Read in `bolna-ai/bolna`, the engine's own open source, at a pinned commit. **This is the engine we rent; it is NOT proof of what the hosted platform runs.** The repo has kept these apart since D-31 and this lane does not merge them. |
| **VERIFIED-IN-REPO** | Read in this tree, cited `file:line`. |
| **REPORTED** | A search-engine summary or a third-party tracker. **Never sufficient for `unit_cost_paid` (hard rule 7) or for a `check_model_lifecycle` entry claimed as verified.** |
| **UNKNOWN** | Nobody here has established it. Recorded as a hole in §F.2, never filled with a guess. |

### 0.2 Egress, measured 23 Aug 2026 — not assumed, and one row is new

`curl` through the agent proxy and the fetch tool use different egress paths. Where both
were tried they agreed.

| Host | Result | Note |
| --- | --- | --- |
| `openai.com`, `platform.openai.com` | **BLOCKED** | carried forward from 22 Aug, not re-probed |
| **`developers.openai.com`** | **BLOCKED** | **NEW ROW.** Confirmed on BOTH paths (curl `000`; fetch tool `EGRESS_BLOCKED`). This is where OpenAI's pricing page now lives — the URL `engine.py::_OPENAI_PRICE_EVIDENCE` tells a human to open (`openai.com/api/pricing/`) is stale. |
| `cdn.openai.com`, `status.openai.com` | **BLOCKED** | new probes, both refused |
| `learn.microsoft.com`, `azure.microsoft.com` | **BLOCKED** | re-measured, unchanged |
| **`prices.azure.com`** (Azure Retail Prices API) | **BLOCKED** | new probe. A machine-readable Microsoft price feed would have settled the Azure leg; it does not answer. |
| `ai.google.dev` (incl. the `.md.txt` plaintext form), `discuss.google.dev` | **BLOCKED** | `deprecations.md.txt` probed specifically and refused |
| `docs.cloud.google.com` | **BLOCKED** | every `cloud.google.com/**/docs/**` path 301s here and dies |
| **`cloud.google.com`** — the **pricing** path | **200** | **THE ONE VENDOR PRICE PAGE THIS LANE REACHED.** See §0.3. |
| `cloud.google.com/products/agent-platform`, `/terms/service-terms` | 200 | reachable; neither carries token prices or retirement dates |
| `github.com` (git proxy), `pypi.org` | **200** | `raw.githubusercontent.com` and `api.github.com` are refused for repositories not attached to this session; `git clone` through the proxy works |

**Consequence, stated plainly: no word of OpenAI's pricing or deprecation policy was read
at an OpenAI URL by this lane. §D.2 and §E.2 are REPORTED in full and must be read as
such.**

### 0.3 The one Google page, pinned

```
URL      https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing
HTTP     200 (no redirect; final URL == requested URL)
Fetched  2026-08-23T04:45Z
Bytes    2862008
SHA-256  85ec2197c1b89a377db840f4d3d39a61326e9f476312ab928ae788304cbe01ca
```

The hash pins **what this lane read**, not a stable vendor artefact — a pricing page is
edited without notice, so a future re-fetch that hashes differently is expected and is not
evidence of tampering. The bytes were not written into this repository.

**⚠ WHAT SURFACE THIS PAGE PRICES, because getting this wrong would be the whole error.**
Its own title is *"Agent Platform Pricing"* and its rows carry a `Region` column with
`Global` / `Non-global` values and a `Priority` and `Flex/Batch` tier — that is **Vertex AI
/ Agent Platform**. The engine's `google` leg is the **Gemini Developer API**:
`gemini_llm.py:48-49` (VERIFIED-OSS) constructs `genai.Client(api_key=api_key)` with an API
key and **no** `vertexai=True`, **no** project, **no** location and **no** `http_options`.
Google prices these two surfaces on separate pages. **So this page is VERIFIED-VENDOR-DOCS
for a surface we would not be billed on.** It is quoted below because it is the vendor's
own arithmetic and it corroborates the Developer-API trackers exactly — but a figure copied
from it into `unit_cost_paid` for a Developer-API call would be hard rule 7 broken by a
surface mismatch instead of by a search summary.

### 0.4 Integrity, checked rather than trusted

Every Bolna mirror page cited was re-hashed against `bolna-findings/mirror/MANIFEST.json`
on 23 Aug 2026. All four verify:

```
OK  providers.md                        63231b2b7a0c5a338dd1d6342dc65ea4ac05546f7ddb6a28bc3c9a4ec24791b9
OK  providers/llm-model/openai.md       37564414f4b1decc6eab595dee5f280e0e51a42140003534f0105f221d74cd50
OK  providers/llm-model/gemini.md       780698114af9607e3d17f72aba0f6d2eefeb27eee51208ded348d970a6a08b09
OK  providers/llm-model/azure-openai.md faeda3c225e378c77f4f8db558f5f8329eb691968610af0b2105ff9e96c63f30
```

`api-reference/providers/add.md` and `api-reference/agent/v2/create.md` are also cited;
both were verified by the prior lane on 22 Aug and neither is in the 7-page drift cluster
that lane flagged. **Nothing under `bolna-findings/` was read-modify-written by this lane;
`git status --porcelain bolna-findings/` is empty.**

Source repositories, cloned shallow through the session git proxy and read at HEAD:

```
bolna-ai/bolna              0172347b601ea66dac0414cc1c6b14dc0d85422a  2026-08-22T00:28:03+05:30
googleapis/python-genai     66807187f2123c6676175ac991f4e34eb09200d1  2026-08-21T12:13:31-07:00
MicrosoftDocs/azure-ai-docs 19bbfea4b8cdc87e92f542b9d7c47f3a4c7f6b10  2026-08-21T22:08:40+00:00
```

**The first two are the SAME commits `llm-provider-postures.md` §0.4 pinned on 22 Aug** —
nothing moved upstream in a day, so this lane's re-verification of §3.4 is a genuine
second reading of identical bytes rather than a reading of a changed file. The third is
the same commit `packages/shared/src/calevate_shared/model_lifecycle.py:230`
(`_MS_DOCS_COMMIT`) already carries, so §E.1 reproduces that entry's source exactly.

---

## A. The engine's supported model lists, at wire level

### A.1 The `provider` strings — three, all confirmed twice

| Leg | Exact `llm_config.provider` value | Docs (VERIFIED-VENDOR-DOCS) | Engine source (VERIFIED-OSS) |
| --- | --- | --- | --- |
| OpenAI direct | **`openai`** | `llm-model/openai.md:20` (JSON body), `:59` (Key settings row) | `bolna/enums.py:96` `LLMProvider.OPENAI = "openai"`; `bolna/providers.py:91` maps it to `OpenAiLLM` |
| Google Gemini | **`google`** — *not* `gemini` | `llm-model/gemini.md:20`, `:51` | `bolna/enums.py:113` `GOOGLE = "google"`; `bolna/providers.py:108` → `GeminiLLM` |
| Azure OpenAI | **`azure-openai`** | `llm-model/azure-openai.md:20`, `:59` | `bolna/enums.py:102` `AZURE_OPENAI = "azure-openai"`; `bolna/providers.py:97` → `AzureLLM` |

**D-417's correction is re-confirmed from a second class of evidence.** The value is
`azure-openai`, not `azure`. ⚠ Note the trap that made D-417 necessary is still present in
the OSS: `bolna/enums.py:112` also defines `AZURE = "azure"` and `providers.py:107` maps
*that* to `AzureLLM` too — so **both** strings instantiate an Azure client in the OSS. The
docs publish only `azure-openai`, and that is the one to send; `azure` working in the OSS is
not evidence that the hosted platform accepts it.

**Model strings are NOT validated by the OSS.** `task_manager.py:1813-1818` (VERIFIED-OSS)
checks the **provider** against `SUPPORTED_LLM_PROVIDERS` and raises if absent; the model
string is passed through untouched into `GeminiLLM.__init__` / `OpenAiLLM.__init__`, both of
which accept any string. **Whether the hosted platform validates model names at agent
creation is UNKNOWN** (hole H-3, §F.2) — the docs assert a 400 for a bad `reasoning_effort`
(`create.md:93`) but assert nothing about a bad `model`.

### A.2 `provider: "openai"` — supported models

VERIFIED-VENDOR-DOCS, `bolna-findings/mirror/pages/providers/llm-model/openai.md:38-49`,
exactly as the vendor's table states them:

| `model` | Context (vendor's column) | Vendor's note |
| --- | --- | --- |
| `gpt-5.6-sol` | 1M | Newest flagship; highest cost |
| `gpt-5.6-terra` | 1M | Newest; about 2x cheaper than Sol |
| `gpt-5.6-luna` | 1M | Newest low-cost tier |
| `gpt-5.5` | 1M | Flagship 5.5 line; high cost |
| `gpt-5.5-pro` | 1M | Highest cost and latency; *"not ideal for latency-sensitive voice"* |
| `gpt-5.4` | 1M | Strong reasoning, lower cost than 5.5 |
| `gpt-5.4-mini` | **400K** | **Recommended** — vendor's default for voice (`:9`, `:46`, `:51`) |
| `gpt-4.1` | 1M | Previous-gen |
| `gpt-4.1-mini` | 1M | Previous-gen |
| `gpt-4o` | 128K | Previous-gen |

**⚠ Two identifiers appear on this page OUTSIDE that table and must not be read as
supported by it.** `gpt-5.4-nano` appears only in the reasoning-effort table (`openai.md:87`),
and `gpt-5.2`, `gpt-5.1`, `gpt-5`, `gpt-5-mini`, `gpt-5-nano` likewise (`:88-90`). The
engine's own `MODEL_REASONING_EFFORT_MAP` (`bolna/constants.py:311-334`, VERIFIED-OSS)
carries all of those **plus** `gpt-5-codex`, `gpt-5-pro`, three `gpt-5.1-codex*` variants,
`gpt-5.2-codex`-adjacent names and three `gpt-realtime-2*` speech-to-speech models. **The
OSS knows more models than the docs page lists; the docs table is the narrower and safer
list, and it is the one to ship against.**

### A.3 `provider: "google"` — supported models

VERIFIED-VENDOR-DOCS, `llm-model/gemini.md:34-41`:

| `model` | Context | Vendor's note |
| --- | --- | --- |
| `gemini-3.5-flash` | 1M | *"Latest generation; stable"* |
| `gemini-3.1-pro` | 1M | *"Gemini 3 premium model"* |
| `gemini-3.1-flash-lite` | 1M | *"Fastest in Gemini 3 family"* |
| `gemini-2.5-pro` | 1M | *"Gemini 2.5 premium; stable"* |
| `gemini-2.5-flash` | 1M | **Recommended** — *"proven, stable, fast"* |
| `gemini-2.5-flash-lite` | 1M | *"Cheapest in 2.5 family"* |

**⚠ FINDING — `gemini-3.1-pro` is unverified as a wire value and two other vendor sources
spell it differently.** The engine's own `GEMINI_THINKING_LEVEL_MAP`
(`bolna/constants.py:349`, VERIFIED-OSS) keys **`gemini-3.1-pro-preview`**, and Google's own
pricing page (§0.3) labels the row **"Gemini 3.1 Pro Preview"**. The bare `gemini-3.1-pro`
appears in the engine's docs table and nowhere else this lane could reach. This has the exact
shape of the D-417 defect — a human-readable table carrying what a machine-readable source
spells differently. Consequence if the docs spelling is wrong: `default_thinking_level`
(`constants.py:357-365`) misses the map and falls through to its `"low"` default — which
happens to equal the map's own first entry for that model, so the failure would be **silent
and currently harmless**, and would stop being harmless the day Google adds a lower level.

**⚠ FINDING — three models the engine's OSS supports are absent from its docs page:**
`gemini-3.5-flash-lite`, `gemini-3.6-flash`, `gemini-3.7-flash` (`constants.py:351-353`,
VERIFIED-OSS). All three are also priced on Google's own page (§D.1). `gemini-3.6-flash` is
the model `model_lifecycle.py` currently names as `gemini-2.5-flash`'s replacement — so the
replacement this repo has written down is **not on the vendor's published model list**.

### A.4 `provider: "azure-openai"` — confirmed, unchanged

VERIFIED-VENDOR-DOCS, `llm-model/azure-openai.md:38-47`: `gpt-5.5`, `gpt-5.4`,
`gpt-5.4-mini`, `gpt-5.4-nano`, `gpt-4.1`, `gpt-4.1-mini`, `gpt-4o`, `gpt-4o-mini`.

Both models this repo ships (`gpt-4o-mini`, `gpt-4.1-mini`) are on it. **The list is
NARROWER than the direct-OpenAI list in one direction and WIDER in another** — no
`gpt-5.6-*` and no `gpt-5.5-pro` (the vendor's own *"Azure has a short lag"*, `:90`), but it
adds `gpt-5.4-nano` and `gpt-4o-mini` which the direct page omits. Microsoft's retirement
schedule independently corroborates both halves (§E.1): `gpt-5.6-sol/terra/luna` **are**
scheduled on Azure, so the lag is a Bolna-side gap rather than an Azure-side absence; and
`gpt-5.5-pro` is **absent from Microsoft's schedule entirely**, so Azure does not serve it at
all and the engine's page is right to omit it.

**`model` on this leg is the Azure DEPLOYMENT id, not a model name** — `azure-openai.md:60`,
`:69`, `:97-98`. Unchanged from D-417; see §C.1.4 for what that costs.

---

## B. The credential contract

### B.1 The store's shape

VERIFIED-VENDOR-DOCS, `api-reference/providers/add.md:55-68`: `POST /providers` takes a flat
object `{provider_name: string, provider_value: string}`, both required. **One call per
entry.** `providers.md:40` states the rule that makes the count matter: *"All these keys
**must** be added for the respective provider."*

### B.2 Per-provider entries

| Leg | Entries | Exact `provider_name` values | Citation |
| --- | --- | --- | --- |
| `openai` | **1** | **`OPENAI`** | `providers.md:84-88`, value at `:87` |
| `google` | **1** | **`GOOGLE`** | `providers.md:105-109`, value at `:108` |
| `azure-openai` | **4** | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_MODEL`, `AZURE_OPENAI_API_BASE`, `AZURE_OPENAI_API_VERSION` | `providers.md:96-103`, values at `:99-102` |

All three rows: **VERIFIED-VENDOR-DOCS**, with the one exception in §B.3.

**Case is not derivable in either direction.** The credential name is `OPENAI` (upper), the
wire provider is `openai` (lower); `GOOGLE` / `google` likewise. Deriving one from the other
is the D-417 error class.

### B.3 ⚠ The `OPENAI` / `OPENAI_API_KEY` conflict — re-confirmed, still open

`providers.md:87` says the property is `OPENAI`. `api-reference/providers/add.md:61` gives
`example: OPENAI_API_KEY` on the same field. **Both are the vendor's own publication and
they do not agree.** `bolna-llm-providers.md` §2.1 reasoned this out at length and landed on
`OPENAI` (the per-provider table is consistent with every other single-key provider in the
file — `OPENAROUTER` `:93`, `GOOGLE` `:108`, `ELEVENLABS` `:143`, `CARTESIA` `:149`,
`SARVAM` `:155`, `SMALLEST` `:161`, `DEEPGRAM` `:169`, `SONIOX` `:175` — while the OpenAPI
value is an `example:`, not an `enum:`). **This lane re-read both lines and confirms the
conflict is real and unresolved.** Classification of the OpenAI credential name is
therefore **REPORTED**, not VERIFIED — it is a reasoned bet, and `AZURE_OPENAI_API_KEY`
proves the vendor does use `_API_KEY` suffixes in this namespace, so the bet is not free.
Settled by one `POST /providers` + `GET /providers` round trip against a real account.
**Google's `GOOGLE` has no such conflict and is VERIFIED-VENDOR-DOCS outright.**

### B.4 Can a base_url / endpoint be supplied? — three different answers

| Leg | Endpoint supplied how | Class |
| --- | --- | --- |
| `azure-openai` | **YES, and it is mandatory.** `AZURE_OPENAI_API_BASE` in the credential store (`providers.md:101`); `azure-openai.md:32` restates it (*"your Azure endpoint URL, API key, and deployment name"*). In the OSS it arrives as the `base_url` kwarg or `AZURE_OPENAI_ENDPOINT` (`azure_llm.py:88`). | VERIFIED-VENDOR-DOCS + VERIFIED-OSS |
| `openai` | **YES, optionally, but through `llm_config` rather than the credential store.** `base_url` is a documented `SimpleLlmAgent` property with default `https://api.openai.com/v1` (`create.md:898-901`). The OSS honours it: `openai_llm.py:184-188` builds `AsyncOpenAI(base_url=..., api_key=...)` when it is set and `AsyncOpenAI(api_key=...)` when it is not. **This is the seam a regional OpenAI endpoint would use.** | VERIFIED-VENDOR-DOCS + VERIFIED-OSS |
| `google` | **NO. There is no endpoint knob at all.** `gemini_llm.py:48-49` is `genai.Client(api_key=api_key)` — no `http_options`, no `base_url`, no `vertexai`, no `location`. `grep` over the whole engine finds no other Gemini client construction. A `base_url` set in `llm_config` is silently ignored on this leg. | VERIFIED-OSS |

The `custom` provider is the documented escape hatch for an arbitrary OpenAI-compatible
endpoint (`providers.md:111-136`, `base_url` at `:120`, `provider: "custom"` at `:129`) —
**its credential path was never verified and remains retired gate 16c.** Not used here.

**Reading for the Gemini leg specifically:** one key, no project, no billing account, no
tier field, and no endpoint. Everything about *which* Google account and *which* terms
govern a live call is invisible on the wire and unreadable back from any API. That is the
same finding `llm-provider-postures.md` §5.2 records, arrived at here from the client
constructor rather than from the credential table.

---

## C. The traps, per family, and whether we can mitigate them

### C.1 GPT-5 family (both the `openai` and `azure-openai` legs)

#### C.1.1 `temperature` must be exactly 1 — **MITIGATED, by the engine, automatically**

VERIFIED-VENDOR-DOCS, three places saying the same thing: `openai.md:28-30` and
`azure-openai.md:28-30` (*"Any other value is rejected with `400 For GPT-5 models,
temperature must be 1`, and the field defaults to `0.1` when omitted, so send it
explicitly"*), and `create.md:826-835` in the schema itself.

VERIFIED-OSS: the engine does **not** rely on the caller. `openai_base.py:467-468` and
again at `:727-738`:

```python
if self.model_family.startswith(GPT5_MODEL_PREFIX):
    create_kwargs["temperature"] = 1
```

It **overwrites** whatever `temperature` reached it. So the runtime trap is closed by the
engine. **What is NOT closed is agent CREATION**: the 400 the docs describe is a
validation-time rejection on the hosted platform, which the OSS does not contain. **Our
mitigation is to send `temperature: 1` explicitly on every GPT-5 agent** — cheap, and the
docs tell us to.

#### C.1.2 `max_tokens` becomes `max_completion_tokens` — **automatic, but the consequence is ours**

VERIFIED-OSS: `openai_llm.py:163-171` and `azure_llm.py:75-85` switch the key when the model
family is GPT-5. VERIFIED-VENDOR-DOCS: `create.md:817-825` and `openai.md:71` state it and
state the consequence — *"reasoning tokens come out of the same budget. At
`reasoning_effort` above `none`/`minimal`, reasoning can consume most of a 150-token cap and
truncate the spoken reply, so raise the cap whenever you raise the effort."*

**The rename is nothing to do. The shared budget is the real trap, and on this leg it
TRUNCATES — it does not silence** (contrast §C.2). Mitigation: keep `reasoning_effort` at
`none`/`minimal` and keep `max_tokens` at 150, or raise both together. Fully in our hands.

#### C.1.3 `reasoning_effort` — per-model, and the two sources AGREE

VERIFIED-VENDOR-DOCS `openai.md:81-90` and VERIFIED-OSS `constants.py:311-334` were compared
model by model. **Every model present in both carries the identical set.** Wire values are
the lowercase strings in `bolna/enums.py:121-127`: `none`, `minimal`, `low`, `medium`,
`high`, `xhigh`.

| Model | Accepted values | `none`? | `minimal`? |
| --- | --- | --- | --- |
| `gpt-5.6-sol`, `-terra`, `-luna` | none, low, medium, high, xhigh | ✅ | ❌ |
| `gpt-5.5` | none, low, medium, high, xhigh | ✅ | ❌ |
| **`gpt-5.5-pro`** | **medium, high, xhigh** | ❌ | ❌ |
| `gpt-5.4` | none, low, medium, high, xhigh | ✅ | ❌ |
| `gpt-5.4-mini`, `gpt-5.4-nano` | none, low, medium, high | ✅ | ❌ |
| `gpt-5.2` | none, low, medium, high, xhigh | ✅ | ❌ |
| `gpt-5.1` | none, low, medium, high | ✅ | ❌ |
| `gpt-5`, `gpt-5-mini`, `gpt-5-nano` | **minimal**, low, medium, high | ❌ | ✅ |

The exclusivity is explicit at `openai.md:92-94`: *"`minimal` is valid only on `gpt-5`,
`gpt-5-mini` and `gpt-5-nano`. On `gpt-5.1` and later the equivalent is `none`."*

**`gpt-5.5-pro` cannot reach a low-latency effort at all** — its floor is `medium`. That, not
just price, is why the vendor says *"not ideal for latency-sensitive voice"* (`openai.md:44`).

#### C.1.4 ⚠ The default-effort trap, and it lands on the DIRECT leg, not the Azure one

VERIFIED-OSS, `constants.py:337-342`:

```python
def default_reasoning_effort(model: str) -> str:
    supported = MODEL_REASONING_EFFORT_MAP.get(model)
    if not supported or RE.MINIMAL in supported:
        return RE.MINIMAL.value
    return supported[0].value
```

**An UNKNOWN model name returns `"minimal"`** — a value every `gpt-5.1`-and-later model
*rejects*. Where the name comes from differs by leg:

- **Azure leg: guarded.** `azure_llm.py:79-81` passes `self.model_family`, i.e.
  `canonical_model(deployment_name)` (`constants.py:368-376`), which longest-match resolves
  `prod-gpt-5.4-mini` back to `gpt-5.4-mini`.
- **Direct-OpenAI leg: UNGUARDED.** `openai_llm.py:167` passes the **raw** `model` string.
  A dated snapshot name (`gpt-5.4-mini-2026-03-17`) or a prefixed one misses the map and
  gets `"minimal"`, which that model does not accept.

**Mitigable, completely, and the mitigation is one line of our config: always send
`reasoning_effort` explicitly rather than omitting it.** `kwargs.get("reasoning_effort")`
wins over the default at both call sites. Sending it also removes the entire class.

#### C.1.5 The Azure-only deployment-name hazard — **unchanged, still the worst on this surface**

VERIFIED-VENDOR-DOCS `azure-openai.md:69`: *"Bolna resolves the deployment to the model it
serves, and that resolution is what selects GPT-5 handling and the right default
`reasoning_effort`. **A name it cannot resolve is treated as a non-GPT-5 model and gets the
wrong defaults.**"* And `:71-73`: with a custom deployment name an unsupported
`reasoning_effort` *"is accepted when you create the agent and then fails on the call
instead."*

VERIFIED-OSS confirms the mechanism exactly: `canonical_model` (`constants.py:368-376`) is
substring-longest-match over `MODEL_REASONING_EFFORT_MAP` keys and *"Unrecognised names pass
through"*, and `openai_base.py:467` gates the `temperature = 1` override on the resolved
family. **So an unresolvable deployment name loses the temperature fix as well as the effort
default, and the failure is deferred from creation to the middle of a live call.**
Mitigation, stated by the vendor and provable from the source: **keep the model name inside
the deployment name.** Fully ours.

#### C.1.6 Responses-API auto-routing — informational, no action

`gpt-5.4`, `gpt-5.5`, `gpt-5.6` are routed through OpenAI's Responses API automatically
because function calling with `reasoning_effort` is not accepted on chat completions
(`openai.md:117`; `create.md:867-874`). VERIFIED-OSS: `constants.py:74-80`
(`RESPONSES_API_MODEL_PREFIXES`) and `task_manager.py:577-580`. Nothing to configure. It does
change which request shape a support conversation is about.

### C.2 Gemini — the important one. **RE-VERIFIED FROM PRIMARY SOURCES. THE CLAIM HOLDS.**

The claim under test, as D-456 states it: *thinking tokens share the reply budget and can
return a candidate with NO content field (silence on a phone call); the engine zeroes the
thinking budget ONLY on `gemini-2.5-flash` and `-flash-lite`; every `gemini-3.x` takes a
non-zero thinking level with no way to reach zero.*

**Verdict: the claim is CORRECT and is not outdated.** The engine's own `gemini.md` page not
mentioning thinking budget is not counter-evidence — it is the *absence* of a field, and
§C.2.4 shows the field genuinely is not in the published schema, which makes the docs page's
silence part of the problem rather than a refutation of it. Three refinements follow, one of
which widens the claim slightly.

#### C.2.1 The engine's actual thinking logic, read at `0172347b601e`

VERIFIED-OSS, `bolna/llms/gemini_llm.py:188-208`, quoted whole because every branch matters:

```python
def _get_thinking_config(self) -> "types.ThinkingConfig | None":
    """Thinking knob per family: 3.x takes thinking_level, 2.5 takes thinking_budget.

    Sending either one to the other family is a 400, so an explicit budget only
    applies to 2.5.
    """
    m = self.model

    if self.thinking_budget and self.thinking_budget > 0 and "2.5" in m:
        return types.ThinkingConfig(thinking_budget=self.thinking_budget, include_thoughts=True)

    if m.startswith("gemini-3"):
        return types.ThinkingConfig(thinking_level=default_thinking_level(m), include_thoughts=True)

    if "2.5" in m:
        if "pro" in m:
            # Pro cannot disable thinking; 128 is its floor.
            return types.ThinkingConfig(thinking_budget=128, include_thoughts=True)
        return types.ThinkingConfig(thinking_budget=0)

    return None
```

with `self.thinking_budget = kwargs.get("thinking_budget", 0)` at `:85` (**default zero**),
and the config assembled at `:210-226` where `max_output_tokens=self.max_tokens` (`:213`).

**What the six documented models actually get:**

| Model | What the engine sends | Thinking tokens out of our `max_tokens` |
| --- | --- | --- |
| `gemini-2.5-flash` | `ThinkingConfig(thinking_budget=0)` | **none — trap fully handled** |
| `gemini-2.5-flash-lite` | `ThinkingConfig(thinking_budget=0)` | **none — trap fully handled** |
| `gemini-2.5-pro` | `ThinkingConfig(thinking_budget=128, include_thoughts=True)` | **≥128 always; cannot be zeroed** |
| `gemini-3.5-flash` | `ThinkingConfig(thinking_level="minimal", include_thoughts=True)` | **always on; no zero exists** |
| `gemini-3.1-flash-lite` | `ThinkingConfig(thinking_level="minimal", include_thoughts=True)` | **always on; no zero exists** |
| `gemini-3.1-pro` | `ThinkingConfig(thinking_level="low", include_thoughts=True)` | **always on; no zero exists** |

Levels from `default_thinking_level` (`constants.py:357-365`) over
`GEMINI_THINKING_LEVEL_MAP` (`:345-354`): `minimal` for `gemini-3.5-flash` (`:350`),
`gemini-3.5-flash-lite` (`:351`), `gemini-3.1-flash-lite` (`:347`), `gemini-3.6-flash`
(`:352`), `gemini-3-flash-preview` (`:346`); `low` for `gemini-3.1-pro-preview` (`:349`) and
`gemini-3.7-flash` (`:353`); and `low` as the fallback for any name not in the map.

#### C.2.2 Refinement 1 — the mitigation predicate is wider than "flash and flash-lite"

The code does not name models; it tests `"2.5" in m and "pro" not in m`. **Any** 2.5 model
that is not a Pro gets `thinking_budget=0`. For the six models the vendor documents the
outcome is identical to D-456's phrasing, so **the decision text is accurate as written**
— it is just less general than the code. Worth knowing because it means a future
`gemini-2.5-flash-preview-xx` would also be safe, while a `gemini-2.6-flash` would not.

#### C.2.3 Refinement 2 — "no way to reach zero" is confirmed at GOOGLE'S OWN TYPE LEVEL

This is the strongest new evidence, and it upgrades the claim's class from VERIFIED-OSS
(the engine's behaviour) to **VERIFIED-VENDOR-DOCS (Google's own generated API surface)**.

`googleapis/python-genai@66807187f212`, `google/genai/types.py:364-376`:

```python
class ThinkingLevel(_common.CaseInSensitiveEnum):
  """The number of thoughts tokens that the model should generate."""
  THINKING_LEVEL_UNSPECIFIED = 'THINKING_LEVEL_UNSPECIFIED'
  MINIMAL = 'MINIMAL'
  LOW = 'LOW'
  MEDIUM = 'MEDIUM'
  HIGH = 'HIGH'
```

**There is no `OFF`, no `NONE`, no `ZERO`.** `MINIMAL` is the floor of the enum, and
`THINKING_LEVEL_UNSPECIFIED` means *unspecified*, not *disabled*. Compare the sibling field
at `types.py:5700-5704`, where a zero **does** exist:

```python
thinking_budget: Optional[int] = Field(
    default=None,
    description="""Indicates the thinking budget in tokens. 0 is DISABLED. -1 is AUTOMATIC.
    The default values and allowed ranges are model dependent.""",
)
```

So: **a zero exists only on the field the engine will not send to a 3.x model**, and the
field it does send has no zero. The enum being `CaseInSensitiveEnum` also confirms the
engine's lowercase `"minimal"` / `"low"` are accepted values rather than a latent bug.

#### C.2.4 Refinement 3 — the knob is passed through, and it is still not a mitigation

`llm-provider-postures.md` §3.4 recorded `thinking_budget` as *"a `kwargs` key with no field
in the documented `llm_config` schema"*. **Half of that is now sharper.** VERIFIED-OSS,
`task_manager.py:573-575`:

```python
for key in ("reasoning_effort", "verbosity", "reasoning_summary", "thinking_budget"):
    if key in self.llm_agent_config:
        self.llm_config[key] = self.llm_agent_config[key]
```

**`thinking_budget` IS an explicit, deliberate passthrough from `llm_config`** — not an
accidental `**kwargs` leak. It reaches `GeminiLLM.__init__`. But:

- **It is still absent from the published schema.** The full `SimpleLlmAgent` property list
  (`create.md:787-929`) is `agent_flow_type`, `provider`, `family`, `model`,
  `summarization_details`, `extraction_details`, `max_tokens`, `temperature`,
  `reasoning_effort`, `verbosity`, `use_responses_api`, `compact_threshold`,
  `presence_penalty`, `base_url`, `top_p`, `min_p`, `top_k`, `request_json`. **No
  `thinking_budget`. No `thinking_level`.** The schema sets no `additionalProperties: false`,
  so it is not *forbidden* — whether the hosted API's validator accepts it is **UNKNOWN**
  (hole H-4).
- **Even when accepted, it does nothing on 3.x.** The first branch of `_get_thinking_config`
  requires `"2.5" in m`, so on any `gemini-3.*` the value is read, logged (`:93`) and
  discarded.
- **`thinking_level` is not readable from config anywhere.** `grep -rn "thinking_level"` over
  the whole engine returns exactly three sites: the `constants.py` definition, the
  `gemini_llm.py` import, and the one call at `:200`. There is no kwarg, no config key, no
  override. **We cannot lower it, raise it, or unset it.**

#### C.2.5 The silence mechanism, assembled from Google's own types

Four facts, each VERIFIED-VENDOR-DOCS from `python-genai@66807187f212`:

1. **Thinking is metered separately but drawn from the same generation.**
   `types.py:8438-8452`: `thoughts_token_count` is its own field and `total_token_count` is
   *"the sum of `prompt_token_count`, `candidates_token_count`, `tool_use_prompt_token_count`,
   and `thoughts_token_count`"*.
2. **The stop reason exists and names the budget.** `types.py:498-499`:
   `MAX_TOKENS = 'MAX_TOKENS'` — *"Token generation reached the configured maximum output
   tokens."*
3. **A candidate with NO content is representable.** `types.py:8221-8225`:
   `content: Optional[Content] = Field(default=None, ...)`.
4. **And in that case `.text` is `None`, not `""`.** `types.py:8587-8601`:
   `if not self.candidates or not self.candidates[0].content or not self.candidates[0].content.parts: return None`.

**Google's own billing page independently confirms the two are one meter.** Every output row
on the page in §0.3 is labelled **"Text output (response and reasoning)"** — one price, one
line, response and reasoning together. That is VERIFIED-VENDOR-DOCS (Vertex surface) for the
half of the claim that says thinking tokens bill as output. The engine's `_usage_kwargs`
(`gemini_llm.py:22-33`, VERIFIED-OSS) does the same arithmetic on its side and says why:
*"Gemini keeps thinking tokens out of `candidates_token_count`; OpenAI folds them into
`output_tokens`, so add them here to keep billing consistent across providers."*

#### C.2.6 ⚠ NEW EVIDENCE — the engine names the outcome, in an error log

This lane's sharpest new finding. VERIFIED-OSS, `gemini_llm.py:461-465`, the terminal branch
of `generate_stream`:

```python
elif synthesize and not buffer.strip() and not _tool_dispatched:
    logger.error(
        "[GeminiLLM] Dead turn detected: synthesize=True, buffer empty, no tool dispatched. "
        f"accumulated_args_keys={list(_pending_fn_args.keys())} answer={answer!r}"
    )
```

**The engine has a named, logged, first-class state for "this turn produced no speech and no
tool call".** It exists only on the Gemini adapter — `openai_llm.py` and `openai_base.py`
have no equivalent. And note what the branch does: it logs and **yields nothing**. No retry,
no fallback line, no exception the caller can catch and cover with a filler phrase. The
generator simply ends.

**On a phone call, that is dead air.** The vendor's own source calls it a *dead turn*, which
is a stronger and more specific corroboration of D-456's *"silence on a phone call"* than
anything in the prior lane's file. It also means the failure would be **diagnosable after the
fact** (the log line is distinctive) and **invisible in the moment** to everything on our
side of the wire.

⚠ Note the branch is reachable for reasons other than thinking-budget exhaustion — a safety
block also returns empty content while streaming (`types.py:500-501`). **The dead-turn log is
proof the state exists and is anticipated, not proof of its cause.** Attributing a specific
dead turn to thinking tokens needs `thoughts_token_count` from the same execution.

#### C.2.7 So what IS the current correct mitigation? — a straight answer

| Model | Mitigable from our side today? | The mitigation |
| --- | --- | --- |
| `gemini-2.5-flash`, `gemini-2.5-flash-lite` | **YES — already done, by the engine, by default.** | `thinking_budget=0` is sent unconditionally. Nothing for us to configure. **Do not send a non-zero `thinking_budget`** — it would switch thinking back ON via the first branch. |
| `gemini-2.5-pro` | **PARTIALLY.** Bounded, not removable. | Floor of 128 thinking tokens. With `max_tokens: 150` that is **85% of the reply budget** before a word is spoken. Headroom must be sized for 128 + the reply. |
| **every `gemini-3.*`** | **NO.** | `thinking_level` is unreachable from config (§C.2.4) and has no zero (§C.2.3). `thinking_budget` is ignored on this family. **The only lever left is `max_output_tokens` headroom** (`gemini_llm.py:213`) — and it is unquantifiable: no vendor source this lane could reach publishes how many tokens `MINIMAL` spends, so there is no number to size the headroom against. Raising it also costs money on the "response and reasoning" meter and adds tail latency on a leg with a 350 ms TTFT budget. |

**Stated as a rule:** on `gemini-3.*` we would be shipping a leg where a request-field trap
we cannot address turns a caller's turn into dead air, with no bound we can compute and no
retry the engine performs. That is not a residency argument, a price argument or a
retirement argument — it is a correctness argument, and it stands on its own.

---

## D. Prices, USD per 1M tokens

**Read the class column before the numbers.** Hard rule 7 has no REPORTED tier and
`LlmModelSpec.__post_init__` (`packages/shared/src/calevate_shared/engine.py:900-907`,
VERIFIED-IN-REPO) enforces that by raising at import on a selectable model with unverified
price evidence.

### D.1 Gemini — VERIFIED-VENDOR-DOCS **on the Vertex surface only**

Read at the URL and hash in §0.3, **Standard tier, `Global` region, ≤200K input tokens,
text**, quoted from Google's own table:

| Vendor's row label | Input | Output ("response and reasoning") | Engine model string this maps to |
| --- | --- | --- | --- |
| Gemini 2.5 Pro | **$1.25** | **$10.00** | `gemini-2.5-pro` |
| Gemini 2.5 Flash | **$0.30** | **$2.50** | `gemini-2.5-flash` |
| Gemini 2.5 Flash Lite | **$0.10** | **$0.40** | `gemini-2.5-flash-lite` |
| Gemini 3.1 Pro Preview | **$2.00** | **$12.00** | `gemini-3.1-pro` (see §A.3 ⚠) |
| Gemini 3.5 Flash | **$1.50** | **$9.00** | `gemini-3.5-flash` |
| Gemini 3.5 Flash-Lite | **$0.30** | **$2.50** | *(not on the engine's docs page)* |
| Gemini 3.1 Flash-Lite | **$0.25** | **$1.50** | `gemini-3.1-flash-lite` |
| Gemini 3 Flash Preview | **$0.50** | **$3.00** | *(not on the engine's docs page)* |
| Gemini 3.6 Flash | **$0.75** → **$1.50** | **$3.75** → **$7.50** | *(OSS only — and it is the replacement `model_lifecycle.py` names)* |
| Gemini 3.7 Flash | **$0.75** → **$1.50** | **$3.75** → **$7.50** | *(OSS only)* |

**Caveats, all quoted from the same page — every one of these would silently corrupt a
derived rate:**

- **Dated promotional pricing on 3.6 and 3.7 Flash.** *"Gemini 3.7 Flash and Gemini 3.6
  Flash are offered with introductory pricing of $0.75 / $3.75 per 1M tokens input / output
  **through December 31, 2026**. Starting **January 1, 2027**, standard pricing of $1.5 /
  $7.5 per 1M tokens input / output will apply."* **A 2x step change on a known date.**
- **The 200K cliff is not marginal, it is retroactive.** *"If a query input context is
  longer than 200K tokens, **all** tokens (input and output) are charged at long context
  rates."* For 2.5 Pro that is $2.50/$15.00; for 3.1 Pro Preview $4.00/$18.00. Voice turns
  are small, but a large RAG context or a long call transcript could cross it.
- **Audio input is metered separately and costs more.** 2.5 Flash: text/image/video $0.30 but
  **audio $1.00**. 2.5 Flash Lite: text $0.10, **audio $0.30**. 3.1 Flash-Lite: text $0.25,
  **audio $0.50**. Our leg sends text (Sarvam does the STT), so the text row is the right
  one — but the distinction is a trap for anyone costing a future speech-to-speech path.
- **Tier multipliers.** Priority ≈ **1.8x** standard; Flex/Batch ≈ **0.5x**. Neither applies
  to a live call.
- **Non-global endpoints cost +10% and carry an unbounded promotional asterisk.** For 3.5
  Flash, non-global is $1.65/$9.90, footnoted *"Promotional pricing provided through 50%
  credits back on net spend on select models within a given period"* — **no period is
  stated**. Also: *"For non-global endpoints, pricing will go into effect for the Generally
  available Gemini 3 and later families of models on July 1, 2026"* — that date has passed,
  so the uplift is live.
- **Thinking is billed at the output rate.** Every output row reads *"Text output (response
  and reasoning)"*. This is the vendor confirming §C.2.5 in its own billing language.

### D.2 Gemini — the DEVELOPER API surface, which is the one we would be billed on: **REPORTED**

`ai.google.dev` is egress-blocked on every path tried, including the plaintext
`.md.txt` form. These are search summaries of third-party trackers
(cloudzero.com, benchlm.ai, getapipulse.com, costgoat.com, metacto.com, developer.puter.com),
read 23 Aug 2026:

| Model | Input | Output | Class |
| --- | --- | --- | --- |
| `gemini-2.5-flash` | $0.30 | $2.50 | **REPORTED** |
| `gemini-2.5-flash-lite` | $0.10 | $0.40 | **REPORTED** |
| `gemini-2.5-pro` | $1.25 | $10.00 | **REPORTED** (>200K: $2.50 / $15.00) |
| `gemini-3.5-flash` | $1.50 | $9.00 | **REPORTED** |
| `gemini-3.1-flash-lite` | $0.25 | $1.50 | **REPORTED** |
| `gemini-3.1-pro` | $2.00 | $12.00 | **REPORTED** (>200K: $4.00 / $18.00) |

**Every one of these matches §D.1's Vertex figure to the cent.** That is a real corroboration
signal and it is worth saying out loud — it means the trackers are not inventing numbers, and
it makes it *likely* Google prices the two surfaces identically for these models. **It does
not make them VERIFIED.** The surfaces are separately published and have diverged before
(the retirement dates in §E.2 differ by four days between exactly these two surfaces, which
is proof in this very file that "the two surfaces agree" is not a safe premise). Also
REPORTED for context: Batch API is 50% off on every model; context caching cuts repeat-prompt
input cost substantially; the free tier has been Flash and Flash-Lite only since 1 Apr 2026.

### D.3 OpenAI direct — **REPORTED, every single row, and no vendor page was reached**

**Stated without hedging, because the commission asked for it explicitly: this container
cannot reach any OpenAI-owned host. `openai.com`, `platform.openai.com`,
`developers.openai.com`, `cdn.openai.com` and `status.openai.com` were all refused;
`developers.openai.com/api/docs/pricing` — the current location of OpenAI's pricing page —
was refused on two independent egress paths. Not one OpenAI price below was read at an
OpenAI URL.**

Search summaries of third-party trackers (morphllm.com, cloudzero.com, benchlm.ai,
modelpricing.ai, aipricing.guru, techjacksolutions.com, eesel.ai, edenai.co, pecollective.com,
kickllm.com), read 23 Aug 2026:

| Model | Input | Output | Class | Note |
| --- | --- | --- | --- | --- |
| `gpt-5.6-sol` | $5.00 | $30.00 | **REPORTED** | ⚠ **Sources conflict**: one tracker reports promotional $4.00 / $20.00 *"at least through 21 Nov 2026"*. Two different numbers for one model. |
| `gpt-5.6-terra` | $2.00 | $12.00 | **REPORTED** | *"Starting July 30"* |
| `gpt-5.6-luna` | $0.20 | $1.20 | **REPORTED** | long-context $0.40 / $1.80. Reported as an **80% cut** on 30 Jul 2026 from a $1 / $6 launch price — i.e. this number is six weeks old and moved by 5x within the last quarter. |
| `gpt-5.5` | $5.00 | $30.00 | **REPORTED** | described as **legacy** — *"OpenAI no longer publishes GPT-5.5 on the current API pricing page"*. Still on the engine's supported list. |
| `gpt-5.5-pro` | — | — | **UNKNOWN** | **No 2026 tracker this lane reached carries a price.** One mentions an earlier-2026 figure of $30 / $180. Not usable. |
| `gpt-5.4` | $2.50 | $15.00 | **REPORTED** | long-context $5.00 / $22.50 |
| `gpt-5.4-mini` | $0.75 | $4.50 | **REPORTED** | Batch $0.375 / $2.25. **The vendor's recommended voice model — 5x our default on input, 7.5x on output, on an unread figure.** |
| `gpt-4.1` | $2.00 | $8.00 | **REPORTED** | |
| `gpt-4.1-mini` | $0.40 | $1.60 | **REPORTED** | equals this repo's Azure card exactly |
| `gpt-4o` | $2.50 | $10.00 | **REPORTED** | Batch $1.25 / $5.00; cached input $1.25 |

Adjacent, not on the direct-OpenAI docs list but on the Azure one: `gpt-5.4-nano` $0.20 /
$1.25 (**REPORTED**); `gpt-4o-mini` $0.15 / $0.60 (**REPORTED**, and identical to this
repo's Azure figure).

### D.4 The Azure leg — unchanged, and still not readable from here

`AZURE_LIST_PRICE_USD_PER_MTOK` / `LLM_MODELS`
(`packages/shared/src/calevate_shared/engine.py:968-992`, **VERIFIED-IN-REPO as our
record**): `gpt-4o-mini` $0.15 / $0.60, `gpt-4.1-mini` $0.40 / $1.60. These are D-410's own
verified Global Standard reading; `azure.microsoft.com`, `learn.microsoft.com` **and** the
`prices.azure.com` retail API are all blocked here, so this lane could not re-read them and
did not try to improve their class. The Regional-Standard premium (reported 5-10%) is
deliberately still not folded in.

**Did provider choice reprice anything at the default? No.** `gpt-4o-mini` is $0.15 / $0.60
on the Azure card and REPORTED at the same figure on OpenAI direct. **TRD §10 stays
unrepriced across all three legs at the shipped default.**

---

## E. Retirement dates

`scripts/check_model_lifecycle.py` REFUSES to score (exit 2) when its table does not cover
exactly the allow-list. So this section is what a new selectable model would have to bring
with it.

### E.1 Azure OpenAI leg — **VERIFIED-VENDOR-DOCS**, the only dated vendor facts in this file

Source: `MicrosoftDocs/azure-ai-docs@19bbfea4b8cd`,
`articles/foundry/openai/includes/concepts-model-retirement-schedule-content.md`, page
`ms.date: 08/19/2026`, table *"Foundry Models sold by Azure → Azure OpenAI"* (header at
`:26-27`). This is the repository `learn.microsoft.com` is published from, and it is the
same commit `model_lifecycle.py:230` already pins — **so this is a reproduction of that
entry's source, not a new one.**

| Model | Version | Lifecycle | **Retirement date** | Replacement | Line |
| --- | --- | --- | --- | --- | --- |
| `gpt-5.5` | 2026-04-24 | GA | **2027-10-26** | — | `:64` |
| `gpt-5.4` | 2026-03-05 | GA | **2027-09-02** | — | `:60` |
| `gpt-5.4-mini` | 2026-03-17 | GA | **2027-09-21** | — | `:61` |
| `gpt-5.4-nano` | 2026-03-17 | GA | **2027-09-21** | — | `:62` |
| `gpt-4.1` | 2025-04-14 | Legacy | **2027-04-14** | — | `:29` |
| `gpt-4.1-mini` | 2025-04-14 | Legacy | **2027-04-14** | — | `:30` |
| `gpt-4o` | 2024-05-13 | Deprecated | **2026-10-01** | `gpt-5.1` | `:32` |
| `gpt-4o` | 2024-08-06 | Deprecated | **2027-04-14** | `gpt-5.1` | `:33` |
| `gpt-4o` | 2024-11-20 | Legacy | **2027-04-14** | `gpt-5.1` | `:34` |
| `gpt-4o-mini` | 2024-07-18 | Deprecated | **2027-04-14** | — | `:35` |
| `gpt-5.6-sol` | 2026-07-09 | GA | **2028-01-11** | — | `:65` |
| `gpt-5.6-terra` | 2026-07-09 | GA | **2028-01-11** | — | `:66` |
| `gpt-5.6-luna` | 2026-07-09 | GA | **2028-01-11** | — | `:67` |

Three readings:

1. **`gpt-4o` has THREE different dates and the earliest is 39 days away.** The schedule
   keys on model *version*, not model name. A `model: "gpt-4o"` deployment created against
   the 2024-05-13 version dies **2026-10-01**. Any `gpt-4o` entry that omits a version is
   not a dated entry, it is three dated entries collapsed into a guess.
2. **`gpt-5.5-pro` is absent from Microsoft's schedule entirely** — corroborating §A.4:
   Azure does not serve it, and the engine's Azure page is correct to omit it.
3. **All three `gpt-5.6-*` models ARE scheduled on Azure (2028-01-11)** while the engine's
   Azure page does not list them. So the vendor's *"Azure has a short lag"* is a **Bolna-side
   gap, not an Azure-side absence** — which is a different and more fixable fact than the
   engine's page implies.

**⚠ These are MICROSOFT's dates for AZURE deployments. They are NOT OpenAI's dates for the
direct API.** Nothing in this table licenses a `retires_on` on an `openai`-provider row.

### E.2 OpenAI direct leg — **UNKNOWN. There is no verified retirement date for any model.**

OpenAI's deprecations page is on a blocked host (both the old `platform.openai.com` path and
the new `developers.openai.com/api/docs/deprecations`, probed and refused today). This is
already the honest state of the tree — `model_lifecycle.py:345-353` records `retires_on=None`
on both OpenAI rows and explains that the absence *is* the finding. **This lane confirms that
and could not improve it.** Every `gpt-5.6-*` / `gpt-5.5*` / `gpt-5.4*` on the direct leg is
undated for `check_model_lifecycle` purposes.

### E.3 Google Gemini — **REPORTED throughout, and the two surfaces disagree**

No reachable Google-owned host carries Gemini retirement dates. `ai.google.dev` (including
`/gemini-api/docs/deprecations.md.txt`), `docs.cloud.google.com` and `discuss.google.dev` are
all blocked; the one reachable Google page (§0.3) was grepped and **carries no retirement or
deprecation dates at all**. So:

| Model | Reported retirement | Class | Note |
| --- | --- | --- | --- |
| `gemini-2.5-flash` | **NONE announced** (GA) | **CORRECTED 2026-08-23** | **The earlier 16/20 Oct dates were preview-snapshot dates conflated with the GA ID.** Google's deprecations page (2026-08-13) lists GA `gemini-2.5-flash` with no shutdown date. |
| `gemini-2.5-flash-lite` | **NONE announced** (GA) | **CORRECTED 2026-08-23** | Google's deprecations page (2026-08-13) lists GA `gemini-2.5-flash-lite` with no shutdown date. The earlier inference from the '2.5 wave' was wrong for the GA ID. |
| `gemini-2.5-pro` | same 2.5 wave, no date read | **UNKNOWN** | On the engine's supported list with no date anywhere. |
| `gemini-3.1-flash-lite` | **7 May 2027** | **REPORTED** | |
| `gemini-3.5-flash` | **none announced** | **REPORTED-as-absent** | Absence of an announcement is not a guarantee of longevity. |
| `gemini-3.1-pro` | — | **UNKNOWN** | Google's own price page calls it **Preview**; a preview model has no support commitment. |

Also **REPORTED**: Google's published shutdown dates are described as the *earliest* possible
retirement, with the exact date communicated later — so these are lower bounds, not
commitments. Combined with the surface split, **no Gemini model can be given a VERIFIED dated
entry from anything this lane reached.**

---

## F. Verdict, and what is left open

### F.1 The two questions the commission asked, answered directly

**1. Can any OpenAI or Gemini price be VERIFIED from this container? — NO for OpenAI.
QUALIFIED-NO for Gemini.**

- **OpenAI: an unqualified no.** Five OpenAI-owned hosts refused, including the one where
  the pricing page now actually lives, confirmed on two independent egress paths. No OpenAI
  figure in this file may reach `unit_cost_paid`. `LlmModelSpec`'s import-time raise is doing
  exactly the job it was built for, and no OpenAI model may become `selectable=True` on
  anything written here. **The blocker is outside this repository**: a human opening
  `https://developers.openai.com/api/docs/pricing` and recording the reading. Note the two
  places in-tree that name the OLD URL (`engine.py::_OPENAI_PRICE_EVIDENCE` says
  `openai.com/api/pricing/`; `model_lifecycle.py:401` says
  `platform.openai.com/docs/deprecations`) — **whoever opens them should be sent to the
  `developers.openai.com` paths instead.**
- **Gemini: one Google-owned pricing page WAS fetched, and it still is not the right one.**
  §D.1 is genuine VERIFIED-VENDOR-DOCS for **Vertex AI / Agent Platform**. The engine's
  `google` leg is the **Gemini Developer API**, proven from the client constructor
  (`gemini_llm.py:48-49`). Six figures match the trackers to the cent, which is strong
  corroboration and is **not** a verification. **A Developer-API price remains REPORTED and
  hard rule 7 remains unsatisfied.** The blocker is external: a human opening
  `https://ai.google.dev/gemini-api/docs/pricing`. *(If the product ever moved the Gemini leg
  to Vertex — which the engine offers no way to do — §D.1 would satisfy hard rule 7 that day.)*

**2. Is the Gemini silence trap real and mitigable today? — REAL, re-verified from primary
sources, and NOT mitigable on any `gemini-3.*` model.**

Real, on four independent legs of evidence: Google's `ThinkingLevel` enum has no zero
(`types.py:364-376`); `Candidate.content` is `Optional` and `.text` returns `None` when it is
absent (`types.py:8221-8225`, `:8587-8601`); `FinishReason.MAX_TOKENS` names the budget as a
stop cause (`types.py:498-499`); and **the engine's own source has a named error state for a
turn that produces no speech and no tool call — `"Dead turn detected"`, `gemini_llm.py:461-465`
— which logs and yields nothing.** D-456's text is accurate as written; §C.2.2-C.2.4 sharpen
it without contradicting it.

Mitigation, by family: `gemini-2.5-flash` / `-flash-lite` are **already mitigated by the
engine** (`thinking_budget=0`, unconditional) and both retire in 54 days. `gemini-2.5-pro` is
**bounded at 128 tokens, 85% of a 150-token reply cap**, and cannot be zeroed.
**Every `gemini-3.*` is unmitigable from our side**: `thinking_level` is unreachable from
config, has no zero in the vendor's own enum, and `thinking_budget` is discarded on that
family. The only remaining lever is `max_output_tokens` headroom, and no reachable vendor
source publishes what `MINIMAL` spends — so the headroom cannot be sized, only guessed.

**The consequence for the commission: the `google` leg cannot be made selectable on current
facts, and the reason is neither residency nor price. It is that a request-field trap we
cannot address turns a caller's turn into dead air on every successor to the only two models
that are safe — and per Google's own deprecations page (2026-08-13) those two GA models carry NO announced shutdown. (An earlier draft of this file said 16 Oct 2026; that was a preview-snapshot date wrongly attached to the GA ID — corrected 2026-08-23.)**

### F.2 Holes — each with what closes it and whose it is

| # | Hole | What closes it | Ours or external |
| --- | --- | --- | --- |
| **H-1** | **No OpenAI price is verified.** Blocks every OpenAI model from `selectable=True`. | A human opens `https://developers.openai.com/api/docs/pricing` and records the reading. | **EXTERNAL** — network egress policy. |
| **H-2** | **No Gemini DEVELOPER-API price is verified**, only the Vertex card. | A human opens `https://ai.google.dev/gemini-api/docs/pricing`. | **EXTERNAL.** |
| **H-3** | Does the hosted platform validate `model` strings at agent creation? The OSS does not. | `POST /agent/v2` with a deliberately wrong model, read the response. | **OURS** — needs a Bolna account. |
| **H-4** | Does the hosted API accept the undocumented `thinking_budget` key in `llm_config`? The OSS passes it through (`task_manager.py:573`); the published schema omits it and sets no `additionalProperties`. | One `POST /agent/v2` carrying it, then `GET` the agent back and see if it survived. | **OURS** — needs a Bolna account. Moot for `gemini-3.*`, which discards it either way. |
| **H-5** | Is the Gemini model string `gemini-3.1-pro` or `gemini-3.1-pro-preview`? The engine's docs page and its own OSS map disagree, and Google's price page sides with the OSS. | One agent create with each. | **OURS.** Failure is currently silent (§A.3), which is why it should be settled before it stops being. |
| **H-6** | Is the OpenAI credential entry `OPENAI` or `OPENAI_API_KEY`? Two vendor pages disagree (§B.3). Unchanged from `bolna-llm-providers.md` §2.1. | `POST /providers` with one name, `GET /providers`, one live call. | **OURS** — needs a Bolna account and an OpenAI key. |
| **H-7** | No OpenAI-direct retirement date for any model (§E.2). `check_model_lifecycle` cannot date this leg. | A human opens `https://developers.openai.com/api/docs/deprecations`. | **EXTERNAL.** |
| **H-8** | Gemini retirement dates are REPORTED and surface-split (16 vs 20 Oct); `gemini-2.5-pro` and `gemini-3.1-pro` have none at all. | A human opens `https://ai.google.dev/gemini-api/docs/deprecations`. | **EXTERNAL.** |
| **H-9** | `model_lifecycle.py` names `gemini-3.6-flash` as `gemini-2.5-flash`'s replacement, but that model is **not on the engine's published supported list** (§A.3) — it exists only in the engine's OSS. | Either the engine's docs page catches up, or the replacement is restated as one the engine actually documents. | **OURS to state; the vendor's to publish.** |

### F.3 What this lane did NOT do

Wrote no code, changed no constant, touched no file but this one. It did not re-derive
`llm-provider-postures.md` §5 (data-use and erasure terms), §6 (region provability) or the
OpenAI regional-endpoint finding — those stand as that lane left them and this file does not
restate them. It did not re-probe `openai.com`, `platform.openai.com` or `deepmind.google`,
which the commission recorded as already measured.

---

### Sources cited in this file

**Bolna mirror (VERIFIED-VENDOR-DOCS, SHA-256 checked §0.4)** —
`bolna-findings/mirror/pages/providers.md` 40, 84-88, 96-103, 105-109, 111-136 ·
`.../providers/llm-model/openai.md` 9, 20, 28-30, 38-49, 51, 57-65, 71, 81-94, 117 ·
`.../gemini.md` 20, 34-41, 43, 49-55 ·
`.../azure-openai.md` 20, 28-30, 32, 38-47, 57-65, 69-73, 90, 97-98 ·
`.../api-reference/providers/add.md` 55-68 ·
`.../api-reference/agent/v2/create.md` 93, 787-929 (esp. 817-825, 826-835, 836-854, 855-866, 867-874, 898-901)

**`bolna-ai/bolna@0172347b601e` (VERIFIED-OSS)** —
`bolna/enums.py` 93-118, 121-127, 135-139 ·
`bolna/providers.py` 90-108 ·
`bolna/constants.py` 74-80, 311-334, 337-342, 345-354, 357-365, 368-376 ·
`bolna/llms/gemini_llm.py` 22-33, 48-49, 85, 93, 188-208, 210-226, 273-280, 461-465 ·
`bolna/llms/openai_llm.py` 163-171, 178-190 ·
`bolna/llms/openai_base.py` 448-455, 467-480, 717-738 ·
`bolna/llms/azure_llm.py` 52-58, 75-85, 88-90 ·
`bolna/agent_manager/task_manager.py` 566-580, 1802-1818

**`googleapis/python-genai@66807187f212` (VERIFIED-VENDOR-DOCS, generated types)** —
`google/genai/types.py` 364-376, 488-520, 5692-5708, 8218-8225, 8438-8452, 8587-8601

**`MicrosoftDocs/azure-ai-docs@19bbfea4b8cd` (VERIFIED-VENDOR-DOCS)** —
`articles/foundry/openai/includes/concepts-model-retirement-schedule-content.md` 11, 16-18, 26-67, 106-119

**Google, fetched (VERIFIED-VENDOR-DOCS, Vertex surface)** —
`https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing`,
2026-08-23T04:45Z, sha256 `85ec2197c1b89a37…`

**This tree (VERIFIED-IN-REPO)** —
`packages/shared/src/calevate_shared/engine.py` 744-1080 (esp. 831-935, 968-1080) ·
`packages/shared/src/calevate_shared/model_lifecycle.py` 230-245, 270-500 ·
`scripts/check_model_lifecycle.py` 1-80 ·
`docs/evidence/llm-provider-postures.md` §0-§9 · `docs/evidence/bolna-llm-providers.md` §2.1

**REPORTED (third-party trackers, read 23 Aug 2026, named so the next reader can weigh
them)** — morphllm.com, cloudzero.com, benchlm.ai, modelpricing.ai, aipricing.guru,
techjacksolutions.com, eesel.ai, edenai.co, pecollective.com, kickllm.com, getapipulse.com,
costgoat.com, metacto.com, developer.puter.com, vorplabs.com, distillabs.ai.
**None of these is sufficient for `unit_cost_paid` or for a verified lifecycle entry.**

---

## ADDENDUM — vendor pages read via founder + Comet browser agent (2026-08-23)

**Evidence class: VENDOR-PUBLISHED, founder-relayed.** The hosts below are egress-blocked
from this container and from CI, so these figures cannot be re-fetched by our toolchain and
are NOT marked `verified=True` in code. They are the vendor's own pages, read in a browser
by the founder via the Comet agent, reported with URL and on-page date. They are stronger
than the third-party trackers (which they corroborate to the cent) and they are the
FOUNDER'S SOURCE DOCUMENT for the operator-attested billing prices entered in the ops
console. Per the multi-provider design, the authoritative billing number is the attested
value, not any figure in source — so this addendum informs the pre-fill and the lifecycle
stance, never `unit_cost_paid` directly.

### Prices (USD per 1M tokens) — for the ops-console pre-fill
| model | input | cached input | output | source | page date |
|---|---|---|---|---|---|
| gpt-5.4-mini | 0.75 | 0.075 | 4.50 | developers.openai.com/api/docs/models/gpt-5.4-mini | accessed 2026-08-23 |
| gpt-5.4 | 2.50 | 0.25 | 15.00 | developers.openai.com/api/docs/models/gpt-5.4 | accessed 2026-08-23 |
| gemini-2.5-flash | 0.30 | 0.03 | 2.50 | ai.google.dev/gemini-api/docs/pricing | 2026-08-17 |
| gemini-2.5-flash-lite | 0.10 | 0.01 | 0.40 | ai.google.dev/gemini-api/docs/pricing | 2026-08-17 |
| gemini-3.5-flash | 1.50 | 0.15 | 9.00 | ai.google.dev/gemini-api/docs/pricing | 2026-08-17 |
| gemini-3.1-flash-lite | 0.25 | 0.025 | 1.50 | ai.google.dev/gemini-api/docs/pricing | 2026-08-17 |
| gpt-4o-mini (Azure Regional Std, East US 2) | 0.165 | 0.083 | 0.66 | azure.microsoft.com/en-us/pricing/details/azure-openai/ | accessed 2026-08-23 |
| gpt-4.1-mini (Azure Regional Std, East US 2) | 0.44 | 0.11 | 1.76 | azure.microsoft.com/en-us/pricing/details/azure-openai/ | accessed 2026-08-23 |

Gemini output price is billed INCLUDING thinking tokens (vendor label "response and
reasoning"). Azure Regional Standard is +10% on Global on all three figures, both models
available in East US 2 — the premium `AZURE_PRICE_EVIDENCE` said was deferred is now
vendor-confirmed, but TRD §10 stays UNREPRICED per CLAUDE.md; attestation can carry the
real invoiced figure.

### Retirement — resolves the OpenAI UNKNOWN
- OpenAI `gpt-5.4-mini` / `gpt-5.4`: NOT deprecated as of 2026-08-23; OpenAI policy is
  ≥6 months' notice for GA models, none posted. Lifecycle stance = "active, no retirement
  announced, verified 2026-08-23 (developers.openai.com)".
- Gemini GA `gemini-2.5-flash` / `gemini-2.5-flash-lite`: **NO shutdown date announced.**
  Read live from Google's own deprecations page, ai.google.dev/gemini-api/docs/deprecations,
  dated 2026-08-13 UTC (founder, 2026-08-23). The `retires_on=2026-10-16` in this repo's
  `model_lifecycle.py` for these GA IDs is WRONG: it conflated DATED PREVIEW snapshots
  (`gemini-2.5-flash-preview-05-20` shut 2025-11-18, `gemini-2.5-flash-preview-09-25`
  shuts 2026-02-17) with the GA IDs we ship, which carry no shutdown date. There is no
  ~54-day window; the two safe Gemini models are durable. CORRECT THE CODE.

### Thinking-token safety — Google's OWN docs confirm the D-456 trap
ai.google.dev/gemini-api/docs/generate-content/thinking (page dated 2026-08-17):
- 2.5-flash: `thinkingBudget` range 0–24576, **0 disables thinking** → SAFE.
- 2.5-flash-lite: `thinkingBudget` 0 disables; default is "does not think" → SAFE.
- 3.x flash/flash-lite: use `thinkingLevel` (minimal/low/medium/high). Vendor: **"Gemini 3
  Flash and Flash-Lite also do not support full thinking-off"** and **"minimal does not
  guarantee that thinking is off."** A candidate can return with empty text at
  `finishReason: MAX_TOKENS` → silence on a phone call. NOT SAFE. Non-selectable.

### OpenAI runtime traps (vendor-confirmed)
- `gpt-5.4-mini` / `gpt-5.4` reasoning_effort: none (default), low, medium, high, xhigh —
  **"none" is the default**, so no forced reasoning. `minimal` NOT supported on 5.4 (only
  original GPT-5); irrelevant since "none" is available.
- temperature must be 1; `max_tokens` deprecated in favour of `max_completion_tokens`.
