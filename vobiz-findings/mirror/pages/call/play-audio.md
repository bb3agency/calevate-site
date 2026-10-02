> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Play audio on calls

> Play audio files into active Vobiz calls for hold music, IVR prompts, announcements, and dynamic in-call media without interrupting other legs.

The Play Audio API lets you play audio files to participants in an ongoing call. Common uses include hold music, automated notifications, IVR prompts, and announcements while maintaining the call connection.

<Info>
  **Supported formats:** Vobiz supports `.mp3` and `.wav` audio files. Files must be accessible via public HTTP/HTTPS URLs.
</Info>

## Key features

<CardGroup cols={2}>
  <Card title="Multiple audio files" icon="list-music">
    Play multiple audio files in sequence by providing comma-separated URLs.
  </Card>

  <Card title="Call leg selection" icon="git-fork">
    Choose which participants hear the audio: caller (A leg), callee (B leg), or both.
  </Card>

  <Card title="Loop playback" icon="repeat">
    Play audio indefinitely for hold music or continuous announcements.
  </Card>

  <Card title="Audio mixing" icon="sliders">
    Mix playback with call audio, or mute participants during playback.
  </Card>

  <Card title="Duration control" icon="timer">
    Limit playback duration to control costs and user experience.
  </Card>

  <Card title="Stop anytime" icon="circle-stop">
    Stop audio playback programmatically whenever needed.
  </Card>
</CardGroup>

## Available operations

<CardGroup cols={2}>
  <Card title="Play audio" icon="play" href="/docs/call/play-audio/play-audio">
    `POST` - Play an audio file or multiple files during an active call.
  </Card>

  <Card title="Stop audio" icon="square" href="/docs/call/play-audio/stop-audio">
    `DELETE` - Stop audio currently being played on a call.
  </Card>
</CardGroup>

## Common use cases

* **Hold music** - Play music while customers wait on hold or during call transfers.
* **IVR prompts** - Play menu options, instructions, or navigation prompts in interactive voice systems.
* **Announcements** - Deliver pre-recorded announcements, promotions, or important information.
* **Queue notifications** - Inform callers of their position in queue or estimated wait time.
* **Call recording disclaimer** - Play legal disclaimers about call recording or monitoring.

## Best practices

<Tip>
  **Use MP3 for efficiency** - MP3 files stream faster and use less bandwidth than WAV. Convert your audio to MP3 for better performance.
</Tip>

<Tip>
  **Host on a CDN** - Host audio files on a CDN or reliable HTTPS hosting for fast, secure delivery.
</Tip>

<Note>
  **Optimize audio length** - Keep files concise. Use the `length` parameter to limit playback duration and avoid lengthy hold times.
</Note>

<Warning>
  **Mix audio thoughtfully** - Set `mix=false` when playing important announcements so participants hear them clearly without conversation interference.
</Warning>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.