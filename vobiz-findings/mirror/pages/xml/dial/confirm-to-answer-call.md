> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Answer confirmation settings

> Configure confirmSound and confirmKey on the Vobiz Dial element while confirmKey connection enforcement remains unverified.

Use `confirmSound` to provide audio instructions after a B-leg answers. You can configure `confirmKey` with the digit mentioned in those instructions.

<Warning>
  `confirmKey` enforcement is currently unverified. Do not rely on it as a security, human-verification, or connection-acceptance gate until Vobiz confirms the behavior.
</Warning>

Vobiz requests the confirmSound URL using the POST HTTP method for a valid Play, Speak, or a Wait XML element. To play a message asking the recipient to input a DTMF tone to connect the call, return the second XML example.

## Example

### Response

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Dial confirmSound="https://your-domain.com/confirm_sound/" confirmKey="5">
        <Number>12025551111</Number>
        <Number>12025552222</Number>
        <Number>12025553333</Number>
    </Dial>
</Response>
```

This example configures `5` as the confirmation digit. It does not guarantee that Vobiz will withhold the connection when the recipient does not press it.

Return the following XML to play a message:

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>Enter the digit 5 to connect the call</Speak>
</Response>
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.