> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# TwiML → VobizXML: verb-by-verb

> Map every TwiML voice verb to its VobizXML equivalent - Say→Speak, Play→Play, Gather→Gather, Dial→Dial, Record, Conference, Stream and more. Swap twilio.twiml.voice_response.VoiceResponse() for vobizxml.ResponseElement() and keep the same IVR flow.

If your Twilio app answers calls by returning TwiML, migrating to Vobiz is mostly a **verb-for-verb rename**. The document shape is identical: a root element wrapping ordered voice verbs. Twilio's `<Response>` becomes Vobiz's `<Response>`, `<Say>` becomes `<Speak>`, and the builder - `twilio.twiml.voice_response.VoiceResponse()` - becomes `vobizxml.ResponseElement()`. This page maps each voice verb and its attributes, then shows before/after IVRs you can copy.

## The builder swap

Twilio's helper libraries expose a `VoiceResponse` builder; Vobiz ships the equivalent `ResponseElement` in the bundled `vobizxml` module. Nesting, chaining, and serialization all mirror what you already do.

<CodeGroup>
  ```python Twilio · Python theme={null}
  from twilio.twiml.voice_response import VoiceResponse

  response = VoiceResponse()
  response.say('Hello from Twilio.')
  print(str(response))
  ```

  ```python Vobiz · Python theme={null}
  from vobiz import vobizxml

  response = vobizxml.ResponseElement()
  response.add_speak('Hello from Vobiz.')
  print(response.to_string())
  ```

  ```javascript Twilio · Node theme={null}
  const { twiml } = require('twilio');

  const response = new twiml.VoiceResponse();
  response.say('Hello from Twilio.');
  console.log(response.toString());
  ```

  ```javascript Vobiz · Node theme={null}
  import { vobizxml } from '@vobiz/sdk';

  const response = new vobizxml.ResponseElement();
  response.addSpeak('Hello from Vobiz.');
  console.log(response.toString());
  ```
</CodeGroup>

## Verb-by-verb mapping

| TwiML verb | Builder (Twilio) | VobizXML verb | Builder (Vobiz) | Notes |
| - | - | - | - | - |
| `<Say>` | `response.say(text, voice=, language=, loop=)` | `<Speak>` | `add_speak(text, voice=, language=, loop=)` | Voice names `man`/`woman` map to Vobiz `MAN`/`WOMAN`; `language` and `loop` carry over 1:1. |
| `<Play>` | `response.play(url, loop=)` | `<Play>` | `add_play(url, loop=)` | Plays MP3/WAV from a URL; `loop="0"` repeats until the call moves on. |
| `<Gather>` | `response.gather(input=, timeout=, num_digits=, finish_on_key=, speech_timeout=, action=)` | `<Gather>` | `add_gather(input_type=, execution_timeout=, num_digits=, finish_on_key=, speech_end_timeout=, action=)` | `input`→`inputType`, `timeout`→`executionTimeout`, `speechTimeout`→`speechEndTimeout`; `numDigits`/`finishOnKey` keep their names. Vobiz adds `digitEndTimeout` for inter-digit timing. |
| `<Dial>` | `response.dial(caller_id=, timeout=, time_limit=, hangup_on_star=, action=)` | `<Dial>` | `add_dial(caller_id=, timeout=, time_limit=, hangup_on_star=, action=)` | `callerId`, `timeout`, `timeLimit`, `hangupOnStar`, `action` all carry over by name. |
| `<Number>` (in `<Dial>`) | `dial.number('+1…')` | `<Number>` | `add_number('+1…')` | PSTN destination nested in `Dial`. |
| `<Client>` / `<Sip>` (in `<Dial>`) | `dial.client('agent')` / `dial.sip('sip:…')` | `<User>` | `add_user('sip:…')` | Reach a SIP endpoint or softphone; supports `sendDigits` and `sipHeaders`. |
| `<Record>` | `response.record(timeout=, finish_on_key=, max_length=, play_beep=, action=)` | `<Record>` | `add_record(timeout=, finish_on_key=, max_length=, play_beep=, file_format=, action=)` | `timeout` is the silence limit on both; Vobiz adds `fileFormat` (mp3/wav) and `startOnDialAnswer`. |
| `<Conference>` (in `<Dial>`) | `dial.conference('Room 1234')` | `<Conference>` | `add_conference('Room 1234')` | Named room by text content. On Vobiz `Conference` is a top-level verb - return it directly from `Response`. |
| `<Pause>` | `response.pause(length=)` | `<Wait>` | `add_wait(length=)` | Silent pause; Vobiz `Wait` adds optional `silence`/`minSilence` for beep detection. |
| `<Redirect>` | `response.redirect(url, method=)` | `<Redirect>` | `add_redirect(url, method=)` | Hand control to another answer URL that returns fresh XML. |
| `<Hangup>` | `response.hangup()` | `<Hangup>` | `add_hangup()` | Ends the call. |
| `<Stream>` | `response.start().stream(url=)` / `response.connect().stream(url=)` | `<Stream>` | `add_stream(url, audio_track=, bidirectional=)` | Fork call audio to a `wss://` server; `track`→`audioTrack`, and `bidirectional="true"` gives two-way media. |

<Tip>
  Vobiz also exposes `add_dtmf` (send digits) and `add_preanswer` (run verbs during early media) on the same `ResponseElement`, plus a first-class [`Gather`](/docs/xml/gather) with combined `dtmf speech` input.
</Tip>

## Before / after: a DTMF IVR menu

A one-key menu. `input`/`timeout`/`numDigits` become `inputType`/`executionTimeout`/`numDigits`, and nested `say` becomes `add_speak`.

<CodeGroup>
  ```python Twilio · Python theme={null}
  from twilio.twiml.voice_response import VoiceResponse

  response = VoiceResponse()
  gather = response.gather(
      input='dtmf',
      num_digits=1,
      timeout=10,
      action='/menu-choice',
      method='POST',
  )
  gather.say('Press 1 for sales, 2 for support, or 0 for an operator.')
  response.say("We didn't receive your input. Goodbye.")
  response.hangup()
  print(str(response))
  ```

  ```python Vobiz · Python theme={null}
  from vobiz import vobizxml

  response = vobizxml.ResponseElement()
  gather = response.add_gather(
      input_type='dtmf',
      num_digits=1,
      execution_timeout=10,
      action='https://yourapp.com/menu-choice',
      method='POST',
  )
  gather.add_speak('Press 1 for sales, 2 for support, or 0 for an operator.')
  response.add_speak("We didn't receive your input. Goodbye.")
  response.add_hangup()
  print(response.to_string())
  ```

  ```javascript Vobiz · Node theme={null}
  import { vobizxml } from '@vobiz/sdk';

  const response = new vobizxml.ResponseElement();
  const gather = response.addGather({
    inputType: 'dtmf',
    numDigits: 1,
    executionTimeout: 10,
    action: 'https://yourapp.com/menu-choice',
    method: 'POST',
  });
  gather.addSpeak('Press 1 for sales, 2 for support, or 0 for an operator.');
  response.addSpeak("We didn't receive your input. Goodbye.");
  response.addHangup();
  console.log(response.toString());
  ```
</CodeGroup>

The XML Vobiz emits is verb-for-verb recognizable:

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="https://yourapp.com/menu-choice" method="POST" inputType="dtmf" numDigits="1" executionTimeout="10">
        <Speak>Press 1 for sales, 2 for support, or 0 for an operator.</Speak>
    </Gather>
    <Speak>We didn't receive your input. Goodbye.</Speak>
    <Hangup/>
</Response>
```

## Before / after: forward a call with caller ID

Twilio's `<Dial>` + `<Number>` maps straight to Vobiz's `<Dial>` + `<Number>`; a `<Client>`/`<Sip>` target becomes `<User>`. `callerId` and `timeout` keep their names.

<CodeGroup>
  ```python Twilio · Python theme={null}
  from twilio.twiml.voice_response import VoiceResponse

  response = VoiceResponse()
  response.say('Please hold while we connect you.')
  dial = response.dial(caller_id='+14155551234', timeout=20, action='/dial-status')
  dial.number('+14165553434')
  print(str(response))
  ```

  ```python Vobiz · Python theme={null}
  from vobiz import vobizxml

  response = vobizxml.ResponseElement()
  response.add_speak('Please hold while we connect you.')
  dial = response.add_dial(caller_id='+14155551234', timeout=20,
                           action='https://yourapp.com/dial-status')
  dial.add_number('+14165553434')
  print(response.to_string())
  ```

  ```javascript Vobiz · Node theme={null}
  import { vobizxml } from '@vobiz/sdk';

  const response = new vobizxml.ResponseElement();
  response.addSpeak('Please hold while we connect you.');
  const dial = response.addDial({ callerId: '+14155551234', timeout: 20, action: 'https://yourapp.com/dial-status' });
  dial.addNumber('+14165553434');
  console.log(response.toString());
  ```
</CodeGroup>

To reach a softphone or SIP endpoint (Twilio `<Client>`/`<Sip>`), nest a `<User>` instead of `<Number>`:

```python Vobiz · Python theme={null}
dial = response.add_dial(caller_id='+14155551234')
dial.add_user('sip:john1234@registrar.vobiz.ai')
```

## Before / after: fork audio to a WebSocket

Twilio's `start().stream()` (one-way) and `connect().stream()` (two-way) both map to Vobiz's `<Stream>` - `track` becomes `audioTrack`, and `bidirectional="true"` requests two-way media.

<CodeGroup>
  ```python Twilio · Python theme={null}
  from twilio.twiml.voice_response import VoiceResponse

  response = VoiceResponse()
  connect = response.connect()
  connect.stream(url='wss://example.com/audio')
  print(str(response))
  ```

  ```python Vobiz · Python theme={null}
  from vobiz import vobizxml

  response = vobizxml.ResponseElement()
  response.add_stream(
      'wss://example.com/audio',
      audio_track='both',
      bidirectional=True,
  )
  print(response.to_string())
  ```
</CodeGroup>

## Key differences

* **Same document, renamed verbs.** The root stays `<Response>`; only leaf names change (`Say`→`Speak`, `Pause`→`Wait`, `Client`/`Sip`→`User`). Nesting, ordering, and the "return XML from your answer URL" model are identical.
* **`Gather` gives you two silence timers.** Twilio's single `timeout` becomes Vobiz's `executionTimeout`, and `speechTimeout` becomes `speechEndTimeout`. Vobiz adds a dedicated `digitEndTimeout` for inter-digit pacing, so DTMF and speech end conditions are tuned independently. Full attribute list on the [Gather reference](/docs/xml/gather).
* **One `Gather` handles digits and speech together.** Set `inputType="dtmf speech"` and whichever the caller does first is posted to your `action` URL - one verb for menus and open-ended intent capture.
* **`User` covers both `Client` and `Sip`.** A single `<User>` element dials SIP endpoints and softphones, carries `sendDigits` for extensions, and sets custom `X-VH-` SIP headers via `sipHeaders`.
* **`Conference` is a top-level verb.** Where Twilio nests `<Conference>` inside `<Dial>`, Vobiz returns `<Conference>` directly from `<Response>`; the room is created on first join and named by the element's text content.
* **Transfers are declarative.** Instead of an imperative "modify live call" step, return a `<Redirect>` (or new `<Dial>`) from your answer URL and Vobiz continues the call with the fresh XML - the same webhook-driven pattern your TwiML app already uses.
* **Streaming is built in.** `<Stream>` forks audio over `wss://` with `audioTrack` selection and `bidirectional` two-way media for AI voice-agent pipelines. See the [Stream reference](/docs/xml/stream) for codecs and reconnect options.

## Related

* [Twilio → Vobiz overview](/docs/compare/twilio/overview) - the full migration order and at-a-glance matrix.
* [Gather XML reference](/docs/xml/gather) - every input attribute and webhook parameter.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.