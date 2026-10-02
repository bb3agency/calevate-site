> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Getting Started with Vobiz Voice XML – Build Your First App

> Build your first Vobiz voice application from scratch. Set up a webhook, write XML responses, and test your call flow with ngrok - works globally on any stack.

## Prerequisites

<CardGroup cols={2}>
  <Card title="What You'll Need">
    * A Vobiz account with API access
    * A phone number purchased from Vobiz
    * A web server that can receive HTTP requests (webhook endpoint)
    * Basic understanding of HTTP and XML
  </Card>

  <Card title="Recommended Tools">
    * **ngrok** or similar for local development tunneling
    * **cURL** or similar for testing webhooks
    * **Node.js, Python, or PHP** for server-side logic
    * **XML validator** to check syntax
  </Card>
</CardGroup>

## Hello World Example

Start with the simplest possible voice application: answering a call and speaking a greeting.

### Step 1: Create a Webhook Endpoint

Set up a simple HTTP server that returns XML. Here's a Node.js Express example:

```javascript server.js theme={null}
const express = require('express');
const app = express();

app.post('/answer', (req, res) => {
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>Hello! Welcome to Vobiz telephony platform.</Speak>
    <Hangup/>
</Response>`;

  res.type('application/xml');
  res.send(xml);
});

app.listen(3000, () => {
  console.log('Server running on port 3000');
});
```

### Step 2: Expose Your Server

For local development, use ngrok to create a public URL.

```bash Terminal theme={null}
ngrok http 3000
```

ngrok will provide a URL like `https://abc123.ngrok.io`

### Step 3: Configure Your Application

In the Vobiz Console, configure your Application's Answer URL:

```text theme={null}
Answer URL: https://abc123.ngrok.io/answer
Method: POST
```

Assign this application to your Vobiz phone number. When someone calls that number, they will hear your greeting.

## IVR Menu Example

Now build an interactive IVR menu that collects caller input and routes calls accordingly.

### Answer Endpoint

```javascript POST /answer - Present IVR Menu theme={null}
app.post('/answer', (req, res) => {
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather
numDigits="1"
executionTimeout="10"
action="https://abc123.ngrok.io/menu-choice"
method="POST">
        <Speak>
            Press 1 for sales, press 2 for technical support,
or press 0 to speak with an operator.
        </Speak>
    </Gather>
    <Speak>We didn't receive your input. Goodbye!</Speak>
    <Hangup/>
</Response>`;

  res.type('application/xml');
  res.send(xml);
});
```

### Menu Choice Handler

```javascript POST /menu-choice - Route Based on Input theme={null}
app.post('/menu-choice', (req, res) => {
  const digit = req.body.Digits;
  let xml;

  switch(digit) {
    case '1':
      xml = `<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>Connecting you to sales.</Speak>
    <Dial>+14155551111</Dial>
</Response>`;
      break;

    case '2':
      xml = `<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>Connecting you to technical support.</Speak>
    <Dial>+14155552222</Dial>
</Response>`;
      break;

    case '0':
      xml = `<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>Transferring to operator.</Speak>
    <Dial>+14155550000</Dial>
</Response>`;
      break;

    default:
      xml = `<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>Invalid selection. Please try again.</Speak>
    <Redirect>https://abc123.ngrok.io/answer</Redirect>
</Response>`;
  }

  res.type('application/xml');
  res.send(xml);
});
```

## Testing Your XML

<CardGroup cols={2}>
  <Card title="Method 1: Real Phone Calls">
    The most accurate way to test is calling your Vobiz number from a real phone.

    * Test audio quality and timing
    * Verify DTMF input collection
    * Check call transfer functionality
    * Monitor webhook logs in real-time
  </Card>

  <Card title="Method 2: Webhook Simulation">
    Use cURL to simulate Vobiz webhook requests to your endpoint:
  </Card>
</CardGroup>

```bash Test with cURL theme={null}
curl -X POST https://yourapp.com/answer \
  -d "CallUUID=test123" \
  -d "From=+14155551234" \
  -d "To=+14155559999"
```

<Warning>
  **Development Tips**

  * Log all incoming webhook data to debug call flows
  * Validate your XML syntax before deploying changes
  * Use descriptive Speak messages to understand which code path executed
  * Start simple and add complexity gradually
  * Monitor server response times - keep them under 1 second
</Warning>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.