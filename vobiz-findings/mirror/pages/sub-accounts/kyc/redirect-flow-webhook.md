> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# KYC Redirect Flow with Webhook

> Start a hosted sub-account KYC via redirect - get a widget_url back, redirect the customer yourself, and register a webhook for status updates. Same endpoint and webhooks as the email flow.

How a parent account starts a hosted KYC for one of its sub-accounts via **redirect** (no email - you get a widget URL back and redirect the customer yourself), and registers a **webhook** to receive status updates.

This is the same endpoint and the same webhook behaviour as the [email flow](/docs/sub-accounts/kyc/email-flow-webhook) - the only differences are `flow_type: "redirect"`, `customer_email` is not required, and the response returns a `widget_url` instead of emailing a link.

## Flow

<Steps>
  <Step title="Create the session">
    Parent calls **Create KYC Session** with `flow_type: "redirect"` and a `webhook_url`.
  </Step>

  <Step title="Vobiz returns a widget_url">
    Vobiz returns a `widget_url`. You redirect the customer to it.
  </Step>

  <Step title="Customer completes KYC">
    Customer completes KYC in the Vobiz-hosted widget.
  </Step>

  <Step title="Receive webhook events">
    Vobiz POSTs **webhook events** to your `webhook_url` at each stage (initiated → submitted → completed/failed).
  </Step>
</Steps>

## 1. Create the KYC session (register the webhook)

```text theme={null}
POST https://api.vobiz.ai/api/v1/sub-accounts/{sub_auth_id}/kyc-sessions
```

<Info>
  **Auth:** parent main account - `X-Auth-ID: MA_xxxx` + `X-Auth-Token: <token>` (or `Authorization: Bearer <JWT>`). The `sub_auth_id` path param (`SA_xxxx`) identifies the sub-account being verified.
</Info>

**Body:**

```json theme={null}
{
  "flow_type": "redirect",
  "webhook_url": "https://your-app.example.com/kyc/webhook",
  "redirect_url": "https://your-app.example.com/kyc/done",
  "expires_in_days": 30,
  "metadata": { "your_ref": "anything you want echoed back" }
}
```

| Field | Required | Notes |
| - | - | - |
| `flow_type` | yes | `"redirect"` for this flow. |
| `webhook_url` | no but **needed for callbacks** | HTTPS endpoint that receives the events below. No `webhook_url` = no callbacks. |
| `redirect_url` | yes (redirect flow) | Where the widget sends the customer after they finish KYC. Required for `flow_type: "redirect"`. |
| `customer_email` | no | Not required for redirect flow (no email is sent). |
| `expires_in_days` | no | Days before the link expires. Defaults to `7` (the example above overrides it to `30`). |
| `metadata` | no | Arbitrary JSON, echoed back in every webhook payload. Mirrors the partner [KYC Sessions](/docs/partner/api/kyc-sessions) endpoint. |

<Note>
  `account_auth_id` in the schema is set automatically from the path `sub_auth_id` for this flow - you don't need to send it.
</Note>

**Response `201`:**

```json theme={null}
{
  "session_id": "b6a1f3c2-7a44-4e2b-9c11-...",
  "account_auth_id": "SA_xxxx",
  "customer_email": null,
  "status": "link_ready",
  "expires_at": "2026-07-04T08:51:10Z",
  "widget_url": "https://kyc.vobiz.ai/verify?token=kst_cb1b3fda...",
  "message": "Redirect your customer to widget_url to begin."
}
```

**Redirect the customer to `widget_url`** to start KYC. (`kyc_link` is only returned in dev for testing.)

## 2. Webhook events you'll receive

Identical to the email flow - Vobiz POSTs JSON to your `webhook_url` as the session progresses:

| Event | When |
| - | - |
| `kyc.initiated` | Session created. |
| `kyc.submitted` | Customer submitted their documents. |
| `kyc.completed` | Verification passed. |
| `kyc.failed` | Verification failed. |
| `kyc.session_expired` | Link expired before completion. |
| `kyc.session_revoked` | Session manually revoked. |

**Payload:**

```json theme={null}
{
  "event": "kyc.completed",
  "timestamp": "2026-06-04T08:51:10Z",
  "session_id": "b6a1f3c2-7a44-4e2b-9c11-...",
  "account_auth_id": "SA_xxxx",
  "customer_email": null,
  "kyc_type": "individual",
  "session_status": "kyc_completed",
  "metadata": { "your_ref": "anything you want echoed back" },
  "created_at": "2026-06-04T08:40:00+00:00",
  "updated_at": "2026-06-04T08:51:10+00:00"
}
```

## 3. Verify the signature

Every delivery includes an HMAC signature header (same as email flow):

```text theme={null}
X-Vobiz-Signature: sha256=<hex>
```

* Algorithm: **HMAC-SHA256** over the raw request body.
* Secret: your **parent account's `auth_token`**.

Verify (Python):

```python theme={null}
import hmac, hashlib

def verify(raw_body: bytes, header: str, auth_token: str) -> bool:
    expected = "sha256=" + hmac.new(auth_token.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)
```

Return `2xx` to acknowledge. Failed deliveries are retried with exponential backoff.

## cURL example

Copy-paste starter - create a redirect-flow session with both your webhook and redirect URLs in one call:

```bash theme={null}
curl -X POST "https://api.vobiz.ai/api/v1/sub-accounts/SA_XXXX/kyc-sessions" \
  -H "X-Auth-ID: MA_XXXX" \
  -H "X-Auth-Token: <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "flow_type": "redirect",
    "webhook_url": "https://your-app.example.com/kyc/webhook",
    "redirect_url": "https://your-app.example.com/kyc/done"
  }'
```

## Email vs Redirect

Same endpoint, same webhooks.

* **`email`** → Vobiz emails the customer the link (needs `customer_email`). See the [email flow](/docs/sub-accounts/kyc/email-flow-webhook).
* **`redirect`** → you get `widget_url` back and redirect the customer yourself (no email).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.