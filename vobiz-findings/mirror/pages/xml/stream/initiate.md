> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Initiate a Stream

> Establish a WebSocket connection to Vobiz Stream and begin streaming raw audio from an active call - covers handshake, codecs, and authentication.

<Info>
  **What Happens**

  When Vobiz encounters a `Stream` element in your XML response:

  1. Vobiz initiates a WebSocket connection to your specified URL
  2. Once connected, raw audio packets are streamed in real-time
  3. Your application can process, analyze, or forward the audio
  4. For bidirectional streams, your app can also send audio back to the call
</Info>

## XML Setup

To initiate an audio stream, include the `Stream` element in your XML response with the WebSocket URL:

```xml Basic Stream XML theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream
bidirectional="true"
audioTrack="inbound"
streamTimeout="7200"
keepCallAlive="true">
wss://stream.vobiz.ai/stream
    </Stream>
</Response>
```

<Tip>
  **Understanding keepCallAlive**

  **Without `keepCallAlive="true"`:** The `<Stream>` element starts the background stream process and finishes immediately. Since there are no more elements in your XML response, the call hits "End Of XML Instructions" and hangs up instantly.

  **With `keepCallAlive="true"`:** The system explicitly waits for the stream to finish (disconnect/error/timeout) before moving on or hanging up. This keeps the call open without needing a `<Pause>` element.

  Note: `keepCallAlive` requires `bidirectional="true"`. Use this attribute instead of `<Pause>` for a cleaner implementation.
</Tip>

### Key Configuration Parameters

* **WebSocket URL:** The text content of the element (e.g., `wss://stream.vobiz.ai/stream`). Must be publicly reachable; use `wss://` (TLS) in production - `ws://` is for local testing only.
* **bidirectional:** Set to `true` to enable sending audio back to the call. Requires `audioTrack="inbound"` (or omit it).
* **audioTrack:** `inbound` (caller), `outbound` (callee), or `both`. Default `inbound`. Do not combine `both`/`outbound` with `bidirectional="true"`.
* **contentType:** Inbound codec and rate that Vobiz sends to your application. Use `audio/x-l16;rate=8000` (default), `audio/x-l16;rate=16000`, or `audio/x-mulaw;rate=8000`. Vobiz reports the selected format in `start.mediaFormat`.
* **streamTimeout:** Maximum streaming duration in seconds (default: 86400 / 24 hours). When reached, Vobiz stops the stream and (for server-side termination) fires `Event=StopStream`.
* **keepCallAlive:** Set to `true` to prevent the call from hanging up when the stream ends or encounters an error. Requires `bidirectional="true"`.
* **maxRetries:** Reconnect attempts if the WebSocket fails to open or drops mid-stream. Default `0` (disabled), max `10`.
* **statusCallbackUrl / extraHeaders:** See the full attribute reference on the [`<Stream>` element page](/docs/xml/stream).

For the complete attribute table, allowed values, and the HTTP status-callback payloads, see [Stream XML element](/docs/xml/stream).

<Info>
  `<Stream contentType>` configures inbound Vobiz-to-application audio. It does not configure the audio your application sends back. For outbound playback, set `playAudio.media.contentType` and `playAudio.media.sampleRate` on each [`playAudio`](/docs/xml/stream/play-audio) event.
</Info>

## WebSocket Connection

Your WebSocket server must be ready to accept connections from Vobiz. Here's what the initial connection looks like:

### Connection Start Message

```json Vobiz sends this when the stream starts theme={null}
{
  "sequenceNumber": 0,
  "event": "start",
  "start": {
    "callId": "5401fd2e-6344-40df-a22c-c8ffea7a92e7",
    "streamId": "c4dfd815-a92a-4140-ab85-5ff28c004116",
    "accountId": "500025",
    "tracks": ["inbound"],
    "mediaFormat": {
      "encoding": "audio/x-l16",
      "sampleRate": 16000
    }
  },
  "extra_headers": "{}"
}
```

This frame fires once, immediately after the WebSocket opens. The call and stream identifiers live inside the nested `start` object. `start.mediaFormat` reports the inbound format Vobiz will use for subsequent `media` events.

### Audio Data Messages

```json Continuous 20 ms audio frames sent during the stream theme={null}
{
  "sequenceNumber": 2,
  "streamId": "c4dfd815-a92a-4140-ab85-5ff28c004116",
  "event": "media",
  "media": {
    "track": "inbound",
    "timestamp": "1778597597091",
    "chunk": 2,
    "payload": "base64-encoded-audio"
  },
  "extra_headers": "{}"
}
```

Vobiz emits approximately 50 `media` frames per second (one every 20 ms) while the call is active. `media.payload` contains base64-encoded raw audio in the inbound format declared by `start.mediaFormat`. Individual `media` events do not repeat `contentType` or `sampleRate`, so initialize your decoder from the `start` event.

### End of stream

When the call ends, the sequence Vobiz sends over the WebSocket is:

1. The final `media` frame (no special marker - its shape is identical to every other `media` frame).
2. The WebSocket **`close`** event - this is the end-of-stream signal.
3. Out-of-band: the `hangup_url` HTTP webhook fires with the full `Event=Hangup` payload (`HangupCause`, `Duration`, `EndTime`, etc).

```javascript Handle end of stream from your close handler theme={null}
ws.on('close', (code, reason) => {
  console.log(`Stream ended: ${streamId}`, code, reason?.toString());
  // Flush recording / transcripts / per-call state here.
});
```

End-of-stream triggers include: the caller hanging up, the carrier ending the call, `streamTimeout` being reached, or your own server sending a [`stop` command](/docs/xml/stream/stream-events#server-initiated-stop).

<Warning>
  **Vobiz does not send an inbound `{ "event": "stop" }`.** The WebSocket simply **closes** after the final `media` frame - that is the only in-band signal. If you're waiting for a `stop` JSON message on the socket, you'll wait forever.

  `Event=StopStream` on `statusCallbackUrl` is **only delivered when the server initiates the termination** via an outbound `stop` packet (it fires reliably in that case). It does not fire for caller-hangup or mid-stream-kill paths.

  The authoritative "call is over" signal across all termination paths is the **`hangup_url`** HTTP webhook, which fires once with `Event=Hangup` plus the full hangup payload. Configure it on the REST call-create request.

  `stop` does exist as an **outbound** (Server → Vobiz) command for agent-initiated hangup - see [Server-initiated stop](/docs/xml/stream/stream-events#server-initiated-stop) on the Stream events page.
</Warning>

## Connection Flow

1. **Vobiz receives your XML response** containing the Stream element
2. **WebSocket connection established** to your specified URL
3. **"start" event sent** with call metadata and stream configuration
4. **Continuous "media" events** stream audio packets in real-time
5. **Bidirectional streams (optional):** Your app can send playAudio events back to Vobiz
6. **WebSocket close** - the final `media` frame is followed by a socket close (no inbound `stop` event)
7. **`hangup_url` webhook fires** with the authoritative `Event=Hangup` payload

## Reconnects and idempotency

If the WebSocket fails to open or drops mid-stream and you set `maxRetries` (1-10) on the `<Stream>` element, Vobiz retries the connection. Each retry is a **fresh connection**: it opens a new socket and replays a new `start` event with a **new `streamId`** (the `callId` stays the same).

Design your handler to be idempotent across reconnects:

* Key per-call state on `start.callId`, not `start.streamId`, so a reconnect resumes the same logical session.
* Expect to receive a second `start` after a drop. Re-send your greeting only if the conversation hadn't progressed, or resume from saved state.
* A `close` you see may be a transient drop that Vobiz will retry, not the end of the call. The authoritative end-of-call signal is the `hangup_url` `Event=Hangup` webhook (see below).

With `maxRetries="0"` (the default), a dropped socket is terminal.

## Implementation Examples

<Tip>
  Prefer a runnable reference? See the [Bun Media Stream Server](/docs/examples/vobiz-bun-media-stream) - a minimal sink-only example that answers a call with `<Stream>`, records audio to WAV, and logs status callbacks. Drop in your own STT/LLM/TTS pipeline to extend it.
</Tip>

### Node.js WebSocket Server

```javascript Simple WebSocket server to receive audio theme={null}
const WebSocket = require('ws');

const wss = new WebSocket.Server({ port: 8080 });

wss.on('connection', (ws) => {
  console.log('Vobiz connected to audio stream');

  ws.on('message', (message) => {
    const data = JSON.parse(message);

    if (data.event === 'start') {
      console.log('Stream started:', data.start.streamId);
      console.log('Call ID:', data.start.callId);
    } else if (data.event === 'media') {
      // Decode the payload using data.start.mediaFormat saved for this stream.
      const audioBuffer = Buffer.from(data.media.payload, 'base64');
      console.log('Received audio chunk:', audioBuffer.length, 'bytes');

      // Your audio processing logic here
      // e.g., send to transcription service, save to file, etc.
    }
    // Note: Vobiz does NOT send an inbound { event: 'stop' }.
    // Detect end of stream via the 'close' event below.
  });

  ws.on('close', () => {
    // Canonical end-of-stream signal. Flush recordings/transcripts here.
    console.log('WebSocket connection closed');
  });
});

console.log('WebSocket server listening on port 8080');
```

### Python WebSocket Handler

```python Python asyncio WebSocket server theme={null}
import asyncio
import websockets
import json
import base64

async def handle_audio_stream(websocket, path):
    print("Vobiz connected to audio stream")

    async for message in websocket:
data = json.loads(message)

if data['event'] == 'start':
print(f"Stream started: {data['start']['streamId']}")
print(f"Call ID: {data['start']['callId']}")

elif data['event'] == 'media':
            # Decode the payload using the start.mediaFormat saved for this stream.
audio_bytes = base64.b64decode(data['media']['payload'])
print(f"Received audio chunk: {len(audio_bytes)} bytes")

            # Your audio processing logic here
            # e.g., send to transcription, analysis, etc.

            # Note: Vobiz does NOT send an inbound 'stop' event.
            # The async-for loop exits when the socket closes - that is
            # your end-of-stream signal.

async def main():
    async with websockets.serve(handle_audio_stream, "0.0.0.0", 8080):
print("WebSocket server listening on port 8080")
await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
```

### Vobiz XML Response with Stream

```xml Complete example with status callbacks theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>This call is being recorded for quality assurance.</Speak>
    <Stream
bidirectional="false"
audioTrack="both"
streamTimeout="3600"
statusCallbackUrl="https://api.vobiz.ai/stream-status"
statusCallbackMethod="POST"
contentType="audio/x-mulaw;rate=8000"
extraHeaders="session_id=abc123,agent_id=john">
wss://stream.vobiz.ai/stream
    </Stream>
    <Dial>+14155551234</Dial>
</Response>
```

This example streams both inbound and outbound audio with 8kHz sample rate (Mu-law), includes custom session headers, and sends status updates to your callback URL.

## Troubleshooting

<Warning>
  **Invalid Stream Configuration**

  **Problem:** If your call hangs up with `End Of XML Instructions`, you likely have an invalid configuration.

  **Solution:** The media server does not support `audioTrack="both"` when `bidirectional="true"`. You must set `audioTrack="inbound"` (or remove the attribute) for bidirectional streams.
</Warning>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.