> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bun Media Stream Server

> Minimal Bun WebSocket server that receives Vobiz call audio, writes it to WAV, and logs status callbacks.

A minimal [Bun](https://bun.sh) server that answers a Vobiz call with a `<Stream>` XML, accepts the inbound WebSocket, and writes each call's audio to a local WAV file. Use it as a sink-only reference when bringing up a new agent stack - replace the WAV writer with your own STT/LLM/TTS pipeline once frames are flowing.

<Card title="Run the example" icon="rocket" horizontal>
  `bun install && bun start` - server listens on port `3000` by default.
</Card>

## What it does

The server exposes three endpoints:

| Endpoint | Purpose |
| - | - |
| `GET /` | Returns VobizXML containing a `<Stream>` element pointing at `/stream`. |
| `WS /stream` | Receives `start` / `media` / `stop` JSON frames; writes audio to `recordings/call-<timestamp>.wav`. |
| `POST /webhook` | Receives status callbacks (`StartStream`, `MediaError`, `StopStream`, ...) and appends each to `webhook-events.log`. |

It is **sink-only** - it does not send `playAudio` / `checkpoint` / `clearAudio` / `stop` packets back to Vobiz. The full bidirectional protocol is documented in [Stream Events](/docs/xml/stream/stream-events), [Play Audio](/docs/xml/stream/play-audio), [Checkpoint Event](/docs/xml/stream/checkpoint-event), and [Clear Audio](/docs/xml/stream/clear-audio); extend `index.js` with those once you wire in an agent.

## Run it

```bash theme={null}
bun install
bun start
```

To change the port:

```bash theme={null}
PORT=3333 bun index.js
```

Expose the local server with ngrok and update the two URL constants in `index.js`:

```bash theme={null}
ngrok http 3000
```

```js theme={null}
const PUBLIC_WS_URL = "wss://your-ngrok-domain.ngrok-free.app/stream";
const WEBHOOK_URL  = "https://your-ngrok-domain.ngrok-free.app/webhook";
```

## VobizXML answer response

`GET /` returns:

```xml theme={null}
<Response>
  <Stream
    bidirectional="true"
    statusCallbackUrl="https://your-ngrok-domain.ngrok-free.app/webhook"
    keepCallAlive="true">
    wss://your-ngrok-domain.ngrok-free.app/stream
  </Stream>
</Response>
```

| Attribute | Purpose |
| - | - |
| `bidirectional="true"` | Caller audio streams to your server **and** your server can stream audio back. |
| `keepCallAlive="true"` | Keeps the call up while no further XML is executing - required for long-running agent sessions. |
| `statusCallbackUrl` | Vobiz POSTs lifecycle events here (`StartStream`, `MediaError`, `StopStream`, ...). |

See [Initiate a Stream](/docs/xml/stream/initiate) for the full set of `<Stream>` attributes.

## What the handler does with each frame

1. `GET /` returns the `<Response><Stream>…</Stream></Response>` XML.
2. On WebSocket `/stream` open, allocates `recordings/call-<ISO timestamp>.wav`.
3. On every `media` frame, Base64-decodes `media.payload`, converts it to the WAV representation used by this example, and appends it to the buffer.
4. On close, flushes the buffered PCM to disk as a mono 16-bit WAV.
5. On `POST /webhook`, appends each status event to `webhook-events.log` as one JSON line.

## Sample console output

A live call produces one `media` frame every 20 ms. A typical mid-stream frame looks like:

```js Mid-stream media frame theme={null}
{
  sequenceNumber: 206,
  streamId: "7f169b6e-130d-46a3-b135-e1cc342c1ca2",
  event: "media",
  media: {
    track: "inbound",
    timestamp: "1778574097426",
    chunk: 206,
    payload: "+P/4/wgACAAIAAgA+P/o//j/+P/4//j/CAAIAAgACAAIAAgACAAIAPj/..."
  },
  extra_headers: "{}"
}
```

### The last media frame

When the caller hangs up, the **final `media` frame** arrives, the WebSocket closes, and the buffered PCM is flushed to a WAV. There is **no special marker inside the last frame** - its shape is identical to every other `media` frame; stream end is signalled by the `stop` event (and the subsequent socket close), not by the frame contents.

In this real example, `sequenceNumber: 274` was the final frame - its payload happens to be all `0xFF` bytes (L16 `-1`, i.e. silence as the carrier wound the call down), but that is a property of the audio at that instant, not an end-of-stream indicator:

```js Final media frame, immediately followed by socket close + WAV flush theme={null}
{
  sequenceNumber: 274,
  streamId: "7f169b6e-130d-46a3-b135-e1cc342c1ca2",
  event: "media",
  media: {
    track: "inbound",
    timestamp: "1778574098786",
    chunk: 274,
    payload: "/////////////////////////////////////////////////////////8="
  },
  extra_headers: "{}"
}
WAV recording saved: /home/user/bun/recordings/call-2026-05-12T08-21-33-347Z.wav
```

<Warning>
  Do **not** detect end-of-call by inspecting `media.payload` (e.g. looking for all-`/` base64 or all-`0xFF` bytes). That pattern is just silence at 8 kHz L16 - it can appear mid-call during any pause.

  End-of-stream signals, in order of arrival:

  1. **The WebSocket `close` event** - universal across every termination path. Vobiz does **not** send an inbound `{ "event": "stop" }`; the socket simply closes after the final `media` frame. See [Detecting end of stream](/docs/xml/stream/stream-events#detecting-end-of-stream).
  2. **`Event=StopStream` on `statusCallbackUrl`** - fires **only for server-initiated stops** (when your code sends a `stop` packet). Does not fire for caller-hangup or mid-stream-kill.
  3. **`Event=Hangup` on `hangup_url`** - fires in every case. This is the authoritative "call is over" signal.

  The example server flushes the WAV in its WebSocket `close` handler, which is why the "WAV recording saved" line is the last log entry of a call.
</Warning>

## Audio format

The example's `<Stream>` element negotiates:

* Encoding: **L16** (linear 16-bit PCM)
* Sample rate: **8000 Hz**
* Channels: Mono
* Chunk size: **20 ms** (320 bytes per frame at 8 kHz L16)

For agent use cases, switch to μ-law by adding `contentType="audio/x-mulaw;rate=8000"` to the `<Stream>` tag - the JSON envelope is unchanged, only the bytes inside `media.payload` differ.

| Property | L16 | μ-law |
| - | - | - |
| `contentType` | `audio/l16` (this example) | `audio/x-mulaw;rate=8000` |
| Bit depth | 16-bit | 8-bit |
| Bytes per 20 ms frame | 320 | 160 |

## Output files

```text theme={null}
recordings/call-YYYY-MM-DDTHH-MM-SS-MMMZ.wav
webhook-events.log
```

Each WebSocket connection produces a timestamped WAV. Webhook events are appended as one JSON line per event with a `receivedAt` timestamp.

## Extending it

To turn this sink into a full agent, send these frames back over the same socket - see the linked protocol pages for the exact JSON shape:

* [`playAudio`](/docs/xml/stream/play-audio) - queue a 20 ms chunk for playback.
* [`checkpoint`](/docs/xml/stream/checkpoint-event) - mark end of an utterance; Vobiz replies with `playedStream` once it's actually played.
* [`clearAudio`](/docs/xml/stream/clear-audio) - drop queued audio on barge-in; Vobiz replies with `clearedAudio`.
* `stop` - terminate the call leg from the WebSocket side without a second REST round-trip. Equivalent REST option: [`POST /audio-streams/.../stop`](/docs/audio-streams/stop-audio-stream).

## Related

* [Initiate a Stream](/docs/xml/stream/initiate) - full `<Stream>` XML reference.
* [Stream events](/docs/xml/stream/stream-events) - every inbound JSON event.
* [Vobiz + Pipecat](/docs/examples/vobiz-x-pipecat) - same idea, Python + Pipecat pipeline instead of Bun.
* [WebSockets integration](/docs/integrations/websockets) - protocol-level overview.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.