> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Plivo → Vobiz: Code Snippets for Common Tasks

> Side-by-side Plivo and Vobiz code for the most common voice tasks - make an outbound call, answer with XML, play/speak/DTMF on a live call, record, and buy a number. Copy the Vobiz tab and you're migrated.

Refactoring a Plivo app to Vobiz is mostly a tab-swap: same call flow, a few renamed methods, and an explicit `auth_id`. Each task below shows the **Plivo** code and the equivalent **Vobiz** code in Python and Node - copy the Vobiz tab.

<Note>
  Set your credentials once: `AUTH_ID` is your Vobiz Auth ID (`MA_…`), `AUTH_TOKEN` is your Auth Token. In the Vobiz SDK, `api_key` **is** the Auth ID, and every account-scoped method takes that `auth_id` explicitly.
</Note>

## Set up the client

<CodeGroup>
  ```python Plivo · Python theme={null}
  import plivo

  client = plivo.RestClient(AUTH_ID, AUTH_TOKEN)
  ```

  ```python Vobiz · Python theme={null}
  from vobiz import Vobiz

  client = Vobiz(api_key=AUTH_ID, auth_token=AUTH_TOKEN)
  ```

  ```javascript Plivo · Node theme={null}
  const plivo = require('plivo');

  const client = new plivo.Client(AUTH_ID, AUTH_TOKEN);
  ```

  ```javascript Vobiz · Node theme={null}
  import { VobizClient } from '@vobiz/sdk';

  const client = new VobizClient({ apiKey: AUTH_ID, authToken: AUTH_TOKEN });
  ```
</CodeGroup>

## Make an outbound call

The classic "change a few lines" migration: `calls.create` → `calls.make_call`, add `auth_id`, and `to_` → `to`.

<CodeGroup>
  ```python Plivo · Python theme={null}
  client.calls.create(
      from_='+14155551234',
      to_='+14165553434',
      answer_url='https://example.com/answer.xml',
      answer_method='POST',
  )
  ```

  ```python Vobiz · Python theme={null}
  client.calls.make_call(
      auth_id=AUTH_ID,
      from_='+14155551234',
      to='+14165553434',
      answer_url='https://example.com/answer.xml',
      answer_method='POST',
  )
  ```

  ```javascript Plivo · Node theme={null}
  await client.calls.create(
    '+14155551234',
    '+14165553434',
    'https://example.com/answer.xml',
    { answerMethod: 'POST' },
  );
  ```

  ```javascript Vobiz · Node theme={null}
  await client.calls.makeCall({
    auth_id: AUTH_ID,
    from: '+14155551234',
    to: '+14165553434',
    answer_url: 'https://example.com/answer.xml',
    answer_method: 'POST',
  });
  ```
</CodeGroup>

## Answer a call with XML (TTS + menu)

The XML builder mirrors `plivoxml` - `ResponseElement` with `add_*` methods. `GetDigits`/`GetInput` become `Gather` (and `add_get_digits` is kept as an alias).

<CodeGroup>
  ```python Plivo · Python theme={null}
  from plivo import plivoxml

  resp = plivoxml.ResponseElement()
  menu = resp.add_get_digits(action='https://example.com/menu', method='POST', num_digits=1)
  menu.add_speak('Press 1 for sales, 2 for support.')
  print(resp.to_string())
  ```

  ```python Vobiz · Python theme={null}
  from vobiz import vobizxml

  resp = vobizxml.ResponseElement()
  menu = resp.add_gather(action='https://example.com/menu', method='POST',
                         input_type='dtmf', num_digits=1)
  menu.add_speak('Press 1 for sales, 2 for support.')
  print(resp.to_string())
  ```

  ```javascript Plivo · Node theme={null}
  const plivo = require('plivo');

  const resp = new plivo.Response();
  const menu = resp.addGetDigits({ action: 'https://example.com/menu', method: 'POST', numDigits: 1 });
  menu.addSpeak('Press 1 for sales, 2 for support.');
  console.log(resp.toXML());
  ```

  ```javascript Vobiz · Node theme={null}
  import { vobizxml } from '@vobiz/sdk';

  const resp = new vobizxml.ResponseElement();
  const menu = resp.addGather({ action: 'https://example.com/menu', method: 'POST', inputType: 'dtmf', numDigits: 1 });
  menu.addSpeak('Press 1 for sales, 2 for support.');
  console.log(resp.toString());
  ```
</CodeGroup>

## Serve the answer URL (Flask / FastAPI / Express)

When Vobiz rings your number it fetches your `answer_url` over HTTP - return the VobizXML from any web framework, exactly as you did with Plivo. Just build the response with `vobizxml` and send it as `application/xml`.

<CodeGroup>
  ```python Plivo · Flask theme={null}
  from flask import Flask, Response
  from plivo import plivoxml

  app = Flask(__name__)

  @app.route('/answer', methods=['POST'])
  def answer():
      resp = plivoxml.ResponseElement()
      resp.add_speak('Hello from Plivo.')
      return Response(resp.to_string(), mimetype='application/xml')
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

## Control a live call

Plivo's in-call actions live on `calls.*`; in Vobiz they're dedicated resources keyed by `(auth_id, call_uuid)`.

<CodeGroup>
  ```python Plivo · Python theme={null}
  client.calls.play(CALL_UUID, urls='https://example.com/hold.mp3')   # play audio
  client.calls.speak(CALL_UUID, text='Please hold.')                  # speak text
  client.calls.send_digits(CALL_UUID, digits='1234')                  # send DTMF
  client.calls.record(CALL_UUID)                                      # start recording
  client.calls.hangup(CALL_UUID)                                      # hang up
  ```

  ```python Vobiz · Python theme={null}
  client.play_audio.call(AUTH_ID, CALL_UUID, urls='https://example.com/hold.mp3')   # play audio
  client.speak_text.call(AUTH_ID, CALL_UUID, text='Please hold.')                   # speak text
  client.dtmf.send_dtmf(AUTH_ID, CALL_UUID, digits='1234')                          # send DTMF
  client.record_calls.start_recording(AUTH_ID, CALL_UUID)                           # start recording
  client.live_calls.hangup_call(AUTH_ID, CALL_UUID)                                 # hang up
  ```

  ```javascript Plivo · Node theme={null}
  await client.calls.play(CALL_UUID, { urls: 'https://example.com/hold.mp3' });
  await client.calls.speak(CALL_UUID, 'Please hold.');
  await client.calls.sendDigits(CALL_UUID, '1234');
  await client.calls.record(CALL_UUID);
  await client.calls.hangup(CALL_UUID);
  ```

  ```javascript Vobiz · Node theme={null}
  await client.playAudio.call(AUTH_ID, CALL_UUID, { urls: 'https://example.com/hold.mp3' });
  await client.speakText.call(AUTH_ID, CALL_UUID, { text: 'Please hold.' });
  await client.dtmf.sendDtmf(AUTH_ID, CALL_UUID, { digits: '1234' });
  await client.recordCalls.startRecording(AUTH_ID, CALL_UUID);
  await client.liveCalls.hangupCall(AUTH_ID, CALL_UUID);
  ```
</CodeGroup>

## Look up a live call

Retrieving a live call needs `status="live"` on Vobiz.

<CodeGroup>
  ```python Plivo · Python theme={null}
  live = client.calls.get(CALL_UUID)
  calls = client.calls.list(status='live')
  ```

  ```python Vobiz · Python theme={null}
  live = client.live_calls.get_live_call(AUTH_ID, CALL_UUID, status='live')
  calls = client.live_calls.list_live_calls(AUTH_ID, status='live')
  ```
</CodeGroup>

## Search and buy a phone number

<CodeGroup>
  ```python Plivo · Python theme={null}
  available = client.numbers.search(country_iso='US', type='local')
  client.numbers.buy('14155551234')
  ```

  ```python Vobiz · Python theme={null}
  available = client.phone_numbers.list_inventory_numbers(AUTH_ID, country='US')
  client.phone_numbers.purchase_from_inventory(AUTH_ID, e164='+14155551234')
  ```

  ```javascript Plivo · Node theme={null}
  const available = await client.numbers.search('US', { type: 'local' });
  await client.numbers.buy('14155551234');
  ```

  ```javascript Vobiz · Node theme={null}
  const available = await client.phoneNumbers.listInventoryNumbers(AUTH_ID, { country: 'US' });
  await client.phoneNumbers.purchaseFromInventory(AUTH_ID, { e164: '+14155551234' });
  ```
</CodeGroup>

## List call records

Completed-call history is a first-class `cdr` resource on Vobiz.

<CodeGroup>
  ```python Plivo · Python theme={null}
  records = client.calls.list(limit=20)
  ```

  ```python Vobiz · Python theme={null}
  records = client.cdr.list_cdrs(AUTH_ID, start_date='2026-06-01', end_date='2026-06-30')
  ```
</CodeGroup>

## Handle errors

Catch the Vobiz error types (all subclasses of `ApiError`) the same way you caught Plivo's.

<CodeGroup>
  ```python Plivo · Python theme={null}
  from plivo.exceptions import PlivoRestError

  try:
      client.calls.make_call(...)
  except PlivoRestError as e:
      print(e)
  ```

  ```python Vobiz · Python theme={null}
  from vobiz.core.api_error import ApiError

  try:
      client.calls.make_call(auth_id=AUTH_ID, from_='+1...', to='+1...',
                             answer_url='https://...', answer_method='POST')
  except ApiError as e:
      print(e.status_code, e.body)
  ```
</CodeGroup>

Need a method that isn't here? The full per-resource map is in [Voice Call API](/docs/compare/plivo/voice-call-api), [Call-control XML](/docs/compare/plivo/call-control-xml), and the rest of the [Plivo migration](/docs/compare/plivo/overview) section.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.