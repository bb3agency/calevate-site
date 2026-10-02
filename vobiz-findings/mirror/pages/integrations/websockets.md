> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Build an AI voice agent with WebSockets

> Connect a custom AI voice agent to Vobiz with bidirectional WebSocket audio, direction-specific formats, playback, checkpoints, and barge-in.

Use a bidirectional `<Stream>` when you want your own WebSocket server to run the speech-to-text, agent, text-to-speech, and barge-in logic for a call.

## Resources

* **GitHub repository:** [Vobiz-Python-Voice-API-Example](https://github.com/vobiz-ai/Vobiz-Python-Voice-API-Example)
* **Stream reference:** [`<Stream>` XML element](/docs/xml/stream)
* **Event reference:** [Stream events](/docs/xml/stream/stream-events)

## Start the WebSocket stream

Return this XML from your call's Answer URL:

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Stream
      bidirectional="true"
      keepCallAlive="true"
      statusCallbackUrl="https://your-domain.com/stream-status"
      statusCallbackMethod="POST">
    wss://your-domain.com/ws
  </Stream>
</Response>
```

The WebSocket URL is the text content of `<Stream>`. Use `wss://` in production.

## Understand the two audio directions

```text theme={null}
Inbound stream audio
Caller -> Vobiz -> your WebSocket application
Configured by <Stream contentType> and reported by start.mediaFormat

Outbound playback audio
Your WebSocket application -> Vobiz -> caller
Configured by playAudio.media.contentType and playAudio.media.sampleRate
```

Your inbound and outbound formats can differ. For example, you can decode inbound L16/8 kHz audio and send an outbound L16/24 kHz TTS response.

<Warning>
  Do not put `contentType="audio/x-l16;rate=24000"` on `<Stream>` to configure 24 kHz TTS playback. That attribute controls inbound Vobiz-to-application audio. Declare 24 kHz on the outbound `playAudio` event.
</Warning>

## Handle WebSocket events

Vobiz sends these events to your application:

| Event | Purpose |
| - | - |
| `start` | Provides `callId`, `streamId`, tracks, and the inbound `mediaFormat`. |
| `media` | Carries Base64-encoded inbound audio. |
| `playedStream` | Confirms playback reached a named checkpoint. |
| `clearedAudio` | Confirms queued outbound playback was cleared. |

Your application sends these commands to Vobiz:

| Command | Purpose |
| - | - |
| `playAudio` | Queue outbound audio for the caller. |
| `checkpoint` | Mark playback progress after an utterance. |
| `clearAudio` | Remove queued audio when the caller interrupts. |
| `stop` | End the streaming session. |

When the call ends, handle the WebSocket `close` event. Do not wait for an inbound `{ "event": "stop" }` message.

## Decode inbound audio

Save the `streamId` and initialize your decoder from the `start` event:

```json theme={null}
{
  "event": "start",
  "start": {
    "callId": "CALL_ID",
    "streamId": "STREAM_ID",
    "tracks": ["inbound"],
    "mediaFormat": {
      "encoding": "audio/x-l16",
      "sampleRate": 8000
    }
  }
}
```

Supported inbound formats are:

| Format | Sample rate |
| - | -: |
| L16 | 8000 or 16000 Hz |
| μ-law | 8000 Hz |

Base64-decode each `media.payload`, then pass the raw audio to a decoder or STT service configured for `start.mediaFormat`. Do not assume the inbound format matches your outbound TTS format.

## Send outbound playback

Vobiz accepts these outbound `playAudio` formats:

| Format | Sample rate |
| - | -: |
| L16 | 8000, 16000, or 24000 Hz |
| μ-law | 8000 Hz |

Send raw mono audio without a WAV, MP3, or other file header:

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

The payload must genuinely match the declared format. If your TTS provider returns audio at another rate or in a container, convert it before Base64 encoding. Changing only `sampleRate` does not resample the audio.

Send approximately 20–60 ms per `playAudio` message for responsive barge-in. This is a recommendation, not a protocol requirement.

## Track completion and handle barge-in

After the final playback chunk for an utterance, send a checkpoint:

```json theme={null}
{
  "event": "checkpoint",
  "streamId": "STREAM_ID",
  "name": "response-1"
}
```

When playback reaches it, Vobiz sends `playedStream` with the same name. If the caller interrupts, send:

```json theme={null}
{
  "event": "clearAudio",
  "streamId": "STREAM_ID"
}
```

Cleared or interrupted playback may not produce `playedStream`. Add a timeout so your application does not wait indefinitely.

## Processing pipeline

```text theme={null}
Caller audio
  -> start.mediaFormat
  -> Base64 decode
  -> STT
  -> agent or LLM
  -> TTS at a supported outbound rate
  -> raw mono audio
  -> Base64 encode
  -> playAudio
  -> caller
```

Your STT and TTS providers may require different formats. Convert only at the boundary that needs it, and keep the declared metadata synchronized with the real bytes.

<Note>
  A 24 kHz `playAudio` payload does not guarantee 24 kHz audio at the handset. The phone-facing carrier, SIP, or PSTN leg may use a lower-rate codec.
</Note>

## Troubleshooting

<AccordionGroup>
  <Accordion title="Playback is slow, fast, or robotic">
    Confirm the real payload rate matches `playAudio.media.sampleRate`. Remove file headers and ensure the audio is mono.
  </Accordion>

  <Accordion title="The agent does not stop when the caller speaks">
    Send `clearAudio` as soon as your voice-activity detector confirms barge-in. Keep playback chunks small so less audio remains queued.
  </Accordion>

  <Accordion title="The call ends immediately">
    Set `bidirectional="true"` and `keepCallAlive="true"`. For bidirectional streams, use `audioTrack="inbound"` or omit `audioTrack`.
  </Accordion>

  <Accordion title="Cleanup never runs">
    Handle the WebSocket `close` event. Vobiz does not send an inbound `stop` JSON event when the call ends.
  </Accordion>
</AccordionGroup>

## Next steps

* [Play audio at 8, 16, or 24 kHz](/docs/xml/stream/play-audio)
* [Implement checkpoint tracking](/docs/xml/stream/checkpoint-event)
* [Implement barge-in with clearAudio](/docs/xml/stream/clear-audio)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.