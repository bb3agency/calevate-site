> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Plivo to Vobiz: Recordings & Transcription Migration

> Map Plivo's Record XML, Recording API, and transcription to Vobiz. Side-by-side endpoints, SDK methods, the Record verb, and the gotchas when migrating call recording from Plivo to Vobiz.

Vobiz mirrors Plivo's recording model closely - same `Record` XML verb, same `Record/` and `Recording/` REST endpoints, and webhook-delivered transcription. Migration is mostly a base-URL (`https://api.vobiz.ai/api/v1`), auth-header (`X-Auth-ID` + `X-Auth-Token`, not Basic auth), and SDK-namespace swap.

## Plivo → Vobiz mapping

| Plivo | Vobiz |
| - | - |
| `Record` XML element | `<Record>` XML element (VobizXML) |
| `<Record>` attrs `action`, `method`, `fileFormat`, `maxLength`, `timeout`, `playBeep`, `finishOnKey`, `redirect` | Same attribute names and semantics |
| `<Record recordSession="true">` | `<Record recordSession="true">` |
| `<Record startOnDialAnswer="true">` (nested in Dial) | `<Record startOnDialAnswer="true">` |
| `<Record transcriptionType="auto\|hybrid">`, `transcriptionUrl`, `transcriptionMethod` | Same attributes, values `auto` / `hybrid` |
| `<Record recordChannelType="mono\|stereo">` | `record_channel_type` on the REST `Record/` call (mono/stereo) |
| `POST /v1/Account/{id}/Call/{call_uuid}/Record/` (start) | `POST /api/v1/Account/{auth_id}/Call/{call_uuid}/Record/` |
| `DELETE /v1/Account/{id}/Call/{call_uuid}/Record/` (stop) | `DELETE /api/v1/Account/{auth_id}/Call/{call_uuid}/Record/` |
| `POST /v1/Account/{id}/Conference/{name}/Record/` | `POST /api/v1/Account/{auth_id}/Conference/{name}/Record/` |
| `DELETE /v1/Account/{id}/Conference/{name}/Record/` | `DELETE /api/v1/Account/{auth_id}/Conference/{name}/Record/` |
| `GET /v1/Account/{id}/Recording/` (list all) | `GET /api/v1/Account/{auth_id}/Recording/` |
| `GET /v1/Account/{id}/Recording/{recording_id}/` | `GET /api/v1/Account/{auth_id}/Recording/{recording_id}/` |
| `DELETE /v1/Account/{id}/Recording/{recording_id}/` | `DELETE /api/v1/Account/{auth_id}/Recording/{recording_id}/` |
| Python `client.calls.record(...)` / `start_recording(...)` | `client.record_calls.start_recording(...)` |
| Python `client.calls.stop_recording(call_uuid)` | `client.record_calls.stop_recording(...)` |
| Python `client.conferences.record(...)` | `client.conference_recording.start_conference_recording(...)` |
| Python `client.recordings.list()` | `client.recordings.list_recordings(...)` |
| Python `client.recordings.get(recording_id)` | `client.recordings.get_recording(...)` |
| Python `client.recordings.delete(recording_id)` | `client.recordings.delete_recording(...)` |
| Node `client.calls.record(callUuid)` | `client.recordCalls.startRecording(...)` |
| Node `client.recordings.list/get/delete` | `client.recordings.listRecordings/getRecording/deleteRecording` |

## Before / after - record a voicemail in XML

Plivo (PlivoXML) and Vobiz (VobizXML) share the verb and attribute names verbatim:

```xml Plivo theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>Please leave a message after the beep.</Speak>
    <Record action="https://yourapp.com/voicemail" method="POST"
            maxLength="120" timeout="10" finishOnKey="#" playBeep="true"
            fileFormat="mp3"/>
</Response>
```

```xml Vobiz theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>Please leave a message after the beep.</Speak>
    <Record action="https://yourapp.com/voicemail" method="POST"
            maxLength="120" timeout="10" finishOnKey="#" playBeep="true"
            fileFormat="mp3"/>
</Response>
```

The action-URL callback params also match: `RecordUrl`, `RecordingID`, `RecordingDuration`, `RecordingDurationMs`, `RecordingStartMs`, `RecordingEndMs`. Vobiz adds `RecordingEndReason` (`RecordingTimeout` / `maxLength` / `FinishedOnKey` / `HungUp`).

## Key differences & gotchas

* **Recording namespace split.** Plivo puts in-call recording on `client.calls`; Vobiz splits it into `client.record_calls` (live call) and `client.conference_recording` (conference). Stored-asset list/get/delete lives on `client.recordings` on both sides.
* **`recordChannelType` location.** On Vobiz, mono/stereo is set via `record_channel_type` on the REST `Record/` call.
* **Transcription delivery.** Both support `auto` and `hybrid`. Vobiz posts the result to `transcriptionUrl` (XML) or the recording `callback_url` (REST) - wire up the webhook to receive it.
* **`timeout` default differs.** `timeout` is the trailing-silence cutoff (Vobiz default 60s, Plivo default 15s); re-check your Plivo values after migrating.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.