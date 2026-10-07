> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Voices, models and numbers

> The lists an agent is configured from — GET /api/v1/voices, /models and /phone-numbers.

Three read-only lists. Their ids are what the [agent](/api-reference/agents)
fields `voice.voice` and `model` take, and what
[`POST /api/v1/calls`](/api-reference/place-call) means by `agent`'s number.

## Voices

```http theme={null}
GET /api/v1/voices
```

```json theme={null}
{
  "items": [
    { "id": "3b7e…", "name": "Anjali", "accent": "hi", "tier": "standard", "description": null },
    { "id": "priya", "name": "Priya", "accent": "hi", "tier": "premium", "description": "Best female — Hindi, Telugu, Kannada, Tamil, Marathi, Gujarati, English." },
    { "id": "spry-swallow-5564__rakesh", "name": "Rakesh Khanna", "accent": "hi", "tier": "studio", "description": "Customer support" },
    { "id": "c4a1…", "name": "Founder voice", "accent": "en-IN", "tier": "studio", "description": null, "mine": true }
  ]
}
```

The same lists the [Playground's](/channels/voice) picker shows. `tier` is the
price band a call is billed at — `standard`, `premium` or `studio` — and
`accent` is the voice's own; every voice speaks every supported language, and
the agent's language decides which it uses.

<Note>
  **The `studio` tier is on the Scale plan and above.** Below Scale this list
  never includes it — not hidden by a flag, just absent — so `voice.voice`
  cannot be set to a Studio voice on a plan that cannot use one. See [Voice
  Clone](/channels/voice-clone) for cloning your own.
</Note>

`mine: true` marks a voice your workspace cloned rather than one from the
shared catalogue — omitted (never `false`) on every other voice. It never
appears for a plan below Scale, because a workspace below Scale has nothing to
clone with.

## Models

```http theme={null}
GET /api/v1/models
```

```json theme={null}
{
  "items": [
    { "id": "prana-voice", "name": "Prana [Voice]", "voice": true, "minPlan": "free", "available": true },
    { "id": "gpt-5-mini", "name": "GPT-5 Mini", "voice": true, "minPlan": "free", "available": true },
    { "id": "gpt-4.1", "name": "GPT-4.1", "voice": false, "minPlan": "payg", "available": false }
  ]
}
```

`voice` says whether it is quick enough to answer a phone call. `available`
says whether **your** plan may pick it; the rest are shown so you can see what
an upgrade would add.

## Phone numbers

```http theme={null}
GET /api/v1/phone-numbers
```

```json theme={null}
{
  "items": [
    { "number": "918012345678", "label": "Sales line", "source": "rented", "agent": "ag_5c4a…", "since": "2026-08-01T00:00:00Z", "provider": "ThinnestAI" }
  ]
}
```

Every number your workspace can call from or be called on: `rented` from us,
or `brought` from your own account. `provider` is whose network it is on —
`ThinnestAI` for a number from us, `plivo`, `vobiz`, `twilio` or `telnyx` for one you
brought; an agent can call from numbers on several. `agent` is the agent answering on it, or
`null` while unassigned or lent to an agent only for calling out — every number
you brought is listed, so any of them can be a call's `from`. Renting a number and attaching it to an agent are done
in the console.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.