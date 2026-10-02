> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Speak text on calls

> Convert text to speech and play it into active Vobiz calls using the built-in TTS engine with 29-language support and selectable voices.

The Speak Text API uses Vobiz's text-to-speech (TTS) engine to convert written text into spoken audio during ongoing calls. Deliver dynamic messages, notifications, or instructions without pre-recording audio files. Supports 29 languages and multiple voices for global reach.

<Info>
  **Supported:** 29 languages with WOMAN and MAN voices (availability varies by language). Default is English (US) with WOMAN voice.
</Info>

## Key features

<CardGroup cols={2}>
  <Card title="29 languages" icon="globe">
    English, Spanish, French, German, Chinese, Japanese, and more major global languages.
  </Card>

  <Card title="Multiple voices" icon="microphone">
    Choose between WOMAN and MAN voices for most languages.
  </Card>

  <Card title="Dynamic content" icon="wand-sparkles">
    Generate speech on-the-fly without pre-recording - perfect for personalized messages.
  </Card>

  <Card title="Call leg selection" icon="git-fork">
    Choose which participants hear the speech: caller, callee, or both.
  </Card>

  <Card title="Loop support" icon="repeat">
    Repeat text indefinitely for continuous notifications or prompts.
  </Card>

  <Card title="Audio mixing" icon="sliders">
    Mix speech with call audio or mute participants during playback.
  </Card>
</CardGroup>

## Available operations

<CardGroup cols={2}>
  <Card title="Speak text" icon="message-square" href="/docs/call/speak-text/speak-text">
    `POST` - Convert text to speech and play it during an active call with language and voice options.
  </Card>

  <Card title="Stop speaking" icon="circle-stop" href="/docs/call/speak-text/stop-speak">
    `DELETE` - Stop text-to-speech currently being spoken on a call.
  </Card>
</CardGroup>

## Common use cases

* **Dynamic IVR menus** - Generate menu options and prompts based on customer data or time of day.
* **Personalized greetings** - Welcome callers by name or deliver customized messages based on caller ID.
* **Queue updates** - Announce queue position, wait times, or estimated callback times dynamically.
* **Multi-language support** - Deliver messages in the caller's preferred language for global support.
* **Real-time notifications** - Deliver account balances, order statuses, or appointment confirmations on-demand.

## Best practices

<Tip>
  **Keep text concise** - Short, clear messages are easier to understand. Break long content into multiple segments if needed.
</Tip>

<Tip>
  **Use proper punctuation** - Punctuation affects speech pacing and tone. Use periods, commas, and question marks for natural-sounding speech.
</Tip>

<Note>
  **Avoid special characters** - Emojis and special symbols may not be pronounced correctly. Use plain text for best results.
</Note>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.