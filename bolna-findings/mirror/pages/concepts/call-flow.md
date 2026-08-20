> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# How a Call Flows Through Bolna

> A step-by-step walkthrough of what happens from the moment a call is placed to the moment the execution record is finalized.

This page traces the lifecycle of an outbound call placed via `POST /call`. The same stages apply to inbound calls, starting from Step 3.

***

## Full lifecycle

```
Your app → POST /call → Bolna API → Telephony provider → Recipient's phone
                                                              ↓
                                              Call answered (or not)
                                                              ↓
                                         Transcriber ← Audio stream
                                                              ↓
                                              LLM processes transcript
                                                              ↓
                                         Synthesizer → Audio stream → Caller
                                                              ↓
                                              Call ends (hangup or timeout)
                                                              ↓
                                          Post-call processing (transcript, cost, extraction)
                                                              ↓
                                              Execution record: status = completed
```

***

## Step-by-step

### 1. Call request accepted

Your app calls `POST /call` with `agent_id`, `recipient_phone_number`, and optional call metadata. Bolna validates the request and returns:

```json theme={"system"}
{
  "execution_id": "b7140255-af33-4608-8e97-04dd944b8e48",
  "status": "queued"
}
```

The execution record is created in the `queued` state. No telephony has happened yet.

### 2. Telephony dialing

Bolna's call scheduler picks up the queued execution and dials out via the configured telephony provider (Plivo, Twilio, Exotel, or your SIP trunk). The execution moves to `initiated`, then `ringing` as the call progresses through the network.

### 3. Call answered → pipeline starts

When the recipient answers, the status moves to `in-progress`. The real-time pipeline activates:

1. **Audio capture** — the telephony provider streams caller audio to Bolna
2. **Transcription** — the transcriber (e.g. Deepgram) converts audio to text in real-time
3. **LLM inference** — the transcript is sent to the LLM with the agent's system prompt; the LLM streams a response
4. **Synthesis** — the synthesizer converts the LLM response to speech audio
5. **Audio playback** — Bolna streams the synthesized audio back to the caller

This loop repeats for every conversational turn.

### 4. Tools (if configured)

If the agent's prompt triggers a tool call (function call, knowledge base lookup, call transfer), the LLM emits a tool-call intent. Bolna:

* Pauses synthesis
* Executes the tool (calls your API endpoint, queries the knowledge base, etc.)
* Feeds the tool result back to the LLM
* Resumes the conversation

Tool calls add 50–500ms of latency depending on the tool's response time.

### 5. Call ends

The call ends when:

* The caller hangs up
* The agent's hangup prompt fires (e.g. "Have a great day, goodbye!")
* `call_terminate` timeout is reached (configured in `task_config`)
* `hangup_after_silence` fires (no speech for N seconds)
* The agent calls the hangup tool explicitly

The telephony provider signals the disconnect. The execution moves to `call-disconnected`.

### 6. Post-call processing

`call-disconnected` is NOT the final state. After the line drops, Bolna runs:

* Transcript assembly (merges partial chunks into the full conversation text)
* Cost calculation (platform fee + network + transcriber + LLM + synthesizer)
* Post-call extraction (if an extraction task is configured — runs the LLM over the transcript to pull structured data)
* Recording URL generation

When all processing completes, the execution moves to **`completed`** and all fields are populated.

<Warning>
  **Always wait for `completed`**, not `call-disconnected`, before reading `conversation_duration`, `total_cost`, `recording_url`, or `extracted_data`. These are `null` or `0` at `call-disconnected`.
</Warning>

### 7. Webhook delivery

If `webhook_url` is set on the agent, Bolna POSTs the execution payload to your server at each status change. The final `completed` POST includes all populated fields.

Source IPs: `13.203.39.153`, `13.126.9.249`, `13.202.133.53` — whitelist all three on your server.

***

## Execution status reference

| Status              | Phase                            |
| ------------------- | -------------------------------- |
| `queued`            | Accepted, waiting to dial        |
| `initiated`         | Dialing                          |
| `ringing`           | Recipient's phone ringing        |
| `in-progress`       | Call answered, pipeline active   |
| `call-disconnected` | Line dropped, post-processing    |
| `completed`         | All fields finalized ✓           |
| `no-answer`         | Not picked up                    |
| `busy`              | Line busy                        |
| `failed`            | Telephony error                  |
| `canceled`          | Manually canceled before answer  |
| `stopped`           | Stopped mid-execution            |
| `error`             | Internal error during processing |
| `balance-low`       | Insufficient wallet balance      |

See [Errors & Status Codes](/docs/api-reference/errors) for the full enum with terminal/intermediate labels.

***

## Related

* [Make a Call API](/docs/api-reference/calls/make)
* [Get Execution API](/docs/api-reference/executions/get_execution)
* [Webhooks](/docs/guides/post-call/polling-call-status-webhooks)
* [Hangup & Termination](/docs/guides/outbound/hangup-calls)
