> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Checkpoint Event

> Send a checkpoint event via Vobiz Stream WebSocket when queued audio events are ready - used to synchronize playback with downstream processing logic.

<Info>
  **Purpose**

  The checkpoint event acts as a marker in your audio event queue. When Vobiz finishes playing all audio events that were sent before the checkpoint, it sends a `playedStream` acknowledgment back to your application. This allows you to:

  * Track playback completion of specific audio segments
  * Synchronize your application logic with audio playback
  * Implement multi-turn conversations with timing control
</Info>

## Attributes

| Attribute | Description |
| - | - |
| `event` <br /> *string* <br /> **Required** | Indicates the event type. Use `checkpoint` as the value expected. |
| `name` <br /> *string* <br /> **Required** | Name of the checkpoint that you use to recognize upon receiving the acknowledgment. <br />**Example:** `"customer greeting audio"`, `"main menu prompt"` |
| `streamId` <br /> *string* <br /> **Required** | A unique identifier generated for each audio stream. <br />This value is provided by Vobiz in the initial "start" event when the WebSocket connection is established. |

## Request & Response

### Request Format

Send this JSON message through the WebSocket to Vobiz:

```json Checkpoint event request theme={null}
{
  "event": "checkpoint",
  "streamId": "20170ada-f610-433b-8758-c02a2aab3662",
  "name": "customer greeting audio"
}
```

### Response Format

When the checkpoint is reached (all previous audio has been played), Vobiz responds with:

```json playedStream acknowledgment theme={null}
{
  "event": "playedStream",
  "name": "customer greeting audio"
}
```

The WebSocket `playedStream` event carries only `event` and `name` - the `name` echoes the value you set on the matching `checkpoint`. Match acknowledgments by `name`, not `streamId`.

<Note>
  **WebSocket `playedStream` vs HTTP `PlayedStream`.** Two different channels share a similar name:

  * The **WebSocket** `playedStream` event (above) is `event` + `name` only.
  * The **HTTP** `Event=PlayedStream` status callback (sent to `statusCallbackUrl`) is form-encoded and *does* include `StreamID`, `CallUUID`, `Name`, etc. See [Status callback events](/docs/xml/stream#status-callback-events).

  Use the WebSocket event for tight in-conversation timing; use the HTTP callback for logging and out-of-band workflows.
</Note>

<Warning>
  **`playedStream` is conditional.**

  It is only emitted if the audio queued before the matching `checkpoint` played to completion. If playback is interrupted (e.g. by a `clearAudio` event, a barge-in, or call disconnection), you will **not** receive this acknowledgment. Never block conversation logic on it - always pair a `checkpoint` with a timeout fallback.
</Warning>

## Examples

### Complete Event Sequence

```javascript Play audio + checkpoint + acknowledgment theme={null}
// 1. Your app sends playAudio event (e.g., greeting message)
ws.send(JSON.stringify({
  event: 'playAudio',
  streamId: '20170ada-f610-433b-8758-c02a2aab3662',
  media: {
    contentType: 'audio/x-l16',
    sampleRate: 8000,
    payload: greetingAudioBase64
  }
}));

// 2. Immediately send checkpoint to mark this audio segment
ws.send(JSON.stringify({
  event: 'checkpoint',
  streamId: '20170ada-f610-433b-8758-c02a2aab3662',
  name: 'customer greeting audio'
}));

// 3. Continue with your logic...
// Later, when Vobiz finishes playing the audio:

// 4. Vobiz sends playedStream acknowledgment (event + name only)
{
  event: 'playedStream',
  name: 'customer greeting audio'
}

// 5. Your app receives the acknowledgment and proceeds
ws.on('message', (message) => {
  const data = JSON.parse(message);

  if (data.event === 'playedStream' && data.name === 'customer greeting audio') {
    console.log('Greeting completed successfully!');
    // Now you can proceed with next step (e.g., collect user input)
  }
});
```

### Node.js Implementation

```javascript Using checkpoints to manage conversation flow theme={null}
const WebSocket = require('ws');

let currentStreamId = null;
let conversationState = 'greeting';

wss.on('connection', (ws) => {
  ws.on('message', (message) => {
    const data = JSON.parse(message);

    // Handle stream start
    if (data.event === 'start') {
      currentStreamId = data.start.streamId;   // IDs are nested under start
      console.log('Stream started:', currentStreamId);

      // Play greeting audio
      playGreeting(ws);
    }

    // Handle checkpoint acknowledgments
    if (data.event === 'playedStream') {
      console.log(`Checkpoint '${data.name}' reached`);

      // Transition based on completed checkpoint
      if (data.name === 'greeting') {
conversationState = 'main-menu';
playMainMenu(ws);
      } else if (data.name === 'main-menu') {
conversationState = 'collecting-input';
        // Start listening for DTMF or speech input
      } else if (data.name === 'option-1-prompt') {
conversationState = 'processing-option-1';
        // Handle option 1 logic
      }
    }

    // Handle incoming audio (for speech recognition, etc.)
    if (data.event === 'media') {
      const audioBuffer = Buffer.from(data.media.payload, 'base64');
      // Process audio based on current conversation state
    }
  });
});

function playGreeting(ws) {
  // Send greeting audio
  ws.send(JSON.stringify({
    event: 'playAudio',
    streamId: currentStreamId,
    media: {
      contentType: 'audio/x-l16',
      sampleRate: 8000,
      payload: greetingAudioBase64
    }
  }));

  // Mark checkpoint
  ws.send(JSON.stringify({
    event: 'checkpoint',
    streamId: currentStreamId,
    name: 'greeting'
  }));
}

function playMainMenu(ws) {
  // Send main menu prompt
  ws.send(JSON.stringify({
    event: 'playAudio',
    streamId: currentStreamId,
    media: {
      contentType: 'audio/x-l16',
      sampleRate: 8000,
      payload: mainMenuAudioBase64
    }
  }));

  // Mark checkpoint
  ws.send(JSON.stringify({
    event: 'checkpoint',
    streamId: currentStreamId,
    name: 'main-menu'
  }));
}
```

This example demonstrates using checkpoints to manage a multi-turn conversation flow, transitioning between states only when the current audio has finished playing.

### Python AsyncIO Example

```python Checkpoint handling in Python theme={null}
import asyncio
import websockets
import json
import base64

stream_id = None
conversation_state = 'greeting'

async def handle_checkpoint(ws, checkpoint_name):
    """Send checkpoint and wait for acknowledgment"""
    checkpoint_msg = {
        'event': 'checkpoint',
        'streamId': stream_id,
        'name': checkpoint_name
    }
    await ws.send(json.dumps(checkpoint_msg))
    print(f"Checkpoint '{checkpoint_name}' sent")

async def play_audio_with_checkpoint(ws, audio_base64, checkpoint_name):
    """Play audio and mark with checkpoint"""
    # Send audio
    play_msg = {
        'event': 'playAudio',
        'streamId': stream_id,
        'media': {
            'contentType': 'audio/x-l16',
            'sampleRate': 8000,
            'payload': audio_base64
        }
    }
    await ws.send(json.dumps(play_msg))

    # Send checkpoint
    await handle_checkpoint(ws, checkpoint_name)

async def handle_stream(websocket, path):
    global stream_id, conversation_state

    async for message in websocket:
data = json.loads(message)

if data['event'] == 'start':
stream_id = data['start']['streamId']  # IDs are nested under start
print(f"Stream started: {stream_id}")

            # Play greeting with checkpoint
await play_audio_with_checkpoint(
                websocket,
                greeting_audio_base64,
                'greeting'
            )

elif data['event'] == 'playedStream':
checkpoint = data['name']
print(f"Checkpoint reached: {checkpoint}")

            # State transitions based on checkpoint
if checkpoint == 'greeting':
                conversation_state = 'main-menu'
                await play_audio_with_checkpoint(
websocket,
main_menu_audio_base64,
'main-menu'
                )

elif checkpoint == 'main-menu':
                conversation_state = 'waiting-input'
                print("Ready for user input")

elif data['event'] == 'media':
            # Process incoming audio
audio_bytes = base64.b64decode(data['media']['payload'])
            # ... handle audio processing

async def main():
    async with websockets.serve(handle_stream, "0.0.0.0", 8080):
print("WebSocket server running on port 8080")
await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
```

## Ordering and edge cases

* **Send the `checkpoint` immediately after the last `playAudio` chunk of an utterance.** The checkpoint marks a position in the playback queue, so it acks only after every chunk queued *before* it has been delivered to the caller.
* **Acks are not guaranteed and not ordered against `media`.** A `playedStream` may arrive interleaved with inbound `media` frames. Match on `name`; don't assume it is the next message after your `checkpoint`.
* **A `clearAudio` voids pending checkpoints.** Any checkpoint whose audio was still queued when you sent `clearAudio` will never ack. Reset per-utterance state when you barge in.
* **Use unique names per utterance.** Re-using a name across turns makes acks ambiguous. A monotonic counter (`response-1`, `response-2`, …) is a good pattern.
* **Always set a timeout fallback.** Because the ack is conditional, drive a watchdog timer alongside each checkpoint so a dropped ack cannot stall the conversation.

```javascript Checkpoint with a timeout fallback theme={null}
function speakWithCheckpoint(ws, audioBase64, name, onDone) {
  ws.send(JSON.stringify({ event: 'playAudio', streamId: currentStreamId, media: { contentType: 'audio/x-l16', sampleRate: 8000, payload: audioBase64 } }));
  ws.send(JSON.stringify({ event: 'checkpoint', streamId: currentStreamId, name }));

  // Fallback: proceed even if playedStream never arrives (e.g. barge-in).
  const timer = setTimeout(() => onDone(name, /* timedOut */ true), 15000);
  pendingCheckpoints.set(name, () => { clearTimeout(timer); onDone(name, false); });
}

// On playedStream: pendingCheckpoints.get(data.name)?.();
```

## Best Practices

### Use Descriptive Checkpoint Names

Give your checkpoints meaningful names that clearly indicate what audio segment they represent. This makes debugging and maintaining your code much easier.

### Don't Rely on Checkpoints for Critical Logic

Remember that playedStream acknowledgments may not arrive if the call is disconnected or audio is interrupted. Always have fallback logic for timeout scenarios.

### Send Checkpoints Immediately After Audio

For the most accurate timing, send your checkpoint event immediately after the corresponding playAudio event. This ensures the checkpoint marks exactly when that audio segment finishes.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.