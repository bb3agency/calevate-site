> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Machine detection

> Use the silence parameter on the Vobiz Wait element with machine_detection to distinguish a human pickup from voicemail before continuing the call flow.

You can use the silence parameter in conjunction with the machine\_detection feature of the Call API to enable your XML to detect whether a call is answered by voice mail. When silence is set to true, as soon as the voice mail finishes speaking, and there is silence for minSilence milliseconds, the next element in the XML is processed, without waiting for the whole period of length seconds to pass.

## Example

### Response

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Wait length="5" silence="true" minSilence="2000"/>
</Response>
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.