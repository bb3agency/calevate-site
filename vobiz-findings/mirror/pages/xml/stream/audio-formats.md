> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Audio formats: 8, 16, and 24 kHz

> Choose and configure supported 8, 16, and 24 kHz audio formats for inbound Vobiz streams and outbound WebSocket playback.

Vobiz supports 8, 16, and 24 kHz audio across its WebSocket streaming flow. The supported rate depends on the audio direction.

An inbound stream carries caller audio from Vobiz to your application. Outbound playback carries agent or TTS audio from your application to Vobiz. Configure each direction independently.

<CardGroup cols={3}>
  <Card title="8 kHz" icon="phone">
    Use L16 or μ-law for inbound audio. Use L16 or μ-law for outbound playback.
  </Card>

  <Card title="16 kHz" icon="waveform">
    Use L16 for inbound audio or outbound playback.
  </Card>

  <Card title="24 kHz" icon="volume-high">
    Use L16 for outbound playback only. Do not configure 24 kHz as the inbound Stream format.
  </Card>
</CardGroup>

## Understand the two audio directions

```text theme={null}
Inbound stream audio
Caller -> Vobiz -> your WebSocket application
Configure with <Stream contentType> or REST content_type
Decode using start.mediaFormat

Outbound playback audio
Your WebSocket application -> Vobiz -> caller
Configure with playAudio.media.contentType and playAudio.media.sampleRate
```

| Direction | L16 at 8 kHz | L16 at 16 kHz | L16 at 24 kHz | μ-law at 8 kHz |
| - | - | - | - | - |
| Inbound: Vobiz to your application | Supported | Supported | Not supported | Supported |
| Outbound: your application to Vobiz | Supported | Supported | Supported | Supported |

<Warning>
  To play 24 kHz TTS audio, set `playAudio.media.sampleRate` to `24000` and send genuine L16/24 kHz audio. Do not set `<Stream contentType="audio/x-l16;rate=24000">`. The Stream `contentType` controls inbound audio only.
</Warning>

## Choose a sample rate

* Use **μ-law at 8 kHz** when your telephony or agent integration already works with G.711 μ-law.
* Use **L16 at 8 kHz** when your pipeline expects raw linear PCM at a telephony-oriented rate.
* Use **L16 at 16 kHz** when your STT or TTS service expects 16 kHz linear PCM.
* Use **L16 at 24 kHz** only for outbound playback when your TTS service produces genuine 24 kHz linear PCM.

Choose the rate that matches the next service in your pipeline. A higher declared rate does not convert or improve audio by itself.

<Note>
  A 24 kHz outbound payload does not guarantee 24 kHz audio at the handset. The carrier, SIP, or PSTN leg may use a lower-rate codec.
</Note>

## Configure inbound audio

Set the inbound format on the `<Stream>` element or the Audio Streams REST request.

| Inbound format | XML `contentType` | REST `content_type` |
| - | - | - |
| L16 at 8 kHz | `audio/x-l16;rate=8000` | `audio/x-l16;rate=8000` |
| L16 at 16 kHz | `audio/x-l16;rate=16000` | `audio/x-l16;rate=16000` |
| μ-law at 8 kHz | `audio/x-mulaw;rate=8000` | `audio/x-mulaw;rate=8000` |

The following XML requests inbound L16/16 kHz audio and enables outbound playback:

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Stream
      bidirectional="true"
      keepCallAlive="true"
      contentType="audio/x-l16;rate=16000">
    wss://your-domain.com/ws
  </Stream>
</Response>
```

When the WebSocket connects, Vobiz reports the selected inbound format in `start.mediaFormat`:

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

Save `streamId` for commands that you send to Vobiz. Decode every inbound `media.payload` using `start.mediaFormat` instead of assuming a rate in your application.

## Send outbound audio

Set `bidirectional="true"` on `<Stream>`, then send a `playAudio` event. The event must describe the actual encoding and sample rate of its payload.

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

The inbound and outbound formats do not need to match. For example, your application can receive inbound L16/16 kHz audio and send outbound L16/24 kHz TTS audio on the same bidirectional WebSocket.

## Prepare the payload

Before you Base64 encode audio for `playAudio`:

* Use raw mono audio.
* Remove WAV, MP3, and other file-container headers.
* For L16, use signed 16-bit samples.
* Generate or resample the audio at the rate declared in `media.sampleRate`.
* Do not change only the JSON sample rate. That does not resample the payload.

Send outbound audio in approximately 20–60 ms chunks for responsive barge-in. This range is a recommendation, not a protocol requirement.

| Format | Raw payload for 20 ms |
| - | -: |
| μ-law at 8 kHz | 160 bytes |
| L16 at 8 kHz | 320 bytes |
| L16 at 16 kHz | 640 bytes |
| L16 at 24 kHz | 960 bytes |

After the final `playAudio` chunk for an utterance, send a [`checkpoint`](/docs/xml/stream/checkpoint-event). Vobiz sends `playedStream` when playback reaches that checkpoint. Use [`clearAudio`](/docs/xml/stream/clear-audio) to discard queued playback when the caller interrupts.

## Common configuration errors

| Symptom | Check |
| - | - |
| 24 kHz inbound stream does not connect | Use supported inbound L16 at 8 or 16 kHz. Configure 24 kHz only on outbound `playAudio`. |
| Audio is slow, fast, distorted, or silent | Confirm that the payload's real encoding and rate match `contentType` and `sampleRate`. |
| A WAV or MP3 file does not play correctly | Remove the file-container header and send supported raw mono audio. |
| Vobiz does not accept `playAudio` | Confirm that `<Stream>` uses `bidirectional="true"` and that you include the active `streamId`. |
| Your application decodes inbound audio incorrectly | Read `start.mediaFormat` for each WebSocket connection. |

## Next steps

* [Initiate a Stream](/docs/xml/stream/initiate)
* [Understand Stream events](/docs/xml/stream/stream-events)
* [Send audio with `playAudio`](/docs/xml/stream/play-audio)
* [Build a custom WebSocket integration](/docs/integrations/websockets)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.