> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# KYC Test Mode

> Build and test your sub-account KYC integration without real documents. Mock endpoints never call the upstream provider - magic inputs drive deterministic verified, failed, pending, and error outcomes.

The mock KYC endpoints let you build and test a sub-account KYC integration end-to-end **without real documents and without calling the upstream provider**. Each mock call still persists a real `kyc_verifications` row and recomputes the sub-account's [KYC status](/docs/sub-accounts/kyc/kyc-status), so you exercise the same state machine your production flow will hit.

<Info>
  Mock endpoints live under the **`/sub-accounts/test/...`** path prefix and authenticate the same way as the real endpoints - your parent main account's `X-Auth-ID` and `X-Auth-Token` headers.
</Info>

## Magic inputs

For PAN and GST, the document value you send selects the outcome:

| Magic input | Outcome |
| - | - |
| `TESTSUCCESS0001` | `verified` |
| `TESTFAIL0001` | `failed` |
| `TESTERROR0001` | HTTP `500` (simulated provider error) |
| `TESTPENDING001` | `pending` - finalize later as `verified` |
| `TESTPENDING_FAIL` | `pending` - finalize later as `failed` |

<Note>
  GST uses the same matrix, but the `gstin` must be a 15-character GSTIN-shaped value. `TESTSUCCESS0001` is already 15 characters - use it as-is (do **not** append a suffix). Pad shorter magic inputs to 15 characters.
</Note>

For the other steps:

| Step | Magic behavior |
| - | - |
| CIN search | Returns deterministic fake matches. |
| CIN confirm | Succeeds when `selected_cin` starts with `U72900KA2024PTC123456`. |
| DigiLocker initiate | Returns a deterministic `access_request_id`. |
| DigiLocker verify | `MOCK_AR_SUCCESS` → `verified`, `MOCK_AR_FAIL` → `failed`. |

## Endpoints

All paths are prefixed with `https://api.vobiz.ai/api/v1/sub-accounts/test/{sub_auth_id}`.

| Method | Path | Description |
| - | - | - |
| POST | `/kyc/verify-pan` | Mock PAN - magic inputs above |
| POST | `/kyc/verify-gst` | Mock GST - same matrix |
| POST | `/kyc/cin/search` | Mock CIN search |
| POST | `/kyc/cin/confirm` | Mock CIN confirm |
| POST | `/kyc/digilocker/initiate` | Mock DigiLocker initiate |
| POST | `/kyc/digilocker/verify` | Mock DigiLocker verify |
| POST | `/kyc/finalize-pending` | Finalize a pending mock verification |

## Example: verified PAN

<CodeGroup>
  ```bash cURL theme={null}
  curl -X POST \
    "https://api.vobiz.ai/api/v1/sub-accounts/test/SA_XXXXXX/kyc/verify-pan" \
    -H "X-Auth-ID: {auth_id}" \
    -H "X-Auth-Token: {auth_token}" \
    -H "Content-Type: application/json" \
    -d '{ "pan": "TESTSUCCESS0001" }'
  ```

  ```json Response (200) theme={null}
  {
    "verification_type": "pan",
    "status": "verified",
    "mock": true
  }
  ```
</CodeGroup>

## Driving the async (pending) path

Some verifications complete asynchronously in production (e.g. provider returns later via webhook). To exercise that path in test mode **without webhooks**:

<Steps>
  <Step title="Submit a pending verification">
    Send a `TESTPENDING001` (or `TESTPENDING_FAIL`) value. The verification is recorded as `pending`.

    ```bash theme={null}
    curl -X POST \
      "https://api.vobiz.ai/api/v1/sub-accounts/test/SA_XXXXXX/kyc/verify-pan" \
      -H "X-Auth-ID: {auth_id}" \
      -H "X-Auth-Token: {auth_token}" \
      -H "Content-Type: application/json" \
      -d '{ "pan": "TESTPENDING001" }'
    ```
  </Step>

  <Step title="Finalize it">
    Promote the most recent pending mock verification of that type to a terminal outcome. `verification_type` ∈ `pan | aadhaar | gst | cin`; `outcome` ∈ `verified | failed`.

    ```bash theme={null}
    curl -X POST \
      "https://api.vobiz.ai/api/v1/sub-accounts/test/SA_XXXXXX/kyc/finalize-pending" \
      -H "X-Auth-ID: {auth_id}" \
      -H "X-Auth-Token: {auth_token}" \
      -H "Content-Type: application/json" \
      -d '{ "verification_type": "pan", "outcome": "verified" }'
    ```
  </Step>

  <Step title="Confirm">
    Poll [KYC status](/docs/sub-accounts/kyc/kyc-status) and confirm the verification flipped and `kyc_calls_blocked` updated as expected.
  </Step>
</Steps>

<Warning>
  Test mode writes real rows against the sub-account's KYC state. Use a dedicated test sub-account so a `failed` mock result doesn't leave a production sub-account blocked.
</Warning>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.