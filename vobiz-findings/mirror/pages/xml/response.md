> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Response XML Element – Root Container for Call Instructions | Vobiz

> Every Vobiz XML document must wrap call instructions in a single Response root element. All verbs and nested elements go inside Response to produce valid XML.

The root element for all Vobiz XML documents. Every XML response must be wrapped in a single `Response` element.

### Purpose

The `Response` element acts as the container for all XML verb elements that control call behavior. It tells Vobiz that the XML document contains valid call instructions and marks the beginning and end of your call flow logic.

## Attributes

| Type | Required | Description |
| - | - | - |
| - | - | The `Response` element has no attributes. |

## Nesting rules

### Allowed child elements

The `Response` element can contain the following verb elements:

### Details

* `<Dial>` - dial a phone number or SIP user
* `<Speak>` - synthesize speech
* `<Play>` - play an audio file
* `<Record>` - record the call
* `<Gather>` - collect DTMF or speech input
* `<Hangup>` - hang up the call
* `<Redirect>` - redirect to another XML URL
* `<Wait>` - pause the call
* `<Conference>` - join a conference room
* `<PreAnswer>` - play audio before answering
* `<DTMF>` - send DTMF tones
* `<Stream>` - start an audio stream

### Parent elements

The `Response` element has no parent - it is always the root element.

**Important:** Every XML document must have exactly one `Response` element. Multiple Response elements or a missing Response element will result in an XML parsing error.

## Examples

### Basic usage

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>Hello! This is a basic XML response.</Speak>
</Response>
```

### Multiple actions

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>Thank you for calling Vobiz support.</Speak>
    <Play>https://yourcdn.com/hold-music.mp3</Play>
    <Dial>
        <Number>+14155551234</Number>
    </Dial>
</Response>
```

Verb elements are executed in the order they appear. In this example, Vobiz speaks the message, plays the hold music, and then dials the number.

### IVR flow

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="https://your-domain.com/gather/" method="POST" numDigits="1" executionTimeout="10">
        <Speak>Press 1 for sales, press 2 for support.</Speak>
    </Gather>
    <Speak>We didn't receive your input. Goodbye!</Speak>
    <Hangup/>
</Response>
```

This response collects one digit from the caller. If no input is received within 10 seconds, it speaks a goodbye message and hangs up.

### Empty response

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
</Response>
```

An empty `Response` element is valid but performs no actions. The call continues without any instructions. Use this for call events where no action is needed.

## Best practices

### Always include the XML declaration

Start your XML documents with `<?xml version="1.0" encoding="UTF-8"?>` to ensure proper parsing and character encoding.

### Validate your XML

Use an XML validator or linter during development to catch syntax errors before deploying to production. Malformed XML will cause call failures.

### Set the proper Content-Type

When your application responds to Vobiz webhooks, set the HTTP `Content-Type` header to `application/xml` or `text/xml`. A `text/html` or `text/plain` response causes a parsing error and drops the call.

### Stay within the size and time limits

Keep each XML response under **100 KB** and return it within 1-2 seconds. Verbs execute top-to-bottom. `<Redirect>` hands control to another document. For elements with an `action` URL, the element's `redirect` behavior determines whether Vobiz executes returned XML or continues the current flow. For example, `<Dial redirect="false">` still sends its final result to `action` but ignores returned XML and continues with the next element.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.