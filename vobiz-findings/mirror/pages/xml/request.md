> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz XML Request – Webhook Parameters & Call Payload

> Vobiz sends a synchronous HTTP request with call parameters to your endpoint on each call event. Return valid XML to drive the flow - 100 KB limit applies.

When Vobiz makes a synchronous HTTP request to your application, it expects an XML document in response. Vobiz sends parameters with the request that your application can use before responding.

Requests are sent as `application/x-www-form-urlencoded` using the HTTP method configured for the URL (POST by default; GET sends the parameters as a query string). Your response must be a single `<Response>` document served as `application/xml` (or `text/xml`) over HTTPS.

<Warning>
  **Response constraints**

  * The XML response must not exceed **100 KB**.
  * Respond quickly - aim for under 1-2 seconds. A slow or unreachable endpoint causes dead air and can drop the call.
  * The `Content-Type` must be `application/xml` or `text/xml`. Returning `text/html` or `text/plain` causes a parsing error.
</Warning>

**Note:** The maximum allowed size of the XML document in response to an HTTP request from Vobiz is 100 KB.

## Voice calls

### Parameters Vobiz sends for voice calls

| Parameter | Description |
| - | - |
| `CallUUID` | Unique identifier for the call. |
| `From` | Phone number of the party that initiated the call, including the country code. For inbound calls, this is the caller's caller ID. For outbound API calls, this is the caller ID specified in the request. |
| `To` | Phone number of the called party, including the country code. For inbound calls, this is your incoming number. For outbound calls, this is the destination number. |
| `ForwardedFrom` | Original forwarding number when the carrier provides it. This field is present only for forwarded calls and may be unavailable depending on the carrier. |
| `CallStatus` | Current call status. Values include `ringing`, `in-progress`, and `completed`. Final outbound values may also include `busy`, `failed`, `timeout`, or `no-answer`. |
| `Direction` | Call direction. Typical values are `inbound` and `outbound`. |
| `ALegUUID` | Unique identifier for the first leg of an outbound call. Not present for inbound calls. |
| `ALegRequestUUID` | Request identifier returned for the first leg of an outbound API call. Not present for inbound calls. |
| `HangupCause` | Standard telephony hangup cause. Not present before the call ends. |
| `Duration` | Total call duration in seconds. Not present before the call ends. |
| `BillDuration` | Billed call duration in seconds. Not present before the call ends. |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.