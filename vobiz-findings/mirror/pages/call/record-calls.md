> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Record calls

> Record specific portions of active Vobiz calls with mp3 or wav format, optional speech-to-text transcription, and completion callback delivery.

The Record endpoint lets you start and stop recording specific portions of an active call. Create multiple recordings on the same call, choose audio formats, and enable automated transcription for compliance and quality assurance.

<Warning>
  Always comply with local recording consent laws and inform participants when calls are being recorded.
</Warning>

## Key features

<CardGroup cols={2}>
  <Card title="Multiple recordings" icon="layers">
    Create multiple recordings on the same call to capture specific portions or conversations.
  </Card>

  <Card title="Format options" icon="file-audio">
    Choose between MP3 and WAV. MP3 files are smaller and recommended for most use cases.
  </Card>

  <Card title="Auto transcription" icon="captions">
    Enable automated transcription with turnaround under 5 minutes for supported durations.
  </Card>

  <Card title="Channel options" icon="audio-waveform">
    Record in mono or stereo. Stereo separates caller and callee into left/right channels.
  </Card>

  <Card title="Completion callbacks" icon="webhook">
    Receive HTTP callbacks when recordings complete with URLs to download the audio files.
  </Card>

  <Card title="Time limits" icon="timer">
    Set maximum recording durations to control file sizes and storage costs.
  </Card>
</CardGroup>

## Available operations

<CardGroup cols={2}>
  <Card title="Start recording" icon="circle-record" href="/docs/call/record-calls/start-recording">
    `POST` - Start recording an active call with customizable format, transcription, and callback options.
  </Card>

  <Card title="Stop recording" icon="circle-stop" href="/docs/call/record-calls/stop-recording">
    `DELETE` - Stop an active recording on a call.
  </Card>
</CardGroup>

## Common use cases

* **Compliance & legal** - Record calls for regulatory compliance, dispute resolution, and legal documentation.
* **Quality assurance** - Monitor customer service quality, agent performance, and script adherence.
* **Training & development** - Use recorded calls for agent training, onboarding, and skill development.
* **Transcription & analysis** - Generate transcripts for sentiment analysis, keyword extraction, and call analytics.
* **Customer records** - Maintain detailed interaction history for CRM integration.

## Best practices

<Tip>
  **Use MP3 format** - MP3 files are significantly smaller than WAV, reducing storage costs and bandwidth. Use MP3 unless you need uncompressed audio.
</Tip>

<Note>
  **Transcription limits** - Transcription is available for English calls between 500ms and 4 hours, and under 2GB. Factor these limits into your design.
</Note>

<Tip>
  **Use stereo for multi-party calls** - Stereo recording separates speakers into left/right channels for easier analysis and transcription.
</Tip>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.