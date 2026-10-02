> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz Webhook (Callback) Configuration

> Configure Vobiz webhook (callback) URLs across resources to receive real-time event notifications for calls, conferences, recordings, and more.

<Info>
  **Quick setup:** Callbacks can be configured at multiple levels: account-wide defaults, per-application, per-trunk, or per-call. More specific configurations override broader ones.
</Info>

## Configuring Callbacks

### Callback URL Requirements

* ✓ Must use HTTPS (not HTTP)
* ✓ Must be publicly accessible (not localhost)
* ✓ Must respond within 3 seconds
* ✓ Must return HTTP 200 status code
* ✓ Should handle POST requests
* ✓ Should accept `application/x-www-form-urlencoded` content type (form data)

### Callback Configuration Hierarchy

Callbacks are resolved in this order (most specific to least specific):

<Steps>
  <Step title="Per-Call Callback">
    Callback URL specified when making a call.

    `status_url` parameter in Make Call API
  </Step>

  <Step title="Application Callback">
    Callback configured in Application settings.

    `callback_url` in Application object
  </Step>

  <Step title="Trunk Callback">
    Callback configured on SIP Trunk.

    `status_callback` in Trunk configuration
  </Step>

  <Step title="Account Default">
    Account-wide default callback URL.

    `default_callback_url` in Account settings
  </Step>
</Steps>

## Application Callbacks

### Configure Application Callback

Set up callbacks when creating or updating an application:

```json Create Application with Callback theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/applications/

{
  "name": "Customer Support App",
  "callback_url": "https://api.yourapp.com/webhooks/vobiz/calls",
  "callback_method": "POST",
  "fallback_callback_url": "https://backup.yourapp.com/webhooks/vobiz/calls",
  "callback_events": [
    "Ring",
    "StartApp",
    "Hangup",
    "recording.completed"
  ]
}
```

### Application Callback Parameters

| Field | Type | Required | Description |
| - | - | - | - |
| `callback_url` | string | No | HTTPS URL to receive callbacks |
| `callback_method` | string | No | HTTP method (POST or GET). Default: POST |
| `fallback_callback_url` | string | No | Fallback URL if primary callback fails |
| `callback_events` | array | No | Array of event types to receive. If empty, receives all events. |

## Trunk Callbacks

### Configure Trunk Status Callback

Receive callbacks for all calls through a specific trunk:

```json Update Trunk with Callback theme={null}
PUT https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks/{trunk_id}

{
  "status_callback": "https://api.yourapp.com/webhooks/trunk-events",
  "status_callback_method": "POST",
  "status_callback_events": [
    "Ring",
    "StartApp",
    "Hangup",
    "call.failed"
  ]
}
```

### Trunk Callback Use Cases

* **Call Tracking:** Monitor all calls through a specific trunk
* **Department Routing:** Different callbacks for sales vs support trunks
* **Billing Integration:** Track usage per trunk for chargeback
* **Quality Monitoring:** Collect metrics for specific carriers/trunks

## Call-Level Callbacks

### Per-Call Callback Configuration

Override application/trunk callbacks for specific calls:

```json Make Call with Custom Callback theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/calls/

{
  "from": "+14155551234",
  "to": "+14155555678",
  "status_url": "https://api.yourapp.com/webhooks/specific-call",
  "status_method": "POST"
}
```

## Callback Authentication

To verify that callbacks originate from Vobiz, configure shared secrets and verify HMAC signatures. See [Callbacks](/docs/concepts/callbacks#security-considerations) for verification code examples.

## Testing Callbacks

For local development, use a tunneling service like [ngrok](https://ngrok.com) to expose your local server publicly:

```bash theme={null}
ngrok http 3000
```

Then use the ngrok URL (e.g. `https://abc123.ngrok.io/webhooks/vobiz`) as your callback URL.

<Tip>
  Vobiz retries failed callbacks (non-200 responses) up to 3 times with exponential backoff. Make your callback handlers **idempotent** to handle duplicate deliveries safely.
</Tip>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.