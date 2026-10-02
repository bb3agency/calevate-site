> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# The Subaccount Object

> Explore the Vobiz Subaccount object schema - auth credentials, permissions, rate limits, SA_ identifier format, and tenant isolation under a parent account.

The Subaccount object represents an isolated account under your main Vobiz account, with its own authentication credentials, permissions, and rate-limiting configuration.

## Attributes

| Field | Type | Description |
| - | - | - |
| `id` | string | Numeric internal identifier for the sub-account (e.g., `"500001"`). This is **not** the `auth_id` - use `auth_id` for API calls. |
| `name` | string | Name of the sub-account. |
| `description` | string \| null | Description of the sub-account purpose or usage. |
| `permissions` | object | Permissions object defining what the sub-account can access. Contains boolean fields like `calls` and `cdr`. |
| `rate_limit` | integer | API rate limit for this sub-account (requests per time period). |
| `kyc_mode` | string | Verification mode: `personal_use` (inherits parent KYC) or `customer_use` (the sub-account must complete its own KYC). |
| `business_type` | string \| null | Legal constitution of the customer (e.g. `individual`, `private_limited`, `llp`). Drives which KYC documents are required. |
| `kyc_calls_blocked` | boolean | `true` while a `customer_use` sub-account has not yet completed the KYC required to place calls. |
| `parent_account_id` | string | Numeric ID of the parent main account (e.g., `"510762"`). |
| `parent_auth_id` | string | Auth ID of the parent main account (e.g., `"MA_XXXXXXXX"`). |
| `auth_id` | string | The sub-account's own Auth ID (`SA_…`). Use this as the `X-Auth-ID` for the sub-account's runtime calls, and as the `{sub_auth_id}` path segment elsewhere. |
| `auth_token` | string | The sub-account's Auth Token. Returned in clear text **only once**, at creation; masked (`<redacted>`) on every later read. |
| `email_verified` | boolean | Whether the sub-account's email has been verified. |
| `enabled` | boolean | Whether the sub-account is enabled. A disabled sub-account stops accepting traffic but keeps its numbers. |
| `is_active` | boolean | Whether the sub-account is currently active and can make API calls. |
| `created_at` | string | ISO 8601 timestamp when the sub-account was created. |
| `updated_at` | string | ISO 8601 timestamp when the sub-account was last updated. |
| `last_used` | string \| null | ISO 8601 timestamp when the sub-account was last used for API calls. Null if never used. |

## Example Subaccount Object

```json theme={null}
{
  "name": "Support Team",
  "description": "Support-facing voice workload",
  "permissions": {
    "calls": true,
    "cdr": true
  },
  "rate_limit": 500,
  "kyc_mode": "customer_use",
  "business_type": "private_limited",
  "kyc_calls_blocked": true,
  "id": "500001",
  "parent_account_id": "510762",
  "parent_auth_id": "MA_XXXXXXXX",
  "auth_id": "SA_XXXXXXXX",
  "auth_token": "<redacted>",
  "email_verified": false,
  "enabled": true,
  "is_active": true,
  "created_at": "2025-10-22T03:57:35.997500Z",
  "updated_at": "2025-10-22T03:57:35.997500Z",
  "last_used": null
}
```

<Info>
  **Permissions Object:** The `permissions` object controls what resources the sub-account can access:

  * **calls** - Whether the sub-account can make/receive calls
  * **cdr** - Whether the sub-account can access Call Detail Records
</Info>

<Warning>
  **Rate Limiting:** The `rate_limit` field controls API request throttling for this sub-account. Set this based on expected usage patterns to prevent abuse.
</Warning>

<Info>
  **KYC mode:** `customer_use` sub-accounts must complete their own KYC before placing calls - they're created with `kyc_calls_blocked: true`. See [Sub-Account KYC](/docs/sub-accounts/kyc/overview).
</Info>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.