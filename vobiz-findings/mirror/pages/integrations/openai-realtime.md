> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# OpenAI Realtime SIP Call Handler

> Connect inbound Vobiz SIP calls directly to OpenAI's Realtime API for natural, low-latency AI voice conversations across 130+ countries including India.

<img className="block w-full rounded-xl border border-gray-200" src="https://mintcdn.com/vobizai/OZ7y9Kg025aXyvCH/images/integration-bg/openairealtime.png?fit=max&auto=format&n=OZ7y9Kg025aXyvCH&q=85&s=00a68d055c196163fa5805642dcca342" alt="OpenAI Realtime API integration with Vobiz SIP trunking" width="3600" height="2160" data-path="images/integration-bg/openairealtime.png" />

Connect inbound calls on a Vobiz number directly to OpenAI's Realtime API. The AI answers the call and holds a natural, low-latency conversation with the caller.

<Note>
  **Scope:** inbound calls only. A caller dials a Vobiz number and is answered by the AI agent.
</Note>

**Source code:** [vobiz-ai/Vobiz-Openai-Realtime](https://github.com/vobiz-ai/Vobiz-Openai-Realtime) - the reference Flask service used throughout this guide (`app.py`, `requirements.txt`, `.env.example`).

## How it works

Vobiz does not proxy the audio. The SIP INVITE is handed to OpenAI, which terminates the media directly with the caller. Your application server only performs control-plane work over HTTPS and a WebSocket - it never handles RTP.

```text theme={null}
Caller
  └─> Vobiz DID
        └─> Inbound Trunk  (transport: TLS, secure: true)
              └─> Origination URI  →  sip:{PROJECT_ID}@sip.api.openai.com:5061
                    └─> OpenAI fires  realtime.call.incoming  webhook
                          └─> Your server: POST /v1/realtime/calls/{call_id}/accept
                                └─> Your server: wss://api.openai.com/v1/realtime?call_id=…
                                      └─> SRTP media flows OpenAI ⟷ caller
```

Because OpenAI terminates the media, VobizXML verbs such as [`<Stream>`](/docs/xml/stream) are not used in this integration, and audio resampling is not required.

## Requirements

| Requirement | Detail |
| - | - |
| OpenAI account | API key, Project ID (`proj_…`), Webhook secret (`whsec_…`) |
| Vobiz account | An active phone number and permission to create trunks |
| Public HTTPS endpoint | Required by OpenAI for webhook delivery. Use ngrok in development. |
| Runtime | Python 3.8+ |

### Network requirements

| Channel | Protocol | Detail |
| - | - | - |
| SIP signalling | TCP/**TLS** | Port **5061** only. OpenAI does not accept UDP or plain TCP. |
| Media | **SRTP** over UDP | Bidirectional, from OpenAI's media ranges |

OpenAI publishes the following media CIDR blocks. Any firewall between Vobiz and OpenAI must permit bidirectional UDP with them:

```text theme={null}
13.79.45.80/28    23.98.140.64/28    40.67.149.176/28    40.83.204.240/28
```

### Regional endpoints

| Endpoint | Use |
| - | - |
| `sip.api.openai.com` | Default |
| `sip-eu.api.openai.com` | EU data residency |

## Step 1: Create the origination URI

Console: **SIP → Inbound → Origination URIs** ([console.vobiz.ai/app/sip/in/uri](https://console.vobiz.ai/app/sip/in/uri))

| Field | Value |
| - | - |
| URI | `proj_xxxxxxxx@sip.api.openai.com:5061` |
| Transport | **TLS** |
| Active | enabled |

<Warning>
  **The port `:5061` is mandatory.**

  OpenAI accepts SIP only on 5061. Without an explicit port the URI resolves to the SIP default (5060), where OpenAI is not listening. The call is refused back to the carrier before it reaches OpenAI, and the CDR shows `hangup_disposition: send_refuse` with `terminated_to: inbound_carrier`.
</Warning>

Substitute your own Project ID, found at **platform.openai.com → Settings → Project → General**.

<Accordion title="API equivalent">
  ```bash theme={null}
  curl -X POST https://api.vobiz.ai/api/v1/Account/$AUTH_ID/origination-uris \
    -H "X-Auth-ID: $AUTH_ID" \
    -H "X-Auth-Token: $AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "name": "openai-realtime",
      "sip_uri": "sip:proj_xxxxxxxx@sip.api.openai.com:5061",
      "priority": 1
    }'
  ```

  The response returns the new URI's `id`, which you pass as `primary_uri_uuid` when creating the trunk. `transport` is not settable on [Create Origination URI](/docs/trunks/origination-uri/create-origination-uri) - select **TLS** in the console.
</Accordion>

## Step 2: Create the inbound trunk

Console: **SIP → Inbound → Trunks** ([console.vobiz.ai/app/sip/in/trunks](https://console.vobiz.ai/app/sip/in/trunks))

| Field | Value |
| - | - |
| Direction | Inbound |
| Origination URI | the URI from Step 1 |
| Transport | TLS |
| **Secure (SRTP)** | **enabled** |
| Status | enabled |

<Warning>
  **`secure` must be enabled, and it is distinct from `transport`.**

  * `transport` controls **signalling** encryption (TLS).
  * `secure` controls **media** encryption (SRTP).

  OpenAI requires SRTP. If `transport` is TLS but `secure` is left disabled, the call completes signalling, answers, and bills normally - **but no audio passes**. The symptom is a connected, billed call with total silence, and elevated `packet_loss` in the CDR. Setting `secure: true` resolves it.
</Warning>

<Accordion title="API equivalent">
  <CodeGroup>
    ```bash Create theme={null}
    curl -X POST https://api.vobiz.ai/api/v1/Account/$AUTH_ID/trunks \
      -H "X-Auth-ID: $AUTH_ID" \
      -H "X-Auth-Token: $AUTH_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "name": "openai-realtime",
        "trunk_direction": "inbound",
        "trunk_status": "enabled",
        "transport": "tls",
        "secure": true,
        "primary_uri_uuid": "<origination-uri-id>",
        "concurrent_calls_limit": 10,
        "cps_limit": 5
      }'
    ```

    ```bash Enable SRTP on an existing trunk theme={null}
    curl -X PUT https://api.vobiz.ai/api/v1/Account/$AUTH_ID/trunks/$TRUNK_ID \
      -H "X-Auth-ID: $AUTH_ID" \
      -H "X-Auth-Token: $AUTH_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"secure": true, "transport": "tls"}'
    ```
  </CodeGroup>
</Accordion>

## Step 3: Assign the phone number

Attach the DID that callers will dial to the trunk from Step 2.

```bash theme={null}
# encode "+" as %2B
curl -X POST "https://api.vobiz.ai/api/v1/Account/$AUTH_ID/numbers/%2B919999999999/assign" \
  -H "X-Auth-ID: $AUTH_ID" \
  -H "X-Auth-Token: $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"trunk_group_id": "<trunk-id>"}'
```

A successful assignment returns `204 No Content`. See [Assign Number to Trunk](/docs/trunks/assign-number).

## Step 4: Register the OpenAI webhook

**platform.openai.com → Settings → Webhooks → Create**

| Field | Value |
| - | - |
| Event type | `realtime.call.incoming` |
| URL | your public HTTPS endpoint (root path) |

Copy the signing secret (`whsec_…`) shown once at creation. If it is lost, delete the webhook and recreate it.

## Step 5: Configure the service

### Environment variables

The repo ships a `.env.example`. Copy it with `cp .env.example .env` and fill in your values:

```ini .env theme={null}
# ---- OpenAI ----
# API key from platform.openai.com
OPENAI_API_KEY=sk-proj-xxxxxxxx
# Project ID - must match the value used in the Origination URI
OPENAI_PROJECT_ID=proj_xxxxxxxx
# Signing secret shown when the webhook was created
OPENAI_WEBHOOK_SECRET=whsec_xxxxxxxx

# Bypass webhook signature verification. Development only - never enable in production.
SKIP_SIGNATURE_VALIDATION=false

# ---- Vobiz ----
# DID assigned to the inbound trunk, E.164
VOBIZ_PHONE_NUMBER=+919999999999

# ---- Service ----
SERVICE_PORT=8000

# ---- Agent ----
AI_MODEL=gpt-realtime-2.1
AI_VOICE=alloy
AI_INSTRUCTIONS=You are a helpful customer support agent.
AI_GREETING=Thank you for calling, how can I help?

# ---- Escalation (optional) ----
# Destination for AI-initiated transfer. tel: for E.164, or a SIP URI.
# Leave blank to disable the transfer tool.
REFER_TARGET=tel:+919888888888
```

Notes on the keys:

* Variable names are **case-sensitive** and must be uppercase.
* Names must not contain spaces. `OPENAI WEBHOOK_SECRET` is not a valid key and is silently ignored by `python-dotenv`, which surfaces later as a signature-verification failure.
* `OPENAI_PROJECT_ID` must be identical to the user part of the Origination URI. A mismatch routes the INVITE to a different project, and the webhook never fires.
* Your Vobiz `AUTH_ID` and `AUTH_TOKEN` are only needed for the provisioning calls in Steps 1-3. The service itself talks to OpenAI, not to the Vobiz API.

### Dependencies

The repo's [`requirements.txt`](https://github.com/vobiz-ai/Vobiz-Openai-Realtime/blob/main/requirements.txt):

```text requirements.txt theme={null}
flask>=3.0
openai>=1.99
websocket-client>=1.8
requests>=2.32
python-dotenv>=1.0
gunicorn>=22.0
```

## Step 6: Handle the call

Three actions are required when `realtime.call.incoming` arrives. The excerpts below are from [`app.py`](https://github.com/vobiz-ai/Vobiz-Openai-Realtime/blob/main/app.py) in the sample repo.

### Verify the webhook signature

```python theme={null}
event = client.webhooks.unwrap(request.get_data(), dict(request.headers),
                               secret=WEBHOOK_SECRET)
```

Return `400` on failure. OpenAI signs each delivery with `webhook-id`, `webhook-timestamp` and `webhook-signature` headers.

### Accept the call

Returning `200` to the webhook does **not** accept the call. Acceptance is a separate REST call:

```python theme={null}
requests.post(
    f"https://api.openai.com/v1/realtime/calls/{call_id}/accept",
    headers={"Authorization": f"Bearer {API_KEY}",
             "Content-Type": "application/json"},
    json={
        "type": "realtime",
        "model": "gpt-realtime-2.1",
        "instructions": INSTRUCTIONS,
        "audio": {"output": {"voice": "alloy"}},
    },
)
```

Codecs are negotiated by OpenAI. Audio format fields are not set for SIP calls.

### Open the control WebSocket

```python theme={null}
ws.connect(f"wss://api.openai.com/v1/realtime?call_id={call_id}",
           header=[f"Authorization: Bearer {API_KEY}"],
           origin="https://api.openai.com")
```

This channel carries session events, transcripts and tool calls. Send `response.create` to make the agent speak first:

```python theme={null}
ws.send(json.dumps({
    "type": "response.create",
    "response": {"instructions": f"Say to the user: {GREETING}"},
}))
```

### Enable caller transcription (optional)

Caller-side transcription is off by default. Enable it after the socket opens:

```python theme={null}
ws.send(json.dumps({
    "type": "session.update",
    "session": {
        "type": "realtime",
        "audio": {"input": {"transcription": {"model": "whisper-1"}}},
    },
}))
```

Caller speech then arrives as `conversation.item.input_audio_transcription.completed`, and agent speech as `response.output_audio_transcript.done`. Both carry a `transcript` field.

## Transferring to a human agent

Escalation uses **SIP REFER**, issued by OpenAI and routed by the Vobiz trunk.

### Give the agent a transfer tool

```python theme={null}
ws.send(json.dumps({
    "type": "session.update",
    "session": {
        "type": "realtime",
        "tools": [{
            "type": "function",
            "name": "transfer_to_human",
            "description": "Transfer the caller to a human agent when they ask for a person.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        }],
        "tool_choice": "auto",
    },
}))
```

### Issue the REFER when the tool fires

Listen for `response.function_call_arguments.done`, then:

```python theme={null}
requests.post(
    f"https://api.openai.com/v1/realtime/calls/{call_id}/refer",
    headers={"Authorization": f"Bearer {API_KEY}",
             "Content-Type": "application/json"},
    json={"target_uri": "tel:+919888888888"},
)
```

OpenAI sends a SIP REFER down the Vobiz trunk, which creates a new leg to the target and bridges the caller to it. The transferred leg appears in CDR as a separate outbound record carrying the trunk ID.

**Transfer target requirements**

* The target must be reachable and able to **receive** an INVITE.
* An endpoint that can place calls is not necessarily able to receive them. A registered SIP user requires an active contact binding in the registrar; without one, the INVITE cannot be delivered and the call clears instead of transferring.
* `tel:` targets take E.164 form, for example `tel:+919888888888`.

### Other call controls

| Action | Endpoint |
| - | - |
| Reject | `POST /v1/realtime/calls/{id}/reject` - optional `status_code`, defaults to `603` |
| Hang up | `POST /v1/realtime/calls/{id}/hangup` |

## Running the service

### Development

```bash theme={null}
git clone https://github.com/vobiz-ai/Vobiz-Openai-Realtime
cd Vobiz-Openai-Realtime
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # fill in the values from Step 5
ngrok http 8000          # register the HTTPS URL as the webhook endpoint
python app.py
```

ngrok issues a new domain on each restart. The webhook URL in the OpenAI console must be updated whenever it changes.

### Production

```bash theme={null}
gunicorn -w 4 -b 0.0.0.0:8000 app:app
```

* Terminate HTTPS with a valid certificate - OpenAI does not deliver webhooks over plain HTTP.
* Keep `SKIP_SIGNATURE_VALIDATION=false`.
* Gunicorn workers do not share memory. Any per-call state must live in shared storage such as Redis if it is read outside the worker that accepted the call.

## Verifying the integration

### Webhook delivery

**platform.openai.com → Settings → Webhooks → Send test event**, selecting `realtime.call.incoming`. A correctly configured service returns `200`.

Test events carry an empty `data` object and no live SIP session, so an accept attempt returns `404 call_id_not_found`. The service should acknowledge this with `200` rather than an error - repeated `5xx` responses count against the endpoint's delivery health.

### Live call

Dial the assigned DID. The agent answers within a few seconds and speaks the configured greeting.

## Behaviour reference

| Observation | Cause | Resolution |
| - | - | - |
| Call refused, never reaches OpenAI. CDR shows `send_refuse` / `terminated_to: inbound_carrier` | Origination URI missing port `:5061` | Add the explicit port |
| Call connects, answers and bills, but audio is silent. CDR shows elevated `packet_loss` | Trunk `secure` disabled, so RTP is offered where SRTP is required | Enable `secure` on the trunk |
| Webhook returns `400` | Signature mismatch, or a malformed `.env` key preventing the secret from loading | Verify `OPENAI_WEBHOOK_SECRET`; check the key name has no spaces and is uppercase |
| Webhook returns `500` on a test event | Accept attempted against a synthetic `call_id` | Acknowledge test events with `200` |
| No webhook on a real call, though test events succeed | Project ID mismatch between `.env` and the Origination URI, or trunk/number not assigned | Align the Project ID; confirm the DID is attached to the trunk |
| Transfer clears the call instead of connecting | Target unreachable or has no active registrar contact | Use a target able to receive an INVITE |

### Useful CDR fields

| Field | Meaning |
| - | - |
| `trunk_id` | Trunk that handled the leg |
| `hangup_disposition` | `send_refuse` indicates the call was rejected before routing |
| `terminated_to` | `inbound_carrier` indicates the call never left Vobiz |
| `packet_loss` | Elevated values indicate a media-path problem |
| `answer_time` / `billsec` | `null` / `0` means the call was never answered |

## Next steps

* Clone the sample service: [vobiz-ai/Vobiz-Openai-Realtime](https://github.com/vobiz-ai/Vobiz-Openai-Realtime).
* Explore the [OpenAI Realtime API documentation](https://platform.openai.com/docs/guides/realtime).
* Review [SIP trunk configuration](/docs/trunks) and [origination URIs](/docs/trunks/origination-uri).
* Inspect call quality and routing in the [CDR reference](/docs/cdr).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.