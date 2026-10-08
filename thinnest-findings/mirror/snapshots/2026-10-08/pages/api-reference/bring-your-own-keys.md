> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Bring your own keys

> Run your agents on your own speech-to-text, LLM and voice accounts, or on your own voice alone, and pay us a flat platform fee.

With **bring your own keys** (BYOK), your workspace uses your own accounts with the providers. The
three jobs are speech-to-text, the LLM and the voice. You pay those providers directly, and we
charge a flat platform fee.

You choose what you bring:

* **All three of my keys** (scope `all`). Speech-to-text, the LLM and the voice are all yours.
* **Only my voice** (scope `voice`). Your voice account speaks. Our speech-to-text hears the
  caller, our model answers, and the phone line is ours.

| | All three of my keys | Only my voice |
| - | - | - |
| Call minute | **₹1.00** (\$0.012) a minute, all-in | **₹1.50** (\$0.02) a minute, our phone line included |
| Chat reply | **₹0.02** per reply | Our usual price, because the model is ours |

Calls are billed in 30-second pulses, at the rate set when the call starts.

With all three, BYOK turns on only when a speech-to-text key, an LLM key and a voice key are all
added and checked. With only your voice, it needs only a checked voice key. Any plan can turn it
on.

With all three keys, each agent can also run its own **model** from your LLM key. On the agent's **Playground**, the
Model list shows every model your key reaches. Leave it on your key's model, which is the one set
in **Settings → Your keys**, or pick another for this agent alone.

Each agent speaks with a voice you choose from your own voice provider. Open the agent's
**Voice** page: it lists every voice your key can use, and **Play** speaks a short line in the
agent's language. The preview runs on your account, so the provider charges you for those few
characters. If a provider hosts its own sample of a voice, that sample plays instead, at no
cost. An agent without a chosen voice speaks with a standard voice from your provider.

On a call with all three, your speech-to-text hears the caller, your LLM answers, and your voice
speaks. With only your voice, only the speaking is yours. If one of your keys cannot be used when a call starts, the call is not
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
why. With all three of your keys, or without BYOK, nothing changes. The limit applies only to agents
that use your keys: an agent you have switched off your keys (below) answers on our stack, so it may
use any model.

### One agent on your keys, another on ours

BYOK is switched on for the workspace, and every agent follows it by default. Some agents can stay on
ours. Give an agent `byok: "off"` and it never uses your keys, whatever the workspace does:

* calls run on our voices, our speech-to-text and our model, and the minute is billed at our normal
  rate for that voice, not the BYOK rate;
* chat replies are billed as normal replies, not the flat BYOK reply charge;
* the voice-only model limit does not apply to it;
* the model and voice choices you saved for your own keys are kept and ignored until you switch the
  agent back to `"workspace"`.

The other agents in the workspace stay on your keys and keep the BYOK price. A customer of yours
follows the same rule on its own agents. The setting is read once when a call or a reply starts, so a
call is never priced at one rate and run on another stack. A call already ringing keeps the stack it
was started on: if you switch its agent off your keys in those few seconds, the call is refused
rather than moved onto ours.

An agent set to `"off"` is billed at our rate for the voice it uses. A new agent starts on a Premium
voice, which bills at the Premium rate, so choose a standard voice for an agent whose minutes should
be cheaper.

## In the console

Open **Settings → Your keys** and choose **All three of my keys** or **Only my voice**. With only
your voice, the speech-to-text and LLM cards are hidden, because those jobs are ours. Any keys you
added for them stay saved for when you switch back. Each card has:

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

## When a key fails

There is no fallback to our providers for a job that is yours. If your provider refuses a request
(a revoked key, no credit, rate limits), the reply fails, or the voice does not speak. We do not answer on our own models and bill you for it. You get a notification naming
the provider and the reason, at most once a day per provider. With only your voice, speech-to-text
and the LLM are ours, so our usual backups for them stay on.

## Customers

If you build on our API with [customers](/api-reference/customers), your customers use **your** keys
while BYOK is on, with your choice of all three or only the voice. A customer can bring a complete
set of its own for that choice (three keys, or a voice key), which then overrides yours. Turning BYOK off in your workspace turns it off for every customer that inherits your keys. A customer with its own complete set and its own switch on keeps using its own.

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

`scope` is what this workspace brings: `all` or `voice`. `usingScope` is the scope that applies
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

Send `enabled`, `scope`, or both. The request is refused with `409` until the keys for the scope
are added, checked, and each has a model: all three for `all`, the voice key for `voice`. While
BYOK is on, moving from `voice` to `all` needs the other two keys first.

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

To use a different voice for a single call, put it in that call's `overrides`, as
`"overrides": { "voice": "EXAVITQu4vr4xnSDxMaL" }` on `POST /api/v1/calls` or in a batch.
On a workspace using its own keys, the voice must be one of yours from `GET /byok/voices`.

A choice belongs to the provider it was made on. If you switch your voice key to another provider,
the agent speaks with the new provider's standard voice until you choose again. `GET` shows the old
choice as `stale` until then.

### Keep one agent on our stack

`byok` is a field of the agent, on `POST /api/v1/agents` and `PATCH /api/v1/agents/{id}`, and comes
back on every agent:

```http theme={null}
PATCH /api/v1/agents/{id}
```

```json theme={null}
{ "byok": "off" }
```

`"workspace"` (the default) follows the workspace; `"off"` keeps this agent on our voices, models and
pricing. Anything else is a 400. In the console, the same switch is **This agent uses your own keys**
on the agent's Playground and Voice pages, shown only while your workspace uses its own keys.

Changing it needs an API key that can edit agents, as for the agent's model and voice. While an agent
is `"off"`, `GET /api/v1/agents/{id}/byok-model` and `byok-voice` answer `409`, because it uses
neither of your providers. `PUT` still saves a choice for when you switch it back on.

### Remove a key

```http theme={null}
DELETE /api/v1/byok/credentials/tts
```

The request is refused with `409` while BYOK is on and the key is one the scope needs. Under scope
`all` that is every key; under scope `voice` only the voice key is required, so a leftover
speech-to-text or LLM key can be deleted while BYOK is on. Replace a needed key instead, or turn BYOK
off first.

Changing keys or switching BYOK needs an API key with **full** access. A read-only key can see the
status.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.