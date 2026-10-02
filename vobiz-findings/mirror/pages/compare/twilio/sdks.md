> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Twilio Helper Libraries → Vobiz SDKs

> Migrate from Twilio's helper libraries (twilio-python, twilio-node, and the seven official languages) to the Vobiz SDKs: client init (Client(account_sid, auth_token) → Vobiz(api_key=, auth_token=) / VobizClient), install, method-name conventions, explicit auth_id, and the TwiML VoiceResponse builder → the bundled vobizxml builder - with side-by-side Python and Node examples.

Twilio ships **official helper libraries for seven languages** - C#/.NET, Java, Node.js, PHP, Python, Ruby, and Go - each wrapping the same REST resources and the TwiML `VoiceResponse` builder. Vobiz ships SDKs for the **same seven languages**, mirroring that resource layout and bundling a `vobizxml` builder in the box. Migrating is mostly a tab‑swap: change the constructor, pass your `auth_id` explicitly, rename a few methods, and swap the markup builder.

<Note>
  Set credentials once: `AUTH_ID` is your Vobiz Auth ID (`MA_…`) and `AUTH_TOKEN` is your Auth Token. In the Vobiz SDK, `api_key` **is** the Auth ID (sent as the `X-Auth-ID` header) and `auth_token` becomes `X-Auth-Token`. Every account‑scoped method takes that `auth_id` explicitly. Base URL: `https://api.vobiz.ai/api/v1`.
</Note>

## Seven-for-seven language parity

Every Twilio helper library has a Vobiz counterpart. Twilio installs from each language's package registry; Vobiz publishes source you clone from `github.com/vobiz-ai` and pin to a tag for reproducible builds.

| Language | Twilio helper library | Vobiz SDK |
| - | - | - |
| Python | `twilio` (PyPI) | [`vobiz-ai/Vobiz-Python-SDK`](https://github.com/vobiz-ai) |
| Node.js / TypeScript | `twilio` (npm) | [`vobiz-ai/Vobiz-Node-SDK`](https://github.com/vobiz-ai/Vobiz-Node-SDK) |
| Go | `github.com/twilio/twilio-go` | [`vobiz-ai/Vobiz-Go-SDK`](https://github.com/vobiz-ai/Vobiz-Go-SDK) |
| Ruby | `twilio-ruby` (RubyGems) | [`vobiz-ai/Vobiz-Ruby-SDK`](https://github.com/vobiz-ai/Vobiz-Ruby-SDK) |
| C# / .NET | `Twilio` (NuGet) | [`vobiz-ai/Vobiz-Csharp-sdk`](https://github.com/vobiz-ai/Vobiz-Csharp-sdk) |
| Java | `com.twilio.sdk:twilio` (Maven) | [`vobiz-ai/Vobiz-Java-SDK`](https://github.com/vobiz-ai/Vobiz-Java-SDK) |
| PHP | `twilio/sdk` (Composer) | [`vobiz-ai/Vobiz-PHP-SDK`](https://github.com/vobiz-ai/Vobiz-PHP-SDK) |

## Twilio → Vobiz mapping

The concepts line up one‑for‑one. What changes is the constructor keyword, the explicit `auth_id`, a few method names, and the name of the bundled XML builder.

| Concept | Twilio (`twilio-python` / `twilio-node`) | Vobiz SDK |
| - | - | - |
| Install (Python) | `pip install twilio` | `git clone github.com/vobiz-ai/Vobiz-Python-SDK` |
| Install (Node) | `npm install twilio` | `git clone github.com/vobiz-ai/Vobiz-Node-SDK` |
| Import (Python) | `from twilio.rest import Client` | `from vobiz import Vobiz` |
| Import (Node) | `const twilio = require('twilio')` | `import { VobizClient } from '@vobiz/sdk'` |
| Client init (Python) | `Client(account_sid, auth_token)` | `Vobiz(api_key=AUTH_ID, auth_token=AUTH_TOKEN)` |
| Client init (Node) | `twilio(accountSid, authToken)` | `new VobizClient({ apiKey, authToken })` |
| Auth transport | HTTP Basic (`account_sid`:`auth_token`) | Headers `X-Auth-ID` + `X-Auth-Token` |
| Account scoping | Implicit (bound to the client) | Explicit `auth_id` on every account‑scoped method |
| Place a call | `client.calls.create(to=, from_=, url=, method=)` | `client.calls.make_call(auth_id, from_=, to=, answer_url=, answer_method=)` |
| Fetch a live call | `client.calls(sid).fetch()` | `client.live_calls.get_live_call(auth_id, call_uuid, status='live')` |
| List calls | `client.calls.list(status=…)` | `client.live_calls.list_live_calls(auth_id, status='live')` · `client.cdr.list_cdrs(auth_id, …)` |
| Recordings | `client.recordings.list()/fetch()/delete()` | `client.recordings.list_recordings/get_recording/delete_recording(auth_id, …)` |
| Search & buy numbers | `client.available_phone_numbers(...).local.list()` + `incoming_phone_numbers.create()` | `client.phone_numbers.list_inventory_numbers(auth_id, country=)` + `purchase_from_inventory(auth_id, e164=)` |
| Sub‑accounts | `client.api.accounts.create()` | `client.sub_accounts.create_subaccount(auth_id, name=, email=, kyc_mode=)` |
| SIP trunking | Elastic SIP Trunking REST resources | First‑class `client.trunks.*`, `client.credentials.*`, `client.ip_access_control_list.*`, `client.origination_uri.*` |
| Markup builder (Python) | `from twilio.twiml.voice_response import VoiceResponse` | `from vobiz import vobizxml` |
| Builder root object | `VoiceResponse()` | `vobizxml.ResponseElement()` |
| Serialize to XML | `str(response)` | `resp.to_string()` |
| Webhook signature | `X-Twilio-Signature` (HMAC‑SHA1) via `RequestValidator` | Signature validation on your `answer_url` with your Auth Token |

## Install & initialize the client

Twilio's Python client wraps `account_sid` + `auth_token`; the Node client is a callable factory. Vobiz uses a keyword constructor where `api_key` **is** the Auth ID.

<CodeGroup>
  ```python Twilio · Python theme={null}
  # pip install twilio
  from twilio.rest import Client

  # account_sid + auth_token → HTTP Basic
  client = Client(ACCOUNT_SID, AUTH_TOKEN)
  ```

  ```python Vobiz · Python theme={null}
  # git clone github.com/vobiz-ai/Vobiz-Python-SDK
  from vobiz import Vobiz

  # api_key IS the Auth ID (X-Auth-ID); auth_token → X-Auth-Token
  client = Vobiz(api_key=AUTH_ID, auth_token=AUTH_TOKEN)
  ```

  ```javascript Twilio · Node theme={null}
  // npm install twilio
  const twilio = require('twilio');

  const client = twilio(ACCOUNT_SID, AUTH_TOKEN);
  ```

  ```javascript Vobiz · Node theme={null}
  // git clone github.com/vobiz-ai/Vobiz-Node-SDK
  import { VobizClient } from '@vobiz/sdk';

  const client = new VobizClient({ apiKey: AUTH_ID, authToken: AUTH_TOKEN });
  ```
</CodeGroup>

## Method-name conventions & the explicit `auth_id`

Twilio's methods are terse CRUD verbs (`create`, `fetch`, `list`) on a resource bound to the client's account. Vobiz spells out the intent (`make_call`, `get_live_call`, `list_recordings`) and threads your `auth_id` through as the first argument - so multi‑account and sub‑account code is unambiguous at the call site.

<CodeGroup>
  ```python Twilio · Python theme={null}
  call = client.calls.create(
      to='+919876543210',
      from_='+14155551234',
      url='https://example.com/answer.xml',
      method='POST',
  )
  print(call.sid)

  rec = client.recordings.list(limit=20)
  ```

  ```python Vobiz · Python theme={null}
  res = client.calls.make_call(
      auth_id=AUTH_ID,                 # explicit account Auth ID
      from_='+14155551234',
      to='+919876543210',
      answer_url='https://example.com/answer.xml',
      answer_method='POST',            # required
  )
  print(res)                           # includes call_uuid

  rec = client.recordings.list_recordings(AUTH_ID)
  ```

  ```javascript Twilio · Node theme={null}
  const call = await client.calls.create({
    to: '+919876543210',
    from: '+14155551234',
    url: 'https://example.com/answer.xml',
    method: 'POST',
  });
  console.log(call.sid);
  ```

  ```javascript Vobiz · Node theme={null}
  const res = await client.calls.makeCall({
    auth_id: AUTH_ID,                  // explicit account Auth ID
    from: '+14155551234',
    to: '+919876543210',
    answer_url: 'https://example.com/answer.xml',
    answer_method: 'POST',
  });
  ```
</CodeGroup>

<Tip>
  Twilio lets you inline TwiML via the `twiml=` parameter. On Vobiz you host the same instructions at your `answer_url` and return **VobizXML**.
</Tip>

## TwiML `VoiceResponse` → the bundled `vobizxml` builder

Twilio's helper libraries include a `VoiceResponse` builder for generating TwiML. Every Vobiz SDK bundles an equivalent `vobizxml` builder: start from `ResponseElement()`, chain `add_*` methods, and serialize with `to_string()`. TwiML's `<Say>` maps to VobizXML's `<Speak>` and `<Pause>` maps to `<Wait>`; `<Play> <Gather> <Dial> <Record> <Hangup> <Redirect> <Conference> <Stream>` keep their names.

<CodeGroup>
  ```python Twilio · Python theme={null}
  from twilio.twiml.voice_response import VoiceResponse, Gather

  resp = VoiceResponse()
  gather = Gather(action='https://example.com/menu', method='POST', num_digits=1)
  gather.say('Press 1 for sales, 2 for support.', voice='woman', language='en-US')
  resp.append(gather)
  resp.say('We did not get your input. Goodbye.')
  resp.hangup()
  print(str(resp))
  ```

  ```python Vobiz · Python theme={null}
  from vobiz import vobizxml

  resp = vobizxml.ResponseElement()
  gather = resp.add_gather(action='https://example.com/menu', method='POST',
                           input_type='dtmf', num_digits=1)
  gather.add_speak('Press 1 for sales, 2 for support.', voice='WOMAN', language='en-US')
  resp.add_speak('We did not get your input. Goodbye.')
  resp.add_hangup()
  print(resp.to_string())
  ```

  ```javascript Twilio · Node theme={null}
  const { twiml } = require('twilio');

  const resp = new twiml.VoiceResponse();
  const gather = resp.gather({ action: 'https://example.com/menu', method: 'POST', numDigits: 1 });
  gather.say({ voice: 'woman', language: 'en-US' }, 'Press 1 for sales, 2 for support.');
  resp.say('We did not get your input. Goodbye.');
  resp.hangup();
  console.log(resp.toString());
  ```

  ```javascript Vobiz · Node theme={null}
  import { vobizxml } from '@vobiz/sdk';

  const resp = new vobizxml.ResponseElement();
  const gather = resp.addGather({ action: 'https://example.com/menu', method: 'POST',
                                 inputType: 'dtmf', numDigits: 1 });
  gather.addSpeak('Press 1 for sales, 2 for support.', { voice: 'WOMAN', language: 'en-US' });
  resp.addSpeak('We did not get your input. Goodbye.');
  resp.addHangup();
  console.log(resp.toString());
  ```
</CodeGroup>

<Note>
  Vobiz `<Gather>` uses `inputType`, `executionTimeout`, `digitEndTimeout`, `numDigits`, and `finishOnKey`. Use `executionTimeout` for the overall input window; `timeout` in VobizXML belongs to `<Dial>`/`<Number>` (ring timeout). See [`/xml/gather`](/docs/xml/gather) for the full attribute list.
</Note>

The full `vobizxml` verb set mirrors the builder methods you already know from TwiML: `add_speak`, `add_play`, `add_wait`, `add_gather`, `add_dial` (with `add_number` / `add_user`), `add_record`, `add_conference`, `add_dtmf`, `add_redirect`, `add_hangup`, `add_preanswer`, and `add_stream`.

## Serve the answer URL (Flask / Express)

When Vobiz rings the destination it fetches your `answer_url` and executes the returned XML - the same request/response model as a Twilio webhook. Build the response with `vobizxml` and send it as `application/xml`.

<CodeGroup>
  ```python Twilio · Flask theme={null}
  from flask import Flask, Response
  from twilio.twiml.voice_response import VoiceResponse

  app = Flask(__name__)

  @app.route('/answer', methods=['POST'])
  def answer():
      resp = VoiceResponse()
      resp.say('Hello from Twilio.')
      return Response(str(resp), mimetype='application/xml')
  ```

  ```python Vobiz · Flask theme={null}
  from flask import Flask, Response
  from vobiz import vobizxml

  app = Flask(__name__)

  @app.route('/answer', methods=['POST'])
  def answer():
      resp = vobizxml.ResponseElement()
      resp.add_speak('Hello from Vobiz.')
      return Response(resp.to_string(), mimetype='application/xml')
  ```

  ```javascript Vobiz · Express theme={null}
  import express from 'express';
  import { vobizxml } from '@vobiz/sdk';

  const app = express();

  app.post('/answer', (req, res) => {
    const resp = new vobizxml.ResponseElement();
    resp.addSpeak('Hello from Vobiz.');
    res.type('application/xml').send(resp.toString());
  });
  ```
</CodeGroup>

## Key differences

* **Same seven languages, cloned from GitHub.** Twilio publishes to each language registry (PyPI, npm, NuGet, Maven, RubyGems, Composer, Go modules); Vobiz publishes the same seven SDKs as source under `github.com/vobiz-ai`. Clone the repo for your language and pin to a tag or commit for reproducible builds.
* **Client init: keyword constructor, headers not Basic.** Twilio's `Client(account_sid, auth_token)` sends HTTP Basic. Vobiz's `Vobiz(api_key=AUTH_ID, auth_token=AUTH_TOKEN)` sends `X-Auth-ID` + `X-Auth-Token`. Note the constructor keyword is `api_key=` (Python) / `apiKey:` (Node) - and that value **is** your Auth ID.
* **Explicit `auth_id` on every account‑scoped method.** Twilio binds the account to the client and infers it. Vobiz passes the Auth ID (`MA_…`) as the first argument, which makes multi‑account and sub‑account code unambiguous at the call site.
* **Intent‑named methods.** Twilio's generic `create`/`fetch`/`list` become `make_call`, `get_live_call`, `list_recordings`, `start_recording`, and `hangup_call`, so each call reads like the action it performs.
* **The TwiML builder ports directly.** `VoiceResponse()` → `vobizxml.ResponseElement()`, `str(response)` → `resp.to_string()`, and the verbs map cleanly - `<Say>`→`<Speak>`, `<Pause>`→`<Wait>`, with `<Play> <Gather> <Dial> <Record> <Hangup> <Redirect> <Conference> <Stream>` unchanged.
* **First‑class SIP trunking and sub‑account KYC.** Vobiz surfaces `trunks`, `credentials`, `ip_access_control_list`, and `origination_uri` as dedicated SDK resources, and `sub_account_kyc` for India KYC (PAN / GST / CIN / DigiLocker / hosted sessions) - all reachable from the same client you use for calls.
* **Signed webhooks work the same way.** Both platforms sign inbound webhook requests with your Auth Token; validate the signature on your `answer_url` the same way you validated `X-Twilio-Signature` with Twilio's `RequestValidator`.

Need the per‑resource method map for calls and live‑call control? See [Twilio Voice Call API → Vobiz](/docs/compare/twilio/voice-call-api), or the [Twilio → Vobiz overview](/docs/compare/twilio/overview) for the full migration order and at‑a‑glance matrix.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.