> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Bring your own keys

> Run your agents on your own speech-to-text, LLM and voice accounts, on your own voice and language model, on your own voice alone, or on your own language model alone. Each agent can follow the workspace or choose its own.

With **bring your own keys** (BYOK), your workspace uses your own accounts with the providers. The
three jobs are speech-to-text, the LLM and the voice. You pay those providers directly. Depending
on what you bring, we charge a flat platform fee or our usual per-minute voice plan.

You choose what you bring:

* **All three of my keys** (scope `all`). Speech-to-text, the LLM and the voice are all yours.
* **Only my voice** (scope `voice`). Your voice account speaks. Our speech-to-text hears the
  caller, our model answers, and the phone line is ours.
* **My voice and my language model** (scope `llm_voice`). Your voice account speaks and your LLM
  account answers, on any model your key offers. We keep the speech recogniser (our speech-to-text
  hears the caller), and the phone line is ours.
* **Only my language model** (scope `llm`). Your LLM account answers, on any model your key
  offers. We keep the speech recogniser and the voice, and the phone line is ours. You pay the same
  per-minute voice plan as any other call: Standard, Premium or Studio, by the voice the agent
  speaks with.

| | All three of my keys | My voice and my language model | Only my voice | Only my language model |
| - | - | - | - | - |
| Call minute | **₹1.00** (\$0.012) a minute, all-in | **₹1.00** (\$0.012) a minute, our speech-to-text and phone line included | **₹1.50** (\$0.02) a minute, our phone line included | Our usual voice plan: Standard, Premium or Studio, with your plan's discount |
| Chat reply | **₹0.02** per reply | **₹0.02** per reply | Our usual price, because the model is ours | **₹0.02** per reply, as with all three |

Calls are billed in 30-second pulses, at the rate set when the call starts. With only your
language model, the model you run never changes the price of the minute: the price follows the
voice alone, however costly your model is on your own account.

With all three, BYOK turns on only when a speech-to-text key, an LLM key and a voice key are all
added and checked. With your voice and your language model, it needs a checked LLM key and a
checked voice key. With only your voice, it needs only a checked voice key. With only your
language model, it needs only a checked LLM key, with a model chosen. Any plan can turn it on.

With all three keys, your voice and language model, or only your language model, each agent can also run its own **model** from your LLM key. On the agent's **Playground**, the
Model list shows every model your key reaches. Leave it on your key's model, which is the one set
in **Settings → Your keys**, or pick another for this agent alone.

Each agent speaks with a voice you choose from your own voice provider. Open the agent's
**Voice** page: it lists every voice your key can use, and **Play** speaks a short line in the
agent's language. The preview runs on your account, so the provider charges you for those few
characters. If a provider hosts its own sample of a voice, that sample plays instead, at no
cost. An agent without a chosen voice speaks with a standard voice from your provider.

On a call with all three, your speech-to-text hears the caller, your LLM answers, and your voice
speaks. With your voice and your language model, our speech-to-text hears the caller, and your LLM
answers and your voice speaks. With only your voice, only the speaking is yours. With only your language model, only the
answering is yours: our speech-to-text hears the caller and our voice speaks. If one of your keys cannot be used when a call starts, the call is not
answered on our providers instead.

### Which models answer calls with only your voice

With only your voice, the call minute includes our model, so a call runs only on a low-cost
model. Today those are:

* Prana
* Prana \[Voice]
* GPT-OSS 120B
* GPT-5 Nano
* GPT-4.1 Nano

The rule is Prana, Prana \[Voice] and GPT-OSS 120B by name, plus any voice model (other than our call-only
Composer, which runs a second model each turn) whose price per token is at or below our reference low-cost voice model on both input and output, so a new
model that is cheap enough joins the list on its own. `GET /api/v1/models` marks each model with
`voiceOnlyByok`.

An agent already set to another model keeps it for chat, which is billed as usual, and runs on
GPT-OSS 120B on calls. The agent's model picker lists only the allowed models while you use only your
voice. Setting another model through `POST` or `PATCH /api/v1/agents` returns a 400 that says
why. With all three of your keys, with your voice and language model, with only your language model, or without BYOK, nothing changes:
with only your language model the model is your key's, so any model your key offers can answer calls. The limit applies only to agents
that use your keys: an agent you have switched off your keys (below) answers on our stack, so it may
use any model.

### Each agent chooses how it uses your keys

BYOK is switched on for the workspace, and the scope you choose in **Settings → Your keys** is the
**default**: every agent follows it until it is told otherwise. A workspace holds its keys once, and
each agent can choose for itself. An agent's `byok` is one of:

* `null` (or `"workspace"`): follow the workspace's default scope. This is how every agent starts.
* `"off"`: never use your keys (below).
* `"all"`, `"voice"`, `"llm"` or `"llm_voice"`: run this agent on that scope's keys, whatever the
  workspace default is. For example, with an LLM key and a voice key saved, one agent can run on
  `"llm"` (your model, our voice) while another runs on `"llm_voice"` (your model and your voice).

Choosing a scope is refused with `409` unless the workspace holds checked keys, each with a model, for
everything the scope needs. The message names the missing key, for example "no verified voice key
(tts)". Switching BYOK off in the workspace is the master switch: with it off, no agent uses a key,
whatever it chose. The workspace default decides which keys turning BYOK on needs; an agent's own
scope needs its keys too, so a key an agent's scope needs cannot be removed while BYOK is on (set the
agent to follow the workspace first, or replace the key).

A call or reply is priced and run under the scope that applies to the agent when it starts, so two
agents in one workspace can bill differently: the price follows the agent's scope. If an agent's
scope can no longer be served when a call starts (a key was removed while BYOK was off), the agent
falls back to the workspace's scope and the call goes ahead; it is never refused for that, and never
billed at a rate that does not match how it ran.

A call can be handed to another agent only when that agent would run on the same stack the call
started on. A hand-off to an agent on a different scope, or switched off your keys, is refused.

#### An agent on ours

Give an agent `byok: "off"` and it never uses your keys, whatever the workspace does:

* calls run on our voices, our speech-to-text and our model, and the minute is billed at our normal
  rate for that voice, not the BYOK rate;
* chat replies are billed as normal replies, not the flat BYOK reply charge. With only your language
  model, the minute is already our normal rate, so what changes for an agent set to `"off"` is the
  model (ours, not yours) and the chat reply price;
* the voice-only model limit does not apply to it;
* the model and voice choices you saved for your own keys are kept and ignored until you switch the
  agent back to `"workspace"`.

The other agents in the workspace keep their own choice and price. A customer of yours
follows the same rule on its own agents. The setting is read once when a call or a reply starts, so a
call is never priced at one rate and run on another stack. A call already ringing keeps the stack it
was started on: if you switch its agent off your keys in those few seconds, the call is refused
rather than moved onto ours.

An agent set to `"off"` is billed at our rate for the voice it uses. A new agent starts on a Premium
voice, which bills at the Premium rate, so choose a standard voice for an agent whose minutes should
be cheaper.

## In the console

Open **Settings → Your keys** and choose the default: **All three of my keys**, **My voice and my
language model** (we keep the speech recogniser, ₹1/min), **Only my voice** or **Only my language
model**. All three key cards are always shown, so you can save a key for an agent that chooses a
different scope. Keys for jobs your default does not cover are not used by agents that follow it. On
an agent's **Playground** or **Voice** page, **How Agent uses your keys** chooses between following
the workspace, **Off**, and each set your saved keys allow. Each card has:

* **Provider.** Choose who does that job.
* **Model.** Every model the provider offers. Before you add a key, the list shows the models the
  provider offers. Once your key is checked, it shows the models **your** key reaches. Long lists
  are grouped by family, such as Flux, Aura-2 and Aura for Deepgram's voices.
* **API key**, plus any other field the provider needs. Azure, for example, needs a region.

**Verify and save** checks the key with the provider before storing it. A key the provider rejects
is not saved. Keys are stored encrypted, and are only ever shown by their last four characters.

Once the cards you need are filled, switch on **Use my own keys**.

## Providers

| Job | Providers |
| - | - |
| Speech-to-text | Deepgram, AssemblyAI, Soniox, Speechmatics, Gladia, Sarvam, ElevenLabs, Cartesia, OpenAI, Groq, Mistral, Azure Speech |
| LLM | OpenAI, Anthropic Claude, Google Gemini, Groq, Mistral, Sarvam, DeepSeek, xAI Grok, Together AI, Fireworks AI, Cerebras, OpenRouter, or any OpenAI-compatible URL |
| Voice | Deepgram, ElevenLabs, Cartesia, OpenAI, Sarvam, Soniox, Mistral, Azure Speech, Rime, Inworld, Hume, Murf, Speechify |

**Azure Speech** takes your key and region. If your Azure resource accepts its key only at its own
address, as Azure AI Foundry resources do, also give its **resource endpoint**, such as
`https://my-resource.cognitiveservices.azure.com`.

**Any OpenAI-compatible URL** takes a base URL that starts with `https://`. Azure OpenAI's
`https://<resource>.openai.azure.com/openai/v1` is one. If the server does not list its models, send
the model id with the key, and we check the two together with a one-token request.

On calls, a Google Gemini 2.5 or 3 model is asked to think less before it speaks, so the
caller is not left waiting (a Pro model cannot switch thinking off, so it is asked for the least
it allows). Chat replies are not changed.

## When a key fails

There is no fallback to our providers for a job that is yours. If your provider refuses a request
(a revoked key, no credit, rate limits), the reply fails, or the voice does not speak. We do not answer on our own models and bill you for it. You get a notification naming
the provider and the reason, at most once a day per provider. With only your voice, speech-to-text
and the LLM are ours, so our usual backups for them stay on. With only your language model, the
speech-to-text and the voice are ours and keep our usual backups, but the model never has one: if your
key fails, the caller hears our apology and the call is flagged, and we do not answer on our model.

## Customers

If you build on our API with [customers](/api-reference/customers), your customers use **your** keys
while BYOK is on, with your choice of all three, your voice and language model, only the voice or only the language model. A customer can bring a complete
set of its own for that choice (three keys, an LLM and voice key, a voice key or an LLM key), which then overrides yours. Turning BYOK off in your workspace turns it off for every customer that inherits your keys. A customer with its own complete set and its own switch on keeps using its own.

## API

Every request below also works for a customer, with the `Thinnest-Workspace` header.

### Status

```http theme={null}
GET /api/v1/byok
```

```json theme={null}
{
  "enabled": true,
  "scope": "all",
  "usingScope": "all",
  "using": "own",
  "complete": true,
  "credentials": [
    {
      "kind": "stt",
      "provider": "deepgram",
      "label": "Deepgram",
      "key": "…k9z2",
      "fields": { "model": "nova-3-general" },
      "model": "nova-3-general",
      "models": ["flux-general-en", "nova-3-general", "…"],
      "verifiedAt": "2026-10-06T10:00:00Z",
      "updatedAt": "2026-10-06T10:00:00Z"
    }
  ]
}
```

`scope` is what this workspace brings by default: `all`, `voice`, `llm` or `llm_voice`; each agent may choose its own (below). `usingScope` is the scope that applies
right now (a customer runs on its developer's), or `null`. `complete` says whether the keys for
`scope` are ready. `using` is `own`, `developer` (a customer using its developer's keys) or `none`. `models` is what the
provider offered this key, and `model` is the one it runs.

### Add or replace a key

```http theme={null}
PUT /api/v1/byok/credentials
```

```json theme={null}
{ "kind": "llm", "provider": "openai", "credentials": { "apiKey": "sk-…", "model": "gpt-5.4-mini" } }
```

* **`kind`.** One of `stt`, `llm` or `tts`.
* **`provider`.** One of the provider ids in the table above, in lower case. An error lists the ones
  that do that job.
* **`credentials.model`.** Optional. Without it, a speech key starts on the provider's usual model.
  An LLM key starts on the provider's usual model when it has one; otherwise choose one.
* **Replacing a key.** If you replace a key with one for the same provider, its model is kept.

| Status | Why |
| - | - |
| `400` | The provider rejected the key, or does not offer that model on it. |
| `409` | BYOK is on, and this key would leave a job without a model. |
| `502` | The provider could not be reached to check the key. Try again. |

### Change the model, or refresh the list

```http theme={null}
PATCH /api/v1/byok/credentials/llm
```

```json theme={null}
{ "model": "gpt-5.4-nano" }
```

The key is not sent again. The model must be on the key's `models` list. For a model the provider
launched after you added the key, send `"refreshModels": true`, alone or together with the new
`model`.

### Turn BYOK on or off

```http theme={null}
PATCH /api/v1/byok
```

```json theme={null}
{ "enabled": true, "scope": "voice" }
```

Send `enabled`, `scope`, or both. `scope` is `all`, `voice`, `llm` or `llm_voice`. The request is refused with
`409` until the keys for the scope are added, checked, and each has a model: all three for `all`,
the voice key for `voice`, the LLM key for `llm`, the LLM key and the voice key for `llm_voice`. While BYOK is on, moving to a scope needs that
scope's keys first, for example the other two keys to move from `voice` to `all`.

### Voices

```http theme={null}
GET /api/v1/byok/voices
```

```json theme={null}
{
  "provider": { "id": "elevenlabs", "label": "ElevenLabs" },
  "model": "eleven_flash_v2_5",
  "items": [
    { "id": "EXAVITQu4vr4xnSDxMaL", "name": "Sarah", "language": "en", "gender": "female", "sample": "https://…" }
  ]
}
```

These are the voices your voice provider offers your key. `sample` is a clip the provider hosts,
when it has one. On Deepgram, a voice is a model, such as `aura-2-helena-en` or `flux-alexis-en`.
On Cartesia the list starts with your own cloned voices.

### Preview a voice

```http theme={null}
POST /api/v1/byok/voices/preview
```

```json theme={null}
{ "voice": "EXAVITQu4vr4xnSDxMaL", "agentId": "agt_…" }
```

The response is the audio itself: `audio/mpeg`, or `audio/wav` for Sarvam. Without `text`, the
voice speaks a short line of ours in the agent's language, or in `language` if you send it. Any
`text` you send is capped at 200 characters, because your provider charges you for every
character. Soniox has no preview here: it speaks only on a live call.

### Choose an agent's model

`GET /api/v1/models` lists our models in `items`, as before. On a workspace using its own keys
it also returns `byok`:

```json theme={null}
{ "byok": { "provider": { "id": "openai", "label": "OpenAI" }, "workspaceModel": "gpt-5.4-nano", "models": ["gpt-5.4-mini", "gpt-5.4-nano", "…"] } }
```

```http theme={null}
PUT /api/v1/agents/{id}/byok-model
```

```json theme={null}
{ "model": "gpt-5.4-mini" }
```

The model must be one your key reaches. Send `null` to go back to your key's model. `GET` on the
same path returns the agent's choice. It also returns `stale`, the agent's earlier choice, if your
key no longer reaches it; until you choose again, the agent runs your key's model.

### Choose an agent's voice

```http theme={null}
PUT /api/v1/agents/{id}/byok-voice
```

```json theme={null}
{ "voice": "EXAVITQu4vr4xnSDxMaL" }
```

The voice must be one that `GET /byok/voices` lists. Send `null` to go back to the provider's
standard voice. `GET` on the same path returns the agent's current choice.

Your own cloned voices are listed and can be used. On Cartesia, `GET /byok/voices` lists your
account's own voices first, then the whole library (up to 2,000 voices), so a clone is always on the
list however large the library is. If Cartesia is slow to answer, the list can come back short:
the response then says `"complete": false`, is not cached, and you should ask again. A voice you cloned a moment ago is accepted here by its id even before it shows up in the
list.

To use a different voice for a single call, put it in that call's `overrides`, as
`"overrides": { "voice": "EXAVITQu4vr4xnSDxMaL" }` on `POST /api/v1/calls` or in a batch.
On a workspace using its own keys, the voice must be one of yours from `GET /byok/voices`. A per-call voice is
checked like an agent's voice: if it is not on the list we ask the provider about that one voice
directly, so a clone made a moment ago is accepted. If the provider cannot be reached to check, the
request fails with `502` and can be retried; only a provider that says it has no such voice gives a refusal.

A choice belongs to the provider it was made on. If you switch your voice key to another provider,
the agent speaks with the new provider's standard voice until you choose again. `GET` shows the old
choice as `stale` until then.

### Tune a Cartesia voice

If your voice key is Cartesia, each agent can also set how its voice sounds. A client who finds
calls quiet or a little fast can fix it for that agent alone, without touching the others.

In the console, open the agent's **Voice** page and choose a voice. A **How it sounds** panel
appears under the list, with a **Hear it** button that speaks a short line with the settings as
they are now (on your account, so Cartesia charges you for those few characters) and a **Save
settings** button. Through the API, send the same fields to the voice call above:

```http theme={null}
PUT /api/v1/agents/{id}/byok-voice
```

```json theme={null}
{ "speed": 0.95, "volume": 1.4, "emotion": "calm", "model": "sonic-3.5", "pronunciationDictId": "pdict_123" }
```

| Field | Values | Default |
| - | - | - |
| `speed` | 0.6 to 1.5 | 1, Cartesia's own |
| `volume` | 0.5 to 2.0. Raise it if calls sound quiet. | 1 |
| `emotion` | One of Cartesia's emotions, such as `neutral`, `calm`, `content`, `sad`, `angry`, `scared`, `happy`, `excited`. | the words decide |
| `model` | `sonic-3.6`, `sonic-3.6-2026-08-27`, `sonic-3.5`, `sonic-3` or `sonic-2`, for this agent alone. `sonic-3.6` is Cartesia's own name for its newest 3.6 version; the dated one is a fixed release. | your key's model |
| `pronunciationDictId` | The id Cartesia gave a pronunciation dictionary in your account | none |

Every field is optional, and a request changes only the fields it names. A field you leave out stays
as it is, `null` puts one back to its default, and a value sets it. So `{ "voice": "…" }` alone
changes the voice and keeps the settings. `{ "voice": null }` goes back to the standard voice and
clears them, because the settings belong to a voice of your own: sending one before a voice is
chosen, or together with `"voice": null`, is refused. A setting that is not allowed answers `400`
with `code: validation_failed` and `field` naming it. `GET` on the same path returns the settings,
each `null` while unset. It returns the agent's own model as `agentModel`, because `model` there is
always your key's.

A few things to know:

* `emotion` works in English only. In other languages Cartesia ignores it.
* `speed`, `volume` and `emotion` need a Sonic 3 model. With `sonic-2` they are refused, and if your
  key's model is later changed to `sonic-2` they are simply not sent.
* `speed` does not apply to a Professional Voice Clone, which keeps the pace of its recording. Use
  `volume`, or an Instant Voice Clone, to adjust it.
* Cartesia treats these as guidance, not exact changes. Listen with **Hear it** or the preview below
  before you rely on a value.
* A call that names its own voice in `overrides` keeps the agent's settings.
* Only an agent speaking with your Cartesia voice has them. Other providers are not affected.

To hear a setting without saving it, add the same fields to the preview:

```http theme={null}
POST /api/v1/byok/voices/preview
```

```json theme={null}
{ "voice": "a0e99841-438c-4a64-b679-ae501e7d6091", "speed": 0.95, "volume": 1.4 }
```

Only the fields you send are spoken; the agent's saved settings are not read.

### Choose how one agent uses your keys

`byok` is a field of the agent, on `POST /api/v1/agents` and `PATCH /api/v1/agents/{id}`, and comes
back on every agent:

```http theme={null}
PATCH /api/v1/agents/{id}
```

```json theme={null}
{ "byok": "llm_voice" }
```

* Leave `byok` out and the agent's choice is unchanged.
* `null` (or `"workspace"`) follows the workspace's default scope. An agent that follows the workspace
  comes back as `"workspace"`.
* `"off"` keeps this agent on our voices, models and pricing.
* `"all"`, `"voice"`, `"llm"` or `"llm_voice"` runs this agent on that scope's keys. It is refused with
  `409` if the workspace has no checked key for something the scope needs, and the error names it.
* Anything else is a 400.

In the console, the same choice is **How Agent uses your keys** on the agent's Playground and Voice
pages, shown only while your workspace uses its own keys.

Changing it needs an API key that can edit agents, as for the agent's model and voice. While an agent
is `"off"`, `GET /api/v1/agents/{id}/byok-model` and `byok-voice` answer `409`, because it uses
neither of your providers. `PUT` still saves a choice for when you switch it back on.

### Remove a key

```http theme={null}
DELETE /api/v1/byok/credentials/tts
```

The request is refused with `409` while BYOK is on and the key is one the scope needs. Under scope
`all` that is every key; under scope `voice` only the voice key is required, under scope `llm`
only the LLM key, and under scope `llm_voice` the LLM key and the voice key, so a leftover key for a
job that is ours can be deleted while BYOK is on. It is also refused while an agent is set to a scope that needs the
key. Replace a needed key instead, set that agent to follow the workspace, or turn BYOK off first.

Changing keys or switching BYOK needs an API key with **full** access. A read-only key can see the
status.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.