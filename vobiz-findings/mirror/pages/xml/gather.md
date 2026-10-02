> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Gather XML Element – Collect DTMF & Speech Input | Vobiz

> Collect caller input via DTMF or speech recognition (ASR) in a live call. Configurable timeout, digit count, and action URL for dynamic IVR flows.

You can use the Gather XML element to collect user input through automatic speech recognition or DTMF "digit press" inputs.

When collecting speech as input, Vobiz transcribes and relays a user's speech to the specified action URL in real time.

When collecting input through digit press, Vobiz relays the digits entered to the specified action URL.

The Gather XML element supports simultaneous detection of both speech and digit press inputs.

## Nesting elements

You can nest Speak XML (text-to-speech) and Play XML elements inside Gather XML to prompt users for inputs. This is useful for building interactive voice response (IVR) experiences.

## Attributes

| Attribute | Description |
| - | - |
| `action` <br /> *string, required* <br /> *Callback-retry configurable* | The input is sent to a specific URL. See the [parameters sent to the action URL](#parameters-sent-to-the-action-url) for more information. <br /> **Allowed values:** a fully qualified URL |
| `method` <br /> *string* | The HTTP method to use when invoking the action URL. <br /> **Allowed values:** `GET`, `POST` <br /> **Default:** `POST` |
| `inputType` <br /> *string* | The type of input you expect to receive. When set to `dtmf speech`, Vobiz listens for both speech and digit inputs. The input detected first is relayed to the action URL. <br /> **Allowed values:** `dtmf`, `speech`, `dtmf speech` |
| `executionTimeout` <br /> *integer* | Maximum input-detection time in seconds. If the user provides no input, Vobiz processes the next element. The timer starts after nested `Play` and `Speak` elements finish. <br /> **Allowed values:** `5` to `60` <br /> **Default:** `15` |
| `digitEndTimeout` <br /> *string* | Time in seconds allowed between consecutive digit inputs. If Vobiz receives no new digit during this period, it processes the digits already entered. Applies to `dtmf` and `dtmf speech`. <br /> **Allowed values:** `2` to `10`, or `auto` <br /> **Default:** `auto` |
| `speechEndTimeout` <br /> *string* | Time in seconds that Vobiz waits for more speech after detecting silence. Vobiz then stops recognition and sends the transcription to the action URL. Applies to `speech` and `dtmf speech`. <br /> **Allowed values:** `2` to `10`, or `auto` <br /> **Default:** `auto` |
| `finishOnKey` <br /> *string* | A digit the user can press to submit the collected digits. If set to `<empty string>` or `none`, capture ends based on a timeout or `numDigits`. Applies to `dtmf` and `dtmf speech`. <br /> **Allowed values:** exactly one of `0`–`9`, `*`, `#`, `<empty string>`, or `none` <br /> **Default:** `#` |
| `numDigits` <br /> *integer* | Maximum number of digits to collect. Vobiz sends the digits to the action URL as soon as it collects this number. Applies to `dtmf` and `dtmf speech`. <br /> **Allowed values:** `1` to `32` <br /> **Default:** `32` |
| `speechModel` <br /> *string* | The automatic speech recognition model used to transcribe speech. Applies to `speech` and `dtmf speech`. <br /> **Allowed values:** `default`, `command_and_search`, `phone_call` <br /> **Default:** `default` <br /> `command_and_search`: optimized for short voice commands and searches. <br /> `phone_call`: optimized for phone-call audio with inconsistent quality. <br /> `telephony`: an enhanced `phone_call` model for audio that typically originates from phone calls. <br /> `default`: optimized for audio that does not match a specialized model, such as long-form audio. |
| `hints` <br /> *string* | A list of phrases that can improve recognition probability. Provide phrases as single words or small groups of words. Applies to `speech` and `dtmf speech`. <br /> **Allowed values:** a non-empty, comma-separated string of phrases <br /> **Limits:** 500 phrases per request; 10,000 characters per request; 100 characters per phrase |
| `language` <br /> *string* | The language Vobiz should recognize. Applies to `speech` and `dtmf speech`. <br /> **Allowed values:** see the list of supported languages <br /> **Default:** `en-US` |
| `interimSpeechResultsCallback` <br /> *string* <br /> *Callback-retry configurable* | URL that receives real-time requests as Vobiz recognizes speech. See the [interim speech callback parameters](#parameters-sent-to-the-interimspeechresultscallback-url) for more information. Applies to `speech` and `dtmf speech`. <br /> **Allowed values:** a fully qualified URL |
| `interimSpeechResultsCallbackMethod` <br /> *string* | The HTTP method used to invoke `interimSpeechResultsCallback`. Applies to `speech` and `dtmf speech`. <br /> **Allowed values:** `GET`, `POST` <br /> **Default:** `POST` |
| `log` <br /> *boolean* | If `true`, Vobiz logs digits or recognized speech from the caller. If `false`, Vobiz disables logging while it processes `Gather`. <br /> **Allowed values:** `true`, `false` <br /> **Default:** `true` |
| `redirect` <br /> *boolean* | If `true`, Vobiz redirects to the action URL. If `false`, Vobiz requests the URL and continues to the next element. <br /> **Allowed values:** `true`, `false` <br /> **Default:** `true` |
| `profanityFilter` <br /> *boolean* | If `true`, Vobiz masks profane words with their first letter and asterisks for the remaining characters, such as `f***`. The filter operates on single words and does not detect abusive or offensive phrases. Applies to `speech` and `dtmf speech`. <br /> **Allowed values:** `true`, `false` <br /> **Default:** `false` |

## Parameters sent to the action URL

In addition to the standard action URL request parameters, these parameters are sent to the action URL specified.

| Parameter | Description |
| - | - |
| `InputType` | The type of input detected. **Allowed values:** `dtmf`, `speech` |
| `Digits` | The digits entered by the caller, excluding the finishOnKey input, if used. Empty if `inputType` is `speech`. |
| `Speech` | The transcribed result of the caller's speech. Empty if `inputType` is `dtmf`. |
| `SpeechConfidenceScore` | A confidence score between 0.0 and 1.0. The higher the score, the more likely the transcription is accurate. |
| `BilledAmount` | The total amount billed for speech input transcription. |

## Parameters sent to the interimSpeechResultsCallback URL

In addition to the standard callback URL request parameters, these parameters are sent to the interim speech results callback URL.

| Parameter | Description |
| - | - |
| `StableSpeech` | The stable transcribed result of the user's speech. |
| `UnstableSpeech` | The newer, unstable transcribed result of the user's speech. This is an interim result and may change as more speech is gathered. |
| `Stability` | Likelihood that the recognizer will not change its guess about the interim result. Range: 0.0 (completely unstable) to 1.0 (completely stable). Only applies to unstable speech. |
| `SequenceNumber` | Sequence number of the interim speech callback, to help with ordering incoming callback requests. |

## Examples

### Collect a single DTMF digit (IVR menu)

Nest a `Speak` or `Play` element to prompt the caller. With `numDigits="1"`, Vobiz posts to the action URL as soon as one digit is pressed.

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="https://yourapp.com/menu-choice" method="POST"
            inputType="dtmf" numDigits="1" executionTimeout="10">
        <Speak>Press 1 for sales, 2 for support, or 0 for an operator.</Speak>
    </Gather>
    <Speak>We didn't receive your input. Goodbye.</Speak>
    <Hangup/>
</Response>
```

### Collect a multi-digit number with finishOnKey

For variable-length input such as an account number, set `finishOnKey="#"` and let the caller signal completion.

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="https://yourapp.com/account" method="POST"
            inputType="dtmf" numDigits="12" finishOnKey="#" executionTimeout="20">
        <Speak>Enter your account number, then press pound.</Speak>
    </Gather>
    <Redirect>https://yourapp.com/answer</Redirect>
</Response>
```

### Collect speech input

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="https://yourapp.com/intent" method="POST"
            inputType="speech" language="en-US" speechEndTimeout="auto"
            hints="billing,support,sales">
        <Speak>In a few words, tell us what you're calling about.</Speak>
    </Gather>
    <Speak>Sorry, we didn't catch that.</Speak>
</Response>
```

### Accept either speech or digits

With `inputType="dtmf speech"`, whichever input Vobiz detects first is the one relayed to the action URL.

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="https://yourapp.com/choice" method="POST"
            inputType="dtmf speech" numDigits="1" speechEndTimeout="auto">
        <Speak>Say "yes" or press 1 to confirm. Say "no" or press 2 to cancel.</Speak>
    </Gather>
</Response>
```

## Webhook payload sent to the action URL

After the caller responds (or input ends), Vobiz POSTs the standard call parameters plus the Gather-specific parameters to your action URL.

```http DTMF input theme={null}
POST /menu-choice HTTP/1.1
Host: yourapp.com
Content-Type: application/x-www-form-urlencoded

CallUUID=xyz789&From=14155551234&To=14155559999&Direction=inbound&InputType=dtmf&Digits=1&Speech=
```

```http Speech input theme={null}
POST /intent HTTP/1.1
Host: yourapp.com
Content-Type: application/x-www-form-urlencoded

CallUUID=xyz789&From=14155551234&To=14155559999&Direction=inbound&InputType=speech&Digits=&Speech=I+have+a+billing+question&SpeechConfidenceScore=0.92&BilledAmount=0.0050
```

## Edge cases and tips

* **No input / timeout.** If the caller provides no input within `executionTimeout` seconds (counted *after* nested `Play`/`Speak` finishes), Vobiz moves on to the next element in the document. Always place fallback XML (a retry, a `Redirect` back to the menu, or a `Hangup`) after the `Gather`. By default, Vobiz still POSTs to the action URL with empty `Digits` and `Speech` on timeout - check for empty values in your handler.
* **Use `executionTimeout`, never `timeout`.** `Gather` has no `timeout` attribute. Use [`Dial timeout`](/docs/xml/dial) to limit how long Vobiz waits for a B-leg to answer. The valid range for `executionTimeout` is 5-60 seconds (default 15).
* **`finishOnKey` is excluded from `Digits`.** The terminating key (default `#`) is not included in the `Digits` parameter. Set `finishOnKey=""` or `finishOnKey="none"` to rely solely on `numDigits` or the timeout.
* **`numDigits` ends collection early.** Vobiz posts as soon as it collects `numDigits` digits, before the timeout or `finishOnKey`. For single-key menus, set `numDigits="1"` for the snappiest response.
* **DTMF vs speech.** Use `dtmf` for menus and structured input (account numbers, PINs) - it is precise and free. Use `speech` for open-ended intent capture; it incurs a per-request charge (see [Pricing for speech recognition](/docs/xml/gather/pricing-for-speech-recognition)) and returns a `SpeechConfidenceScore` you should threshold before acting. Combine with `dtmf speech` when you want to accept both.
* **Improve recognition.** Pass domain words via `hints`, set the correct `language` (see [supported languages](/docs/xml/gather/supported-languages)), and pick a `speechModel` suited to the input (`command_and_search` for short commands, `phone_call`/`telephony` for call audio).
* **Validate input server-side.** Never trust `Digits` or `Speech` directly in queries or business logic - sanitize and range-check them in your handler.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.