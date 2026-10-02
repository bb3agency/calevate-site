> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz Audio Streams API – Real-Time WebSocket Call Audio

> Fork live call audio to a WebSocket server in real time with the Vobiz Audio Streams API - enabling AI voice agents, speech transcription, sentiment analysis, and monitoring globally.

The Audio Streams API lets you fork the audio of a live call to a WebSocket server in near real time. You can start and stop streams dynamically during the call, retrieve the list of active streams, and optionally send audio back into the call using bidirectional streaming.

## Key Capabilities

* **Real-time Audio** - Fork inbound, outbound, or both tracks of a live call to your WebSocket in near real time.
* **Bidirectional Mode** - Enable `bidirectional=true` to send audio from your server back into the call.
* **Direction-specific formats** - Receive inbound L16 at 8 or 16 kHz, or μ-law at 8 kHz. In bidirectional mode, send outbound L16 playback at 8, 16, or 24 kHz, or μ-law at 8 kHz.
* **Status Callbacks** - Receive stream lifecycle events (`connected`, `stopped`, `timeout`, `failed`) on your callback URL.

<Info>
  **Important:** Your WebSocket server must accept connections over `wss://`. Audio packets are delivered as JSON frames containing base64-encoded payloads. See the [Stream XML element](/docs/xml/stream) to start streams from XML instead of the API.
</Info>

## API Endpoint

**Base URL**

```
https://api.vobiz.ai/api/v1
```

**Stream Base URI**

```
https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/Stream/
```

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account ID (e.g., `{auth_id}`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

## Available Operations

| Method | Operation | Description |
| - | - | - |
| OBJECT | [The Stream object](/docs/audio-streams/stream-object) | Complete structure and attributes of an audio Stream object including status, timing, and configuration fields. |
| POST | [Start an audio stream](/docs/audio-streams/start-audio-stream) | Start streaming audio from an active call to your WebSocket server with configurable tracks, codecs, and bidirectional mode. |
| GET | [Retrieve an audio stream](/docs/audio-streams/retrieve-audio-stream) | Get details of a specific audio stream on a call using its stream ID. |
| GET | [List all audio streams](/docs/audio-streams/list-audio-streams) | Retrieve all audio streams attached to a given call. |
| DELETE | [Stop a specific audio stream](/docs/audio-streams/stop-audio-stream) | Stop a single active audio stream on a call by its stream ID. |
| DELETE | [Stop all audio streams](/docs/audio-streams/stop-all-audio-streams) | Stop every active audio stream currently running on a call in one request. |

<Warning>
  **Note:** Audio streams are billed per minute of audio forked. Stopping a stream immediately halts billing for that stream.
</Warning>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.