> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Voice streaming over WebSockets

> Understand how Vobiz sends inbound call audio to your WebSocket application and receives independent outbound playback audio.

Vobiz can fork live call audio to your WebSocket application. Your application can transcribe the caller, run agent logic, generate speech, and send audio back to the caller on the same connection.

Use WebSocket streaming when you want to own the STT, agent, TTS, voice-activity detection, barge-in, and conversation state.

## How the connection starts

You can create a stream in two ways:

* Return a [`<Stream>` XML element](/docs/xml/stream) from the call's Answer URL.
* Start an [Audio Stream through REST](/docs/audio-streams/start-audio-stream) on an active call.

For a bidirectional XML stream:

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Stream bidirectional="true" keepCallAlive="true">
    wss://your-domain.com/ws
  </Stream>
</Response>
```

Vobiz connects to your WebSocket, sends a `start` event, and then sends inbound `media` events while the call is active.

## Treat the audio directions separately

```text theme={null}
Inbound stream audio
Caller -> Vobiz -> your WebSocket application
Configured by <Stream contentType> or REST content_type
Reported by start.mediaFormat

Outbound playback audio
Your WebSocket application -> Vobiz -> caller
Configured by playAudio.media.contentType and playAudio.media.sampleRate
```

The two directions can use different supported formats. Always identify a format by its direction instead of using the ambiguous phrase “stream sample rate.”

<Warning>
  To play 24 kHz agent audio, send genuine L16/24 kHz data in `playAudio` with `sampleRate: 24000`. Do not configure inbound `<Stream contentType>` or REST `content_type` as L16/24 kHz for this purpose.
</Warning>

## Inbound stream formats

Vobiz reports the selected inbound format in `start.mediaFormat`.

| Encoding | Inbound sample rates |
| - | - |
| `audio/x-l16` | 8000 or 16000 Hz |
| `audio/x-mulaw` | 8000 Hz |

Use `start.mediaFormat` to configure your Base64 decoder, audio processor, or STT service for every connection.

```json theme={null}
{
  "event": "start",
  "start": {
    "callId": "CALL_ID",
    "streamId": "STREAM_ID",
    "tracks": ["inbound"],
    "mediaFormat": {
      "encoding": "audio/x-l16",
      "sampleRate": 16000
    }
  }
}
```

## Outbound playback formats

Your application sends agent or TTS audio with `playAudio`.

| Encoding | Outbound sample rates |
| - | - |
| `audio/x-l16` | 8000, 16000, or 24000 Hz |
| `audio/x-mulaw` | 8000 Hz |

```json theme={null}
{
  "event": "playAudio",
  "streamId": "STREAM_ID",
  "media": {
    "contentType": "audio/x-l16",
    "sampleRate": 24000,
    "payload": "BASE64_ENCODED_RAW_L16_AUDIO"
  }
}
```

The payload must be raw mono audio without a WAV, MP3, or other container header. Its real encoding and sample rate must match the metadata in the event.

<Note>
  A 24 kHz outbound payload does not guarantee 24 kHz audio at the handset. The phone-facing carrier, SIP, or PSTN leg may use a lower-rate codec.
</Note>

## WebSocket protocol

Vobiz sends:

| Event | Purpose |
| - | - |
| `start` | Identifies the call and stream and reports the inbound media format. |
| `media` | Delivers Base64-encoded inbound audio. |
| `playedStream` | Confirms playback reached a named checkpoint. |
| `clearedAudio` | Confirms queued playback was cleared. |

Your application sends:

| Command | Purpose |
| - | - |
| `playAudio` | Queues outbound playback audio. |
| `checkpoint` | Marks the end of an utterance for completion tracking. |
| `clearAudio` | Drops queued playback during barge-in. |
| `stop` | Ends the stream. |

When the call ends, Vobiz closes the WebSocket. Treat the `close` event as the in-band end-of-stream signal instead of waiting for an inbound `stop` JSON event.

## Voice-agent flow

```text theme={null}
1. Vobiz sends start with the inbound media format.
2. Vobiz sends caller audio in media events.
3. Your application decodes the payload using start.mediaFormat.
4. Your STT service transcribes the caller.
5. Your agent generates a response.
6. Your TTS service generates audio at a supported outbound rate.
7. Your application sends raw audio in playAudio events.
8. Your application sends a checkpoint after the utterance.
9. Vobiz sends playedStream when playback reaches the checkpoint.
```

## Chunking and barge-in

Send outbound playback in approximately 20–60 ms chunks. This range is recommended for responsive barge-in; it is not a protocol requirement.

For 20 ms of mono audio:

| Format | Raw payload size |
| - | -: |
| μ-law/8000 | 160 bytes |
| L16/8000 | 320 bytes |
| L16/16000 | 640 bytes |
| L16/24000 | 960 bytes |

When your voice-activity detector confirms that the caller is interrupting, send `clearAudio` with the active `streamId`. Audio removed before its checkpoint may not produce a `playedStream` event, so add a timeout to checkpoint-dependent application logic.

## Format conversion

Convert audio only when the next system requires another format:

```text theme={null}
Inbound
media.payload -> Base64 decode -> decode using start.mediaFormat -> STT format

Outbound
TTS output -> convert to supported raw mono format -> Base64 encode -> playAudio
```

Do not automatically downsample every TTS response to μ-law/8 kHz. If your application sends supported L16 playback, declare the actual L16 rate in `playAudio`. If your integration is configured for μ-law/8 kHz, resample and encode the payload before sending it.

## Implementation responsibilities

Your application must:

* Keep per-call state for each WebSocket connection.
* Save `callId`, `streamId`, and `start.mediaFormat` from the `start` event.
* Validate outbound audio before sending it.
* Serialize concurrent WebSocket writes.
* Clear queued playback when the caller interrupts.
* Handle conditional checkpoint acknowledgments and timeouts.
* Clean up STT, TTS, buffers, and conversation state on WebSocket close.

## Next steps

* [Build a custom WebSocket voice agent](/docs/integrations/websockets)
* [Review the complete stream event sequence](/docs/xml/stream/stream-events)
* [Send outbound playback audio](/docs/xml/stream/play-audio)
* [Compare SIP and WebSocket integrations](/docs/concepts/sip-vs-websockets)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.