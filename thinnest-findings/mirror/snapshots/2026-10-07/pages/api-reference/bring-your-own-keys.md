> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Bring your own keys

> Run your agents on your own speech-to-text, LLM and voice accounts, and pay us a flat platform fee.

With **bring your own keys** (BYOK), your workspace uses your own accounts with the providers. The
three jobs are speech-to-text, the LLM and the voice. You pay those providers directly, and we
charge a flat platform fee.

| | With your own keys |
| - | - |
| Chat reply | **₹0.02** per reply |
| Call minute | **₹1.00** a minute, all-in, our phone line included |

BYOK is all three jobs or none: it turns on only when a speech-to-text key, an LLM key and a voice
key are all added and checked. Any plan can turn it on.

Each agent can also run its own **model** from your LLM key. On the agent's **Playground**, the
Model list shows every model your key reaches. Leave it on your key's model, which is the one set
in **Settings → Your keys**, or pick another for this agent alone.

Each agent speaks with a voice you choose from your own voice provider. Open the agent's
**Voice** page: it lists every voice your key can use, and **Play** speaks a short line in the
agent's language. The preview runs on your account, so the provider charges you for those few
characters. If a provider hosts its own sample of a voice, that sample plays instead, at no
cost. An agent without a chosen voice speaks with a standard voice from your provider.

On a call, all three run on your accounts: your speech-to-text hears the caller, your LLM answers,
and your voice speaks. If one of your keys cannot be used when a call starts, the call is not
answered on our providers instead.

## In the console

Open **Settings → Your keys**. Each of the three cards has:

* **Provider.** Choose who does that job.
* **Model.** Every model the provider offers. Before you add a key, the list shows the models the
  provider offers. Once your key is checked, it shows the models **your** key reaches. Long lists
  are grouped by family, such as Flux, Aura-2 and Aura for Deepgram's voices.
* **API key**, plus any other field the provider needs. Azure, for example, needs a region.

**Verify and save** checks the key with the provider before storing it. A key the provider rejects
is not saved. Keys are stored encrypted, and are only ever shown by their last four characters.

Once all three cards are filled, switch on **Use my own keys**.

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

There is no fallback. If your provider refuses a request (a revoked key, no credit, rate limits), the
reply fails. We do not answer on our own models and bill you for it. You get a notification naming
the provider and the reason, at most once a day per provider.

## Customers

If you build on our API with [customers](/api-reference/customers), your customers use **your** keys
while BYOK is on. A customer can bring a complete set of three keys of its own, which then
overrides yours. Turning BYOK off in your workspace turns it off for all your customers.

## API

Every request below also works for a customer, with the `Thinnest-Workspace` header.

### Status

```http theme={null}
GET /api/v1/byok
```

```json theme={null}
{
  "enabled": true,
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

`using` is `own`, `developer` (a customer using its developer's keys) or `none`. `models` is what the
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
{ "enabled": true }
```

The request is refused with `409` until all three keys are added, checked, and each has a model.

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

### Remove a key

```http theme={null}
DELETE /api/v1/byok/credentials/tts
```

The request is refused with `409` while BYOK is on. Replace the key instead, or turn BYOK off
first.

Changing keys or switching BYOK needs an API key with **full** access. A read-only key can see the
status.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.