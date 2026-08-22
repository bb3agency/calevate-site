# Three LLM postures at wire level — Azure OpenAI vs OpenAI direct vs Gemini direct

**Lane P-1. Read 22 August 2026.** Question, in the founder's framing: D-449 withdrew the
India warranty and moved the declared posture to `us-azure-openai` / `eastus2`, so the
India constraint that refused both direct APIs is gone — *why not offer OpenAI direct or
Gemini direct alongside Azure, each as a declarable residency posture?*

**Scope.** The VENDOR FACTS an implementation lane would build on: the exact wire values,
the exact credential entries, every request-field trap, the data-use and erasure terms, and
price. Not a design. This lane wrote only this file and two amendment blocks in the two
prior reports it supersedes in part (§0.3).

**The short answer, so the reader knows what the evidence is for.** The residency argument
is spent, exactly as D-449 says, and it was never the strongest argument against either
vendor. Two arguments that survive it are stronger and neither is about India: **OpenAI
direct is the only one of the three whose region is provable from our own AST** (§6), and
**Gemini's thinking-token behaviour makes a phone agent go silent rather than merely
truncate** (§3.4). The verdict is in §8 and it is not "adopt none of them".

---

## 0. Evidence classes, egress, and integrity

### 0.1 Classes

| Class | Means here |
| --- | --- |
| **VERIFIED-VENDOR-DOCS** | Read in the vendor's own published documentation. For Bolna that is the in-tree mirror at `bolna-findings/mirror/`, cited `page:line`, SHA-256 re-checked against `MANIFEST.json` (§0.4). For OpenAI and Google it is a file under `src/`-equivalent in the vendor's **own** repository whose header marks it generated from their OpenAPI spec — the machine-readable value, not a rendered label. |
| **VERIFIED-OSS** | Read in the vendor's own open-source engine (`bolna-ai/bolna`), cited `file:line` at a pinned commit. **This is the engine we rent, but it is NOT proof of what the hosted platform runs** — the repo has kept these two classes apart since D-31 and this lane does not merge them. |
| **VERIFIED-IN-REPO** | Read in this tree, cited `file:line`. |
| **VENDOR-PUBLISHED** | The vendor published it somewhere reachable that is not their docs site — a release artifact, their own issue tracker, PyPI metadata. |
| **REPORTED** | A search-engine summary of a page this container could not open, or a third-party page. Never sufficient to write a number into `unit_cost_paid` or a sentence into a DPA. |
| **UNKNOWN** | Nobody here has established it. Recorded as a hole (§9), never filled with a guess. |

### 0.2 What the egress proxy allowed, measured rather than assumed

Measured 22 Aug 2026, by `curl` and by the fetch tool, which use different egress paths and
agreed on every row:

| Host | Result |
| --- | --- |
| `platform.openai.com`, `openai.com`, `api.openai.com`, `help.openai.com`, `trust.openai.com` | **BLOCKED** |
| `ai.google.dev` | **BLOCKED** |
| `docs.cloud.google.com` — where every `cloud.google.com/vertex-ai/...` doc 301s to | **BLOCKED** |
| `google-gemini.github.io`, `developers.google.com`, `firebase.google.com`, `policies.google.com` | **BLOCKED** |
| `learn.microsoft.com`, `azure.microsoft.com` | **BLOCKED** |
| `www.bolna.ai` | **BLOCKED** (403 on CONNECT, unchanged since 20 Aug) |
| `cloud.google.com` | 200, but 301s to the blocked `docs.` host — only the redirect is observable |
| **`github.com` / `raw.githubusercontent.com`** | **200** |
| **`pypi.org`** | **200** |

**So no word of OpenAI's or Google's terms of service was read at its own URL by this lane,
and §5 is REPORTED throughout.** That is a finding, not an apology, and §9 names the four
URLs a human must open.

**What the two reachable hosts bought is larger than it looks.** GitHub carries the
vendors' *own* repositories, and for wire values a generated type stub beats a docs page:
it is the machine-readable value rather than a human-readable label, which is the exact
distinction D-417 was written about. Three of this lane's four sharpest findings — the
Gemini region rejection (§6.3), OpenAI's regional endpoints (§6.2) and the engine's actual
thinking-token handling (§3.4) — are first-hand from source, not summaries.

### 0.3 What this supersedes, and what it does not

- `docs/evidence/openai-direct-api.md` — **stands.** This lane re-verified its
  `DataResidency` finding first-hand (§6.2) and adds the credential/erasure/posture
  material it did not cover. Its §4 remains REPORTED and this lane could not lift it.
- `docs/evidence/gemini-direct-api.md` — **its §3 is UPGRADED from REPORTED to
  VERIFIED-VENDOR-DOCS** by §6.3 below: the claim that the Developer API cannot express a
  region is no longer a search summary, it is a `raise ValueError` in Google's own SDK. Its
  §2 free-versus-paid ⚠ is **narrowed but not closed** (§5.2).
- `docs/evidence/subprocessor-erasure-reach.md` — **unchanged and re-confirmed.** Neither
  candidate adds a subject-granular erasure instrument (§5.3). Gate 36 gets no easier.
- **D-449's own text is confirmed on the point that matters**: *"D-448's refusal of OpenAI
  direct is SPENT ... that ground no longer discriminates."* This lane agrees and does not
  quote the India argument against either vendor anywhere below.

### 0.4 Integrity, checked rather than trusted

Every mirror page cited was hashed and compared to `bolna-findings/mirror/MANIFEST.json`,
22 Aug 2026. Nothing under `bolna-findings/` was read-modify-written by this lane.

```
OK  providers.md                                      63231b2b7a0c5a33
OK  providers/llm-model/openai.md                     37564414f4b1decc
OK  providers/llm-model/gemini.md                     780698114af9607e
OK  providers/llm-model/azure-openai.md               faeda3c225e378c7
OK  api-reference/providers/add.md                    58ae4bf242d30e5f
OK  api-reference/providers/get.md                    57136c64685c2c7a
OK  api-reference/agent/v2/create.md                  69e3dd768f1c2996
OK  concepts/latency.md                               72bfee9ca4382cce
OK  concepts/choosing-providers.md                    8efe1100667fe69b
OK  concepts/security.md                              019f41cfd0effe23
OK  customizations/multilingual-languages-support.md  176ec67471442350
```

OSS read at pinned heads, 22 Aug 2026: `bolna-ai/bolna` @ `0172347b601e`,
`googleapis/python-genai` @ `66807187f212`, `openai/openai-python` @ `e43b422412a9`.

**⚠ INCIDENTAL FINDING — 7 mirror pages do not match `MANIFEST.json`, and it is
pre-existing.** A full sweep of all 334 hashable pages was run while checking the eleven
above: 327 verify, **7 drift**, and all seven are in one cluster:

```
api-reference/agent/get_all_agent_executions.md      api-reference/executions/get_batch_executions.md
api-reference/agent/v2/get_agent_execution.md        api-reference/executions/get_execution.md
api-reference/agent/v2/get_all_agent_executions.md   api-reference/executions/get_executions.md
api-reference/batches/executions.md
```

**This lane did not cause it and did not touch it**: `git status --porcelain
bolna-findings/` is empty, and each drifted file's working-tree hash equals its `HEAD`
hash — the drift is committed. It has the shape CLAUDE.md warns about (a repo-wide
`ruff format .` once rewrote vendor code blocks inside pages other lanes cite by line
number). **None of the seven is cited by this report**, but they are exactly the pages
`bolna-response-contract.md` and `bolna-executions-cost.md` cite for the executions
contract, so anyone quoting those by `page:line` is quoting a page whose integrity is
currently unproven. Not this lane's to fix — flagged so somebody re-fetches or
re-manifests them.

---

## 1. The wire value for `llm_config.provider`, settled three ways

D-417 exists because `"azure"` was chosen off a provider matrix and a dashboard dropdown —
two human-readable labels — and would have been the wrong string. So this lane refused to
settle any of the three on one source. All three now have **two independent
machine-readable sources that agree**, and the second one is the vendor's own enum.

| Leg | Wire value | Source A — vendor docs (copy-pasteable JSON body) | Source B — vendor source (enum member) |
| --- | --- | --- | --- |
| Azure OpenAI | **`"azure-openai"`** | `providers/llm-model/azure-openai.md:20`, restated `:59` | `AZURE_OPENAI = "azure-openai"` |
| OpenAI direct | **`"openai"`** | `providers/llm-model/openai.md:20`, restated `:59` | `OPENAI = "openai"` |
| Google Gemini | **`"google"`** | `providers/llm-model/gemini.md:20`, restated `:51` | `GOOGLE = "google"` |

Source A: **VERIFIED-VENDOR-DOCS**, mirror, hashes in §0.4.
Source B: **VERIFIED-OSS**, `bolna/enums.py:93-118` @ `0172347b601e`, class `LLMProvider`.

The full enum, verbatim, because its membership answers questions people keep re-asking:

```python
class LLMProvider(str, Enum):
    OPENAI = "openai";        COHERE = "cohere";        OLLAMA = "ollama"
    DEEPINFRA = "deepinfra";  TOGETHER = "together";    FIREWORKS = "fireworks"
    AZURE_OPENAI = "azure-openai";                      PERPLEXITY = "perplexity"
    VLLM = "vllm";            ANYSCALE = "anyscale";    CUSTOM = "custom"
    OLA = "ola";              GROQ = "groq";            ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek";    OPENROUTER = "openrouter"
    AZURE = "azure";          GOOGLE = "google"
```

**Two consequences worth recording rather than re-deriving.**

1. **`azure` and `azure-openai` are BOTH real members and both resolve to the same class.**
   `bolna/providers.py:97,107` (VERIFIED-OSS): `LLMProvider.AZURE_OPENAI.value: AzureLLM`
   and `LLMProvider.AZURE.value: AzureLLM`. So `_llm_routing`'s recorded one-string fallback
   from `azure-openai` to `azure` is confirmed harmless **in the OSS** — it lands on the
   same class. This does not license changing the shipped value: the docs state
   `azure-openai` twice and that is what D-417 settled on.
2. **`SUPPORTED_LLM_PROVIDERS` maps our three legs to three DIFFERENT classes**
   (`bolna/providers.py:90-108`, VERIFIED-OSS): `"openai"` → `OpenAiLLM`, `"azure-openai"` →
   `AzureLLM`, `"google"` → `GeminiLLM`. They are not three configurations of one client.
   **Every request-field fact in §3 is per-class**, which is why a trap that is handled on
   one leg is unhandled on another.

**⚠ The OpenAPI does NOT constrain this field, so it cannot corroborate a third time.**
`api-reference/agent/v2/create.md:795-798` (VERIFIED-VENDOR-DOCS), the `SimpleLlmAgent`
schema, in full for `provider`:

```yaml
provider:
  type: string
  default: openai
  example: openai
```

No `enum`. A wrong provider string is therefore **schema-valid** and fails somewhere later,
not at agent creation. That is a reason to pin the value in one constant and test it, which
`_AZURE_LLM_PROVIDER` and `tests/in_call_llm_provider_test.py` already do for the Azure leg.

---

## 2. Credentials — how many `POST /providers` calls, and named exactly

**This is the highest-value fact in the lane and the one a wrong answer 401s on.**

The store is flat. `api-reference/providers/add.md:55-68` (VERIFIED-VENDOR-DOCS), the
`ProviderRequest` schema, is exactly two required strings:

```yaml
ProviderRequest:
  properties:
    provider_name:   { type: string, description: Name of the provider,  example: OPENAI_API_KEY }
    provider_value:  { type: string, description: Secret value/key associated with the provider,
                       example: sk-0123456789az }
  required: [provider_name, provider_value]
```

There is no per-provider object and no nesting, so **each entry a provider needs is its own
`POST /providers` call**. The endpoint set is `POST /providers`, `GET /providers`,
`DELETE /providers/:provider_key_name` (`api-reference/providers/overview.md:17-21`).

`providers.md:39-40` prefaces the property tables with the sentence that makes them binding:

> We currently have the following providers which you can connect to Bolna.
> All these keys **must** be added for the respective provider.

### 2.1 The answer

| Leg | Entries | Exact `provider_name` values | Mirror citation |
| --- | --- | --- | --- |
| Azure OpenAI | **4** | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_MODEL`, `AZURE_OPENAI_API_BASE`, `AZURE_OPENAI_API_VERSION` | `providers.md:96-102` |
| **OpenAI direct** | **1** | **`OPENAI`** | `providers.md:84-88`, key at `:87` |
| **Google Gemini** | **1** | **`GOOGLE`** | `providers.md:105-109`, key at `:108` |

Verbatim, `providers.md:87` and `:108`:

```
| `OPENAI` | Your OpenAI API key |
| `GOOGLE` | Your Google Gemini API key |
```

**Note the two namespaces do not derive from one another.** The credential entry is
`OPENAI`, uppercase; the `llm_config.provider` value is `"openai"`, lowercase. Same for
`GOOGLE` / `"google"`. Deriving either from the other is the same class of error as D-417.

### 2.2 ⚠ A REAL CONFLICT IN THE VENDOR'S OWN DOCS: `OPENAI` vs `OPENAI_API_KEY`

Three OpenAPI specs in the mirror print `example: OPENAI_API_KEY` on the `provider_name`
field — `api-reference/providers/add.md:61`, `get.md:73`, `remove.md:39`. The property
table at `providers.md:87` says `OPENAI`. **Both are VERIFIED-VENDOR-DOCS and they do not
say the same string.**

This lane's reading, and its confidence, stated separately so a later reader can disagree
with the reasoning without re-doing the work:

- **`OPENAI` is the value.** `providers.md` is the per-provider table, it names the
  provider it belongs to, and it sits under a sentence declaring those exact keys mandatory.
  The OpenAPI entry is an `example` on a generic field that names no provider — a
  placeholder illustrating *shape*, and the same placeholder appears on `DELETE`, where a
  provider-specific name would make no sense as a general example.
- **Confidence: high, not certain.** `AZURE_OPENAI_API_KEY` shows the vendor does use
  `_API_KEY` suffixes in this namespace, so `OPENAI_API_KEY` is not obviously a typo.

**And this one does not need to be guessed, which is the whole point.** Unlike
`AZURE_OPENAI_API_VERSION` — where nobody knows the value and gate 16f delegates it to a
human at a console — the credential *name* is readable back from the vendor:
`POST /providers` with one name, then `GET /providers`, and the store says which name it
holds. **That sequence is ours and it is API calls.** Any implementation lane must run it
before a live call, and must not ship `OPENAI` on the strength of this paragraph alone.

### 2.3 What one entry versus four actually buys

- **`AZURE_OPENAI_API_VERSION` has no analogue on either direct provider.** OPERATIONS §2
  gate 16f — the last marked assumption in D-410, where two of the vendor's own pages
  disagree about whether an api-version is even required on a v1 base URL — **is closed by
  deletion, not by an answer,** on either direct leg. That is a genuine reduction in
  unverified surface and it is the strongest operational argument either candidate has.
- **The deployment-name indirection disappears too.** On Azure, `model` carries a
  deployment id an operator chose and `azure_openai_model` is a second string that never
  reaches the wire (`_llm_routing`, `engine.py:544`). On both direct providers `model` **is**
  the model. `ModelBinding`'s two-strings-or-one question stops existing, and so does the
  failure mode where a leg that sent the model name looks right and 404s at dial time.
- **The residency chain gets one link shorter.** `AZURE_OPENAI_API_BASE` means the endpoint
  may be a value in *Bolna's* credential store rather than only in ours, and no read-back of
  ours can see it (`_llm_routing` docstring, VERIFIED-IN-REPO). One credential, no base-URL
  entry, removes that link.

---

## 3. Request-field traps

### 3.1 The `temperature` trap bites all three legs, and the brief understates it

`api-reference/agent/v2/create.md:826-835` (VERIFIED-VENDOR-DOCS), the `SimpleLlmAgent`
schema, verbatim:

```yaml
temperature:
  type: number
  format: float
  default: 0.1
  example: 1
  description: >
    Sampling temperature. **GPT-5-series models require exactly `1`** —
    any other value is rejected with `400 For GPT-5 models, temperature
    must be 1`. The field defaults to `0.1`, so a GPT-5 agent must send
    `1` explicitly rather than omitting it.
```

restated as a documented 400 at `create.md:92`, and identically on **both** provider pages
— `openai.md:29` and **`azure-openai.md:29`**. Corroborated in source: `bolna/llms/
openai_llm.py:171` (VERIFIED-OSS) puts `temperature` into `model_args` unconditionally,
whatever the model, and `AzureLLM` shares that path.

**Three corrections to the brief, in order of how much they matter.**

1. **This is not an OpenAI-direct trap. It is a GPT-5 trap, and it is already armed on the
   Azure leg we ship.** `azure-openai.md:29` carries the identical warning. Adopting
   `gpt-5.4-mini` — which is Bolna's recommendation for voice on *both* pages, and the
   OpenAPI's own `model` default (`create.md:803-806`) — breaks our adapter without any
   provider change at all.
2. **We send `"temperature": 0.1` and `"max_tokens": 400`, not `150`**
   (`apps/api/engine/bolna.py:2307-2308`, VERIFIED-IN-REPO). The brief says 150; 150 is the
   vendor's *example* and their `max_tokens` recommendation for voice. The 400 is deliberate
   and the comment above it argues the case on Telugu token fertility.
3. **Today the trap is latent and safe, and it is one `Literal` edit from live.**
   `AzureOpenAIModel = Literal["gpt-4o-mini", "gpt-4.1-mini"]`
   (`packages/shared/src/calevate_shared/engine.py:544`, VERIFIED-IN-REPO), and
   `GPT5_MODEL_PREFIX = "gpt-5"` with the branch guarded by `model.startswith(...)`
   (`bolna/constants.py:74`, `bolna/llms/openai_llm.py:165`, VERIFIED-OSS). Neither shipped
   model starts with `gpt-5`, so `0.1` is correct **and will keep being correct until
   somebody adds a GPT-5 model to that allow-list, at which point every publish 400s.**

### 3.2 `max_tokens` → `max_completion_tokens`, and the reasoning budget

`create.md:817-825` (VERIFIED-VENDOR-DOCS):

```yaml
max_tokens:
  type: integer
  default: 100
  example: 150
  description: >
    Cap on the tokens generated per response. On GPT-5-series models
    this is sent as `max_completion_tokens`, and reasoning tokens are
    drawn from the same budget, so raise it above the default when
    running `reasoning_effort` higher than `none`/`minimal`.
```

Confirmed in source at `openai_llm.py:165-171` (VERIFIED-OSS) — the key name literally
swaps:

```python
max_tokens_key = "max_tokens"
if model.startswith(GPT5_MODEL_PREFIX):
    max_tokens_key = "max_completion_tokens"
    self.model_args["reasoning_effort"] = kwargs.get("reasoning_effort") or default_reasoning_effort(model)
    self.model_args["verbosity"] = kwargs.get("verbosity", None) or Verbosity.LOW.value
self.model_args.update({max_tokens_key: self.max_tokens, "temperature": self.temperature, "model": self.model})
```

**So the brief's fear is confirmed for OpenAI/Azure and the engine already mitigates it.**
`default_reasoning_effort` (`bolna/constants.py:337-342`, VERIFIED-OSS) returns *"minimal
where available, else the lowest in its map"*, and `MODEL_REASONING_EFFORT_MAP["gpt-5.4-mini"]`
is `[NONE, LOW, MEDIUM, HIGH]` (`:323`) — no `MINIMAL`, so the default is **`none`**. At
`none` there is no reasoning to eat the budget, and our 400 is generous against a 1–3
sentence turn.

**⚠ But that mitigation is keyed on the model name, and an Azure deployment name defeats
it.** `default_reasoning_effort` does a bare `MODEL_REASONING_EFFORT_MAP.get(model)`; a
deployment id like `prod-voice-01` misses, falls to the `not supported` arm, and returns
**`"minimal"`** — which `gpt-5.4-mini` does **not** accept. The vendor documents exactly
this outcome at `azure-openai.md:69-73` (*"A name it cannot resolve is treated as a non-GPT-5
model and gets the wrong defaults"*; unsupported values *"accepted when you create the agent
and then fail on the call instead"*). The engine ships `canonical_model()` for precisely
this (`constants.py:368-376`) and `default_reasoning_effort` does not call it — **a vendor
defect, VERIFIED-OSS at `0172347b601e`, unverified against the hosted platform.**
**This is an Azure-only failure mode. Neither direct provider has deployment names, so
neither can hit it.**

### 3.3 The complete `llm_config` field list, for whoever writes the adapter

`create.md:787-928` (VERIFIED-VENDOR-DOCS), `SimpleLlmAgent`, every property:

| Field | Type / enum | Default | Notes from the schema |
| --- | --- | --- | --- |
| `agent_flow_type` | enum `[streaming]` | `streaming` | always `streaming` for voice |
| `provider` | string, **no enum** | `openai` | §1 |
| `family` | string | `openai` | cosmetic on their side |
| `model` | string | **`gpt-5.4-mini`** | |
| `max_tokens` | integer | **100** | §3.2 |
| `temperature` | float | **0.1** | §3.1 |
| `reasoning_effort` | enum `[none, minimal, low, medium, high, xhigh]` | `null` | *"GPT-5-series models only"* |
| `verbosity` | enum `[low, medium, high]` | `null` | *"GPT-5-series models only. Defaults to `low`"* |
| `use_responses_api` | boolean | `false` | *"Always on for `gpt-5.4`, `gpt-5.5` and `gpt-5.6` regardless of this field"* |
| `compact_threshold` | integer | `null` | Responses API only |
| `base_url` | string | **`https://api.openai.com/v1`** | |
| `presence_penalty`, `frequency_penalty`, `top_p`, `min_p`, `top_k` | float/int | 0, 0, 0.9, 0.1, 0 | *"Accepted for backwards compatibility. **Not sent to OpenAI or Azure models.**"* |
| `request_json` | boolean | `false` | |

**Two things a reader should not miss.**

- **`verbosity` has a contradictory default**: the schema says `default: null`, the
  description says *"Defaults to `low`"*. `openai_llm.py:168` (VERIFIED-OSS) resolves it —
  `kwargs.get("verbosity", None) or Verbosity.LOW.value`, so `low` is applied client-side
  when unset. The schema is the misleading half.
- **The five sampling knobs say "not sent to OpenAI or Azure models" and are silent about
  Google.** Read literally that means they *are* forwarded on a `provider: "google"` leg.
  Our body sends none of them, so nothing is at risk today; an adapter that starts sending
  `top_k` because "it is in the schema" would behave differently per provider. **UNKNOWN-6.**
- **There is no field for Gemini's thinking budget anywhere in this schema.** That is §3.4.

### 3.4 ⚠ THE GEMINI TRAP, AND IT IS WORSE THAN THE GPT-5 ONE

The brief asked for the Gemini equivalent of the reasoning-budget problem. It exists, it is
sharper, and the failure mode on a phone call is **silence, not a truncated sentence.**

**The mechanism, VERIFIED-VENDOR-DOCS from Google's own generated types**
(`googleapis/python-genai` @ `66807187f212`, `google/genai/types.py:5692-5707`):

```python
class ThinkingConfig(_common.BaseModel):
  """The thinking features configuration."""
  include_thoughts: Optional[bool] = ...
  thinking_budget: Optional[int] = Field(default=None, description=
      """Indicates the thinking budget in tokens. 0 is DISABLED. -1 is AUTOMATIC.
         The default values and allowed ranges are model dependent.""")
  thinking_level: Optional[ThinkingLevel] = ...
```

and `types.py:8438-8452`, the usage metadata, where thinking is accounted **separately**:

```python
thoughts_token_count: Optional[int] = ...
# total_token_count = prompt_token_count + candidates_token_count
#                     + tool_use_prompt_token_count + thoughts_token_count
```

**The behaviour, REPORTED but with a first-hand reproduction.** `valentinfrlch/ha-llmvision`
issue #609 (VENDOR-PUBLISHED as a third-party repro, read 22 Aug 2026):

> The thinking tokens are counted against `maxOutputTokens`, which causes responses to be
> empty or truncated.
>
> With `max_tokens: 50` and no `thinkingConfig` — **Gemini 2.5 Flash: only 2 output tokens
> remain, `finishReason: "MAX_TOKENS"`. Gemini 3 Flash Preview: zero output tokens,
> completely empty response content.** When zero tokens are left, the API returns
> `candidates` with **no `content` field**.

Corroborated by `langchain-ai/langchain-google` #1020 and Google's own developer forum
thread *"`max_output_tokens` isn't respected when using `gemini-2.5-flash`"*. One summary
puts the dynamic default at *"90 to 98 percent of your budget on anything non-trivial"*
(REPORTED — a blog, weakest class here, quoted for shape not for the number).

**Contrast with OpenAI, which is the reason this is the sharper of the two.** On GPT-5 the
reasoning tokens also draw on `max_completion_tokens` (§3.2) — but the reply is *truncated*,
and Bolna defaults the effort to `none` where the model allows it. On Gemini the model can
consume the entire budget and return **a candidate with no content at all**. A voice agent
whose LLM turn returns nothing does not say half a sentence; it says nothing, and the caller
hears dead air.

**Now the part that required reading the engine, and that changes the verdict.**
`bolna/llms/gemini_llm.py:85,188-209` (VERIFIED-OSS @ `0172347b601e`):

```python
self.thinking_budget = kwargs.get("thinking_budget", 0)          # :85  — DEFAULT ZERO
...
def _get_thinking_config(self) -> "types.ThinkingConfig | None":
    """Thinking knob per family: 3.x takes thinking_level, 2.5 takes thinking_budget.
    Sending either one to the other family is a 400, so an explicit budget only applies to 2.5."""
    m = self.model
    if self.thinking_budget and self.thinking_budget > 0 and "2.5" in m:
        return types.ThinkingConfig(thinking_budget=self.thinking_budget, include_thoughts=True)
    if m.startswith("gemini-3"):
        return types.ThinkingConfig(thinking_level=default_thinking_level(m), include_thoughts=True)
    if "2.5" in m:
        if "pro" in m:
            return types.ThinkingConfig(thinking_budget=128, include_thoughts=True)  # "Pro cannot disable thinking; 128 is its floor."
        return types.ThinkingConfig(thinking_budget=0)
    return None
```

**Read against `max_output_tokens=self.max_tokens` at `:213`, that is a three-row table:**

| Model family | What the engine sends | Thinking tokens out of our `max_tokens` |
| --- | --- | --- |
| `gemini-2.5-flash`, `-flash-lite` | `ThinkingConfig(thinking_budget=0)` | **none — the trap is handled** |
| `gemini-2.5-pro` | `ThinkingConfig(thinking_budget=128)` | **≥128 of 400, and it cannot be zero** |
| **`gemini-3.*` (every one)** | `ThinkingConfig(thinking_level=default_thinking_level(m), include_thoughts=True)` | **always on; there is no zero** |

`default_thinking_level` returns *"Lowest-latency thinking level the Gemini 3.x model
supports ... Unknown models fall back to `"low"`, the only level the whole 3.x family
accepts"* (`constants.py:357-365`) — lowest, but never off.

**So the honest finding is not "Gemini is broken for voice". It is narrower and worse:**

1. **On `gemini-2.5-flash` the trap is already mitigated by the engine**, and this lane
   would have reported the opposite if it had stopped at the docs. Say so plainly.
2. **`thinking_budget` is a `kwargs` key with no field in the documented `llm_config`
   schema** (§3.3). We cannot set it, raise it or lower it through the documented API. We
   inherit the engine's default, which is a value in somebody else's repository — exactly
   the objection `bolna.py`'s own comment raises about inheriting `max_tokens=100`.
3. **The only Gemini model on which thinking can be disabled is `gemini-2.5-flash`, which
   Google retires on 16/20 Oct 2026** (REPORTED, `docs/evidence/gemini-direct-api.md` §4.1,
   unchanged). Its successors are all `gemini-3.*`, and on every one of those the engine
   sends a non-zero thinking level with `include_thoughts=True`. **The mitigation and the
   retirement are the same model.**
4. **Thinking tokens are billed to us as output tokens.** `gemini_llm.py:26-31`
   (VERIFIED-OSS), the engine's own comment:

   > Gemini keeps thinking tokens out of `candidates_token_count`; OpenAI folds them into
   > `output_tokens`, so add them here to keep billing consistent across providers.

   ```python
   "output_tokens": (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0),
   ```

   Output tokens are the expensive ones on every card in §7. A metering lane must know that
   a Gemini leg's `output_tokens` is not the spoken reply's length.

### 3.5 The Responses API, the hardcoded WebSocket, and what `base_url` switches off

`openai.md:117` (VERIFIED-VENDOR-DOCS): *"`gpt-5.4`, `gpt-5.5` and `gpt-5.6` run through
OpenAI's Responses API automatically, because function calling combined with
`reasoning_effort` is not accepted on chat completions for those models."* Confirmed in
source at `constants.py:78-80`.

What the docs do **not** say, and what an in-call tool lane must know
(`openai_llm.py:39,46,206-210`, VERIFIED-OSS):

```python
class OpenAIWSConnection:
    """Persistent WebSocket connection to wss://api.openai.com/v1/responses."""
    WS_URL = "wss://api.openai.com/v1/responses"
...
self._ws_transport = None
if self.use_responses_api and kwargs.get("provider", "openai") != "custom" and not base_url:
    self._ws_transport = OpenAIWSConnection(api_key=api_key)
```

- On a plain `provider: "openai"` leg with **no** `base_url`, a Responses-API model gets a
  **persistent WebSocket to a hardcoded `api.openai.com`**. Good for latency; it also means
  the endpoint is fixed and not the one you configured.
- **Sending any `base_url` silently disables that WebSocket** and falls back to HTTP. So
  pinning a regional endpoint (§6.2) *costs* the persistent-connection latency win. That
  tradeoff is invisible from the docs and is a real design input, not a footnote.
- The same block confirms the `base_url` we send **is** read on the non-custom path
  (`:186-189`: `if base_url: AsyncOpenAI(base_url=base_url, ...)`) — VERIFIED-OSS only.
  It does **not** answer `_llm_routing`'s open question, which is about `AzureLLM` on the
  **hosted** platform. Do not let this close gate 16f's sibling.
- `openai_llm.py:173` sets `service_tier` (default `"default"`) — a field with **no entry in
  the documented `llm_config` schema**. An undocumented passthrough exists.

---

## 4. Models for voice, TTFT, function calling, Telugu

### 4.1 What each provider offers, per the engine

VERIFIED-VENDOR-DOCS. OpenAI (`openai.md:38-51`): `gpt-5.6-sol` / `-terra` / `-luna`,
`gpt-5.5`, `gpt-5.5-pro`, `gpt-5.4`, **`gpt-5.4-mini` — marked "Recommended: fastest TTFT,
lowest cost"**, `gpt-4.1`, `gpt-4.1-mini`, `gpt-4o`. Google (`gemini.md:34-43`):
`gemini-3.5-flash`, `gemini-3.1-pro`, `gemini-3.1-flash-lite`, `gemini-2.5-pro`,
**`gemini-2.5-flash` — marked "Recommended — proven, stable, fast"**, `gemini-2.5-flash-lite`.
Azure (`azure-openai.md:38-47`) mirrors OpenAI's list plus `gpt-5.4-nano` and `gpt-4o-mini`,
with the caveat that *"Azure model availability varies by region"* (`:49-51`).

`concepts/choosing-providers.md:55` puts `gpt-5.4-mini`, `gemini-2.5-flash` and
`deepseek-v4-flash` in one "Fast / cost-efficient" tier, and `:22` recommends
`gpt-5.4-mini` **or Sarvam** for the "Indian languages (Hindi, Tamil, etc.)" row.

### 4.2 ⚠ The vendor's own low-TTFT recommendation is not backed by its own latency page

`concepts/latency.md:64-69` (VERIFIED-VENDOR-DOCS), the complete TTFT table:

| Provider | Typical TTFT |
| --- | --- |
| OpenAI `gpt-4.1-mini` | ~150 ms |
| OpenAI `gpt-4.1` | ~200 ms |
| Anthropic `claude-sonnet-4-20250514` | ~250 ms |
| Google `gemini-2.5-flash` | ~150 ms |

and `:127` names `gpt-4.1-mini` and `gemini-2.5-flash-lite` as the low-TTFT choices.

**No GPT-5 model appears anywhere on that page.** The "fastest TTFT" claim for
`gpt-5.4-mini` at `openai.md:46` is a recommendation with **no measured number behind it in
the vendor's own latency documentation**, and the only two models the latency page actually
measures are a previous-generation OpenAI model and the Gemini model that retires in
October. On the vendor's own numbers, `gpt-4.1-mini` and `gemini-2.5-flash` **tie at
~150 ms** — which means TTFT does not discriminate between these providers on any evidence
we can cite. **UNKNOWN-4.**

**And the same page contradicts §3.1 in one line.** `latency.md:71`: *"Shorter prompts,
lower `max_tokens`, and `temperature` close to 0 all reduce TTFT."* On a GPT-5 model
`temperature` close to 0 is a documented 400. Their latency guidance predates their GPT-5
support and has not been reconciled. Follow §3.1, not this line.

### 4.3 Telugu

Language on this engine is a property of the **transcriber and synthesizer legs**, not the
LLM leg. `customizations/multilingual-languages-support.md:9` (VERIFIED-VENDOR-DOCS):
*"Language support is integrated across all components: transcription, LLM processing, and
voice synthesis"*, and the supported-language table at `:128-147` lists **Telugu `te`**.
Also at `agent-setup/audio-tab.md:57,241` and `concepts/choosing-providers.md:41`. **The
list is per-engine, not per-LLM-provider: `te` is supported on all three legs identically,
because the LLM never selects it.**

What differs is model quality in Telugu, and here the evidence is thin and vendor-authored
on both sides: `gemini.md:61-63` claims *"For Indian language agents (Hindi, Tamil, Bengali,
etc.), Gemini is a good alternative to Sarvam"* — **Telugu is not named** — while
`gemini.md:75` claims *"Gemini has an edge on multilingual tasks... GPT-5.4-mini has a
slight edge on English instruction following consistency"*. Both are the engine vendor's
unsourced opinion about third-party models. **No Telugu-specific benchmark for any of the
three was found from any reachable host. UNKNOWN-5**, and it is the one a pilot answers
cheaply.

One thing that *is* established and cuts across all three: Telugu token fertility is
~2.1–2.3 tokens/word against ~1.2–1.4 for English (`apps/api/engine/bolna.py:2265-2273`,
VERIFIED-IN-REPO, itself REPORTED from FLORES-200 comparisons). **Telugu costs roughly 1.7x
per spoken word on every provider's card in §7, and it makes every token budget in §3
tighter than its number suggests** — which is why the Gemini empty-response mode in §3.4 is
more likely on our traffic than on an English deployment.

### 4.4 Function calling

- OpenAI/Azure: all GPT-5 and GPT-4.1 models support it (`openai.md:115`), with the
  automatic Responses-API routing of §3.5.
- Gemini: `gemini.md` **says nothing about function calling at all** — the section is absent
  from the page, where OpenAI's has one. `gemini_llm.py:220-225` (VERIFIED-OSS) shows it is
  implemented (`types.Tool(function_declarations=...)`, with
  `AutomaticFunctionCallingConfig(disable=True)`), and `:88-92` shows a Gemini-3-specific
  workaround: *"Gemini 3 thought_signatures cannot survive bytes serialisation — the only
  reliable way to return them is to reuse the exact Part object the SDK gave us."*
- **This matters to us specifically**: the in-call RAG tool endpoint (100 ms budget) depends
  on reliable function calling. `docs/evidence/gemini-direct-api.md` §4.2 already records
  third-party voice-agent benchmarking calling tool calling *"its big weakness"* for Gemini.
  A documentation gap plus a serialisation workaround in the engine plus a REPORTED
  weakness is three weak signals pointing the same way, and none of them is proof.

---

## 5. Data use, retention, deletion — REPORTED throughout, and that is the finding

**No OpenAI or Google terms page was readable from this container (§0.2).** Everything in
§5.1 and §5.2 is a search-engine summary. §9 names what a human must open.

### 5.1 OpenAI direct

| Question | Answer | Class |
| --- | --- | --- |
| Do API inputs/outputs train models by default? | **No.** Not used for training by default; business/Enterprise data requires explicit opt-in, and the Enterprise DPA contractually prohibits it. | REPORTED |
| Default retention | **Up to 30 days** for abuse monitoring, then deleted absent a legal hold. Data *selected for human review* sits in an abuse-monitoring store *"for up to 30 days under strict access controls"*. | REPORTED |
| Who can read it | Authorised employees **and specialised third-party contractors under confidentiality agreements** — a sub-processor disclosure under DPDP, not a footnote. | REPORTED |
| Zero Data Retention | Real, **endpoint-specific, and approval-gated**: *"subject to prior approval by OpenAI and acceptance of additional requirements"*. Prevents retention rather than reversing it. | REPORTED |
| Modified Abuse Monitoring | A distinct, weaker control: *"excludes customer content (other than image and file inputs in rare cases) from abuse monitoring logs across all API endpoints"*. **This is the same instrument we already hold on Azure**, so it is not a differentiator — it is parity. | REPORTED |
| Private Safety Processing | Announced **19 Aug 2026 — three days before this reading.** Extends ZDR to frontier models with pattern-level abuse detection and no personnel access to content. **Anything written about OpenAI ZDR today has a short shelf life.** | REPORTED |
| DPA: self-serve or negotiated? | **UNKNOWN-1.** Every source describes ZDR/MAM/residency as *"get in touch with our sales team ... inquire about eligibility"*, which reads as negotiated, but no source states whether a standard DPA can be accepted online without a sales conversation. | UNKNOWN |

**⚠ The one first-party retention fact, and nobody would find it on a policy page.**
`openai/openai-python`, `src/openai/types/responses/response_create_params.py:179-197`
(VERIFIED-VENDOR-DOCS, generated from their OpenAPI spec), documenting
`prompt_cache_retention`:

> *"For `gpt-5.5`, `gpt-5.5-pro`, and future models, **only `24h` is supported**."*
> *"Organizations with ZDR enabled default to `in_memory` when `prompt_cache_retention` is
> not specified."*

**ZDR's prompt-cache escape is `in_memory`; on `gpt-5.5` and every model after it,
`in_memory` does not exist.** On an in-call turn the prompt prefix *is* the conversation so
far. Whether ZDR overrides this, refuses those models, or coexists with a 24-hour cache is
**UNKNOWN-2** and is the single most important thing to put to OpenAI in writing.

### 5.2 Google Gemini — the free/paid split, which is the whole decision

**First, D-127's reason, as the brief asked for it, quoted from `docs/ROADMAP.md:449`
(VERIFIED-IN-REPO):**

> **G-1 — the endpoint, and it is the whole decision**: `asia-south1-aiplatform.googleapis.com`
> with `locations/asia-south1` in the path; the AI Studio / Gemini Developer API
> (`generativelanguage.googleapis.com` ...) is **DISQUALIFIED, not deprioritised**.

So D-127 banned the Developer API on **region-expressibility**, not on training. §6.3 shows
that ground is now *stronger* than when D-127 was written — but D-449 removed the
requirement it served, so it no longer refuses anything on its own. The training question
therefore has to carry the weight, and here it is.

| Tier | What Google does with prompts and responses | Class |
| --- | --- | --- |
| **Unpaid** (AI Studio + free Gemini API quota) | *"Google uses the content you submit ... and any generated responses to provide, improve, and develop Google products and services and machine learning technologies"*, and *"human reviewers may read, annotate, and process your API input and output"*. Google's own instruction: *"[do] not submit sensitive, confidential, or personal information to the Unpaid Services."* | REPORTED |
| **Paid** | *"When you use Paid Services, Google doesn't use your prompts (including associated system instructions, cached content, and files ...) or responses to improve our products."* Logging is narrowed to *"a limited period of time, solely for the purpose of detecting violations of the Prohibited Use Policy"* — reported elsewhere as **55 days**. | REPORTED |

**The distinction is real and the paid tier does resolve the training objection.** A caller's
phone conversation with an SMB is personal information under DPDP by definition, so the
unpaid tier is disqualified by Google's own instruction, not by our interpretation. That
part is not close.

**Three things this lane found that sharpen it, and the third is new.**

1. **Enabling billing removes the free tier entirely.** REPORTED, 22 Aug 2026: *"When you
   enable billing for the Gemini API, you lose your free tier entirely. Every single API
   call becomes billable from that point forward. There is no free usage allowance within
   the paid tier."* If that is right, there is no mixed state and the boundary is an account
   property, cleanly.
2. **⚠ But Google's terms do not say so, and Google has been asked and has not answered.**
   `google-gemini/gemini-cli` issue **#1472**, *"Clarify use of user's code for training
   within the free quota on paid service"* (VENDOR-PUBLISHED — Google's own repository, read
   22 Aug 2026): the terms *"[state] that 'paid quota' usage isn't used for training, but
   the document doesn't explicitly address whether free-tier usage within a paid account
   receives the same protection"*, and **the thread carries no official Google response.**
   So the practice is reported to be unambiguous and **the contract is documented-ambiguous
   in Google's own issue tracker.** For a DPA warranty the contract is what binds.
3. **A regional carve-out runs the other way**: for the EEA, Switzerland and the UK the
   paid-services data terms *"apply to all services including the free tiers"* (REPORTED).
   **India is not in that carve-out.** An Indian data fiduciary gets the weaker default and
   has to buy its way out — worth knowing before anyone assumes the EU sentence is global.

**Zero Data Retention exists on the Developer API** and is *"approved ... for a particular
project"*, after which *"all user content (prompts and responses) and identifiable metadata
(such as IP addresses and Google Account IDs) are cleared prior to logging, with the
resulting record marked as sanitized"* (REPORTED). Same shape as OpenAI's: an application,
not a toggle. Also REPORTED and worth flagging because it is easy to trip: **Grounding with
Google Search stores prompts, context and output for 30 days** regardless. We would not
enable grounding; an adapter must not enable it by default.

**⚠ The `providers.md:108` credential has no tier in it.** Bolna's Google provider takes one
key named `GOOGLE` and nothing else — no project, no billing account, no tier field. **Which
terms govern a given in-call turn is therefore a property of a key we paste into a third
party's credential store, invisible on the wire and unreadable back from any Bolna API.**
That is not a reason it cannot be done correctly; it is a reason it cannot be *proved*, and
this repository's residency guard exists because "cannot be proved" is not good enough for a
DPA warranty.

### 5.3 Subject-granular deletion — gate 36, and neither candidate closes it

`docs/evidence/subprocessor-erasure-reach.md` records that **no vendor we use today has a
subject-granular delete** that reaches one caller's data. Checked for both candidates:

| Provider | Subject-granular delete? | What exists instead |
| --- | --- | --- |
| **OpenAI** | **Partially, and only for a copy we can choose never to create.** `DELETE /responses/{response_id}` and `DELETE /chat/completions/{id}` are real (`src/openai/resources/responses/api.md:169`, `api.md:98`, VERIFIED-VENDOR-DOCS). They delete the **stored response object** — the one you opted into with `store: true`. They say nothing about the 30-day abuse-monitoring copy, which is a separate retention path. `store: false` (`response_create_params.py:243-244`) never creates the object at all. | ZDR / Modified Abuse Monitoring, by approval |
| **Google** | **No.** No endpoint found from any reachable source; Google's own developer forum carries multiple unresolved threads alleging retention after deletion in AI Studio. | ZDR by project approval; 55-day expiry |
| **Azure** (incumbent) | **No** — REPORTED, unchanged | Modified abuse monitoring, already held |

**So the honest reading is a tie that slightly favours OpenAI and changes nothing
operationally.** The OpenAI `DELETE` routes are only reachable for objects we would have to
deliberately create, and the correct posture is `store: false` — which means never having
the object, which means never needing the delete. **Gate 36 is not closed by any of the
three, and this lane found nothing that closes it.** The instrument remains the contract
clause already drafted in `subprocessor-erasure-reach.md` §6.

**And the in-call leg is not ours to configure anyway.** On a BYOK leg *Bolna* builds the
request. `store`, `safety_identifier` and `prompt_cache_key` are not fields in Bolna's
`llm_config` schema (§3.3). **UNKNOWN-3: whether Bolna sends `store: false` on an OpenAI
leg.** `openai_llm.py`'s `model_args` at `0172347b601e` does not set `store` at all, and
the OpenAI default is unread from here. If Bolna omits it and OpenAI defaults it true, every
caller turn becomes a retrievable object in our OpenAI account that our retention worker
does not know exists. **This is the single most important thing to test before a live
OpenAI-direct call, it is ours to test, and it is API calls.**

---

## 6. Residency as a *declarable posture* — the axis that actually separates the three

The founder's framing is the right one and it is where the evidence is most decisive.
`scripts/check_model_residency.py` proves a posture from the AST; what it cannot prove is
delegated to a named human gate. **The three legs differ in how much falls on each side, and
the ordering is not the one the vendors' marketing implies.**

### 6.1 Azure — the region is NOT in the URL, by construction

`<resource>.openai.azure.com` names no region; the region is a property of the resource
(CLAUDE.md, D-449). So the guard proves one spelling of `AZURE_LOCATION`, no `Settings`
field carrying a region, and one builder — **and delegates to a human in the portal both
that the resource really is in East US 2 (gate 20) and that the deployment is Regional
Standard and NOT Global (gate 20c).** Global is Azure's default and processes worldwide, so
gate 20c is not a refinement: without it the posture has no enforceable property at all.
**Two standing human attestations, re-attested whenever anything changes.**

### 6.2 OpenAI direct — the region IS in the hostname, and this is new

**VERIFIED-VENDOR-DOCS**, `openai/openai-python` @ `e43b422412a9`,
`src/openai/_data_residency.py` — header *"File generated from our OpenAPI spec by
Castiron"*, read first-hand by this lane (not inherited):

```python
DataResidency = Literal["global", "us", "eu", "ae"]

_DATA_RESIDENCY_BASE_URLS: dict[DataResidency, str] = {
    "global": "https://api.openai.com/v1",
    "us":     "https://us.api.openai.com/v1",
    "eu":     "https://eu.api.openai.com/v1",
    "ae":     "https://ae.api.openai.com/v1",
}
```

and `:30-39`, which make the setting honest rather than decorative: `data_residency` is
**mutually exclusive** with `base_url`, `websocket_base_url` and `provider`, and an invalid
region raises locally, never reaching the network.

> **`us.api.openai.com` puts the region back in the hostname — the exact property D-449
> records Azure as having lost.** A `us-openai-direct` posture could be proved the way
> `check_model_residency.py` proved the old Vertex posture: one builder, one literal, one
> region in the URL, checkable from the AST — **with no portal attestation, no gate 20 and
> no gate 20c.**

**⚠ And the posture spec already in this tree does not know that.**
`scripts/check_model_residency.py:395-412` (VERIFIED-IN-REPO) defines an `openai-direct`
posture with `region=None`, `region_constant=None`,
`builder_suffix=f"https://{OPENAI_DIRECT_HOST}/v1"`, and the warrant *"NO REGIONAL CLAIM IS
MADE OR CHECKABLE under this posture — inference runs where the vendor runs it."* That was
correct against `api.openai.com`, which is the `global` endpoint. **Against
`us.api.openai.com` it is understated**, and D-449's own generalisation (`PostureSpec.region`
is now read rather than declared-and-ignored) is what makes a corrected spec a small
reviewed commit. **This lane does not edit that file — it is outside scope — but an
implementation lane must, and must carry the caveats below.**

**Four caveats, none of which is fatal and all of which are commercial:**

1. **Residency is an entitlement, not a request parameter.** REPORTED: *"Enterprise
   Customers that have been approved for advanced data controls can enable regional data
   residency by creating a new Project in the API Platform dashboard and selecting their
   preferred region"*, and *"for regional API requests, the domain prefix must be defined in
   requests"*. **Both halves are true: a project setting AND a URL prefix.** The URL is what
   we can prove; the project approval is what makes the URL work.
2. **Non-US regions carry an extra gate**: *"To use data residency with any region other
   than the United States, you must be approved for abuse monitoring controls, and execute a
   Modified Retention amendment"* (REPORTED). We would want `us`, which is the lighter path.
3. **A price exists**: *"Data residency endpoints are charged a **10% uplift** for models
   released on or after March 5, 2026, that are eligible for data residency"* (REPORTED,
   §7).
4. **On the in-call leg it costs the persistent WebSocket** (§3.5), and whether Bolna's
   hosted `openai` provider forwards our `base_url` at all is the same unanswered question
   gate 16f asks about Azure. **UNKNOWN-7.**

### 6.3 Gemini Developer API — the region is not merely unset, it is REFUSED

`docs/evidence/gemini-direct-api.md` §3 asserted this as REPORTED. **It is now
VERIFIED-VENDOR-DOCS, from Google's own SDK**, `googleapis/python-genai` @ `66807187f212`,
`google/genai/_api_client.py:681-682`:

```python
# Validate explicitly set initializer values.
if (project or location) and not self.vertexai:
    raise ValueError('Gemini API does not support project/location.')
```

and `:829-837`, the branch taken when `vertexai` is false:

```python
else:  # Implicit initialization or missing arguments.
    if not self.api_key:
        raise ValueError('No API key was provided. ...')
    self._http_options.base_url = 'https://generativelanguage.googleapis.com/'
    self._http_options.api_version = 'v1beta'
```

against the Vertex branch at `:824-828`, which builds
`https://{self.location}-aiplatform.googleapis.com/`.

> **This is the strongest possible form of the claim: not "no region is documented" but
> "asking for a region is a `ValueError` before a packet leaves the machine."** A
> Gemini-direct posture's `PostureSpec.region` can only ever be `None`. There is nothing for
> a residency guard to check and nothing a DPA can warrant beyond "somewhere in Google."

Two corroborations, both first-hand:

- The engine's Google leg is exactly this client. `bolna/llms/gemini_llm.py:48-49`
  (VERIFIED-OSS): `api_key = kwargs.get("llm_key", os.getenv("GOOGLE_API_KEY"))`;
  `self.client = genai.Client(api_key=api_key)` — **no `project`, no `location`, no
  `vertexai=True`.** D-401's and D-407's finding, re-verified in the engine's source rather
  than inferred from its docs.
- Auth is `x-goog-api-key`, not `Authorization: Bearer` (`_api_client.py:843`) — a wire
  detail an adapter would otherwise guess wrong.
- Vertex is not a way around it *here*: Bolna's `google` provider constructs the
  api-key client unconditionally, so a regional Vertex leg is only expressible through
  `provider: "custom"` — the route whose credential path retired gate 16c never verified,
  carrying the 1-hour OAuth bearer and the rotation machinery D-410 deleted.

### 6.4 The three postures, ranked by what a guard can prove

| | Region in the URL? | Provable from our AST? | Human attestations required | Posture expressible today |
| --- | --- | --- | --- | --- |
| **OpenAI direct, `us`** | **YES** — `us.api.openai.com` | **YES** | **none** | spec exists but says `region=None` — needs correcting |
| **Azure OpenAI** (in force) | no | partially — one region spelling, one builder | **two** (gate 20 resource region, gate 20c Regional-not-Global) | yes, declared |
| **Gemini direct** | **NO, and refused** | **no — nothing to check** | n/a — there is no claim to attest | expressible only as `region=None` |

**On the founder's own axis — "declarable residency postures, switched by a reviewed commit"
— OpenAI direct is STRICTLY STRONGER than the posture we are in, and Gemini direct is
strictly weaker than both.** That is the opposite of what D-448's spent argument implied,
and it is the single most consequential finding in this lane.

---

## 7. Price

USD per 1M tokens, standard tier (non-batch, non-cached), read 22 Aug 2026.

### 7.1 The incumbent's card, and whether provider choice repriced anything

`AZURE_LIST_PRICE_USD_PER_MTOK` (`packages/shared/src/calevate_shared/engine.py:656-659`,
**VERIFIED-IN-REPO** as *our* record; the underlying figures are Global Standard list
prices verified for D-410, on a host this container cannot reach):

| Model | In | Out |
| --- | --- | --- |
| `gpt-4o-mini` | $0.15 | $0.60 |
| `gpt-4.1-mini` | $0.40 | $1.60 |

**REPORTED, 22 Aug 2026: OpenAI direct lists `gpt-4o-mini` at $0.15 / $0.60 — the same
numbers**, with cached input at $0.075.

> **So the answer to "did provider choice reprice anything?" is NO, for the model we
> actually ship.** `gpt-4o-mini` costs the same on OpenAI direct as the Azure Global
> Standard list this repo already carries, so **TRD §10 stands unrepriced across all three
> postures at the current default** — ₹0.16/min at five minutes, ₹4.28 all-in ceiling, all
> unchanged. Two riders, both already carried as gates rather than folded into a number:
> Azure Regional Standard is reported 5–10% above Global Standard (unpaid, settled by the
> first invoice), and OpenAI's residency endpoints carry a reported **10% uplift** for
> models released on or after 5 Mar 2026 — which **excludes `gpt-4o-mini`**.

### 7.2 The candidate cards — **REPORTED, weakest section in the file**

Every OpenAI- and Google-owned pricing page is blocked (§0.2). These are search-engine
summaries of third-party trackers. **Nothing here may reach `unit_cost_paid` (Hard Rule 7)
until a human opens the two pages in §9.**

**OpenAI direct:**

| Model | In | Out | Note |
| --- | --- | --- | --- |
| `gpt-4o-mini` | $0.15 | $0.60 | = our current Azure card |
| `gpt-5.6-luna` | $0.20 | $1.20 | cheapest current-gen; long-context $0.40 / $1.80 |
| `gpt-5.4-nano` | $0.20 | $1.25 | |
| `gpt-5.4-mini` | $0.75 | $4.50 | **Bolna's recommended voice model — 5x/7.5x our default** |
| `gpt-5.6-terra` | $2.00 | $12.00 | |
| `gpt-5.4` | $2.50 | $15.00 | |
| `gpt-5.5`, `gpt-5.6-sol` | $5.00 | $30.00 | |

**Gemini Developer API, paid tier:**

| Model | In | Out | Note |
| --- | --- | --- | --- |
| `gemini-2.5-flash-lite` | $0.10 | $0.40 | **cheapest thing in this file** |
| `gemini-2.5-flash` | $0.30 | $2.50 | retires 16/20 Oct 2026 |
| `gemini-3.1-flash-lite` | $0.25 | $1.50 | thinking cannot be disabled (§3.4) |
| `gemini-3.5-flash` | $1.50 | $9.00 | |
| `gemini-3.6-flash` | $1.50 | $7.50 | global only, no residency |

**Three readings that survive the weak evidence class, because they are about ratios rather
than absolutes:**

1. **Output is where a voice agent's money goes, and the spread is 4x to 7.5x.** Our default
   is 4x (0.15 → 0.60). `gpt-5.4-mini` is 6x on a 5x-higher base. **Switching to the model
   both provider pages recommend for voice costs ~7.5x per output token**, whichever provider
   serves it — and per §4.2 there is no measured TTFT number backing that recommendation.
2. **Gemini's cheap tier really is cheaper, and it is the tier with the trap.**
   `gemini-2.5-flash-lite` at $0.10/$0.40 undercuts `gpt-4o-mini`; it is also inside the
   family that retires in October, and its successors are `gemini-3.*` where thinking cannot
   be switched off and thinking tokens bill as output (§3.4). **A cheaper per-token rate on a
   model that emits reasoning tokens you cannot disable is not a cheaper leg.**
3. **`gpt-5.6-luna` at $0.20/$1.20 is the interesting row nobody has costed.** Newer than
   `gpt-5.4-mini`, roughly a quarter its input price, and per `MODEL_REASONING_EFFORT_MAP`
   (`constants.py:329`, VERIFIED-OSS) it accepts `none` — so the reasoning budget can be
   zeroed. It is absent from the Azure model page (`azure-openai.md:38-47`), which is
   Bolna's *"Azure has a short lag"* (`:90`) showing up as a concrete difference rather than
   a slogan.

---

## 8. Verdict

**1. Offer OpenAI direct as a second declarable posture. It is the one candidate that makes
the product's residency story *better*, not worse.**

Not on price (identical at our default, §7.1) and not on latency (no measured number
separates them, §4.2). On **provability**: `us.api.openai.com` puts the region back in the
hostname, which is the property D-449 records Azure as having lost, and a `us-openai-direct`
posture would need **neither gate 20 nor gate 20c** — no standing human portal attestation
at all (§6.2). Secondary: it deletes gate 16f by deleting the field (§2.3), it is one
credential instead of four, and it removes the deployment-name indirection along with the
class of failure at `azure-openai.md:69-73` that only deployment names can produce (§3.2).
It is not free — it costs an enterprise entitlement, a Modified Retention conversation, the
persistent-WebSocket win (§3.5), and UNKNOWN-3 must be closed before a live call.

**2. Do NOT adopt Gemini direct, and the reason is no longer residency.**

D-449 spent the residency argument and this lane does not reuse it. Three independent
grounds survive it, and any one would be enough:

- **A phone agent can go silent.** Thinking tokens draw on `max_output_tokens` and can
  consume all of it, returning a candidate with **no `content` field** (§3.4). The engine
  mitigates this on `gemini-2.5-flash` by sending `thinking_budget=0` — **and that is the
  model Google retires in eight weeks.** On every `gemini-3.*` successor the engine sends a
  non-zero thinking level and there is no zero. We would be adopting a leg whose only safe
  model has a published retirement date and whose successors reintroduce the failure.
- **The tier that protects the data is not expressible or verifiable on the wire.** The paid
  tier genuinely resolves the training objection (§5.2) — but Bolna's Google provider takes
  one key named `GOOGLE` with no project, no billing account and no tier field, so which
  terms govern a live call is invisible on the wire and unreadable back from any API. And
  Google's own issue tracker carries an **unanswered** question about exactly the boundary
  we would be relying on (#1472). A DPA warranty cannot rest on that.
- **It cannot participate in the mechanism the founder is asking for.** A Gemini-direct
  posture's `region` can only be `None`, because asking for a region is a `ValueError`
  before a packet leaves the machine (§6.3). "Declarable residency posture" is a category
  the Developer API cannot enter.

**3. Keep Azure as the declared posture until UNKNOWN-3 and UNKNOWN-7 are closed, then
decide — and note that the decision is now closer than D-448 left it.**

D-449 retains Azure on an enterprise DPA, modified abuse monitoring, deployment-level
retirement control (which `scripts/check_model_lifecycle.py` consumes) and a specified
migration cost. **Two of those four are weaker than they read against OpenAI direct rather
than against Gemini.** Modified Abuse Monitoring is offered by OpenAI under the same name
and shape (§5.1) — parity, not an advantage. And deployment-level control is the same
mechanism that produces the `default_reasoning_effort` failure at §3.2 and gate 16f's
unanswerable `AZURE_OPENAI_API_VERSION`: it is a real benefit **and** the source of two
defects unique to that leg. The enterprise DPA and the migration cost stand unchallenged and
are, on this evidence, the whole remaining case.

**4. Two things to fix that are ours and are not blocked on anybody.**

- `scripts/check_model_residency.py:395-412`'s `openai-direct` spec is understated against
  `us.api.openai.com` (§6.2). Correcting it is the small reviewed commit D-449's
  generalisation was built to allow. **Outside this lane's write scope.**
- The `temperature: 0.1` / GPT-5 interaction (§3.1) is a live trap on the **Azure** leg we
  ship, one `Literal` edit away from breaking every publish, and it has nothing to do with
  which provider we choose. It deserves a test now, not when a model is added.

---

## 9. UNKNOWNs, and what closes each

Ordered by consequence. Marked **OURS** (API calls, no external blocker — CLAUDE.md tempo
rule) or by the external blocker's name.

| # | Unknown | What closes it |
| --- | --- | --- |
| **1** | Is an OpenAI DPA self-serve or negotiated? Every source routes ZDR/MAM/residency through *"get in touch with our sales team"*; nothing states whether a standard DPA can be accepted online. | A human on an unblocked network opening `openai.com/enterprise-privacy/`. **Blocker: blocked host, ~10 min.** |
| **2** | Does ZDR permit `gpt-5.5`+, given `prompt_cache_retention` admits only `24h` there and ZDR's escape is `in_memory`? Surfaced from a generated type stub, not a policy page. | A written answer from OpenAI on a ZDR application. **Blocker: vendor account + application.** |
| **3** | **Does Bolna send `store: false` on an OpenAI leg?** `store` is not in the documented `llm_config` schema and `openai_llm.py`'s `model_args` never sets it. If it is omitted and OpenAI defaults it true, every caller turn is a retrievable object our retention worker does not know exists. | `GET /providers` → `POST /providers` (`OPENAI`) → publish one agent → one call → `GET /responses` on our own OpenAI account. **OURS.** |
| **4** | TTFT for any GPT-5 model, and for any of the three from India. The vendor's own latency page measures only `gpt-4.1-mini` and `gemini-2.5-flash` and ties them at ~150 ms; no GPT-5 model appears on it. | One afternoon with real keys from a Mumbai host, all three legs head to head. **Blocker: vendor accounts.** |
| **5** | Telugu quality on each of the three. No benchmark for any of them found from any reachable host; both vendor claims are the engine vendor's unsourced opinion about third-party models. | The pilot. **OURS**, and cheap. |
| **6** | Are `top_p` / `top_k` / `min_p` / the penalties forwarded to Google? The schema says *"Not sent to OpenAI or Azure models"* and is silent about Google. | Publish one `provider: "google"` agent with a distinctive `top_k` and read it back. **OURS.** |
| **7** | Does Bolna's hosted `openai` provider read the per-agent `base_url`? Required before any regional endpoint (§6.2) can be pinned. It is the same question gate 16f asks about `azure-openai`, on a different provider. | The same publish-and-read-back sequence already queued for the Azure work. **OURS.** |
| **8** | Is the OpenAI credential entry `OPENAI` or `OPENAI_API_KEY`? Two vendor pages disagree (§2.2). | `POST /providers` with one name, then `GET /providers`. **OURS.** |
| **9** | Which paragraph of `ai.google.dev/gemini-api/terms` the human-reviewer sentence sits in, and whether free-quota usage on a billed project takes paid terms (#1472 is unanswered). | A human opening `ai.google.dev/gemini-api/terms`. **Blocker: blocked host, ~10 min.** — carried forward unchanged from `gemini-direct-api.md` §7. |
| **10** | Real list prices for every model in §7.2. | The same human, `openai.com/api/pricing/` and `ai.google.dev/gemini-api/docs/pricing`. **Blocker: blocked host.** |

**The four URLs a human must open**, consolidated: `openai.com/enterprise-privacy/`,
`openai.com/api/pricing/`, `ai.google.dev/gemini-api/terms`,
`ai.google.dev/gemini-api/docs/pricing`.

---

## 10. Sources

**VERIFIED-VENDOR-DOCS — Bolna mirror, in-tree, SHA-256 re-checked §0.4:**
`pages/providers.md` 39-40, 84-88, 96-102, 105-109, 111-136 ·
`pages/providers/llm-model/openai.md` 9, 17-31, 38-51, 57-71, 79-96, 115-117, 149 ·
`pages/providers/llm-model/gemini.md` 17-28, 34-43, 49-55, 59-63, 70-80 ·
`pages/providers/llm-model/azure-openai.md` 20, 28-32, 38-51, 57-73, 77-91 ·
`pages/api-reference/providers/add.md` 14-68 · `.../get.md` 70-73 · `.../remove.md` 39 ·
`pages/api-reference/providers/overview.md` 17-21 ·
`pages/api-reference/agent/v2/create.md` 85-93, 787-929 ·
`pages/concepts/latency.md` 60-71, 120-131 · `pages/concepts/choosing-providers.md` 21-26, 49-80 ·
`pages/customizations/multilingual-languages-support.md` 9, 126-147 ·
`pages/agent-setup/audio-tab.md` 57, 241

**VERIFIED-VENDOR-DOCS — vendors' own generated types, read first-hand 22 Aug 2026:**
`openai/openai-python` @ `e43b422412a9` — `src/openai/_data_residency.py` (complete),
`src/openai/types/responses/response_create_params.py` 179-197, 243-244;
`src/openai/resources/responses/api.md` 169, `api.md` 98 ·
`googleapis/python-genai` @ `66807187f212` — `google/genai/_api_client.py` 681-682, 795-843;
`google/genai/types.py` 5692-5723, 6458-6462, 8438-8452; `google/genai/client.py` 266-300

**VERIFIED-OSS — `bolna-ai/bolna` @ `0172347b601e`, read 22 Aug 2026. NOT proof of the
hosted platform:**
`bolna/enums.py` 93-123 · `bolna/providers.py` 46-48, 90-108 ·
`bolna/llms/openai_llm.py` 24, 39-46, 140, 155-210, 444-454, 506-522 ·
`bolna/llms/gemini_llm.py` 20-31, 37-49, 85-93, 188-225 ·
`bolna/constants.py` 74-80, 311-334, 337-342, 345-365, 368-376

**VENDOR-PUBLISHED:** `pypi.org/pypi/openai/json` — 3.3.1, 2026-08-19, `>=3.10` ·
`pypi.org/pypi/google-genai/json` — 2.19.0, 2026-08-19, `>=3.10` ·
`github.com/google-gemini/gemini-cli/issues/1472` (unanswered by Google) ·
`github.com/valentinfrlch/ha-llmvision/issues/609` ·
`github.com/langchain-ai/langchain-google/issues/1020`

**VERIFIED-IN-REPO:** `apps/api/engine/bolna.py` 340-368, 396-500, 2247-2308 ·
`packages/shared/src/calevate_shared/engine.py` 544-547, 576, 610-659, 862-870 ·
`scripts/check_model_residency.py` 280-360, 395-412, 419-426 ·
`docs/ROADMAP.md` 449 (D-127 G-1), 631 (D-410), 670 (D-449) ·
`docs/evidence/subprocessor-erasure-reach.md`, `docs/evidence/openai-direct-api.md`,
`docs/evidence/gemini-direct-api.md`

**REPORTED — every host below was ATTEMPTED from this container and BLOCKED:**
`openai.com/enterprise-privacy/` · `openai.com/api/pricing/` ·
`developers.openai.com/api/docs/guides/your-data` ·
`help.openai.com/en/articles/10503543-data-residency-for-the-openai-api` ·
`openai.com/index/expanding-data-residency-access-to-business-customers-worldwide/` ·
`ai.google.dev/gemini-api/terms` · `ai.google.dev/gemini-api/docs/zdr` ·
`ai.google.dev/gemini-api/docs/billing` · `ai.google.dev/gemini-api/docs/pricing` ·
`ai.google.dev/gemini-api/docs/openai` ·
`cloud.google.com/vertex-ai/generative-ai/docs/data-governance` (301 → blocked host)
**Third-party summaries:** `morphllm.com` · `cloudzero.com` · `devtk.ai` · `benchlm.ai` ·
`aipricing.guru` · `usagebox.com` · `meetily.ai` · `techstrong.ai` · `explainx.ai` ·
`scalevise.com` · `discuss.ai.google.dev` (blocked; via summary)
