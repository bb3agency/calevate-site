> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Twilio Recordings & Transcription → Vobiz

> Migrate Twilio call recording and transcription to Vobiz: map recordings.list / fetch / delete, in-call recording (calls(sid).recordings.create), the <Record> TwiML verb, and transcribeCallback to Vobiz recordings.*, record_calls.start_recording/stop_recording, the <Record> verb, and callback-delivered transcription.

Vobiz models recording the same way Twilio does: a `<Record>` verb for TwiML-style flows, an imperative API to start and stop recording on a live call, a recordings collection to list / fetch / delete, and transcription delivered to a callback URL. Migration is mostly a base-URL swap to `https://api.vobiz.ai/api/v1`, an auth-header swap (`X-Auth-ID` + `X-Auth-Token` in place of HTTP Basic), and a few renamed SDK methods that each take an explicit `auth_id`.

<Note>
  Set your credentials once: `AUTH_ID` is your Vobiz Auth ID (`MA_…`) and `AUTH_TOKEN` is your Auth Token. In the Vobiz SDK, `api_key` **is** the Auth ID (sent as `X-Auth-ID`), and every account-scoped method takes that `auth_id` explicitly as its first argument.
</Note>

## Twilio → Vobiz mapping

| Twilio | Vobiz |
| - | - |
| `<Record>` TwiML verb | `<Record>` VobizXML verb ([reference](/docs/xml/record)) |
| `<Record action= method=>` | `<Record action= method=>` - same names, `POST` default |
| `<Record maxLength=>` (hard cap) | `<Record maxLength=>` (hard cap on length) |
| `<Record timeout=>` (silence ends recording) | `<Record timeout=>` (silence ends recording) |
| `<Record playBeep=>` | `<Record playBeep=>` |
| `<Record finishOnKey=>` | `<Record finishOnKey=>` |
| `<Record trim="trim-silence\|do-not-trim">` | `<Record fileFormat="mp3\|wav">` plus post-processing on your side |
| `<Record recordingStatusCallback= recordingStatusCallbackEvent=>` | `<Record callbackUrl= callbackMethod=>` (fired when the file is ready) |
| `<Record transcribe="true" transcribeCallback=…>` | `<Record transcriptionType="auto\|hybrid" transcriptionUrl= transcriptionMethod=>` |
| Record whole call (Dial + `record="record-from-answer"`) | `<Record recordSession="true">` / `<Record startOnDialAnswer="true">` |
| Action-URL params `RecordingUrl`, `RecordingSid`, `RecordingDuration`, `Digits` | `RecordUrl`, `RecordingID`, `RecordingDuration`, `RecordingEndReason` |
| `transcribeCallback` params `TranscriptionText`, `TranscriptionStatus`, `TranscriptionUrl`, `RecordingSid` | Transcription-URL params `transcription`, `transcription_url`, `transcription_id`, `recording_id` |
| `POST /Calls/{sid}/Recordings.json` (start on live call) | `POST /api/v1/Account/{auth_id}/Call/{call_uuid}/Record/` |
| `POST /Calls/{sid}/Recordings/{rsid}.json` `Status=paused\|stopped` | `DELETE /api/v1/Account/{auth_id}/Call/{call_uuid}/Record/` (stop) |
| `GET /Recordings.json` (list) | `GET /api/v1/Account/{auth_id}/Recording/` |
| `GET /Recordings/{sid}.json` (fetch) | `GET /api/v1/Account/{auth_id}/Recording/{recording_id}/` |
| `DELETE /Recordings/{sid}.json` | `DELETE /api/v1/Account/{auth_id}/Recording/{recording_id}/` |
| Conference recording (`Conference record=`) | `POST/DELETE /api/v1/Account/{auth_id}/Conference/{name}/Record/` |
| Python `client.recordings.list()` | `client.recordings.list_recordings(auth_id)` |
| Python `client.recordings(sid).fetch()` | `client.recordings.get_recording(auth_id, recording_id=…)` |
| Python `client.recordings(sid).delete()` / `.remove()` | `client.recordings.delete_recording(auth_id, recording_id=…)` |
| Python `client.calls(sid).recordings.create(...)` | `client.record_calls.start_recording(auth_id, call_uuid, …)` |
| Python `client.calls(sid).recordings(rsid).update(status="stopped")` | `client.record_calls.stop_recording(auth_id, call_uuid)` |
| Node `client.recordings.list()` / `.fetch()` / `.remove()` | `client.recordings.listRecordings / getRecording / deleteRecording` |
| Node `client.calls(sid).recordings.create()` | `client.recordCalls.startRecording(...)` |
| Conference `client.conferences(...).recordings` | `client.conferenceRecording.startConferenceRecording / stopConferenceRecording` |

## Before / after - record a voicemail in XML

Twilio's `<Record>` and Vobiz's `<Record>` share the verb name and most attributes. The main renames: `recordingStatusCallback` → `callbackUrl`, and transcription is enabled with `transcriptionType` + `transcriptionUrl` instead of `transcribe` + `transcribeCallback`.

<CodeGroup>
  ```xml Twilio · TwiML theme={null}
  <?xml version="1.0" encoding="UTF-8"?>
  <Response>
    <Say>Please leave a message after the beep. Press pound when finished.</Say>
    <Record action="https://yourapp.com/voicemail"
            method="POST"
            maxLength="120"
            timeout="10"
            finishOnKey="#"
            playBeep="true"
            transcribe="true"
            transcribeCallback="https://yourapp.com/transcription"/>
    <Say>Thank you. Goodbye.</Say>
    <Hangup/>
  </Response>
  ```

  ```xml Vobiz · VobizXML theme={null}
  <?xml version="1.0" encoding="UTF-8"?>
  <Response>
    <Speak>Please leave a message after the beep. Press pound when finished.</Speak>
    <Record action="https://yourapp.com/voicemail"
            method="POST"
            maxLength="120"
            timeout="10"
            finishOnKey="#"
            playBeep="true"
            fileFormat="mp3"
            transcriptionType="auto"
            transcriptionUrl="https://yourapp.com/transcription"/>
    <Speak>Thank you. Goodbye.</Speak>
    <Hangup/>
  </Response>
  ```
</CodeGroup>

Building the XML in code? The Vobiz SDK ships the `vobizxml` builder (same `ResponseElement` + `add_*` pattern you may know from PlivoXML):

<CodeGroup>
  ```python Twilio · Python theme={null}
  from twilio.twiml.voice_response import VoiceResponse

  resp = VoiceResponse()
  resp.say('Please leave a message after the beep.')
  resp.record(
      action='https://yourapp.com/voicemail',
      method='POST',
      max_length=120,
      finish_on_key='#',
      transcribe=True,
      transcribe_callback='https://yourapp.com/transcription',
  )
  print(str(resp))
  ```

  ```python Vobiz · Python theme={null}
  from vobiz import vobizxml

  resp = vobizxml.ResponseElement()
  resp.add_speak('Please leave a message after the beep.')
  resp.add_record(
      action='https://yourapp.com/voicemail',
      method='POST',
      max_length=120,
      finish_on_key='#',
      transcription_type='auto',
      transcription_url='https://yourapp.com/transcription',
  )
  print(resp.to_string())
  ```

  ```javascript Vobiz · Node theme={null}
  import { vobizxml } from '@vobiz/sdk';

  const resp = new vobizxml.ResponseElement();
  resp.addSpeak('Please leave a message after the beep.');
  resp.addRecord({
    action: 'https://yourapp.com/voicemail',
    method: 'POST',
    maxLength: 120,
    finishOnKey: '#',
    transcriptionType: 'auto',
    transcriptionUrl: 'https://yourapp.com/transcription',
  });
  console.log(resp.toString());
  ```
</CodeGroup>

## Before / after - start & stop recording on a live call

Twilio starts an in-call recording by POSTing to the call's `Recordings` sub-resource and stops it by updating that recording's `Status`. Vobiz gives each action a dedicated method keyed by `(auth_id, call_uuid)`, so you never have to track a separate recording SID just to stop it.

<CodeGroup>
  ```python Twilio · Python theme={null}
  from twilio.rest import Client

  client = Client(ACCOUNT_SID, AUTH_TOKEN)

  # Start recording on an in-progress call
  recording = client.calls(CALL_SID).recordings.create(
      recording_channels='dual',
      recording_track='both',
      recording_status_callback='https://yourapp.com/recording-status',
  )

  # Stop it later
  client.calls(CALL_SID).recordings(recording.sid).update(status='stopped')
  ```

  ```python Vobiz · Python theme={null}
  from vobiz import Vobiz

  client = Vobiz(api_key=AUTH_ID, auth_token=AUTH_TOKEN)

  # Start recording on an in-progress call
  client.record_calls.start_recording(
      auth_id=AUTH_ID,
      call_uuid=CALL_UUID,
      time_limit=120,
      file_format='mp3',
      record_channel_type='dual',
      transcription_type='auto',
      callback_url='https://yourapp.com/recording-status',
  )

  # Stop it later - no recording id needed
  client.record_calls.stop_recording(auth_id=AUTH_ID, call_uuid=CALL_UUID)
  ```

  ```javascript Twilio · Node theme={null}
  const client = require('twilio')(ACCOUNT_SID, AUTH_TOKEN);

  const recording = await client.calls(CALL_SID).recordings.create({
    recordingChannels: 'dual',
    recordingTrack: 'both',
    recordingStatusCallback: 'https://yourapp.com/recording-status',
  });

  await client.calls(CALL_SID)
    .recordings(recording.sid)
    .update({ status: 'stopped' });
  ```

  ```javascript Vobiz · Node theme={null}
  import { VobizClient } from '@vobiz/sdk';

  const client = new VobizClient({ apiKey: AUTH_ID, authToken: AUTH_TOKEN });

  await client.recordCalls.startRecording(AUTH_ID, CALL_UUID, {
    timeLimit: 120,
    fileFormat: 'mp3',
    recordChannelType: 'dual',
    transcriptionType: 'auto',
    callbackUrl: 'https://yourapp.com/recording-status',
  });

  await client.recordCalls.stopRecording(AUTH_ID, CALL_UUID);
  ```
</CodeGroup>

## Before / after - list, fetch, and delete recordings

The recordings collection maps almost one-to-one. Twilio addresses a recording as `recordings(sid)`; Vobiz passes the id as `recording_id` and (as everywhere) an explicit `auth_id`.

<CodeGroup>
  ```python Twilio · Python theme={null}
  # List recent recordings
  for rec in client.recordings.list(limit=20):
      print(rec.sid, rec.duration, rec.media_url)

  # Fetch one
  rec = client.recordings('RE0123456789abcdef0123456789abcdef').fetch()

  # Delete one
  client.recordings('RE0123456789abcdef0123456789abcdef').delete()
  ```

  ```python Vobiz · Python theme={null}
  # List recent recordings
  page = client.recordings.list_recordings(auth_id=AUTH_ID, limit=20, offset=0)
  for rec in page.recordings:
      print(rec.recording_id, rec.recording_duration, rec.record_url)

  # Fetch one
  rec = client.recordings.get_recording(auth_id=AUTH_ID, recording_id='rec_0123456789')

  # Delete one
  client.recordings.delete_recording(auth_id=AUTH_ID, recording_id='rec_0123456789')
  ```

  ```javascript Twilio · Node theme={null}
  const recs = await client.recordings.list({ limit: 20 });
  const rec = await client.recordings('RE0123...').fetch();
  await client.recordings('RE0123...').remove();
  ```

  ```javascript Vobiz · Node theme={null}
  const page = await client.recordings.listRecordings(AUTH_ID, { limit: 20, offset: 0 });
  const rec = await client.recordings.getRecording(AUTH_ID, { recordingId: 'rec_0123456789' });
  await client.recordings.deleteRecording(AUTH_ID, { recordingId: 'rec_0123456789' });
  ```
</CodeGroup>

## Transcription callbacks

Both platforms deliver the transcript to a URL you own rather than blocking the call. Twilio posts `transcribeCallback` parameters; Vobiz posts to the `transcriptionUrl` you set on `<Record>` (or via `transcription_type='auto'` on `start_recording`). Point Vobiz at your existing endpoint and remap a few field names:

| Twilio field | Vobiz field |
| - | - |
| `TranscriptionText` | `transcription` |
| `TranscriptionUrl` | `transcription_url` |
| `RecordingSid` | `recording_id` |
| (transcript id in resource URL) | `transcription_id` |

```python Vobiz · Flask (transcription webhook) theme={null}
from flask import Flask, request

app = Flask(__name__)

@app.post('/transcription')
def transcription():
    text = request.form['transcription']
    recording_id = request.form['recording_id']
    # ... persist / index / route the transcript ...
    return ('', 204)
```

## Key differences

* **Stopping a recording is a single call.** Vobiz's `record_calls.stop_recording(auth_id, call_uuid)` stops the active recording by call - you address the call, not a separate recording SID, so there's less state to carry through your app.
* **One `<Record>` for whole-call capture.** Where Twilio recording is split across TwiML attributes and REST resources, Vobiz's `<Record recordSession="true">` captures the entire session (including later `Speak`/`Play` and bridged legs), and `startOnDialAnswer="true"` begins capture the moment the far leg answers.
* **Transcription is a two-tier `auto` / `hybrid` choice.** `transcriptionType="auto"` uses the default Vobiz engine; `hybrid` blends Vobiz for common languages with a third-party provider for the long tail - a single attribute covers broad language coverage.
* **A dedicated callback for file readiness.** Vobiz's `callbackUrl` fires when the recording file is actually downloadable, so your download/processing job starts on a real signal instead of polling after the `action` URL returns.
* **Explicit `auth_id` everywhere.** Every recording method takes the account `auth_id` as its first argument, which makes multi-account and sub-account workloads explicit and easy to route.
* **Auth headers instead of Basic auth.** Vobiz authenticates with `X-Auth-ID` + `X-Auth-Token` headers against `https://api.vobiz.ai/api/v1`; the SDK sets these for you from `api_key` / `auth_token`.
* **Familiar verb and attribute names.** `action`, `method`, `maxLength`, `timeout`, `playBeep`, and `finishOnKey` keep their Twilio meanings on the Vobiz `<Record>` verb, so most of your recording XML ports with only the callback/transcription attributes renamed.

See the full [`<Record>` reference](/docs/xml/record), pair recording with a menu using [`<Gather>`](/docs/xml/gather), or go back to the [Twilio → Vobiz overview](/docs/compare/twilio/overview).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.