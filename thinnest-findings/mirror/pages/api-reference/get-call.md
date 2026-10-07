> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Get a call's results

> GET /api/v1/calls/{id} and the call.analysed webhook — the summary, the details you asked for, the transcript and a recording link.

```http theme={null}
GET /api/v1/calls/out_9f2c1a44-...
Authorization: Bearer ta_live_…
```

```json theme={null}
{
  "id": "out_9f2c1a44-...",
  "callRef": "out_9f2c1a44-...",
  "reference": "LSQ-42",
  "metadata": { "deal_id": "D-19", "owner": "Ravi" },
  "attempt": 1,
  "status": "completed",
  "direction": "outbound",
  "phone": "919876543210",
  "from": "918045678901",
  "agent": { "id": "ag_5d1c…", "name": "Skyline Sales" },
  "scheduledFor": null,
  "startedAt": "2026-09-18T04:30:02Z",
  "answeredAt": "2026-09-18T04:30:09Z",
  "endedAt": "2026-09-18T04:33:11Z",
  "seconds": 182,
  "hangup": "answered",
  "variables": { "lead_name": "Asha", "project": "Sky Towers" },
  "summary": "Asha is keen on a 2BHK at Sky Towers with a budget around 80 lakh. She asked to visit the site on Saturday.",
  "fields": { "budget": 8000000, "interest": "Hot", "site_visit": true },
  "transcript": [
    { "speaker": "agent", "text": "Hello Asha, I'm calling from Skyline Homes…", "at": "2026-09-18T04:30:10Z" },
    { "speaker": "customer", "text": "Yes, go ahead…", "at": "2026-09-18T04:30:14Z" }
  ],
  "recording": {
    "url": "https://app.thinnest.ai/api/v1/recordings/3b7e…?expires=1760000000&sig=…",
    "expiresAt": "2026-10-18T04:30:02Z",
    "ready": true
  },
  "analysedAt": "2026-09-18T04:33:20Z",
  "retryScheduledFor": null,
  "error": null
}
```

Use the `id` that [Place a call](/api-reference/place-call) gave you — `out_…`
for a call placed at once, `sch_…` for one that was scheduled. Ids from another
workspace, and calls the API did not place, are `404`.

## Pushed to you instead: `call.analysed`

On the agent's **Actions** page, add an endpoint and tick **A call's results are
ready**. It receives exactly the object above, once per try, after the summary
and fields are written:

```json theme={null}
{
  "event": "call.analysed",
  "sentAt": "2026-09-18T04:33:20Z",
  "data": { "id": "out_9f2c1a44-...", "reference": "LSQ-42", "summary": "…", "fields": { … } }
}
```

Every delivery carries an `x-thinnest-signature: sha256=…` header, an HMAC of the
raw body under the secret shown when you added the endpoint.

**One event per try.** A call with `retry` sends `call.analysed` after each
attempt under the same `id`: the first says `status: "missed"`, `attempt: 1`
and `retryScheduledFor`; the retry's own report follows when it rings. If a
queued try can never be placed, one last event says `status: "failed"` (or
`cancelled`, when the person opted out meanwhile) with `hangup: "not_placed"`
and the reason in `error`. `GET` always answers with the newest try.

It fires for **every** call the agent makes or takes, including missed ones —
`status: "missed"` with an empty `fields` is how you learn nobody picked up.
Poll `GET` as well if you cannot afford to miss one: a delivery is not retried,
and an endpoint that fails five times in a row is switched off.

<Tip>
  Most CRMs cannot take this shape directly. Put Pabbly Connect, Make or Zapier
  in between and map `fields.budget` to your CRM's budget field, `summary` to a
  note, and `recording.url` to a link field.
</Tip>

## Cancelling or ending a call

```http theme={null}
DELETE /api/v1/calls/{id}
Authorization: Bearer ta_live_…
```

The lead converted, the deal closed, the CRM changed its mind:

* **Waiting to ring** — booked, queued for its hours, or a retry. It is
  cancelled; the answer is `200` with the report, `status: "cancelled"`.
* **Ringing or on the line** — the call is ended at once, mid-sentence if the
  agent is talking. The answer is `202` with the report as it stands; the
  ending arrives a moment later like any other, with its `call.analysed`.
  **No retry follows**, whatever `retry` asked for.
* **Already ended** — `409` with its report.

A call on a number you brought without adding its carrier credentials cannot be
ended from here, and answers `409` saying so. After either, the person may be
rung again by a new request.

## Fields

<ResponseField name="id" type="string">
  The id the API handed you. Stays the same for a scheduled call once it rings.
</ResponseField>

<ResponseField name="callRef" type="string | null">
  Our reference for the attempt that actually rang. Null while scheduled. For
  support; map on `id` or `reference` instead.
</ResponseField>

<ResponseField name="reference" type="string | null">
  Your own `reference`, untouched.
</ResponseField>

<ResponseField name="phone" type="string | null">
  The customer's number.
</ResponseField>

<ResponseField name="from" type="string | null">
  Your number the call rang from. For a call still waiting, the `from` you
  chose — or `null`, when the agent's own number will be decided as it dials.
</ResponseField>

<ResponseField name="status" type="string">
  `scheduled`, `ringing`, `connected`, `completed`, `missed`, `failed`, or
  `cancelled` (a scheduled call whose customer opted out, or whose number was
  put on the do-not-call list, before it rang).
</ResponseField>

<ResponseField name="hangup" type="string | null">
  Why it ended: `answered`, `no_answer`, `busy`, `rejected`, `unreachable`,
  `cancelled`, `voicemail`, `before_agent`, `failed` — or `not_placed` for a
  scheduled call that never rang. Null while the call is live.
</ResponseField>

<ResponseField name="summary" type="string | null">
  Two or three sentences on what the customer said and how the call ended. Null
  when summaries are off for this call, or nobody spoke.
</ResponseField>

<ResponseField name="fields" type="object">
  The `extract` fields the customer actually answered, keyed by your names and
  typed as you asked. A field they said nothing about is **absent**, never
  `null` or `"N/A"`. Empty when nothing was asked or nothing was said.
</ResponseField>

<ResponseField name="transcript" type="object[]">
  What was said on this call only — `speaker` is `agent`, `customer` or `team`
  (a teammate who joined). Your team's internal notes are never included.
</ResponseField>

<ResponseField name="recording" type="object | null">
  A link to the call's audio, or null when the call was not recorded.

  * Anyone holding the link can play it — store it where you store the rest of
    the lead.
  * It stops working when your plan deletes the recording: **30 days** on
    pay-as-you-go, **75** on Scale. `expiresAt` is that moment; save the file
    itself if you need it longer.
  * `ready: false` means the audio is still arriving. The link is already
    valid and answers `404 — not ready yet` for a minute or so. A website
    call's recording lands just after the call ends, so its first
    `call.analysed` usually says `ready: false` — the link in it still works
    once the audio is in.
</ResponseField>

<ResponseField name="metadata" type="object | null">
  The `metadata` you sent with the call, untouched.
</ResponseField>

<ResponseField name="attempt" type="number">
  Which try this report is about: `1` for the first, `2` for the first retry.
</ResponseField>

<ResponseField name="retryScheduledFor" type="string | null">
  When the next try will ring, if this one did not reach the person and a
  [retry](/api-reference/place-call) is queued. Null otherwise.
</ResponseField>

<ResponseField name="analysedAt" type="string | null">
  When the summary and fields were finished. Null means they are not final yet —
  read again in a few seconds.
</ResponseField>

<ResponseField name="error" type="string | null">
  For a scheduled call that could not be placed: why.
</ResponseField>

## Cost

The summary and the fields are each one pass of a small model over the
transcript after the call, billed to your balance like any other usage. Fields are only extracted when somebody will read them: a
call placed through the API, or an agent with an endpoint subscribed to
`call.analysed`.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.