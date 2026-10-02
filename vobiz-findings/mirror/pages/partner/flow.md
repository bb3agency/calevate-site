> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Partner Integration Flow

> Walk through a full Vobiz partner integration - provision a customer, transfer balance, complete KYC, create a SIP trunk, and monitor live CDRs end-to-end.

[← Partner Overview](/docs/partner)

A step-by-step integration guide demonstrating the full lifecycle of a customer on your platform - from provisioning and balance transfer to KYC, trunk creation, and CDR monitoring.

## Authentication Setup

All Partner API calls require your Master credentials. Store these securely in your backend.

```http theme={null}
X-Auth-ID: {your_partner_id}
X-Auth-Token: {your_auth_token}
```

## Step 1 - Create customer account

Provision a new SIP-enabled account under your partner umbrella.

`POST https://api.vobiz.ai/api/v1/partner/accounts`

| Field | Required | Description |
| - | - | - |
| `name` | Yes | Customer's full name |
| `email` | Yes | Customer's email - KYC link is sent here |
| `phone` | Yes | E.164 format, e.g. `+919876543210` |
| `password` | Yes | Min 8 chars, must include number and special char |
| `company` | No | Legal company or business name |
| `country` | Yes | ISO 2-letter code, e.g. `IN` |

```bash theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/partner/accounts" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "John Doe",
    "email": "john@example.com",
    "phone": "+919876543210",
    "password": "SecurePass123!",
    "company": "Acme Corp",
    "country": "IN"
  }'
```

```json theme={null}
{
  "auth_id": "MA_XXXXXXXX",
  "auth_token": "<redacted>",
  "name": "John Doe",
  "email": "john@example.com",
  "status": "active",
  "balance": 0.00,
  "currency": "INR",
  "country": "IN",
  "created_at": "2026-03-25T10:00:00Z"
}
```

<Warning>
  **Save both `auth_id` and `auth_token`.** The `auth_id` is used in every partner API call for this customer. The `auth_token` is the customer's own credential - used when calling the Customer API on their behalf.
</Warning>

## Step 2 - Transfer balance to customer

When you call the transfer endpoint, Vobiz atomically debits the amount from your partner master balance and credits it to the customer's wallet.

* **Your Master Balance** - debited by the transfer amount (e.g. `-₹500.00`).
* **Customer Wallet** - credited by the same amount (e.g. `+₹500.00`).

`POST https://api.vobiz.ai/api/v1/partner/accounts/{customer_auth_id}/transfer-balance`

```bash theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/partner/accounts/{customer_auth_id}/transfer-balance" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": 500.00,
    "currency": "INR",
    "description": "April recharge"
  }'
```

```json theme={null}
{
  "transaction_id": "txn_aabbccdd1234",
  "from_account": "PA_XXXXXXXX",
  "to_account": "MA_XXXXXXXX",
  "amount": 500.00,
  "currency": "INR",
  "description": "April recharge",
  "status": "completed",
  "partner_balance_after": 47750.00,
  "customer_balance_after": 2950.00,
  "timestamp": "2026-03-25T11:00:00Z"
}
```

## Step 3 - Initiate KYC session

Vobiz supports two ways to initiate KYC. Pick the one that matches your onboarding UX:

* **Email flow** *(default, async)* - Vobiz emails the customer a link to a hosted KYC widget. They complete verification later from their inbox.
* **Redirect flow** *(real-time)* - Vobiz returns a `widget_url` in the response. You redirect the customer to it during signup; their browser comes back to your `redirect_url` after verification.

Full request/response reference: [KYC Sessions API](/docs/partner/api/kyc-sessions).

`POST https://api.vobiz.ai/api/v1/partner/kyc-sessions`

### Email flow

```bash theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/partner/kyc-sessions" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "account_auth_id": "MA_XXXXXXXX",
    "flow_type": "email",
    "customer_email": "customer@example.com",
    "webhook_url": "https://yourapp.com/kyc-webhook",
    "expires_in_days": 14,
    "reminder_schedule": [
      { "trigger": "days_before_expiry", "value": 3 },
      { "trigger": "days_before_expiry", "value": 1 }
    ]
  }'
```

```json theme={null}
{
  "session_id": "a5f8da3c-b47f-40c3-a3e6-d2c9a0f27065",
  "account_auth_id": "MA_XXXXXXXX",
  "customer_email": "customer@example.com",
  "email_dispatched_to": "c***@example.com",
  "kyc_type": null,
  "status": "email_sent",
  "expires_at": "2026-05-28T10:00:00Z",
  "widget_url": null,
  "kyc_link": null,
  "message": "KYC email dispatched successfully"
}
```

<Warning>
  `POST /kyc-sessions` itself sends the first email, which starts a **30-minute resend cooldown**. Calling `/resend` immediately after creation returns `429`. Also, creating a new session for an `account_auth_id` that already has an active one **silently auto-revokes** the old session - always act on the most recent `session_id`. See [KYC Sessions](/docs/partner/api/kyc-sessions) for the full edge-case matrix.
</Warning>

### Redirect flow

```bash theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/partner/kyc-sessions" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "account_auth_id": "MA_XXXXXXXX",
    "flow_type": "redirect",
    "redirect_url": "https://yourapp.com/kyc-complete",
    "webhook_url": "https://yourapp.com/kyc-webhook",
    "expires_in_days": 14
  }'
```

```json theme={null}
{
  "session_id": "1a0f7da5-2abb-47bf-a6c3-eb5cff7feda5",
  "account_auth_id": "MA_XXXXXXXX",
  "customer_email": null,
  "email_dispatched_to": null,
  "kyc_type": null,
  "status": "link_ready",
  "expires_at": "2026-05-28T10:00:00Z",
  "widget_url": "https://kyc.vobiz.ai/verify?token=kst_cb1b3fda15c0df5cf58a283e47e9eee148ce0b2b87d7c6693f77296612f58f07",
  "kyc_link": null,
  "message": "KYC session created - redirect your customer to widget_url to begin."
}
```

A fresh redirect-flow session starts at **`link_ready`** (not `email_sent`). Redirect the customer's browser to `widget_url` immediately. After verification, their browser is sent back to:

```
https://yourapp.com/kyc-complete?session_id=1a0f7da5-…&status=kyc_completed&auth_id=MA_XXXXXXXX
```

<Warning>
  **Treat the redirect return params as a UI hint, not proof of completion.** Query params can be spoofed. When your `redirect_url` is hit, confirm the real outcome before unlocking anything - either trust the `kyc.completed` webhook (below) or call `GET /kyc-sessions/{session_id}` and check `status` server-side.
</Warning>

<Note>
  `expires_in_days` defaults to **7** if omitted. The examples above override it to 14.
</Note>

## Step 4 - Customer completes KYC

The customer completes verification on the Vobiz-hosted widget (either by clicking the email link, or via the redirect URL).

* **Individual** (PAN 4th char = `P`) - PAN + DOB → Aadhaar via DigiLocker (Govt OTP)
* **Company** (PAN 4th char = `C`) - PAN + entity name → GSTIN

### Webhook events

Vobiz POSTs JSON to your `webhook_url` as the session progresses:

* **`kyc.completed`** - All steps verified. The sub-account's `kyc_status` flips to `completed`.
* **`kyc.failed`** - Document invalid, name mismatch, or OTP failure. The session terminates.
* **`kyc.session_revoked`** - You revoked the session (or a newer session auto-revoked it).

A `kyc.completed` payload echoes your `metadata` and the verified data:

```json theme={null}
{
  "event": "kyc.completed",
  "session_id": "1a0f7da5-2abb-47bf-a6c3-eb5cff7feda5",
  "account_auth_id": "MA_XXXXXXXX",
  "kyc_type": "individual",
  "status": "kyc_completed",
  "metadata": { "customer_ref": "TEST_001", "plan": "starter" },
  "verified_data": {
    "pan_type": "individual",
    "pan_name_match": true,
    "completed_steps": ["pan", "aadhaar"]
  }
}
```

### Verify and handle the webhook

Always re-confirm the session server-side before granting access - never trust the POST body alone. Respond `200` fast and process asynchronously so Vobiz doesn't retry.

```python theme={null}
from fastapi import FastAPI, Request
import httpx

app = FastAPI()
BASE = "https://api.vobiz.ai/api/v1/partner"
HEADERS = {"X-Auth-ID": "{your_partner_id}", "X-Auth-Token": "{your_auth_token}"}

@app.post("/kyc-webhook")
async def kyc_webhook(req: Request):
    event = await req.json()
    session_id = event["session_id"]

    # Re-fetch the session from Vobiz - the body could be spoofed or stale.
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BASE}/kyc-sessions/{session_id}", headers=HEADERS)
    session = r.json()

    if session["status"] == "kyc_completed":
        # idempotent: only unlock once
        activate_customer(session["account_auth_id"])
    elif session["status"] == "revoked":
        handle_revoked(session["account_auth_id"])

    return {"ok": True}  # 200 quickly; do heavy work in a background task
```

<Note>
  Webhook deliveries retry with exponential backoff on any non-2xx response, so make your handler **idempotent** - the same `kyc.completed` may arrive more than once.
</Note>

## Managing KYC sessions

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/kyc-sessions?page=1&size=20" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}"
```

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/kyc-sessions/{session_id}" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}"
```

```bash theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/partner/kyc-sessions/{session_id}/resend" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}"
```

```bash theme={null}
curl -X DELETE \
  "https://api.vobiz.ai/api/v1/partner/kyc-sessions/{session_id}" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Content-Type: application/json" \
  -d '{ "reason": "Wrong email" }'
```

## Transactions

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/accounts/{customer_auth_id}/transactions?page=1&per_page=20" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}"
```

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/accounts/{customer_auth_id}/transactions?from_date=2026-03-01&to_date=2026-03-31&per_page=100" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}"
```

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/accounts/{customer_auth_id}/transactions?transaction_type=recharge&per_page=50" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}"
```

## CDRs (Call History)

### Partner view

You (the partner) look up any customer's call history from your side.

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/accounts/{customer_auth_id}/cdrs?call_direction=inbound&status=answered&min_duration=10" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}"
```

### Customer view

The customer calls this endpoint using their own credentials.

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/Account/{customer_auth_id}/cdrs?status=failed&hangup_cause=NO_ANSWER" \
  -H "X-Auth-ID: {customer_auth_id}" \
  -H "X-Auth-Token: {customer_auth_token}"
```

## Phone numbers (partner view)

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/accounts/{customer_auth_id}/numbers?page=1&per_page=20" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}"
```

## Profile & dashboard

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/me" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}"
```

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/dashboard" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}"
```

## Customer API

<Info>
  These endpoints are called using the **customer's own credentials** - not yours as the partner. The `auth_id` and `auth_token` are returned when you create the customer account (Step 1).

  * **Base URL** - `https://api.vobiz.ai/api/v1/Account/{customer_auth_id}/...`
  * **Auth headers** - `X-Auth-ID: {customer_auth_id}` + `X-Auth-Token: {customer_auth_token}`
</Info>

### Inventory Numbers (Browse Available)

Lists phone numbers available to purchase - not yet assigned to any account.

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/Account/{customer_auth_id}/inventory/numbers?country=IN&page=1&per_page=25" \
  -H "X-Auth-ID: {customer_auth_id}" \
  -H "X-Auth-Token: {customer_auth_token}"
```

### Release a phone number

Returns a number from the customer's account back to inventory. **Permanent - cannot be undone.**

```bash theme={null}
curl -X DELETE \
  "https://api.vobiz.ai/api/v1/Account/{customer_auth_id}/numbers/+918071387149" \
  -H "X-Auth-ID: {customer_auth_id}" \
  -H "X-Auth-Token: {customer_auth_token}"
```

### Create a SIP trunk

Vobiz auto-generates a unique SIP domain for the trunk in the format: `{trunk_id}.sip.vobiz.ai`

```bash theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/Account/{customer_auth_id}/trunks" \
  -H "X-Auth-ID: {customer_auth_id}" \
  -H "X-Auth-Token: {customer_auth_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My SIP Trunk",
    "trunk_status": "enabled",
    "secure": false,
    "trunk_direction": "outbound",
    "concurrent_calls_limit": 10,
    "cps_limit": 5,
    "transport": "udp"
  }'
```

```json theme={null}
{
  "trunk_id": "aabbccdd-1234-5678-90ab-cdef12345678",
  "auth_id": "MA_XXXXXXXX",
  "name": "My SIP Trunk",
  "trunk_domain": "aabbccdd-1234-5678-90ab-cdef12345678.sip.vobiz.ai",
  "trunk_status": "enabled",
  "secure": false,
  "trunk_direction": "outbound",
  "concurrent_calls_limit": 10,
  "cps_limit": 5,
  "transport": "udp",
  "created_at": "2026-03-25T14:09:12Z",
  "updated_at": "2026-03-25T14:09:12Z"
}
```

Save the `trunk_id` - it is required for all trunk update, delete, and lookup operations.

***

## Build the full onboarding with an AI agent

<Prompt description="End-to-end customer onboarding - create account, transfer balance, fire KYC, all wired up." icon="handshake" actions={["copy", "cursor"]}>
  Using the Vobiz MCP at `https://vobiz.ai/docs/mcp`:

  1. Read the `vobiz-partner-api` skill from `mintlify://skills/partner-api`.
  2. Ask me for: customer's `name`, `email`, `phone`, `country`, my partner `X-Auth-ID`/`X-Auth-Token`, the initial `amount` (INR) to credit them, and the KYC `webhook_url` where I want to receive `kyc.completed` / `kyc.failed` events.
  3. Pick a language (default Python + httpx; offer Node + axios as alternative). Generate `onboard_customer.py` that does in order:
     * `POST /api/v1/partner/accounts` to create the customer account. Capture `auth_id` and `auth_token` from the response.
     * `POST /api/v1/partner/accounts/{customer_auth_id}/transfer-balance` with the credit amount. Validate `partner_balance_after` is non-negative.
     * `POST /api/v1/partner/kyc-sessions` with `account_auth_id`, `webhook_url`, `expires_in_days: 14`, and a two-stage reminder schedule.
     * Print the `session_id` and `expires_at`.
  4. Add a `--dry-run` flag that prints the requests without firing.
  5. Tell me how the eKYC flow works (PAN+Aadhaar OTP for individuals, PAN+GSTIN for companies - no document uploads) and what webhook events to expect.
</Prompt>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.