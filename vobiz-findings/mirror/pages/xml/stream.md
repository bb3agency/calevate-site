> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Stream XML Element – Real-Time WebSocket Audio | Vobiz

> Fork live call audio to a WebSocket server in real time with Vobiz Stream. Supports bidirectional streaming, L16/μ-law codecs, and AI voice agent pipelines.

<Info>
  **Key Capabilities**

  * **Bidirectional streaming:** Send and receive audio in real-time
  * **Multiple audio tracks:** Stream inbound, outbound, or both tracks
  * **Flexible codecs:** Support for multiple audio formats and sample rates
  * **Event streaming:** Send playback, checkpoint, and control events via WebSocket
</Info>

## Audio directions

A bidirectional stream uses one WebSocket connection, but it describes incoming and outgoing audio separately:

```text theme={null}
Inbound stream audio
Caller -> Vobiz -> your WebSocket application
Configured by <Stream contentType> and reported by start.mediaFormat

Outbound playback audio
Your WebSocket application -> Vobiz -> caller
Configured by playAudio.media.contentType and playAudio.media.sampleRate
```

The two directions can use different supported formats. Decode inbound `media` events using `start.mediaFormat`. Encode each outbound `playAudio` payload using the format declared in that event.

<Warning>
  To play a 24 kHz TTS response, send genuine L16/24 kHz audio with `playAudio.media.sampleRate: 24000`. Do not set `<Stream contentType="audio/x-l16;rate=24000">`; `contentType` configures inbound audio sent to your application.
</Warning>

## Attributes

| Attribute | Description |
| - | - |
| `bidirectional` <br /> *boolean* | Specifies whether the audio being streamed over the WebSocket is bidirectional (read/write) or one-way (read-only). <br /><br />If `true`, Vobiz accepts outbound `playAudio` events with: <br />- **contentType:** `audio/x-l16` or `audio/x-mulaw` <br />- **sampleRate:** `8000`, `16000`, or `24000` for L16; `8000` for μ-law <br />- **payload:** Base64-encoded raw mono audio |
| `audioTrack` <br /> *string* | The audio track (inbound/outbound) that Vobiz will fork and stream to the WebSocket. <br />**Allowed values:** `inbound`, `outbound`, `both` <br />**Default:** `inbound` <br /><br />**Note:** When bidirectional is true, audioTrack should not be `outbound` or `both`. |
| `streamTimeout` <br /> *integer* | Maximum duration (in seconds) for audio streaming. Streaming stops after this duration. Must be a positive integer. <br />**Default:** `86400` (24 hours) |
| `statusCallbackUrl` <br /> *string* | URL notified when: <br />- Audio stream is connected <br />- Audio stream is stopped intentionally or due to timeout <br />- Audio stream failed or disconnected |
| `statusCallbackMethod` <br /> *string* | HTTP method used to invoke statusCallbackUrl. <br />**Allowed values:** `GET`, `POST` <br />**Default:** `POST` |
| `contentType` <br /> *string* | Preferred format for inbound audio that Vobiz sends to your WebSocket. Vobiz reports the selected format in `start.mediaFormat`. <br />**Allowed values:** <br />- `audio/x-l16;rate=8000` <br />- `audio/x-l16;rate=16000` <br />- `audio/x-mulaw;rate=8000` <br /><br />**Default:** `audio/x-l16;rate=8000` |
| `extraHeaders` <br /> *string* | Key-value pairs sent to the WebSocket service with the audio stream. <br />**Example:** `test1=12,test2=123` <br />**Max length:** 512 bytes <br />**Allowed characters:** \[A-Z], \[a-z], \[0-9] |
| `maxRetries` <br /> *integer* | Maximum number of reconnect attempts if the WebSocket connection fails to establish or drops mid-stream. <br />**Default:** `0` (retries disabled) <br />**Max:** `10` <br /><br />Values below `0` are treated as `0`. Values above `10` are capped at `10`. Non-integer values fall back to `0`. |
| `keepCallAlive` <br /> *boolean* | If `true`, the Stream element executes exclusively and subsequent XML elements run only after the stream disconnects. <br />**Allowed values:** `true`, `false` <br />**Default:** `false` |

## Parameters sent to statusCallbackUrl

This information is sent to the `statusCallbackUrl` when an event is triggered.

| Parameter | Description |
| - | - |
| `bidirectional` <br /> *boolean* | Indicates whether the audio stream was bidirectional (read/write) or one-way (read-only). |
| `audioTrack` <br /> *string* | The audio track that Vobiz forked and streamed. Values: `inbound`, `outbound`, `both` |
| `streamTimeout` <br /> *integer* | Maximum duration (in seconds) that audio was streamed. Default: 86400 (24 hours) |
| `statusCallbackUrl` <br /> *string* | URL that received the notification of stream events. |
| `statusCallbackMethod` <br /> *string* | HTTP method used (GET or POST). Default: POST |
| `contentType` <br /> *string* | Inbound audio codec and sampling rate used for the stream. |
| `extraHeaders` <br /> *string* | Key-value pairs that were sent along with the audio stream. |
| `maxRetries` <br /> *integer* | Maximum reconnect attempts configured for this stream. Default: 0 (disabled). |
| `keepCallAlive` <br /> *boolean* | Whether the stream executed exclusively before continuing with subsequent XML elements. |

## Status callback events

When you configure a `statusCallbackUrl`, Vobiz sends HTTP POST/GET requests to that URL when specific stream lifecycle events occur. These are separate from WebSocket events and are useful for logging, monitoring, and triggering business logic.

<Info>
  **HTTP Callbacks vs WebSocket Events**

  **HTTP status callbacks** (sent to `statusCallbackUrl`):

  * StartStream, PlayedStream, StopStream events
  * Sent via HTTP POST/GET to your web server
  * For logging, monitoring, and triggering workflows

  **WebSocket events and commands**:

  * Vobiz sends `start`, `media`, `playedStream`, and `clearedAudio`
  * Your application sends `playAudio`, `checkpoint`, `clearAudio`, and `stop`
  * Sent through the WebSocket connection in real time
  * For audio streaming and real-time interaction
</Info>

### StartStream - stream started

Fired when the WebSocket connection is successfully established and audio streaming begins.

```http Example StartStream Callback theme={null}
POST /stream-status HTTP/1.1
Host: yourapp.com
Content-Type: application/x-www-form-urlencoded

From=918071387423
To=919624705678
CallUUID=9a0e0208-d01a-4572-9a04-fe583a05ac53
Event=StartStream
StreamID=227d997a-0af4-447c-a3f3-b243e902e527
ServiceURL=wss://your-server.com/ws
ParentAuthID=MA_PU0XU668
status_callback_url=https://yourapp.com/stream-status
status_callback_method=POST
Timestamp=2025-11-06 09:58:40
```

### PlayedStream - checkpoint reached

Fired when audio queued before a checkpoint event has been successfully played to the caller. The `Name` parameter contains the checkpoint name you specified.

<Warning>
  This event is only sent if you send a `checkpoint` event via WebSocket and the audio plays successfully. If playback is interrupted, this event may not fire.
</Warning>

```http Example PlayedStream Callback theme={null}
POST /stream-status HTTP/1.1
Host: yourapp.com
Content-Type: application/x-www-form-urlencoded

From=918071387423
To=919624705678
CallUUID=9a0e0208-d01a-4572-9a04-fe583a05ac53
Event=PlayedStream
StreamID=227d997a-0af4-447c-a3f3-b243e902e527
Name=first
ParentAuthID=MA_PU0XU668
status_callback_url=https://yourapp.com/stream-status
status_callback_method=POST
Timestamp=2025-11-06 09:58:46
```

### StopStream - stream ended

Fired when the audio streaming session ends. This can happen due to:

* Stream timeout (streamTimeout reached)
* Call ended by either party
* WebSocket connection closed
* Network error or disconnection

```http Example StopStream Callback theme={null}
POST /stream-status HTTP/1.1
Host: yourapp.com
Content-Type: application/x-www-form-urlencoded

From=918071387423
To=919624705678
CallUUID=9a0e0208-d01a-4572-9a04-fe583a05ac53
Event=StopStream
StreamID=227d997a-0af4-447c-a3f3-b243e902e527
ParentAuthID=MA_PU0XU668
status_callback_url=https://yourapp.com/stream-status
status_callback_method=POST
Timestamp=2025-11-06 09:58:50
```

### Common parameters in all events

| Parameter | Description |
| - | - |
| `CallUUID` | Unique identifier for the call |
| `StreamID` | Unique identifier for this streaming session |
| `Event` | Event type. See the full set below |
| `From` | Caller's phone number |
| `To` | Called phone number |
| `Timestamp` | When the event occurred |
| `Name` | Checkpoint name (PlayedStream only) |
| `ServiceURL` | WebSocket URL used for streaming (StartStream only) |
| `Error` | Human-readable state. Present on **every** stream status callback; empty on healthy events |

### The full event set

The typical live sequence is `StartStream` → `PlayedStream` → `ClearedAudio` (on
barge-in) → `DroppedStream`. Two of these are not otherwise documented:

| `Event` | `Error` value |
| - | - |
| `StartStream` | *(empty)* |
| `PlayedStream` | *(empty)* - also carries `Name`, the checkpoint label |
| `ClearedAudio` | *(empty)* |
| `DegradedStream` | `connection degraded` |
| `DroppedStream` | `connection disconnected with the remote service` |
| `StopStream` | *(empty)* |

`DegradedStream` signals that the WebSocket media path is deteriorating **while the
stream is still up** - the right moment to degrade gracefully or re-attach, rather
than waiting for the drop.

<Warning>
  **`StopStream` fires only when your application initiates the stop.** It is not
  sent on caller hangup, on a mid-call kill, or on a transfer. The authoritative
  end-of-call signal across every termination path is the `Event=Hangup` POST to your
  `hangup_url`.
</Warning>

<Note>
  **Plan for callback volume.** `ClearedAudio` fires on every barge-in, so a busy
  conversational call produces far more status callbacks than events in the table
  suggest - a 125-second call was observed producing 15. Make the handler cheap and
  idempotent.
</Note>

### Example: handling status callbacks

```javascript Node.js Express Handler theme={null}
app.post('/stream-status', (req, res) => {
  const { Event, StreamID, CallUUID, Name, Timestamp } = req.body;

  switch(Event) {
    case 'StartStream':
      console.log(`Stream started: ${StreamID} for call ${CallUUID}`);
      // Log to database, initialize session, etc.
      break;

    case 'PlayedStream':
      console.log(`Checkpoint "${Name}" reached for stream ${StreamID}`);
      // Track checkpoint completion, trigger next action
      break;

    case 'StopStream':
      console.log(`Stream ended: ${StreamID} at ${Timestamp}`);
      // Clean up resources, finalize session, send notifications
      break;

    default:
      console.log(`Unknown event: ${Event}`);
  }

  // Always respond with 200 OK
  res.status(200).send('OK');
});
```

## Examples

### Basic audio stream

```xml Simple one-way audio stream theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream>wss://stream.vobiz.ai/stream</Stream>
</Response>
```

Streams inbound audio (default) to your WebSocket server at the specified URL.

### Bidirectional audio stream

```xml Two-way audio streaming with callbacks theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream
bidirectional="true"
keepCallAlive="true"
statusCallbackUrl="https://yourapp.vobiz.ai/stream-status"
contentType="audio/x-l16;rate=16000">
wss://stream.vobiz.ai/stream
    </Stream>
</Response>
```

Configures inbound L16 audio at 16 kHz, enables bidirectional playback, keeps the call alive during streaming, and sends status updates to your callback URL. Configure outbound playback independently in each [`playAudio`](/docs/xml/stream/play-audio) event.

### Stream both tracks with timeout

```xml Stream inbound and outbound audio with 1-hour timeout theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream
audioTrack="both"
streamTimeout="3600"
statusCallbackUrl="https://yourapp.vobiz.ai/stream-status"
statusCallbackMethod="POST"
extraHeaders="session=abc123,user=john">
wss://stream.vobiz.ai/stream
    </Stream>
    <Speak>Thank you for calling. We're processing your request.</Speak>
</Response>
```

Streams both inbound and outbound audio for up to 1 hour, includes custom headers, and continues to subsequent XML elements after streaming ends.

## Next steps

* [Audio formats: 8, 16, and 24 kHz](/docs/xml/stream/audio-formats) - Choose the correct format for inbound streaming and outbound playback.
* [Initiate a Stream](/docs/xml/stream/initiate) - Learn how to establish a WebSocket connection and start streaming audio from active calls.
* [Stream Events Overview](/docs/xml/stream/stream-events) - Understand how to send events like playAudio, clearAudio, and checkpoint via WebSocket.
* [Checkpoint Event](/docs/xml/stream/checkpoint-event) - Send checkpoint events to confirm audio playback completion and manage event queues.
* [Play Audio Event](/docs/xml/stream/play-audio) - Transmit audio through WebSocket for bidirectional audio streaming use cases.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.