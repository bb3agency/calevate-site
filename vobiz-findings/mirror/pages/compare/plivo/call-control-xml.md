> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# PlivoXML to VobizXML: Verb-by-Verb Call-Control Reference

> A complete verb-by-verb map of PlivoXML to VobizXML call control: GetDigits/GetInput to Gather, Dial, Record, Conference, Stream, plus every attribute rename and the plivoxml-to-vobizxml SDK builder swap.

VobizXML is a near drop-in for PlivoXML: same `<Response>` wrapper, same verb names, same nesting rules. The only structural rename is input collection - Plivo's `<GetDigits>` **and** `<GetInput>` both become Vobiz's [`<Gather>`](/docs/xml/gather).

## Verb mapping table

| PlivoXML verb | `plivoxml` builder method | VobizXML verb | `vobizxml` builder method | Notes |
| - | - | - | - | - |
| `<Response>` | `ResponseElement()` | [`<Response>`](/docs/xml/response) | `vobizxml.ResponseElement()` | Same root. Serve as `application/xml`. |
| `<GetDigits>` | `add_get_digits()` | [`<Gather>`](/docs/xml/gather) | `add_gather()` (alias `add_get_digits()`) | **Rename.** `timeout`→`executionTimeout`, `digitTimeout`→`digitEndTimeout`. |
| `<GetInput>` | `add_get_input()` | [`<Gather>`](/docs/xml/gather) | `add_gather()` (alias `add_get_input()`) | **Rename only** - `inputType`/`executionTimeout` already match. |
| `<Speak>` | `add_speak()` | [`<Speak>`](/docs/xml/speak) | `add_speak()` | Same. `voice` (`WOMAN`/`MAN`), `language`, `loop`. |
| `<Play>` | `add_play()` | [`<Play>`](/docs/xml/play) | `add_play()` | Same. `loop` (`0` = infinite). MP3/WAV over HTTPS. |
| `<Wait>` | `add_wait()` | [`<Wait>`](/docs/xml/wait) | `add_wait()` | Same. `length`, `silence`/`minSilence`, `beep`. |
| `<Dial>` | `add_dial()` | [`<Dial>`](/docs/xml/dial) | `add_dial()` | Same. Nest `Number`/`User`. Ports verbatim. |
| `<Number>` | `add_number()` | [`<Number>`](/docs/xml/dial/number) | `add_number()` | Same. `sendDigits`, `sipHeaders`. |
| `<User>` | `add_user()` | [`<User>`](/docs/xml/dial/user) | `add_user()` | Same. SIP endpoint as text content. |
| `<Record>` | `add_record()` | [`<Record>`](/docs/xml/record) | `add_record()` | Same verb; `action` is **required** in Vobiz. |
| `<Conference>` | `add_conference()` | [`<Conference>`](/docs/xml/conference) | `add_conference()` | Same. Room name is text content. `startConferenceOnEnter`, `endConferenceOnExit`, `callbackUrl`. |
| `<Redirect>` | `add_redirect()` | [`<Redirect>`](/docs/xml/redirect) | `add_redirect()` | Same. `method` (GET/POST). |
| `<Hangup>` | `add_hangup()` | [`<Hangup>`](/docs/xml/hangup) | `add_hangup()` | Same. `reason` (`rejected`/`busy`), `schedule`. |
| `<DTMF>` | `add_dtmf()` | [`<DTMF>`](/docs/xml/dtmf) | `add_dtmf()` | Same. Digits are text content; `async` (Python kwarg `async_`). |
| `<PreAnswer>` | `add_pre_answer()` | [`<PreAnswer>`](/docs/xml/preanswer) | `add_preanswer()` | Same. Only `Speak`/`Play`/`Wait` nest inside. |
| `<Stream>` | `add_stream()` | [`<Stream>`](/docs/xml/stream) | `add_stream()` | Same. `bidirectional`, `audioTrack`, `contentType`, `keepCallAlive`. |

## Before / after: an IVR menu (GetDigits → Gather)

This is the most common port. Map `timeout`→`executionTimeout`, `digitTimeout`→`digitEndTimeout`, and add `inputType="dtmf"`.

```xml PlivoXML (before) theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <GetDigits action="https://yourapp.com/menu-choice" method="POST"
               numDigits="1" timeout="10" digitTimeout="3" finishOnKey="#">
        <Speak>Press 1 for sales, 2 for support, or 0 for an operator.</Speak>
    </GetDigits>
    <Speak>We didn't receive your input. Goodbye.</Speak>
    <Hangup/>
</Response>
```

```xml VobizXML (after) theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="https://yourapp.com/menu-choice" method="POST"
            inputType="dtmf" numDigits="1" executionTimeout="10"
            digitEndTimeout="3" finishOnKey="#">
        <Speak>Press 1 for sales, 2 for support, or 0 for an operator.</Speak>
    </Gather>
    <Speak>We didn't receive your input. Goodbye.</Speak>
    <Hangup/>
</Response>
```

The action-URL payload is parameter-compatible: both platforms POST `Digits` (and, for speech, `Speech`, `SpeechConfidenceScore`, and `BilledAmount`).

<Warning>
  `<Gather>` uses **`executionTimeout`** (5–60s, default 15) for its collection window. In VobizXML `timeout` belongs to [`<Dial>`](/docs/xml/dial) and `<Number>` (ring timeout). When porting from Plivo's `<GetDigits timeout="...">`, map `timeout` → `executionTimeout`.
</Warning>

## Gotchas

* **`<GetInput>` is a free port** - its `inputType` and `executionTimeout` already match `<Gather>`; just rename the tag.
* **`<Record action>` is required in Vobiz** - Plivo allows `<Record>` without it; Vobiz needs it to deliver `RecordUrl`.
* **SSML is content, not builder verbs** - pass `ssml="..."` to `add_speak()`/`<Speak>` instead of Plivo's `add_break`/`add_prosody`/etc. See [SSML](/docs/xml/speak/ssml).
* **REST auth differs** - Vobiz uses `X-Auth-ID` + `X-Auth-Token` headers (not HTTP Basic) against `https://api.vobiz.ai/api/v1`. See [auth & base URL](/docs/guides/plivo-to-vobiz/auth-and-base-url).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.