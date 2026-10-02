> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Wait XML Element – Silent Pause & Machine Detection | Vobiz

> Pause a call silently for a set duration with the Vobiz Wait element. Detects voicemail beeps and delays call pickup - essential for AMD and paced IVR flows.

The Wait element waits silently for a specified number of seconds. If `<Wait>` is the first element in a XML document, Vobiz will wait the specified number of seconds before picking up the call.

## Attributes

| Attribute | Description |
| - | - |
| `length` <br /> *integer* | Time to wait in seconds. <br /> **Allowed values:** integer greater than `0` <br /> **Default:** `1` |
| `silence` <br /> *boolean* | If `true`, Vobiz ends the wait and continues to the next XML element when it detects no voice or sound for `minSilence` milliseconds. If `false`, Vobiz waits for the full `length` period regardless of detected sound or voice. <br /> **Allowed values:** `true`, `false` <br /> **Default:** `false` |
| `minSilence` <br /> *integer* | Minimum silence duration in milliseconds required to trigger an early exit. Only used when `silence` is `true`. The `length` value must be greater than `minSilence` for this attribute to work as expected. <br /> **Allowed values:** integer greater than `0` <br /> **Default:** `2000` |
| `beep` <br /> *boolean* | Detects a voicemail machine beep so an application can leave a voicemail message. Only used when `silence` and `minSilence` are not active. <br /> **Allowed values:** `true`, `false` <br /> **Default:** `false` |

## Nesting rules

`Wait` takes no child elements and no text content; it is a self-closing element (`<Wait/>`). It can appear as a top-level child of `<Response>` or nested inside [`PreAnswer`](/docs/xml/preanswer). `Wait` posts no parameters of its own to any URL.

## Examples

### Pause before speaking

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Wait length="3"/>
    <Speak>Sorry to keep you waiting.</Speak>
</Response>
```

### Delay answering an inbound call

When `Wait` is the first element, Vobiz holds the call ringing for `length` seconds before answering. This avoids billing the first few seconds and can deter auto-diallers.

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Wait length="5"/>
    <Speak>Thank you for calling.</Speak>
</Response>
```

### Exit early on silence

With `silence="true"`, Vobiz ends the wait as soon as it detects `minSilence` milliseconds of quiet, up to a maximum of `length` seconds. Useful for waiting out a greeting before proceeding.

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Wait length="10" silence="true" minSilence="2000"/>
    <Speak>Continuing now.</Speak>
</Response>
```

### Leave a voicemail after the beep (AMD)

With `beep="true"`, Vobiz waits for the answering-machine beep before continuing, so your message records after the tone. See [Machine detection](/docs/xml/wait/machine-detection).

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Wait length="15" beep="true"/>
    <Speak>Hi, this is a reminder about your appointment tomorrow at 10 AM.</Speak>
    <Hangup/>
</Response>
```

## Edge cases and tips

* **`silence` and `beep` are mutually exclusive.** `beep` is only evaluated when `silence` (and `minSilence`) are not active. Do not rely on both behaviors in the same `Wait`.
* **`length` must exceed `minSilence`.** Because `length` is in seconds and `minSilence` is in milliseconds, ensure `length * 1000 > minSilence`, or the silence early-exit never has room to trigger.
* **First-element behavior is special.** Only a leading `Wait` delays answering. A `Wait` placed after another element pauses an already-answered call.
* **Detection is best-effort.** Beep and silence detection depend on audio quality and carrier behavior; always pair them with a fallback flow.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.