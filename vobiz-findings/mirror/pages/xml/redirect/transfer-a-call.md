> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Transfer a call

> Use the Vobiz Redirect XML element after a Speak verb to transfer control of a call to a different URL that returns fresh XML for the next flow step.

In this example, we have a Redirect element after a Speak element. When the Speak element finishes, the Redirect element executes, and Vobiz processes the call based on the XML returned from the Redirect element.

## Example Request

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>Please wait while you call is being transferred.</Speak>
    <Redirect>https://your-domain.com/redirect/</Redirect>
</Response>
```

## Response

To connect the incoming call to a different number, you should return the section example's XML from the Redirect URL.

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Dial>
        <Number>12025551111</Number>
    </Dial>
</Response>
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.