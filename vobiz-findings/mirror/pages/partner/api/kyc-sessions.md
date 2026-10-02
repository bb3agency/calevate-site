> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# KYC Sessions

> Initiate and manage Vobiz KYC verification sessions for sub-accounts under your partner umbrella - supports both async email-link delivery and real-time in-app redirect flows, with PAN + Aadhaar OTP for individuals and PAN + GSTIN for companies.

[← Partner API Reference](/docs/partner/api)

Trigger and manage the customer KYC flow for any sub-account you've provisioned. Vobiz supports two delivery modes - async via emailed link, or real-time via in-app redirect - and runs the underlying verification (PAN + Aadhaar OTP for individuals, PAN + GSTIN for companies - no document uploads). Webhook events fire as the session progresses.

<Info>
  All Partner API requests use `X-Auth-ID` and `X-Auth-Token` headers. See [Authentication](/docs/partner/api/authentication) for details.
</Info>

## Overview

| Method | Endpoint | Description |
| - | - | - |
| POST | `/kyc-sessions` | Initiate a KYC session (email or redirect flow) |
| GET | `/kyc-sessions` | List all KYC sessions (paginated) |
| GET | `/kyc-sessions/{session_id}` | Get a single KYC session by ID |
| POST | `/kyc-sessions/{session_id}/resend` | Resend the KYC email (email flow only) |
| DELETE | `/kyc-sessions/{session_id}` | Revoke an in-flight session |

## Flow types

Pick the flow that matches your onboarding UX. The request body, response, and post-verification handoff all differ.

| `flow_type` | When to use | Extra required field | Post-verification handoff |
| - | - | - | - |
| `"email"` *(default)* | Async onboarding - customer completes KYC later from their inbox. | `customer_email` | Webhook only. |
| `"redirect"` | Real-time inline KYC during signup or checkout. | `redirect_url` | Browser redirect to your `redirect_url?session_id=…&status=…&auth_id=…` **plus** webhook. |

Both flows end with the same Vobiz-hosted KYC widget. The widget itself is internal to Vobiz - you do not call its endpoints directly; you either email a link to it, or redirect the customer to it.

## Initiate KYC Session - Email Flow

Async flow. Vobiz emails the link to `customer_email`; the session sits in `email_sent` until the customer opens it.

`POST /api/v1/partner/kyc-sessions`

```bash Email flow theme={null}
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
    ],
    "metadata": {
      "customer_ref": "TEST_001",
      "plan": "starter"
    }
  }'
```

### Response (201)

```json theme={null}
{
  "session_id": "a5f8da3c-b47f-40c3-a3e6-d2c9a0f27065",
  "account_auth_id": "MA_E31MAU98",
  "customer_email": "customer@example.com",
  "email_dispatched_to": "c***@example.com",
  "kyc_type": null,
  "status": "email_sent",
  "expires_at": "2026-05-15T19:37:01.316686Z",
  "widget_url": null,
  "kyc_link": null,
  "message": "KYC email dispatched successfully"
}
```

| Field | Description |
| - | - |
| `session_id` | Permanent identifier for this KYC session - a UUID. Store it for retrieve / resend / revoke. |
| `account_auth_id` | Echoed from the request. |
| `customer_email` | Echoed from the request. |
| `email_dispatched_to` | Masked email address where the link was sent (`c***@example.com`). |
| `kyc_type` | `null` until the customer starts the flow; then `individual` (PAN 4th char = `P`) or `company` (PAN 4th char = `C`). |
| `status` | `email_sent` on a fresh email-flow session. See [Lifecycle](#session-lifecycle). |
| `expires_at` | UTC ISO timestamp after which the link stops working. |
| `widget_url` | Always `null` for email flow (used for redirect flow only). |
| `kyc_link` | Reserved. Currently `null`. |
| `message` | Human-readable status string. Don't parse it - use `status`. |

<Note>
  Subsequent `GET` calls return the session under the field name **`id`** (UUID) - not `session_id` as in the POST response. Same value, different key. Use whichever the API returned on the request you just made.
</Note>

## Initiate KYC Session - Redirect Flow

Real-time flow. The response contains a `widget_url`; redirect the customer to it immediately. No email is sent. After the customer finishes, their browser is redirected to `redirect_url?session_id=…&status=…&auth_id=…` and a webhook fires.

`POST /api/v1/partner/kyc-sessions`

```bash Redirect flow theme={null}
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
    "expires_in_days": 14,
    "metadata": {
      "customer_ref": "TEST_001",
      "plan": "starter"
    }
  }'
```

### Response (201)

```json theme={null}
{
  "session_id": "1a0f7da5-2abb-47bf-a6c3-eb5cff7feda5",
  "account_auth_id": "MA_E31MAU98",
  "customer_email": null,
  "email_dispatched_to": null,
  "kyc_type": null,
  "status": "link_ready",
  "expires_at": "2026-05-15T19:37:01.841263Z",
  "widget_url": "https://kyc.vobiz.ai/verify?token=kst_cb1b3fda15c0df5cf58a283e47e9eee148ce0b2b87d7c6693f77296612f58f07",
  "kyc_link": null,
  "message": "KYC session created - redirect your customer to widget_url to begin."
}
```

| Field | Description |
| - | - |
| `session_id` | UUID. Store for retrieve / revoke. |
| `status` | **`link_ready`** on a fresh redirect-flow session - distinct from the email flow's `email_sent`. |
| `widget_url` | The hosted KYC widget. Redirect the customer's browser to this URL. Token portion is `kst_<64-hex>`. |
| `customer_email` / `email_dispatched_to` | Always `null` for redirect flow - no email is sent. |
| All other fields | Same semantics as the email-flow response above. |

<Warning>
  **Resend is not supported for redirect-flow sessions.** A `POST /kyc-sessions/{id}/resend` against a redirect-flow session returns `400` with message `"Resend is not available for redirect-flow sessions - no email is associated with this session."`
</Warning>

<Warning>
  **Only one active session per `account_auth_id` at a time.** Creating a new session (email or redirect) for a sub-account that already has an active session will **silently auto-revoke** the previous one. The old session's `status` flips to `revoked` at the moment the new one is created.

  This means: if you call resend / revoke on an "old" session id you stashed earlier, you may get `409 Cannot resend: session is 'revoked'` or `409 Session is already in terminal status: 'revoked'` because a newer POST replaced it. Always operate on the most recent `session_id` returned by your most recent POST.
</Warning>

## Request body - full field reference

| Field | Type | Email flow | Redirect flow | Notes |
| - | - | - | - | - |
| `account_auth_id` | string | Required | Required | Sub-account `auth_id` from [`POST /accounts`](/docs/partner/api/customers#create-customer-account). |
| `flow_type` | string | Optional | **Required** = `"redirect"` | Omit or set `"email"` for email flow. Set `"redirect"` for inline flow. |
| `customer_email` | string | **Required** | Ignored | Where the link is mailed. |
| `redirect_url` | string | Ignored | **Required** | URL the browser is sent to after the customer finishes the widget. Receives `session_id`, `status`, `auth_id` as query params. |
| `webhook_url` | string | Optional | Optional | HTTPS endpoint that receives `kyc.completed` / `kyc.failed` / `kyc.session_revoked` events. |
| `expires_in_days` | integer | Optional, default `7` | Optional, default `7` | Days until the link / widget URL expires. |
| `reminder_schedule` | array | Optional | Optional | Auto reminder emails before expiry. Each item: `{ "trigger": "days_before_expiry", "value": <int> }`. |
| `metadata` | object | Optional | Optional | Free-form key/value object echoed back on `GET` and on webhook payloads. Useful fields: `customer_ref`, `plan`. |

## List KYC Sessions

Returns a paginated list of every KYC session you've initiated.

`GET /api/v1/partner/kyc-sessions`

### Query Parameters

| Parameter | Default | Description |
| - | - | - |
| `page` | `1` | Page number (1-indexed). |
| `size` | `20` | Items per page. |
| `status` | - | Filter by status: `email_sent`, `link_ready`, `opened`, `in_progress`, `kyc_completed`, `revoked`. |
| `account_auth_id` | - | Filter to a single sub-account. |

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/kyc-sessions?page=1&size=20" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}"
```

```json theme={null}
{
  "sessions": [
    {
      "id": "09f40c53-bd09-4e4f-882b-6ebc922278de",
      "account_auth_id": "MA_YLTJEUZY",
      "customer_email": null,
      "kyc_type": null,
      "status": "opened",
      "expires_at": "2026-05-20T08:32:48.524909Z",
      "first_opened_at": "2026-05-06T08:33:01.101780Z",
      "completed_at": null,
      "webhook_url": null,
      "redirect_url": "https://console.vobiz.ai/kyc-complete",
      "reminder_schedule": [],
      "metadata": null,
      "verified_data": null,
      "created_at": "2026-05-06T08:32:48.518048Z",
      "updated_at": "2026-05-06T08:33:01.094999Z"
    }
  ],
  "total": 18,
  "page": 1,
  "size": 20
}
```

Each session in the `sessions[]` array contains the fields documented in [Session object](#session-object) below.

## Get KYC Session

Fetch the current state of a single session - useful for polling if your webhook receiver isn't reachable.

`GET /api/v1/partner/kyc-sessions/{session_id}`

```bash theme={null}
curl -X GET \
  "https://api.vobiz.ai/api/v1/partner/kyc-sessions/96df2f70-f51f-41b4-997d-0de8fdb570e8" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}"
```

```json theme={null}
{
  "id": "96df2f70-f51f-41b4-997d-0de8fdb570e8",
  "account_auth_id": "MA_M3P94TZC",
  "customer_email": "customer@example.com",
  "kyc_type": "individual",
  "status": "revoked",
  "expires_at": "2026-06-04T06:00:52.443834Z",
  "first_opened_at": "2026-05-05T06:02:17.055612Z",
  "completed_at": null,
  "webhook_url": null,
  "redirect_url": null,
  "reminder_schedule": [],
  "metadata": null,
  "verified_data": {
    "pan_type": "individual",
    "pan_number": "GTBPDXXXXX",
    "pan_name_match": true,
    "completed_steps": ["pan"],
    "pan_registered_name": "SAURABH DUBEY"
  },
  "created_at": "2026-05-05T06:00:52.435008Z",
  "updated_at": "2026-05-06T07:07:38.048734Z"
}
```

See [Session object](#session-object) for full field reference.

## Resend KYC Email

Re-sends the KYC link to the customer's email. Useful if they lost the email or filtered it as spam. **Only valid for email-flow sessions** that are still in an active status.

`POST /api/v1/partner/kyc-sessions/{session_id}/resend`

```bash theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/partner/kyc-sessions/{session_id}/resend" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}"
```

<Warning>
  **The 30-minute cooldown starts at session creation, not at the first resend.** `POST /kyc-sessions` itself dispatches the first email, so a `resend` fired immediately after creation returns `429`. The 429 response tells you exactly how long to wait:

  ```json theme={null}
  {
    "error": "HTTPError",
    "message": "Email was sent recently. Please wait 1799 seconds before resending.",
    "status_code": 429
  }
  ```
</Warning>

| Response | Meaning |
| - | - |
| `200` | Email re-dispatched (only available 30 min after the previous send). |
| `400` | Session is a redirect-flow session. Message: `"Resend is not available for redirect-flow sessions - no email is associated with this session."` |
| `409` | Session is in a terminal status (`revoked` or `kyc_completed`). Message: `"Cannot resend: session is '<status>'"`. |
| `429` | Rate-limited - at most one email send per 30 minutes per session. Message includes the exact remaining-seconds value. |

## Revoke KYC Session

Cancels an in-flight session. The hosted link / widget URL stops working immediately and Vobiz fires a `kyc.session_revoked` webhook.

`DELETE /api/v1/partner/kyc-sessions/{session_id}`

### Request Body (optional)

| Field | Type | Description |
| - | - | - |
| `reason` | string | Free-text reason. Surfaced on the webhook and in the audit log. |

```bash theme={null}
curl -X DELETE \
  "https://api.vobiz.ai/api/v1/partner/kyc-sessions/{session_id}" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Content-Type: application/json" \
  -d '{ "reason": "Wrong email - creating new session" }'
```

### Response (200)

```json theme={null}
{
  "message": "Session revoked",
  "session_id": "1a0f7da5-2abb-47bf-a6c3-eb5cff7feda5"
}
```

If the session is already in a terminal status, returns `409` with `"Session is already in terminal status: '<status>'"`.

## Session lifecycle

```
email flow:     email_sent ─┐
                            ├─► opened ─► in_progress ─► kyc_completed
redirect flow:  link_ready ─┘                  │
                                               └─► revoked
   (also: revoked at any time via DELETE
    or auto-revoked when a new session
    is created for the same account_auth_id)
```

| Status | Meaning |
| - | - |
| `email_sent` | Fresh email-flow session; awaiting customer to open the emailed link. |
| `link_ready` | Fresh redirect-flow session; `widget_url` is live and waiting for the redirect. |
| `opened` | Customer has loaded the widget at least once. |
| `in_progress` | Customer has started verification (PAN submitted). `kyc_type` is now set. |
| `kyc_completed` | All verification steps succeeded. The sub-account's `kyc_status` flips to `completed`. |
| `revoked` | Terminated - either you called `DELETE`, or you created a new session for the same account (auto-revoke). |

## Session object

The fields returned on `GET /kyc-sessions` and `GET /kyc-sessions/{session_id}`.

| Field | Type | Notes |
| - | - | - |
| `id` | string | Session identifier. |
| `account_auth_id` | string | Sub-account this session belongs to. |
| `customer_email` | string \| null | Set on email-flow sessions. |
| `kyc_type` | string \| null | `individual`, `company`, or `null` before PAN is submitted. |
| `status` | string | See [Session lifecycle](#session-lifecycle). |
| `expires_at` | string | UTC ISO timestamp. |
| `first_opened_at` | string \| null | When the customer first loaded the widget. |
| `completed_at` | string \| null | Set when `status` reaches `kyc_completed`. |
| `webhook_url` | string \| null | Echoed from the create request. |
| `redirect_url` | string \| null | For redirect-flow: where the customer is sent after finishing. |
| `reminder_schedule` | array | Echoed from the create request. |
| `metadata` | object \| null | Echoed from the create request. |
| `verified_data` | object \| null | Populated as steps complete - see [Verified data](#verified-data). |
| `created_at` | string | UTC ISO timestamp. |
| `updated_at` | string | UTC ISO timestamp. |

### Verified data

`verified_data` accumulates as the customer completes steps. Sample after a successful **individual** flow:

```json theme={null}
{
  "pan_type": "individual",
  "pan_number": "ABCPE1234F",
  "pan_name_match": true,
  "pan_registered_name": "John Doe",
  "completed_steps": ["pan", "aadhaar"],
  "aadhaar_name": "John Doe",
  "aadhaar_dob": "1990-01-15",
  "masked_aadhaar": "9942",
  "gender": "MALE",
  "address": "221B Baker Street, Mumbai, Maharashtra, 400001, India"
}
```

Sample after a successful **company** flow:

```json theme={null}
{
  "pan_type": "company",
  "completed_steps": ["pan", "gst"],
  "pan_registered_name": "ACME TECHNOLOGIES PVT LTD"
}
```

## Webhook events

Vobiz POSTs JSON to your `webhook_url` as the session progresses:

| Event | Fires when |
| - | - |
| `kyc.completed` | All verification steps succeeded. The sub-account's `kyc_status` flips to `completed`. |
| `kyc.failed` | Document invalid, name mismatch, or OTP failure. The session terminates. |
| `kyc.session_revoked` | You revoked the session via `DELETE /kyc-sessions/{session_id}`. |

<Note>
  Webhook deliveries are retried with exponential backoff on non-2xx responses. Respond with `200 OK` quickly and process the event asynchronously.
</Note>

## Verification methods

The customer's PAN determines which flow runs - the partner does not pick it.

| 4th character of PAN | Flow | Inputs |
| - | - | - |
| `P` | **Individual** | PAN + DOB → Aadhaar via DigiLocker (Govt OTP) |
| `C` | **Company** | PAN + entity name → GSTIN |

Neither flow requires the customer to upload documents - Vobiz pulls verification data directly from government APIs.

## Errors

All errors share this shape:

```json theme={null}
{
  "error": "HTTPError",
  "message": "Cannot resend: session is 'revoked'",
  "status_code": 409
}
```

Validation errors (`422`) include a `details` array with `loc` / `msg` / `type` per field, e.g.:

```json theme={null}
{
  "error": "ValidationError",
  "message": "Request validation failed",
  "details": [
    { "type": "json_invalid", "loc": ["body", 78], "msg": "JSON decode error", "input": {}, "ctx": { "error": "Invalid control character at" } }
  ],
  "status_code": 422
}
```

| Status | Cause |
| - | - |
| `400` | `POST /resend` on a redirect-flow session. |
| `401` / `403` | Missing or invalid `X-Auth-ID` / `X-Auth-Token`. |
| `404` | `account_auth_id` does not exist, or belongs to another partner. |
| `409` | Operation on a session in a terminal status - `Cannot resend: session is 'revoked'` or `Session is already in terminal status: '<status>'`. Common cause: a newer session for the same account auto-revoked this one. |
| `422` | Validation error - e.g. email flow without `customer_email`, redirect flow without `redirect_url`, malformed `reminder_schedule`, invalid JSON body. |
| `429` | `POST /resend` called within the 30-minute cooldown. |

## Related

* [Partner Integration Flow](/docs/partner/flow#step-3-initiate-kyc-session) - end-to-end walkthrough including KYC.
* [Create Customer Account](/docs/partner/api/customers#create-customer-account) - `account_auth_id` is returned here.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.