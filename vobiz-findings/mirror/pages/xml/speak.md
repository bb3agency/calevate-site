> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Speak XML Element – Text-to-Speech in Live Calls | Vobiz

> Convert text to speech in a live call with the Vobiz Speak element. Choose voices and languages, set loop count, and drive dynamic IVR prompts worldwide.

The `Speak` element converts text to speech (TTS) and plays it to the caller. The text to read is the element's content; voice, language, and loop count are set as attributes. `Speak` runs to completion before Vobiz moves to the next element, and posts no parameters of its own to any URL.

## Attributes

| Attribute | Description |
| - | - |
| `voice` <br /> *string* | The voice used to read the text. <br /> **Allowed values:** WOMAN, MAN <br /> Defaults to WOMAN. |
| `language` <br /> *string* | Language used to read the text. <br /> **Allowed values:** See the "Supported voices and languages" table below. <br /> Defaults to en-US. |
| `loop` <br /> *integer* | Number of times to speak the text. Set to 0 to loop indefinitely. <br /> **Allowed values:** integer >= 0 (0 indicates a continuous loop) <br /> Defaults to 1. |

## Nesting rules

`Speak` takes plain text or [SSML](/docs/xml/speak/ssml) markup as its content. It cannot contain other verbs. You can nest `Speak` inside [`Gather`](/docs/xml/gather) (to prompt for input) and [`PreAnswer`](/docs/xml/preanswer) (to speak before answering).

## Examples

### Speak a basic message

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>Thank you for calling. Please hold while we connect you.</Speak>
</Response>
```

### Choose a voice and language

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="MAN" language="en-GB">Welcome to our London office.</Speak>
</Response>
```

### Repeat a message in a loop

Set `loop` to repeat an announcement. Use `loop="0"` to repeat indefinitely (for example, a waiting-room message) until another event moves the call forward.

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak loop="3">Your call is important to us. Please stay on the line.</Speak>
</Response>
```

## Edge cases and tips

* **Escape special XML characters.** Ampersands and angle brackets in the spoken text must be escaped as `&amp;`, `&lt;`, and `&gt;`. Unescaped characters cause an XML parsing error and the call fails.
* **A voice may not exist for every language.** Not every language has both a `WOMAN` and a `MAN` voice (see the table below). If you request an unavailable combination, Vobiz falls back to the available voice for that language.
* **`Speak` vs `Play`.** Use `Speak` for dynamic, per-call text (account balances, names, confirmation read-backs). Use [`Play`](/docs/xml/play) for prerecorded audio when you need consistent quality, music, or branding.
* **Pronunciation control.** For numbers, dates, currency, and pauses, use [SSML](/docs/xml/speak/ssml) to control how text is read aloud.
* **Keep prompts short.** Callers lose attention after 15-20 seconds. Split long content into shorter `Speak` elements or break it up with menu prompts.

## Supported voices and languages

| Language | Woman | Man |
| - | - | - |
| Danish (da-DK) | yes | no |
| Dutch (nl-NL) | yes | yes |
| English - Australian (en-AU) | yes | yes |
| English - British (en-GB) | yes | yes |
| English - USA (en-US) | yes | yes |
| French (fr-FR) | yes | yes |
| French - Canadian (fr-CA) | yes | no |
| German (de-DE) | yes | yes |
| Italian (it-IT) | yes | yes |
| Polish (pl-PL) | yes | yes |
| Portuguese (pt-PT) | no | yes |
| Portuguese - Brazilian (pt-BR) | yes | yes |
| Russian (ru-RU) | yes | no |
| Spanish (es-ES) | yes | yes |
| Spanish - USA (es-US) | yes | yes |
| Swedish (sv-SE) | yes | no |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.