> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Stream with Record

> Use the Vobiz Record and Stream XML elements together to simultaneously record a call to file and stream raw audio to your WebSocket in real time.

You can use the `<Record>` and `<Stream>` elements together to simultaneously record a call and stream its audio to a WebSocket in real-time. This is useful for applications that require both persistent storage of the call audio and live processing, such as real-time transcription and analysis.

Make `<Record/>` self-closing and place it before `<Stream>` as a sibling element. This starts full-session recording before live audio processing begins. Set `recordSession="true"` so recording continues while later XML elements execute, and set `redirect="false"` so the recording callback does not interrupt the streaming flow.

## Stream with Record XML

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Play>https://yourcdn.com/play.wav</Play>
  <Record action="https://your-domain.com/record_action/" method="POST"
          recordSession="true" redirect="false"
          maxLength="3600" playBeep="true"/>
  <Stream bidirectional="true" keepCallAlive="true">wss://your-server.com/ws</Stream>
  <Play>https://yourcdn.com/play.wav</Play>
</Response>
```

## Initial Record event parameters

The `action` URL receives the initial Record event near the start of recording. Use its `RecordingID` to correlate this event with the completed `RecordStop` callback. Other recording fields may be absent or incomplete at this stage.

| Parameter | Type | Description |
| - | - | - |
| From | string | The calling party number. |
| RecordingID | string | The unique ID for the recording. |
| To | string | The called party number. |
| CallUUID | string | The unique ID for the call. |
| Event | string | The event type (Record). |

## Stream with Record & Callback URL XML

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Play>https://yourcdn.com/play.wav</Play>
  <Record action="https://your-domain.com/record_action/" method="POST"
          callbackUrl="https://your-domain.com/record_callback/" callbackMethod="POST"
          recordSession="true" redirect="false"
          maxLength="3600" playBeep="true"/>
  <Stream bidirectional="true" keepCallAlive="true">wss://your-server.com/ws</Stream>
  <Play>https://yourcdn.com/play.wav</Play>
</Response>
```

## RecordStop event callback parameters

A `RecordStop` event is posted to `callbackUrl` after recording stops. Use this event for final duration and the ready `RecordFile` or `RecordUrl` at `media.vobiz.ai`.

| Parameter | Type | Description |
| - | - | - |
| From | string | The calling party number. |
| RecordingID | string | The unique ID for the recording. |
| RecordFile | string | The URL of the recorded file. |
| RecordingEndMs | string | The timestamp when the recording ended. |
| BillRate | string | The billing rate for the call. |
| To | string | The called party number. |
| RecordingDurationMs | string | The duration of the recording in milliseconds. |
| CallUUID | string | The unique ID for the call. |
| ALegRequestUUID | string | The request UUID for the A leg of the call. |
| SessionStart | string | The timestamp when the session started. |
| Direction | string | The direction of the call (inbound or outbound). |
| RecordUrl | string | The URL of the recorded file. |
| RecordingDuration | string | The duration of the recording in seconds. |
| ALegUUID | string | The unique ID for the A leg of the call. |
| CallStatus | string | The status of the call. |
| ParentAuthID | string | The parent authentication ID. |
| RequestUUID | string | The unique ID for the request. |
| Event | string | The event type (RecordStop). |
| RecordingStartMs | string | The timestamp when the recording started. |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.