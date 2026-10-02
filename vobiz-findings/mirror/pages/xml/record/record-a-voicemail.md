> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Record a voicemail

> This example shows how to record a voicemail message. The recording will stop when the caller presses the star key or after 30 seconds, whichever comes first.

This example shows how to record a voicemail message. The recording will stop when the caller presses the star key or after 30 seconds, whichever comes first.

## Example

In this example, the caller hears a message asking them to leave a voicemail. After the beep, the recording begins. The recording will stop when the caller presses the star key (\*) or after 30 seconds. If no recording is received, the caller will hear "Recording not received."

### XML Response

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>Please leave a message after the beep.</Speak>
    <Record action="https://your-domain.com/recording" maxLength="60" playBeep="true"/>
</Response>
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.