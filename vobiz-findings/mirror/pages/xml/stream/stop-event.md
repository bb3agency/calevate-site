> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Stop Event

> Send a stop event via Vobiz Stream WebSocket to terminate the stream from your application - Vobiz immediately proceeds to the next XML element, or hangs up if none exists.

<Info>
  **Purpose**

  The `stop` event terminates the stream from your application's side. When Vobiz receives it:

  * The stream stops **immediately** and the WebSocket closes
  * Vobiz moves to the **next XML element** in your response (e.g. `<Speak>`, `<Dial>`, `<Redirect>`)
  * If there is **no next element**, Vobiz hangs up the call automatically (`HangupCauseCode=4010`)
</Info>

## Attributes

| Attribute | Description |
| - | - |
| `event` <br /> *string* <br /> **Required** | Indicates the event type. Use `stop` as the value. |
| `streamId` <br /> *string* <br /> **Required** | A unique identifier generated for each audio stream. <br />This value is provided by Vobiz in the initial "start" event when the WebSocket connection is established. |

## Request & Response

### Request Format

Send this JSON message through the WebSocket to terminate the stream:

```json Stop event request theme={null}
{
  "event": "stop",
  "streamId": "c4dfd815-a92a-4140-ab85-5ff28c004116"
}
```

### Response Format

There is **no inbound JSON acknowledgment** for the `stop` event. The WebSocket close itself is your confirmation.

<Warning>
  **No inbound `stop` event exists.** Vobiz does **not** send `{ "event": "stop" }` when the call ends - the WebSocket simply closes. Do not wait for an inbound JSON reply after sending the `stop` command. Treat the WebSocket `close` event as your end-of-stream signal.
</Warning>

**What happens after you send `stop`:**

| Step | What Vobiz does |
| - | - |
| 1 | Stream stops immediately; WebSocket closes |
| 2 | Next XML element executes - or the call hangs up automatically if there is no next element |
| 3 | `Event=StopStream` POSTed to `statusCallbackUrl` |
| 4 | `Event=Hangup` POSTed to `hangup_url` (only if the call ended - i.e. no further XML elements after `<Stream>`) |

## Examples

### Complete Event Sequence

```javascript Send stop to end the stream theme={null}
// After agent finishes its final response...

// 1. Send the last audio chunk
ws.send(JSON.stringify({
  event: 'playAudio',
  streamId: '20170ada-f610-433b-8758-c02a2aab3662',
  media: {
    contentType: 'audio/x-l16',
    sampleRate: 8000,
    payload: farewellAudioBase64
  }
}));

// 2. Send checkpoint to wait for playback completion
ws.send(JSON.stringify({
  event: 'checkpoint',
  streamId: '20170ada-f610-433b-8758-c02a2aab3662',
  name: 'farewell'
}));

// 3. Wait for playedStream acknowledgment, then stop
ws.on('message', (message) => {
  const data = JSON.parse(message);

  if (data.event === 'playedStream' && data.name === 'farewell') {
    // Farewell audio finished playing - now terminate the stream
    ws.send(JSON.stringify({
      event: 'stop',
      streamId: '20170ada-f610-433b-8758-c02a2aab3662'
    }));
  }
});

// 4. Handle WebSocket close (the stop confirmation)
ws.on('close', () => {
  console.log('Stream terminated successfully');
});
```

### Node.js Implementation

```javascript Agent teardown with stop event theme={null}
const WebSocket = require('ws');

let currentStreamId = null;

wss.on('connection', (ws) => {
  ws.on('message', (message) => {
    const data = JSON.parse(message);

    if (data.event === 'start') {
      currentStreamId = data.start.streamId;
      console.log('Stream started:', currentStreamId);

      // Begin conversation flow
      startConversation(ws);
    }

    if (data.event === 'playedStream') {
      console.log('Checkpoint reached:', data.name);

      if (data.name === 'farewell') {
        // Final audio played - terminate the stream
        terminateStream(ws);
      }
    }

    if (data.event === 'media') {
      // Process incoming audio
      const audioBuffer = Buffer.from(data.media.payload, 'base64');
      // ... transcribe, run through LLM, generate TTS response
    }
  });

  ws.on('close', () => {
    // WebSocket close confirms the stop was received
    console.log('Stream ended:', currentStreamId);
    cleanupSession(currentStreamId);
  });
});

function terminateStream(ws) {
  console.log('Sending stop event...');

  ws.send(JSON.stringify({
    event: 'stop',
    streamId: currentStreamId
  }));
}

function cleanupSession(streamId) {
  // Flush recordings, close DB connections, etc.
  console.log('Cleaning up session for stream:', streamId);
}
```

### Python AsyncIO Example

```python Stop event in Python asyncio theme={null}
import asyncio
import websockets
import json

stream_id = None

async def terminate_stream(websocket):
    """Send stop event to end the stream"""
    stop_msg = {
        'event': 'stop',
        'streamId': stream_id
    }
    await websocket.send(json.dumps(stop_msg))
    print("Stop event sent - waiting for WebSocket close")

async def handle_stream(websocket, path):
    global stream_id

    try:
        async for message in websocket:
            data = json.loads(message)

            if data['event'] == 'start':
                stream_id = data['start']['streamId']
                print(f"Stream started: {stream_id}")

                # Begin conversation
                await start_conversation(websocket)

            elif data['event'] == 'playedStream':
                print(f"Checkpoint reached: {data['name']}")

                if data['name'] == 'farewell':
                    # Final audio confirmed - end the stream
                    await terminate_stream(websocket)

            elif data['event'] == 'media':
                # Process inbound audio
                audio_bytes = __import__('base64').b64decode(data['media']['payload'])
                # ... STT / LLM / TTS pipeline

    except websockets.exceptions.ConnectionClosed:
        # WebSocket close is the stop confirmation
        print(f"Stream ended: {stream_id}")
        await cleanup_session(stream_id)

async def cleanup_session(sid):
    """Flush recordings, close connections, etc."""
    print(f"Cleaning up session: {sid}")

async def main():
    async with websockets.serve(handle_stream, "0.0.0.0", 8080):
        print("WebSocket server running on port 8080")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
```

## Best Practices

### Play Farewell Audio Before Stopping

Send any farewell audio and a `checkpoint` before the `stop` event. Wait for the `playedStream` acknowledgment so the caller hears the full goodbye message before the stream terminates.

### Handle the WebSocket Close Event

Wire up a `ws.on('close')` handler to flush in-memory buffers (recordings, transcripts) and clean up per-call state. Do not rely on a JSON reply - the close event is your only confirmation.

### Avoid Sending Events After Stop

Do not send `playAudio`, `clearAudio`, or `checkpoint` events after the `stop` command. The WebSocket closes immediately and any queued sends will be dropped.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.