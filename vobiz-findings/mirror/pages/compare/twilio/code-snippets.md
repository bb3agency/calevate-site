> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Twilio → Vobiz: Code Snippets for Common Tasks

> Side-by-side Twilio and Vobiz code for the most common voice tasks - make an outbound call, answer with XML, control a live call, search a number, and validate webhooks. Copy the Vobiz tab and you're migrated.

Refactoring a Twilio app to Vobiz is mostly a tab-swap: same call flow, a few renamed methods, and an explicit `auth_id`. Each task below shows the **Twilio** code and the equivalent **Vobiz** code in Python and Node - copy the Vobiz tab.

<Note>
  Set your credentials once: `AUTH_ID` is your Vobiz Auth ID (`MA_…`), `AUTH_TOKEN` is your Auth Token. In the Vobiz SDK, `api_key` **is** the Auth ID, and every account-scoped method takes that `auth_id` explicitly.
</Note>

## Set up the client

<CodeGroup>
  ```python Twilio · Python theme={null}
  from twilio.rest import Client

  client = Client(ACCOUNT_SID, AUTH_TOKEN)
  ```

  ```python Vobiz · Python theme={null}
  from vobiz import Vobiz

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

## Make an outbound call

The classic "change a few lines" migration: `calls.create` → `calls.make_call`, add `auth_id`, and `url`/`method` → `answer_url`/`answer_method`.

<CodeGroup>
  ```python Twilio · Python theme={null}
  call = client.calls.create(
      to='+919876543210',
      from_='+14155551234',
      url='https://example.com/answer.xml',
      method='POST',
  )
  print(call.sid)
  ```

  ```python Vobiz · Python theme={null}
  res = client.calls.make_call(
      auth_id=AUTH_ID,
      from_='+14155551234',
      to='+919876543210',
      answer_url='https://example.com/answer.xml',
      answer_method='POST',
  )
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
  await client.calls.makeCall({
    auth_id: AUTH_ID,
    from: '+14155551234',
    to: '+919876543210',
    answer_url: 'https://example.com/answer.xml',
    answer_method: 'POST',
  });
  ```
</CodeGroup>

## Answer a call with XML (TTS + menu)

The XML builder maps verb-for-verb: `VoiceResponse()` → `ResponseElement()`, and `Gather` keeps its name. On the builder, `response.gather(...)` → `resp.add_gather(...)`, nested `.say()` → `.add_speak()`, and `str(response)` → `resp.to_string()`. Twilio's `input`/`timeout` become Vobiz's `input_type`/`execution_timeout`; `num_digits` carries over unchanged.

<CodeGroup>
  ```python Twilio · Python theme={null}
  from twilio.twiml.voice_response import VoiceResponse, Gather

  resp = VoiceResponse()
  menu = resp.gather(input='dtmf', num_digits=1, timeout=10,
                     action='https://example.com/menu', method='POST')
  menu.say('Press 1 for sales, 2 for support.')
  print(str(resp))
  ```

  ```python Vobiz · Python theme={null}
  from vobiz import vobizxml

  resp = vobizxml.ResponseElement()
  menu = resp.add_gather(input_type='dtmf', num_digits=1, execution_timeout=10,
                         action='https://example.com/menu', method='POST')
  menu.add_speak('Press 1 for sales, 2 for support.')
  print(resp.to_string())
  ```

  ```javascript Twilio · Node theme={null}
  const { twiml } = require('twilio');

  const resp = new twiml.VoiceResponse();
  const menu = resp.gather({ input: 'dtmf', numDigits: 1, timeout: 10, action: 'https://example.com/menu', method: 'POST' });
  menu.say('Press 1 for sales, 2 for support.');
  console.log(resp.toString());
  ```

  ```javascript Vobiz · Node theme={null}
  import { vobizxml } from '@vobiz/sdk';

  const resp = new vobizxml.ResponseElement();
  const menu = resp.addGather({ inputType: 'dtmf', numDigits: 1, executionTimeout: 10, action: 'https://example.com/menu', method: 'POST' });
  menu.addSpeak('Press 1 for sales, 2 for support.');
  console.log(resp.toString());
  ```
</CodeGroup>

Vobiz emits the same document shape your TwiML app already returns - see the full verb table in [TwiML → VobizXML](/docs/compare/twilio/twiml-to-vobizxml), and validate the incoming request on your answer URL as shown in [Webhooks](/docs/compare/twilio/webhooks).

## Serve the answer URL (Flask / FastAPI / Express)

When Vobiz rings your number it fetches your `answer_url` over HTTP - return the VobizXML from any web framework, exactly as your Twilio voice URL returned TwiML. Just build the response with `vobizxml` instead of `VoiceResponse`, and send it as `application/xml`.

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

  ```python Vobiz · FastAPI theme={null}
  from fastapi import FastAPI, Response
  from vobiz import vobizxml

  app = FastAPI()

  @app.post('/answer')
  async def answer():
      resp = vobizxml.ResponseElement()
      resp.add_speak('Hello from Vobiz.')
      return Response(content=resp.to_string(), media_type='application/xml')
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

<Tip>
  Building the XML is the only thing that changes - swap `VoiceResponse()`/`str(resp)` for `vobizxml.ResponseElement()`/`resp.to_string()` and keep the same route. The full verb map is in [TwiML → VobizXML](/docs/compare/twilio/twiml-to-vobizxml), and validating the signed request on this endpoint is covered in [Webhooks](/docs/compare/twilio/webhooks).
</Tip>

## Control a live call

This is the biggest shape change - and the one that makes Vobiz code clearer. Twilio funnels every mid-call action back through `client.calls(sid).update(...)` (redirecting to fresh TwiML or setting `status`) and starts recording with `client.calls(sid).recordings.create()`. Vobiz gives each action its own resource keyed by `(auth_id, call_uuid)`, so the intent lives on the method name.

| Action | Twilio | Vobiz |
| - | - | - |
| Play audio | `client.calls(sid).update(twiml="<Play>…")` | `client.play_audio.call(auth_id, call_uuid, urls=)` |
| Speak text | `client.calls(sid).update(twiml="<Say>…")` | `client.speak_text.call(auth_id, call_uuid, text=)` |
| Send DTMF | `client.calls(sid).update(twiml="<Play digits=…>")` | `client.dtmf.send_dtmf(auth_id, call_uuid, digits=)` |
| Start recording | `client.calls(sid).recordings.create()` | `client.record_calls.start_recording(auth_id, call_uuid)` |
| Hang up | `client.calls(sid).update(status="completed")` | `client.live_calls.hangup_call(auth_id, call_uuid)` |

<CodeGroup>
  ```python Twilio · Python theme={null}
  # Every mid-call change re-enters client.calls(sid).update(...)
  client.calls(sid).update(                                            # play audio
      twiml='<Response><Play>https://example.com/hold.mp3</Play></Response>')
  client.calls(sid).update(                                            # speak text
      twiml='<Response><Say>Please hold.</Say></Response>')
  client.calls(sid).update(                                            # send DTMF
      twiml='<Response><Play digits="1234"></Play></Response>')
  client.calls(sid).recordings.create()                                # start recording
  client.calls(sid).update(status='completed')                         # hang up
  ```

  ```python Vobiz · Python theme={null}
  client.play_audio.call(AUTH_ID, CALL_UUID, urls='https://example.com/hold.mp3')   # play audio
  client.speak_text.call(AUTH_ID, CALL_UUID, text='Please hold.')                   # speak text
  client.dtmf.send_dtmf(AUTH_ID, CALL_UUID, digits='1234')                          # send DTMF
  client.record_calls.start_recording(AUTH_ID, CALL_UUID)                           # start recording
  client.live_calls.hangup_call(AUTH_ID, CALL_UUID)                                 # hang up
  ```

  ```javascript Twilio · Node theme={null}
  await client.calls(sid).update({
    twiml: '<Response><Play>https://example.com/hold.mp3</Play></Response>' });
  await client.calls(sid).update({
    twiml: '<Response><Say>Please hold.</Say></Response>' });
  await client.calls(sid).update({
    twiml: '<Response><Play digits="1234"></Play></Response>' });
  await client.calls(sid).recordings.create();
  await client.calls(sid).update({ status: 'completed' });
  ```

  ```javascript Vobiz · Node theme={null}
  await client.playAudio.call(AUTH_ID, CALL_UUID, { urls: 'https://example.com/hold.mp3' });
  await client.speakText.call(AUTH_ID, CALL_UUID, { text: 'Please hold.' });
  await client.dtmf.sendDtmf(AUTH_ID, CALL_UUID, { digits: '1234' });
  await client.recordCalls.startRecording(AUTH_ID, CALL_UUID);
  await client.liveCalls.hangupCall(AUTH_ID, CALL_UUID);
  ```
</CodeGroup>

<Tip>
  Each Vobiz method name states the action, so live-call logic reads top-to-bottom. For the full resource map, see [Voice Call API](/docs/compare/twilio/voice-call-api); to convert the TwiML you inline via `update(twiml=…)`, use the [TwiML → VobizXML](/docs/compare/twilio/twiml-to-vobizxml) reference.
</Tip>

## Look up a live call

Twilio reads live and completed calls off one `client.calls` resource, filtered by `status`. Vobiz gives in-flight calls their own `live_calls` resource - pass `status="live"` to fetch or list what's currently on the wire. Completed-call history lives in [`cdr`](/docs/compare/twilio/voice-call-api).

<CodeGroup>
  ```python Twilio · Python theme={null}
  one = client.calls('CA0123...').fetch()
  live = client.calls.list(status='in-progress')
  ```

  ```python Vobiz · Python theme={null}
  one = client.live_calls.get_live_call(AUTH_ID, 'call-uuid-here', status='live')
  live = client.live_calls.list_live_calls(AUTH_ID, status='live')
  ```
</CodeGroup>

## Search and buy a phone number

Twilio searches the live carrier catalog with `available_phone_numbers('US').local.list(...)`, reads `.phone_number` off a result, then provisions it with `incoming_phone_numbers.create(phone_number=...)`. Vobiz browses ready-to-buy stock with `list_inventory_numbers(...)` and buys by E.164 with `purchase_from_inventory(...)` - a deterministic two-step flow where the E.164 number is the key.

<CodeGroup>
  ```python Twilio · Python theme={null}
  available = client.available_phone_numbers('US').local.list(limit=1)
  number = available[0].phone_number   # e.g. '+14155551234'
  incoming = client.incoming_phone_numbers.create(phone_number=number)
  ```

  ```python Vobiz · Python theme={null}
  available = client.phone_numbers.list_inventory_numbers(AUTH_ID, country='US')
  number = available.numbers[0].e164   # e.g. '+14155551234'
  bought = client.phone_numbers.purchase_from_inventory(AUTH_ID, e164=number)
  ```

  ```javascript Twilio · Node theme={null}
  const available = await client.availablePhoneNumbers('US').local.list({ limit: 1 });
  const number = available[0].phoneNumber;   // e.g. '+14155551234'
  const incoming = await client.incomingPhoneNumbers.create({ phoneNumber: number });
  ```

  ```javascript Vobiz · Node theme={null}
  const available = await client.phoneNumbers.listInventoryNumbers(AUTH_ID, { country: 'US' });
  const number = available.numbers[0].e164;   // e.g. '+14155551234'
  const bought = await client.phoneNumbers.purchaseFromInventory(AUTH_ID, { e164: number });
  ```
</CodeGroup>

## Manage a conference

Twilio tracks a room by its `CF…` SID and each leg by its `CallSid`. Vobiz uses the **room name** as the join key and a `member_id` per participant - `get_conference` returns the room details **and** its member list in one call, and every control is its own verb.

<CodeGroup>
  ```python Twilio · Python theme={null}
  conf = client.conferences("CFxxxxxxxx")

  # Who is in the room?
  for p in conf.participants.list():
      print(p.call_sid, "muted:", p.muted)

  # Mute, hold, and remove one participant
  conf.participants("CAaaaa").update(muted=True)
  conf.participants("CAaaaa").update(hold=True, hold_url="https://example.com/hold.mp3")
  conf.participants("CAaaaa").delete()

  # End the whole conference
  conf.update(status="completed")
  ```

  ```python Vobiz · Python theme={null}
  # Who is in the room? get_conference returns members + room details together
  room = client.conferences.get_conference(AUTH_ID, conference_name="SalesRoom")
  for m in room["members"]:
      print(m["member_id"], "muted:", m["muted"])

  # Mute a member; hold = play audio to just that member, stop returns them to the room
  client.conference_members.mute_member(AUTH_ID, conference_name="SalesRoom", member_id="MEMBER_1")
  client.conference.play_audio_member(AUTH_ID, conference_name="SalesRoom",
                                      member_id="MEMBER_1", url="https://example.com/hold.mp3")
  client.conference.stop_audio_member(AUTH_ID, conference_name="SalesRoom", member_id="MEMBER_1")
  client.conference.kick_member(AUTH_ID, conference_name="SalesRoom", member_id="MEMBER_1")

  # End one room, or every active room at once
  client.conferences.delete_conference(AUTH_ID, conference_name="SalesRoom")
  client.conferences.delete_all_conferences(AUTH_ID)
  ```
</CodeGroup>

Record the whole room on demand by name - start and stop whenever you like:

<CodeGroup>
  ```python Twilio · Python theme={null}
  # Twilio sets recording on the <Conference> verb:
  #   <Conference record="record-from-start"
  #               recordingStatusCallback="https://example.com/rec">SalesRoom</Conference>
  ```

  ```python Vobiz · Python theme={null}
  client.conference_recording.start_conference_recording(
      AUTH_ID, conference_name="SalesRoom",
      file_format="mp3", callback_url="https://example.com/rec")
  client.conference_recording.stop_conference_recording(AUTH_ID, conference_name="SalesRoom")
  ```
</CodeGroup>

The full per-verb map - mute/unmute, deaf/undeaf, kick/hangup, and the `<Conference>` element - is in [Conferences](/docs/compare/twilio/conferences).

## List call records

Completed-call history is a first-class `cdr` resource on Vobiz, with rich filters for reporting.

<CodeGroup>
  ```python Twilio · Python theme={null}
  records = client.calls.list(status="completed", limit=20)
  for r in records:
      print(r.sid, r.to, r.duration, r.price)
  ```

  ```python Vobiz · Python theme={null}
  records = client.cdr.list_cdrs(
      AUTH_ID,
      start_date="2026-06-01",
      end_date="2026-06-30",
      call_direction="outbound",
  )
  ```
</CodeGroup>

<Tip>
  Filter CDRs by `from_number`, `to_number`, `call_direction`, `hangup_cause`, `bridge_uuid`, or `sip_call_id` - purpose-built for reporting. See [Voice Call API](/docs/compare/twilio/voice-call-api) for the live-vs-history split (`live_calls` for in-flight legs, `cdr` for completed history).
</Tip>

## Validate a webhook signature

Both platforms sign inbound webhooks so you can prove the request came from them. Twilio's `RequestValidator` rebuilds the full URL plus every sorted POST field and HMAC-SHA1s it against `X-Twilio-Signature`. Vobiz signs a short, deterministic string - `baseURL + "." + nonce` (query stripped) - with HMAC-SHA256, and sends it as `X-Vobiz-Signature-V3` with the random nonce in `X-Vobiz-Signature-V3-Nonce`. No param-sorting step, reproducible in any language with the standard library.

<CodeGroup>
  ```python Twilio · Python theme={null}
  from flask import Flask, request, abort
  from twilio.request_validator import RequestValidator

  app = Flask(__name__)
  AUTH_TOKEN = "your_twilio_auth_token"

  @app.route("/voice", methods=["POST"])
  def voice():
      validator = RequestValidator(AUTH_TOKEN)
      # HMAC-SHA1 over full URL + sorted POST params
      valid = validator.validate(
          request.url,
          request.form,
          request.headers.get("X-Twilio-Signature", ""),
      )
      if not valid:
          abort(403)
      # ... return TwiML
  ```

  ```python Vobiz · Python theme={null}
  import hmac, hashlib, base64
  from urllib.parse import urlparse, urlunparse
  from flask import Flask, request, abort

  app = Flask(__name__)
  AUTH_TOKEN = "your_vobiz_auth_token"      # your Auth Token signs the webhook

  def _base_url(url: str) -> str:
      p = urlparse(url)
      return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))  # strip query

  def validate_v3(url: str, headers, token: str) -> bool:
      nonce = headers.get("X-Vobiz-Signature-V3-Nonce", "")   # read case-insensitively
      msg = (_base_url(url) + "." + nonce).encode()            # HMAC-SHA256
      expected = base64.b64encode(
          hmac.new(token.encode(), msg, hashlib.sha256).digest()
      ).decode()
      # constant-time compare - never ==
      return hmac.compare_digest(headers.get("X-Vobiz-Signature-V3", ""), expected)

  @app.route("/voice", methods=["POST"])
  def voice():
      if not validate_v3(request.url, request.headers, AUTH_TOKEN):
          abort(403)
      # ... return VobizXML
      return "", 200
  ```
</CodeGroup>

<Note>
  On sub-account callbacks Vobiz also adds `X-Vobiz-Signature-MA-V3`, signed with the **parent (main-account)** token, so a parent can verify child traffic with the same validator. Full mapping and the Node version: [webhooks & signatures](/docs/compare/twilio/webhooks).
</Note>

## Handle errors

Catch the Vobiz error types (all subclasses of `ApiError`) the same way you caught Twilio's `TwilioRestException` - with the HTTP status and response body available on the exception.

<CodeGroup>
  ```python Twilio · Python theme={null}
  from twilio.base.exceptions import TwilioRestException

  try:
      client.calls.create(
          to="+14165553434",
          from_="+14155551234",
          url="https://example.com/answer.xml",
          method="POST",
      )
  except TwilioRestException as e:
      print(e.status, e.code, e.msg)
  ```

  ```python Vobiz · Python theme={null}
  from vobiz.core.api_error import ApiError

  try:
      client.calls.make_call(
          auth_id=AUTH_ID,
          from_="+14155551234",
          to="+14165553434",
          answer_url="https://example.com/answer.xml",
          answer_method="POST",
      )
  except ApiError as e:
      print(e.status_code, e.body)
  ```
</CodeGroup>

<Tip>
  Full verb table: [TwiML → VobizXML](/docs/compare/twilio/twiml-to-vobizxml).
</Tip>

<Tip>
  Need a method that isn't here? The full per-resource map is in [Voice Call API](/docs/compare/twilio/voice-call-api), [TwiML → VobizXML](/docs/compare/twilio/twiml-to-vobizxml), and the rest of the [Twilio migration](/docs/compare/twilio/overview) section.
</Tip>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.