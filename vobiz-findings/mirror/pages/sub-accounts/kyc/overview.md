> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Sub-Account KYC

> Verify customer_use sub-accounts with per-document KYC - PAN, GST, CIN, and Aadhaar via DigiLocker - or hand off to a Vobiz-hosted KYC session. Includes a full test mode with magic inputs.

A `customer_use` sub-account must complete its own KYC before it can place calls. Until it does, the sub-account is returned with `kyc_calls_blocked: true`. This section documents the per-sub-account KYC API used to drive that verification.

<Info>
  **Authentication:** Sub-account KYC endpoints authenticate as the **parent main account** that owns the sub-account (or an admin), using your account's `X-Auth-ID` and `X-Auth-Token` headers - the same credential pair used everywhere else in the API:

  ```
  X-Auth-ID: {auth_id}
  X-Auth-Token: {auth_token}
  ```
</Info>

## When KYC applies

| `kyc_mode` | KYC required? | Notes |
| - | - | - |
| `personal_use` *(default)* | No | The sub-account inherits the parent account's KYC. |
| `customer_use` | Yes | The sub-account must verify itself. Requires an `email`. Fresh sub-accounts start with `kyc_calls_blocked: true`. |

Set `kyc_mode` at [creation](/docs/sub-accounts/create-subaccount) or [promote an existing sub-account](/docs/sub-accounts/update-subaccount).

## Verification paths

There are two ways to complete KYC for a `customer_use` sub-account:

<CardGroup cols={2}>
  <Card title="Per-document API" icon="list-check" href="/docs/sub-accounts/kyc/kyc-status">
    Drive each step yourself - PAN, GST, CIN, or Aadhaar via DigiLocker - and poll the aggregated status.
  </Card>

  <Card title="Hosted session" icon="link" href="/docs/sub-accounts/kyc/kyc-session">
    Hand the customer a Vobiz-hosted link (email) or redirect them inline to the hosted widget.
  </Card>
</CardGroup>

## Document requirements by entity

| Entity (`business_type`) | Typical documents |
| - | - |
| `individual`, `proprietorship`, `huf` | PAN + Aadhaar (via DigiLocker) |
| `private_limited`, `public_limited`, `llp`, `partnership` | PAN + GST and/or CIN |
| `trust`, `society`, `government` | PAN + supporting registration (CIN/GST as applicable) |

## How the call-blocking gate works

Each verification persists a `kyc_verifications` row and recomputes the sub-account's aggregated KYC state. The aggregated [status](/docs/sub-accounts/kyc/kyc-status) exposes:

* `overall_status` - `not_started` → `pending` → `verified` / `failed`.
* `verifications` - the per-document state (`pan`, `gst`, `cin`, `aadhaar`), each `not_started` / `pending` / `verified` / `failed`.
* `kyc_calls_blocked` - the gate. While `true`, the sub-account's calls are rejected; it flips to `false` once the documents its `business_type` requires are `verified`.

A single `failed` document leaves `kyc_calls_blocked: true`. Re-run that verification with corrected input to clear it.

## Create → KYC → unblock recipe

1. **Create** a `customer_use` sub-account with an `email` and a `business_type`. It returns `kyc_calls_blocked: true`. ([Create](/docs/sub-accounts/create-subaccount))
2. **Verify** the documents the entity needs - authenticate as the **parent**, with the sub-account in the path. For a company: [PAN](/docs/sub-accounts/kyc/verify-pan) then [GST](/docs/sub-accounts/kyc/verify-gst) and/or [CIN search](/docs/sub-accounts/kyc/cin-search) → [confirm](/docs/sub-accounts/kyc/cin-confirm). For an individual: PAN then [DigiLocker initiate](/docs/sub-accounts/kyc/digilocker-initiate) → [verify](/docs/sub-accounts/kyc/digilocker-verify).
3. **Poll** [KYC status](/docs/sub-accounts/kyc/kyc-status) until `kyc_calls_blocked` is `false`.
4. The sub-account can now place calls with **its own** credentials. See the full [onboarding flow](/docs/sub-accounts/onboarding-flow).

Prefer to hand the customer a Vobiz-hosted form instead of driving each step? Use a [hosted session](/docs/sub-accounts/kyc/kyc-session) and listen for [webhooks](/docs/sub-accounts/kyc/email-flow-webhook).

## Endpoints

| Method | Endpoint | Description |
| - | - | - |
| GET | `/sub-accounts/{sub_auth_id}/kyc/status` | Aggregated KYC state |
| POST | `/sub-accounts/{sub_auth_id}/kyc/verify-pan` | Verify PAN |
| POST | `/sub-accounts/{sub_auth_id}/kyc/verify-gst` | Verify GST |
| POST | `/sub-accounts/{sub_auth_id}/kyc/cin/search` | CIN search |
| POST | `/sub-accounts/{sub_auth_id}/kyc/cin/confirm` | CIN confirm |
| POST | `/sub-accounts/{sub_auth_id}/kyc/digilocker/initiate` | DigiLocker initiate |
| POST | `/sub-accounts/{sub_auth_id}/kyc/digilocker/verify` | DigiLocker verify |
| POST | `/sub-accounts/{sub_auth_id}/kyc-sessions` | Create a hosted KYC session |

<Tip>
  Building an integration? Use [Test Mode](/docs/sub-accounts/kyc/test-mode) to drive `verified` / `failed` / `pending` outcomes with magic inputs - no real documents and no calls to the upstream provider.
</Tip>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.