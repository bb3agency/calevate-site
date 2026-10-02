> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# DTMF XML Element – Send Tones on Live Calls | Vobiz

> Send DTMF tones programmatically on a live call with the Vobiz DTMF element. Automate IVR navigation and phone-tree traversal using async digit sending.

The DTMF element sends digits on a live call - for instance, to automate navigation through an interactive voice response (IVR) menu.

If `async` is set to `true`, Vobiz sends digits in the background and the call moves to the next XML element as soon as the first digit is sent. Use the character `w` to add a 0.5-second delay and `W` for a 1-second delay.

**Allowed values:** 1234567890\*#wW

## Attributes

| Attribute | Description |
| - | - |
| `async` <br /> *boolean* | If `true`, proceeds to the next XML element after the first digit is sent. <br /> **Allowed values:** `true`, `false` <br /> **Default:** `true` |

## Nesting rules

The digits to send are the element's text content. `DTMF` takes no child elements and is a top-level child of `<Response>`. It posts no parameters of its own to any URL.

## Send digits

This code sends the digits 1234 on the live call.

### Response

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <DTMF>1234</DTMF>
</Response>
```

### Navigate an IVR with delays

Use `w` (0.5 s) and `W` (1 s) characters to pace tones so a remote menu has time to respond between digits.

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <DTMF async="false">1WW2W3#</DTMF>
    <Speak>Connected to the right department.</Speak>
</Response>
```

## Edge cases and tips

* **`async` controls flow.** With the default `async="true"`, the call advances to the next element as soon as the first digit is sent - useful when you want to send tones in the background while continuing the flow. Set `async="false"` to send all digits before moving on, which matters when a downstream menu must receive every digit first.
* **Only valid characters.** The content must contain only `1234567890*#wW`. Any other character causes the element to be ignored.
* **`DTMF` sends, `Gather` receives.** Use `DTMF` to *send* tones onto a live call (for example, to traverse another system's phone tree). Use [`Gather`](/docs/xml/gather) to *collect* digits the caller presses.
* **Pacing matters.** Sending digits too fast can outrun a remote IVR. Insert `w`/`W` pauses if the far end misses tones.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.