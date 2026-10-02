> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz Webhooks (Callbacks) – Real-Time Event Notifications

> Vobiz webhooks (callbacks) are HTTP POST requests sent to your server when call, recording, conference, and message events occur - enabling real-time event handling.

<Info>
  **What are callbacks?** When events occur in your Vobiz account (a call completing, a recording finishing, a conference ending), Vobiz automatically sends HTTP POST requests to your server with details about the event. This lets your application react to events in real time without polling.
</Info>

## How Vobiz Webhooks Work

<Steps>
  <Step title="Configure Callback URL">
    You provide a callback URL when creating resources (applications, trunks, calls, etc.).
  </Step>

  <Step title="Event Occurs">
    An event happens in your account (call ends, recording completes, etc.).
  </Step>

  <Step title="Vobiz Sends HTTP POST">
    Vobiz sends an HTTP POST request to your callback URL with event details.
  </Step>

  <Step title="Your Server Responds">
    Your server processes the callback and responds with HTTP 200 OK.
  </Step>
</Steps>

### Example Callback Request

When a call ends, Vobiz sends a POST request to your callback URL:

```http POST Request to Your Callback URL theme={null}
POST /webhooks/call-status HTTP/1.1
Host: your-domain.com
Content-Type: application/x-www-form-urlencoded
User-Agent: Vobiz-Webhook/1.0

{
  "Event": "Hangup",
  "CallUUID": "550e8400-e29b-41d4-a716-446655440000",
  "From": "+14155551234",
  "To": "+14155555678",
  "Status": "completed",
  "Duration": 125,
  "StartTime": "2025-10-30T10:30:00Z",
  "EndTime": "2025-10-30T10:32:05Z",
  "Direction": "outbound",
  "auth_id": "{auth_id}"
}
```

### Example Server Response

Your server should respond with HTTP 200 to acknowledge receipt:

```http Your Server Response theme={null}
HTTP/1.1 200 OK
Content-Type: application/json

{
  "status": "received"
}
```

## Callback Events

| Event Type | Description | When It's Sent |
| - | - | - |
| `CallInitiated` | Outbound call created | On call creation |
| `Ring` | Call is ringing | When an outbound call starts ringing |
| `StartApp` | Call was answered | Delivered to `answer_url` when the called party answers |
| `Hangup` | Call has ended | When the call completes. The authoritative end-of-call signal |
| `Record` / `RecordStop` | Recording started / finished | `RecordStop` carries the recording identity and URL |
| `DialAnswer` · `DialConnected` · `DialHangup` · `DialAction` · `DialDigitsMatch` | `<Dial>` lifecycle | During and after a Dial |
| `ConferenceEnter` · `ConferenceExit` | Participant joined / left a conference | Carries `ConferenceMemberID` |
| `ConferenceRemoteSounds` · `ConferenceDigitsMatch` | Conference wait-audio and digit matches | See [Conference Callbacks](/docs/xml/conference/conference-callbacks) |
| `StartStream` · `PlayedStream` · `ClearedAudio` · `DegradedStream` · `DroppedStream` · `StopStream` | Audio stream lifecycle | See [`<Stream>`](/docs/xml/stream#status-callback-events) |
| `MachineDetection` | Answering machine detected | When AMD resolves |
| `Redirect` | Call was redirected | On `<Redirect>` |

<Warning>
  **`Event=StartApp` is what arrives at your `answer_url`**, not `Answer`. This
  surprises most integrators on their first call.

  There is also **no conference start or end event of any kind**. Room lifecycle
  must be derived from the first `ConferenceEnter` and the last `ConferenceExit`.
</Warning>

## Callback Parameters

### Standard Parameters

All callback requests include these standard parameters:

| Parameter | Type | Description |
| - | - | - |
| `Event` | string | Event type identifier (e.g., Ring, StartApp, Hangup) |
| `timestamp` | string | ISO 8601 timestamp of when event occurred |
| `auth_id` | string | Your Vobiz account identifier |
| `CallUUID` | string | Unique identifier for the call |

## Security Considerations

### Always Use HTTPS

<Warning>
  **Important:** Only use HTTPS URLs for callback endpoints. HTTP URLs are not supported for security reasons.
</Warning>

### Verify Callback Source

Every callback Vobiz sends includes HMAC-SHA256 signatures in the request headers (`X-Vobiz-Signature-V2`, `X-Vobiz-Signature-V3`, and their multi-account variants). Validate these signatures to confirm the request genuinely came from Vobiz and was not tampered with.

<Card title="Validating Callbacks" icon="shield-check" href="/docs/concepts/validating-callbacks">
  Full validation guide with code examples in Python, Node.js, Go, and Ruby.
</Card>

## Best Practices

* **Respond quickly** - Return HTTP 200 within 3 seconds. If processing takes longer, queue the callback for async processing and respond immediately.
* **Handle retries** - Vobiz will retry failed callbacks (non-200 responses) up to 3 times with exponential backoff. Make your callback handlers idempotent to handle duplicate deliveries.
* **Log everything** - Log all incoming callbacks with full payload for debugging. Include timestamps, event types, and processing results.
* **Monitor callback health** - Track callback success/failure rates, response times, and set up alerts for failures. Monitor for missing callbacks as a sign of delivery issues.
* **Use separate endpoints** - Consider using different callback URLs for different event types or resources to simplify routing and processing logic.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.