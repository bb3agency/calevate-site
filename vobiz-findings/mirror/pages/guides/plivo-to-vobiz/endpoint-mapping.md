> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Endpoint & SDK mapping

> Map every Plivo REST endpoint and SDK method to its Vobiz equivalent. The SDK method names match, so only the client init changes when you migrate from Plivo to Vobiz.

If you already run on Plivo, the migration to Vobiz is mostly mechanical. Vobiz mirrors Plivo's REST resource layout and ships SDKs whose method names match Plivo's, so in most cases you change only how you construct the client.

This page maps each Plivo resource and method to its Vobiz equivalent, then shows a before/after for the most common operation: placing an outbound call.

## The short version

* The REST paths share the same shape: `/api/v1/Account/{auth_id}/...` with PascalCase resource segments (`/Account/.../Call/`, identical to Plivo).
* The call **parameters** carry over (`from`, `to`, `answer_url`, ...), but the Vobiz client and method **names differ** (see the table): `plivo.RestClient(...)`/`calls.create(...)` → `Vobiz(api_key=, auth_token=)`/`calls.make_call(...)`, and Vobiz methods take an explicit `auth_id`.
* The make-call response includes the call identifier (`call_uuid`) and a status message.
* Bulk dialing is unchanged: both Plivo and Vobiz accept multiple destinations in a single `to` separated by `<` (for example, `a<b<c`).

<Tip>
  A drop-in compatibility shim is coming soon: **`vobiz-plivo-compat`** (Python) and **`@vobiz/plivo-compat`** (Node). It keeps your existing `plivo.RestClient(...)` calls working against Vobiz, so you can point at Vobiz with zero code changes and migrate at your own pace. Until it ships, follow the explicit mapping below.
</Tip>

## Resource and method mapping

The table covers the resources most teams use. The Vobiz REST path assumes the base `https://api.vobiz.ai` and your account `auth_id`. SDK methods are shown in their Python form (every method takes `auth_id=`); the Node SDK uses the same names in camelCase (for example, `make_call` → `makeCall`).

| Plivo resource / method | Vobiz REST path | Vobiz SDK method (Python) |
| - | - | - |
| **Calls** | | |
| Make a call (`POST /Call/`) | `POST /api/v1/Account/{auth_id}/Call/` | `client.calls.make_call(auth_id, from_, to, answer_url, ...)` |
| Get a live call | `GET /api/v1/Account/{auth_id}/Call/{call_uuid}/` | `client.live_calls.get_live_call(auth_id, call_uuid)` |
| List calls | `GET /api/v1/Account/{auth_id}/Call/` | `client.live_calls.list_live_calls(auth_id)` (and `list_queued_calls`) |
| Hang up a call | `DELETE /api/v1/Account/{auth_id}/Call/{call_uuid}/` | `client.live_calls.hangup_call(auth_id, call_uuid)` |
| Transfer a call | (call-control XML) | Return `<Dial>` / `<Redirect>` from your answer URL - see [Transfer a Call](/docs/call/transfer-call) |
| Play / speak / send digits | `POST /api/v1/Account/{auth_id}/Call/{call_uuid}/Play/` (etc.) | `client.play_audio.call(...)`, `client.speak_text.call(...)`, `client.dtmf.send_dtmf(...)` |
| **Applications** | | |
| Create / list / get / update / delete | `POST\|GET\|DELETE /api/v1/Account/{auth_id}/Application/` | `client.applications.create_application(...)`, `.list_applications(...)`, `.retrieve_application(...)`, `.update_application(...)`, `.delete_application(...)` |
| **Numbers** | | |
| Search inventory | `GET /api/v1/Account/{auth_id}/PhoneNumber/` | `client.phone_numbers.list_inventory_numbers(...)` |
| Buy a number | `POST /api/v1/Account/{auth_id}/PhoneNumber/{e164}/` | `client.phone_numbers.purchase_from_inventory(auth_id, e164, currency)` |
| List owned numbers | `GET /api/v1/Account/{auth_id}/Number/` | `client.phone_numbers.list_numbers(auth_id)` |
| Release a number | `DELETE /api/v1/Account/{auth_id}/Number/{number}/` | `client.phone_numbers.unrent_number(auth_id, e164)` |
| Route a number to a trunk | `POST /api/v1/Account/{auth_id}/Number/{number}/` | `client.phone_numbers.assign_number_to_trunk(...)` / `unassign_number_from_trunk(...)` |
| **Recordings** | | |
| List / get / delete | `GET\|DELETE /api/v1/Account/{auth_id}/Recording/` | `client.recordings.list_recordings(...)`, `.get_recording(...)`, `.delete_recording(...)` |
| **Conferences** | | |
| Member ops (kick / mute / play) | `POST\|DELETE /api/v1/Account/{auth_id}/Conference/{name}/Member/{id}/` | `client.conference.kick_member(...)`, `client.conference_members.mute_member(...)` / `unmute_member(...)` |
| **Sub-accounts** | | |
| Create / list / get / update / delete | `POST\|GET\|DELETE /api/v1/Account/{auth_id}/Subaccount/` | `client.sub_accounts.create_subaccount(...)`, `.list_subaccounts(...)`, `.retrieve_subaccount(...)`, `.update_subaccount(...)`, `.delete_subaccount(...)` |

<Note>
  Use the canonical reference pages for exact request and response fields. The make-call contract is documented in full at [Make an Outbound Call](/docs/call/make-call).
</Note>

## Before / after: making a call

The call parameters (`from`, `to`, `answer_url`, ...) carry over, but the Vobiz client and method differ: `plivo.RestClient(...)`/`client.calls.create(...)` becomes `Vobiz(api_key=, auth_token=)`/`client.calls.make_call(...)` (Python) - and `make_call` takes an explicit `auth_id`.

<CodeGroup>
  ```python Python theme={null}
  # --- Before: Plivo ---
  import plivo

  client = plivo.RestClient(
      auth_id="MA_PLIVO_ID",
      auth_token="plivo_token",
  )

  response = client.calls.create(
      from_="+911234567890",
      to_="+919876543210",                          # bulk: "a<b<c"
      answer_url="https://your-server.com/answer",
      answer_method="GET",
  )
  print(response.request_uuid)


  # --- After: Vobiz ---
  from vobiz import Vobiz

  client = Vobiz(api_key="MA_VOBIZ_ID", auth_token="vobiz_token")

  response = client.calls.make_call(
      auth_id="MA_VOBIZ_ID",                         # new: explicit account auth_id
      from_="+911234567890",
      to="+919876543210",                            # bulk: "a<b<c"  (unchanged)
      answer_url="https://your-server.com/answer",
      answer_method="GET",
  )
  print(response)
  ```

  ```javascript Node.js theme={null}
  // --- Before: Plivo ---
  const plivo = require('plivo');

  const client = new plivo.Client('MA_PLIVO_ID', 'plivo_token');

  client.calls.create(
    '+911234567890',
    '+919876543210',                                  // bulk: 'a<b<c'
    'https://your-server.com/answer',
    { answerMethod: 'GET' }
  ).then(res => console.log(res.requestUuid));


  // --- After: Vobiz ---
  import { VobizClient } from '@vobiz/sdk';

  const client = new VobizClient({ apiKey: 'MA_VOBIZ_ID', authToken: 'vobiz_token' });

  await client.calls.makeCall({
    auth_id: 'MA_VOBIZ_ID',                            // new: explicit account auth_id
    from: '+911234567890',
    to: '+919876543210',                               // bulk: 'a<b<c'  (unchanged)
    answer_url: 'https://your-server.com/answer',
    answer_method: 'GET',
  });
  ```
</CodeGroup>

The same applies to `ring_url`, `hangup_url`, `fallback_url`, `machine_detection`, `sip_headers`, and `time_limit`: pass them exactly as you did on Plivo.

## Raw HTTP equivalent

If you call the REST API directly instead of through an SDK, the change is also small: swap the base host to `https://api.vobiz.ai`, send your Vobiz `auth_id` in the path, and authenticate with the `X-Auth-ID` and `X-Auth-Token` headers. The path casing (`/Account/.../Call/`) is identical to Plivo's. See [Authentication & base URL](/docs/guides/plivo-to-vobiz/auth-and-base-url) for the exact credentials and host swap.

## Beyond parity

A few Vobiz resources have no direct Plivo counterpart and are worth knowing about as you migrate:

* **Trunk** - Vobiz exposes SIP trunking as a first-class resource, with credentials, IP-ACL, and origination-URI management, rather than folding it into the endpoint model.
* **DID cool-off** - released numbers enter a 15-day cool-off before they re-enter inventory, so plan number churn accordingly.
* **Granular capacity** - the account object surfaces per-account concurrency and calls-per-second (CPS) limits you can read and reason about directly.

## Next

<CardGroup cols={2}>
  <Card title="Migrate your XML" icon="code" href="/docs/guides/plivo-to-vobiz/xml-migration">
    Map Plivo XML verbs to VobizXML and update your answer-URL responses.
  </Card>

  <Card title="Plivo to Vobiz overview" icon="arrow-right-arrow-left" href="/docs/guides/plivo-to-vobiz">
    Back to the full migration guide and checklist.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.