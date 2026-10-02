> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Pipecat integration

> Pipecat connects to Vobiz SIP trunking to power AI voice pipelines on real phone calls - WebSocket streaming and SIP trunk setup across 130+ countries.

This integration combines Vobiz telephony with the [Pipecat](https://pipecat.ai) voice agent framework to build intelligent AI-powered phone calls.

<iframe width="100%" height="420" src="https://www.youtube.com/embed/4ae-Lgg2gbU" title="Pipecat + Vobiz Integration Tutorial" frameBorder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowFullScreen style={{ borderRadius: "12px", marginTop: "1rem", marginBottom: "1rem" }} />

## Overview

**What you'll build:** An outbound calling system with real-time AI conversations powered by OpenAI (STT → LLM → TTS), automatic call recording, and bidirectional audio streaming.

Three moving parts do all the work:

| Part | What it is | Responsibility |
| - | - | - |
| `server.py` | Your FastAPI app | Places the call, serves the answer XML, accepts the WebSocket |
| `bot.py` | The Pipecat pipeline | Runs STT → LLM → TTS for the duration of one call |
| `pipecat-vobiz` | `VobizFrameSerializer` | Translates between Vobiz's JSON/base64 WebSocket protocol and Pipecat audio frames |

### Call flow

<div className="not-prose my-8 rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
  <div className="flex flex-wrap items-center gap-2 px-5 py-3 border-b border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/40">
    <span className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400 mr-1">Actors</span>
    <span className="px-2 py-0.5 rounded text-[12px] font-medium bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300">You</span>
    <span className="px-2 py-0.5 rounded text-[12px] font-medium bg-blue-50 dark:bg-blue-950/60 border border-blue-200 dark:border-blue-900 text-blue-800 dark:text-blue-300">server.py</span>
    <span className="px-2 py-0.5 rounded text-[12px] font-medium bg-orange-50 dark:bg-orange-950/60 border border-orange-200 dark:border-orange-900 text-orange-800 dark:text-orange-300">Vobiz</span>
    <span className="px-2 py-0.5 rounded text-[12px] font-medium bg-purple-50 dark:bg-purple-950/60 border border-purple-200 dark:border-purple-900 text-purple-800 dark:text-purple-300">bot.py</span>
    <span className="px-2 py-0.5 rounded text-[12px] font-medium bg-emerald-50 dark:bg-emerald-950/60 border border-emerald-200 dark:border-emerald-900 text-emerald-800 dark:text-emerald-300">Customer</span>
  </div>

  <div className="px-5 py-2 bg-gray-100/70 dark:bg-gray-800/50 text-[11px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">Phase 1 · Placing the call</div>

  <div className="px-5 pt-5">
    <div className="flex gap-4">
      <div className="flex flex-col items-center shrink-0">
        <div className="w-7 h-7 rounded-full bg-orange-500 text-white text-[11px] font-bold flex items-center justify-center">1</div>

        <div className="w-px grow bg-gray-200 dark:bg-gray-700 mt-1" />
      </div>

      <div className="pb-5 min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap text-[13px] mb-1.5">
          <span className="px-2 py-0.5 rounded font-medium bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300">You</span>
          <span className="text-gray-400">→</span>
          <span className="px-2 py-0.5 rounded font-medium bg-blue-50 dark:bg-blue-950/60 border border-blue-200 dark:border-blue-900 text-blue-800 dark:text-blue-300">server.py</span>
        </div>

        <div className="text-[13px] text-gray-600 dark:text-gray-400">Trigger the call.</div>

        <pre className="mt-2 text-[12px] leading-relaxed overflow-x-auto rounded-lg bg-gray-900 dark:bg-black/60 text-gray-100 p-3">
          <code>
            {`POST /start   { "phone_number": "+91…" }`}
          </code>
        </pre>
      </div>
    </div>

    <div className="flex gap-4">
      <div className="flex flex-col items-center shrink-0">
        <div className="w-7 h-7 rounded-full bg-orange-500 text-white text-[11px] font-bold flex items-center justify-center">2</div>

        <div className="w-px grow bg-gray-200 dark:bg-gray-700 mt-1" />
      </div>

      <div className="pb-5 min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap text-[13px] mb-1.5">
          <span className="px-2 py-0.5 rounded font-medium bg-blue-50 dark:bg-blue-950/60 border border-blue-200 dark:border-blue-900 text-blue-800 dark:text-blue-300">server.py</span>
          <span className="text-gray-400">→</span>
          <span className="px-2 py-0.5 rounded font-medium bg-orange-50 dark:bg-orange-950/60 border border-orange-200 dark:border-orange-900 text-orange-800 dark:text-orange-300">Vobiz</span>
        </div>

        <div className="text-[13px] text-gray-600 dark:text-gray-400">Server calls the Vobiz Call API, filling <code className="text-[12px]">answer\_url</code> from <code className="text-[12px]">PUBLIC\_URL</code>.</div>

        <pre className="mt-2 text-[12px] leading-relaxed overflow-x-auto rounded-lg bg-gray-900 dark:bg-black/60 text-gray-100 p-3">
          <code>
            {`POST /api/v1/Account/{AUTH_ID}/Call/
                        { from, to, answer_url, answer_method }`}
          </code>
        </pre>
      </div>
    </div>

    <div className="flex gap-4">
      <div className="flex flex-col items-center shrink-0">
        <div className="w-7 h-7 rounded-full bg-orange-500 text-white text-[11px] font-bold flex items-center justify-center">3</div>

        <div className="w-px grow bg-gray-200 dark:bg-gray-700 mt-1" />
      </div>

      <div className="pb-5 min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap text-[13px] mb-1.5">
          <span className="px-2 py-0.5 rounded font-medium bg-orange-50 dark:bg-orange-950/60 border border-orange-200 dark:border-orange-900 text-orange-800 dark:text-orange-300">Vobiz</span>
          <span className="text-gray-400">→</span>
          <span className="px-2 py-0.5 rounded font-medium bg-blue-50 dark:bg-blue-950/60 border border-blue-200 dark:border-blue-900 text-blue-800 dark:text-blue-300">server.py</span>
        </div>

        <div className="text-[13px] text-gray-600 dark:text-gray-400">Call accepted.</div>

        <pre className="mt-2 text-[12px] leading-relaxed overflow-x-auto rounded-lg bg-gray-900 dark:bg-black/60 text-gray-100 p-3">
          <code>
            {`201 Created   { "request_uuid": "…" }`}
          </code>
        </pre>
      </div>
    </div>
  </div>

  <div className="px-5 py-2 bg-gray-100/70 dark:bg-gray-800/50 text-[11px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">Phase 2 · Answer & instructions</div>

  <div className="px-5 pt-5">
    <div className="flex gap-4">
      <div className="flex flex-col items-center shrink-0">
        <div className="w-7 h-7 rounded-full bg-orange-500 text-white text-[11px] font-bold flex items-center justify-center">4</div>

        <div className="w-px grow bg-gray-200 dark:bg-gray-700 mt-1" />
      </div>

      <div className="pb-5 min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap text-[13px] mb-1.5">
          <span className="px-2 py-0.5 rounded font-medium bg-orange-50 dark:bg-orange-950/60 border border-orange-200 dark:border-orange-900 text-orange-800 dark:text-orange-300">Vobiz</span>
          <span className="text-gray-400">→</span>
          <span className="px-2 py-0.5 rounded font-medium bg-emerald-50 dark:bg-emerald-950/60 border border-emerald-200 dark:border-emerald-900 text-emerald-800 dark:text-emerald-300">Customer</span>
        </div>

        <div className="text-[13px] text-gray-600 dark:text-gray-400">Vobiz dials out over PSTN — the phone rings, then the customer answers.</div>
      </div>
    </div>

    <div className="flex gap-4">
      <div className="flex flex-col items-center shrink-0">
        <div className="w-7 h-7 rounded-full bg-orange-500 text-white text-[11px] font-bold flex items-center justify-center">5</div>

        <div className="w-px grow bg-gray-200 dark:bg-gray-700 mt-1" />
      </div>

      <div className="pb-5 min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap text-[13px] mb-1.5">
          <span className="px-2 py-0.5 rounded font-medium bg-orange-50 dark:bg-orange-950/60 border border-orange-200 dark:border-orange-900 text-orange-800 dark:text-orange-300">Vobiz</span>
          <span className="text-gray-400">→</span>
          <span className="px-2 py-0.5 rounded font-medium bg-blue-50 dark:bg-blue-950/60 border border-blue-200 dark:border-blue-900 text-blue-800 dark:text-blue-300">server.py</span>
        </div>

        <div className="text-[13px] text-gray-600 dark:text-gray-400">On answer, Vobiz asks your server what to do.</div>

        <pre className="mt-2 text-[12px] leading-relaxed overflow-x-auto rounded-lg bg-gray-900 dark:bg-black/60 text-gray-100 p-3">
          <code>
            {`POST {PUBLIC_URL}/answer`}
          </code>
        </pre>
      </div>
    </div>

    <div className="flex gap-4">
      <div className="flex flex-col items-center shrink-0">
        <div className="w-7 h-7 rounded-full bg-orange-500 text-white text-[11px] font-bold flex items-center justify-center">6</div>

        <div className="w-px grow bg-gray-200 dark:bg-gray-700 mt-1" />
      </div>

      <div className="pb-5 min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap text-[13px] mb-1.5">
          <span className="px-2 py-0.5 rounded font-medium bg-blue-50 dark:bg-blue-950/60 border border-blue-200 dark:border-blue-900 text-blue-800 dark:text-blue-300">server.py</span>
          <span className="text-gray-400">→</span>
          <span className="px-2 py-0.5 rounded font-medium bg-orange-50 dark:bg-orange-950/60 border border-orange-200 dark:border-orange-900 text-orange-800 dark:text-orange-300">Vobiz</span>
        </div>

        <div className="text-[13px] text-gray-600 dark:text-gray-400">Returns VobizXML: record the session, and stream the caller’s audio to your bot.</div>

        <pre className="mt-2 text-[12px] leading-relaxed overflow-x-auto rounded-lg bg-gray-900 dark:bg-black/60 text-gray-100 p-3">
          <code>
            {`200 application/xml

                        <Record … />
                        <Stream bidirectional="true" audioTrack="inbound"
                              contentType="audio/x-mulaw;rate=8000"
                              keepCallAlive="true">wss://…/ws</Stream>`}
          </code>
        </pre>
      </div>
    </div>
  </div>

  <div className="px-5 py-2 bg-gray-100/70 dark:bg-gray-800/50 text-[11px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">Phase 3 · The live conversation</div>

  <div className="px-5 pt-5">
    <div className="flex gap-4">
      <div className="flex flex-col items-center shrink-0">
        <div className="w-7 h-7 rounded-full bg-purple-500 text-white text-[11px] font-bold flex items-center justify-center">7</div>

        <div className="w-px grow bg-gray-200 dark:bg-gray-700 mt-1" />
      </div>

      <div className="pb-5 min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap text-[13px] mb-1.5">
          <span className="px-2 py-0.5 rounded font-medium bg-orange-50 dark:bg-orange-950/60 border border-orange-200 dark:border-orange-900 text-orange-800 dark:text-orange-300">Vobiz</span>
          <span className="text-gray-400">→</span>
          <span className="px-2 py-0.5 rounded font-medium bg-purple-50 dark:bg-purple-950/60 border border-purple-200 dark:border-purple-900 text-purple-800 dark:text-purple-300">bot.py</span>
        </div>

        <div className="text-[13px] text-gray-600 dark:text-gray-400">WebSocket upgrade on <code className="text-[12px]">/ws</code>, then a single <code className="text-[12px]">start</code> event carrying the IDs and the negotiated audio format.</div>

        <pre className="mt-2 text-[12px] leading-relaxed overflow-x-auto rounded-lg bg-gray-900 dark:bg-black/60 text-gray-100 p-3">
          <code>
            {`{ "event": "start",
                        "start": { "callId": "…", "streamId": "…",
                                   "mediaFormat": { "encoding": "audio/x-mulaw",
                                                    "sampleRate": 8000 } } }`}
          </code>
        </pre>

        <div className="mt-2 text-[12px] text-gray-500 dark:text-gray-400 border-l-2 border-purple-300 dark:border-purple-800 pl-3"><code className="text-[12px]">parse\_vobiz\_start()</code> reads this before the transport is built. <strong>mediaFormat is authoritative</strong> — prefer it over your own <code className="text-[12px]">contentType</code>.</div>
      </div>
    </div>

    <div className="flex gap-4">
      <div className="flex flex-col items-center shrink-0">
        <div className="w-7 h-7 rounded-full bg-purple-500 text-white text-[11px] font-bold flex items-center justify-center">8</div>

        <div className="w-px grow bg-gray-200 dark:bg-gray-700 mt-1" />
      </div>

      <div className="pb-5 min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap text-[13px] mb-1.5">
          <span className="px-2 py-0.5 rounded font-medium bg-orange-50 dark:bg-orange-950/60 border border-orange-200 dark:border-orange-900 text-orange-800 dark:text-orange-300">Vobiz</span>
          <span className="text-gray-400">↔</span>
          <span className="px-2 py-0.5 rounded font-medium bg-purple-50 dark:bg-purple-950/60 border border-purple-200 dark:border-purple-900 text-purple-800 dark:text-purple-300">bot.py</span>
          <span className="ml-1 px-1.5 py-0.5 rounded text-[11px] bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400">bidirectional · \~20 ms frames</span>
        </div>

        <div className="text-[13px] text-gray-600 dark:text-gray-400">Audio flows both ways as base64 <code className="text-[12px]">media</code> events.</div>

        <pre className="mt-2 text-[12px] leading-relaxed overflow-x-auto rounded-lg bg-gray-900 dark:bg-black/60 text-gray-100 p-3">
          <code>
            {`{ "event": "media", "media": { "payload": "<base64 μ-law>" } }`}
          </code>
        </pre>

        <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[12px]">
          <span className="px-2 py-1 rounded bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 font-mono">VobizFrameSerializer</span>
          <span className="text-gray-400">→</span>
          <span className="px-2 py-1 rounded bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300">Silero VAD</span>
          <span className="text-gray-400">→</span>
          <span className="px-2 py-1 rounded bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300">OpenAI STT</span>
          <span className="text-gray-400">→</span>
          <span className="px-2 py-1 rounded bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300">GPT</span>
          <span className="text-gray-400">→</span>
          <span className="px-2 py-1 rounded bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300">OpenAI TTS</span>
          <span className="text-gray-400">→</span>
          <span className="px-2 py-1 rounded bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 font-mono">back to Vobiz</span>
        </div>
      </div>
    </div>
  </div>

  <div className="px-5 py-2 bg-gray-100/70 dark:bg-gray-800/50 text-[11px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">Phase 4 · Teardown & recording</div>

  <div className="px-5 pt-5 pb-1">
    <div className="flex gap-4">
      <div className="flex flex-col items-center shrink-0">
        <div className="w-7 h-7 rounded-full bg-gray-400 dark:bg-gray-600 text-white text-[11px] font-bold flex items-center justify-center">9</div>

        <div className="w-px grow bg-gray-200 dark:bg-gray-700 mt-1" />
      </div>

      <div className="pb-5 min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap text-[13px] mb-1.5">
          <span className="px-2 py-0.5 rounded font-medium bg-emerald-50 dark:bg-emerald-950/60 border border-emerald-200 dark:border-emerald-900 text-emerald-800 dark:text-emerald-300">Customer</span>
          <span className="text-gray-400">hangs up →</span>
          <span className="px-2 py-0.5 rounded font-medium bg-orange-50 dark:bg-orange-950/60 border border-orange-200 dark:border-orange-900 text-orange-800 dark:text-orange-300">Vobiz</span>
          <span className="text-gray-400">→</span>
          <span className="px-2 py-0.5 rounded font-medium bg-purple-50 dark:bg-purple-950/60 border border-purple-200 dark:border-purple-900 text-purple-800 dark:text-purple-300">bot.py</span>
        </div>

        <pre className="mt-1 text-[12px] leading-relaxed overflow-x-auto rounded-lg bg-gray-900 dark:bg-black/60 text-gray-100 p-3">
          <code>
            {`{ "event": "stop" }`}
          </code>
        </pre>

        <div className="mt-2 text-[12px] text-gray-500 dark:text-gray-400 border-l-2 border-gray-300 dark:border-gray-700 pl-3">With <code className="text-[12px]">auto\_hang\_up=True</code> the serializer also issues a REST hangup, so a bot-initiated end tears the call down cleanly.</div>
      </div>
    </div>

    <div className="flex gap-4">
      <div className="flex flex-col items-center shrink-0">
        <div className="w-7 h-7 rounded-full bg-gray-400 dark:bg-gray-600 text-white text-[11px] font-bold flex items-center justify-center">10</div>
      </div>

      <div className="pb-5 min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap text-[13px] mb-1.5">
          <span className="px-2 py-0.5 rounded font-medium bg-orange-50 dark:bg-orange-950/60 border border-orange-200 dark:border-orange-900 text-orange-800 dark:text-orange-300">Vobiz</span>
          <span className="text-gray-400">→</span>
          <span className="px-2 py-0.5 rounded font-medium bg-blue-50 dark:bg-blue-950/60 border border-blue-200 dark:border-blue-900 text-blue-800 dark:text-blue-300">server.py</span>
        </div>

        <div className="text-[13px] text-gray-600 dark:text-gray-400">Recording callback fires; the helper downloads the file.</div>

        <pre className="mt-2 text-[12px] leading-relaxed overflow-x-auto rounded-lg bg-gray-900 dark:bg-black/60 text-gray-100 p-3">
          <code>
            {`POST /recording-ready   { "RecordUrl": "…", … }
                        → download_recording.py  →  recordings/<recording_id>.mp3`}
          </code>
        </pre>
      </div>
    </div>
  </div>
</div>

<Note>
  Steps 1–3 are only for **outbound** calls. For inbound calls the flow starts at step 6 — Vobiz calls your `/answer` URL directly. See [Receiving inbound calls](#receiving-inbound-calls).
</Note>

## Features

<CardGroup cols={2}>
  <Card title="AI Voice Conversations" icon="robot">
    Natural conversations powered by OpenAI GPT + TTS/STT
  </Card>

  <Card title="Outbound Calling" icon="phone-arrow-up-right">
    Trigger calls via REST API from anywhere
  </Card>

  <Card title="Automatic Recording" icon="microphone">
    All conversations automatically recorded and saved
  </Card>

  <Card title="Real-time Streaming" icon="wave-square">
    Bidirectional audio via WebSockets
  </Card>
</CardGroup>

## Prerequisites

<div className="border border-gray-200 dark:border-gray-800 rounded-xl p-6 mt-4 mb-8">
  <div className="flex flex-col gap-5">
    <div className="flex items-center gap-3">
      <div className="w-5 h-5 rounded bg-[#4ade80] flex items-center justify-center text-white shrink-0">
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="4" d="M5 13l4 4L19 7" />
        </svg>
      </div>

      <div className="text-gray-800 dark:text-gray-200 text-[15px]">**Vobiz Account** with Auth ID and Auth Token → <a href="https://console.vobiz.ai/auth/signup" className="text-primary hover:underline">Sign up</a></div>
    </div>

    <div className="flex items-center gap-3">
      <div className="w-5 h-5 rounded bg-[#4ade80] flex items-center justify-center text-white shrink-0">
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="4" d="M5 13l4 4L19 7" />
        </svg>
      </div>

      <div className="text-gray-800 dark:text-gray-200 text-[15px]">**OpenAI API Key** for LLM, STT, and TTS → <a href="https://platform.openai.com/api-keys" className="text-primary hover:underline">Get API key</a></div>
    </div>

    <div className="flex items-center gap-3">
      <div className="w-5 h-5 rounded bg-[#4ade80] flex items-center justify-center text-white shrink-0">
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="4" d="M5 13l4 4L19 7" />
        </svg>
      </div>

      <div className="text-gray-800 dark:text-gray-200 text-[15px]">**Python 3.11+** installed on your system</div>
    </div>

    <div className="flex items-center gap-3">
      <div className="w-5 h-5 rounded bg-[#4ade80] flex items-center justify-center text-white shrink-0">
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="4" d="M5 13l4 4L19 7" />
        </svg>
      </div>

      <div className="text-gray-800 dark:text-gray-200 text-[15px]">**ngrok** for local development → <a href="https://ngrok.com/download" className="text-primary hover:underline">Download ngrok</a></div>
    </div>
  </div>
</div>

<Warning>
  **Python 3.11 is a hard floor.** `pipecat-ai` 1.x declares `requires-python >=3.11`. On Python 3.10, `pip` does not fail — it silently backtracks and installs an ancient `0.0.x` Pipecat, and then every import in `bot.py` breaks with confusing `ModuleNotFoundError`s. Check with `python --version` before installing.
</Warning>

### Version compatibility

This integration targets the **Pipecat 1.x** API. Versions are pinned in `requirements.txt`:

| Package | Pin | Why |
| - | - | - |
| `pipecat-ai[websocket,openai,silero]` | `>=1.8.1,<1.9` | Pipecat 1.x moved VAD onto `LLMUserAggregatorParams` and introduced `LLMContext`. The 1.8 line is the verified one. |
| `pipecat-vobiz` | `>=0.0.3,<0.1` | 0.0.3 adds L16, multi-rate, `start`-event negotiation and `stop`-event hangup. |
| Python | `>=3.11` | Required by `pipecat-ai` 1.x. |

<Note>
  Pipecat 1.9 and 1.10 are published but are **not** covered by this pin. Widen the upper bound only after re-testing — the serializer contract has changed once already inside 1.x (`FrameSerializer.setup()` took a `StartFrame` before 1.3 and a `FrameProcessorSetup` after).
</Note>

<Note>
  Pipecat 1.x deprecated `pipecat.pipeline.task` in favour of `pipecat.pipeline.worker` (`PipelineTask` → `PipelineWorker`). The old import path still works for all of 1.x and is what this repo uses, but it is scheduled for removal in Pipecat 2.0 — which is why the pin is `<2`.
</Note>

## Installation

<Steps>
  <Step title="Clone the repository">
    ```bash theme={null}
    git clone https://github.com/vobiz-ai/Vobiz-X-Pipecat
    cd Vobiz-X-Pipecat
    ```
  </Step>

  <Step title="Install dependencies">
    ```bash theme={null}
    pip install -r requirements.txt
    ```

    <Note>This installs FastAPI, Pipecat, OpenAI SDK, and other required packages.</Note>
  </Step>

  <Step title="Configure environment">
    The repo ships an `env.example` file. Copy it and fill in your values:

    ```bash theme={null}
    cp env.example .env
    ```

    ```bash .env theme={null}
    # --- Required ---
    OPENAI_API_KEY=sk-...
    VOBIZ_AUTH_ID=MA_XXXXXXXX
    VOBIZ_AUTH_TOKEN=your-token-here
    PUBLIC_URL=https://your-ngrok-url.ngrok-free.app

    # --- Caller ID for outbound ---
    VOBIZ_PHONE_NUMBER=+918065480214

    # --- Wire format (must match the <Stream contentType> server.py emits) ---
    VOBIZ_ENCODING=audio/x-mulaw
    VOBIZ_SAMPLE_RATE=8000
    VOBIZ_L16_ENDIAN=le
    ```

    **Required**

    | Variable | Where to find it |
    | - | - |
    | `OPENAI_API_KEY` | OpenAI Platform → API Keys |
    | `VOBIZ_AUTH_ID` | Vobiz Console → Account Settings |
    | `VOBIZ_AUTH_TOKEN` | Vobiz Console → Account Settings |
    | `PUBLIC_URL` | Your ngrok HTTPS URL (set in Step 2 of Usage) |

    **Optional**

    | Variable | Default | Purpose |
    | - | - | - |
    | `VOBIZ_PHONE_NUMBER` | — | Caller ID for `/start`. Required unless you pass `from_number` in the request body. |
    | `VOBIZ_ENCODING` | `audio/x-mulaw` | Wire encoding. `audio/x-mulaw` or `audio/x-l16`. |
    | `VOBIZ_SAMPLE_RATE` | `8000` | Wire sample rate. `8000` or `16000`. |
    | `VOBIZ_L16_ENDIAN` | `le` | L16 byte order. Ignored for μ-law. See the note below. |
    | `ENABLE_RECORDING` | `true` | Set `false` to omit the `<Record>` element from the answer XML. |
    | `MAX_RECORDING_LENGTH` | `3600` | Recording cap in seconds. |
    | `ENV` | `local` | `local` or `production`. |
    | `VOBIZ_PROD_WS_URL` | — | Required when `ENV=production` — the public `wss://` URL hosting your bot. |
    | `TRANSFER_AGENT_NUMBER` | — | Required only if you use the human-transfer endpoints. |
    | `AGENT_NAME` / `ORGANIZATION_NAME` | — | Used to build the `serviceHost` query param when `ENV=production`. |
    | `DEEPGRAM_API_KEY` | — | Not read by `bot.py` as shipped. Set it only if you swap `OpenAISTTService` for `DeepgramSTTService`. |

    <Warning>
      **`VOBIZ_L16_ENDIAN` only matters for `audio/x-l16`.** RFC 2586 specifies big-endian (network byte order), but some Vobiz accounts transport L16 as **little-endian**. If L16 media frames arrive at the expected size yet STT returns no transcripts, flip this to `le`. Leave the default μ-law encoding and you never hit this.
    </Warning>
  </Step>
</Steps>

## Usage

<Steps>
  <Step title="Start the server">
    ```bash theme={null}
    python server.py
    ```

    The server runs on `http://0.0.0.0:7860`.
  </Step>

  <Step title="Start ngrok">
    In a new terminal, expose your local server:

    ```bash theme={null}
    ngrok http 7860
    ```

    Copy the ngrok URL from the output (for example, `https://abc123.ngrok-free.app`).

    <Warning>
      **Important:** Update `PUBLIC_URL` in your `.env` file with this ngrok URL, then restart the server.
    </Warning>
  </Step>

  <Step title="Make a call">
    There are two ways to trigger an outbound call - pick whichever fits your stack.

    <Tabs>
      <Tab title="Server's /start helper (easiest)">
        The repo exposes `POST /start` on the local server. It wraps the Vobiz Call API and auto-fills `answer_url` from your `PUBLIC_URL`, plus uses `VOBIZ_PHONE_NUMBER` as `from` when set.

        ```bash theme={null}
        curl -X POST http://localhost:7860/start \
          -H "Content-Type: application/json" \
          -d '{ "phone_number": "+919148223344" }'
        ```

        <Warning>
          The field is **`phone_number`**, not `to`. `server.py` returns `400 Missing 'phone_number' in the request body` for anything else.
        </Warning>

        | Field | Required | Purpose |
        | - | - | - |
        | `phone_number` | Yes | The number to dial. |
        | `from_number` | No | Caller ID. Falls back to `VOBIZ_PHONE_NUMBER`; if neither is set the call is rejected with `400`. |
        | `body` | No | Arbitrary JSON. Forwarded to `/answer` as a URL-encoded query param, then base64-encoded onto the WebSocket URL so `bot.py` can read per-call context. |

        Response:

        ```json theme={null}
        { "call_uuid": "…", "status": "call_initiated", "phone_number": "+919148223344" }
        ```
      </Tab>

      <Tab title="Direct Vobiz API">
        ```bash theme={null}
        curl -X POST https://api.vobiz.ai/api/v1/Account/YOUR_AUTH_ID/Call/ \
          -H "X-Auth-ID: YOUR_AUTH_ID" \
          -H "X-Auth-Token: YOUR_AUTH_TOKEN" \
          -H "Content-Type: application/json" \
          -d '{
            "from": "+918011223344",
            "to": "+919148223344",
            "answer_url": "https://your-ngrok-url.ngrok-free.app/answer",
            "answer_method": "POST"
          }'
        ```
      </Tab>
    </Tabs>

    **What happens next:**

    * Phone rings at the `phone_number` you passed
    * When answered, Vobiz requests XML from your server's `/answer` endpoint
    * Server returns `<Record>` + `<Stream>` pointing at `wss://…/ws`
    * Vobiz opens the WebSocket and sends a `start` event, then `media` frames
    * AI assistant speaks and listens (STT → LLM → TTS)
    * On hangup, Vobiz posts the recording URL to `/recording-ready`, which downloads it to `recordings/`
  </Step>
</Steps>

## How the flow works

Everything above is driven by one XML document and one WebSocket protocol. This section is what you need if you are adapting the repo rather than running it as-is.

### The answer XML

`/answer` returns this (with `{PUBLIC_URL}` and the wire format substituted in):

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Record fileFormat="wav" maxLength="3600" recordSession="true"
            callbackUrl="https://your-ngrok-url.ngrok-free.app/recording-ready"
            callbackMethod="POST">
    </Record>
    <Stream bidirectional="true" audioTrack="inbound"
            contentType="audio/x-mulaw;rate=8000" keepCallAlive="true">
        wss://your-ngrok-url.ngrok-free.app/ws
    </Stream>
</Response>
```

Why each attribute matters:

| Attribute | Value | Why |
| - | - | - |
| `bidirectional` | `true` | Lets the bot play TTS audio back to the caller. Without it the stream is listen-only. |
| `audioTrack` | `inbound` | The caller's audio. **Must** be `inbound` when `bidirectional="true"`. |
| `contentType` | `audio/x-mulaw;rate=8000` | Must match what `VobizFrameSerializer` is constructed with. |
| `keepCallAlive` | `true` | Keeps the call up when the stream ends, so `<Record>` can finish and callbacks fire. |

<Warning>
  **`audioTrack="both"` is incompatible with `bidirectional="true"`.** The media server accepts the XML, sends a `start` event, and then never sends audio — a silent failure that looks like a broken bot. Use `audioTrack="inbound"` for any bidirectional stream. To capture both legs, use two separate one-way `<Stream>` elements.
</Warning>

### The WebSocket protocol

Vobiz speaks JSON text frames. `VobizFrameSerializer` handles all of this for you; the shapes are here so you can debug what you see on the wire.

<AccordionGroup>
  <Accordion title="start — sent once, immediately after the upgrade">
    ```json theme={null}
    {
      "event": "start",
      "start": {
        "callId": "…",
        "streamId": "…",
        "mediaFormat": { "encoding": "audio/x-mulaw", "sampleRate": 8000 }
      }
    }
    ```

    `bot.py` reads this with `parse_vobiz_start()` before building the transport, because it carries both the IDs needed for REST hangup and the negotiated audio format.

    <Note>
      **`mediaFormat` is authoritative.** It reflects what the media server actually negotiated. If it differs from the `contentType` you asked for in your `<Stream>` XML, trust this event — the XML is a request, the `start` event is the agreement. The serializer adopts these values automatically and logs a warning on mismatch.
    </Note>
  </Accordion>

  <Accordion title="media — the audio frames, both directions">
    ```json theme={null}
    { "event": "media", "media": { "payload": "<base64-encoded audio>" } }
    ```

    At 8 kHz μ-law this arrives roughly every 20 ms as 160-byte payloads. The serializer base64-decodes, converts μ-law → linear PCM, and resamples to the pipeline rate; outbound TTS makes the same trip in reverse.
  </Accordion>

  <Accordion title="stop — the call is over">
    ```json theme={null}
    { "event": "stop" }
    ```

    With `auto_hang_up=True` the serializer also issues a REST hangup using `call_id` + your auth credentials, so a bot-initiated end tears the call down properly rather than leaving it hanging.
  </Accordion>
</AccordionGroup>

### Sample rates

| Rate | μ-law | L16 | Notes |
| - | - | - | - |
| 8000 | Supported | Supported | Default. Matches the PSTN carrier path — no transcode. |
| 16000 | Supported | Supported | Vobiz transcodes. |
| 24000 | Not reliable | Not reliable | Appears in the protocol, but the media server may accept the XML and then **silently never open the WebSocket**. Avoid. |

### The Pipecat pipeline

`bot.py` builds a standard cascaded pipeline. Two details are specific to Pipecat 1.x and telephony:

```python bot.py theme={null}
context_aggregator = LLMContextAggregatorPair(
    context,
    # Pipecat 1.x: VAD is wired HERE, not on the transport.
    user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
)

transport = FastAPIWebsocketTransport(
    websocket=runner_args.websocket,
    params=FastAPIWebsocketParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        add_wav_header=False,   # CRITICAL for telephony
        serializer=serializer,
    ),
)
```

<Warning>
  **Two mistakes that produce a silent bot:**

  * Passing `vad_analyzer=` to `FastAPIWebsocketParams`. In Pipecat 1.x the transport no longer has that field, and Pydantic **silently discards it** — you get no error and no turn detection. It belongs on `LLMUserAggregatorParams`.
  * Leaving `add_wav_header` at its default. A WAV header prepended to every frame is interpreted as audio by the media server, and the caller hears noise.
</Warning>

Pipeline order matters — `transport.output()` sits before `context_aggregator.assistant()` so what the bot actually said is what gets recorded into context:

```python theme={null}
pipeline = Pipeline([
    transport.input(),          # Vobiz → frames
    stt,                        # Speech-to-text
    context_aggregator.user(),
    llm,                        # LLM
    tts,                        # Text-to-speech
    transport.output(),         # frames → Vobiz
    context_aggregator.assistant(),
])
```

## Receiving inbound calls

Configure your Vobiz number to handle incoming calls with your Pipecat agent.

<Steps>
  <Step title="Open Applications">
    Log in to the Vobiz Console and navigate to the **Applications** section in the sidebar.

    <img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/OZ7y9Kg025aXyvCH/images/pipecat/image1.png?fit=max&auto=format&n=OZ7y9Kg025aXyvCH&q=85&s=bebde1c06f39cbd1c4897de25e604f84" alt="Open Applications" width="413" height="236" data-path="images/pipecat/image1.png" />
  </Step>

  <Step title="Create an application">
    Click **Create New Application** and give it a name (for example, "Pipecat Agent").

    <img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/OZ7y9Kg025aXyvCH/images/pipecat/image2.png?fit=max&auto=format&n=OZ7y9Kg025aXyvCH&q=85&s=09e88aae040f0fda432ac1d5acb60c67" alt="Create an application" width="884" height="716" data-path="images/pipecat/image2.png" />
  </Step>

  <Step title="Configure URLs">
    Set the **Answer URL** to your ngrok URL (for example, `https://.../answer`) and select `POST` method. You can use the same URL for Hangup or leave it blank.

    <img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/OZ7y9Kg025aXyvCH/images/pipecat/image3.png?fit=max&auto=format&n=OZ7y9Kg025aXyvCH&q=85&s=b9079fffd97a49493326df0835d25ac5" alt="Configure the Answer URL" width="192" height="81" data-path="images/pipecat/image3.png" />
  </Step>

  <Step title="Assign phone number">
    Go to **Phone Numbers**, select your number, and assign it to the application you just created.

    <img className="block w-full rounded-xl border border-gray-200 my-4 shadow-sm" src="https://mintcdn.com/vobizai/OZ7y9Kg025aXyvCH/images/pipecat/image4.png?fit=max&auto=format&n=OZ7y9Kg025aXyvCH&q=85&s=0a9dcd9879635f8752398ee00bc5da1f" alt="Attach your phone number" width="1684" height="203" data-path="images/pipecat/image4.png" />
  </Step>
</Steps>

<Check>
  **Success:** Calls to your Vobiz number will now be handled by your local Pipecat server!
</Check>

## Quick reference

### Server endpoints

| Endpoint | Method | Description |
| - | - | - |
| `/start` | POST | Trigger an outbound call. Body: `{ "phone_number": "+91..." }`. Wraps the Vobiz Call API. |
| `/answer` | GET, POST | Called by Vobiz when the call is answered. Returns `<Record>` + `<Stream>` XML pointing at `/ws`. |
| `/ws` | WebSocket | Bidirectional audio between Vobiz and the Pipecat bot. Also served at `/`, `/voice/ws` and `/stream` for flexibility in what you put in the XML. |
| `/recording-finished` | GET, POST | Vobiz callback when recording stops. Logs metadata. |
| `/recording-ready` | GET, POST | Vobiz callback when the recording is ready. Downloads the file via `download_recording.py`. |
| `/active-calls` | GET | Debug view of the in-memory call registry. |
| `/initiate-transfer` | POST | Flags a call for human transfer, then calls the Vobiz Transfer API. |
| `/transfer-to-human` | POST | Returns the `<Speak>` + `<Dial>` XML used by the transfer flow. |

<Note>
  The call registry is an in-memory dict. It resets on restart and does not work across multiple workers — use Redis or a database before running more than one process in production.
</Note>

### Project files

| File | Purpose |
| - | - |
| `server.py` | FastAPI app - owns `/start`, `/answer`, `/ws`, and the recording callbacks |
| `bot.py` | Pipecat pipeline - STT → LLM → TTS, runs per call |
| `download_recording.py` | Helper used by `/recording-ready` to pull the recording from Vobiz |
| `requirements.txt` | Python dependencies, with the Pipecat version pins |
| `env.example` | Template for your `.env` file - copy and fill in |

<Note>
  `VobizFrameSerializer` and `parse_vobiz_start` are **not** in this repo — they ship in the separate [`pipecat-vobiz`](https://pypi.org/project/pipecat-vobiz/) package, which installs into the `pipecat.serializers` namespace. That is why `bot.py` imports them from `pipecat.serializers.vobiz` rather than from a local file.
</Note>

## Customizing the bot

Edit `bot.py` to customize your AI assistant:

```python Change Bot Personality theme={null}
messages = [
    {
        "role": "system",
        "content": "You are a friendly customer service agent..."
    },
]
```

```python Change TTS Voice theme={null}
tts = OpenAITTSService(
    api_key=os.getenv("OPENAI_API_KEY"),
    voice="ballad",  # alloy, ash, ballad, coral, echo, fable, nova, onyx, sage, shimmer
)
```

<Tip>
  The bot as shipped **waits for the caller to speak first** — `on_client_connected` only logs. To have it greet the caller, queue an `LLMRunFrame` in that handler so the LLM produces its opening line from the system prompt.
</Tip>

## Troubleshooting

<AccordionGroup>
  <Accordion title="Import errors right after pip install">
    Almost always Python 3.10. `pipecat-ai` 1.x requires **3.11+**, and on 3.10 pip installs a `0.0.x` release instead of failing. Run `python --version`, then `pip show pipecat-ai` — if the version starts with `0.0.`, recreate your virtualenv on 3.11+.
  </Accordion>

  <Accordion title="The bot never replies — it hears nothing">
    Check VAD wiring. In Pipecat 1.x, `vad_analyzer` belongs on `LLMUserAggregatorParams`, **not** on `FastAPIWebsocketParams`. The transport no longer has that field, and Pydantic discards unknown fields silently, so the mistake produces no error at all — just a bot that never detects the end of a turn.
  </Accordion>

  <Accordion title="The caller hears static or noise instead of speech">
    Set `add_wav_header=False` on `FastAPIWebsocketParams`. A WAV header on every frame is played as audio by the media server.
  </Accordion>

  <Accordion title="start event arrives, then no media frames">
    You almost certainly have `audioTrack="both"` together with `bidirectional="true"`. That combination is not supported and fails silently. Use `audioTrack="inbound"`.
  </Accordion>

  <Accordion title="Media frames arrive but STT produces nothing (L16 only)">
    Byte order. Set `VOBIZ_L16_ENDIAN=le`. The docs and RFC 2586 specify big-endian, but some accounts transport L16 little-endian. Using the default `audio/x-mulaw` avoids the problem entirely.
  </Accordion>

  <Accordion title="The WebSocket never opens at all">
    Two common causes: the sample rate is `24000` (not reliably supported — use 8000 or 16000), or `PUBLIC_URL` is stale. After restarting ngrok the URL changes; update `PUBLIC_URL` and restart the server, since the answer XML is built from it.
  </Accordion>

  <Accordion title="Vobiz cannot reach /answer">
    If `PUBLIC_URL` is unset the server falls back to the request `Host` header, which is `localhost` in local runs — Vobiz cannot route to that. The server prints a warning when this happens. Set `PUBLIC_URL` to your public HTTPS URL.
  </Accordion>

  <Accordion title="The downloaded recording is named .mp3 but will not play as one">
    Known quirk. The answer XML requests `fileFormat="wav"`, so Vobiz serves a `.wav` URL — but `download_recording.py` unconditionally appends `.mp3` to the saved filename. The bytes are a RIFF/WAVE container (8 kHz, 16-bit, stereo); only the extension is wrong. Rename it to `.wav`, or change the `fileFormat` in the `<Record>` element to match the extension you want.
  </Accordion>
</AccordionGroup>

<Check>
  **Integration complete!**

  You can now make AI-powered phone calls with Vobiz and Pipecat.
</Check>

## Next steps

* Customize your AI assistant's personality in `bot.py`
* Deploy to production (AWS/GCP/Heroku) instead of ngrok
* Add custom business logic and integrations

## Resources

**Vobiz Documentation**

* [API Documentation](/docs/account)
* [Make a Call](/docs/call/make-call)
* [Vobiz Console](https://console.vobiz.ai)

**External Resources**

* [GitHub Repository](https://github.com/vobiz-ai/Vobiz-X-Pipecat)
* [Pipecat Documentation](https://docs.pipecat.ai)

## Build it with an AI agent

<Prompt description="Clone, configure, and run the Vobiz-X-Pipecat repo - your first AI voice agent in ~5 minutes." icon="robot" actions={["copy", "cursor"]}>
  Using the Vobiz MCP at `https://vobiz.ai/docs/mcp`:

  1. Read the `vobiz-ai-voice-agents` skill from `mintlify://skills/ai-voice-agents` and the `vobiz-audio-streams` skill from `mintlify://skills/audio-streams`.
  2. Check my Python version first — `pipecat-ai` 1.x needs **3.11+**, and on 3.10 pip silently installs an incompatible `0.0.x` release. Stop and tell me if I'm on 3.10 or older.
  3. Clone `https://github.com/vobiz-ai/Vobiz-X-Pipecat` into the current directory.
  4. Run `pip install -r requirements.txt` (warn me first if I'm not in a virtualenv), then confirm `pip show pipecat-ai` reports a 1.8.x version.
  5. Copy `env.example` to `.env` and ask me for: `OPENAI_API_KEY`, `VOBIZ_AUTH_ID`, `VOBIZ_AUTH_TOKEN`, my Vobiz number for `VOBIZ_PHONE_NUMBER`. Leave `PUBLIC_URL` and `DEEPGRAM_API_KEY` blank for now.
  6. Explain how to start the FastAPI server (`python server.py`) and how to expose it with `ngrok http 7860`. Tell me to paste the ngrok HTTPS URL into `PUBLIC_URL` and restart — the answer XML is built from that value, so a stale URL breaks the call.
  7. Show me the curl to fire my first AI-powered call via the local `/start` endpoint: `POST http://localhost:7860/start` with body `{"phone_number": "+91..."}` (the field is `phone_number`, not `to`).
  8. Explain the call flow: Vobiz → `/answer` → returns `<Record>` + `<Stream>` XML → WebSocket upgrade on `/ws` → `start` event carrying the authoritative `mediaFormat` → base64 `media` frames both ways → Pipecat pipeline (STT → LLM → TTS) → recording delivered to `/recording-ready`.
</Prompt>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.