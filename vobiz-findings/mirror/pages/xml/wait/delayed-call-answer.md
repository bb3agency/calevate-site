> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Delayed call answer

> Example of the Vobiz Wait XML element - demonstrates how to delay answering an inbound call by 10 seconds before any other XML verb executes.

This example demonstrates how to wait for 10 seconds before accepting a call.

## Example

### Response

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Wait length="3"/>
    <Speak>Hello!</Speak>
</Response>
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.