> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Plivo vs Vobiz: Server SDKs & XML Builder Migration

> Port your Plivo server SDK code to Vobiz: 7-for-7 language parity, registry installs vs git-clone, client init (RestClient to Vobiz/VobizClient), method-name differences, and plivoxml to vobizxml.

Plivo and Vobiz ship server SDKs for the **same seven languages**, and the Vobiz SDKs mirror Plivo's resource layout and XML-builder shape. What changes when you migrate: you **git-clone** the Vobiz SDKs from `github.com/vobiz-ai` (no registry install), you construct the client with `X-Auth-ID`/`X-Auth-Token` headers instead of HTTP Basic, and a handful of **method names** differ (`calls.create` → `calls.make_call`, plus an explicit `auth_id`).

## Client init & method-name mapping

| Plivo SDK (Python) | Vobiz SDK (Python) |
| - | - |
| `import plivo` / `plivo.RestClient(auth_id, auth_token)` | `from vobiz import Vobiz` / `Vobiz(api_key=auth_id, auth_token=…)` |
| `new plivo.Client(authId, authToken)` (Node) | `new VobizClient({ apiKey, authToken })` (Node) |
| `client.calls.create(from_, to, answer_url=)` | `client.calls.make_call(auth_id, from_, to, answer_url=)` |
| `client.calls.get(call_uuid)` | `client.live_calls.get_live_call(auth_id, call_uuid)` |
| `client.calls.get_all()` / `.list()` | `client.live_calls.list_live_calls(auth_id)` |
| `client.calls.delete(call_uuid)` | `client.live_calls.hangup_call(auth_id, call_uuid)` |
| `client.calls.play(...)` / `.speak(...)` / `.send_digits(...)` | `client.play_audio.call(...)` / `client.speak_text.call(...)` / `client.dtmf.send_dtmf(...)` |
| `client.calls.record(...)` / `.stop_record(...)` | `client.record_calls.start_recording(...)` / `.stop_recording(...)` |
| `client.recordings.get / list / delete` | `client.recordings.get_recording / list_recordings / delete_recording` |
| `client.applications.create / get / list / update / delete` | `client.applications.create_application / retrieve_application / list_applications / update_application / delete_application` |
| `client.numbers.search / buy / list / delete` | `client.phone_numbers.list_inventory_numbers / purchase_from_inventory / list_numbers / unrent_number` |
| `client.conferences.*` / member ops | `client.conference.*` (member ops) + `client.conference_members.mute_member / unmute_member` |
| `client.endpoints.*` | `client.endpoints.*` (+ first-class `client.trunks.*`) |
| `client.get_account()` | `client.account.retrieve_account()` |
| `from plivo import plivoxml` | `from vobiz import vobizxml` |
| `plivoxml.ResponseElement()` / `add_get_digits(...)` / `to_string()` | `vobizxml.ResponseElement()` / `add_gather(...)` / `to_string()` |

CDRs live under `client.cdr.*` on Vobiz (Plivo folds completed-call lookups into `calls.get`). For the verb-by-verb XML mapping see [Convert PlivoXML to VobizXML](/docs/guides/plivo-to-vobiz/xml-migration).

## Before / after: client init + outbound call

The call parameters (`from`, `to`, `answer_url`, `answer_method`, etc.) carry over unchanged. What changes is the constructor, the method name, and the added `auth_id`.

<CodeGroup>
  ```python Python theme={null}
  # --- Before: Plivo ---
  import plivo
  client = plivo.RestClient(auth_id="MA_PLIVO_ID", auth_token="plivo_token")

  resp = client.calls.create(
      from_="14155551234",
      to="+919876543210",                       # bulk: "a<b<c"
      answer_url="https://example.com/answer",
      answer_method="POST",
  )
  print(resp.request_uuid)

  # --- After: Vobiz ---
  from vobiz import Vobiz
  client = Vobiz(api_key="MA_VOBIZ_ID", auth_token="vobiz_token")

  resp = client.calls.make_call(
      auth_id="MA_VOBIZ_ID",                     # new: explicit account auth_id
      from_="14155551234",
      to="+919876543210",                        # bulk: "a<b<c"  (unchanged)
      answer_url="https://example.com/answer",
      answer_method="POST",
  )
  print(resp)                                    # includes call_uuid
  ```

  ```javascript Node.js theme={null}
  // --- Before: Plivo ---
  const plivo = require('plivo');
  const client = new plivo.Client('MA_PLIVO_ID', 'plivo_token');

  client.calls.create(
    '14155551234',
    '+919876543210',                             // bulk: 'a<b<c'
    'https://example.com/answer',
    { answerMethod: 'POST' }
  ).then(res => console.log(res.requestUuid));

  // --- After: Vobiz ---
  import { VobizClient } from '@vobiz/sdk';
  const client = new VobizClient({ apiKey: 'MA_VOBIZ_ID', authToken: 'vobiz_token' });

  await client.calls.makeCall({
    auth_id: 'MA_VOBIZ_ID',                       // new: explicit account auth_id
    from: '14155551234',
    to: '+919876543210',                          // bulk: 'a<b<c'  (unchanged)
    answer_url: 'https://example.com/answer',
    answer_method: 'POST',
  });
  ```
</CodeGroup>

## Key differences & gotchas

* **Install is git-clone, not registry.** Clone `vobiz-ai/Vobiz-<Language>-SDK` and install from the checkout (Go is the exception: `go get github.com/vobiz-ai/Vobiz-Go-SDK`). Pin to a tag/commit for reproducible builds.
* **Auth is headers, not Basic.** Vobiz sends `api_key` as `X-Auth-ID` and `auth_token` as `X-Auth-Token`; the constructor keyword is `api_key=` (Python) / `apiKey:` (Node), not `auth_id`.
* **Every account-scoped method takes an explicit `auth_id`** - Plivo infers it from the credential.
* **Purpose-built call resources.** Vobiz uses `live_calls` for in-progress calls and `cdr` for completed-call records - each resource is dedicated to its job.
* **`Gather` uses `executionTimeout`, never `timeout`** - the most common porting mistake. `timeout` in VobizXML belongs only to `<Dial>`/`<Number>` (ring timeout).

<CardGroup cols={2}>
  <Card title="Endpoint & SDK mapping" icon="arrow-right-arrow-left" href="/docs/guides/plivo-to-vobiz/endpoint-mapping">
    The full REST resource and method mapping, with the make-call contract.
  </Card>

  <Card title="Convert PlivoXML to VobizXML" icon="code" href="/docs/guides/plivo-to-vobiz/xml-migration">
    Verb-by-verb XML mapping and the GetDigits/GetInput to Gather rename.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.