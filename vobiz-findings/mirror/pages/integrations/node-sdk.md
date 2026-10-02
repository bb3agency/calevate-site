> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Node.js SDK

> Build Node.js and TypeScript voice apps with the Vobiz SDK - outbound calls, SIP trunks, CDR, and call recording across 130+ countries including India.

The official Node.js SDK for the Vobiz Voice API. Make calls, manage SIP trunks, handle CDR, record calls, configure phone numbers, and more - all natively from your Node.js or TypeScript backend.

**Source code:** [vobiz-ai/Vobiz-Node-SDK](https://github.com/vobiz-ai/Vobiz-Node-SDK)

## Installation

The SDK is distributed from its GitHub repo (not a package registry). Clone it and install from source:

```bash theme={null}
git clone https://github.com/vobiz-ai/Vobiz-Node-SDK.git
npm install ./Vobiz-Node-SDK
```

## Quick start

Make an outbound call:

```javascript theme={null}
import { VobizClient } from "@vobiz/sdk";

const authId = process.env.VOBIZ_AUTH_ID;

const client = new VobizClient({
  apiKey: authId,                          // your Auth ID
  authToken: process.env.VOBIZ_AUTH_TOKEN, // your Auth Token
});

const call = await client.calls.makeCall({
  auth_id: authId,
  from: "14155551234",                      // your Vobiz number or SIP URI
  to: "+919876543210",                       // destination number
  answer_url: "https://yourserver.com/answer", // webhook returning VobizXML
  answer_method: "POST",
});

console.log("Call initiated:", call);
```

<Note>
  Resources and client namespaces are `camelCase` (e.g. `client.liveCalls`), while request body fields are `snake_case` (e.g. `auth_id`, `answer_url`). All methods return a `Promise`.
</Note>

## Authentication

All API calls require your **Auth ID** and **Auth Token**, available in the [Vobiz Console](https://console.vobiz.ai). Pass them when constructing the client - `apiKey` maps to your Auth ID and `authToken` to your Auth Token:

```javascript theme={null}
import { VobizClient } from "@vobiz/sdk";

const client = new VobizClient({
  apiKey: "YOUR_AUTH_ID",
  authToken: "YOUR_AUTH_TOKEN",
});
```

We recommend keeping credentials out of source by reading them from environment variables:

```bash theme={null}
export VOBIZ_AUTH_ID=YOUR_AUTH_ID
export VOBIZ_AUTH_TOKEN=YOUR_AUTH_TOKEN
```

```javascript theme={null}
const client = new VobizClient({
  apiKey: process.env.VOBIZ_AUTH_ID,
  authToken: process.env.VOBIZ_AUTH_TOKEN,
});
```

## Common operations

All snippets assume `client` and `authId` are initialized as shown above.

### Live calls

```javascript theme={null}
// List in-progress calls
await client.liveCalls.listLiveCalls({ auth_id: authId });

// Fetch a single live call
await client.liveCalls.getLiveCall({ auth_id: authId, call_uuid: "CALL_UUID" });

// Hang up a live call
await client.liveCalls.hangupCall({ auth_id: authId, call_uuid: "CALL_UUID" });
```

### In-call actions

```javascript theme={null}
await client.playAudio.call({ auth_id: authId, call_uuid: "CALL_UUID" });
await client.speakText.call({ auth_id: authId, call_uuid: "CALL_UUID" });
await client.dtmf.sendDtmf({ auth_id: authId, call_uuid: "CALL_UUID" });
await client.recordCalls.startRecording({ auth_id: authId, call_uuid: "CALL_UUID" });
await client.recordCalls.stopRecording({ auth_id: authId, call_uuid: "CALL_UUID" });
```

### Call detail records (CDR)

```javascript theme={null}
const cdrs = await client.cdr.listCdrs({ auth_id: authId });
const match = await client.cdr.searchCdrs({ auth_id: authId });
const one = await client.cdr.getCdr({ auth_id: authId, call_id: "CALL_ID" });
```

### Conferences

```javascript theme={null}
await client.conferences.listConferences({ auth_id: authId });
await client.conferenceMembers.muteMember({ auth_id: authId });
await client.conference.kickMember({ auth_id: authId });
```

### Phone numbers and balance

```javascript theme={null}
await client.phoneNumbers.listNumbers({ auth_id: authId });
await client.phoneNumbers.purchaseFromInventory({ auth_id: authId });
await client.balance.getBalance({ auth_id: authId, currency: "INR" });
```

## VobizXML

When a call is answered, Vobiz fetches your `answer_url` and expects **VobizXML** describing the call flow. The SDK bundles a `vobizxml` builder so you can construct it programmatically - it handles escaping and validation:

```javascript theme={null}
import { vobizxml } from "@vobiz/sdk";

app.post("/answer", (req, res) => {
  const r = new vobizxml.ResponseElement();

  const g = r.addGather({
    action: "https://yourserver.com/gather-result",
    inputType: "dtmf",
    numDigits: 1,
    executionTimeout: 10,
  });
  g.addSpeak("Welcome to Acme Corp. Press 1 for Sales.");

  r.addHangup();

  res.type("application/xml").send(r.toString());
});
```

<Note>
  Gather uses `inputType` and `executionTimeout` (not `timeout`). The `timeout` attribute belongs to Dial/Number elements only.
</Note>

### Alternative: raw XML

You can also return hand-written VobizXML directly if you prefer:

```javascript theme={null}
app.post("/answer", (req, res) => {
  const xml = `
    <Response>
      <Speak voice="WOMAN" language="en-US">Thank you for calling.</Speak>
    </Response>
  `;
  res.type("application/xml").send(xml);
});
```

## Resources

* [GitHub repository](https://github.com/vobiz-ai/Vobiz-Node-SDK)
* [Vobiz Console](https://console.vobiz.ai)
* [API documentation](/docs/introduction)
* [VobizXML reference](/docs/xml/response)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.