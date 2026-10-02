> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Conference XML Element – Multi-Party Call Rooms | Vobiz

> Connect callers to a named conference room with the Vobiz Conference element. Multiple participants join the same room - supports global SIP conferencing.

Connects the caller to a named conference room. Multiple callers joining the same room name are bridged together into a group call. If the room does not exist, Vobiz creates it automatically.

The room name is the element's text content (case-sensitive). `Conference` takes no child elements. Because the caller stays in the room until they leave or the conference ends, any elements placed after `<Conference>` run only once this participant exits.

## Quick example

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>You are joining the conference now.</Speak>
    <Conference
        startConferenceOnEnter="true"
        endConferenceOnExit="false"
        callbackUrl="https://yourapp.com/conference-events">
        MyConferenceRoom
    </Conference>
</Response>
```

## Next steps

* [Attributes](/docs/xml/conference/attributes) - Full reference for every Conference element attribute.
* [Conference Callbacks](/docs/xml/conference/conference-callbacks) - Participant enter and exit callbacks, plus wait-audio request fields.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.