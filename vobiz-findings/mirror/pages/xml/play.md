> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Play XML Element – Stream Audio Files to Callers | Vobiz

> Stream MP3 or WAV audio from a remote URL to a caller with the Vobiz Play element. Set loop count for hold music, announcements, or voice agent audio prompts.

The `Play` element plays an audio file from a remote URL to the caller. Vobiz supports MP3 and WAV audio files. The audio URL is the text content of the element, not an attribute.

`Play` runs to completion before Vobiz moves to the next element, unless the caller hangs up. It posts no parameters of its own to any URL.

## Attributes

| Attribute | Description |
| - | - |
| `loop` <br /> *integer* | The number of times to play the audio file. Set to `0` to play indefinitely, until the caller hangs up or another event interrupts the call. <br /> **Allowed values:** integer greater than or equal to `0` <br /> **Default:** `1` |

## Nesting rules

`Play` takes no child elements. Its text content must be a single fully qualified HTTPS URL pointing to an MP3 or WAV file. To play several files in sequence, use multiple `Play` elements.

## Examples

### Play an audio file once

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>https://yourcdn.com/welcome.mp3</Play>
</Response>
```

### Loop hold music indefinitely

Use `loop="0"` for hold music or waiting tones. The audio repeats until the caller hangs up or a parallel event (such as a bridged `Dial` connecting) moves the flow forward.

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play loop="0">https://yourcdn.com/hold-music.mp3</Play>
</Response>
```

### Play several files in order

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>https://yourcdn.com/greeting.mp3</Play>
    <Play loop="2">https://yourcdn.com/menu-options.mp3</Play>
</Response>
```

## Edge cases and tips

* **URL must be reachable over HTTPS.** If Vobiz cannot fetch the file (404, timeout, SSL error, or non-audio content type), it skips the element and continues to the next one. Always serve audio with a correct `Content-Type` (`audio/mpeg` for MP3, `audio/wav` for WAV).
* **Optimize for telephony.** Use 8 kHz mono files. Higher sample rates increase fetch latency without improving call audio quality.
* **`Play` vs `Speak`.** Use `Play` for prerecorded audio (consistent quality, music, jingles). Use [`Speak`](/docs/xml/speak) for dynamic text that changes per call.
* **Interrupting playback.** To let the caller interrupt audio with a key press, nest `Play` inside a [`Gather`](/docs/xml/gather) instead of using it standalone.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.