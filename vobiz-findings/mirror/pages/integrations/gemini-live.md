> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Gemini Live Voice Agent

> Bridge a Vobiz XML <Stream> to Google's Gemini Live API to build a phone-callable voice agent with real barge-in and no audio resampling anywhere in the path.

[Gemini Live](https://ai.google.dev/gemini-api/docs/live) does speech-to-text, the LLM and text-to-speech inside a single WebSocket session, with its own voice activity detection. Bridge it to a Vobiz [`<Stream>`](/docs/xml/stream) and you have a phone-callable voice agent with no separate STT vendor, no TTS vendor, and no turn-taking logic of your own.

**Source code:** [vobiz-ai/Vobiz-Gemini-Live-Streaming](https://github.com/vobiz-ai/Vobiz-Gemini-Live-Streaming) — the reference FastAPI bridge used throughout this guide (`app.py`, `gemini_live.py`, `audio.py`), plus a mock client that holds a whole conversation without placing a call.

<Note>
  **Scope:** inbound and outbound. Point a Vobiz number's answer URL at `/answer`, or place an outbound call with the same URL — the bridge does not care which direction the call came from.
</Note>

## How it works

```text theme={null}
caller ──PSTN──▶ Vobiz ──wss──▶ your bridge ──wss──▶ Gemini Live
       ◀────────────────  playAudio  ◀────────────  audio + transcripts
```

Vobiz opens the WebSocket **to you** — your `wss://` URL is the server. Caller audio arrives as `media` events, you send the model's speech back as `playAudio`, and what is left for your code to do is format handling, barge-in, and the Vobiz control protocol.

<Card title="The bidirectional Stream protocol" icon="wave-square" href="/docs/xml/stream/stream-events" horizontal>
  Every event and control message on the socket — `start`, `media`, `dtmf`, `playedStream`, `clearedAudio`, `stop` — and what you send back.
</Card>

## Why the default formats matter

The two directions of a Vobiz bidirectional stream are **independent**, and Gemini Live is fixed at 16 kHz in / 24 kHz out. Line them up and no audio is resampled anywhere in the path:

| Direction | Configured by | Use | Gemini wants |
| - | - | - | - |
| Vobiz → app | `<Stream contentType>` | `audio/x-l16;rate=16000` | PCM16 mono **16 kHz** ✅ |
| app → Vobiz | `playAudio.media` | L16 @ **24000** | emits PCM16 mono **24 kHz** ✅ |

`audio/x-mulaw;rate=8000` and `audio/x-l16;rate=8000` also work — the bridge's `audio.py` converts — but each conversion costs a little quality and latency.

<Warning>
  **Never put `rate=24000` on `<Stream>`.** Inbound L16 at 24 kHz is accepted by the XML parser and the platform attempts the stream, but your application never receives usable media. 24 kHz is valid only on `playAudio`.

  This is exactly why the working combination for a 24 kHz TTS engine is **16 kHz in, 24 kHz out**.
</Warning>

See [Audio formats](/docs/xml/stream/audio-formats) for the full matrix of supported rates and encodings.

## Requirements

| Requirement | Detail |
| - | - |
| Gemini API key | From [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| Vobiz account | `AUTH_ID`, `AUTH_TOKEN`, and a DID to call from — [console.vobiz.ai](https://console.vobiz.ai) |
| Public HTTPS + WSS endpoint | Vobiz connects inbound to your `wss://` URL. ngrok is fine in development. |
| Runtime | Python 3.11+ |

<Info>
  If your WebSocket endpoint is IP-restricted, allow **inbound TCP 443** from the Vobiz media fleet. The RTP rule (UDP 5000–65535) does not cover it — see [IP whitelisting](/docs/concepts/ip-whitelisting#websocket-streaming).
</Info>

## Step 1: Pick a Live model

Live API model names change often, and choosing one your key cannot use fails at connect time with a bare WebSocket close `1008` and no useful message. Check first:

```bash theme={null}
.venv/bin/python models.py
```

It lists every model your key can use with `bidiGenerateContent`. Two worth knowing:

| Model | Character |
| - | - |
| `gemini-3.1-flash-live-preview` | Half-cascade. Best tool use — the default in the repo. |
| `gemini-2.5-flash-native-audio-latest` | Native audio, more expressive. |

## Step 2: Configure the bridge

```bash theme={null}
git clone https://github.com/vobiz-ai/Vobiz-Gemini-Live-Streaming
cd Vobiz-Gemini-Live-Streaming
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env       # then fill it in
```

```ini .env theme={null}
# ---- Gemini ----
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.1-flash-live-preview
# Aoede Puck Charon Kore Fenrir Leda Orus Zephyr
GEMINI_VOICE=Aoede
# BCP-47 for the half-cascade models, e.g. en-IN, hi-IN. Empty = auto.
GEMINI_LANGUAGE=en-IN

AGENT_GREETING=Hi, you are through to the Gemini voice agent. How can I help?
AGENT_SYSTEM_PROMPT=You are a voice assistant on a live telephone call. Keep every reply to one or two short sentences. Speak plainly, never use markdown or emoji, and read numbers digit by digit. If the caller says goodbye, say goodbye and call the end_call function.

# Let the model hang up the call itself with the end_call tool.
ENABLE_END_CALL=true

# ---- Vobiz ----
VOBIZ_AUTH_ID=
VOBIZ_AUTH_TOKEN=
FROM_NUMBER=+91XXXXXXXXXX
TO_NUMBER=+91XXXXXXXXXX

# Vobiz -> app. Never 24000 here.
STREAM_CONTENT_TYPE=audio/x-l16;rate=16000

# app -> Vobiz. Gemini's native output rate, so nothing is resampled.
OUTPUT_CONTENT_TYPE=audio/x-l16
OUTPUT_SAMPLE_RATE=24000
PLAY_CHUNK_MS=20

# ---- Server ----
HTTP_PORT=8000
# Set on a box with a public IP. Empty => ngrok is started automatically.
PUBLIC_URL=
```

<Tip>
  **Pin `GEMINI_LANGUAGE` for a real phone line.** With language detection on auto, background noise and accented speech get transcribed as whatever language fits best, and the model answers in kind. On an Indian line, `en-IN` keeps it steady.
</Tip>

### Dependencies

```text requirements.txt theme={null}
google-genai>=1.30.0
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
websockets>=13.0
python-dotenv>=1.0.0
python-multipart>=0.0.9
requests>=2.32.0
httpx>=0.27.0
```

## Step 3: Run it

```bash theme={null}
.venv/bin/python selftest.py --gemini   # 41 checks, no phone call
.venv/bin/python app.py                 # starts ngrok if PUBLIC_URL is empty
```

`app.py` prints the URLs it is serving:

```text theme={null}
  answer url      https://<public>/answer     (POST)
  hangup url      https://<public>/hangup     (POST)
  stream ws       wss://<public>/ws
  Vobiz -> app    audio/x-l16;rate=16000
  app -> Vobiz    l16/24000 in 20ms frames
```

| Route | Role |
| - | - |
| `POST /answer` | The XML Vobiz executes when the call is answered |
| `WS /ws` | The bidirectional media stream `<Stream>` connects to |
| `POST /stream-status` | `<Stream statusCallbackUrl>` — `StartStream`, `PlayedStream`, `StopStream` |
| `POST /hangup` | The call's `hangup_url` |
| `GET /health` | Public URL and resolved agent configuration |
| `GET /calls` | Transcripts and stream events, newest first |

## Step 4: Place a call

<Tabs>
  <Tab title="Outbound">
    ```bash theme={null}
    .venv/bin/python call.py            # dials TO_NUMBER — pick up and talk
    ```

    It discovers the answer URL from the running server and posts to [Make a Call](/docs/call/make-call):

    ```bash theme={null}
    curl -X POST "https://api.vobiz.ai/api/v1/Account/$AUTH_ID/Call/" \
      -H "X-Auth-ID: $AUTH_ID" \
      -H "X-Auth-Token: $AUTH_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "from": "+91XXXXXXXXXX",
        "to": "+91XXXXXXXXXX",
        "answer_url": "https://<public>/answer",
        "answer_method": "POST",
        "hangup_url": "https://<public>/hangup",
        "hangup_method": "POST"
      }'
    ```
  </Tab>

  <Tab title="Inbound">
    Point a Vobiz number's answer URL at `https://<public>/answer` and the same bridge handles the call. Nothing else changes.

    Console: **Phone Numbers → your number → Answer URL**, or attach an [application](/docs/applications) that carries the URL.
  </Tab>
</Tabs>

While a call is up, or after it:

```bash theme={null}
curl -s localhost:8000/calls | python -m json.tool    # turns + stream events
```

Each call is also written to `data/call-<uuid>.json` when it ends.

## The answer XML

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream bidirectional="true"
            audioTrack="inbound"
            keepCallAlive="true"
            contentType="audio/x-l16;rate=16000"
            statusCallbackUrl="https://example.com/stream-status"
            statusCallbackMethod="POST">
        wss://example.com/ws
    </Stream>
    <Hangup/>
</Response>
```

| Attribute | Why it matters |
| - | - |
| `bidirectional="true"` | Without it the socket is receive-only and `playAudio` is ignored |
| `keepCallAlive="true"` | Holds XML execution while the socket is open. Without it Vobiz walks straight on to `<Hangup/>` |
| `audioTrack="inbound"` | Caller audio only, so the agent never hears its own playback |
| `contentType` | Controls **Vobiz → app** only. Not the playback format |
| `statusCallbackUrl` | HTTP mirror of the socket lifecycle: `StartStream`, `PlayedStream`, `ClearedAudio`, `DroppedStream`, `StopStream` |

<Warning>
  **Malformed answer XML is not an HTTP error.** Vobiz accepts the `200`, then drops the call about a second later. The only trace is the CDR field `hangup_cause_name: "Invalid Answer XML"` with `hangup_source: Error`.

  A URL carrying two query parameters contains a bare `&`, which is by itself enough to invalidate the document — escape it. The reference bridge runs every interpolated value through `html.escape()` for this reason.
</Warning>

If the session must be recorded, [`<Record>`](/docs/xml/record) and `<Stream>` are **siblings** — never nest them. Watch the Record `action` URL: if it answers `<Hangup/>`, the call ends before `<Stream>` ever runs.

## Inside the bridge

### Making the model speak first

The caller should never have to open the conversation. A client-content turn at session start makes the model greet them:

```python theme={null}
await session.send_client_content(
    turns=types.Content(
        role="user",
        parts=[types.Part(text=f"Greet the caller with exactly: {GREETING}")],
    ),
    turn_complete=True,
)
```

### Barge-in

Gemini's VAD reports `server_content.interrupted` the moment the caller talks over the agent. Forward it to Vobiz as [`clearAudio`](/docs/xml/stream/clear-audio):

```python theme={null}
if getattr(content, "interrupted", None):
    await self.vobiz.clear()   # {"event": "clearAudio", "streamId": ...}
```

That drops the playback still queued on the call leg. Queued audio can be seconds long, so skip this and the caller keeps hearing a reply the model has already abandoned.

### End of turn, and hanging up cleanly

After each turn the bridge sends a [`checkpoint`](/docs/xml/stream/checkpoint-event). Vobiz answers `playedStream` once the queued audio has actually played — the only reliable signal that the caller *heard* something:

```python theme={null}
if getattr(content, "turn_complete", None):
    self._flush_turns()
    await self.vobiz.checkpoint()      # {"event": "checkpoint", "name": "turn-N"}
```

That is what lets the `end_call` tool say goodbye **and then** hang up, instead of cutting the caller off mid-word: the tool call only sets a flag, and the socket closes when `playedStream` comes back.

```python theme={null}
if call.name == "end_call":
    self.hangup_after_playback = True
```

<Note>
  A checkpoint discarded by `clearAudio` may never complete. Do not block on one.
</Note>

### DTMF

Keypad presses arrive as `dtmf` events. Forwarding them to the model as text is worth doing — a caller asked for a number will often type it:

```python theme={null}
await self.session.send_realtime_input(
    text=f"The caller pressed the keypad digit {digit}."
)
```

### Reading the format from the wire

```python theme={null}
# start.mediaFormat is the authority on what is arriving, and it changes
# the moment someone edits the XML.
{"event": "start", "start": {"mediaFormat": {"encoding": "audio/x-l16",
                                            "sampleRate": 16000}}}
```

Decode according to `start.mediaFormat` on **every** connection rather than trusting your own configuration. Keep the `streamId` — every control message needs it.

### Frame sizes

Send 20–60 ms per `playAudio`. 20 ms gives responsive barge-in and predictable queueing.

| Format | Bytes per 20 ms |
| - | -: |
| μ-law/8000 | 160 |
| L16/8000 | 320 |
| L16/16000 | 640 |
| L16/24000 | 960 |

L16 means signed 16-bit, mono, little-endian, **raw** — no RIFF/WAV header — base64-encoded.

## Test without spending a phone call

`mock_vobiz.py` impersonates Vobiz: it opens the WebSocket, sends a real `start` frame, streams a spoken prompt, and writes the agent's reply to `media/reply.wav`. It exits non-zero if no audio comes back, so it works in CI.

```bash theme={null}
.venv/bin/python app.py &
.venv/bin/python mock_vobiz.py
.venv/bin/python mock_vobiz.py --say "What is two plus two?"
.venv/bin/python mock_vobiz.py --greeting-wait 1.2   # talk over the greeting
.venv/bin/python mock_vobiz.py --wav question.wav    # your own mono 16-bit WAV
```

The prompt is spoken by Gemini TTS and cached in `media/`, so no recording and no second provider is needed.

## Verified behaviour

Run against `gemini-3.1-flash-live-preview`.

| Test | Result |
| - | - |
| `selftest.py --gemini` | 41 passed, 0 failed |
| Greeting plays unprompted | first audio **1.02–1.27 s** after `start` |
| Caller speech transcribed | *"Sorry to interrupt you. What is 2 + 2?"* |
| Agent replies with audio | *"2 plus 2 equals 4."* |
| Barge-in over the greeting | `clearAudio` sent, agent transcript truncates mid-sentence |
| `end_call` tool | tool call → goodbye plays → `playedStream` → stream closed |
| L16 16 kHz in / 24 kHz out | pass, no resampling |
| μ-law 8 kHz in / out | pass |

On a real PSTN call — 44 s answered, 2189 media frames in, 928 KB played:

| Signal | Result |
| - | - |
| `StartStream` → WebSocket open | 48 ms after the answer XML |
| Gemini session ready | 758 ms after `start` |
| Greeting heard by the caller | `PlayedStream` for `turn-1` |
| Barge-in | 2 × `clearAudio`, each confirmed by a Vobiz `ClearedAudio` |
| Checkpoints | 5 sent, 5 `PlayedStream` callbacks returned |
| `end_call` | goodbye played, then the stream closed and Vobiz ran `<Hangup/>` |
| Line quality | MOS 4.5, jitter 0, packet loss 0.27 %, codec PCMU |

## Behaviour reference

| Observation | Cause | Resolution |
| - | - | - |
| Gemini socket closes the instant the greeting finishes; every later frame fails with `sent 1000 (OK)` | A bare `async for message in session.receive()` exits the `async with` — `receive()` yields **one turn**, then stops | Wrap it in an outer `while not closed:` loop |
| Call drops \~1 s after answer, CDR shows `hangup_cause_name: "Invalid Answer XML"` | Malformed XML, commonly a bare `&` in a URL with two query parameters | XML-escape every interpolated value |
| Caller audio decodes as noise or silence | Format assumed instead of read from `start.mediaFormat`, or a rate declared that does not match the bytes | Decode from `start.mediaFormat`; declaring a rate never resamples anything |
| Stream connects but no usable media arrives | `rate=24000` set on `<Stream contentType>` | 24 kHz belongs only in `playAudio` — use 16000 inbound |
| Caller keeps hearing an abandoned reply | `server_content.interrupted` not forwarded as `clearAudio` | Send `clearAudio` on interruption |
| Caller cut off mid-word when the agent hangs up | Socket closed on the tool call instead of after playback | Wait for `playedStream` on the turn's checkpoint |
| Agent hears itself and loops | `audioTrack` not restricted to `inbound` | Set `audioTrack="inbound"` |
| Stream torn down immediately; caller hears the element after `<Stream>` | `keepCallAlive` not set | Set `keepCallAlive="true"` |
| Model interrupts the caller's thinking pauses | VAD end-of-turn too aggressive for the line | Raise `VAD_SILENCE_MS` |
| WebSocket close `1008` at connect | Model name not available to the key | `python models.py`, then set `GEMINI_MODEL` |
| CDR `stream_termination_reason: "Connection error"`, callback `DroppedStream` | The application closed the socket itself, as `end_call` does | Expected — Vobiz has no separate label for a deliberate close |
| Hangup webhook reports zero cost | Voice and stream are billed as separate line items that appear **only** in the CDR | Read [`GET /cdr/{call_uuid}`](/docs/cdr/get-cdr) |

### Useful CDR fields

`total_cost`, `stream_cdrs[].billed_amount`, `billsec`, `mos`, `jitter`, `packet_loss`, `codec`, `ring_time`, `hangup_disposition`, `hangup_cause_name`.

<Note>
  Two timing traps: the hangup webhook's `Duration` counts **answered** seconds, while the CDR's `duration` is wall clock **including ringing** — they disagree on every call. And billing rounds up to a 60-second minimum pulse, so a 44-second stream reports `rounded_bill_duration: 60`.
</Note>

## Configuration reference

| Key | Default | Notes |
| - | - | - |
| `GEMINI_MODEL` | `gemini-3.1-flash-live-preview` | `models.py` lists valid ones |
| `GEMINI_VOICE` | `Aoede` | Puck, Charon, Kore, Fenrir, Leda, Orus, Zephyr |
| `GEMINI_LANGUAGE` | *(auto)* | BCP-47, e.g. `en-IN`, `hi-IN` |
| `AGENT_GREETING` | *(set)* | Spoken by the model as its first turn |
| `AGENT_SYSTEM_PROMPT` | *(set)* | Keep it explicit about short, plain, spoken replies |
| `STREAM_CONTENT_TYPE` | `audio/x-l16;rate=16000` | Vobiz → app. Never 24000 |
| `OUTPUT_CONTENT_TYPE` | `audio/x-l16` | app → Vobiz |
| `OUTPUT_SAMPLE_RATE` | `24000` | app → Vobiz |
| `PLAY_CHUNK_MS` | `20` | 20–60 ms per `playAudio` |
| `ENABLE_END_CALL` | `true` | Lets the model hang up |
| `VAD_SILENCE_MS` | *(API default)* | Raise it if the agent interrupts thinking pauses |
| `VAD_PREFIX_PADDING_MS` | *(API default)* | |
| `GREETING_XML` | *(none)* | A `<Speak>` before the stream connects |
| `PUBLIC_URL` | *(none)* | Empty starts ngrok automatically |

## Deploying

Any host with a public HTTPS URL and WebSocket support works. Set `PUBLIC_URL` and ngrok is skipped:

```bash theme={null}
PUBLIC_URL=https://voice.example.com .venv/bin/python app.py
```

* Behind a reverse proxy, WebSocket upgrades on `/ws` must be forwarded, and the idle timeout has to exceed your longest call.
* ngrok issues a new domain on each restart, so an answer URL stored on a number or application must be updated whenever it changes.

<Warning>
  **Transcripts and recordings are personal data in most jurisdictions.** The bridge writes `data/call-<uuid>.json` per call and `media/reply.wav` on mock runs, and `.env` holds your Gemini key and Vobiz auth token. All three are gitignored in the reference repo. If you add storage, decide on retention before you add the feature, and tell callers.
</Warning>

## 24 kHz playback and the handset

24 kHz on `playAudio` does not mean 24 kHz at the caller's ear. If the phone leg negotiated G.711 (`codec: PCMU`), Vobiz downconverts anyway. The gain is in not degrading the TTS *before* it reaches Vobiz.

## Next steps

* Clone the reference bridge: [vobiz-ai/Vobiz-Gemini-Live-Streaming](https://github.com/vobiz-ai/Vobiz-Gemini-Live-Streaming)
* Read the [`<Stream>` reference](/docs/xml/stream), [audio formats](/docs/xml/stream/audio-formats), [stream events](/docs/xml/stream/stream-events) and [`playAudio`](/docs/xml/stream/play-audio)
* Google's [Gemini Live API docs](https://ai.google.dev/gemini-api/docs/live) and the [`google-genai` SDK](https://github.com/googleapis/python-genai)
* Bridging to something else over the same socket? See [WebSockets](/docs/integrations/websockets)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.