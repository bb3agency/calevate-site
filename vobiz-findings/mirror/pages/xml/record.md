> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Record XML Element – Call & Conference Recording | Vobiz

> Record calls or conferences with the Vobiz Record element and get a URL at your callback endpoint. Configurable format, max length, beep, and transcription.

The Record element records a call or conference. Use `action` for the initial recording event and `callbackUrl` for the completed recording event and ready file information.

## Attributes

| Attribute | Description |
| - | - |
| `action` <br /> *string* <br /> *Callback-retry configurable* | URL that receives the initial recording event and recording identifier. For whole-session recording, you can omit `action` and use `callbackUrl` alone when you only need the completed recording. <br /> **Allowed values:** a fully qualified URL |
| `method` <br /> *string* <br /> *Callback-retry configurable* | HTTP method used to send the initial recording event to the action URL. <br /> **Allowed values:** `GET`, `POST` <br /> **Default:** `POST` |
| `fileFormat` <br /> *string* | File format of the recording. <br /> **Allowed values:** `mp3`, `wav` <br /> **Default:** `mp3` |
| `redirect` <br /> *boolean* | Controls whether Vobiz executes XML returned by `action`. With `true`, Vobiz requests `action` and executes its returned XML. With `false`, Vobiz sends the recording event without using the response to redirect call control - **your `action` handler must return an empty `<Response></Response>`**, or it will interrupt a flow that has already moved on. <br /> **Allowed values:** `true`, `false` <br /> **Default:** `false` |
| `timeout` <br /> *integer* | Maximum silence duration in seconds before the recording ends. This does not set a total recording-duration limit. If the recording ends due to timeout, the final `callbackUrl` request reports `RecordingEndReason=RecordingTimeout`. <br /> **Allowed values:** integer greater than `0` <br /> **Default:** `60` |
| `maxLength` <br /> *integer* | Maximum recording length in seconds. When the limit is reached, the final `callbackUrl` request reports `RecordingEndReason=maxLength`. <br /> **Allowed values:** integer greater than `0` <br /> **Default:** `60` |
| `playBeep` <br /> *boolean* | If `true`, a beep plays before recording begins. <br /> **Allowed values:** `true`, `false` <br /> **Default:** `true` |
| `finishOnKey` <br /> *string* | Stops the recording when the caller presses a configured key. The final `callbackUrl` request reports `RecordingEndReason=FinishedOnKey`. <br /> **Allowed values:** any digit, `#`, `*` <br /> **Default:** `1234567890*#` |
| `recordSession` <br /> *boolean* | If `true`, records the entire session, including multiple `Play` or `Speak` elements. Recording ends when the call is hung up, and the final `callbackUrl` request reports `RecordingEndReason=HungUp`. <br /> **Allowed values:** `true`, `false` <br /> **Default:** `false` |
| `startOnDialAnswer` <br /> *boolean* | If `true`, recording starts when the call is answered. Use this for outbound calls where `Record` is nested inside `Dial`. <br /> **Allowed values:** `true`, `false` <br /> **Default:** `false` |
| `transcriptionType` <br /> *string* | Transcription service to use. Transcription is available at an additional cost. Refer to the pricing page for details. <br /> **Allowed values:** `auto`, `hybrid` <br /> **Default:** `auto` <br /> `auto`: uses the default Vobiz transcription service. <br /> `hybrid`: uses the Vobiz transcription service for the most common languages and a third-party provider for other languages. |
| `transcriptionUrl` <br /> *string* <br /> *Callback-retry configurable* | URL that receives the transcription. <br /> **Allowed values:** a fully qualified URL |
| `transcriptionMethod` <br /> *string* <br /> *Callback-retry configurable* | HTTP method used to request `transcriptionUrl`. <br /> **Allowed values:** `GET`, `POST` <br /> **Default:** `POST` |
| `callbackUrl` <br /> *string* <br /> *Callback-retry configurable* | URL that receives `RecordStop` after recording ends. Use this callback for the final duration and recording file URL. <br /> **Allowed values:** a fully qualified URL |
| `callbackMethod` <br /> *string* <br /> *Callback-retry configurable* | HTTP method used to request `callbackUrl`. <br /> **Allowed values:** `GET`, `POST` <br /> **Default:** `POST` |

## Parameters sent to the action URL

Vobiz requests `action` near the start of recording. The request includes the standard call parameters and the recording identifier.

| Parameter | Type | Description |
| - | - | - |
| `RecordingID` | string | Unique identifier for the recording. Store this value to correlate the initial event with the completed callback. |

Other recording fields may be absent or incomplete in the action request. Do not use this request as proof that recording has finished or that the file is ready.

## Parameters sent to the callback URL

Vobiz sends `Event=RecordStop` to `callbackUrl` after recording finishes. Use this request for completed recording metadata.

| Parameter | Type | Description |
| - | - | - |
| `Event` | string | Event type. The completed recording event is `RecordStop`. |
| `RecordingID` | string | Unique identifier for the recording. |
| `RecordFile` | string | URL of the completed recording file when returned under this field name. |
| `RecordUrl` | string | URL of the completed recording file when returned under this field name. |
| `RecordingDuration` | integer | Final recording duration in seconds. |
| `RecordingDurationMs` | integer | Final recording duration in milliseconds. |
| `RecordingStartMs` | integer | Timestamp when recording started, in milliseconds. |
| `RecordingEndMs` | integer | Timestamp when recording ended, in milliseconds. |
| `RecordingEndReason` | string | Reason the recording ended. |

Possible `RecordingEndReason` values include:

* `RecordingTimeout`: silence reached the configured `timeout`
* `maxLength`: recording reached the configured `maxLength`
* `FinishedOnKey`: the caller pressed a configured `finishOnKey`
* `HungUp`: the call ended

## Parameters sent to the transcription URL

| Parameter | Type | Description |
| - | - | - |
| `transcription` | string | Text of the transcription. |
| `transcription_id` | string | Unique identifier for the transcription. |
| `transcription_url` | string | URL of the transcription file. |
| `recording_id` | string | Unique identifier for the recording. |

## Examples

### Record a voicemail message

Speak a prompt, then record until the caller stays silent, presses a key, or hits `maxLength`. See [Record a voicemail](/docs/xml/record/record-a-voicemail).

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>Please leave a message after the beep. Press pound when finished.</Speak>
    <Record action="https://yourapp.com/recording-started" method="POST"
            callbackUrl="https://yourapp.com/recording-ready" callbackMethod="POST"
            maxLength="120" timeout="10" finishOnKey="#" playBeep="true"
            fileFormat="mp3"/>
    <Speak>Thank you. Goodbye.</Speak>
    <Hangup/>
</Response>
```

### Record the entire call session

Set `recordSession="true"` to capture the full call (including subsequent `Speak`, `Play`, and bridged audio). The recording ends when the call hangs up.

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Record
        recordSession="true"
        callbackUrl="https://yourapp.com/recording-ready"
        callbackMethod="POST"
        redirect="false"
        playBeep="false"/>
    <Speak>This call is now being recorded for quality assurance.</Speak>
    <Dial callerId="+14155550100" timeout="30">
        <Number>+14155550101</Number>
    </Dial>
</Response>
```

Place the self-closing `<Record/>` before `<Dial>` so whole-session recording starts before the bridge. The final `RecordStop` callback includes the completed duration and recording file information.

### Record the answered leg of an outbound dial

Nest `Record` with `startOnDialAnswer="true"` so recording begins only once the called party answers.

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Dial>
        <Number>14155551234</Number>
    </Dial>
    <Record startOnDialAnswer="true" maxLength="600"
            action="https://yourapp.com/recording-started"
            callbackUrl="https://yourapp.com/recording-ready"/>
</Response>
```

## Completed recording webhook sent to callbackUrl

After recording ends, Vobiz posts `RecordStop`, the standard call parameters, and final recording metadata to `callbackUrl`. Use `action` only for the earlier recording event and `RecordingID`.

```http Completed recording theme={null}
POST /recording-ready HTTP/1.1
Host: yourapp.com
Content-Type: application/x-www-form-urlencoded

Event=RecordStop&CallUUID=CALL_UUID&RecordingID=RECORDING_ID&RecordFile=https://media.vobiz.ai/recordings/RECORDING_ID.mp3&RecordingDuration=42&RecordingDurationMs=42120&RecordingStartMs=1716112335000&RecordingEndMs=1716112377120&RecordingEndReason=FinishedOnKey
```

## Edge cases and tips

* **`timeout` vs `maxLength`.** `timeout` ends the recording after a stretch of silence (default 60 s) and is *not* a total cap. `maxLength` is the hard ceiling on recording length (default 60 s). Set `maxLength` generously for voicemails so callers are not cut off mid-sentence. The `RecordingEndReason` parameter tells you which limit fired (`RecordingTimeout`, `maxLength`, `FinishedOnKey`, or `HungUp`).
* **`action` and `callbackUrl` serve different stages.** `action` receives the initial recording event and identifier. `callbackUrl` fires after recording stops with final duration and file information. A `recordSession="true"` flow can use `callbackUrl` without `action`.
* **Use the completion callback for the file.** Process or download the recording after `callbackUrl` receives `RecordStop` with `RecordFile` or `RecordUrl`.
* **`finishOnKey` defaults to all keys.** By default any of `1234567890*#` stops the recording. Narrow it (for example `finishOnKey="#"`) if callers might press other digits during their message.
* **`recordSession` vs a standalone `Record`.** Use `recordSession="true"` to capture the whole call for compliance; use a standalone `Record` element to capture a single message (voicemail) and then continue the flow.
* **Compliance.** Announce recording before it starts where required by law (for example, two-party-consent jurisdictions and TRAI rules in India). Use a `Speak`/`Play` before `Record` or set `playBeep="true"`.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.