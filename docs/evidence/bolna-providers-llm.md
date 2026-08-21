# Bolna providers — LLM, speech and the credential store, audited against the mirror

**Scope.** Every page in this lane, read end to end:
`bolna-findings/mirror/pages/providers/` (25 — `llm-model/` 6, `transcriber/` 10,
`voice/` 9), `api-reference/providers/` (4), `api-reference/user/` (3),
`agent-setup/llm-tab.md`, `agent-setup/audio-tab.md`,
`customizations/using-custom-llm.md`, `concepts/choosing-providers.md`, and the root
`providers.md`. **37 pages** (25 + 4 + 3 + 2 + 1 + 1 + 1).

**Evidence rule.** Every claim cites `bolna-findings/mirror/pages/<path>:<line>` and
quotes the line. `MANIFEST.json` records status 200, byte count and SHA-256 per page, so
these are fetched bytes rather than a transcription — the class is **VERIFIED-VENDOR-DOCS**.
Where the vendor contradicts itself the contradiction is **REPORTED, NOT RESOLVED**; this
repository has been burned three times (D-31, D-32, D-350) treating vendor prose as
specification, and an ambiguous page does not license a guess.

**Headline, in the order that matters.**

1. **LEAD-A is answered NO. Neither Azure model identifier is invalid, and there is no
   production-blocking defect.** Their Azure "Supported models" table lists all four
   `gpt-4o`/`gpt-4.1` variants including both *mini*s. The index sentence that raised the
   alarm was a marketing summary of the top of a table, not an allow-list. **No fork, no
   cost consequence, no founder decision forced.**
2. **Gate 16f's field-name question is CLOSED, and the guess was wrong.** Their Azure
   provider needs **four** credential entries and none of them is `AZURE`, which is what
   `Settings.bolna_llm_credential_name` defaulted to. Fixed to `AZURE_OPENAI_API_KEY`.
3. **A second, unrelated defect fell out of the same pages: our wire `provider` string was
   wrong.** We sent `"azure"`; their documented value is `"azure-openai"`. D-410 chose
   `azure` from two human-readable *labels*, which is the wrong class of evidence for a
   wire value. Fixed.
4. **One half of gate 16f stays open and got sharper**: the four keys include
   `AZURE_OPENAI_API_VERSION`, which contradicts our v1-surface premise, and the vendor's
   own two pages disagree about whether it is required. No value is invented.
5. **A silent Sarvam defect found and fixed**: pilot gate 1 configured `saaras:v2.5`,
   which **translates to English**, on a Telugu-first product. It does not 400 — that is
   what made it survivable.

---

## 1. LEAD-A — RESOLVED: `gpt-4o-mini` and `gpt-4.1-mini` are both listed. No defect.

The alarm came from the `llms.txt` index sentence, reproduced at
`providers/llm-model/azure-openai.md:7`:

```
> Use GPT-5.4-mini, GPT-5.4, GPT-4.1, or GPT-4o through Azure OpenAI for enterprise data residency and compliance.
```

The page body contains a "Supported models" table (`:36`) with eight rows.
`:44-47`:

```
| `gpt-4.1`      | 1M tokens   | Previous gen; still available   | Stable if already deployed                  |
| `gpt-4.1-mini` | 1M tokens   | Previous gen; still available   | Stable if already deployed                  |
| `gpt-4o`       | 128K tokens | Previous gen; still available   | Stable if already deployed                  |
| `gpt-4o-mini`  | 128K tokens | Previous gen; still available   | Stable if already deployed                  |
```

**Both members of `AzureOpenAIModel` are there, verbatim, marked available.** The index
sentence names the four the vendor is *recommending*, not the four the field accepts.

**And the field is not an enum at all**, which is the second half of the answer and is
stated twice. `:69`:

> "Azure deployment names are chosen freely, so `model` here is often not the model name.
> Keep the underlying model name inside the deployment name — `prod-gpt-5.4-mini` rather
> than `prod-voice-01`."

and `:97-98`, in the FAQ:

> **"Do I need a separate Azure deployment for each model?"** — "Yes. In Azure OpenAI, you
> create a named deployment for each model in the Azure portal. **The deployment name is
> what you pass as the `model` field in Bolna config.**"

This **confirms**, from the vendor's side, the argument `calevate_shared/engine.py` has
been making at length — `azure_openai_deployment` is not `azure_openai_model`, the wire
carries the deployment, and `Settings.azure_openai_model` never leaves us. `_llm_routing`
and `_agent_body` were already right, and `test_the_wire_carries_the_deployment_and_never_
the_model_name` was already pinning it.

**Verdict: NO GAP. No fork to present, and no ₹/min figure moves.** The founder decision
LEAD-A anticipated does not arise.

### 1a. But the page adds a trap our tree did not know about, and it is recorded now

`:69`, continuing:

> "Bolna resolves the deployment to the model it serves, and that resolution is what
> selects GPT-5 handling and the right default `reasoning_effort`. **A name it cannot
> resolve is treated as a non-GPT-5 model and gets the wrong defaults.**"

For us today this is harmless in the luckiest possible way: `AzureOpenAIModel` is closed
to two GPT-4-class models, and "treated as a non-GPT-5 model" *is* the correct handling
for both. It becomes a live trap the moment anyone adds a GPT-5 model to that Literal —
`prod-voice-01` would then be served GPT-4-era defaults on a GPT-5 model with no error
anywhere. Recorded at `Settings.azure_openai_deployment` and at `AzureOpenAIModel`.

### 1b. A second GPT-5 trap: `temperature`

`providers/llm-model/azure-openai.md:29`:

> "GPT-5-series models require `"temperature": 1`. Any other value is rejected with
> `400 For GPT-5 models, temperature must be 1`, and the field defaults to `0.1` when
> omitted, so send it explicitly."

`apps/api/engine/bolna.py::_agent_body` sends `"temperature": 0.1` — correct and
deliberate for the models we run (D-283's reasoning stands unchanged and the vendor's own
default agrees with it). On any GPT-5 model **every publish would 400**. That checklist is
now written at `AzureOpenAIModel`, where the person adding a member will read it.

---

## 2. Gate 16f — the credential FIELD NAMES are settled, and the default was wrong

This was the last marked assumption in D-410 and the thing CLAUDE.md calls "one API call"
away. Half of it is now answered from the page rather than the account.

`providers.md:96-102`, "LLMs" tab, "Azure OpenAI" accordion:

```
    <Accordion title="Azure OpenAI">
      | Property                   | Description                  |
      | -------------------------- | ---------------------------- |
      | `AZURE_OPENAI_API_KEY`     | Your Azure API key           |
      | `AZURE_OPENAI_MODEL`       | Your Azure OpenAI model      |
      | `AZURE_OPENAI_API_BASE`    | Your Azure URL               |
      | `AZURE_OPENAI_API_VERSION` | Your Azure Model API version |
```

under the sentence at `providers.md:40`:

> "All these keys **must** be added for the respective provider."

And the store itself is flat. `api-reference/providers/overview.md:18-20`:

```
POST /providers
GET /providers
DELETE /providers/:provider_key_name
```

`api-reference/providers/add.md:55-68` — `ProviderRequest` is exactly
`{provider_name, provider_value}`, both required, no per-provider object and no way to
write several fields at once. So **four keys means four POSTs**, and
`api-reference/providers/get.md` confirms `GET /providers` returns a bare array of
`{provider_id, provider_name, provider_value}` with the value masked — which is what
`BolnaEngine._llm_credential_ids` already assumes (`vendor_http` wraps a bare array as
`{"data": [...]}`; no defect there).

### THE DEFECT: `bolna_llm_credential_name` defaulted to `AZURE`, which does not exist

D-410 derived it: their matrix names single-key entries after the provider in upper case
(`OPENAI`, `GOOGLE`, `SARVAM` — all three visible at `providers.md:87`, `:108`, `:155`),
so `azure` became `AZURE`. The derivation generalised a rule that is real for one-key
providers and does not survive a provider needing a key, an endpoint, a model and a
version. **A key installed under `AZURE` authenticates nothing**, and the symptom would
have been a 401 from Azure on the first turn of the first call — after the account, the
resource and the deployment were all correctly set up.

**Fixed** to `AZURE_OPENAI_API_KEY`. Still a setting, still `applies: live` — the reason
changed rather than disappeared: a documented name and a live account's actual name are
different claims, and gate 16f's `GET /providers` can still disagree with the page.

### THE HALF THAT STAYS OPEN, and it is now a sharper question

`AZURE_OPENAI_API_VERSION` — "Your Azure Model API version" — **contradicts the whole
reason D-410 chose the v1 surface.** `…/openai/v1` has no `api-version`; a dated string
belongs to the classic `…/deployments/{id}/chat/completions?api-version=…` surface.

**And the vendor contradicts itself about it.** `providers/llm-model/azure-openai.md:32`:

> "Connect your Azure account at platform.bolna.ai/auth/azure. **You'll need your Azure
> endpoint URL, API key, and deployment name.**"

Three things. No api-version. Two first-party pages, one saying four keys are mandatory
and one describing the same connection as three.

Three readings survive and nothing here picks one:

1. it is vestigial for a v1 base URL and any value is ignored;
2. their Azure client is the **classic** one, and D-410's endpoint choice is wrong;
3. it is required but unvalidated.

**No value is invented.** `apps/api/engine/bolna.py::_AZURE_PROVIDER_KEYS` records all
four names, each one's source in our settings, and the fact that this one has none.

### A THIRD consequence, and it touches residency — so it is stated carefully

`AZURE_OPENAI_API_BASE` is a **provider-level** credential. Their documented per-agent
Azure config has **no `base_url` row at all** (`azure-openai.md:59-65` Key settings:
`provider`, `model`, `max_tokens`, `temperature`, `reasoning_effort`, `verbosity`,
`agent_flow_type`) — while the Custom-LLM accordion's example *does* carry one
(`providers.md:120`).

So it is possible that on an `azure-openai` leg the endpoint comes from **their credential
store**, and the `base_url` our `_llm_routing` puts in `llm_config` is inert.

**What that costs, stated at the strength the page supports and no further.** It would add
a link to the residency chain that lives in *their* store rather than ours, and **no
read-back of ours can see it** — `_agent_models` reads the endpoint off the agent object,
and an agent whose `base_url` is ignored reads back identically to one whose `base_url` is
honoured. This does **not** weaken any sentence about `AZURE_LOCATION`, the resource, or
the Regional-not-Global deployment type; those were already human-attested (gates 20/20c)
and are unchanged. It means the drift sweep covers one link fewer than a reader of
`_agent_models` would assume. `base_url` is still sent — their `SimpleLlmAgent` schema has
the field (VERIFIED-OAS), and a value that might be read beats a key that is certainly
ignored — and the gate now asks for the Azure resource's own metrics as the confirmation.

---

## 3. The wire `provider` string was wrong: `azure` → `azure-openai`

Found while verifying `_llm_routing` against their vocabulary, as the lane asked.

`providers/llm-model/azure-openai.md:20`, inside a copy-pasteable agent body:

```json
"llm_config": {
    "provider": "azure-openai",
```

and again at `:59`, in the Key settings table:

```
| `provider`         | string  | `"azure-openai"` | Provider name                          |
```

**Why this beats what D-410 had.** Their OSS `LLMProvider` carries *both* spellings, so
the question was always "which of two real names". D-410's evidence was a published
provider matrix reading `Azure OpenAI` and a live agent dropdown offering `azure` — **both
human-readable labels**, and `agent-setup/llm-tab.md` shows the dashboard label is indeed
just "Azure". A label cannot settle a wire value. The docs give a machine-readable one,
twice, and the form is corroborated across every sibling page: `openai`
(`openai.md:20`), `anthropic` (`anthropic.md:20`), `google` (`gemini.md:20` — note: not
`gemini`), `deepseek` (`deepseek.md:24`), `openrouter` (`openrouter.md:20`), `custom`
(`providers.md:112`). Each of those is a spelling this repository already treats as the
wire name.

**Fixed**, with `azure` kept in the comment as the one-string fallback — the same
structure D-410 had, with the ordering inverted by evidence rather than taste.

### `custom` is now *more* clearly wrong, not less

CLAUDE.md asked whether the docs change the calculus on the retired gate 16c. **They make
it worse for `custom`.** The entire documented custom-LLM flow takes two values and has
**no credential field anywhere**:

- `customizations/using-custom-llm.md:32-33` — the dashboard dialog is `LLM URL` and
  `LLM Name`.
- `api-reference/user/add_model.md:39-45` — `POST /user/model/custom` requires exactly
  `custom_model_name` and `custom_model_url`.
- `providers.md:111-112` — the Custom-LLM accordion is **the only provider entry in the
  file with no key table at all**: *"For custom llm simply keep provider in the
  `llm_agent` key as `custom` and add a openai compatible `base_url`."*

Our Azure endpoint requires `Authorization: Bearer <key>` on every request, and there is
no documented way for a custom model to carry one. **Route not switched; the reason is
now documentary rather than a browser sweep.**

---

## 4. Speech (D-36) — identifiers verified, one real defect found

### 4a. TTS — Bulbul: **no gap**

`providers/voice/sarvam.md:42-44` lists exactly `bulbul:v3`, `bulbul:v2`, `bulbul:v1`.
`apps/api/agents/voices.py` ships `bulbul:v3` (premium/default) and `bulbul:v2` (value) —
both supported, tier names ours and unaffected. D-36's ladder survives contact intact.

Worth recording: **`bulbul:v4` is not on this engine.** `apps/api/billing/rates.py:126`
notes search summaries reporting Sarvam has shipped v4 — the table above is first-party
evidence that Bolna does not expose it. No action; the note is now answerable.

### 4b. STT — Saaras: **a silent defect, fixed**

`providers/transcriber/sarvam.md:61-64` lists four models, and separates them on an axis
our tree did not model:

```
| saarika:v2.5 | Speech-to-text transcription in original language                     |
| saaras:v2.5  | Speech-to-English translation with automatic language detection      |
| saaras:v3    | Speech-to-text transcription in original language                    |
| saaras:v4    | Latest Saaras model ... original language, with automatic language detection support |
```

restated at `:84-87`. **`saaras:v2.5` translates. It does not transcribe.**

`scripts/pilot/gates_api.py` configured `saaras:v2.5` — on the agent that dials a real
Indian telephone for pilot gate 1, on a Telugu-first product. Meanwhile
`scripts/pilot/scorecard.py:661` prices "Sarvam Saaras V3 STT" and the conformance suite
configures `saaras:v3`. Three spellings of one leg; the one that would have run was the
one returning English.

**Why it had survived: nothing fails.** The model is supported, the request succeeds, the
transcript is well-formed. The damage is downstream and silent —
`apps/workers/redaction.py:92` matches transliterated Telugu digit words and
`apps/api/compliance/optout.py:111` matches romanised Telugu opt-out phrases, and neither
survives a translation. **An unrecognised opt-out is a compliance failure, not a quality
one.**

**Fixed** to `saaras:v3`, with a scan test (`SARVAM_TRANSLATING_STT`) so it cannot come
back. `saaras:v4` was deliberately **not** adopted — see §7.

### 4c. Language coverage — **no gap, with one spelling to know about**

`providers/transcriber/sarvam.md:68-80` — 11 languages, Telugu `te-IN` at `:74`.
`agent-setup/audio-tab.md:36-55` — the agent-level language list uses bare codes (`te`,
`hi`, `en`) and spells Odia **`od`**, while Sarvam's STT list spells it `od-IN` and
`providers/voice/maya.md:54` spells it `or`. Three spellings of one language across the
vendor's own pages. `apps/api/agents/voices.py` sells `te-IN`/`hi-IN`/`en-IN` only, so
nothing we ship is affected — recorded so nobody re-derives it.

### 4d. D-358's marked assumption is SETTLED, in the direction it feared — but the fix is blocked

`apps/api/engine/bolna.py` sends `"synthesizer": {"provider_config": {"voice":
cfg.models.tts_voice}}` where `tts_voice` holds a **model** string (`bulbul:v3`). D-358
marked this as very likely wrong on the strength of one prose example. The docs confirm
`model` and `voice`/`voice_id` are separate keys in `provider_config`:

- `providers/voice/elevenlabs.md:18-21` — `"provider_config": {"voice": "Nila",
  "voice_id": "V9LCAAi4tTlqe9JadbCo", "model": "eleven_turbo_v2_5"}`.
- `:51-53` Key settings — `voice` "Display name of the voice", `voice_id` "ElevenLabs
  voice ID (stable; use this, not the name)", `model` "ElevenLabs model".
- `providers/voice/maya.md:69-71` — the same three keys for a different provider.
- `agent-setup/audio-tab.md:116-124` — Provider, then Model, then Voice, as three separate
  selections; `:110` alt text shows a live agent on *"Sarvam provider, Bulbul v2 model,
  Anjura voice selected"*.

So we are naming a model where a speaker belongs, and naming no model at all.

**NOT fixed here, and the blocker is the same one D-358 named.** Moving the string to
`model` leaves `voice` unset and the engine picks a speaker, which changes what every
client's caller hears. Doing it properly needs `ModelConfig` to carry `tts_model` beside
`tts_voice` **and** a real Sarvam speaker catalogue — and no page in this lane publishes
one. `providers/voice/sarvam.md` lists models and no voices; the only speaker name
anywhere is "Anjura" in an image alt-text. The catalogue comes from `GET /me/voices` on a
live account, which is an **external blocker: a Bolna account**. What changed is that the
uncertain half is now certain, which is why §8 proposes a decision-log row.

### 4e. Cartesia — **no gap, and the two Cartesias are different products**

`providers/voice/cartesia.md:59-61` lists `sonic-3`, `sonic-3.5`, `sonic-preview`. That is
Cartesia **as a TTS provider inside Bolna**, which this product does not use — D-36 puts
speech on Sarvam, and `apps/api/agents/voices.py:72` says Cartesia is deliberately absent
from the voice catalogue.

`apps/api/engine/cartesia.py` is an adapter for **Cartesia Line**, a different product: a
voice-agent platform whose `TTSConfig(voice_id, pronunciation_dict_id, language)` has no
model field at all (`cartesia.py:265-266`). No Sonic identifier belongs in it and none is
there. **No gap.** These names would matter only if we ever offered Cartesia TTS *on
Bolna*, and `providers.md:149` confirms the credential for that would be the single key
`CARTESIA`.

---

## 5. Model generation — what it means for D-410's comparison (reported, not decided)

D-410 compared `gpt-4o-mini` against `gemini-2.5-flash` and against Sarvam, Krutrim,
DeepSeek and OpenAI-direct. Every one of those comparisons was written against a
generation the vendor now lists as previous-gen.

| Provider | Their current names | Page |
| --- | --- | --- |
| OpenAI | `gpt-5.6-sol` / `-terra` / `-luna`, `gpt-5.5`, `gpt-5.5-pro`, `gpt-5.4`, `gpt-5.4-mini` | `llm-model/openai.md:40-49` |
| Azure OpenAI | `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.4-nano` above our two | `llm-model/azure-openai.md:40-47` |
| Anthropic | `claude-fable-5`, `claude-opus-4-8`, `claude-sonnet-5`, `claude-haiku-4-5-20251001` | `llm-model/anthropic.md:36-39` |
| Google | `gemini-3.5-flash`, `gemini-3.1-pro`, `gemini-3.1-flash-lite`, `gemini-2.5-*` | `llm-model/gemini.md:36-41` |
| DeepSeek | `deepseek-v4-flash`, `deepseek-v4-pro` | `llm-model/deepseek.md:40-41` |

**What does NOT change, and it is most of D-410.** The refusals were on grounds
generations do not touch: OpenAI-direct is out because its India residency covers storage
at rest and not inference; DeepSeek is out because it is China-hosted under DPDP —
`deepseek.md` says nothing about hosting and nothing here changes that; Krutrim is GPU
IaaS; Sarvam-via-Custom-LLM is out because there is still **no Sarvam LLM provider** (the
directory has six LLM pages and none is Sarvam; `openrouter.md`'s own FAQ links "Sarvam"
to the bare directory `/docs/providers/llm-model`). `concepts/choosing-providers.md:24`
independently corroborates the core of the decision: for *"Enterprise / data residency"*
their recommended LLM is **Azure OpenAI**, and `:22` puts Sarvam on both speech legs for
Indian languages. **D-410's shape is confirmed by the vendor's own selection guide.**

**What DOES change is a cost/quality question, and it is a founder decision — see §7.**

One vendor deadline exists in this lane and it is not ours: `deepseek.md:12` deprecates
`deepseek-chat`/`deepseek-reasoner` on 24 July 2026. We ship neither. **No vendor deadline
runs against this product**, which is the state CLAUDE.md records.

---

## 6. Changes made, file by file, with red-then-green evidence

All four behavioural changes are sabotage-verified. `uv run ruff check --fix . && uv run
ruff format .` and `uv run mypy apps packages` are clean.

### 6.1 `apps/api/engine/bolna.py`

- `_AZURE_LLM_PROVIDER: Final = "azure-openai"` — new constant, one spelling, replacing the
  inline `"azure"` in `_llm_routing`. Docstring rewritten with the citation, the
  label-vs-wire-value argument, and the inverted fallback order.
- `_AZURE_PROVIDER_KEYS` — new constant holding the vendor's four key names verbatim, each
  one's source in our settings, and the marked open question on `AZURE_OPENAI_API_VERSION`.
  Read by a test, not at runtime — the same shape `_VENDOR_STATUSES` has in the same file.
- `set_llm_credential` docstring — says why it installs one of four rather than three of
  four, and cites the mirrored provider API pages.
- `_agent_models` and `_llm_routing` body comments corrected for the new provider string
  and for the `AZURE_OPENAI_API_BASE` question.

**RED** (sabotage: `_AZURE_LLM_PROVIDER = "azure"`):

```
>       assert llm["provider"] == "azure-openai"
E       AssertionError: assert 'azure' == 'azure-openai'
FAILED tests/in_call_llm_provider_test.py::test_an_azure_leg_renders_the_spelling_the_vendor_documents
FAILED tests/in_call_llm_provider_test.py::test_the_agent_body_carries_the_endpoint_into_the_llm_block
2 failed, 30 passed
```

**GREEN** (restored, byte-identical to backup): `32 passed, 1 warning in 0.27s`

**RED** (sabotage: `_AZURE_PROVIDER_KEYS` reverted to a bare `"AZURE"` entry):

```
E       AssertionError: if the vendor ever does document a bare `AZURE` entry, this test
        and the default below both need re-deciding rather than one of them quietly moving
FAILED tests/bolna_contract_test.py::test_the_credential_name_we_push_is_one_the_vendor_documents
1 failed, 21 passed
```

**GREEN** (restored): `22 passed, 1 warning in 0.27s`

**RED** (sabotage: `provider_name` identity loosened from `==` to a prefix match, the
mistake the four-key store now invites):

```
E       apps.api.core.errors.ProblemError: engine_credential_not_replaced: The credential
        store appended the new value beside the old one instead of replacing it...
FAILED tests/bolna_contract_test.py::test_the_other_three_azure_entries_are_not_mistaken_for_ours
1 failed, 20 passed
```

**GREEN** (restored): `21 passed, 1 warning in 0.28s`

### 6.2 `packages/shared/src/calevate_shared/config.py`

- `bolna_llm_credential_name` default `AZURE` → **`AZURE_OPENAI_API_KEY`**, with the
  vendor table quoted and the derivation's failure explained.
- `azure_openai_deployment` — records the deployment-name resolution rule (`:69`) and why
  it is free today and a trap on a GPT-5 model.

**RED** (sabotage: default reverted to `AZURE`):

```
FAILED tests/bolna_contract_test.py::test_installing_the_llm_credential_posts_the_documented_body
FAILED tests/bolna_contract_test.py::test_a_store_that_appends_is_reported_rather_than_tolerated
2 failed, 19 passed
```

**GREEN** (restored, byte-identical): `21 passed, 1 warning in 0.28s`

### 6.3 `packages/shared/src/calevate_shared/engine.py` *(exclusively owned this wave)*

- `SARVAM_TRANSLATING_STT: Final = frozenset({"saaras:v2.5"})` — new. A **deny**-list of
  the one behaviour we cannot tolerate rather than an allow-list of good names, so the
  vendor's next release is not our outage.
- `AzureOpenAIModel` — LEAD-A's answer recorded at the Literal, plus the three-item
  checklist a new member costs (price table, `temperature: 1`, deployment naming).
- `LlmProvider` comment corrected: the `custom` route's credential path is refused on the
  docs' own silence rather than on a browser sweep.

### 6.4 `scripts/pilot/gates_api.py`

- `stt_model="saaras:v2.5"` → **`"saaras:v3"`**, with the vendor's two sentences quoted and
  the reason `saaras:v4` was not taken.

**RED** (sabotage: reverted to `saaras:v2.5`):

```
E       AssertionError: these modules configure a Sarvam transcriber that returns an ENGLISH
        TRANSLATION rather than the caller's own words, on a Telugu-first product:
        scripts/pilot/gates_api.py → ['saaras:v2.5']...
FAILED tests/sarvam_model_identifier_test.py::test_no_shipped_module_configures_a_translating_sarvam_transcriber
1 failed, 5 passed
```

**GREEN** (restored, byte-identical): `6 passed, 1 warning in 3.59s`

### 6.5 Tests

- `tests/in_call_llm_provider_test.py` — provider assertions and read-back fixtures moved
  to `azure-openai`; the pinning test's docstring rewritten with the citation and with why
  a label lost to a documented value.
- `tests/bolna_contract_test.py` — two **new** tests:
  `test_the_credential_name_we_push_is_one_the_vendor_documents` (couples the default to
  `_AZURE_PROVIDER_KEYS`, which is what makes that constant load-bearing) and
  `test_the_other_three_azure_entries_are_not_mistaken_for_ours` (the near-miss the
  four-key store creates).
- `tests/sarvam_model_identifier_test.py` — one **new** scan,
  `test_no_shipped_module_configures_a_translating_sarvam_transcriber`.
- `tests/platform_config_test.py` — docstring only.

### 6.6 Comments corrected elsewhere

`apps/api/agents/service.py` (the publish-time key check now says the gap got *wider*, not
narrower — the platform can push one of four entries), `apps/api/core/platform_config.py`
(example value), `scripts/probe_bolna_providers.py` (the gate-16f instrument now tells the
operator the other three entries exist, points at the single authoritative list rather than
copying it, and asks them to **record what the console accepts for the api-version** —
that is the observation that settles v1-versus-classic).

### Test runs

```
tests/in_call_llm_provider_test.py tests/sarvam_model_identifier_test.py
tests/bolna_contract_test.py packages/shared/tests/engine_conformance
tests/bolna_snapshot_test.py                        →  301 passed
tests/pilot_gates_test.py                           →   41 passed
```

Per the brief, the full suite and `make coverage-ratchet` were **not** run (10 agents, 4
vCPU). Two environment failures were observed and are **not** from this change:
`tests/platform_config_test.py`'s store tests fail on a missing `platform_settings` table
and four `tests/engine_audit_test.py` cases fail on `ConnectionRefusedError` to Redis at
`127.0.0.1:6380`. One real cross-agent breakage exists and is **another lane's**:
`test_every_payload_key_an_adapter_reads_is_classified` fails because
`transfer_call_data`, `cost`, `objective` and `subjective` were added to `bolna.py` this
wave and are not yet in `_VENDOR_ONLY_KEYS`/`_SHARED_PAYLOAD_KEYS`. Flagged, not touched.

---

## 7. Founder decisions surfaced, with what is known and what is not

**(a) Move to a current-generation model? — a cost/quality question, NOT a blocker.**
LEAD-A's forced fork does not exist; both our identifiers work. What the pages show is
that we are two generations behind the vendor's recommendation: `gpt-5.4-mini` is marked
**"Recommended — best latency/cost balance"** for Azure (`azure-openai.md:42`) and
`gpt-5.4-mini` is the standing recommendation across `openai.md` and
`concepts/choosing-providers.md`.

What is known, in our own numbers (`AZURE_LIST_PRICE_USD_PER_MTOK`, D-410, Global Standard
list, verified 19 Aug 2026):

| Model | $/Mtok in | $/Mtok out | ₹/min at 1 / 5 / 10 min |
| --- | --- | --- | --- |
| `gpt-4o-mini` (shipped default) | 0.15 | 0.60 | ₹0.10 / ₹0.16 / ₹0.24 |
| `gpt-4.1-mini` (live switch) | 0.40 | 1.60 | ₹0.27 / ₹0.44 / ₹0.65 |
| `gpt-5.4-mini` | **not in our tree** | **not in our tree** | **not derivable here** |

**What is NOT known and is not guessed:** `gpt-5.4-mini`'s Azure list price, and whether it
is available in `southindia` at all — `azure-openai.md:50` warns *"Azure model
availability varies by region. Not all models are available in all Azure regions
immediately at launch."*, which is the exact constraint that made `gpt-4o-mini` the default
in the first place. Microsoft's pricing and model-availability pages are refused by this
environment's egress proxy, so neither number can be fetched from here.

Also material to the decision: GPT-5 models draw reasoning tokens from the same budget as
`max_tokens` (`openai.md`, "Keep max_tokens short"), so our `max_tokens: 400` and
`temperature: 0.1` would both need re-deciding — see §1b. **Blocked outside this repo on:
an Azure subscription (to read South India availability and quota) and Microsoft's
published price for `gpt-5.4-mini` in that region.**

**(b) Adopt `saaras:v4` for STT? — a Telugu quality question.** The vendor calls it the
latest model, transcribing in the original language with automatic language detection
(`transcriber/sarvam.md:64`, `:87`). Auto-detection is attractive for code-mixed Telugu.
Not taken: quality on Telugu code-mixed speech is unmeasured for v3 and for v4 alike, the
instrument is the golden-transcript fixtures plus `scripts/eval.py`, and a pilot is for
measuring the stack we ship. **Blocked outside this repo on: a Sarvam account and pilot
gate 3's ear test.** No cost consequence — TRD §10.1 prices Saaras per minute, not per
model version.

**(c) Nothing else in this lane needs a decision.** LEAD-A produced no fork; the credential
work produced a fix and a sharper gate.

---

## 8. Proposed text for the central files (I did not edit ROADMAP.md or OPERATIONS.md)

### 8a. `docs/OPERATIONS.md` §2 — REPLACEMENT for gate 16f

*Applied 20 Aug 2026. §8b's deployment-naming line went into gates 20 AND 20c; §8c landed as
**D-417**.*

> | 16f H | **Does Bolna's `azure-openai` provider, configured with the four documented credential entries, actually run a call against OUR Azure resource? — the FIELD NAMES are settled; three questions are not** [D-410, narrowed by the docs mirror] | **The naming half is CLOSED and the old default was WRONG.** VERIFIED-VENDOR-DOCS, `bolna-findings/mirror/pages/providers.md:96-102`: their Azure OpenAI provider requires FOUR entries — `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_MODEL`, `AZURE_OPENAI_API_BASE`, `AZURE_OPENAI_API_VERSION` — under *"All these keys **must** be added for the respective provider."* `Settings.bolna_llm_credential_name` defaulted to `AZURE`, which appears nowhere in that table; it now defaults to `AZURE_OPENAI_API_KEY` and the full list with its evidence is `apps/api/engine/bolna.py::_AZURE_PROVIDER_KEYS`. The wire provider string moved with it: `azure-openai`, not `azure` (`providers/llm-model/azure-openai.md:20`, `:59`). **WHAT IS STILL OPEN, and each has its own observation.** **(i) `AZURE_OPENAI_API_VERSION` has no derivable value and the vendor contradicts itself about whether it is needed** — `providers.md:40` calls all four mandatory; `azure-openai.md:32` says the connection needs *"your Azure endpoint URL, API key, and deployment name"*. D-410 chose the v1 surface (`…/openai/v1`) precisely because it has no `api-version`. **Record what the console accepts.** If it demands a real dated version, their Azure client is the CLASSIC surface and D-410's endpoint choice needs re-deciding. **(ii) Is the per-agent `base_url` read at all?** Their documented Azure `llm_config` has no `base_url` row and the endpoint is a provider-level credential, so our `base_url` may be inert — which puts one link of the residency chain in THEIR store where no read-back of ours can see it. **(iii) Does `provider: "azure-openai"` route as documented on the live account?** **THE TEST:** with `BOLNA_API_KEY` set, `uv run python -m scripts.probe_bolna_providers` (writes the key entry only); install the other three by hand in the console; `GET /providers` and confirm all four persist; publish one agent and read it back (gate 16); place ONE call. **PASS** = the agent answers in language AND the Azure resource's own metrics show the request — metrics, not just a working call, because only they prove WHICH resource served it. **On a fail, do not change code first:** `bolna_llm_credential_name` is `applies: live`. Fallback provider strings are `azure` then `custom`, in that order, one string each. **Wrong answers**: inventing an api-version, and putting the key anywhere it can be logged. Blocked outside this repo on: a Bolna account AND an Azure subscription with a deployed model. |

### 8b. `docs/OPERATIONS.md` §2 — one line to ADD to gates 20/20c (deployment naming)

> **Name the deployment after the model it serves** (`prod-gpt-4o-mini`, not
> `prod-voice-01`). VERIFIED-VENDOR-DOCS, `providers/llm-model/azure-openai.md:69`: Bolna
> resolves the deployment name back to a model to choose its handling, and *"a name it
> cannot resolve is treated as a non-GPT-5 model and gets the wrong defaults"*. Free today
> — that is the correct handling for both models in `AzureOpenAIModel` — and a silent
> misconfiguration the day a GPT-5 model is adopted.

### 8c. `docs/ROADMAP.md` §6 — proposed decision-log row

> | D-417 | **THE BOLNA DOCS MIRROR SETTLES D-410's LAST MARKED ASSUMPTION AND CORRECTS TWO WIRE VALUES. LEAD-A IS ANSWERED NO: our Azure model identifiers were never at risk.** | **LEAD-A: NO DEFECT.** Their Azure "Supported models" table (`bolna-findings/mirror/pages/providers/llm-model/azure-openai.md:44-47`) lists `gpt-4.1`, `gpt-4.1-mini`, `gpt-4o` AND `gpt-4o-mini`, each *"Previous gen; still available / Stable if already deployed"*. The index sentence that raised the alarm named the four they RECOMMEND. The field is not an enum in any case: `:69` and `:97-98` state that `model` carries a freely-chosen DEPLOYMENT name — confirming, from the vendor's side, the distinction `engine.py` has argued since D-410. **No fork, no price change, no ₹/min figure moves.** **GATE 16f, FIELD NAMES: CLOSED, AND THE GUESS WAS WRONG.** `providers.md:96-102` names FOUR required entries for Azure OpenAI and none is `AZURE`, which `Settings.bolna_llm_credential_name` defaulted to; the derivation ("their matrix names entries after the provider in upper case") is real for one-key providers and does not survive one needing a key, an endpoint, a model and a version. Default → `AZURE_OPENAI_API_KEY`; the full list, each key's source in our settings, and the one with no derivable value are `apps/api/engine/bolna.py::_AZURE_PROVIDER_KEYS`, read by a test so it cannot drift. `POST /providers` is a flat `{provider_name, provider_value}` (`api-reference/providers/add.md:55-68`), so four keys means four installs; `set_llm_credential` still writes ONE — the key — because it is the only one whose value is a secret we hold, and installing three of four while reporting success is the failure its count-before/count-after design exists to avoid. **THE WIRE PROVIDER STRING WAS WRONG: `azure` → `azure-openai`** (`azure-openai.md:20`, `:59`, stated as a copy-pasteable body and again in a Key settings table). D-410 chose `azure` from a provider matrix reading `Azure OpenAI` and a dashboard dropdown offering `azure` — **both human-readable LABELS, which is the wrong class of evidence for a wire value**; `agent-setup/llm-tab.md` confirms the dashboard label is "Azure". Corroborated by form across every sibling page (`openai`, `anthropic`, `google`, `deepseek`, `openrouter`, `custom`). `azure` survives as the one-string fallback. **`custom` IS NOW MORE CLEARLY REFUSED, NOT LESS**: the entire documented custom-LLM flow takes a URL and a name and has **no credential field anywhere** (`customizations/using-custom-llm.md:32-33`, `api-reference/user/add_model.md:39-45`, `providers.md:111-112` — the only provider accordion in the file with no key table), so there is no documented way for it to carry the Bearer token our v1 endpoint requires. Gate 16c's verdict is upgraded from a browser sweep to a document. **A SILENT SARVAM DEFECT, FIXED**: `scripts/pilot/gates_api.py` configured `saaras:v2.5`, which **translates to English** (`providers/transcriber/sarvam.md:62`, `:85`) rather than transcribing, on a Telugu-first product's one real telephone call — while `scorecard.py` priced "Saaras V3" and the conformance suite configured `saaras:v3`. It fails NOTHING: the request succeeds and the transcript is well-formed, and the damage lands on `workers/redaction.py`'s transliterated Telugu digits and `compliance/optout.py`'s romanised opt-out phrases, neither of which survives a translation. **An unrecognised opt-out is a compliance failure, not a quality one.** Fixed to `saaras:v3` and guarded by `SARVAM_TRANSLATING_STT` — a DENY-list of the one behaviour we cannot tolerate rather than an allow-list of good names, so the vendor's next release is not our outage. **CONFIRMED WITH NO CHANGE**: `bulbul:v3`/`bulbul:v2` are both on their supported list (`providers/voice/sarvam.md:42-44`, and `bulbul:v4` is NOT on this engine); Telugu is `te-IN` on Sarvam STT; `concepts/choosing-providers.md:22-24` independently recommends Sarvam for Indian-language speech and **Azure OpenAI for data residency**, which is D-410's own argument from the vendor's side; and `apps/api/engine/cartesia.py` needs no Sonic identifier because Cartesia Line and Cartesia-TTS-on-Bolna are different products. | **WHAT IS STILL OPEN, AND IT IS SHARPER RATHER THAN SMALLER.** `AZURE_OPENAI_API_VERSION` is documented as REQUIRED and **contradicts the v1 surface D-410 chose**, which has no `api-version` at all — and the vendor's own two pages disagree: `providers.md:40` calls all four mandatory while `azure-openai.md:32` describes the same connection as *"your Azure endpoint URL, API key, and deployment name"*. Three readings survive (vestigial; their client is the CLASSIC surface and our endpoint choice is wrong; required-but-unvalidated) and **nothing here picks one** — a guessed date would be exactly the defect gate 16f exists to prevent. **A RESIDENCY NUANCE, STATED AT THE STRENGTH THE PAGE SUPPORTS AND NO FURTHER.** `AZURE_OPENAI_API_BASE` is a PROVIDER-level credential and their documented per-agent Azure config has **no `base_url` row** (`azure-openai.md:59-65`), so the endpoint may come from THEIR store and the `base_url` we send may be inert. This does not weaken any claim about `AZURE_LOCATION`, the resource, or Regional-not-Global — those were already human-attested (gates 20/20c). It means one link of the chain sits where **no read-back of ours can see it**: `_agent_models` reads the endpoint off the agent, and an ignored `base_url` reads back identically to an honoured one. `base_url` is still SENT (their `SimpleLlmAgent` has the field, VERIFIED-OAS) and gate 16f now asks for the Azure resource's own metrics as the confirmation. **A NEW TRAP RECORDED IN ADVANCE**: Bolna resolves the deployment NAME back to a model to select GPT-5 handling and `reasoning_effort` defaults, and *"a name it cannot resolve is treated as a non-GPT-5 model"* (`:69`). Harmless for `AzureOpenAIModel`'s two GPT-4-class members — that IS the right handling — and silent misconfiguration the day a GPT-5 model is added. Adding one also costs an `AZURE_LIST_PRICE_USD_PER_MTOK` entry and a `temperature` change, because GPT-5 models reject anything but `1` with a 400 at agent creation (`:29`) and `_agent_body` sends `0.1`. That checklist now sits at the Literal. **WHAT THE MODEL GENERATION MEANS FOR D-410, REPORTED AND NOT DECIDED.** Their lineups moved to GPT-5.6/5.5/5.4, Claude Sonnet 5, Gemini 3.x and DeepSeek V4, and `gpt-5.4-mini` is their standing recommendation. **None of D-410's REFUSALS moves**, because none rested on a generation: OpenAI-direct is still out on inference residency, DeepSeek still China-hosted, Krutrim still IaaS, and there is still **no Sarvam LLM provider** on this engine. What moves is a cost/quality question the founder owns and this repository cannot price: `gpt-5.4-mini` is not in `AZURE_LIST_PRICE_USD_PER_MTOK` and its South India availability is unconfirmed — `azure-openai.md:50` warns availability varies by region, which is the exact constraint that made `gpt-4o-mini` the default. Blocked outside this repo on an Azure subscription and Microsoft's regional price. **D-358 IS SETTLED IN THE DIRECTION IT FEARED AND STILL CANNOT BE FIXED HERE.** `provider_config` really does keep `model` and `voice`/`voice_id` in separate keys (`providers/voice/elevenlabs.md:18-21`, `:51-53`; `maya.md:69-71`; `agent-setup/audio-tab.md:116-124`), so we name a model where a speaker belongs and name no model at all. The fix needs `ModelConfig` to grow `tts_model` **and** a real Sarvam speaker catalogue, and **no page publishes one** — `providers/voice/sarvam.md` lists models and no voices; the only speaker name anywhere in this lane is "Anjura" in an image alt-text. It comes from `GET /me/voices` on a live account: an external blocker (a Bolna account), which is what gate 3 already owns. |
