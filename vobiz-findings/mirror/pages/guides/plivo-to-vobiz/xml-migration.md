> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Convert PlivoXML to VobizXML

> Migrate your Plivo call-control XML to VobizXML. Most verbs are identical; the only rename is GetDigits/GetInput to Gather. Includes a full verb mapping table, before/after examples, and SDK builder changes.

If you already drive your call flows with PlivoXML, moving to VobizXML is mostly a copy-and-paste. Vobiz uses the same `<Response>` wrapper and the same verb names and nesting rules as Plivo, so the vast majority of your XML works as-is.

There is exactly **one** real rename you need to make:

* Plivo's `<GetDigits>` **and** `<GetInput>` both become Vobiz's [`<Gather>`](/docs/xml/gather).

Everything else maps one-to-one by name. This guide gives you the full mapping table and a before/after example in both XML and the SDK builder.

## How Vobiz serves XML

Like Plivo, Vobiz fetches your call-control XML from your own HTTPS endpoint. When a call is answered, Vobiz POSTs to your `answer_url`, and you return a `<Response>` document with `Content-Type: application/xml`. Verbs execute top to bottom. See [How VobizXML works](/docs/xml/overview/how-it-works) for the request and response lifecycle.

## Verb mapping table

| PlivoXML element | VobizXML element | Notes |
| - | - | - |
| `<Response>` | `<Response>` | Same wrapper. Return as `application/xml`. |
| `<GetDigits>` | `<Gather>` | **Renamed.** `type` to `inputType`, `timeout` to `executionTimeout`. |
| `<GetInput>` | `<Gather>` | **Renamed.** Same attribute changes as `<GetDigits>`. |
| `<Speak>` | `<Speak>` | Same. Supports `voice` (`WOMAN`/`MAN`), `language`, `loop`. |
| `<Play>` | `<Play>` | Same. Supports `loop` (`0` = infinite). |
| `<Dial>` | `<Dial>` | Same, with nested `<Number>`/`<User>`. Supports `action`, `timeout`, `timeLimit`, `callerId`, `confirmSound`, `dialMusic`. |
| `<Number>` | `<Number>` | Same. Nests inside `<Dial>`. |
| `<User>` | `<User>` | Same. Nests inside `<Dial>` for SIP/app endpoints. |
| `<Record>` | `<Record>` | Same. Supports `action`, `maxLength`, `timeout`, `playBeep`, `finishOnKey`, `fileFormat`, `recordSession`, `startOnDialAnswer`. |
| `<Conference>` | `<Conference>` | Same. Supports `startConferenceOnEnter`, `endConferenceOnExit`, `callbackUrl`. |
| `<Redirect>` | `<Redirect>` | Same. Supports `method`. |
| `<Hangup>` | `<Hangup>` | Same. Supports `reason`, `schedule`. |
| `<Wait>` | `<Wait>` | Same. Supports `length`, `silence`, `beep`. |
| `<PreAnswer>` | `<PreAnswer>` | Same. Only `Speak`/`Play`/`Wait` nest inside. |
| `<DTMF>` | `<DTMF>` | Same. Send tones to a remote IVR. |
| `<MultiPartyCall>` and other advanced verbs | *No direct equivalent* | Review and [contact support](/docs/faq/contact-support) before migrating. Do not assume a one-to-one mapping. |

<Warning>
  `<Gather>` uses **`executionTimeout`** (5-60 seconds, default 15), never `timeout`. In PlivoXML, `<GetDigits timeout="...">` is the inter-digit/overall timeout; in VobizXML that attribute is `executionTimeout`. The `timeout` attribute in VobizXML belongs only to `<Dial>` and `<Number>`, where it is the ring timeout.
</Warning>

## Inside Gather: the attribute changes

When you rename `<GetDigits>` or `<GetInput>` to `<Gather>`, change these two attributes:

| Plivo attribute | Vobiz attribute | Values |
| - | - | - |
| `type` | `inputType` | `dtmf`, `speech`, or `dtmf speech` |
| `timeout` | `executionTimeout` | `5` to `60` (default `15`) |

Most other attributes carry over directly, including `action`, `method`, `numDigits`, `finishOnKey`, and `language`.

## Before and after: an IVR menu

Here is a typical Plivo IVR that collects a single digit and routes the caller.

### PlivoXML (before)

```xml PlivoXML theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <GetDigits action="https://yourapp.com/menu-choice" method="POST"
               type="dtmf" numDigits="1" timeout="10">
        <Speak>Press 1 for sales, 2 for support, or 0 for an operator.</Speak>
    </GetDigits>
    <Speak>We didn't receive your input. Goodbye.</Speak>
    <Hangup/>
</Response>
```

### VobizXML (after)

Rename `<GetDigits>` to `<Gather>`, `type` to `inputType`, and `timeout` to `executionTimeout`. Nothing else changes.

```xml VobizXML theme={null}
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

## Before and after: the SDK builder

If you build XML programmatically with the Plivo SDK, the change is just as small. Plivo's `add_get_digits(...)` (and `add_get_input(...)`) becomes Vobiz's `add_gather(...)` on a `vobizxml.ResponseElement()`, with the same `type` to `inputType` and `timeout` to `executionTimeout` renames.

### Plivo SDK builder (before)

```python Plivo SDK theme={null}
import plivoxml

response = plivoxml.ResponseElement()
get_digits = response.add_get_digits(
    action="https://yourapp.com/menu-choice",
    method="POST",
    type="dtmf",
    num_digits=1,
    timeout=10,
)
get_digits.add_speak("Press 1 for sales, 2 for support, or 0 for an operator.")
response.add_speak("We didn't receive your input. Goodbye.")
response.add_hangup()

print(response.to_string())
```

### Vobiz SDK builder (after)

```python Vobiz SDK theme={null}
from vobiz import vobizxml

response = vobizxml.ResponseElement()
gather = response.add_gather(
    action="https://yourapp.com/menu-choice",
    method="POST",
    input_type="dtmf",
    num_digits=1,
    execution_timeout=10,
)
gather.add_speak("Press 1 for sales, 2 for support, or 0 for an operator.")
response.add_speak("We didn't receive your input. Goodbye.")
response.add_hangup()

print(response.to_string())
```

## What to double-check after converting

* **Every `<Gather>` uses `executionTimeout`, not `timeout`.** This is the most common mistake when porting from Plivo.
* **`<MultiPartyCall>` and other advanced Plivo verbs.** These have no guaranteed one-to-one Vobiz equivalent. Review each one and [contact support](/docs/faq/contact-support) rather than inventing a mapping.
* **All URLs are fully qualified HTTPS.** Action, callback, `confirmSound`, and `dialMusic` URLs must be absolute HTTPS, just as in Plivo.
* **Your response is served as `application/xml`.** Not `text/html` or `text/plain`.

## Next steps

<CardGroup cols={2}>
  <Card title="Webhooks and signatures" icon="webhook" href="/docs/guides/plivo-to-vobiz/webhooks-and-signatures">
    Map Plivo webhook parameters and signature validation to Vobiz.
  </Card>

  <Card title="Plivo to Vobiz overview" icon="arrow-right-arrow-left" href="/docs/guides/plivo-to-vobiz">
    See the full migration guide for moving from Plivo to Vobiz.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.