# REPORTED-DOCS — hosted-platform facts from search summaries

**Nothing on this page has been read by anyone in this repository.** `docs.bolna.ai`,
`www.bolna.ai` and `api.bolna.ai` are all refused by this environment's egress proxy
(`EGRESS_BLOCKED`); the `www.bolna.ai/docs/...` path was tried once directly and refused
too. Every row below is a **WebSearch result summary** that quoted or paraphrased one of
those pages, gathered 2026-08-18.

**Suggestive, never proof.** A REPORTED-DOCS row may sharpen a marked assumption and may
justify a doc or comment change. It may **not** justify a behaviour change on its own —
that is the D-31/D-32 rule, and the one place it would have been most tempting to break it
is the cost unit, which was left alone.

---

## Get Execution response

Described from a summary of `https://www.bolna.ai/docs/api-reference/executions/get_execution`.

Fields named: `id`, `agent_id`, `batch_id`, `conversation_time`, `total_cost`, `status`,
`error_message`, `answered_by_voice_mail`, `transcript`, `created_at`, `updated_at`.

`telephony_data` object: `duration`, `to_number`, `from_number`, `recording_url`,
`hosted_telephony`, `provider_call_id`.

`cost_breakdown` object: **`llm`, `network`, `platform`, `synthesizer`, `transcriber`**.

**What this settled.** Our adapter reads exactly those five `cost_breakdown` keys. Two of
them (`platform`, `network`) had no source before this and were carried as guesses; the
other three are independently VERIFIED-OSS. All five now have at least this. Our
`telephony_data` reads (`from_number`, `to_number`, `recording_url`) are all named here.

**What it did NOT settle.** The **unit** of `total_cost` and `cost_breakdown`, and whether
any currency is stated at all. No currency field is named in the summary. See gate 7.

**What we are not reading.** `error_message`, `answered_by_voice_mail`, `batch_id`,
`hosted_telephony`, `provider_call_id`. `answered_by_voice_mail` is the interesting one —
see below.

---

## Status lifecycle and webhooks

Described from summaries of `https://docs.bolna.ai/polling-call-status-webhooks` and
`https://docs.bolna.ai/list-phone-call-status`.

- The documented progression is **`scheduled → queued → in-progress → completed`**. All
  four are in our `_STATUS_MAP`.
- **`completed` is the FINAL status of every conversation**, indicating post-call
  processing (recordings, data extraction) is finished. This is direct support for
  `billable_ready = (raw_status == "completed")` and for triggering the post-call pipeline
  on `completed` rather than on a disconnect.
- **The webhook payload "matches the Get Execution API response format"** — i.e. one shape,
  two delivery paths. This is load-bearing for `parse_webhook`, which reuses `_snapshot`,
  and for the reconciliation poller being able to repair from the same parser. **It is
  confirmed only at this class**, and gate 1 already asks for the byte-level comparison.
- The full status enumeration was **not** recoverable from any snippet. Several searches
  returned the page title and no body. So the other eleven keys in `_STATUS_MAP`
  (`initiated`, `ringing`, `call-connected`, `call-disconnected`, `no-answer`, `busy`,
  `voicemail`, `failed`, `canceled`/`cancelled`, `stopped`, `error`, `balance-low`) remain
  **STILL UNVERIFIED**.

### `voicemail`: a status we map, or a flag we ignore?

`answered_by_voice_mail` is reported as a **separate boolean field** on Get Execution, and
VERIFIED-OSS has voicemail as a **hangup reason** (`HangupReason.VOICEMAIL_DETECTED`) under
a `ConversationConfig.voicemail` detector. Both are facts *about* a call whose status is
plain `completed`.

If that is how the hosted platform reports it, our `voicemail` `CallStatus` is unreachable
and every voicemail currently reads to a client as a normal completed call. Not rewired on
inference — reading a flag into the status would change what a client's screen says about
calls we have never seen. **OPERATIONS §2 gate 17.**

---

## Pricing shape

Described from summaries of `https://docs.bolna.ai/pricing/agent-pricing`,
`https://www.bolna.ai/docs/pricing/call-pricing` and the public pricing page.

- Cost is the sum of **five components across three parts**: voice AI processing
  (STT + LLM + TTS), telephony, and a Bolna platform fee — which lines up with the
  five-key `cost_breakdown` above.
- STT billed by call duration, LLM by tokens, TTS by characters synthesized.
- Platform fee reported as a flat **$0.02/min**; dashboard estimate ~**$0.06/min**
  excluding telephony.
- Prepaid credits from $10; no monthly floor (this is D-32's finding, restated).

**All prices are quoted in DOLLARS per minute, never in cents.** Together with the
VERIFIED-OSS cost function returning a rounded dollar float, this is the second independent
signal against the `USD cents` assumption — and still not the observation that settles it,
which is one completed call's `total_cost` beside the same call's dashboard charge.
**OPERATIONS §2 gate 7.**

---

## Agent v2 routes

A search summary of the v2 agent reference lists `GET /v2/agent/{agent_id}` beside the
`POST /v2/agent`, `PUT /v2/agent/:agent_id` and `GET /v2/agent/all` the adapter already
calls, and documents `DELETE https://api.bolna.ai/v2/agent/{agent_id}` returning
`{"message": "success", "state": "deleted"}` with 400 as the only other documented status.
This is the pre-existing basis for `delete_agent`'s docstring and is unchanged by this
harvest; what the harvest added is the OSS *intent* of 404 on a repeat. Gate 2 still owns
the question.
