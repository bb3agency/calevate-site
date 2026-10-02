> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Twilio Subaccounts → Vobiz Sub-Accounts

> Migrate Twilio subaccounts to Vobiz. Map api.accounts.create / list / update(status) and subaccount auth to Vobiz sub_accounts.create_subaccount / list / retrieve / update / delete, plus built-in customer KYC (PAN, GST, CIN, DigiLocker, hosted sessions) for your customers.

Twilio's [Account resource](https://www.twilio.com/docs/iam/api/account) lets you spin up **subaccounts** under one parent for multi-tenant isolation and per-tenant billing. Vobiz gives you the same model with the `sub_accounts` resource - plus a first-class **customer KYC** pipeline (PAN, GST, CIN, DigiLocker, hosted verification sessions) so each customer sub-account can be onboarded and compliant before it ever places a call.

If you already have a Twilio integration, this is mostly a rename-and-add-`auth_id` job. Every account-scoped Vobiz method takes your master `auth_id` explicitly, and the sub-account is addressed by its own `sub_auth_id`.

<Note>
  Set credentials once: `AUTH_ID` is your Vobiz **master** Auth ID (`MA_…`) and `AUTH_TOKEN` is its Auth Token. In the Vobiz SDK `api_key` **is** the Auth ID (sent as `X-Auth-ID`), and `auth_token` maps to `X-Auth-Token`. Base URL: `https://api.vobiz.ai/api/v1`.
</Note>

## At a glance

| Concept | Twilio | Vobiz |
| - | - | - |
| Identifier | Account SID `AC…` | Master Auth ID `MA_…` / Sub Auth ID `SA_…` |
| Create tenant | `accounts.create(friendly_name=)` | `sub_accounts.create_subaccount(auth_id, name=)` |
| Per-tenant credentials | Subaccount SID + Auth Token | Sub-account Auth ID + Auth Token / password |
| Billing | Rolls up to parent | Rolls up to master |
| Suspend / resume | `update(status="suspended" \| "active")` | `update_subaccount(..., enabled=False \| True)` |
| Close tenant | `update(status="closed")` (irreversible) | `delete_subaccount(auth_id, sub_auth_id=)` |
| Customer onboarding | Build your own KYC | Built-in `sub_account_kyc.*` (PAN/GST/CIN/DigiLocker/hosted) |

## Twilio → Vobiz mapping table

| Task | Twilio (`twilio-python`) | Vobiz (`vobiz`) |
| - | - | - |
| Create a tenant | `client.api.v2010.accounts.create(friendly_name="Customer Co")` | `client.sub_accounts.create_subaccount(auth_id=AUTH_ID, name="Customer Co")` |
| Create a KYC-gated customer tenant | *(build your own KYC on top)* | `create_subaccount(auth_id, name=, email=, kyc_mode="customer_use", business_type="private_limited")` |
| List tenants | `client.api.v2010.accounts.list()` | `client.sub_accounts.list_subaccounts(AUTH_ID)` |
| Filter by name / status | `accounts.list(friendly_name=…, status=…)` | `list_subaccounts(AUTH_ID)` then filter on `name` / `enabled` |
| Fetch one tenant | `client.api.v2010.accounts(sid).fetch()` | `client.sub_accounts.retrieve_subaccount(AUTH_ID, sub_auth_id=SA_ID)` |
| Rename a tenant | `accounts(sid).update(friendly_name="New")` | `update_subaccount(AUTH_ID, sub_auth_id=SA_ID, name="New")` |
| Suspend a tenant | `accounts(sid).update(status="suspended")` | `update_subaccount(AUTH_ID, sub_auth_id=SA_ID, enabled=False)` |
| Reactivate a tenant | `accounts(sid).update(status="active")` | `update_subaccount(AUTH_ID, sub_auth_id=SA_ID, enabled=True)` |
| Close / delete a tenant | `accounts(sid).update(status="closed")` | `client.sub_accounts.delete_subaccount(AUTH_ID, sub_auth_id=SA_ID)` |
| Act as the tenant | Re-auth with subaccount SID + Auth Token | Call account-scoped methods with the sub-account's Auth ID/Token |
| Assign a number to a tenant | Transfer the phone number to the subaccount | `client.phone_numbers.assign_did_to_subaccount(AUTH_ID, e164=, sub_account_id=SA_ID)` |
| Verify customer PAN | *(external / manual)* | `client.sub_account_kyc.verify_subaccount_pan(sub_auth_id=SA_ID, pan="ABCDE1234F")` |
| Verify customer GSTIN | *(external / manual)* | `client.sub_account_kyc.verify_subaccount_gst(sub_auth_id=SA_ID, gstin="29AAJCN5983D1Z0")` |
| Verify company (CIN) | *(external / manual)* | `search_subaccount_cin(...)` → `confirm_subaccount_cin(...)` |
| Aadhaar via DigiLocker | *(external / manual)* | `subaccount_digilocker_initiate(...)` → `subaccount_digilocker_verify(...)` |
| Hand off onboarding to the customer | *(build your own)* | `create_subaccount_kyc_session(sub_auth_id, account_auth_id, flow_type="email" \| "redirect")` |
| KYC status | *(your own store)* | `client.sub_account_kyc.get_subaccount_kyc_status(sub_auth_id=SA_ID)` |

## Create a tenant

Twilio's `accounts.create` becomes `sub_accounts.create_subaccount` - add your master `auth_id` and use `name` instead of `friendly_name`. Both return the new tenant's own credentials.

<CodeGroup>
  ```python Twilio · Python theme={null}
  from twilio.rest import Client

  client = Client(ACCOUNT_SID, AUTH_TOKEN)

  sub = client.api.v2010.accounts.create(friendly_name="Customer Co")
  print(sub.sid, sub.auth_token)   # subaccount credentials
  ```

  ```python Vobiz · Python theme={null}
  from vobiz import Vobiz

  client = Vobiz(api_key=AUTH_ID, auth_token=AUTH_TOKEN)

  sub = client.sub_accounts.create_subaccount(
      auth_id=AUTH_ID,
      name="Customer Co",
  )
  # sub carries the new sub-account's Auth ID (SA_…) and credentials
  ```

  ```javascript Twilio · Node theme={null}
  const client = require('twilio')(ACCOUNT_SID, AUTH_TOKEN);

  const sub = await client.api.v2010.accounts.create({ friendlyName: 'Customer Co' });
  console.log(sub.sid, sub.authToken);
  ```

  ```javascript Vobiz · Node theme={null}
  import { VobizClient } from '@vobiz/sdk';

  const client = new VobizClient({ apiKey: AUTH_ID, authToken: AUTH_TOKEN });

  const sub = await client.subAccounts.createSubaccount({
    auth_id: AUTH_ID,
    name: 'Customer Co',
  });
  ```
</CodeGroup>

## Onboard a customer tenant with built-in KYC

Where Twilio hands you a bare subaccount, Vobiz lets you gate the tenant behind verification. Create it with `kyc_mode="customer_use"` (this **requires** an `email`) and pass the customer's `business_type` to drive which documents are needed. A fresh `customer_use` sub-account starts with `kyc_calls_blocked: true`, then flips live once KYC passes - no external compliance stack to build.

<CodeGroup>
  ```python Vobiz · Python theme={null}
  # 1) Create a KYC-gated customer sub-account
  sub = client.sub_accounts.create_subaccount(
      auth_id=AUTH_ID,
      name="Customer Co",
      email="ops@customer.co",
      kyc_mode="customer_use",
      business_type="private_limited",
  )
  SA_ID = sub.auth_id  # e.g. "SA_…"

  # 2a) Verify documents directly through the API
  client.sub_account_kyc.verify_subaccount_pan(sub_auth_id=SA_ID, pan="ABCDE1234F")
  client.sub_account_kyc.verify_subaccount_gst(sub_auth_id=SA_ID, gstin="29AAJCN5983D1Z0")

  # 2b) …or let the customer self-serve via a Vobiz-hosted session
  session = client.sub_account_kyc.create_subaccount_kyc_session(
      sub_auth_id=SA_ID,
      account_auth_id=SA_ID,
      flow_type="email",                 # emails a signed link from kyc@vobiz.ai
      customer_email="ops@customer.co",
      webhook_url="https://your-app.example.com/kyc/webhook",
      expires_in_days=30,
  )

  # 3) Check aggregated KYC state before enabling calls
  status = client.sub_account_kyc.get_subaccount_kyc_status(sub_auth_id=SA_ID)
  ```

  ```javascript Vobiz · Node theme={null}
  const sub = await client.subAccounts.createSubaccount({
    auth_id: AUTH_ID,
    name: 'Customer Co',
    email: 'ops@customer.co',
    kyc_mode: 'customer_use',
    business_type: 'private_limited',
  });
  const SA_ID = sub.authId;

  await client.subAccountKyc.verifySubaccountPan({ sub_auth_id: SA_ID, pan: 'ABCDE1234F' });

  // Redirect flow: get an inline widget URL back instead of emailing the customer
  const session = await client.subAccountKyc.createSubaccountKycSession({
    sub_auth_id: SA_ID,
    account_auth_id: SA_ID,
    flow_type: 'redirect',
    redirect_url: 'https://partner.example.com/kyc/callback',
    webhook_url: 'https://your-app.example.com/kyc/webhook',
  });
  ```
</CodeGroup>

<Tip>
  For a company, run `search_subaccount_cin(company_name=…)` to get candidate matches, then `confirm_subaccount_cin(selected_cin=…)`. For an individual, use `subaccount_digilocker_initiate(redirect_url=…)` and finish with `subaccount_digilocker_verify(...)` after the customer completes the DigiLocker OAuth flow.
</Tip>

## List, fetch, rename

`accounts.list()` / `.fetch()` map straight across. Vobiz addresses a specific tenant by its `sub_auth_id`.

<CodeGroup>
  ```python Twilio · Python theme={null}
  accounts = client.api.v2010.accounts.list(status="active", limit=50)
  one = client.api.v2010.accounts("ACxxxxxxxx").fetch()
  client.api.v2010.accounts("ACxxxxxxxx").update(friendly_name="Renamed Co")
  ```

  ```python Vobiz · Python theme={null}
  accounts = client.sub_accounts.list_subaccounts(AUTH_ID)
  one = client.sub_accounts.retrieve_subaccount(AUTH_ID, sub_auth_id="SA_XXXX")
  client.sub_accounts.update_subaccount(AUTH_ID, sub_auth_id="SA_XXXX", name="Renamed Co")
  ```

  ```javascript Twilio · Node theme={null}
  const accounts = await client.api.v2010.accounts.list({ status: 'active', limit: 50 });
  const one = await client.api.v2010.accounts('ACxxxxxxxx').fetch();
  await client.api.v2010.accounts('ACxxxxxxxx').update({ friendlyName: 'Renamed Co' });
  ```

  ```javascript Vobiz · Node theme={null}
  const accounts = await client.subAccounts.listSubaccounts(AUTH_ID);
  const one = await client.subAccounts.retrieveSubaccount(AUTH_ID, { sub_auth_id: 'SA_XXXX' });
  await client.subAccounts.updateSubaccount(AUTH_ID, { sub_auth_id: 'SA_XXXX', name: 'Renamed Co' });
  ```
</CodeGroup>

## Suspend, reactivate, close

Twilio drives lifecycle through the `status` enum (`active` / `suspended` / `closed`). Vobiz splits this into a reversible `enabled` toggle and an explicit delete, so "pause" and "permanently remove" are separate, deliberate calls.

<CodeGroup>
  ```python Twilio · Python theme={null}
  client.api.v2010.accounts("ACxxxxxxxx").update(status="suspended")  # pause
  client.api.v2010.accounts("ACxxxxxxxx").update(status="active")     # resume
  client.api.v2010.accounts("ACxxxxxxxx").update(status="closed")     # irreversible
  ```

  ```python Vobiz · Python theme={null}
  client.sub_accounts.update_subaccount(AUTH_ID, sub_auth_id="SA_XXXX", enabled=False)  # pause
  client.sub_accounts.update_subaccount(AUTH_ID, sub_auth_id="SA_XXXX", enabled=True)   # resume
  client.sub_accounts.delete_subaccount(AUTH_ID, sub_auth_id="SA_XXXX")                 # remove + revoke creds
  ```

  ```javascript Vobiz · Node theme={null}
  await client.subAccounts.updateSubaccount(AUTH_ID, { sub_auth_id: 'SA_XXXX', enabled: false });
  await client.subAccounts.updateSubaccount(AUTH_ID, { sub_auth_id: 'SA_XXXX', enabled: true });
  await client.subAccounts.deleteSubaccount(AUTH_ID, { sub_auth_id: 'SA_XXXX' });
  ```
</CodeGroup>

## Acting as a tenant

On Twilio you re-authenticate with the subaccount's own SID and Auth Token to make calls "as" that tenant. Vobiz works the same way: each sub-account has its own Auth ID and Auth Token, and you pass those as the `auth_id` on account-scoped methods (`make_call`, `phone_numbers.*`, `cdr.*`, and the rest). Calls, numbers, recordings and CDRs are all scoped to whichever Auth ID you present, so billing and data stay cleanly isolated per tenant and roll up to the master.

<CodeGroup>
  ```python Vobiz · Python theme={null}
  # Instantiate against the sub-account's own credentials …
  tenant = Vobiz(api_key=SUB_AUTH_ID, auth_token=SUB_AUTH_TOKEN)
  tenant.calls.make_call(
      auth_id=SUB_AUTH_ID,
      from_="+14155551234",
      to="+14165553434",
      answer_url="https://example.com/answer.xml",
      answer_method="POST",
  )

  # … or assign a purchased number to the tenant from the master account
  client.phone_numbers.assign_did_to_subaccount(
      AUTH_ID, e164="+14155551234", sub_account_id="SA_XXXX",
  )
  ```
</CodeGroup>

## Key differences

* **Explicit `auth_id` everywhere.** Twilio infers the account from the credentials on the client; Vobiz passes the Auth ID on each account-scoped call. This makes master-vs-tenant context obvious in code and easy to audit.
* **Reversible pause is its own field.** Twilio overloads one `status` enum; Vobiz uses `enabled` (True/False) for pause/resume and a separate `delete_subaccount` for permanent removal - so a routine "pause billing" can never be confused with an irreversible close.
* **Customer KYC is built in.** Twilio gives you the tenant container; Vobiz adds `sub_account_kyc.*` on top - PAN, GSTIN, CIN, and Aadhaar-via-DigiLocker verification, plus Vobiz-hosted email/redirect sessions from `kyc.vobiz.ai`. You can onboard regulated Indian customers without building a compliance stack.
* **KYC-gated go-live.** With `kyc_mode="customer_use"`, a new tenant starts with `kyc_calls_blocked: true` and flips live automatically once verification passes - a clean, provable onboarding gate. `personal_use` sub-accounts simply inherit the master's KYC.
* **Number assignment is a first-class call.** Move a purchased DID to a tenant with `phone_numbers.assign_did_to_subaccount(...)`, keeping ownership and billing under the master while the tenant uses the number.
* **Self-service onboarding.** `create_subaccount_kyc_session(...)` hands the whole verification flow to your customer via a signed email link or an inline redirect widget, with results delivered to your `webhook_url`.

## Next steps

* Continue with the full [Twilio → Vobiz overview](/docs/compare/twilio/overview) for the resource-by-resource map.
* Building IVR/menus for these tenants? See the [`<Gather>` reference](/docs/xml/gather).
* Coming from Plivo too? Start with the [Plivo → Vobiz overview](/docs/compare/plivo/overview) for the resource-by-resource map.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.