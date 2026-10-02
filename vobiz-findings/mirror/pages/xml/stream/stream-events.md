> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Stream Events Overview

> Use the Vobiz Stream WebSocket connection to send events from your application to control playback, mark checkpoints, and signal interruption.

<Info>
  **Prerequisites**

  To use stream events, you must:

  * Set `bidirectional="true"` on the `<Stream>` element.
  * Have an active WebSocket connection established by Vobiz.
  * Send events as JSON messages through the WebSocket.
</Info>

<Card title="Open the Stream Events Visualizer" icon="diagram-project" href="/docs/resources/stream-events-visualizer">
  Step through a complete bidirectional sequence and inspect each payload as it moves between Vobiz and your application.
</Card>

## 1. Bidirectional XML setup

Bidirectional streaming is the prerequisite for sending any command back to Vobiz. Configure it on the `<Stream>` XML element:

```xml Enable bidirectional audio streaming theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream
bidirectional="true"
keepCallAlive="true"
contentType="audio/x-l16;rate=8000">
wss://stream.vobiz.ai/stream
    </Stream>
</Response>
```

See [Initiate a Stream](/docs/xml/stream/initiate) for the full set of `<Stream>` attributes.

## 2. How events flow

Two directions, seven events total. Each event is documented in detail in the [Typical event sequence](#3-typical-event-sequence) below.

**App → Vobiz** - commands you send to control the call

| Event | Purpose | Details |
| - | - | - |
| `playAudio` | Queue outbound audio for playback to the caller. | [→ docs](/docs/xml/stream/play-audio) |
| `checkpoint` | Mark end of an utterance; ack arrives as `playedStream`. | [→ docs](/docs/xml/stream/checkpoint-event) |
| `clearAudio` | Drop queued playback audio on barge-in. | [→ docs](/docs/xml/stream/clear-audio) |
| `stop` | Terminate the stream from your side. | [→ Server-initiated stop](#server-initiated-stop) |

**Vobiz → App** - events your handler receives

| Event | Purpose |
| - | - |
| `start` | Stream connection established; carries `callId`, `streamId`, `mediaFormat`. Fires once. |
| `media` | Inbound 20 ms audio frame. Fires \~50 times per second per track. |
| `playedStream` | Ack that audio up to your most recent `checkpoint` finished playing. |
| `clearedAudio` | Ack that your `clearAudio` flushed the playback queue. |

<Warning>
  **There is no inbound `stop` event.** Vobiz does **not** send `{ "event": "stop" }` when the call ends - the WebSocket simply closes. Treat the WebSocket `close` event as your end-of-stream signal. See [Detecting end of stream](#detecting-end-of-stream) for the lifecycle details.

  `stop` exists **only as an outbound command** - see [Server-initiated stop](#server-initiated-stop).
</Warning>

<Warning>
  **`playedStream` is conditional.** It is only emitted if the audio queued before the matching `checkpoint` played to completion. If playback fails or is interrupted (e.g. by a `clearAudio`), you will not receive the ack.
</Warning>

## 3. Typical event sequence

A complete interactive turn - Vobiz opens the stream, your app greets the caller, the caller speaks, your app barges in with a new response.

<Steps>
  <Step title="Vobiz → App · start" stepNumber={1}>
    Fires once, immediately after Vobiz upgrades the WebSocket. Use it to set up per-call state (transcribers, recording paths, etc). The call/stream identifiers live **inside** the nested `start` object - not at the top level.

    ```json theme={null}
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

    | Field | Notes |
    | - | - |
    | `start.callId` | Matches the `CallUUID` returned by the REST call-create response and the `hangup_url` webhook. |
    | `start.streamId` | Identifies the active stream. Use it on commands your application sends to Vobiz, including the examples below. |
    | `start.accountId` | Internal numeric Vobiz account ID. Corresponds to the public `ParentAuthID` (`MA_…`) that appears on lifecycle webhooks. |
    | `start.tracks` | `["inbound"]` when `bidirectional="true"`. With `bidirectional="false"` you can also receive the outbound leg via `audioTrack="both"`. |
    | `start.mediaFormat` | Reports the inbound format Vobiz uses for `media` events. Supported inbound rates are L16 at `8000` or `16000`, and μ-law at `8000`. |

    `start.mediaFormat` reflects the inbound `contentType` selected on `<Stream>`. Decode every incoming `media.payload` using this value. It does not set the format for outbound `playAudio` events.
  </Step>

  <Step title="App → Vobiz · playAudio (greeting)" stepNumber={2}>
    Queue outbound audio for playback. The payload must match the `media.contentType` and `media.sampleRate` declared in this event. The outbound format can differ from the inbound `start.mediaFormat` when both formats are supported.

    ```json theme={null}
    {
      "event": "playAudio",
      "streamId": "c4dfd815-a92a-4140-ab85-5ff28c004116",
      "media": {
        "contentType": "audio/x-mulaw",
        "sampleRate": 8000,
        "payload": "base64-encoded-audio..."
      }
    }
    ```

    Use approximately 20–60 ms chunks for responsive barge-in. For a 20 ms chunk, μ-law/8 kHz uses 160 raw bytes and L16/8 kHz uses 320 raw bytes.

    <Note id="playaudio-streamid">
      Include the `streamId` from the `start` event in customer-facing `playAudio`, `clearAudio`, `checkpoint`, and `stop` commands.
    </Note>
  </Step>

  <Step title="App → Vobiz · checkpoint" stepNumber={3}>
    Send right after the last `playAudio` chunk of an utterance. Vobiz replies with `playedStream` once it has actually delivered the queued audio to the caller.

    ```json theme={null}
    {
      "event": "checkpoint",
      "streamId": "c4dfd815-a92a-4140-ab85-5ff28c004116",
      "name": "response-3"
    }
    ```
  </Step>

  <Step title="Vobiz → App · playedStream" stepNumber={4}>
    Acknowledgment that the audio queued before the checkpoint finished playing to the caller. The payload is **just** `event` + `name` - there is no `streamId` field.

    <Note>
      This is the uninterrupted-playback branch. In the [Stream Events Visualizer](/docs/resources/stream-events-visualizer), the caller barges in before the greeting finishes. That branch skips this acknowledgment, sends `clearAudio`, and continues after `clearedAudio`.
    </Note>

    ```json theme={null}
    {
      "event": "playedStream",
      "name": "response-3"
    }
    ```

    The `name` echoes the `name` you set in the matching `checkpoint`.
  </Step>

  <Step title="Vobiz → App · media (caller audio)" stepNumber={5}>
    One frame every 20 ms while the caller is on the line (\~50 per second per track). `media.payload` is base64-encoded raw audio in the encoding declared by `start.mediaFormat`.

    ```json theme={null}
    {
      "sequenceNumber": 2,
      "streamId": "c4dfd815-a92a-4140-ab85-5ff28c004116",
      "event": "media",
      "media": {
        "track": "inbound",
        "timestamp": "1778597597091",
        "chunk": 2,
        "payload": "base64-user-audio..."
      },
      "extra_headers": "{}"
    }
    ```

    | Field | Notes |
    | - | - |
    | `sequenceNumber` | Monotonic across the whole stream - starts at `0` on the `start` event and increments per message. |
    | `media.track` | `inbound` (caller) or `outbound` (callee). |
    | `media.timestamp` | Stream timestamp in ms on the Vobiz clock - not your server clock. |
    | `media.chunk` | Per-stream monotonic chunk index. |
    | `media.payload` | Base64-encoded raw audio in the inbound format reported by `start.mediaFormat`. |
  </Step>

  <Step title="App → Vobiz · clearAudio (barge-in)" stepNumber={6}>
    Drops everything queued in Vobiz that hasn't been streamed to the caller yet. Use this the moment your VAD detects the caller speaking over the bot.

    ```json theme={null}
    {
      "event": "clearAudio",
      "streamId": "c4dfd815-a92a-4140-ab85-5ff28c004116"
    }
    ```
  </Step>

  <Step title="Vobiz → App · clearedAudio" stepNumber={7}>
    Acknowledgment that the queued playback audio was flushed.

    ```json theme={null}
    {
      "event": "clearedAudio",
      "streamId": "c4dfd815-a92a-4140-ab85-5ff28c004116"
    }
    ```
  </Step>

  <Step title="App → Vobiz · playAudio (new response)" stepNumber={8}>
    Send the fresh response. Repeat steps 2–4 (`playAudio` → `checkpoint` → `playedStream`) for each utterance.

    ```json theme={null}
    {
      "event": "playAudio",
      "streamId": "c4dfd815-a92a-4140-ab85-5ff28c004116",
      "media": {
        "contentType": "audio/x-mulaw",
        "sampleRate": 8000,
        "payload": "base64-new-audio..."
      }
    }
    ```
  </Step>

  <Step title="App → Vobiz · stop (end the stream)" stepNumber={9}>
    When your agent is done, send a `stop` packet. The stream **stops immediately** and Vobiz proceeds to the next XML element in your response. If there is no next element, Vobiz hangs up the call with `HangupCauseCode=4010` ("End Of XML Instructions").

    ```json theme={null}
    {
      "event": "stop",
      "streamId": "c4dfd815-a92a-4140-ab85-5ff28c004116"
    }
    ```

    There is no inbound `stop` ack - the WebSocket close itself confirms it. Full webhook flow and the `Hangup` payload are in [Server-initiated stop](#server-initiated-stop) below.
  </Step>
</Steps>

## 4. Ending the stream

### Detecting end of stream

When the call ends, the last `media` frame arrives and the WebSocket closes. There is no in-band JSON `stop` event from Vobiz. The end-of-stream signals are, in order of arrival:

1. **The WebSocket `close` event** - the canonical signal, universal across every termination path.
2. **(Server-initiated stops only)** `Event=StopStream` POSTed to `statusCallbackUrl`.
3. **`Event=Hangup`** POSTed to `hangup_url` - the authoritative "call is over" signal regardless of who ended the call.

<Warning>
  Do **not** detect the end of a call by inspecting `media.payload`. Silence can appear at any point in a call and is not an end-of-stream marker.

  Do **not** wait for an inbound `{ "event": "stop" }` on the WebSocket - Vobiz does not emit one.

  The `StopStream` status callback is **only observed when the server initiates the stop** (it does fire reliably in that case). It does not fire when the caller hangs up or the call is killed mid-stream - fall back to the WebSocket `close` event and the `Hangup` webhook in those cases.

  Flush any in-memory recording/transcript buffers from your WebSocket `close` handler.
</Warning>

For a runnable reference that demonstrates this flow end-to-end (mid-stream frames → final frame → WAV flush on close), see the [Bun Media Stream Server](/docs/examples/vobiz-bun-media-stream#sample-console-output).

### Server-initiated stop

You can terminate the stream from your side by sending a `stop` command over the WebSocket. The stream **stops immediately** and Vobiz proceeds to the next XML element in your response:

* **If there is a next XML element** (e.g. `<Speak>`, `<Dial>`, `<Redirect>`), Vobiz executes it. The call continues without `<Stream>`.
* **If there is no next element**, Vobiz hangs up the call. The `Hangup` webhook will report `HangupCauseCode=4010` ("End Of XML Instructions") and `HangupSource=Vobiz`. You do not need to follow `<Stream>` with `<Hangup/>` for this - it's automatic.

```json theme={null}
{
  "event": "stop",
  "streamId": "c4dfd815-a92a-4140-ab85-5ff28c004116"
}
```

```python Producer snippet theme={null}
stop_event = {
    "event": "stop",
    "streamId": self.stream_id,
}
await websocket.send_text(json.dumps(stop_event))
```

**What happens after you send the `stop`:**

| Step | What Vobiz does |
| - | - |
| 1 | Stream stops immediately; WebSocket closes |
| 2 | Next XML element executes - or, if there is no next element, the call hangs up automatically |
| 3 | `Event=StopStream` POSTed to `statusCallbackUrl` |
| 4 | `Event=Hangup` POSTed to `hangup_url` (only if the call ended - i.e. no further XML elements after `<Stream>`) |

You don't need to wait for any WebSocket reply - once you've sent the `stop`, the WS closes and the lifecycle webhooks (if applicable) follow. There is no matching inbound `stop` JSON event; the WebSocket close itself is your acknowledgment.

The REST equivalent of this is [`POST /audio-streams/.../stop`](/docs/audio-streams/stop-audio-stream).

## 5. Node.js handler

A minimal reference handler that wires up the four most common code paths: receiving `start`, queueing `playAudio` + `checkpoint`, processing inbound `media`, and reacting to `playedStream`. Use it as a skeleton; replace the bodies with your STT/LLM/TTS pipeline.

```javascript Sending events from your WebSocket server theme={null}
const WebSocket = require('ws');

let streamId = null;

wss.on('connection', (ws) => {
  ws.on('message', (message) => {
    const data = JSON.parse(message);

    if (data.event === 'start') {
      streamId = data.start.streamId;
      console.log('Stream started:', streamId);

      // Play a greeting audio
      sendPlayAudio(ws, streamId, greetingAudioBase64);

      // Send checkpoint to track when greeting finishes
      sendCheckpoint(ws, streamId, 'greeting-complete');
    }

    if (data.event === 'playedStream') {
      console.log('Checkpoint reached:', data.name);
      // Greeting played successfully - continue with next action
    }

    if (data.event === 'media') {
      // Process incoming audio
      const audioData = Buffer.from(data.media.payload, 'base64');
      // ... analyze, transcribe, etc.
    }
  });

  ws.on('close', () => {
    // End-of-stream signal - flush recordings/transcripts here.
    console.log('Stream ended:', streamId);
  });
});

function sendPlayAudio(ws, streamId, audioBase64) {
  ws.send(JSON.stringify({
    event: 'playAudio',
    streamId,
    media: {
      contentType: 'audio/x-l16',
      sampleRate: 8000,
      payload: audioBase64
    }
  }));
}

function sendCheckpoint(ws, streamId, checkpointName) {
  ws.send(JSON.stringify({
    event: 'checkpoint',
    streamId: streamId,
    name: checkpointName
  }));
}

function sendClearAudio(ws, streamId) {
  ws.send(JSON.stringify({
    event: 'clearAudio',
    streamId: streamId
  }));
}

function sendStop(ws, streamId) {
  ws.send(JSON.stringify({
    event: 'stop',
    streamId: streamId
  }));
}
```

## 6. Runnable example

Use the [Bun Media Stream Server](/docs/examples/vobiz-bun-media-stream) to inspect `start` and `media` events, handle WebSocket closure, and save inbound audio for local testing.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.