> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Hangup XML Element – Terminate or Reject Calls | Vobiz

> End or reject a call at any point with the Vobiz Hangup element. Set a reason code (busy, rejected) and schedule a delayed hangup programmatically.

The Hangup element ends a call without answering it. The application attached to the Vobiz number must return the Hangup XML element with a reason attribute to end the call.

## Attributes

The Hangup element supports the following attributes.

| Attribute | Description |
| - | - |
| `reason` <br /> *string* | Specifies the reason for the hangup. <br /> **Allowed values:** `rejected`, `busy` |
| `schedule` <br /> *integer* | Schedules a call hangup after the specified number of seconds. Follow it with an element such as `Speak`; otherwise, the call hangs up immediately. <br /> **Allowed values:** integer greater than `0`, in seconds |

**Note:**

* When the Hangup element is the first element in an Answer XML response, the call is hung up with reason `rejected` if no reason attribute is specified.
* When Hangup is not the first element, or if the call is already answered, the call is hung up with reason `Normal Hangup` if no reason attribute is specified.

## Nesting rules

`Hangup` takes no child elements and no text content; it is a self-closing top-level child of `<Response>` (`<Hangup/>`). Any elements placed after `Hangup` are not processed.

## Examples

### End a call gracefully

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>Thank you for calling. Goodbye.</Speak>
    <Hangup/>
</Response>
```

### Reject an inbound call before answering

Place `Hangup` first to reject a call without billing it. Use `reason="busy"` to return a busy signal or `reason="rejected"` to decline.

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Hangup reason="busy"/>
</Response>
```

### Hang up after a fixed duration

Combine `schedule` with a following element so the call stays up until the timer fires. See [Hang up after a minute](/docs/xml/hangup/hang-up-after-a-minute).

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Hangup schedule="60"/>
    <Speak loop="0">This call will end in one minute.</Speak>
</Response>
```

## Edge cases and tips

* **`schedule` needs a following element.** If you set `schedule` but no element follows, the call hangs up immediately. Add a `Speak`, `Play`, or `Wait` element so there is something to run until the timer elapses.
* **Reject vs hang up.** Use `reason="rejected"` or `reason="busy"` on an unanswered inbound call to avoid answering (and billing) it. Once a call is answered, omitting `reason` ends it with `Normal Hangup`.
* **No XML response also ends the call.** Returning an empty `<Response></Response>` leaves the call connected with no instructions; to actively end it, include `<Hangup/>`.
* **The hangup URL still fires.** After the call ends, Vobiz posts the final call metadata (duration, hangup cause) to your application's hangup URL. No XML is expected in that response.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.