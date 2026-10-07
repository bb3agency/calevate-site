> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Agents

> Create, read, update and delete agents — everything the console's Agent page does, from your own code.

```http theme={null}
POST /api/v1/agents
Authorization: Bearer ta_live_…
Content-Type: application/json
```

```json theme={null}
{
  "name": "Skyline Sales",
  "instructions": "You are calling people who enquired about a flat at Sky Towers…",
  "greeting": "Hello, I'm calling from Skyline Homes.",
  "model": "prana-voice",
  "language": "Hindi",
  "secondLanguage": "English",
  "voice": { "voice": "priya", "summariseCalls": true, "maxCallSeconds": 300 },
  "collectFields": [
    { "name": "budget", "type": "number", "description": "Budget in rupees" },
    { "name": "interest", "choices": ["Hot", "Warm", "Cold"] }
  ]
}
```

```json theme={null}
{
  "id": "ag_5c4a5f93-…",
  "name": "Skyline Sales",
  "instructions": "…",
  "greeting": "Hello, I'm calling from Skyline Homes.",
  "businessDescription": "",
  "model": "prana-voice",
  "temperature": 0.3,
  "maxReplyTokens": 300,
  "language": "Hindi",
  "secondLanguage": "English",
  "escalation": { "onNoAnswer": false, "onRequest": false },
  "captureLeads": true,
  "scheduleCallbacks": false,
  "steps": [],
  "widget": { "theme": "classic", "accent": null, "height": 806, "welcomeScreen": true, "welcomeCollectLeads": true },
  "voice": {
    "answersCalls": true,
    "surfaces": ["web"],
    "voice": "priya",
    "phoneNumber": null,
    "language": null,
    "summariseCalls": true,
    "detectMachines": false,
    "recordCalls": false,
    "maxCallSeconds": 300,
    "pastConversations": "quiet"
  },
  "collectFields": [
    { "name": "budget", "type": "number", "description": "Budget in rupees", "choices": null },
    { "name": "interest", "type": "text", "description": null, "choices": ["Hot", "Warm", "Cold"] }
  ],
  "webKey": "pk_…",
  "createdAt": "2026-09-17T09:39:31Z"
}
```

An agent made here is the same thing the console makes: it opens in the
Playground a moment later with a starter persona, a website widget key and a
voice channel, and every rule the console applies — length limits, the plan's
agent allowance, which models your plan may pick — applies here too.

## Endpoints

| Method | Path | What |
| - | - | - |
| `GET` | `/agents` | List, newest first. `limit` (≤100) and `cursor` page it |
| `POST` | `/agents` | Create. `name` is required; everything else optional |
| `GET` | `/agents/{id}` | One agent |
| `PATCH` | `/agents/{id}` | Change any subset of the fields below |
| `DELETE` | `/agents/{id}` | The agent, its conversations, its knowledge and its channels. `204` |

`{id}` is the `ag_…` id every response carries.

## Fields

<ParamField body="name" type="string" required>
  2–60 characters. Required on create.
</ParamField>

<ParamField body="instructions" type="string">
  What the agent is and how it behaves, up to 8,000 characters. Left out on
  create, the agent gets the same starter persona the console gives a blank one.
</ParamField>

<ParamField body="greeting" type="string">
  The first thing it says on a call or in a chat, up to 200 characters.
</ParamField>

<ParamField body="businessDescription" type="string">
  A line about the business, up to 200 characters.
</ParamField>

<ParamField body="model" type="string">
  A model id from [`GET /api/v1/models`](/api-reference/voices-and-models),
  e.g. `prana-voice`. A model your plan does not include, or one too slow to
  answer a call, is refused when you *change to* it — never when it is already
  set.
</ParamField>

<ParamField body="temperature" type="number">
  0–2, clamped. How adventurous the wording is.
</ParamField>

<ParamField body="maxReplyTokens" type="number">
  100–800, clamped. One ceiling for chat and calls.
</ParamField>

<ParamField body="language" type="string">
  `"auto"` (follow the customer) or a language the console offers — `"Hindi"`,
  `"English"`, `"Tamil"`…
</ParamField>

<ParamField body="secondLanguage" type="string | null">
  A second language it may switch to. `null` clears it. Ignored when
  `language` is `"auto"`, which already follows the customer.
</ParamField>

<ParamField body="escalation" type="object">
  `{ "onNoAnswer": bool, "onRequest": bool }` — when the agent fetches a person.
</ParamField>

<ParamField body="captureLeads" type="boolean">
  Whether it takes a name, email or phone from an interested customer.
</ParamField>

<ParamField body="scheduleCallbacks" type="boolean">
  Whether it may book a callback when asked.
</ParamField>

<ParamField body="steps" type="object[]">
  A conversation script: up to 12 of `{ "title": "…", "detail": "…" }`, in
  order.
</ParamField>

<ParamField body="widget" type="object">
  The website widget: `theme` (`classic` or `modern`), `accent` (a `#rrggbb`
  colour or null), `height` (420–900), `welcomeScreen`, `welcomeCollectLeads`.
</ParamField>

<ParamField body="voice" type="object">
  How it handles calls. Any subset:

  * `answersCalls` — whether it answers at all.
  * `voice` — an id from [`GET /api/v1/voices`](/api-reference/voices-and-models).
  * `language` — the language for calls, or `null` to follow the agent's.
  * `summariseCalls` — write a summary after every call ([what that produces](/api-reference/get-call)).
  * `detectMachines` — hang up on an answering machine.
  * `recordCalls` — keep a recording.
  * `maxCallSeconds` — 60–1200, or `null` for the plan's default.
  * `pastConversations` — what a call does with earlier conversations:
    `quiet` (the default: used, never mentioned), `recap` (opens by recapping
    and asking whether to carry on) or `fresh` (nothing from before). See
    [Earlier conversations](/channels/voice#earlier-conversations).

  Read-only in the response: `surfaces` (`web`, `phone`) and `phoneNumber`.
  Attaching a number is done on the **Phone Numbers** page.
</ParamField>

<ParamField body="collectFields" type="object[]">
  The details the agent fills in after **every** call — the **Collect details**
  list on its Actions page. The same shape as a call's
  [`extract`](/api-reference/place-call): `name`, `type`, `description`,
  `choices`, up to 30.

  They arrive as `fields` in each [call's results](/api-reference/get-call),
  and on the records link the Actions page shows. A call that sends its own
  `extract` uses that list instead.

  Set here, the details are read from the transcript after the call; the agent
  is not given a tool to save them mid-call. If you switched that on in the
  console, a later change here leaves it on. An empty list stops collecting —
  the records already taken are kept.
</ParamField>

## Responses

<ResponseField name="201 / 200" type="object">
  The agent, as above. `PATCH` returns the whole agent after the change.
</ResponseField>

<ResponseField name="400" type="object">
  A field that does not follow the rules above. `error` says which.
</ResponseField>

<ResponseField name="404" type="object">
  No such agent in your workspace. Another workspace's agent is the same `404`.
</ResponseField>

<ResponseField name="409" type="object">
  Your plan's agent allowance is used up.
</ResponseField>

<Note>
  **What you will not see:** which engine speaks a voice, which service runs a
  model, or which carrier holds a number. The API describes what your agent
  does; how we run it this month is ours to change.
</Note>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.