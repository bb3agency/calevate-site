> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# The Account Object

> Explore every field in the Vobiz Account object - auth_id, pricing tier, CPS limits, concurrency caps, IP whitelist, and verification status for global telephony platform.

The Account object contains all the information about your Vobiz account, including authentication credentials, pricing tier, verification status, and timestamps.

## Attributes

| Field | Type | Description |
| - | - | - |
| `id` | string | Internal numeric account identifier (e.g., `"500000"`). The credential you authenticate with is `auth_id` (e.g., `"MA_XXXXXX"`), not `id`. |
| `api_id` | string | Internal API reference identifier (UUID). |
| `name` | string | Name of the account or company. |
| `email` | string | Email address associated with the account. |
| `phone` | string | Primary phone number for the account. |
| `type` | string | Object type discriminator. Always `"account"`. |
| `auth_id` | string | Authentication ID used for API requests. |
| `auth_secret` | string | Secret key for authentication (only shown in secure contexts). |
| `auth_token_expire_time` | string | ISO 8601 timestamp when the current auth token expires. |
| `description` | string \| null | Optional description or notes for the account. |
| `company` | string | Full legal name of the company. |
| `address \| city \| state \| zip_code` | string | Physical location details for the account. |
| `country` | string \| null | Country code or name for the account location. |
| `timezone` | string | Local timezone of the account (e.g., `"America/Los_Angeles"`). |
| `account_type` | string | Plan/category label for the account (e.g., `"standard"`). |
| `postpaid` | boolean | `true` for postpaid billing, `false` for prepaid. This is the authoritative billing-model flag. |
| `auto_recharge` | boolean | Whether auto-recharge is enabled for prepaid accounts. |
| `auto_recharge_config` | object \| null | Auto-recharge configuration (trigger threshold, top-up amount). `null` when unset. |
| `enabled` | boolean | Whether the account is generally enabled for service. |
| `is_active` | boolean | Whether the account is currently active. |
| `is_verified` | boolean | Whether the account identity has been verified. |
| `is_trial_account` | boolean | Indicates if the account is a trial account. |
| `role` | string | Role of the user associated with the account (e.g., `"ADMIN"`, `"USER"`). |
| `carrier_type` | string \| null | Type of carrier service. May be `null`. |
| `customer_type` | string \| null | Type of customer. May be `null`. |
| `credit_limit` | number | Maximum credit allowed for postpaid accounts. `0` for prepaid accounts with no credit line. |
| `cps_limit` | integer | Effective calls-per-second limit (`base_cps_limit` + `purchased_cps`). |
| `concurrent_calls_limit` | integer | Effective concurrent calls limit (`base_concurrent_calls_limit` + `purchased_concurrent_calls`). |
| `base_cps_limit` | integer | Base calls per second limit before any purchased add-ons. |
| `base_concurrent_calls_limit` | integer | Base concurrent calls limit before any purchased add-ons. |
| `purchased_cps` | integer | Additional CPS purchased by the account. |
| `purchased_concurrent_calls` | integer | Additional concurrent calls purchased by the account. |
| `risk_rating` | integer | Numeric risk assessment score for the account. |
| `risk_status` | string \| null | Current risk status. May be `null`. |
| `ip_auth_enabled` | boolean | Whether IP authentication is enabled for API access. |
| `ip_whitelist_rules` | object | Map of IP whitelist rules allowed for API access. Empty (`{}`) when unset. |
| `allow_aws_ips` | boolean | Whether to allow AWS IP ranges for API access. |
| `features` | object | Map of enabled features. Includes `call_queue` (boolean). |
| `pricing_tier_id` | string | Unique identifier of the pricing tier assigned to this account. |
| `pricing_tier` | object | Complete pricing tier object with billing rates and descriptions. |
| `created_at` | string | ISO 8601 timestamp when the account was created. |
| `updated_at` | string | ISO 8601 timestamp when the account was last updated. |
| `last_login` | string | ISO 8601 timestamp of the most recent login. |

## Example Account Object

```json theme={null}
{
  "type": "account",
  "id": "500000",
  "api_id": "aabbccdd-1234-5678-90ab-cdef12345678",
  "name": "John Doe",
  "email": "admin@example.com",
  "phone": "+919876543210",
  "description": "",
  "auth_id": "MA_XXXXXXXX",
  "auth_secret": "<redacted>",
  "auth_token_expire_time": null,
  "country": "IN",
  "timezone": "Asia/Kolkata",
  "city": "Bengaluru",
  "state": "KA",
  "address": "123 Example Street, Bengaluru",
  "zip_code": "560001",
  "company": "Acme Corp",
  "account_type": "standard",
  "postpaid": true,
  "auto_recharge": false,
  "auto_recharge_config": null,
  "enabled": true,
  "carrier_type": null,
  "customer_type": null,
  "credit_limit": 1000,
  "cps_limit": 61,
  "concurrent_calls_limit": 46,
  "base_cps_limit": 41,
  "base_concurrent_calls_limit": 26,
  "purchased_cps": 20,
  "purchased_concurrent_calls": 20,
  "risk_rating": 0,
  "risk_status": null,
  "features": {
    "call_queue": true
  },
  "ip_auth_enabled": false,
  "ip_whitelist_rules": {},
  "allow_aws_ips": false,
  "role": "user",
  "is_active": true,
  "is_verified": false,
  "is_trial_account": false,
  "created_at": "2026-01-19T18:39:14.529435+00:00",
  "updated_at": "2026-05-11T13:31:06.283235+00:00",
  "last_login": "2026-05-11T13:31:06.795577+00:00",
  "pricing_tier_id": "11223344-5566-7788-99aa-bbccddeeff00",
  "pricing_tier": {
    "id": "11223344-5566-7788-99aa-bbccddeeff00",
    "name": "Standard",
    "description": null,
    "currency": "INR",
    "rate_per_minute": 1.2,
    "billing_increment_seconds": 15,
    "minimum_duration_seconds": 15,
    "is_active": true,
    "is_default": false
  }
}
```

<Info>
  **Pricing Tier Object**

  Each account includes a nested `pricing_tier` object that defines billing rates:

  * **name** - Name of the pricing tier (e.g., `"baseTier"`)
  * **description** - A brief description of the pricing plan
  * **rate\_per\_minute** - Cost per minute of call time in the specified currency
  * **billing\_increment\_seconds** - Granularity of billing (e.g., 60 = billed by full minutes)
  * **minimum\_duration\_seconds** - Minimum billable duration for calls
  * **currency** - Currency code (USD, INR, EUR, etc.)
</Info>

<Info>
  **Prepaid vs postpaid**

  Use the `postpaid` boolean as the source of truth for the billing model. When `postpaid` is `false`, the account is prepaid and `auto_recharge` / `auto_recharge_config` control automatic top-ups; `credit_limit` is typically `0`. When `postpaid` is `true`, calls draw against the `credit_limit` (see [Balance](/docs/account/balance), where `is_postpaid` and `credit_limit_type` are also returned).
</Info>

<Info>
  **CPS and concurrency limits**

  The effective ceilings are derived: `cps_limit = base_cps_limit + purchased_cps` and `concurrent_calls_limit = base_concurrent_calls_limit + purchased_concurrent_calls`. The `purchased_*` fields report active add-on capacity; do not update them directly. [Preview the monthly price](/docs/account/channel-pricing-preview), then use the [capacity subscription API](/docs/account/channel-subscriptions) to purchase more. Live usage against these limits is reported by the [Concurrency](/docs/account/concurrency) endpoint.
</Info>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.