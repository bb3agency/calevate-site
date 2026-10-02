> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Plivo Subaccounts → Vobiz Sub-Accounts: Migration & Mapping

> Map Plivo's Subaccount API to Vobiz sub_accounts.* - create, list, update, delete, assign DIDs - plus the India KYC verification and 15-day DID cool-off that Vobiz adds for customer_use sub-accounts.

Vobiz keeps Plivo's sub-account CRUD shape (`sub_accounts.*`) but adds two things Plivo has no equivalent for: a **`kyc_mode`** that turns a sub-account into a separately-verified `customer_use` tenant, and a **15-day DID cool-off** when you move a number back out of a sub-account.

## Plivo → Vobiz mapping

| Plivo (REST / Python SDK) | Vobiz REST | Vobiz Python SDK |
| - | - | - |
| `POST /v1/Account/{auth_id}/Subaccount/` · `client.subaccounts.create(name, enabled)` | `POST /accounts/{auth_id}/sub-accounts/` | `client.sub_accounts.create_subaccount(auth_id, name, ...)` |
| `GET /v1/Account/{auth_id}/Subaccount/` (`limit`,`offset`) · `client.subaccounts.list()` | `GET /accounts/{auth_id}/sub-accounts/` | `client.sub_accounts.list_subaccounts(auth_id)` |
| `GET .../Subaccount/{subauth_id}/` · `client.subaccounts.get(subauth_id)` | `GET /accounts/{auth_id}/sub-accounts/{sub_auth_id}` | `client.sub_accounts.retrieve_subaccount(...)` |
| `POST .../Subaccount/{subauth_id}/` (`name`,`enabled`) · `client.subaccounts.update(...)` | `PUT /accounts/{auth_id}/sub-accounts/{sub_auth_id}` | `client.sub_accounts.update_subaccount(...)` |
| `DELETE .../Subaccount/{subauth_id}/` (`cascade`) · `client.subaccounts.delete(...)` | `DELETE /accounts/{auth_id}/sub-accounts/{sub_auth_id}` | `client.sub_accounts.delete_subaccount(...)` |
| `subaccount` param on **buy/update Number** (`POST .../Number/{number}/`) | `POST /account/{auth_id}/numbers/{e164}/assign-subaccount` | (REST - `sub_account_id` body) |
| *no equivalent* - Plivo has no per-subaccount KYC | `DELETE /account/{auth_id}/numbers/{e164}/assign-subaccount` (15-day cool-off) | (REST - `?force=true` admin bypass) |
| *no equivalent* | `GET /sub-accounts/{sub_auth_id}/kyc/status` | `client.sub_account_kyc.get_subaccount_kyc_status(...)` |
| *no equivalent* | `POST /sub-accounts/{sub_auth_id}/kyc/verify-pan` | `client.sub_account_kyc.verify_subaccount_pan(sub_auth_id, pan)` |
| *no equivalent* | `POST /sub-accounts/{sub_auth_id}/kyc/verify-gst` | `client.sub_account_kyc.verify_subaccount_gst(...)` |
| *no equivalent* | `POST /sub-accounts/{sub_auth_id}/kyc/cin/search` + `/cin/confirm` | `client.sub_account_kyc.search_subaccount_cin(...)` / `confirm_subaccount_cin(...)` |
| *no equivalent* | `POST /sub-accounts/{sub_auth_id}/kyc/digilocker/initiate` + `/verify` | `client.sub_account_kyc.subaccount_digilocker_initiate(...)` / `subaccount_digilocker_verify(...)` |
| *no equivalent* | `POST /sub-accounts/{sub_auth_id}/kyc-sessions` (hosted email/redirect flow) | `client.sub_account_kyc.create_subaccount_kyc_session(...)` |

Multi-tenancy is purely a REST/SDK concern.

## Before / after: create a tenant

On Plivo a subaccount is just a name + enabled flag. On Vobiz you decide at creation whether it inherits the parent's KYC (`personal_use`, the default - closest to Plivo) or is a separately-verified `customer_use` tenant.

```python Plivo theme={null}
import plivo

client = plivo.RestClient("MAXXXXXXXXXXXXXXXXXX", "auth_token")
client.subaccounts.create(
    name="Wayne Enterprises Subaccount",
    enabled=True,
)
```

```python Vobiz theme={null}
from vobiz import Vobiz

client = Vobiz(api_key="MA_XXXXXX", auth_token="AUTH_TOKEN")

# personal_use (default) ≈ Plivo's flat subaccount - inherits parent KYC
client.sub_accounts.create_subaccount(
    auth_id="MA_XXXXXX",
    name="Wayne Enterprises Subaccount",
    enabled=True,
)

# customer_use - a separately-verified tenant; email is REQUIRED and the
# sub-account comes back with kyc_calls_blocked=true until KYC passes
client.sub_accounts.create_subaccount(
    auth_id="MA_XXXXXX",
    name="Customer Co",
    email="customer@example.com",
    password="Customer@12345",
    kyc_mode="customer_use",
    business_type="private_limited",
)
```

The Vobiz create response returns the sub-account plus its `auth_credentials` (`auth_id` / `auth_token`) **and** a short-lived bearer token pair (`access_token` / `refresh_token`, `expires_in: 1800`) - Plivo only returns `auth_id` / `auth_token`.

## Key differences & gotchas

* **Headers, not Basic auth.** Plivo sends `auth_id:auth_token` as HTTP Basic; Vobiz sends `X-Auth-ID` + `X-Auth-Token` headers. A copied `RestClient(...)` won't authenticate.
* **`kyc_mode` is the new axis.** `personal_use` (default) is the drop-in equivalent of a Plivo subaccount. `customer_use` makes it a separately-verified tenant, **requires `email`**, and stays `kyc_calls_blocked` until KYC clears.
* **15-day DID cool-off.** Unassigning a DID used in the last 15 days returns `409 did_cool_off_in_effect`; never-used DIDs move instantly. An admin can bypass with `?force=true`.
* **Delete is permanent.** Vobiz `delete_subaccount` permanently deletes and revokes credentials; reassign DIDs (respecting the cool-off) first. List paging uses `total`/`page`/`size`.

The entire India KYC surface (`kyc_mode`, PAN/GST/CIN/Aadhaar verification, hosted KYC sessions, `kyc_calls_blocked`) and the 15-day DID cool-off are Vobiz-only. See [sub-account KYC](/docs/sub-accounts/kyc/kyc-session) and [India KYC](/docs/compliance/india/kyc) for the full flow.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.