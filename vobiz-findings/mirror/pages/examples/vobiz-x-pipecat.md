> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz + Pipecat

> Stream raw Vobiz call audio into a Pipecat AI voice agent pipeline using WebSocket transport - covers trunk setup, Python code, and pipeline wiring.

Stream raw Vobiz audio over WebSocket into a Pipecat AI pipeline - no LiveKit or third-party WebRTC SDK required.

<Card title="View on GitHub" icon="github" href="https://github.com/vobiz-ai/Vobiz-x-Pipecat">
  Clone and run the full working example
</Card>

## Getting started

```bash theme={null}
git clone https://github.com/vobiz-ai/Vobiz-x-Pipecat.git
cd Vobiz-x-Pipecat
pip install -r requirements.txt
python server.py
```

## Overview

When a caller dials in, Vobiz is instructed via XML to open a raw WebSocket to your server. Pipecat's `WebsocketServerTransport` receives the audio stream and routes it through a sequential AI pipeline - VAD → STT → LLM → TTS - before streaming synthesized audio back to the caller.

## Architecture

```text theme={null}
Caller → Vobiz SIP → XML: <Connect><Stream url="wss://your-server/ws"/></Connect>
                                           ↓
                              WebsocketServerTransport (Pipecat)
                                           ↓
                              SileroVADAnalyzer (voice activity)
                                           ↓
                              Deepgram STT (speech → text)
                                           ↓
                              OpenAI LLM (text → response)
                                           ↓
                              ElevenLabs TTS (response → audio)
                                           ↓
                              WebSocket → Vobiz → Caller
```

## How it works

<Steps>
  <Step title="Incoming call">
    When an inbound call triggers your webhook, respond with Vobiz XML instructing Vobiz to open a WebSocket stream to your server.
  </Step>

  <Step title="Pipecat transport">
    `WebsocketServerTransport` receives the raw audio stream. Vobiz sends base64-encoded G.711 μ-law audio frames as JSON events, which Pipecat decodes and buffers automatically.
  </Step>

  <Step title="Sequential pipeline">
    Audio flows through the Pipecat pipeline - VAD detects speech, Deepgram transcribes it, OpenAI generates a response, and ElevenLabs synthesizes speech.
  </Step>

  <Step title="Audio response">
    Encode the synthesized audio and send it back over the WebSocket. Vobiz plays it to the caller in real time.
  </Step>
</Steps>

## Vobiz XML hook

Your webhook endpoint must return this XML when a call arrives:

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="wss://your-server.com/ws" />
  </Connect>
</Response>
```

## Environment variables

```bash .env theme={null}
DEEPGRAM_API_KEY=your-deepgram-key
OPENAI_API_KEY=sk-...
ELEVENLABS_API_KEY=your-elevenlabs-key
HTTP_PORT=8000
PUBLIC_URL=https://your-server.com  # or leave blank to use ngrok
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.