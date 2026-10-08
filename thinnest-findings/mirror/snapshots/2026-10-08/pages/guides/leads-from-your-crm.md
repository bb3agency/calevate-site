> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Call leads from your CRM

> A lead lands in your CRM, your agent rings them within minutes, and the summary, their answers and the recording go back to the same record.

A property enquiry that waits until tomorrow is a lead your competitor already
called. By the end of this, every new lead in your CRM is rung by your agent —
straight away in working hours, first thing next morning otherwise — and the
lead's record gets a summary of the call, the answers you care about (budget,
interest, site visit) and a link to the recording.

It works with any CRM that can send a webhook when a lead is created —
LeadSquared, Sell.Do, Kylas, HubSpot, Zoho and most others — using a connector
tool such as Pabbly Connect, Make or Zapier in the middle. It takes about thirty
minutes.

## What you need

* An agent that answers the phone, with a number.
* An API key, from **Settings → API keys**.
* An account on a connector tool (Pabbly Connect, Make or Zapier).

## 1. Write the agent for this call

On the agent's **Instructions**, describe the call. Use `{{…}}` for anything the
CRM will tell it about the lead:

```text theme={null}
You are calling {{lead_name}}, who enquired about {{project}} a few minutes ago.
Confirm they are still looking, ask what budget they have in mind, whether they
want a 2BHK or 3BHK, and whether they would like to visit the site this week.
Keep it short and friendly. If they are busy, ask when to call back.
```

<Tip>
  Test it from the playground with those variables filled in before a real lead
  hears it.
</Tip>

## 2. When a lead arrives, place the call

In your connector tool, start a flow from your CRM's **new lead** trigger, and
add an HTTP step:

```http theme={null}
POST https://app.thinnest.ai/api/v1/calls
Authorization: Bearer ta_live_…
Content-Type: application/json
Idempotency-Key: lead-{{CRM lead id}}
```

```json theme={null}
{
  "to": "{{CRM phone}}",
  "purpose": "Hello, I'm calling from Skyline Homes about your enquiry for {{CRM project}}.",
  "name": "{{CRM name}}",
  "source": "{{CRM lead source}}",
  "reference": "{{CRM lead id}}",
  "variables": { "lead_name": "{{CRM first name}}", "project": "{{CRM project}}" },
  "callingHours": { "start": "10:00", "end": "19:00" },
  "extract": [
    { "name": "budget", "type": "number", "description": "Budget in rupees" },
    { "name": "configuration", "choices": ["1BHK", "2BHK", "3BHK", "Villa"] },
    { "name": "site_visit", "type": "boolean", "description": "Wants to visit the site" },
    { "name": "visit_date", "type": "date" },
    { "name": "interest", "choices": ["Hot", "Warm", "Cold", "Not interested"] }
  ],
  "summary": true
}
```

* The lead does **not** need to be in your contacts first — it is added, with the
  name and source you sent.
* A lead that arrives at 11pm gets `"status": "scheduled"` and is rung at 10am
  in their own time. Use `"ifOutsideHours": "refuse"` if you would rather decide
  yourself.
* The `Idempotency-Key` means a CRM that fires the trigger twice still rings the
  lead once.

Full reference: [Place a call](/api-reference/calls/place-call).

## 3. Send the results back

On the agent's **Actions** page, under **Send what happens somewhere else**, add
your connector tool's webhook address and tick **A call's results are ready**.
Copy the signing secret.

In a second flow, start from that webhook. Each call sends one delivery:

```json theme={null}
{
  "id": "evt_9d1c…",
  "event": "call.analysed",
  "sentAt": "2026-10-07T09:12:03.551Z",
  "data": {
    "reference": "LSQ-42",
    "status": "completed",
    "summary": "Asha is keen on a 2BHK with a budget around 80 lakh and wants to visit on Saturday.",
    "fields": { "budget": 8000000, "configuration": "2BHK", "site_visit": true, "interest": "Hot" },
    "recording": { "url": "https://app.thinnest.ai/api/v1/recordings/…", "expiresAt": "…" }
  }
}
```

`id` is the event's id, repeated in the `x-thinnest-event-id` header. A delivery
that fails is tried again (1 minute, 5 minutes, 30 minutes, 2 hours, 6 hours)
with the same `id`, so **dedupe on it** and answer 2xx quickly, or a retry will
update the lead twice. Headers, retries and re-sending are in
[Webhooks](/api-reference/webhooks). To stop calling someone who asked not to
be called, subscribe to `contact.opted_out` too.

`id` is the event's id, repeated in the `x-thinnest-event-id` header. A delivery
that fails is tried again (1 minute, 5 minutes, 30 minutes, 2 hours, 6 hours)
with the same `id`, so **dedupe on it** and answer 2xx quickly, or a retry will
update the lead twice. Headers, retries and re-sending are in
[Webhooks](/api-reference/webhooks). To stop calling someone who asked not to
be called, subscribe to `contact.opted_out` too.

Then **update** the lead in your CRM:

| From the call | To your CRM |
| - | - |
| `data.reference` | the lead to update |
| `data.summary` | a note or activity |
| `data.fields.budget`, `…interest`, `…site_visit` | the matching lead fields |
| `data.recording.url` | a link field, or attach the file |
| `data.status`, `data.hangup` | call outcome — `missed` + `no_answer` means ring again later |

<Warning>
  **Recording links expire** when your plan deletes the recording — 30 days on
  pay-as-you-go, 49 on Pro, 75 on Scale. If your team needs recordings for longer, have the
  flow download the file into your CRM rather than saving only the link.
</Warning>

A field the lead did not answer is simply missing from `fields`, so map each one
as optional. A missed call still sends a delivery, with `status: "missed"` and
no summary.

## 4. Try it end to end

Create a test lead in your CRM with your own number. Within a minute your phone
should ring; answer as a buyer would. A few seconds after you hang up, the lead
should show the note, the fields and the link.

If the result does not arrive, read it directly — it is the same object:

```http theme={null}
GET https://app.thinnest.ai/api/v1/calls/{id}
Authorization: Bearer ta_live_…
```

## Things worth knowing

* **Who is refused.** Anyone who told your agent to stop, on any channel, and any
  number on your do-not-call list. `source` is your record of why you had the
  number — keep it honest.
* **Calling rules.** Calls are only ever placed between 9am and 9pm in the lead's
  own time, and never earlier or later whatever you send. Promotional calling in
  India also needs DLT registration and DND checks on your side.
* **The lead converted while the phone rang.** `DELETE /api/v1/calls/{id}`
  cancels a call still waiting, and ends one that is ringing or connected — see
  [Cancelling or ending a call](/api-reference/calls/get-call).
* **A different number or voice for some leads.** Send `from` (one of the
  agent's numbers) or `overrides` on the call; the agent itself is not changed.
* **Fields every call should fill.** Set them once on the agent as
  `collectFields` ([Agents](/api-reference/agents/create-agent)) instead of sending
  `extract` each time.
* **Only answers the lead gave.** Fields are filled from what the *customer* said
  on that call. Nothing is guessed, and a `number` field gets a number or
  nothing — "80 lakh" arrives as `8000000`.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.