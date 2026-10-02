> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Webhook Events Reference

> Reference for every outbound WhatsApp webhook event Vobiz delivers to your server - the common envelope, the three real event types (message.inbound, message.status, call.*), and sample payloads.

[← Back to Webhooks](/docs/whatsapp/webhooks)

This page documents the **outbound** events that Vobiz delivers to your server (Vobiz → your `url`). For the inbound Meta → Vobiz contract and how to register a subscription, see the [Webhooks overview](/docs/whatsapp/webhooks) and the [Webhooks API](/docs/whatsapp/api/webhooks).

All outbound webhooks are HTTP `POST` requests with `Content-Type: application/json`, signed with the `X-Webhook-Signature` header (see [Verifying signatures](/docs/whatsapp/webhooks#verifying-the-signature)).

## Common Envelope

Every outbound webhook body is the same envelope. Only the `payload` object differs per event type.

| Field | Type | Description |
| - | - | - |
| `event_id` | string (UUID) | Unique identifier for this delivery. Use it to deduplicate retries. |
| `event_type` | string | One of `message.inbound`, `message.status`, or `call.<event>`. |
| `account_id` | string | Your Vobiz account ID, e.g. `MA_XXXXXXXX`. |
| `occurred_at` | string (RFC3339, UTC) | When Vobiz processed the event. |
| `payload` | object | Event-specific data - the relevant slice of the underlying WhatsApp Cloud API payload. |

```json Envelope shape theme={null}
{
  "event_id": "f4c1a0d2-3b6e-4a9c-8e2f-0a1b2c3d4e5f",
  "event_type": "message.inbound",
  "account_id": "MA_XXXXXXXX",
  "occurred_at": "2026-03-25T10:00:00Z",
  "payload": { }
}
```

The `X-Webhook-Event` request header carries the same value as `event_type`, so you can route on the header before parsing the body.

<Note>
  There are exactly **three** outbound event types: `message.inbound`, `message.status`, and `call.<event>`. There is no separate `message.delivered`, `message.read`, `message.sent`, or `message.failed` event - those are delivery states reported inside `message.status`.
</Note>

## message.inbound

An end customer sent a message to your WhatsApp number. This is the event you build conversational experiences and auto-replies on.

The `payload` contains the WhatsApp Cloud API change `value`: the channel `metadata`, the sender in `contacts[]`, and the message in `messages[]` (with the WhatsApp message id `wamid` and the type-specific content).

```json message.inbound theme={null}
{
  "event_id": "f4c1a0d2-3b6e-4a9c-8e2f-0a1b2c3d4e5f",
  "event_type": "message.inbound",
  "account_id": "MA_XXXXXXXX",
  "occurred_at": "2026-03-25T10:00:00Z",
  "payload": {
    "object": "whatsapp_business_account",
    "entry": [
      {
        "id": "<waba_id>",
        "changes": [
          {
            "field": "messages",
            "value": {
              "messaging_product": "whatsapp",
              "metadata": {
                "display_phone_number": "919876543210",
                "phone_number_id": "<phone_number_id>"
              },
              "contacts": [
                { "wa_id": "918888888888", "profile": { "name": "Asha" } }
              ],
              "messages": [
                {
                  "from": "918888888888",
                  "id": "wamid.HBgMOTE4ODg4ODg4ODg4FQIAEhg..",
                  "timestamp": "1711360800",
                  "type": "text",
                  "text": { "body": "Hi, is my order shipped?" }
                }
              ]
            }
          }
        ]
      }
    ]
  }
}
```

### Message types

The `messages[].type` field reflects the WhatsApp message type, e.g. `text`, `image`, `video`, `audio`, `document`, `location`, `contacts`, `button`, `interactive`. Text content is in `text.body`; media and interactive messages carry their own type-specific object alongside.

## message.status

A delivery-status update for a message **you** sent. The `payload` contains the change `value` with a `statuses[]` array; each entry has the WhatsApp message id (`id` = the `wamid` returned when you sent the message), the `recipient_id`, and a `status`.

`status` is one of:

| Status | Meaning |
| - | - |
| `sent` | Accepted by WhatsApp and on its way. |
| `delivered` | Reached the recipient's device (double gray ticks). |
| `read` | Opened by the recipient (blue ticks; only if read receipts are enabled). |
| `failed` | Delivery failed. |

<Note>
  `delivered` and `read` are **values of `status`** inside a single `message.status` event - they are not separate event types. Use the `id` to correlate the update back to the message you sent.
</Note>

```json message.status theme={null}
{
  "event_id": "a1b2c3d4-5e6f-7a8b-9c0d-1e2f3a4b5c6d",
  "event_type": "message.status",
  "account_id": "MA_XXXXXXXX",
  "occurred_at": "2026-03-25T10:00:05Z",
  "payload": {
    "object": "whatsapp_business_account",
    "entry": [
      {
        "id": "<waba_id>",
        "changes": [
          {
            "field": "messages",
            "value": {
              "messaging_product": "whatsapp",
              "metadata": {
                "display_phone_number": "919876543210",
                "phone_number_id": "<phone_number_id>"
              },
              "statuses": [
                {
                  "id": "wamid.HBgMOTE4ODg4ODg4ODg4FQIAERg...",
                  "status": "delivered",
                  "recipient_id": "918888888888",
                  "timestamp": "1711360805"
                }
              ]
            }
          }
        ]
      }
    ]
  }
}
```

## call.\<event>

WhatsApp Business Calling lifecycle events. The `event_type` suffix mirrors Meta's call event, so values you may receive include:

* `call.connect` - a call is being set up (carries the SDP offer in the session).
* `call.status_change` - the call status changed (e.g. ringing → accepted).
* `call.terminate` - the call ended.

The `payload` contains the change `value` with a `calls[]` array. Each call entry includes `id`, `from`, `to`, `event`, `status`, `direction`, and (for `connect`) a `session` with the SDP.

```json call.connect theme={null}
{
  "event_id": "9c8b7a6d-5e4f-3a2b-1c0d-9e8f7a6b5c4d",
  "event_type": "call.connect",
  "account_id": "MA_XXXXXXXX",
  "occurred_at": "2026-03-25T10:01:00Z",
  "payload": {
    "object": "whatsapp_business_account",
    "entry": [
      {
        "id": "<waba_id>",
        "changes": [
          {
            "field": "calls",
            "value": {
              "messaging_product": "whatsapp",
              "metadata": {
                "display_phone_number": "919876543210",
                "phone_number_id": "<phone_number_id>"
              },
              "calls": [
                {
                  "id": "wacid.HBgMOTE...",
                  "from": "918888888888",
                  "to": "919876543210",
                  "timestamp": "1711360860",
                  "event": "connect",
                  "status": "ringing",
                  "direction": "USER_INITIATED",
                  "session": { "sdp_type": "offer", "sdp": "v=0\r\n..." }
                }
              ]
            }
          }
        ]
      }
    ]
  }
}
```

## Handling tips

* **Deduplicate** on `event_id` - Vobiz may retry a delivery, and the underlying WhatsApp event can repeat.
* **Verify the signature** on every request before trusting the body (see the [overview](/docs/whatsapp/webhooks#verifying-the-signature)).
* **Respond fast** - return `200` quickly and process asynchronously; Vobiz uses a short per-delivery timeout.

## Related Topics

* [Webhooks Overview →](/docs/whatsapp/webhooks)
* [Webhooks API →](/docs/whatsapp/api/webhooks)
* [Send Message API →](/docs/whatsapp/api/send-message)
* [Inbox Management →](/docs/whatsapp/messaging/inbox)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.