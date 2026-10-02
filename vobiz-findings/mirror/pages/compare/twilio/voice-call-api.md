> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Twilio Voice Call API → Vobiz

> Migrate Twilio Programmable Voice outbound calls and live call control to Vobiz. Map client.calls.create() to calls.make_call(), fetch/list calls to live_calls + cdr, and client.calls(sid).update() to Vobiz's dedicated in-call resources - with side-by-side Python and Node examples.

Twilio's Programmable Voice puts outbound calling and live call control on one `client.calls` resource. Vobiz keeps the same call flow and gives each concern a **dedicated, explicitly named resource** - `calls.make_call` to place a call, `live_calls` to fetch/list/hang up in‑flight calls, and one purpose‑built resource per in‑call action (`play_audio`, `speak_text`, `dtmf`, `record_calls`). Migrating is mostly a tab‑swap: rename the method, pass your `auth_id` explicitly, and keep the same answer‑URL webhook.

<Note>
  Set credentials once: `AUTH_ID` is your Vobiz Auth ID (`MA_…`) and `AUTH_TOKEN` is your Auth Token. In the Vobiz SDK, `api_key` **is** the Auth ID (sent as the `X-Auth-ID` header) and `auth_token` becomes `X-Auth-Token`. Every account‑scoped method takes that `auth_id` as its first argument. Base URL: `https://api.vobiz.ai/api/v1`.
</Note>

## Twilio → Vobiz mapping

Twilio grounds every outbound call in `client.calls.create()` and every live‑call change in `client.calls(sid).update()`. Vobiz splits those responsibilities into focused resources so each call is easy to read and test.

| Task | Twilio (`twilio-python` / `twilio-node`) | Vobiz SDK |
| - | - | - |
| Create client | `Client(account_sid, auth_token)` | `Vobiz(api_key=AUTH_ID, auth_token=AUTH_TOKEN)` |
| Place outbound call | `client.calls.create(to=, from_=, url=, method=)` | `client.calls.make_call(auth_id, from_=, to=, answer_url=, answer_method=)` |
| Answer webhook fetch | `url` + `method` on the call | `answer_url` + `answer_method` on the call |
| Inline instructions | `twiml="<Response>…"` | Serve VobizXML from `answer_url` (build with `vobizxml`) |
| Fetch one call | `client.calls(sid).fetch()` | Live: `client.live_calls.get_live_call(auth_id, call_uuid, status='live')` · History: `client.cdr.get_cdr(auth_id, call_id)` |
| List calls | `client.calls.list(status=…)` | Live: `client.live_calls.list_live_calls(auth_id, status='live')` · History: `client.cdr.list_cdrs(auth_id, …)` |
| Queued calls | `client.calls.list(status='queued')` | `client.live_calls.list_queued_calls(auth_id)` / `get_queued_call` |
| Redirect a live call | `client.calls(sid).update(url=, method=)` | Return `<Redirect>` from your answer flow, or drive the leg with the in‑call resources below |
| Play audio on live call | `client.calls(sid).update(twiml="<Play>…")` | `client.play_audio.call(auth_id, call_uuid, urls=)` |
| Speak text on live call | `client.calls(sid).update(twiml="<Say>…")` | `client.speak_text.call(auth_id, call_uuid, text=, voice=, language=)` |
| Send DTMF on live call | `sendDigits` at create time | `client.dtmf.send_dtmf(auth_id, call_uuid, digits=)` |
| Start / stop recording | `client.calls(sid).recordings.create()` | `client.record_calls.start_recording(auth_id, call_uuid, …)` / `stop_recording` |
| End a live call | `client.calls(sid).update(status='completed')` | `client.live_calls.hangup_call(auth_id, call_uuid)` |
| Recording resources | `client.recordings.list()/fetch()/delete()` | `client.recordings.list_recordings/get_recording/delete_recording(auth_id, …)` |
| Answer‑TwiML verbs | `<Say> <Play> <Gather> <Dial> <Record> <Hangup> <Redirect> <Pause>` | `<Speak> <Play> <Gather> <Dial> <Record> <Hangup> <Redirect> <Wait>` |
| Webhook auth | `X-Twilio-Signature` (HMAC‑SHA1) via `RequestValidator` | Signature validation on your `answer_url` with your Auth Token |

## Place an outbound call

Twilio requires exactly one of `url`, `twiml`, or `application_sid`; the common case is `url` + `method` pointing at your answer webhook. Vobiz uses `answer_url` + `answer_method` for the identical purpose.

<CodeGroup>
  ```python Twilio · Python theme={null}
  from twilio.rest import Client

  client = Client(ACCOUNT_SID, AUTH_TOKEN)

  call = client.calls.create(
      to='+919876543210',
      from_='+14155551234',
      url='https://example.com/answer.xml',
      method='POST',
  )
  print(call.sid)
  ```

  ```python Vobiz · Python theme={null}
  from vobiz import Vobiz

  client = Vobiz(api_key=AUTH_ID, auth_token=AUTH_TOKEN)

  res = client.calls.make_call(
      auth_id=AUTH_ID,
      from_='+14155551234',
      to='+919876543210',
      answer_url='https://example.com/answer.xml',
      answer_method='POST',
  )
  ```

  ```javascript Twilio · Node theme={null}
  const twilio = require('twilio');
  const client = twilio(ACCOUNT_SID, AUTH_TOKEN);

  const call = await client.calls.create({
    to: '+919876543210',
    from: '+14155551234',
    url: 'https://example.com/answer.xml',
    method: 'POST',
  });
  console.log(call.sid);
  ```

  ```javascript Vobiz · Node theme={null}
  import { VobizClient } from '@vobiz/sdk';

  const client = new VobizClient({ apiKey: AUTH_ID, authToken: AUTH_TOKEN });

  await client.calls.makeCall({
    auth_id: AUTH_ID,
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

## Answer the call with markup

When Vobiz rings the destination it fetches your `answer_url` and executes the returned XML - the same request/response model as a Twilio webhook. TwiML's `<Say>`/`<Gather>` become VobizXML's `<Speak>`/`<Gather>`; the `vobizxml` builder mirrors the ergonomics you already use.

<CodeGroup>
  ```python Twilio · Python theme={null}
  from twilio.twiml.voice_response import VoiceResponse, Gather

  resp = VoiceResponse()
  g = Gather(action='https://example.com/menu', method='POST', num_digits=1)
  g.say('Press 1 for sales, 2 for support.')
  resp.append(g)
  print(str(resp))
  ```

  ```python Vobiz · Python theme={null}
  from vobiz import vobizxml

  resp = vobizxml.ResponseElement()
  menu = resp.add_gather(action='https://example.com/menu', method='POST',
                         input_type='dtmf', num_digits=1)
  menu.add_speak('Press 1 for sales, 2 for support.')
  print(resp.to_string())
  ```

  ```javascript Vobiz · Node theme={null}
  import { vobizxml } from '@vobiz/sdk';

  const resp = new vobizxml.ResponseElement();
  const menu = resp.addGather({ action: 'https://example.com/menu', method: 'POST',
                               inputType: 'dtmf', numDigits: 1 });
  menu.addSpeak('Press 1 for sales, 2 for support.');
  console.log(resp.toString());
  ```
</CodeGroup>

<Note>
  Vobiz `<Gather>` uses `inputType`, `executionTimeout`, `digitEndTimeout`, `numDigits`, and `finishOnKey`. See [`/xml/gather`](/docs/xml/gather) for the full attribute list.
</Note>

## Control a live call

This is the biggest shape change - and the one that makes Vobiz code clearer. Twilio funnels every mid‑call action back through `client.calls(sid).update(...)`, either redirecting to fresh TwiML or setting `status`. Vobiz gives each action its own resource keyed by `(auth_id, call_uuid)`, so the intent is on the method name.

<CodeGroup>
  ```python Twilio · Python theme={null}
  sid = 'CA0123456789abcdef0123456789abcdef'

  # Redirect the live call to new TwiML
  client.calls(sid).update(
      url='https://example.com/next.xml', method='POST')

  # Play / speak by redirecting to TwiML that contains <Play>/<Say>
  client.calls(sid).update(
      twiml='<Response><Play>https://example.com/hold.mp3</Play></Response>')
  client.calls(sid).update(
      twiml='<Response><Say>Please hold.</Say></Response>')

  # End the call
  client.calls(sid).update(status='completed')
  ```

  ```python Vobiz · Python theme={null}
  call_uuid = 'call-uuid-here'

  # Each in-call action is its own resource
  client.play_audio.call(AUTH_ID, call_uuid, urls='https://example.com/hold.mp3')
  client.speak_text.call(AUTH_ID, call_uuid, text='Please hold.',
                         voice='WOMAN', language='en-US')
  client.dtmf.send_dtmf(AUTH_ID, call_uuid, digits='1234')
  client.record_calls.start_recording(AUTH_ID, call_uuid)

  # End the call
  client.live_calls.hangup_call(AUTH_ID, call_uuid)
  ```

  ```javascript Twilio · Node theme={null}
  const sid = 'CA0123456789abcdef0123456789abcdef';

  await client.calls(sid).update({ url: 'https://example.com/next.xml', method: 'POST' });
  await client.calls(sid).update({
    twiml: '<Response><Play>https://example.com/hold.mp3</Play></Response>' });
  await client.calls(sid).update({ status: 'completed' });
  ```

  ```javascript Vobiz · Node theme={null}
  const callUuid = 'call-uuid-here';

  await client.playAudio.call(AUTH_ID, callUuid, { urls: 'https://example.com/hold.mp3' });
  await client.speakText.call(AUTH_ID, callUuid, { text: 'Please hold.',
                              voice: 'WOMAN', language: 'en-US' });
  await client.dtmf.sendDtmf(AUTH_ID, callUuid, { digits: '1234' });
  await client.recordCalls.startRecording(AUTH_ID, callUuid);
  await client.liveCalls.hangupCall(AUTH_ID, callUuid);
  ```
</CodeGroup>

## Fetch and list calls

Twilio's `client.calls.list()` and `client.calls(sid).fetch()` return both live and completed calls from one resource, filtered by `status`. Vobiz separates the two lifecycles: `live_calls` for anything in flight (`status='live'`, plus queued‑call helpers) and `cdr` for completed‑call history with rich filters.

<CodeGroup>
  ```python Twilio · Python theme={null}
  # Live / in-progress
  one = client.calls('CA0123...').fetch()
  live = client.calls.list(status='in-progress')

  # Completed history
  done = client.calls.list(status='completed', limit=20)
  ```

  ```python Vobiz · Python theme={null}
  # Live / in-progress
  one = client.live_calls.get_live_call(AUTH_ID, 'call-uuid-here', status='live')
  live = client.live_calls.list_live_calls(AUTH_ID, status='live')
  queued = client.live_calls.list_queued_calls(AUTH_ID)

  # Completed history (CDR)
  done = client.cdr.list_cdrs(AUTH_ID, start_date='2026-06-01',
                              end_date='2026-06-30', call_direction='outbound')
  ```

  ```javascript Vobiz · Node theme={null}
  const one = await client.liveCalls.getLiveCall(AUTH_ID, 'call-uuid-here', { status: 'live' });
  const live = await client.liveCalls.listLiveCalls(AUTH_ID, { status: 'live' });
  const done = await client.cdr.listCdrs(AUTH_ID, {
    start_date: '2026-06-01', end_date: '2026-06-30', call_direction: 'outbound' });
  ```
</CodeGroup>

## Key differences

* **The answer webhook maps 1:1.** Twilio's `url` + `method` become Vobiz's `answer_url` + `answer_method`, and `answer_method` is passed explicitly on every `make_call`. Your web framework returns markup exactly as before - just VobizXML instead of TwiML.
* **Explicit `auth_id` on every call.** Twilio scopes requests to the account behind the client. Vobiz passes the Auth ID (`MA_…`) as the first argument of each account‑scoped method, which makes multi‑account and sub‑account code unambiguous at the call site.
* **In‑call actions are first‑class resources.** Where Twilio re‑enters `client.calls(sid).update(...)` for every mid‑call change, Vobiz exposes `play_audio.call`, `speak_text.call`, `dtmf.send_dtmf`, `record_calls.start_recording`, and `live_calls.hangup_call`. Each method name states the action, so live‑call logic reads top‑to‑bottom.
* **Live vs. completed are separate lenses.** Vobiz `live_calls` covers in‑flight and queued legs; the dedicated `cdr` resource covers completed‑call history with filters like `from_number`, `to_number`, `call_direction`, `hangup_cause`, and `bridge_uuid` - purpose‑built for reporting.
* **Redirect the natural way.** An imperative Twilio redirect (`update(url=…)`) is expressed on Vobiz by returning `<Redirect>` from your answer flow, keeping call routing declarative and versionable alongside the rest of your XML.
* **Familiar verb set.** TwiML's core verbs have direct VobizXML counterparts - `<Say>`→`<Speak>`, `<Pause>`→`<Wait>`, and `<Play> <Gather> <Dial> <Record> <Hangup> <Redirect> <Conference> <Stream>` keep their names - so answer documents port with minimal edits.
* **Signed webhooks.** Both platforms sign inbound webhook requests with your Auth Token; validate the signature on your `answer_url` the same way you validated `X-Twilio-Signature` with Twilio's `RequestValidator`.

Need a resource that isn't here? See the full [Twilio → Vobiz overview](/docs/compare/twilio/overview) for the migration order and the at‑a‑glance matrix across numbers, SIP trunking, conferences, and CDR.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.