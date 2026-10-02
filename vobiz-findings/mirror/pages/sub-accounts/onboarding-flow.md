> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Sub-Account Onboarding Flow

> End-to-end example: create a customer_use sub-account, complete KYC, buy and assign a number, and place the first call - with explicit guidance on when to use the parent's X-Auth credentials versus the sub-account's own auth_id and auth_token.

This walkthrough provisions a `customer_use` sub-account from scratch - **create → KYC → number → first call** - and is explicit about **which credentials to use at each step**.

**Base URL:** `https://api.vobiz.ai/api/v1`

## The one rule that prevents most of the confusion

Two credential pairs are in play. Keep them straight:

| Credential | What it is | Used for |
| - | - | - |
| **Parent `X-Auth-ID` / `X-Auth-Token`** | Your main account (`MA_…`) API key | **All provisioning & administration** - create the sub-account, run its KYC, buy numbers, assign/unassign numbers. The `{sub_auth_id}` in the URL identifies *which* sub-account you act on. |
| **Sub-account `auth_id` / `auth_token`** | The sub-account's own API key (`SA_…`), returned once at creation | The sub-account's **runtime** usage - placing/receiving calls, pulling its own CDRs and recordings. Hand this to your customer. |

<Tip>
  **Rule of thumb:** if you are *setting up* the sub-account, authenticate as the **parent**. Once it's live, the sub-account authenticates as **itself** to use the service.
</Tip>

<Info>
  KYC is **not** an exception. Sub-account KYC endpoints authenticate with the **parent's** `X-Auth-ID` / `X-Auth-Token`; the sub-account is identified by `{sub_auth_id}` in the path.
</Info>

<Warning>
  **Path casing is significant.** Note `/accounts/` and `/sub-accounts/` (sub-account CRUD + KYC), `/account/` (assign to sub-account), and `/Account/` (inventory + purchase + calls). The wrong casing returns 401/404 even with valid credentials.
</Warning>

## The flow

<Steps>
  <Step title="Create the customer sub-account - parent credentials">
    A customer that must be KYC'd in its own name is a `customer_use` sub-account. It requires an `email` and starts **call-blocked** until KYC passes.

    ```bash cURL theme={null}
    curl -X POST "https://api.vobiz.ai/api/v1/accounts/{parent_auth_id}/sub-accounts/" \
      -H "X-Auth-ID: {parent_auth_id}" \
      -H "X-Auth-Token: {parent_auth_token}" \
      -H "Content-Type: application/json" \
      -d '{
        "name": "Acme Corp",
        "email": "owner@acme.com",
        "password": "Acme@Secure123",
        "kyc_mode": "customer_use",
        "business_type": "private_limited"
      }'
    ```

    **Response (201)** - save the sub-account's own credentials; `auth_token` is shown **once**:

    ```json theme={null}
    {
      "sub_account": { "id": "SA_67401KW8", "kyc_mode": "customer_use", "kyc_calls_blocked": true },
      "auth_credentials": { "auth_id": "{sub_auth_id}", "auth_token": "{sub_auth_token}" },
      "tokens": { "access_token": "eyJ…", "refresh_token": "eyJ…", "token_type": "bearer", "expires_in": 1800 }
    }
    ```

    * `auth_credentials` → the **sub-account's** key (used in the final step).
    * `tokens` (JWT) are **optional** - only for console/dashboard sign-in, not the REST/telephony API.
    * `kyc_calls_blocked: true` → the sub-account cannot place calls yet.
  </Step>

  <Step title="Complete KYC - parent credentials">
    All KYC endpoints live under `/sub-accounts/{sub_auth_id}/kyc/…` and authenticate as the **parent**. Run the documents the entity needs (PAN + GST/CIN for companies; PAN + Aadhaar via DigiLocker for individuals), then poll status.

    ```bash Verify PAN theme={null}
    curl -X POST "https://api.vobiz.ai/api/v1/sub-accounts/{sub_auth_id}/kyc/verify-pan" \
      -H "X-Auth-ID: {parent_auth_id}" \
      -H "X-Auth-Token: {parent_auth_token}" \
      -H "Content-Type: application/json" \
      -d '{ "pan": "ABCDE1234F" }'
    ```

    ```bash Verify GST theme={null}
    curl -X POST "https://api.vobiz.ai/api/v1/sub-accounts/{sub_auth_id}/kyc/verify-gst" \
      -H "X-Auth-ID: {parent_auth_id}" \
      -H "X-Auth-Token: {parent_auth_token}" \
      -H "Content-Type: application/json" \
      -d '{ "gstin": "29ABCDE1234F1Z5" }'
    ```

    ```bash Poll status theme={null}
    curl "https://api.vobiz.ai/api/v1/sub-accounts/{sub_auth_id}/kyc/status" \
      -H "X-Auth-ID: {parent_auth_id}" \
      -H "X-Auth-Token: {parent_auth_token}"
    ```

    ```json theme={null}
    {
      "sub_account_id": "SA_67401KW8",
      "kyc_mode": "customer_use",
      "business_type": "private_limited",
      "overall_status": "verified",
      "kyc_calls_blocked": false,
      "verifications": {
        "pan": "verified",
        "gst": "verified",
        "aadhaar": "not_started",
        "cin": "not_started"
      }
    }
    ```

    When `kyc_calls_blocked` flips to `false`, the sub-account may place calls. `overall_status` is the aggregate (`not_started` / `pending` / `verified` / `failed`); `verifications` holds the per-document state.

    <Tip>
      Building the integration first? Use the [test-mode mirror](/docs/sub-accounts/kyc/test-mode) at `/sub-accounts/test/{sub_auth_id}/kyc/…` with magic inputs (`TESTSUCCESS0001` → verified, `TESTFAIL0001` → failed, `TESTPENDING001` → pending). Same parent auth, no real documents, no provider calls.
    </Tip>
  </Step>

  <Step title="Buy a number - parent credentials">
    Browse inventory, then purchase. Buying with the parent puts the number in the **parent's pool**, ready to assign in the next step. Billing for an `SA_` purchase always routes to the parent `MA_`.

    ```bash Find a number theme={null}
    curl "https://api.vobiz.ai/api/v1/Account/{parent_auth_id}/inventory/numbers" \
      -H "X-Auth-ID: {parent_auth_id}" \
      -H "X-Auth-Token: {parent_auth_token}"
    ```

    ```bash Purchase it theme={null}
    curl -X POST "https://api.vobiz.ai/api/v1/Account/{parent_auth_id}/numbers/purchase-from-inventory" \
      -H "X-Auth-ID: {parent_auth_id}" \
      -H "X-Auth-Token: {parent_auth_token}" \
      -H "Content-Type: application/json" \
      -d '{ "e164": "+919876543210" }'
    ```

    Purchasing debits the parent's balance (setup fee + monthly fee).
  </Step>

  <Step title="Link the number to the sub-account - parent credentials">
    Assign a parent-pool DID to the sub-account. URL-encode `+` as `%2B` in the path; name the sub-account in the body via `sub_account_id`.

    ```bash cURL theme={null}
    curl -X POST "https://api.vobiz.ai/api/v1/account/{parent_auth_id}/numbers/%2B919876543210/assign-subaccount" \
      -H "X-Auth-ID: {parent_auth_id}" \
      -H "X-Auth-Token: {parent_auth_token}" \
      -H "Content-Type: application/json" \
      -d '{ "sub_account_id": "{sub_auth_id}" }'
    ```

    The number now belongs to the sub-account.

    <Note>
      Moving a number back to the parent pool is subject to a **15-day cool-off** if it had a call in the last 15 days. See [Unassign DID](/docs/account-phone-number/unassign-subaccount).
    </Note>
  </Step>

  <Step title="The sub-account places a call - sub-account credentials">
    Now switch credentials. The sub-account (or your customer) authenticates as **itself** using the `auth_id` / `auth_token` from Step 1.

    ```bash cURL theme={null}
    curl -X POST "https://api.vobiz.ai/api/v1/Account/{sub_auth_id}/Call/" \
      -H "X-Auth-ID: {sub_auth_id}" \
      -H "X-Auth-Token: {sub_auth_token}" \
      -H "Content-Type: application/json" \
      -d '{
        "from": "+919876543210",
        "to": "+919812345678",
        "answer_url": "https://your-app.example.com/answer.xml"
      }'
    ```

    This succeeds only when `kyc_calls_blocked` is `false` (Step 2 complete).
  </Step>
</Steps>

## Alternative: let the sub-account buy its own number

Instead of Steps 3–4, the sub-account can purchase directly with **its own** `auth_id` / `auth_token` (billing still routes to the parent `MA_`). The number lands directly on the sub-account - no separate assign step:

```bash cURL theme={null}
curl -X POST "https://api.vobiz.ai/api/v1/Account/{sub_auth_id}/numbers/purchase-from-inventory" \
  -H "X-Auth-ID: {sub_auth_id}" \
  -H "X-Auth-Token: {sub_auth_token}" \
  -H "Content-Type: application/json" \
  -d '{ "e164": "+919876543210" }'
```

## Auth cheat-sheet

| Step | Operation | Endpoint | Auth |
| - | - | - | - |
| 1 | Create sub-account | `POST /accounts/{auth_id}/sub-accounts/` | **Parent** |
| 2 | Verify PAN / GST / CIN / DigiLocker | `POST /sub-accounts/{sub_auth_id}/kyc/…` | **Parent** |
| 2 | KYC status | `GET /sub-accounts/{sub_auth_id}/kyc/status` | **Parent** |
| 3 | List inventory | `GET /Account/{auth_id}/inventory/numbers` | **Parent** |
| 3 | Buy number | `POST /Account/{auth_id}/numbers/purchase-from-inventory` | **Parent** |
| 4 | Assign to sub-account | `POST /account/{auth_id}/numbers/{e164}/assign-subaccount` | **Parent** |
| 4 | Unassign (15-day cool-off) | `DELETE /account/{auth_id}/numbers/{e164}/assign-subaccount` | **Parent** |
| 5 | Place a call | `POST /Account/{auth_id}/Call/` | **Sub-account** |
| alt | Sub buys directly | `POST /Account/{auth_id}/numbers/purchase-from-inventory` | **Sub-account** |

**TL;DR:** Parent credentials for setup (Steps 1–4); the sub-account's own credentials for usage (Step 5 onward).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.