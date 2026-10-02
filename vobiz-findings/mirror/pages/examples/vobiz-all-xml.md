> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bare-metal XML WebSocket

> Build a real-time AI voice agent on Vobiz using only the XML WebSocket streaming primitive - no LiveKit, no Pipecat, no third-party SDK required.

Build a real-time AI voice agent using only Vobiz XML WebSocket streaming - no LiveKit, no Pipecat, no third-party SDK.

<Card title="View on GitHub" icon="github" href="https://github.com/vobiz-ai/Vobiz-All-XML">
  Clone and run the full working example
</Card>

## Getting started

```bash theme={null}
git clone https://github.com/vobiz-ai/Vobiz-All-XML.git
cd Vobiz-All-XML
pip install -r requirements.txt
python server.py
```

## Overview

This example shows the lowest-level integration possible with Vobiz - raw WebSocket audio frames, manual VAD, direct STT/LLM/TTS API calls, and base64 audio encoding back to Vobiz. Use this when you need maximum control and minimum latency with no intermediary layers.

## Architecture

```text theme={null}
Caller → Vobiz SIP
              ↓
    XML: <Response><Connect><Stream url="wss://your-server/ws"/></Connect></Response>
              ↓
    FastAPI WebSocket endpoint
              ↓
    JSON event parsing → base64 decode → G.711 μ-law bytes
              ↓
    Deepgram streaming STT WebSocket (speech → text)
              ↓
    OpenAI ChatCompletions (text → response tokens)
              ↓
    ElevenLabs / OpenAI TTS (tokens → audio bytes)
              ↓
    base64 encode → JSON → WebSocket → Vobiz → Caller
```

## How it works

<Steps>
  <Step title="XML routing">
    When an inbound call hits your FastAPI webhook, respond with Vobiz XML instructing Vobiz to open a bidirectional WebSocket to your server.
  </Step>

  <Step title="Audio frame parsing">
    Vobiz sends JSON frames containing base64-encoded G.711 μ-law audio. Decode these frames into raw byte streams.
  </Step>

  <Step title="Streaming STT">
    Forward raw audio bytes to Deepgram's streaming WebSocket for real-time transcription. As words are recognized, stream them to the LLM.
  </Step>

  <Step title="LLM response">
    Send the transcription to OpenAI's ChatCompletions API. Response tokens stream back as they are generated.
  </Step>

  <Step title="TTS and playback">
    Synthesize tokens using a TTS engine (ElevenLabs or OpenAI). Base64-encode the resulting audio and send it back over the WebSocket to Vobiz, which plays it to the caller.
  </Step>
</Steps>

## Vobiz XML hook

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="wss://your-server.com/ws" />
  </Connect>
</Response>
```

## When to use this

| Use case | Recommendation |
| - | - |
| Maximum latency control | ✅ This example |
| Rapid prototyping | Use LiveKit or Pipecat examples |
| Custom audio processing | ✅ This example |
| Production-ready pipeline | Use LiveKit or Pipecat examples |

## Environment variables

```bash .env theme={null}
DEEPGRAM_API_KEY=your-deepgram-key
OPENAI_API_KEY=sk-...
ELEVENLABS_API_KEY=your-elevenlabs-key
HTTP_PORT=8000
PUBLIC_URL=https://your-server.com
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.