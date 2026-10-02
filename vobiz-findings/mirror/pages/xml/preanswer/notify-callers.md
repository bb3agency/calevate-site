> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Notify callers

> Use the Vobiz PreAnswer XML element to notify the caller that the current call costs $2 a minute before fully answering and billing the call.

This example notifies the caller that the cost of the current call is \$2 a minute.

## Example Request

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <PreAnswer>
        <Speak>This call will cost you $2 a minute.</Speak>
    </PreAnswer>
    <Speak>Hey, thanks for dropping by.</Speak>
</Response>
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.