> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Twilio vs Vobiz - full comparison

> The complete, domain-by-domain Twilio to Vobiz migration reference: voice call API, TwiML to VobizXML, phone numbers, SIP trunking, conferences, recordings, sub-accounts, webhooks, and SDKs - each with a Twilio/Vobiz mapping and a migration-effort rating.

Vobiz maps cleanly onto the Twilio model you already know: your Twilio **Account SID + Auth Token** become the Vobiz **`api_key` (Auth ID)** and **`auth_token`** (sent as `X-Auth-ID` and `X-Auth-Token` headers), **TwiML** answer documents become **VobizXML** with the same `<Response>` container and familiar verbs, and `client.calls.create(...)` becomes `client.calls.make_call(...)`. Most of a migration is mechanical - swap the base URL to `https://api.vobiz.ai/api/v1`, pass an explicit `auth_id`, and rename a handful of methods. The matrix below maps each domain to its Vobiz home and rates the effort, then a recommended migration order tells you what to move first.

## At-a-glance matrix

| Domain | Twilio | Vobiz | Migration effort |
| :- | :- | :- | :-: |
| [Voice Call API](/docs/compare/twilio/voice-call-api) | `Client(account_sid, auth_token)`; `client.calls.create(to, from_, url, method)`; in-call control via `client.calls(sid).update(...)` | `Vobiz(api_key, auth_token)`; `calls.make_call(auth_id, from_, to, answer_url, answer_method)`; in-call actions on `play_audio`/`speak_text`/`dtmf`/`record_calls`; in-progress on `live_calls` | Medium |
| [TwiML → VobizXML](/docs/compare/twilio/twiml-to-vobizxml) | TwiML `<Response>` with `<Say>`/`<Play>`/`<Gather>`/`<Dial>`/`<Record>`; served from `url` or inline `twiml` | VobizXML `<Response>` with `<Speak>`/`<Play>`/`<Gather>`/`<Dial>`/`<Record>` built by the bundled `vobizxml` builder; served from `answer_url` | Low |
| [Phone numbers](/docs/compare/twilio/phone-numbers) | `AvailablePhoneNumbers` search + `IncomingPhoneNumbers` provision/configure | `phone_numbers` over a pre-provisioned **inventory**; `purchase_from_inventory`, `assign_number_to_trunk`, `assign_did_to_subaccount` | High |
| [SIP trunking](/docs/compare/twilio/sip-trunking) | Elastic SIP Trunking (Trunks, Credential Lists, IP ACLs, Origination URIs) | First-class `trunks`/`credentials`/`ip_access_control_list`/`origination_uri` in every SDK; account-scoped auth; priority-weighted origination | Medium |
| [Conferences](/docs/compare/twilio/conferences) | `<Conference>` noun + Conference/Participant REST resources | Same `<Conference>` verb; member ops split across `conference`/`conference_members`/`conference_recording` | Low |
| [Recordings](/docs/compare/twilio/recordings) | `<Record>` + `record="record-from-answer"`; `Recordings` list/fetch/delete | `<Record>` + `record_calls` (`start_recording`/`stop_recording`); `recordings.list_recordings`/`get_recording`/`delete_recording` | Low |
| [Sub-accounts](/docs/compare/twilio/subaccounts) | Subaccounts under the `Accounts` resource (create, suspend, close) | `sub_accounts` CRUD plus `kyc_mode`/`business_type` and first-class India KYC via `sub_account_kyc` (PAN/GST/CIN/DigiLocker/hosted sessions) | High |
| [Webhooks](/docs/compare/twilio/webhooks) | `X-Twilio-Signature` (HMAC-SHA1 over full URL + alphabetically-sorted POST params); `RequestValidator` helper; params `CallSid`/`From`/`To`/`CallStatus`/`Digits` | Ring/answer flow to your `answer_url`; `X-Vobiz-Signature` header + SDK validator; `Gather` posts collected input to your `action` URL | Medium |
| [SDKs](/docs/compare/twilio/sdks) | Helper libraries from package registries (`twilio-python`, `twilio` for Node, etc.); `Client`; resource-CRUD method names | Seven languages **git-cloned** from `vobiz-ai/*`; `Vobiz`/`VobizClient` header auth; verb-named methods; explicit `auth_id`; bundled `vobizxml` | Medium |

## Twilio → Vobiz mapping

| Twilio concept | Vobiz equivalent |
| :- | :- |
| Account SID | `api_key` - your Vobiz **Auth ID**, sent as the `X-Auth-ID` header |
| Auth Token | `auth_token`, sent as the `X-Auth-Token` header |
| `Client(account_sid, auth_token)` | `Vobiz(api_key=AUTH_ID, auth_token=AUTH_TOKEN)` (Python) · `new VobizClient({ apiKey, authToken })` (Node) |
| API base `https://api.twilio.com/2010-04-01` | `https://api.vobiz.ai/api/v1` |
| Account scope implicit in the request path | Explicit `auth_id` passed to every account-scoped method |
| `client.calls.create(to, from_, url, method)` | `client.calls.make_call(auth_id, from_, to, answer_url, answer_method)` |
| `url` / inline `twiml` on the call | `answer_url` + `answer_method` (both explicit) |
| TwiML `<Response>` document | VobizXML `<Response>` built with `vobizxml.ResponseElement()` |
| `<Say>` | `<Speak>` · live: `speak_text.call(auth_id, call_uuid, text=)` |
| `<Play>` | `<Play>` · live: `play_audio.call(auth_id, call_uuid, urls=)` |
| `<Gather input numDigits timeout finishOnKey>` | `<Gather inputType numDigits executionTimeout digitEndTimeout finishOnKey>` ([reference](/docs/xml/gather)) |
| `<Dial><Number>` / `<Dial><Client>` | `<Dial><Number>` / `<Dial><User>` |
| `<Record>` / `record="record-from-answer"` | `<Record>` · live: `record_calls.start_recording` / `stop_recording` |
| `<Redirect>` (continue at another TwiML URL) | `<Redirect>` (continue at another VobizXML URL) - the way to move a call imperatively |
| `<Hangup>` / `client.calls(sid).update(status='completed')` | `<Hangup>` · `live_calls.hangup_call(auth_id, call_uuid)` |
| `<Enqueue>` / Queues | `live_calls.list_queued_calls` / `get_queued_call` |
| `client.calls(sid).update(...)` (in-call redirect) | `live_calls.get_live_call(auth_id, call_uuid, status='live')` + `play_audio`/`speak_text`/`dtmf`/`record_calls` |
| `AvailablePhoneNumbers` search | `phone_numbers.list_inventory_numbers(auth_id, country=, search=)` |
| `IncomingPhoneNumbers.create` (buy) | `phone_numbers.purchase_from_inventory(auth_id, e164=)` |
| Number → TwiML app / trunk binding | `phone_numbers.assign_number_to_trunk(auth_id, phone_number, trunk_group_id=)` |
| Elastic SIP Trunk | `trunks.create_trunk(auth_id, name=, trunk_type=, max_concurrent_calls=)` |
| Credential List / IP ACL / Origination URI | `credentials.*` / `ip_access_control_list.create_ip_acl` / `origination_uri.create_origination_uri` |
| Subaccounts (`Accounts` resource) | `sub_accounts.create_subaccount(auth_id, name=, email=, kyc_mode=, business_type=, enabled=)` |
| Regulatory Bundles / number compliance | `sub_account_kyc.*` - India KYC (PAN/GST/CIN/DigiLocker/hosted sessions) |
| `Recordings` resource | `recordings.list_recordings` / `get_recording` / `delete_recording(auth_id, ...)` |
| Call logs (`Calls` list) | `cdr.list_cdrs(auth_id, from_number=, to_number=, start_date=, end_date=, ...)` / `get_cdr(auth_id, call_id)` |
| Conference / Participant resources | `conferences.*` + `conference.*` / `conference_members.*` / `conference_recording.*` |
| `X-Twilio-Signature` + `RequestValidator` | `X-Vobiz-Signature` + SDK validator |
| Webhook params `CallSid` / `From` / `To` / `Digits` | Ring/answer-flow params posted to your `answer_url` / `Gather` `action` URL |

## Two changes that unlock everything

Before touching any domain, land these two orientation swaps - they cover the majority of a Twilio port.

### 1. Credentials and client

Same two secrets, moved into headers. Your Account SID is the Auth ID (`api_key`); your Auth Token is `auth_token`.

<CodeGroup>
  ```python Twilio · Python theme={null}
  from twilio.rest import Client

  client = Client(ACCOUNT_SID, AUTH_TOKEN)
  ```

  ```python Vobiz · Python theme={null}
  from vobiz import Vobiz

  # api_key IS your Auth ID → X-Auth-ID; auth_token → X-Auth-Token
  client = Vobiz(api_key=AUTH_ID, auth_token=AUTH_TOKEN)
  ```

  ```javascript Twilio · Node theme={null}
  const twilio = require('twilio');

  const client = twilio(ACCOUNT_SID, AUTH_TOKEN);
  ```

  ```javascript Vobiz · Node theme={null}
  import { VobizClient } from '@vobiz/sdk';

  const client = new VobizClient({ apiKey: AUTH_ID, authToken: AUTH_TOKEN });
  ```
</CodeGroup>

### 2. Outbound call + call instructions

`client.calls.create(...)` becomes `client.calls.make_call(...)`: add an explicit `auth_id`, point `url` → `answer_url`, and make `answer_method` explicit. Your TwiML answer document becomes VobizXML - same `<Response>`, `<Say>` → `<Speak>`, `<Gather>` keeps `numDigits`/`finishOnKey` and gains `inputType` + `executionTimeout`.

<CodeGroup>
  ```python Twilio · Python theme={null}
  call = client.calls.create(
      to='+14165553434',
      from_='+14155551234',
      url='https://example.com/answer.xml',
      method='POST',
  )
  ```

  ```python Vobiz · Python theme={null}
  call = client.calls.make_call(
      auth_id=AUTH_ID,
      from_='+14155551234',
      to='+14165553434',
      answer_url='https://example.com/answer.xml',
      answer_method='POST',
  )
  ```

  ```xml TwiML · answer.xml theme={null}
  <?xml version="1.0" encoding="UTF-8"?>
  <Response>
    <Gather action="/menu" method="POST" input="dtmf" numDigits="1">
      <Say>Press 1 for sales, 2 for support.</Say>
    </Gather>
  </Response>
  ```

  ```python VobizXML · Python builder theme={null}
  from vobiz import vobizxml

  resp = vobizxml.ResponseElement()
  menu = resp.add_gather(action='/menu', method='POST',
                         input_type='dtmf', num_digits=1)
  menu.add_speak('Press 1 for sales, 2 for support.')
  print(resp.to_string())
  ```
</CodeGroup>

## Recommended migration order

Work outward from the two foundations above so every later step builds on working auth and a working answer flow.

1. **Credentials and client** - map Account SID/Auth Token → `api_key`/`auth_token`, swap the base URL to `https://api.vobiz.ai/api/v1`, and add the explicit `auth_id`. See [Voice Call API](/docs/compare/twilio/voice-call-api).
2. **TwiML → VobizXML** - port your answer documents: `<Say>` → `<Speak>`, keep `<Gather>` (add `inputType`/`executionTimeout`), `<Dial><Client>` → `<Dial><User>`. See [TwiML → VobizXML](/docs/compare/twilio/twiml-to-vobizxml) and [`/xml/gather`](/docs/xml/gather).
3. **Outbound calls and live control** - `calls.create` → `calls.make_call`, and move in-call actions to `play_audio`/`speak_text`/`dtmf`/`record_calls` + `live_calls`. See [Voice Call API](/docs/compare/twilio/voice-call-api).
4. **Numbers and SIP trunking** - search the inventory, `purchase_from_inventory`, then wire `trunks`/`credentials`/`ip_access_control_list`/`origination_uri`. See [Phone numbers](/docs/compare/twilio/phone-numbers) and [SIP trunking](/docs/compare/twilio/sip-trunking).
5. **Conferences and recordings** - same `<Conference>`/`<Record>` verbs; adopt the `conference*` and `record_calls`/`recordings` namespaces. See [Conferences](/docs/compare/twilio/conferences) and [Recordings](/docs/compare/twilio/recordings).
6. **Sub-accounts and KYC** - recreate subaccounts with `sub_accounts`, then layer on `sub_account_kyc` for India onboarding. See [Sub-accounts](/docs/compare/twilio/subaccounts).
7. **Webhook validation** - swap `X-Twilio-Signature`/`RequestValidator` for `X-Vobiz-Signature` + the SDK validator, and read `Gather` input from the `action` URL. See [Webhooks](/docs/compare/twilio/webhooks).
8. **Reporting and SDK cleanup** - repoint call-log queries to `cdr.list_cdrs`/`get_cdr` and finish adopting the git-cloned SDKs. See [SDKs](/docs/compare/twilio/sdks).

## Key differences

* **Same two secrets, header auth.** Vobiz sends your Auth ID and Auth Token as `X-Auth-ID` and `X-Auth-Token` headers (the SDK does this for you), instead of Twilio's HTTP Basic `Account SID:Auth Token`.
* **Explicit `auth_id` everywhere.** Every account-scoped Vobiz method names the account it acts on, so multi-tenant and sub-account code reads unambiguously and is easy to audit.
* **`answer_url` + `answer_method`.** A Vobiz call fetches VobizXML from your `answer_url`, with the HTTP method stated explicitly - the same webhook-driven model as TwiML `url`, made explicit.
* **Familiar XML, one rename.** VobizXML keeps the `<Response>` container and most verbs; the main change is `<Say>` → `<Speak>`. `<Gather>` keeps `numDigits`/`finishOnKey` and adds `inputType`, `executionTimeout`, and `digitEndTimeout` (per-leg answer timeouts live on `<Dial>`/`<Number>`).
* **Dedicated in-call resources.** Where Twilio updates a call to redirect or act on it, Vobiz exposes `live_calls`, `play_audio`, `speak_text`, `dtmf`, and `record_calls` as first-class, strongly-typed resources keyed by `(auth_id, call_uuid)`.
* **Imperative transfers via `<Redirect>`.** To move a call to a new flow, return `<Redirect>` from the answer URL - a clean, stateless hand-off that keeps your call logic in one place.
* **SIP trunking and India KYC are first-class in the SDK.** `trunks`/`credentials`/`ip_access_control_list`/`origination_uri` and `sub_account_kyc` (PAN/GST/CIN/DigiLocker/hosted sessions) are typed resources in all seven SDKs.
* **SDKs you git-clone.** The seven Vobiz SDKs are cloned from `vobiz-ai/*` and ship the `vobizxml` builder in the box, so your REST calls and your answer-document generation come from one package.

Ready to go deeper? Start with the [Voice Call API](/docs/compare/twilio/voice-call-api) and [TwiML → VobizXML](/docs/compare/twilio/twiml-to-vobizxml) pages.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.