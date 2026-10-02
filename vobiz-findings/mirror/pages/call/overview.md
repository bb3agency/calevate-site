> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Call Management Overview

> Manage voice calls globally with Vobiz telephony platform - make, transfer, hang up, record, and monitor calls across 130+ countries via a unified REST API.

## Introduction

A Call object is created when an outbound call is initiated or an inbound call is received. Use it to interact with ongoing calls, retrieve details about completed calls, and transfer calls to build custom call flows.

### Base URL

```
https://api.vobiz.ai/api
```

### Endpoint

```
https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/
```

## Authentication

<Info>
  **Authentication Required:**

  * `X-Auth-ID` - Your account ID (e.g., `{auth_id}`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

### Example Request Headers

```
X-Auth-ID: {auth_id}
X-Auth-Token: YOUR_AUTH_TOKEN
Content-Type: application/json
```

## Call Operations

* **[Make a Call](/docs/call/make-call)** - Initiate an outbound call to a PSTN number or SIP endpoint.
* **[Machine Detection](/docs/call/machine-detection)** - Detect answering machines on outbound calls with synchronous or asynchronous detection modes.
* **[Transfer a Call](/docs/call/transfer-call)** - Transfer an ongoing call to fetch and execute XML from a different URL. Transfer A-leg, B-leg, or both.
* **[Hang Up a Call](/docs/call/hangup-call)** - Hang up an ongoing call or cancel a queued outbound call.
* **[Retrieve a Live Call](/docs/call/retrieve-live-call)** - Get details of a specific ongoing call in real-time using its call UUID.
* **[Retrieve All Live Calls](/docs/call/retrieve-all-live-calls)** - Get a list of all ongoing calls (v1). Returns an array of call UUIDs for currently active calls.
* **[Retrieve a Queued Call](/docs/call/retrieve-queued-call)** - Get details of a specific queued outbound call that has not yet been initiated using its call UUID.
* **[Retrieve All Queued Calls](/docs/call/retrieve-all-queued-calls)** - Get a list of all queued outbound calls. Returns up to 20 queued calls per request.
* **[Record Calls](/docs/call/record-calls)** - Record call audio in MP3 or WAV format with automatic transcription support. Start and stop recording during active calls.
* **[Play Audio on Calls](/docs/call/play-audio)** - Play audio files during active calls. Support for single or multiple audio files, looping, and selective playback to caller or callee.
* **[Speak Text on Calls](/docs/call/speak-text)** - Convert text to speech and play during active calls. Support for 29 languages with multiple voice options.
* **[DTMF](/docs/call/dtmf)** - Send DTMF digits during active calls for IVR navigation and menu selection.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.