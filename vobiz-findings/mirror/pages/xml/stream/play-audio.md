> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Play audio event

> Send raw L16 or μ-law audio from your WebSocket application to Vobiz for playback on a live call.

Use `playAudio` to send audio from your WebSocket application to Vobiz for playback to the caller. The stream must use `bidirectional="true"`.

<Info>
  **Inbound and outbound formats are independent.** `start.mediaFormat` describes audio Vobiz sends to your application. `playAudio.media` describes audio your application sends to Vobiz. The two directions can use different supported formats.
</Info>

```text theme={null}
Inbound stream audio
Caller -> Vobiz -> your application
Decode using start.mediaFormat

Outbound playback audio
Your application -> Vobiz -> caller
Encode using playAudio.media
```

<Warning>
  **`playAudio` bypasses the conference mixer.** Audio sent this way is injected into
  the **call leg the stream rides**, not into the conference mix. Three consequences:

  * **`deaf` cannot silence it.** Deafening a member suppresses what the *mixer* sends
    them, and `playAudio` never passed through the mixer - a deafened member still
    hears anything played onto their own leg.
  * **A stream can only address its own leg**, never the room. To reach other
    participants use the per-member [Play](/docs/conference/members/play-audio) or Speak
    routes.
  * **`mute` on a leg does blind a stream attached to it**, because the media bug taps
    that leg's inbound audio - exactly what `mute` suppresses.

  This also means `deaf` cannot be tested against an AI agent at all. Testing it needs
  two human participants: deafen one, have the other speak.
</Warning>

## Event fields

| Field | Requirement | Description |
| - | - | - |
| `event` | Required | Set to `playAudio`. |
| `streamId` | Required | Use the `streamId` from the WebSocket `start` event to identify the active stream. |
| `media.contentType` | Required | Set to `audio/x-l16` or `audio/x-mulaw`. |
| `media.sampleRate` | Required | Set to the actual sample rate of the payload. |
| `media.payload` | Required | Base64-encoded raw mono audio without a file-container header. |

## Supported outbound playback formats

| Content type | Sample rate | Channels | Description |
| - | -: | -: | - |
| `audio/x-l16` | 8000 | 1 | 16-bit linear PCM at 8 kHz |
| `audio/x-l16` | 16000 | 1 | 16-bit linear PCM at 16 kHz |
| `audio/x-l16` | 24000 | 1 | 16-bit linear PCM at 24 kHz |
| `audio/x-mulaw` | 8000 | 1 | G.711 μ-law at 8 kHz |

<Warning>
  Your payload must genuinely match the declared `contentType` and `sampleRate`. Changing `sampleRate` in JSON does not resample the audio. A mismatched rate, stereo payload, file header, or incorrectly encoded payload can produce slow, fast, distorted, or silent playback.
</Warning>

For `audio/x-l16`, send signed 16-bit mono samples. For both formats:

* Remove WAV, MP3, or other file-container headers before Base64 encoding.
* Generate or resample the source audio at the declared rate.
* Validate the payload in your application before sending it. A playback checkpoint confirms queue progress, not encoding correctness.

## Send audio at 8, 16, or 24 kHz

The XML does not change when you change the outbound playback rate. Change both the real audio payload and `media.sampleRate` in the `playAudio` event.

<Tabs>
  <Tab title="L16 at 8 kHz">
    ```json theme={null}
    {
      "event": "playAudio",
      "streamId": "STREAM_ID",
      "media": {
        "contentType": "audio/x-l16",
        "sampleRate": 8000,
        "payload": "BASE64_ENCODED_RAW_L16_AUDIO"
      }
    }
    ```
  </Tab>

  <Tab title="L16 at 16 kHz">
    ```json theme={null}
    {
      "event": "playAudio",
      "streamId": "STREAM_ID",
      "media": {
        "contentType": "audio/x-l16",
        "sampleRate": 16000,
        "payload": "BASE64_ENCODED_RAW_L16_AUDIO"
      }
    }
    ```
  </Tab>

  <Tab title="L16 at 24 kHz">
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
  </Tab>

  <Tab title="μ-law at 8 kHz">
    ```json theme={null}
    {
      "event": "playAudio",
      "streamId": "STREAM_ID",
      "media": {
        "contentType": "audio/x-mulaw",
        "sampleRate": 8000,
        "payload": "BASE64_ENCODED_RAW_MULAW_AUDIO"
      }
    }
    ```
  </Tab>
</Tabs>

For example, your application can receive inbound L16/8 kHz audio in `media` events and send an outbound L16/24 kHz TTS response with `playAudio`.

<Warning>
  Do not set `<Stream contentType="audio/x-l16;rate=24000">` to request 24 kHz playback. `<Stream contentType>` configures inbound Vobiz-to-application audio. Set `24000` on the outbound `playAudio.media.sampleRate` field.
</Warning>

## Choose a chunk size

Send playback in approximately 20–60 ms chunks for responsive barge-in and predictable queueing. This is a recommendation, not a requirement.

| Format | Raw bytes for 20 ms |
| - | -: |
| `audio/x-mulaw` at 8000 Hz | 160 |
| `audio/x-l16` at 8000 Hz | 320 |
| `audio/x-l16` at 16000 Hz | 640 |
| `audio/x-l16` at 24000 Hz | 960 |

For L16, calculate the raw payload size with:

```text theme={null}
bytes = sample rate * 2 bytes per sample * duration in seconds
```

Smaller chunks let [`clearAudio`](/docs/xml/stream/clear-audio) discard queued speech sooner when the caller interrupts. Keep the chunk duration and payload format consistent within an utterance.

## Send playback from Node.js

```javascript theme={null}
function sendPlayAudio(ws, streamId, audioBuffer, sampleRate = 24000) {
  const event = {
    event: 'playAudio',
    streamId,
    media: {
      contentType: 'audio/x-l16',
      sampleRate,
      payload: audioBuffer.toString('base64')
    }
  };

  ws.send(JSON.stringify(event));
}
```

Pass raw mono audio to `audioBuffer`. If your TTS provider returns a WAV or another container, extract the raw samples before calling this function.

## Track playback completion

After the final `playAudio` chunk for an utterance, send a [`checkpoint`](/docs/xml/stream/checkpoint-event):

```json theme={null}
{
  "event": "checkpoint",
  "streamId": "STREAM_ID",
  "name": "response-1"
}
```

When playback reaches that checkpoint, Vobiz sends:

* A WebSocket `playedStream` event with the checkpoint name.
* An HTTP `PlayedStream` status callback when you configured `statusCallbackUrl`.

If the caller hangs up or [`clearAudio`](/docs/xml/stream/clear-audio) removes queued audio before the checkpoint, the completion event may not arrive. Use a timeout in your application instead of waiting indefinitely.

<Note>
  Sending L16/24 kHz audio to Vobiz does not guarantee 24 kHz audio at the handset. The carrier, SIP, or PSTN leg may use a lower-rate codec.
</Note>

## Next steps

* [Understand the complete event sequence](/docs/xml/stream/stream-events)
* [Clear queued audio for barge-in](/docs/xml/stream/clear-audio)
* [Stop a stream after playback](/docs/xml/stream/stop-event)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.