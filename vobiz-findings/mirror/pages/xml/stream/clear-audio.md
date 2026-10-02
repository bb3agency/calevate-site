> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Clear Stream

> The Vobiz clearAudio Stream event interrupts audio previously sent via playAudio - useful for instantly stopping TTS when the caller starts speaking.

<Info>
  **When to Use clearAudio**

  You can send a clearAudio event to interrupt the audio that has been sent to Vobiz. This will clear all the buffered audio. Common scenarios include:

  * **Barge-in:** User starts speaking while AI prompt is playing
  * **Context switch:** User changes topic mid-conversation
  * **Error recovery:** Cancel current playback and play error message
  * **Priority messages:** Interrupt to play urgent information
</Info>

## Attributes

| Attribute | Description |
| - | - |
| `event` <br /> *string* <br /> **Required** | Indicates the event type. Use `clearAudio` to clear all the buffered audio. |
| `streamId` <br /> *string* <br /> **Required** | A unique identifier generated for each audio stream. <br />This value is provided by Vobiz in the initial "start" event when the WebSocket connection is established. |

## Request & Response

### Request Format

Send this JSON message through the WebSocket to Vobiz to clear buffered audio:

```json clearAudio event request theme={null}
{
  "event": "clearAudio",
  "streamId": "b77e037d-4119-44b5-902d-25826b654539"
}
```

### Response Format

Vobiz acknowledges the clearAudio event with a `clearedAudio` response:

```json clearedAudio acknowledgment theme={null}
{
  "sequenceNumber": 0,
  "event": "clearedAudio",
  "streamId": "20170ada-f610-433b-8758-c02a2aab3662"
}
```

The `sequenceNumber` field helps track the order of events in the stream.

<Warning>
  **Important:**

  After sending clearAudio, all previously sent playAudio events that haven't been played yet are discarded. Any pending checkpoint events will not receive acknowledgments. You can immediately send new playAudio events after clearAudio to replace the interrupted audio.
</Warning>

## Common use cases

### 1. Voice Assistant Barge-In

When building conversational AI, users often start speaking before the AI finishes its response. Detect user speech and send clearAudio to stop the AI from continuing its playback.

```javascript Detect speech and interrupt theme={null}
// Detect user speech in incoming audio
if (data.event === 'media') {
  const audioLevel = detectAudioLevel(data.media.payload);

  // If user starts speaking while AI is talking
  if (audioLevel > SPEECH_THRESHOLD && isAIPlaying) {
    console.log('User barge-in detected');

    // Clear the buffered AI audio
    ws.send(JSON.stringify({
      event: 'clearAudio',
      streamId: currentStreamId
    }));

    isAIPlaying = false;

    // Start listening for user's full input
    startSpeechRecognition();
  }
}
```

### 2. Dynamic Content Updates

If you're playing a long audio message and receive updated information (e.g., real-time data), you can interrupt the current playback and play the updated content.

```javascript Update with new information theme={null}
// Receive real-time update (e.g., stock price change)
async function handleDataUpdate(newData) {
  // Clear currently playing audio
  await sendClearAudio(ws, streamId);

  // Wait for acknowledgment
  await waitForClearedAudio();

  // Generate and play updated audio with new information
  const updatedAudio = await generateSpeech(
    `Update: The price is now ${newData.price}`
  );

  await sendPlayAudio(ws, updatedAudio);
}
```

### 3. Error Handling & Recovery

When an error occurs during a transaction or API call, interrupt the current flow and play an appropriate error message.

```javascript Handle errors gracefully theme={null}
try {
  // Attempting some operation
  await processPayment(userId, amount);

  // Play success audio
  await sendPlayAudio(ws, successAudioBase64);

} catch (error) {
  console.error('Payment failed:', error);

  // Clear any pending audio
  await sendClearAudio(ws, streamId);

  // Play error message
  const errorAudio = await generateSpeech(
    'Sorry, there was an error processing your payment. Please try again.'
  );

  await sendPlayAudio(ws, errorAudio);
}
```

## Implementation Examples

### Node.js Example

```javascript Complete clearAudio implementation theme={null}
const WebSocket = require('ws');

let currentStreamId = null;
let isPlaying = false;

wss.on('connection', (ws) => {
  ws.on('message', (message) => {
    const data = JSON.parse(message);

    if (data.event === 'start') {
      currentStreamId = data.start.streamId;
      console.log('Stream started:', currentStreamId);

      // Start playing introduction
      playIntroduction(ws);
    }

    if (data.event === 'playedStream') {
      isPlaying = false;
      console.log('Audio completed:', data.name);
    }

    if (data.event === 'clearedAudio') {
      console.log('Audio cleared successfully');
      // Now safe to send new playAudio events
    }

    if (data.event === 'media') {
      // Detect if user is speaking
      const audioBuffer = Buffer.from(data.media.payload, 'base64');
      const speechDetected = detectSpeech(audioBuffer);

      if (speechDetected && isPlaying) {
        // User is interrupting - clear current audio
clearAudio(ws);
      }
    }
  });
});

function playIntroduction(ws) {
  isPlaying = true;

  ws.send(JSON.stringify({
    event: 'playAudio',
    streamId: currentStreamId,
    media: {
      contentType: 'audio/x-l16',
      sampleRate: 8000,
      payload: introAudioBase64
    }
  }));

  ws.send(JSON.stringify({
    event: 'checkpoint',
    streamId: currentStreamId,
    name: 'introduction'
  }));
}

function clearAudio(ws) {
  console.log('Clearing buffered audio...');

  ws.send(JSON.stringify({
    event: 'clearAudio',
    streamId: currentStreamId
  }));

  isPlaying = false;
}

function detectSpeech(audioBuffer) {
  // Implement your speech detection logic
  // Return true if speech is detected above threshold
  return audioBuffer.length > 0 && calculateRMS(audioBuffer) > 0.02;
}

function calculateRMS(buffer) {
  let sum = 0;
  for (let i = 0; i < buffer.length; i++) {
    sum += buffer[i] * buffer[i];
  }
  return Math.sqrt(sum / buffer.length);
}
```

### Python Example

```python clearAudio with asyncio theme={null}
import asyncio
import websockets
import json
import base64

stream_id = None
is_playing = False

async def clear_audio(websocket):
    """Clear buffered audio"""
    global is_playing

    clear_msg = {
        'event': 'clearAudio',
        'streamId': stream_id
    }
    await websocket.send(json.dumps(clear_msg))
    is_playing = False
    print("Sent clearAudio event")

async def play_audio(websocket, audio_base64, checkpoint_name=None):
    """Play audio with optional checkpoint"""
    global is_playing

    # Send playAudio
    play_msg = {
        'event': 'playAudio',
        'streamId': stream_id,
        'media': {
            'contentType': 'audio/x-l16',
            'sampleRate': 8000,
            'payload': audio_base64
        }
    }
    await websocket.send(json.dumps(play_msg))
    is_playing = True

    # Send checkpoint if provided
    if checkpoint_name:
checkpoint_msg = {
            'event': 'checkpoint',
            'streamId': stream_id,
            'name': checkpoint_name
        }
await websocket.send(json.dumps(checkpoint_msg))

async def handle_stream(websocket, path):
    global stream_id, is_playing

    async for message in websocket:
data = json.loads(message)

if data['event'] == 'start':
stream_id = data['start']['streamId']
print(f"Stream started: {stream_id}")

            # Play welcome message
await play_audio(websocket, welcome_audio_base64, 'welcome')

elif data['event'] == 'playedStream':
is_playing = False
print(f"Checkpoint reached: {data['name']}")

elif data['event'] == 'clearedAudio':
print("Audio cleared - ready for new playback")

elif data['event'] == 'media':
            # Detect user speech
audio_bytes = base64.b64decode(data['media']['payload'])
speech_detected = detect_speech(audio_bytes)

if speech_detected and is_playing:
                print("User interruption detected")
                await clear_audio(websocket)

def detect_speech(audio_bytes):
    """Detect if audio contains speech"""
    # Implement your speech detection logic
    # Simple RMS-based detection as example
    if len(audio_bytes) == 0:
return False

    rms = sum(b * b for b in audio_bytes) / len(audio_bytes)
    return rms > 0.02  # Threshold

async def main():
    async with websockets.serve(handle_stream, "0.0.0.0", 8080):
print("WebSocket server running on port 8080")
await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
```

## Ordering and edge cases

* **`clearAudio` only flushes audio that hasn't reached the caller yet.** Anything already played out cannot be recalled. Keeping `playAudio` chunks small (\~20 ms) maximises how much a barge-in can cancel.
* **Pending checkpoints are voided.** Every `checkpoint` whose audio was still queued at the moment of the flush will *not* produce a `playedStream`. Reset your per-utterance state (timers, `botSpeaking` flags) when you send `clearAudio`, and don't wait on those acks.
* **Gate new playback on `clearedAudio`.** If you `playAudio` immediately after `clearAudio` without waiting for the `clearedAudio` ack, the new audio can race the flush and be partially dropped. Wait for `clearedAudio`, then enqueue the replacement.
* **Debounce barge-in detection.** A single noisy `media` frame can trip a naive energy threshold. Require a short run of speech-level frames (or use a proper VAD) before firing `clearAudio`, or you will cut off the bot on background noise.
* **`clearedAudio` carries `sequenceNumber` and `streamId`.** Use `streamId` to confirm it matches the active stream; `sequenceNumber` reflects ordering within the stream.

```javascript Barge-in that gates replacement audio on clearedAudio theme={null}
let awaitingClear = false;
let queuedResponse = null;

function bargeIn(ws, newAudioBase64) {
  awaitingClear = true;
  queuedResponse = newAudioBase64;
  ws.send(JSON.stringify({ event: 'clearAudio', streamId: currentStreamId }));
}

// In your message handler:
if (data.event === 'clearedAudio' && awaitingClear) {
  awaitingClear = false;
  if (queuedResponse) {
    ws.send(JSON.stringify({
      event: 'playAudio',
      streamId: currentStreamId,
      media: { contentType: 'audio/x-l16', sampleRate: 8000, payload: queuedResponse },
    }));
    queuedResponse = null;
  }
}
```

## Best Practices

### Wait for clearedAudio Acknowledgment

Before sending new playAudio events after clearAudio, it's best practice to wait for the `clearedAudio` acknowledgment to ensure the buffer is fully cleared.

### Track Playback State

Maintain a state variable to track whether audio is currently playing. This helps you decide when to send clearAudio events and avoid unnecessary interruptions.

### Use Appropriate Detection Thresholds

When implementing barge-in, tune your speech detection threshold carefully to avoid false positives from background noise while still being responsive to actual user speech.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.