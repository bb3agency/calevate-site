> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# WhatsApp Webhooks

> Receive real-time WhatsApp event notifications from Vobiz on your own server - inbound messages, delivery status, and call events delivered as signed HTTP callbacks.

There are **two** webhook systems in a Vobiz WhatsApp integration. Keep them separate when you design your integration:

| System | Direction | Who configures it | Purpose |
| - | - | - | - |
| **Inbound** | Meta → Vobiz | Platform plumbing (set once in your Meta App) | Meta delivers raw WhatsApp Cloud API events to Vobiz. |
| **Outbound** | Vobiz → your server | App developers | Vobiz forwards events to the HTTPS endpoint you register. |

Most app developers only work with the **outbound** system: register a subscription, then receive signed POSTs. The inbound system is described here for completeness.

## Inbound (Meta → Vobiz)

Meta sends WhatsApp Cloud API events to a single Vobiz endpoint:

```
https://api.vobiz.ai/api/v1/webhooks/whatsapp
```

You normally configure this **once** inside your Meta App (or it is configured for you during onboarding). You don't call it from your own application - Vobiz is the receiver. See the [Webhooks API](/docs/whatsapp/api/webhooks) for the verification handshake, the `X-Hub-Signature-256` requirement, and the Meta payload shape.

## Outbound (Vobiz → your server)

This is what you build against. You register an HTTPS endpoint and a shared secret; Vobiz then `POST`s a signed envelope to your endpoint whenever a relevant WhatsApp event occurs.

### How it works

1. **Register a subscription** - `POST /api/v1/messaging/webhooks` with your `url` and a `secret`.
2. **An event occurs** - a customer messages you, a message you sent changes delivery status, or a call event happens.
3. **Vobiz POSTs to your `url`** - with the [common envelope](/docs/whatsapp/webhooks/events#common-envelope) as the JSON body, an `X-Webhook-Signature` header, and an `X-Webhook-Event` header.
4. **Your server verifies and responds** - validate the signature, then return `200` quickly and process asynchronously.

### Base URL

All subscription-management endpoints live under:

```
https://api.vobiz.ai/api/v1/messaging
```

### Authentication

Subscription-management requests authenticate with your account API credentials (get them from [console.vobiz.ai](https://console.vobiz.ai)):

```
X-Auth-ID: MA_XXXXXXXX
X-Auth-Token: <token>
```

The webhook deliveries Vobiz sends to **your** endpoint are authenticated the other way around - by the `X-Webhook-Signature` HMAC, computed with the `secret` you supplied (see [below](#verifying-the-signature)).

## Event Types

Vobiz emits exactly **three** outbound event types. The full payloads are in the [Event Reference](/docs/whatsapp/webhooks/events).

* **`message.inbound`** - an end customer sent a message to your WhatsApp number.
* **`message.status`** - a delivery-status update for a message you sent. The `status` field is one of `sent`, `delivered`, `read`, or `failed`.
* **`call.<event>`** - a WhatsApp Business Calling lifecycle event, e.g. `call.connect`, `call.status_change`, `call.terminate`.

<Note>
  `delivered` and `read` are **values of the `status` field inside `message.status`**, not separate events. There is no `message.delivered`, `message.read`, `message.sent`, `message.failed`, `contact.updated`, or `campaign.completed` webhook.
</Note>

[View Complete Event Reference →](/docs/whatsapp/webhooks/events)

## Security

### Verifying the signature

Every outbound delivery includes an `X-Webhook-Signature` header. Its value is the **hex-encoded HMAC-SHA256 of the exact raw request body**, keyed by the `secret` you registered with the subscription. There is **no** `sha256=` prefix - it is just the hex digest.

To verify:

1. Read the raw request body (do not re-serialize the parsed JSON - HMAC is over the exact bytes).
2. Compute `HMAC-SHA256(raw_body, your_secret)` and hex-encode it.
3. Constant-time compare against the `X-Webhook-Signature` header. Reject on mismatch.

```python Python (Flask) theme={null}
import hmac, hashlib
from flask import Flask, request, abort

WEBHOOK_SECRET = "your-shared-secret"  # the secret you registered

app = Flask(__name__)

@app.post("/webhooks/whatsapp")
def receive():
    raw = request.get_data()  # exact bytes
    expected = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    received = request.headers.get("X-Webhook-Signature", "")
    if not hmac.compare_digest(expected, received):
        abort(401)

    event = request.headers.get("X-Webhook-Event")  # e.g. "message.inbound"
    payload = request.get_json()
    # ... handle event ...
    return "", 200
```

```javascript Node.js (Express) theme={null}
const crypto = require("crypto");
const express = require("express");

const WEBHOOK_SECRET = "your-shared-secret";
const app = express();

// capture the raw body for HMAC verification
app.use(express.raw({ type: "application/json" }));

app.post("/webhooks/whatsapp", (req, res) => {
  const expected = crypto
    .createHmac("sha256", WEBHOOK_SECRET)
    .update(req.body) // raw Buffer
    .digest("hex");
  const received = req.get("X-Webhook-Signature") || "";

  const a = Buffer.from(expected);
  const b = Buffer.from(received);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) {
    return res.sendStatus(401);
  }

  const event = req.get("X-Webhook-Event"); // e.g. "message.status"
  const payload = JSON.parse(req.body.toString());
  // ... handle event ...
  res.sendStatus(200);
});
```

<Warning>
  Always verify `X-Webhook-Signature` before processing any webhook data. The secret is never returned by the API after creation - store it securely on your side when you create the subscription.
</Warning>

### Additional notes

* **HTTPS only** - your `url` must be an HTTPS endpoint.
* **Replay protection (inbound leg)** - on the Meta → Vobiz leg, Vobiz validates `X-Hub-Signature-256` and enforces a replay window, rejecting stale or future-dated payloads.
* **Deduplicate** on the envelope's `event_id` - deliveries can be retried.

## Best Practices

* **Respond quickly** - return `200` within a few seconds. Do heavy work asynchronously in a queue so you don't hit the delivery timeout.
* **Verify every request** - never trust a request to your webhook URL without a valid `X-Webhook-Signature`.
* **Deduplicate** - use `event_id` to ignore repeated deliveries.
* **Route on `X-Webhook-Event`** - switch on the header (which equals `event_type`) before parsing.

## Real-time UI stream (optional)

Separately from outbound webhooks, Vobiz exposes a WebSocket for building a live inbox UI:

```
wss://api.vobiz.ai/api/v1/messaging/ws
```

It pushes richer real-time UI events (e.g. `message.created`, `message.updated`, `call.incoming`, `call.status`) for an authenticated session. This is for interactive front-ends and is **not** a substitute for webhooks in server-to-server integrations.

## Next Steps

* [Webhook Event Reference →](/docs/whatsapp/webhooks/events)
* [Webhooks API →](/docs/whatsapp/api/webhooks)
* [Managing Conversations →](/docs/whatsapp/messaging/inbox)
* [Send Messages via API →](/docs/whatsapp/api/send-message)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.