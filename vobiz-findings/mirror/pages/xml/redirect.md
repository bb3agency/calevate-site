> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Redirect XML Element – Dynamic Call Flow Routing | Vobiz

> Transfer call control to a new URL with the Vobiz Redirect element. All elements after Redirect are skipped - ideal for conditional IVR branching globally.

The `Redirect` element transfers control of a call to a different URL, which then returns a fresh `<Response>` to drive the rest of the flow. The redirect URL is the element's text content. Any elements placed after `<Redirect>` are never processed - `Redirect` must be the last element you intend to run.

## Attributes

| Attribute | Description |
| - | - |
| `method` <br /> *string* | HTTP method used to request the redirect URL. <br /> **Allowed values:** `GET`, `POST` <br /> **Default:** `POST` |

## Nesting rules

`Redirect` takes no child elements. Its text content is a single fully qualified HTTPS URL. `Redirect` cannot be nested inside another verb - it is a top-level child of `<Response>`.

## Parameters sent in the redirect request

| Parameter | Type | Description |
| - | - | - |
| `From` | string | Phone number of the party that initiated the call, including the country code. For inbound calls, this is the caller's caller ID. For outbound API calls, this is the configured caller ID. |
| `To` | string | Phone number of the called party, including the country code. For inbound calls, this is your incoming number. For outbound calls, this is the destination number. |
| `Event` | string | Event type. The value is `Redirect`. |
| `CallUUID` | string | Unique identifier for the call. |
| `CallerName` | string | Caller name for a SIP call or caller ID for a PSTN call. |
| `Direction` | string | Call direction. Typical values are `inbound` and `outbound`. |
| `CallStatus` | string | Current call status, such as `ringing`, `in-progress`, or `completed`. Final outbound values may also include `busy`, `failed`, `timeout`, or `no-answer`. |

## Examples

### Redirect to a new flow

When the `Speak` element finishes, Vobiz requests the redirect URL and runs whatever XML it returns.

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>Please wait while we transfer your call.</Speak>
    <Redirect>https://yourapp.com/next-step</Redirect>
</Response>
```

### Loop back to a menu

Use `Redirect` to re-present an IVR menu after invalid input, instead of duplicating the menu XML.

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>Sorry, that is not a valid option.</Speak>
    <Redirect method="POST">https://yourapp.com/answer</Redirect>
</Response>
```

### Example redirect webhook

```http POST to the redirect URL theme={null}
POST /next-step HTTP/1.1
Host: yourapp.com
Content-Type: application/x-www-form-urlencoded

From=14155551234&To=14155559999&CallUUID=xyz789&Event=Redirect&Direction=inbound&CallStatus=in-progress&CallerName=Jane+Doe
```

## Edge cases and tips

* **Elements after `Redirect` are dead code.** Vobiz stops processing the current document the moment it reaches `Redirect`. Put fallback logic in the redirect target, not after the `Redirect` element.
* **The target must return valid XML.** The redirect URL must respond with a `<Response>` document served as `application/xml`. A non-XML or error response drops the call.
* **`Redirect` vs transferring with `Dial`.** Use `Redirect` to change which of *your* endpoints controls the call flow (branching, looping, handing off to another service). Use [`Dial`](/docs/xml/dial) to bridge the caller to *another party* (a phone number or SIP user). To transfer a live call to an agent, return XML from the redirect target that contains a `Dial` - see [Transfer a call](/docs/xml/redirect/transfer-a-call).
* **State is not carried automatically.** `Redirect` posts the standard call parameters but not your application's own state. Pass context via query parameters on the URL or look it up by `CallUUID`.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.