> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# The Stream Object

> Understand every field on the Vobiz audio Stream object: stream ID, status, codec, track direction, WebSocket URL, bidirectional mode, and start/end timestamps.

The Stream object represents an audio stream attached to an active call. It captures the configuration you provided when starting the stream (WebSocket URL, codec, track, bidirectional mode) along with runtime metadata such as status, start time, and end time.

<Note>
  A single call may have multiple concurrent streams. Each stream is identified by a unique `stream_id` and can be stopped independently.
</Note>

## Attributes

| Field | Type | Description |
| - | - | - |
| `stream_id` | string | Unique identifier for the stream. Used in API operations to identify specific streams. |
| `call_uuid` | string | The UUID of the call this stream is attached to. |
| `service_url` | string | WebSocket URL (wss\:// or ws\://) to which Vobiz forwards the forked audio. |
| `audio_track` | string | Which audio track is being streamed. One of "inbound", "outbound", "both". |
| `bidirectional` | boolean | Whether the WebSocket is also allowed to send audio back into the call. |
| `content_type` | string | Format used for inbound audio sent to the WebSocket. One of "audio/x-l16;rate=8000", "audio/x-l16;rate=16000", or "audio/x-mulaw;rate=8000". Vobiz reports this format in `start.mediaFormat`. |
| `sampling_rate` | integer | Inbound audio sample rate in Hz, parsed from `content_type`. One of 8000 or 16000 for L16; μ-law is fixed at 8000. |
| `stream_timeout` | integer | Maximum stream duration in seconds. The stream is automatically stopped when this limit is reached. |
| `status_callback_url` | string | URL invoked via HTTP POST when the stream status changes (connected, stopped, timeout, failed). |
| `status_callback_method` | string | HTTP method used to invoke status\_callback\_url. One of "GET", "POST". Default: "POST". |
| `status` | string | Current status of the stream. One of "in-progress", "completed", "failed". |
| `start_time` | string | Timestamp when the stream started (ISO 8601 with timezone). |
| `end_time` | string | Timestamp when the stream ended. Null while the stream is still active. |
| `resource_uri` | string | Relative URI of this Stream resource. |

## Example

```json Stream Object theme={null}
{
    "api_id": "15b27100-1231-11ee-b875-0242ac110003",
    "call_uuid": "6e558798-499c-4a68-bc77-46f2c53d1f69",
    "stream_id": "2b1b3f8e-4c9a-4f2a-9e2d-7f9d0b1c2a34",
    "service_url": "wss://example.com/audio-stream",
    "audio_track": "inbound",
    "bidirectional": false,
    "content_type": "audio/x-l16",
    "sampling_rate": 8000,
    "stream_timeout": 86400,
    "status_callback_url": "https://example.com/stream-status",
    "status_callback_method": "POST",
    "status": "in-progress",
    "start_time": "2025-11-06 13:49:10+00:00",
    "end_time": null,
    "resource_uri": "/v1/Account/MA_PU0XU668/Call/6e558798-499c-4a68-bc77-46f2c53d1f69/Stream/2b1b3f8e-4c9a-4f2a-9e2d-7f9d0b1c2a34/"
}
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.