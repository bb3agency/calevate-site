> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# How Vobiz Voice XML Works – Event-Driven Call Flow Architecture

> Discover the event-driven cycle powering Vobiz Voice XML. Calls trigger webhooks, your server returns XML instructions, and Vobiz executes them in real time.

<Info>
  **Event-Driven Architecture**

  Vobiz XML uses an event-driven model. When call events occur (incoming call, DTMF pressed, recording complete), Vobiz sends HTTP requests to your configured URLs and executes the XML you return. This lets you build dynamic, data-driven call flows.
</Info>

## Request-response flow

### The basic cycle

<Steps>
  <Step title="Call Event Triggers">
    An incoming call arrives, an outbound call connects, a user presses a DTMF key, a recording finishes, or any other call event occurs.
  </Step>

  <Step title="Vobiz Sends Webhook">
    Vobiz makes an HTTP POST (or GET) request to your Answer URL or Action URL with call details: CallUUID, From, To, Direction, DTMF digits, RecordingURL, etc.
  </Step>

  <Step title="Your Server Generates XML">
    Your application processes the webhook data (look up customer in database, check business rules, etc.) and returns XML instructions in the HTTP response body.
  </Step>

  <Step title="Vobiz Executes XML">
    Vobiz parses your XML and executes each element in order: plays audio, collects input, dials numbers, records audio, etc.
  </Step>

  <Step title="Cycle Repeats">
    If your XML includes action URLs (on Gather, Record, Dial, etc.), Vobiz requests new XML from those URLs and the cycle continues until the call ends or a Hangup element is reached.
  </Step>
</Steps>

## Webhook lifecycle

### Answer URL (inbound calls)

When an incoming call arrives at your Vobiz phone number, Vobiz requests XML from the Answer URL configured in your application settings.

```http theme={null}
POST https://yourapp.com/answer
CallUUID=abc123&From=+14155551234&To=+14155559999&Direction=inbound
```

### Action URLs (subsequent events)

XML elements like Gather, Record, and Dial can specify action URLs. After the action completes, Vobiz requests new XML from that URL with event-specific parameters.

```http theme={null}
POST https://yourapp.com/menu-choice
CallUUID=abc123&Digits=1&From=+14155551234
```

### Hangup URL (call end)

When the call ends (hangup, timeout, network issue), Vobiz sends a final webhook to your Hangup URL with call duration, end reason, and other metadata. This is used for logging and billing - no XML response is expected.

```http theme={null}
POST https://yourapp.com/hangup
CallUUID=abc123&Duration=125&HangupCause=NORMAL_CLEARING
```

## Complete example flow

### Step 1: incoming call (answer URL)

A customer calls your Vobiz number. Vobiz sends a webhook to your Answer URL:

```http Webhook Request to Answer URL theme={null}
POST /answer HTTP/1.1
Host: yourapp.com
Content-Type: application/x-www-form-urlencoded

CallUUID=xyz789&From=+14155551234&To=+14155559999&Direction=inbound
```

Your server returns XML presenting an IVR menu:

```xml Your XML Response theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather
numDigits="1"
executionTimeout="10"
action="https://yourapp.com/menu-choice"
method="POST">
        <Speak>Press 1 for sales, 2 for support, 0 for operator.</Speak>
    </Gather>
    <Speak>We didn't receive your input. Goodbye!</Speak>
    <Hangup/>
</Response>
```

### Step 2: user presses "1" (action URL)

Vobiz collects the digit and sends a webhook to the action URL:

```http Webhook Request to Action URL theme={null}
POST /menu-choice HTTP/1.1
Host: yourapp.com
Content-Type: application/x-www-form-urlencoded

CallUUID=xyz789&Digits=1&From=+14155551234
```

Your server checks the digit, looks up the sales queue, and returns XML to transfer the call:

```xml Your XML Response theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>Connecting you to sales. Please hold.</Speak>
    <Dial timeout="30" action="https://yourapp.com/dial-result">
        +14155555678
    </Dial>
    <Speak>Sorry, no one is available. Please call back later.</Speak>
    <Hangup/>
</Response>
```

### Step 3: call connects or fails

If the Dial succeeds, the calls are bridged. When one party hangs up, Vobiz sends a webhook to the Dial action URL with the result, then to your Hangup URL when the call fully ends.

## Key takeaways

<CardGroup cols={2}>
  <Card title="XML is Stateless">
    Each webhook is independent. Vobiz does not maintain call flow state - your application must track the conversation using `CallUUID` and database lookups.
  </Card>

  <Card title="Webhooks Must Respond Fast">
    Your server should return XML within 1–2 seconds. Slow responses cause dead air for callers. Do heavy processing asynchronously and cache data when possible.
  </Card>

  <Card title="Chain Actions Together">
    Use action URLs to build multi-step flows: collect input, validate, transfer, record, send notification. Each step is a separate webhook-XML cycle.
  </Card>

  <Card title="Always Have a Fallback">
    If input collection times out or a Dial fails, provide fallback XML (retry, leave voicemail, or hang up gracefully). Never leave calls in an undefined state.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.