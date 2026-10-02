> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Is call transfer supported?

> Vobiz supports three call transfer methods - Dial XML, REST API live transfer, and SIP REFER (RFC 3515) - covering warm transfers, cold transfers, and AI agent escalations.

**Yes.** Call transfer functionality is fully supported across all environments - whether you are using a simple Voice XML script or dynamically redirecting calls via the REST API in response to AI Voice agent sentiment analysis.

## Supported Routing Methods

* **The [`<Dial>`](/docs/xml/dial) XML tag** - The primary method for bridging a live caller to another party. Use the standard `<Dial>` noun within your BXML response to warm- or cold-transfer the caller to a new SIP URI or E.164 phone number.
* **[REST API live transfer](/docs/call/transfer-call)** - If a call is already in progress (e.g., streaming to Retell AI) and you need to redirect dynamically (such as escalating a frustrated user to a human agent), `Update` the call state via the `/transfer-call` endpoint to point it at a new XML destination.
* **SIP REFER (blind/attended SIP transfer)** - If you connect natively via SIP hardware (IP desk phone or PBX) rather than APIs, Vobiz supports RFC 3515 `SIP REFER` messages so your authenticated SIP endpoints can trigger blind or attended transfers at the network layer.

<Note>
  SIP REFER is supported on verified SIP Trunks only.
</Note>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.