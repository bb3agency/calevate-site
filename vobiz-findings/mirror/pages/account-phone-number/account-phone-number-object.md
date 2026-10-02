> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# The PhoneNumber Object

> Every Vobiz phone number is modeled as a PhoneNumber object holding capabilities, billing, E.164 format, status, and assignment details for voice calls.

The PhoneNumber object represents a phone number in the Vobiz system, including its capabilities, billing details, and status.

## Attributes

| Field | Type | Description |
| - | - | - |
| `id` | string | UUID identifier for the phone number. |
| `auth_id` | string | Auth ID (MA\_xxx or SA\_xxx) that owns this number. Null if number is in inventory and not assigned to any account. |
| `e164` | string | Phone number in E164 format (e.g., "+14155551234"). |
| `country` | string | Country code (e.g., "US", "IN"). |
| `region` | string | State/region code (e.g., "CA", "MH"). Optional. |
| `capabilities` | object | Object containing boolean flags for each capability: voice, sms, mms, fax. |
| `capabilities.voice` | boolean | Whether the number supports voice calling. |
| `capabilities.sms` | boolean | Whether the number supports SMS messaging. |
| `capabilities.mms` | boolean | Whether the number supports MMS messaging. |
| `capabilities.fax` | boolean | Whether the number supports fax. |
| `status` | string | Current status of the number. One of: "active", "pending\_purchase", "pending\_release", "released", "blocked". |
| `provider` | string | Upstream carrier/provider identifier. Often an empty string for Vobiz-stocked numbers. |
| `setup_fee` | number | One-time setup fee charged when purchasing the number. |
| `monthly_fee` | number | Monthly recurring fee for the number. |
| `currency` | string | Currency code for fees (e.g., "USD", "INR"). |
| `application_id` | string | ID of the application the number is attached to, if any. Optional. |
| `trunk_group_id` | string | UUID of assigned trunk group. Null if not assigned to any trunk. Optional. |
| `voice_enabled` | boolean | Whether voice routing is enabled for the number. |
| `tags` | array | Free-form string tags applied to the number. |
| `is_blocked` | boolean | Whether the number is currently blocked. |
| `is_trial_number` | boolean | Whether the number was provisioned as a trial number. |
| `source` | string | How the number entered the account (e.g., `purchased`, `inventory`). |
| `minimum_commitment_months` | integer | Minimum commitment period in months. `0` if none. |
| `aadhaar_verification_required` | boolean | Whether Aadhaar verification is required for this number (India). |
| `aadhaar_verified` | boolean | Whether Aadhaar verification has been completed. |
| `purchased_at` | string | ISO 8601 timestamp when the number was purchased. Optional. |
| `released_at` | string | ISO 8601 timestamp when the number was released. Optional. |
| `last_billing_date` | string | ISO 8601 timestamp of the most recent monthly-fee billing. Optional. |
| `next_billing_date` | string | ISO 8601 timestamp of the next scheduled monthly-fee billing. Optional. |
| `created_at` | string | ISO 8601 timestamp when the number record was created. |
| `updated_at` | string | ISO 8601 timestamp when the number record was last updated. |

<Note>
  In list and purchase responses the owning account is returned as `account_id` (e.g. `MA_XXXXXX`). The detached `inventory` listing has `auth_id=NULL`. The `capabilities` block is voice-first - `sms`, `mms`, and `fax` are commonly `false`.
</Note>

## Number Status Values

| Status | Description |
| - | - |
| `active` | Number is active and available |
| `pending_purchase` | Purchase in progress |
| `pending_release` | Release in progress |
| `released` | Number has been released |
| `blocked` | Number is blocked |

## Example PhoneNumber Object

```json JSON theme={null}
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "auth_id": "{auth_id}",
  "e164": "+14155551234",
  "country": "US",
  "region": "CA",
  "capabilities": {
    "voice": true,
    "sms": true,
    "mms": false,
    "fax": false
  },
  "status": "active",
  "setup_fee": 1.00,
  "monthly_fee": 1.00,
  "currency": "USD",
  "trunk_group_id": "660e8400-e29b-41d4-a716-446655440001",
  "purchased_at": "2025-01-15T10:00:00Z",
  "created_at": "2025-01-15T10:00:00Z",
  "updated_at": "2025-01-15T10:00:00Z"
}
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.