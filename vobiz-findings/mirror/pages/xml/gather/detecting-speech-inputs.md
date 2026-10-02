> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Detecting speech inputs

> Gather's automatic speech recognition (ASR) on Vobiz accepts spoken input as well as DTMF - configure language, hints, and timeout per gather call.

Gather's automatic speech recognition (ASR) feature is ideal for accepting both unstructured and structured speech input from users. Structured inputs, in the form of keywords and commands, are suited for use cases that have a finite set of distinct operations for users to choose from, such as interactive voice response (IVR). Adding speech detection to DTMF-driven IVR menus can improve conversions by offering users an easier alternative to navigate through menus, as in this first example.

## Examples

### Structured input with DTMF and speech

This menu accepts **either** a key press **or** a spoken command. `inputType="dtmf speech"` listens for both, and the input detected first is relayed to the action URL. The `hints` attribute biases the recognizer toward the exact phrases you expect, and `speechModel="command_and_search"` is tuned for short commands like these.

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="https://your-domain.com/gather/menu"
            method="POST"
            inputType="dtmf speech"
            numDigits="1"
            speechModel="command_and_search"
            hints="New Appointment, Cancel Appointment"
            language="en-US"
            executionTimeout="15"
            speechEndTimeout="auto">
        <Speak>Press 1 or say New Appointment to schedule an appointment. Press 2 or say Cancel Appointment to cancel an existing appointment.</Speak>
    </Gather>
    <Speak>We didn't receive your input. Goodbye!</Speak>
    <Hangup/>
</Response>
```

On the action URL, read `InputType` to see what was detected, then branch on `Digits` (for `dtmf`) or `Speech` (for `speech`):

```text Action URL parameters theme={null}
InputType=speech
Speech=New Appointment
SpeechConfidenceScore=0.92
Digits=
```

### Conversational AI with speech input

Real-time transcription of fuzzy inputs such as complete sentences, on the other hand, helps to build conversational AI-driven experiences. Here `inputType="speech"` collects free-form speech, and `interimSpeechResultsCallback` streams partial transcripts to your server as the caller talks - useful for low-latency AI agents.

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="https://your-domain.com/gather/conversation"
            method="POST"
            inputType="speech"
            speechModel="default"
            language="en-US"
            executionTimeout="30"
            speechEndTimeout="auto"
            interimSpeechResultsCallback="https://your-domain.com/gather/interim"
            profanityFilter="true">
        <Speak>Thanks for calling. How can I help you today?</Speak>
    </Gather>
    <Speak>Sorry, I didn't catch that. Let me connect you to an agent.</Speak>
    <Redirect>https://your-domain.com/gather/transfer</Redirect>
</Response>
```

An easy way to build AI conversational interfaces is by passing the transcribed speech received through the Gather XML element to AI chatbot platforms such as Google Dialogflow for NLP-based intent extraction. Also read about how the Vobiz [Speak XML element's SSML engine](/docs/xml/speak/ssml) can be used to make your bot's responses sound natural.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.