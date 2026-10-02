> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# SSML

> Use Speech Synthesis Markup Language (SSML) inside the Vobiz Speak XML element to control pronunciation, pauses, emphasis, and prosody of TTS output.

SSML supports 27 languages and more than 40 voices, and allows developers to control pronunciation, pitch, and volume.

For more information on SSML, see Getting Started with SSML.

Speak elements with SSML can be nested inside Gather XML element tags.

## Examples

### Basic SSML Example

```xml XML Response theme={null}
<Response>
  <Speak voice="Polly.Amy">
    <prosody rate="medium">
    Hello and welcome to the Vobiz text-to-speech engine.
    <break/>
    <break/>
    We're now testing the
    <say-as interpret-as="spell-out">SSML</say-as>
    feature.
    </prosody>
  </Speak>
</Response>
```

### SSML with Gather

```xml XML Response theme={null}
<Response>
  <Gather numDigits="1" playBeep="true">
  <Speak voice="Polly.Salli">
  <prosody rate="fast">
  Please press 1 to proceed.
  <break/>
  <break/>
  We're now testing the
  <say-as interpret-as="spell-out">SSML</say-as>
  feature.
  </prosody>
  </Speak>
  </Gather>
</Response>
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.