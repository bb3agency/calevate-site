> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Webhooks API

> Manage Vobiz outbound webhook subscriptions and understand the inbound Meta callback - create, list, and delete subscriptions to receive WhatsApp inbound messages, delivery status, and call events on your server.

Two separate webhook systems work together in a Vobiz WhatsApp integration. See the [Webhooks overview](/docs/whatsapp/webhooks) for the conceptual split.

| System | Direction | Purpose |
| - | - | - |
| **Inbound** | Meta → Vobiz | Meta delivers raw WhatsApp Cloud API events to a Vobiz endpoint. Platform plumbing you set once in your Meta App. |
| **Outbound** | Vobiz → your server | Vobiz forwards a signed event envelope to the endpoint URL you register here. |

All endpoints are under the base URL `https://api.vobiz.ai/api/v1/messaging`, except the inbound Meta callback which is at `https://api.vobiz.ai/api/v1/webhooks/whatsapp`.

## Inbound (Meta → Vobiz)

These endpoints are called **by Meta**, not by your application. You normally configure the callback URL and verify token once inside your Meta App. The examples below are for understanding and local simulation only.

### Verify webhook (challenge-response)

```http theme={null}
GET https://api.vobiz.ai/api/v1/webhooks/whatsapp
```

When you register the webhook in your Meta App, Meta sends a `GET` with the standard `hub.*` query params. Vobiz echoes the `hub.challenge` back as `text/plain` `200` **only when** `hub.verify_token` matches the token configured on the Vobiz side. **No auth header** is used on this endpoint.

| Param | Description |
| - | - |
| `hub.mode` | Always `subscribe`. |
| `hub.verify_token` | The verify token you set. Must match the Vobiz-side token or the request is rejected with `403`. |
| `hub.challenge` | Random string Meta expects echoed back verbatim. |

```bash Simulate Meta's verification theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=<your-verify-token>&hub.challenge=test_challenge_123"
```

```text 200 OK theme={null}
test_challenge_123
```

### Receive webhook (Meta callback)

```http theme={null}
POST https://api.vobiz.ai/api/v1/webhooks/whatsapp
```

Meta `POST`s the WhatsApp Cloud API event here. Meta signs the request with `X-Hub-Signature-256: sha256=<hex HMAC-SHA256 of the raw body, keyed by your Meta App Secret>`. Vobiz verifies that signature and enforces a **replay window**, rejecting stale or future-dated payloads. The body is the standard Meta envelope (`object` = `whatsapp_business_account`, `entry[].changes[].value` carrying `messaging_product`, `metadata`, and any of `contacts[]`, `messages[]`, `statuses[]`, `calls[]`).

```bash Simulate a delivery status callback theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/webhooks/whatsapp" \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: sha256=<hex_hmac_of_raw_body>" \
  -d '{"object":"whatsapp_business_account","entry":[{"id":"<waba_id>","changes":[{"field":"messages","value":{"messaging_product":"whatsapp","metadata":{"display_phone_number":"919876543210","phone_number_id":"<phone_number_id>"},"statuses":[{"id":"wamid.test","status":"delivered","recipient_id":"918888888888","timestamp":"1711360805"}]}}]}]}'
```

```text 200 OK theme={null}
// Empty body on success
```

After Vobiz accepts an inbound Meta event, it fans it out to your registered subscriptions as an [outbound webhook](#outbound-vobiz-your-server).

## Outbound (Vobiz → your server)

Register an HTTPS endpoint and a shared secret. Vobiz then delivers a signed event envelope to your endpoint for the three supported event types. See the [Event Reference](/docs/whatsapp/webhooks/events) for envelope and payload shapes, and the [overview](/docs/whatsapp/webhooks#verifying-the-signature) for signature verification.

**Authentication (subscription management):** `X-Auth-ID: MA_XXXXXXXX`, `X-Auth-Token: <token>`. Get credentials from [console.vobiz.ai](https://console.vobiz.ai).

<ParamField header="X-Auth-ID" type="string" required>
  Your Vobiz account ID, for example `MA_XXXXXXXX`.
</ParamField>

### Create webhook subscription

```http theme={null}
POST https://api.vobiz.ai/api/v1/messaging/webhooks
```

Register an HTTPS endpoint to receive events.

| Field | Required | Description |
| - | - | - |
| `url` | Yes | HTTPS endpoint that will receive event deliveries. |
| `secret` | Yes | Shared secret used to sign deliveries (HMAC-SHA256 → `X-Webhook-Signature`). Store it securely - it is **never** returned in any response. |

<ParamField body="url" type="string" required>
  HTTPS endpoint that will receive event deliveries.
</ParamField>

<ParamField body="secret" type="string" required>
  Shared secret used to sign deliveries (HMAC-SHA256 → `X-Webhook-Signature`). Store it securely - it is never returned in any response.
</ParamField>

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/messaging/webhooks" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: <token>" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://your-server.com/webhooks/whatsapp","secret":"your-shared-secret"}'
```

```json 201 Created theme={null}
{
  "id": "f4c1a0d2-3b6e-4a9c-8e2f-0a1b2c3d4e5f",
  "url": "https://your-server.com/webhooks/whatsapp",
  "status": "active",
  "created_at": "2026-03-25T10:00:00Z",
  "updated_at": "2026-03-25T10:00:00Z"
}
```

| Field | Type | Description |
| - | - | - |
| `id` | string (UUID) | Subscription identifier. |
| `url` | string | Your registered HTTPS endpoint. |
| `status` | string | `active` or `inactive`. |
| `created_at` | string (RFC3339, UTC) | Creation timestamp. |
| `updated_at` | string (RFC3339, UTC) | Last-update timestamp. |

### List webhook subscriptions

```http theme={null}
GET https://api.vobiz.ai/api/v1/messaging/webhooks
```

Returns the webhook subscriptions for your account. The `secret` is never included.

```bash cURL theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/messaging/webhooks" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: <token>"
```

```json 200 OK theme={null}
{
  "items": [
    {
      "id": "f4c1a0d2-3b6e-4a9c-8e2f-0a1b2c3d4e5f",
      "url": "https://your-server.com/webhooks/whatsapp",
      "status": "active",
      "created_at": "2026-03-25T10:00:00Z",
      "updated_at": "2026-03-25T10:00:00Z"
    }
  ]
}
```

### Delete webhook subscription

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/messaging/webhooks/{id}
```

Remove a subscription by its UUID. Vobiz stops delivering events to that URL.

```bash cURL theme={null}
curl -X DELETE \
  "https://api.vobiz.ai/api/v1/messaging/webhooks/f4c1a0d2-3b6e-4a9c-8e2f-0a1b2c3d4e5f" \
  -H "X-Auth-ID: MA_XXXXXXXX" \
  -H "X-Auth-Token: <token>"
```

```text 204 No Content theme={null}
// Empty body on success
```

## Delivery to your endpoint

When an event fires, Vobiz sends a `POST` to your registered `url` with:

**Headers**

| Header | Description |
| - | - |
| `X-Webhook-Signature` | Hex-encoded HMAC-SHA256 of the exact raw request body, keyed by your subscription `secret`. **No** `sha256=` prefix - just the hex digest. |
| `X-Webhook-Event` | The event type, equal to the body's `event_type`. |
| `Content-Type` | `application/json`. |

**Body** - the common envelope ([full reference](/docs/whatsapp/webhooks/events#common-envelope)):

```json theme={null}
{
  "event_id": "f4c1a0d2-3b6e-4a9c-8e2f-0a1b2c3d4e5f",
  "event_type": "message.inbound",
  "account_id": "MA_XXXXXXXX",
  "occurred_at": "2026-03-25T10:00:00Z",
  "payload": { }
}
```

The only `event_type` values emitted are `message.inbound`, `message.status` (with `status` ∈ `sent`/`delivered`/`read`/`failed`), and `call.<event>` (e.g. `call.connect`, `call.terminate`).

<Warning>
  Verify `X-Webhook-Signature` against the **raw** body before processing - compute HMAC-SHA256 with your `secret`, hex-encode, and constant-time compare. See the [signature example](/docs/whatsapp/webhooks#verifying-the-signature).
</Warning>

## Related Topics

* [Webhooks Overview →](/docs/whatsapp/webhooks)
* [Webhook Event Reference →](/docs/whatsapp/webhooks/events)
* [Send Message API →](/docs/whatsapp/api/send-message)
* [Inbox Management →](/docs/whatsapp/messaging/inbox)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.