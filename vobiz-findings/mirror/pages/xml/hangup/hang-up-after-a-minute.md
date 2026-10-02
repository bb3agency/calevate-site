> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Hang up call after a minute

> Schedule a hangup on a Vobiz call after one minute using the Hangup XML element - example plays a final message before the call is terminated.

This example shows how to schedule a hangup for a call after a minute while playing a message on the call.

## Example

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>This call will be hung up after a minute</Speak>
    <Hangup schedule="60"/>
</Response>
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.