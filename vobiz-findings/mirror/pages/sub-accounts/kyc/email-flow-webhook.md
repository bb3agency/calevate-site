> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# KYC Email Flow with Webhook

> Start a hosted sub-account KYC via email link and register a webhook to receive status updates - create the session, the events Vobiz POSTs, and how to verify the HMAC signature.

How a parent account starts a hosted KYC for one of its sub-accounts via **email link**, and registers a **webhook** to receive status updates.

## Flow

<Steps>
  <Step title="Create the session">
    Parent calls **Create KYC Session** with `flow_type: "email"`, the customer's email, and a `webhook_url`.
  </Step>

  <Step title="Vobiz emails the link">
    Vobiz emails the customer a signed link to the Vobiz-hosted KYC widget.
  </Step>

  <Step title="Customer completes KYC">
    Customer completes KYC in the widget.
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
  "flow_type": "email",
  "customer_email": "customer@example.com",
  "webhook_url": "https://your-app.example.com/kyc/webhook",
  "expires_in_days": 30,
  "reminder_schedule": [
    { "trigger": "days_before_expiry", "value": 3 }
  ],
  "metadata": { "your_ref": "anything you want echoed back" }
}
```

| Field | Required | Notes |
| - | - | - |
| `flow_type` | yes | `"email"` for this flow (default). |
| `customer_email` | yes (email flow) | Where the KYC link is sent. Falls back to the sub-account's email if omitted. |
| `webhook_url` | no but **needed for callbacks** | HTTPS endpoint that receives the events below. No `webhook_url` = no callbacks. |
| `expires_in_days` | no | Days before the link expires. Defaults to `7` (the example above overrides it to `30`). |
| `reminder_schedule` | no | Reminder emails before expiry (email flow only), e.g. 3 days before. Mirrors the partner [KYC Sessions](/docs/partner/api/kyc-sessions) endpoint. |
| `metadata` | no | Arbitrary JSON, echoed back in every webhook payload. Mirrors the partner [KYC Sessions](/docs/partner/api/kyc-sessions) endpoint. |

<Note>
  `account_auth_id` in the schema is set automatically from the path `sub_auth_id` for this flow - you don't need to send it.
</Note>

**Response `201`:**

```json theme={null}
{
  "session_id": "b6a1f3c2-7a44-4e2b-9c11-...",
  "account_auth_id": "SA_xxxx",
  "customer_email": "customer@example.com",
  "email_dispatched_to": "c***@example.com",
  "status": "email_sent",
  "expires_at": "2026-07-04T08:51:10Z",
  "widget_url": null,
  "message": "KYC email dispatched successfully"
}
```

`widget_url` is only populated for `flow_type: "redirect"`; `kyc_link` is returned only in dev for testing without email.

## 2. Webhook events you'll receive

Vobiz POSTs JSON to your `webhook_url` as the session progresses:

| Event | When |
| - | - |
| `kyc.initiated` | Session created / email dispatched. |
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
  "customer_email": "customer@example.com",
  "kyc_type": "individual",
  "session_status": "kyc_completed",
  "metadata": { "your_ref": "anything you want echoed back" },
  "created_at": "2026-06-04T08:40:00+00:00",
  "updated_at": "2026-06-04T08:51:10+00:00"
}
```

## 3. Verify the signature

Every delivery includes an HMAC signature header:

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

Copy-paste starter - create an email-flow session and register your webhook in one call:

```bash theme={null}
curl -X POST "https://api.vobiz.ai/api/v1/sub-accounts/SA_XXXX/kyc-sessions" \
  -H "X-Auth-ID: MA_XXXX" \
  -H "X-Auth-Token: <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "flow_type": "email",
    "customer_email": "customer@example.com",
    "webhook_url": "https://your-app.example.com/kyc/webhook"
  }'
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.