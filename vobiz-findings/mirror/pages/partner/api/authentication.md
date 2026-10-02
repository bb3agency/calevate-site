> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Partner API Authentication

> Authenticate against the Vobiz Partner API using permanent X-Auth headers for server integrations or short-lived JWT tokens for interactive sessions.

[← Partner API Reference](/docs/partner/api)

The Partner API supports two authentication mechanisms. Header-based authentication is recommended for all programmatic integrations. JWT login is available for interactive sessions only.

<Info>
  All Partner API requests must include `X-Auth-ID` and `X-Auth-Token` headers. The base URL is `{BASE}` which resolves to `https://api.vobiz.ai/api/v1/partner`.
</Info>

## Overview

Every Partner API request requires your Partner credentials, obtained from the [Vobiz Partner Console](https://console.vobiz.ai). There are two ways to authenticate:

### Header-Based Auth (Recommended)

Pass `X-Auth-ID` and `X-Auth-Token` on every request. Best for server-to-server integrations, automation scripts, and production systems. Credentials never expire.

### JWT Login (Interactive sessions)

Exchange email + password for a temporary JWT access token. Expires after a set period. Suitable for dashboard UIs or short-lived sessions.

## Two credential scopes - partner vs customer

The Partner API and the Customer (voice) API use the **same header scheme** (`X-Auth-ID` + `X-Auth-Token`) but **different credentials**. Sending the wrong pair against the wrong base path returns `401`/`403`.

| You are calling | Base path | `X-Auth-ID` | `X-Auth-Token` |
| - | - | - | - |
| **Partner operations** (create customers, transfer balance, KYC sessions, per-customer CDRs/transactions/numbers) | `/api/v1/partner/*` | Your partner `auth_id` (e.g. `PA_…`) | Your partner token |
| **Voice / account operations on a customer's behalf** (trunks, applications, numbers, placing calls) | `/api/v1/Account/{customer_auth_id}/*` | The **customer's** `auth_id` (e.g. `MA_…`) | The **customer's** token (returned once at account creation) |

<Warning>
  Your partner token can create and fund customers but **cannot** be used to drive a customer's voice resources. To act on a customer's behalf, use that customer's own `auth_id`/`auth_token` from [Create Customer Account](/docs/partner/api/customers#create-customer-account) against the `/Account/{customer_auth_id}/*` base path. There is no separate Bearer JWT for partner server-to-server calls - the JWT login below is for interactive sessions only.
</Warning>

## Header-Based Authentication

Include the following headers on every request. These credentials are permanent and do not expire - rotate them manually if compromised.

* **`X-Auth-ID`** *(required)* - Your permanent Partner ID. Retrieved from the Partner Console under **Settings → API Keys**. It does not change unless you request a new one.
* **`X-Auth-Token`** *(required)* - Your secret API token. Rotate this immediately if you suspect it has been compromised. Issue a new token from the Partner Console.
* **`Accept`** *(required on GET/POST)* - Tells the API to return JSON responses.
* **`Content-Type`** *(required on POST/PUT with body)* - Set to `application/json` when sending a request body.

```bash theme={null}
curl -X GET \
  "${BASE}/me" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json"
```

```bash theme={null}
curl -X POST \
  "${BASE}/accounts" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{ "name": "Acme Corp", "email": "admin@acme.com", "password": "Secure@123", "country": "IN" }'
```

## Partner Login (JWT)

Exchanges your partner email and password for a temporary JWT access token. The Postman collection automatically captures the token into `partner_access_token` after a successful login. Use this for interactive sessions; use `X-Auth` headers for automation.

### Request

| Field | Type | Required | Description |
| - | - | - | - |
| `email` | string | Required | Your partner account email address |
| `password` | string | Required | Your partner account password |

```bash theme={null}
curl -X POST \
  "${BASE}/login" \
  -H "X-Auth-ID: {your_partner_id}" \
  -H "X-Auth-Token: {your_auth_token}" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "partner@example.com",
    "password": "YourPassword123!"
  }'
```

### Response

```json theme={null}
{
  "tokens": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "Bearer",
    "expires_in": 3600
  }
}
```

```json theme={null}
{
  "error": "invalid_credentials",
  "message": "The email or password you provided is incorrect."
}
```

## Common auth errors

| Status | Cause | Fix |
| - | - | - |
| `401` | Missing, malformed, or revoked `X-Auth-ID` / `X-Auth-Token`. | Re-check both headers; reissue the token from the Console if rotated. |
| `403` | Valid credentials but the operation isn't permitted - e.g. calling a partner endpoint with customer credentials, or a partner whose `can_create_accounts` / `can_transfer_balance` flag is `false`. | Use partner credentials for `/partner/*`; check your capability flags via [`GET /me`](/docs/partner/api/profile). |
| `404` | Right credentials, wrong base path (e.g. `/partner/v1/…` instead of `/api/v1/partner/…`), or a `customer_auth_id` that belongs to a different partner. | Use the base path `https://api.vobiz.ai/api/v1/partner`. |

<Warning>
  **Never expose the partner `X-Auth-Token` (or any customer `auth_token`) in client-side code, browser requests, mobile apps, URLs, or logs.** These are long-lived secrets that can create customers and move money. Keep them server-side and proxy any browser-initiated flows through your backend. Rotate immediately from the Console if a token is ever exposed.
</Warning>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.