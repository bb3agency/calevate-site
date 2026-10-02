> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Conference recording

> Start and stop Vobiz conference recordings in MP3 or WAV format and handle asynchronous API responses.

Conference recording lets you capture conference audio for compliance, training, or archival purposes. Use the recording endpoints to start and stop capture while a conference is active.

<Info>
  Recording captures the conference audio mix until you send a stop request.
</Info>

## Recording features

<CardGroup cols={2}>
  <Card title="Conference audio mix" icon="microphone">
    Record all conference participants in a single mixed audio file.
  </Card>

  <Card title="Asynchronous start" icon="clock">
    Vobiz queues the start operation and returns an API request identifier.
  </Card>

  <Card title="File formats" icon="file-audio">
    Choose MP3 (smaller) or WAV (higher quality) for your recording output.
  </Card>

  <Card title="Explicit stop" icon="circle-stop">
    Stop media capture with a `DELETE` request and a `204 No Content` response.
  </Card>
</CardGroup>

## Available operations

<CardGroup cols={2}>
  <Card title="Start recording" icon="circle-record" href="/docs/conference/recording/start-recording">
    `POST` - Queue conference recording with an optional MP3 or WAV format setting.
  </Card>

  <Card title="Stop recording" icon="circle-stop" href="/docs/conference/recording/stop-recording">
    `DELETE` - Stop an active conference recording. The response does not include a recording URL.
  </Card>
</CardGroup>

## Best practices

<Warning>
  **Legal compliance** - Ensure you have consent from all participants before recording. Laws vary by jurisdiction. Consider playing an announcement when recording starts.
</Warning>

<Tip>
  **File format** - Use `file_format` to request MP3 or WAV. MP3 is the default.
</Tip>

<Note>
  **Response handling** - The start response does not include a recording ID or download URL. Callback delivery and recording retrieval are not currently guaranteed by this flow.
</Note>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.