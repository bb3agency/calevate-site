> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Deepgram Voice Agent

> Bridge a Vobiz XML <Stream> to the Deepgram Voice Agent API for a phone-callable agent on Deepgram's India region, with Flux STT, Indian-accented Flux TTS, real barge-in, and playback confirmation.

<img className="block w-14 h-14 rounded-xl border border-gray-200 dark:border-zinc-800 mb-4" src="https://mintcdn.com/vobizai/TSi6bV2yJ4DOAsqc/images/deepgram/logo.png?fit=max&auto=format&n=TSi6bV2yJ4DOAsqc&q=85&s=93c783aab94de4da08b0a8b10c380468" alt="Deepgram" width="460" height="460" data-path="images/deepgram/logo.png" />

The [Deepgram Voice Agent API](https://developers.deepgram.com/docs/voice-agent) runs speech-to-text, the LLM and text-to-speech behind a single WebSocket, with its own turn-taking. Bridge it to a Vobiz [`<Stream>`](/docs/xml/stream) and you have a phone-callable agent that a caller can interrupt mid-sentence — no separate STT vendor, no TTS vendor, and no turn logic of your own.

**Source code:** [vobiz-ai/Vobiz-Deepgram-Voice-Agent](https://github.com/vobiz-ai/Vobiz-Deepgram-Voice-Agent) — the reference FastAPI bridge used throughout this guide (`app.py`, `call.py`, `mock_vobiz.py`), plus a mock client that exercises the whole protocol without placing a call.

The defaults are tuned for India: Deepgram's Hyderabad region, an Indian-accented voice, and a keyterm list biased toward Indian vocabulary. One variable switches all of it back to global.

<Note>
  **Scope:** inbound and outbound. Attach a number to an application whose answer URL points at `/answer`, or place an outbound call with the same URL — the bridge does not care which direction the call came from.
</Note>

## How it works

<div className="my-6">
  <img className="block dark:hidden w-full max-w-2xl mx-auto" src="https://mintcdn.com/vobizai/d1twzJfy97_OnWYw/images/deepgram/how-it-works-light.svg?fit=max&auto=format&n=d1twzJfy97_OnWYw&q=85&s=1a35f654c8efecd2294e8316c5eeb680" alt="Vertical call flow: caller audio travels from the caller over PSTN to Vobiz, over a bidirectional WebSocket as media events to app.py, and into the Deepgram Voice Agent as send_media. Agent audio returns as audio bytes, then playAudio, then PSTN. A dashed barge-in loop runs from Deepgram back to Vobiz, labelled UserStartedSpeaking then clearAudio." width="720" height="500" data-path="images/deepgram/how-it-works-light.svg" />

  <img className="hidden dark:block w-full max-w-2xl mx-auto" src="https://mintcdn.com/vobizai/d1twzJfy97_OnWYw/images/deepgram/how-it-works-dark.svg?fit=max&auto=format&n=d1twzJfy97_OnWYw&q=85&s=f107224b6a9621911773b137c2bb5019" alt="Vertical call flow: caller audio travels from the caller over PSTN to Vobiz, over a bidirectional WebSocket as media events to app.py, and into the Deepgram Voice Agent as send_media. Agent audio returns as audio bytes, then playAudio, then PSTN. A dashed barge-in loop runs from Deepgram back to Vobiz, labelled UserStartedSpeaking then clearAudio." width="720" height="500" data-path="images/deepgram/how-it-works-dark.svg" />
</div>

Vobiz opens the WebSocket **to you** — your `wss://` URL is the server. Caller audio arrives as `media` events, the agent's speech goes back as `playAudio`, and `app.py` is a thin relay: format handling, barge-in, and the Vobiz control protocol. Deepgram owns the conversation.

1. Vobiz fetches `/answer` and receives a `<Stream>` element.
2. Vobiz opens a WebSocket to `/media/<secret>` and sends a `start` event.
3. Caller audio arrives as `media` events and is forwarded to Deepgram.
4. Agent audio comes back as raw bytes and goes to Vobiz as `playAudio` events.
5. When the caller interrupts, Deepgram signals it and the app sends `clearAudio`.
6. After each turn a `checkpoint` is sent; Vobiz replies `playedStream` once the caller has actually heard it.

<Card title="The bidirectional Stream protocol" icon="wave-square" href="/docs/xml/stream/stream-events" horizontal>
  Every event and control message on the socket — `start`, `media`, `dtmf`, `playedStream`, `clearedAudio`, `stop` — and what you send back.
</Card>

## Audio profiles

The two directions of a Vobiz bidirectional stream are configured **independently**. Both profiles below are pure passthrough — the bridge never resamples.

| `AUDIO_MODE` | Vobiz → app (`<Stream contentType>`) | app → Vobiz (`playAudio`) | Deepgram agent settings |
| - | - | - | - |
| `mulaw` *(default)* | `audio/x-mulaw;rate=8000` | mu-law 8000 | `mulaw` 8k in / `mulaw` 8k out |
| `l16` | `audio/x-l16;rate=16000` | L16 24000 | `linear16` 16k in / `linear16` 24k out |

`mulaw` matches the PSTN leg exactly and is the right default. `l16` trades bandwidth for a wider band — 16 kHz in, 24 kHz out — and Deepgram emits 24 kHz natively, so nothing is degraded on the way to Vobiz.

<Warning>
  **Never put `rate=24000` on `<Stream contentType>`.** That attribute configures the **inbound** direction, which tops out at 16 kHz. 24 kHz is outbound-only — valid on `playAudio` and nowhere else.
</Warning>

`playAudio` accepts L16 at 8/16/24 kHz and mu-law at 8 kHz. See [audio formats](/docs/xml/stream/audio-formats) for the full matrix.

## Region: India by default

`DEEPGRAM_REGION=india` points every Deepgram connection at `api.in.deepgram.com` (AWS `ap-south-2`, Hyderabad) instead of Deepgram's default hosts. For calls that terminate in India this is the single highest-leverage setting in the file.

| | `india` *(default)* | `global` |
| - | - | - |
| Endpoint | `api.in.deepgram.com` | `api.deepgram.com` / `agent.deepgram.com` |
| Region | AWS ap-south-2, Hyderabad | nearest of Deepgram's default regions |
| Time to first audio, measured from Bengaluru | **\~0.4 s** | \~1.5 s |
| Audio, transcripts, synthesis | stay in India | leave the country |
| Models, pricing, API keys, SDK code | same | same |

On a phone call that gap is not a metric, it is the difference between a natural reply and a pause the caller notices. Set `DEEPGRAM_REGION=global` when serving callers elsewhere.

<Note>
  **Two caveats before promising full data residency.** The LLM step runs wherever that model provider runs, which is outside India, and operational metadata and billing are processed in the US.

  Note also that the SDK takes the Voice Agent host from `environment.agent`, a *different* host from the REST base — so selecting a region means overriding the whole environment rather than a base URL. `app.py` does this for you.
</Note>

## Language and voice

Deepgram listens in far more Indian languages than it can speak. Flux Multilingual understands Hindi, and Nova-3 adds Tamil, Telugu, Marathi, Bengali, Gujarati, Punjabi, Kannada, Assamese and Urdu — but there is **no Indic-language voice**. Every Flux TTS voice is an English model.

What does exist is Indian-accented English:

| `DG_TTS_MODEL` | Character |
| - | - |
| `flux-meena-en` *(default)* | Female — customer service, casual chat |
| `flux-priya-en` | Female — IVR, confident and reassuring |
| `flux-naveen-en` | Male — IVR, support, informative |

So **every locale replies in English**, and the Indian character comes from the voice rather than the words.

| `AGENT_LOCALE` | Understands | Replies in | Model |
| - | - | - | - |
| `en-in` *(default)* | English | English, Indian accent | `flux-general-en` (v2) |
| `hi-in` | Hindi and English, including mid-sentence code-switching | English, Indian accent | `flux-general-multi` (v2) |
| `indic` | One Indic language, set by `INDIC_LANGUAGE` | English, Indian accent | `nova-3` (v1) |
| `en-us` | English | English, American accent | `flux-general-en` (v2) |

`en-in` is the default because the monolingual Flux model has the tightest end-of-turn behaviour. Use `hi-in` when callers code-switch. `indic` reaches nine more languages through Nova, which brings its own endpointing rather than Flux's — so the turn-taking knobs below, eager generation included, do not apply to it. A fair trade when you need that coverage.

<Warning>
  **Do not feed a Flux voice romanised Hindi.** Every Flux voice is an English model; giving one non-English text makes synthesis slow and the audio broken. Keep replies in English and let the accent carry the locality.
</Warning>

Recognition is biased toward Indian vocabulary with a keyterm list — Aadhaar, UPI, PAN card, GST, IFSC, RuPay, lakh, crore, KYC, OTP and major city names, plus the product names that were being mistranscribed. Edit `INDIA_KEYTERMS` in `app.py` to add your own; brand names are the ones most often misheard.

## Choosing the language model

Recognition is a few hundred milliseconds and synthesis is under 100 ms, so the LLM is where the latency lives — it is the setting worth benchmarking. Median time from a user message to first audio, India endpoint, six turns each:

| `LLM_PROVIDER` | `LLM_MODEL` | Median | Range |
| - | - | - | - |
| `anthropic` | `claude-haiku-4-5` *(default)* | **945 ms** | 822–962 |
| `open_ai` | `gpt-4.1-mini` | 1347 ms | 1202–1790 |
| `google` | `gemini-3.1-flash-lite` | 1387 ms | 1196–1465 |
| `open_ai` | `gpt-4o-mini` | 1444 ms | 1115–1755 |
| `google` | `gemini-2.5-flash` | 1807 ms | — |
| `google` | `gemini-3.5-flash` | 2700 ms | — |
| `open_ai` | `gpt-5-mini` | 4792 ms | — |

All of these are Deepgram-managed, so no provider API key is needed. `app.py` handles Deepgram's `LatencyReport` and logs a per-turn `[latency]` breakdown across STT, LLM and TTS — read that line before changing anything.

<Info>
  The system prompt is re-sent every turn, so its length is a recurring latency cost, not a one-off.
</Info>

## Requirements

| Requirement | Detail |
| - | - |
| Deepgram API key | From [console.deepgram.com](https://console.deepgram.com) — it runs STT, the LLM and TTS |
| Vobiz account | `AUTH_ID`, `AUTH_TOKEN`, and a DID — [console.vobiz.ai](https://console.vobiz.ai) |
| Public HTTPS + WSS endpoint | Vobiz connects inbound to your `wss://` URL. ngrok is fine in development. |
| Runtime | Python 3.10+ — `deepgram-sdk` 7.x declares `Requires-Python >=3.10`, so `pip install` is the first thing that fails on 3.9 |

<Info>
  No separate LLM key is needed. Deepgram manages the model provider connection and bills it through your Deepgram account.
</Info>

<Info>
  If your WebSocket endpoint is IP-restricted, allow **inbound TCP 443** from the Vobiz media fleet. The RTP rule (UDP 5000–65535) does not cover it — see [IP whitelisting](/docs/concepts/ip-whitelisting#websocket-streaming).
</Info>

## Step 1: Configure the bridge

```bash theme={null}
git clone https://github.com/vobiz-ai/Vobiz-Deepgram-Voice-Agent
cd Vobiz-Deepgram-Voice-Agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # then fill it in
```

**Only two values are required.** Everything else has a working India default.

```ini .env theme={null}
# ---- Required ----
DEEPGRAM_API_KEY=
# Bare hostname Vobiz can reach. A scheme or trailing slash is stripped;
# a path is rejected, and so is the placeholder.
PUBLIC_HOSTNAME=

# ---- Region, language, voice ----
DEEPGRAM_REGION=india        # india (api.in.deepgram.com) or global
AGENT_LOCALE=en-in           # en-in | hi-in | indic | en-us
INDIC_LANGUAGE=ta            # only when AGENT_LOCALE=indic
DG_TTS_MODEL=                # override the locale's voice
GREETING=                    # override the first thing the caller hears

# ---- Language model (Deepgram-managed, no provider key) ----
LLM_PROVIDER=anthropic
LLM_MODEL=claude-haiku-4-5

# ---- Turn-taking (Flux only; the indic locale ignores these) ----
EOT_THRESHOLD=0.7            # confidence to end a turn, 0.5-1.0
EOT_TIMEOUT_MS=3000          # end the turn this long after speech regardless
EAGER_EOT_THRESHOLD=0.4      # start generating early, 0.3-0.9, or 0 to disable

# ---- Transport ----
HTTP_PORT=5050
BIND_HOST=127.0.0.1          # loopback assumes a tunnel in front
DEV_RELOAD=                  # set to enable the auto-reloader; a reload drops live calls
AUDIO_MODE=mulaw             # mulaw (default) or l16 - see Audio profiles above
CLEAR_ACK_TIMEOUT_S=1.0      # hold new audio this long waiting for clearedAudio

# ---- Security ----
# ASCII alphanumeric - it becomes a path segment on the wss:// URL.
#   python -c "import secrets; print(secrets.token_hex(16))"
STREAM_SECRET=
# true to validate the X-Vobiz-Signature-V3 HMAC on every webhook.
VERIFY_SIGNATURE=

# ---- Outbound only (used by call.py) ----
VOBIZ_AUTH_ID=
VOBIZ_AUTH_TOKEN=
# Left blank on purpose: call.py rejects placeholder digits, so a copied
# template cannot dial a literal +91XXXXXXXXXX.
FROM_NUMBER=
TO_NUMBER=
```

<Note>
  `PUBLIC_HOSTNAME` is normalised and validated at startup — a pasted `https://host/` is accepted and trimmed, but a path, an empty value, or the `your-host…` placeholder exits with a message naming the variable. A blank override anywhere else in the file is treated as absent, so a copied template keeps the defaults.
</Note>

### Dependencies

```text requirements.txt theme={null}
fastapi>=0.115,<1.0
uvicorn[standard]>=0.30
deepgram-sdk>=7.8.1,<8
python-dotenv
websockets<18
requests
```

<Note>
  **Two pins carry a reason.** `deepgram-sdk` is floored at 7.8.1 and capped below 8 — the bridge is verified end to end on 7.8.1 and 7.11.0. `websockets` is held below 18 because the SDK still imports `websockets.legacy` for the async agent client; when that import goes, every agent connect fails on the `extra_headers` / `additional_headers` rename.
</Note>

## Step 2: Run it

The server binds loopback (`BIND_HOST=127.0.0.1`), so start a tunnel first and put its host in `PUBLIC_HOSTNAME`:

```bash theme={null}
cloudflared tunnel --url http://127.0.0.1:5050    # or: ngrok http 127.0.0.1:5050
```

```bash theme={null}
python app.py
```

### Or run it in Docker

The image needs no `.env` — configuration is passed in, and `.dockerignore` keeps `.env` out of the build context so a real key can never be baked into a layer:

```bash theme={null}
docker build -t vobiz-deepgram .
docker run --rm -p 5050:8080 \
  -e DEEPGRAM_API_KEY=your_key \
  -e PUBLIC_HOSTNAME=your-tunnel-host \
  -e STREAM_SECRET=$(openssl rand -hex 16) \
  vobiz-deepgram
```

It listens on `8080` inside the container and binds `0.0.0.0`, because the container's loopback is not reachable from outside it — map it to whatever your tunnel points at. `PORT` overrides the internal port for platforms that assign one. The image is `python:3.12-slim` with no build toolchain, and `uvicorn` is PID 1 so `SIGTERM` stops the container promptly.

`/health` echoes the resolved region, locale, models, voice and audio profile, so you can confirm what is actually in use rather than what you think you set:

```bash theme={null}
curl -s https://<public>/health | python -m json.tool
```

```json theme={null}
{
  "answer_url": "https://<public>/answer",
  "stream_url": "wss://<public>/media",
  "audio_mode": "mulaw",
  "vobiz_to_app": "audio/x-mulaw;rate=8000",
  "app_to_vobiz": "audio/x-mulaw;rate=8000",
  "play_frame_bytes": 160,
  "region": "india",
  "agent_host": "wss://api.in.deepgram.com",
  "locale": "en-in",
  "agent": {
    "listen": "flux-general-en",
    "listen_language": "en",
    "think": "anthropic/claude-haiku-4-5",
    "speak": "flux-meena-en",
    "eot_threshold": 0.7,
    "eot_timeout_ms": 3000
  },
  "webhook_signature_checked": false,
  "media_socket_authenticated": true
}
```

<Note>
  `/health` reports **whether** the media socket is guarded, never the secret that guards it — `stream_url` is printed without the secret path segment, and `media_socket_authenticated` is the only signal. The `eot_*` fields are `null` on the `indic` locale, which uses a v1 provider that does its own endpointing.
</Note>

<Note>
  **Quote the session-end line in a support ticket.** Deepgram's `request_id` arrives on the `Welcome` event, before Vobiz's `start` event has supplied the call id — and the two race, so neither line can carry both. The bridge keeps the request id on the stream and prints the pair when the media session ends, which is the one line that identifies the call to both sides.
</Note>

Whichever host you use becomes the answer URL below.

| Route | Role |
| - | - |
| `GET/POST /answer` | The XML Vobiz executes when the call is answered |
| `WS /media/<secret>` | The bidirectional media stream `<Stream>` connects to |
| `POST /stream-status` | `<Stream statusCallbackUrl>` — `StartStream`, `PlayedStream`, `ClearedAudio`, `StopStream` |
| `POST /hangup` | The call's `hangup_url` |
| `GET /health` | Resolved URLs and audio profile |

## Step 3: Place a call

<Tabs>
  <Tab title="Inbound">
    Vobiz decides what to do with an inbound call by looking up the **Voice Application** attached to the number that was dialled. A number on its own is not enough — create the application first, then attach a number to it.

    **1. Create a Voice Application**

    In the console, go to **Voice Applications → Create application**. Set **Primary answer URL** to `https://<public>/answer` with method **POST**. Optionally set the **Hangup URL** to `https://<public>/hangup` to receive the call-ended webhook.

    <Frame>
      <img src="https://mintcdn.com/vobizai/TSi6bV2yJ4DOAsqc/images/deepgram/create-voice-application.png?fit=max&auto=format&n=TSi6bV2yJ4DOAsqc&q=85&s=431eea4c0756b1bd326d2285925b401a" alt="Vobiz console Create application dialog with fields for application name, primary answer URL with a POST method selector, hangup URL, and fallback answer URL" width="2000" height="1416" data-path="images/deepgram/create-voice-application.png" />
    </Frame>

    **2. Attach a number**

    Open the application and attach one of your DIDs under **Attached Numbers → Attach number**. Calls to that number now fetch XML from your answer URL.

    <Frame>
      <img src="https://mintcdn.com/vobizai/TSi6bV2yJ4DOAsqc/images/deepgram/attach-number.png?fit=max&auto=format&n=TSi6bV2yJ4DOAsqc&q=85&s=5fbf399f605e1a903a27e7dbff89f44b" alt="Attached Numbers panel on a Vobiz voice application showing no numbers attached yet and an Attach number button" width="980" height="376" data-path="images/deepgram/attach-number.png" />
    </Frame>

    Dial the attached number with a `0` or `+91` prefix — `09XXXXXXXXX` or `+919XXXXXXXXX`. You should hear the greeting.

    See [Applications](/docs/applications) for the full reference.
  </Tab>

  <Tab title="Outbound">
    `call.py` places the call and points it at this server, so no Voice Application is needed:

    ```bash theme={null}
    python call.py --to +919XXXXXXXXX
    python call.py --to +919XXXXXXXXX --dry-run   # print the payload without dialling
    ```

    `--from` overrides `FROM_NUMBER` and `--host` overrides `PUBLIC_HOSTNAME` for a one-off call. A scheme on `PUBLIC_HOSTNAME` is stripped here exactly as `app.py` strips it, so a pasted `https://host` cannot build a `https://https://host/answer` answer URL.

    It posts to [Make a Call](/docs/call/make-call):

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

    Answer the phone and talk. `app.py` prints `[user]` and `[assistant]` lines as the conversation runs.
  </Tab>
</Tabs>

## The answer XML

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Stream bidirectional="true"
          audioTrack="inbound"
          keepCallAlive="true"
          contentType="audio/x-mulaw;rate=8000"
          statusCallbackUrl="https://example.com/stream-status"
          statusCallbackMethod="POST">wss://example.com/media/&lt;secret&gt;</Stream>
  <Hangup/>
</Response>
```

| Attribute | Why it matters |
| - | - |
| `bidirectional="true"` | Without it the socket is receive-only and `playAudio` is ignored. It is also what unlocks `clearAudio` and `checkpoint` |
| `keepCallAlive="true"` | Holds XML execution while the socket is open. Without it the element returns immediately, the document ends, and Vobiz hangs up on *End Of XML Instructions* |
| `audioTrack="inbound"` | The only track setting valid alongside `bidirectional` — `both` is rejected. It also stops the agent hearing its own playback |
| `contentType` | Controls **Vobiz → app** only. Never the playback format |
| `statusCallbackUrl` | HTTP mirror of the socket lifecycle: `StartStream`, `PlayedStream`, `ClearedAudio`, `DroppedStream`, `StopStream` |

The WebSocket URL is the element's **text content**, not a `url=""` attribute.

<Warning>
  **Malformed answer XML is not an HTTP error.** Vobiz accepts the `200`, then drops the call about a second later, and the only trace is the CDR field `hangup_cause_name: "Invalid Answer XML"`. A URL carrying two query parameters contains a bare `&`, which is enough on its own to invalidate the document — the reference bridge runs every interpolated value through `html.escape()` for this reason.
</Warning>

## Inside the bridge

### The agent settings

Both ends of the pipeline are [Flux](https://developers.deepgram.com/docs/flux/feature-overview), Deepgram's conversational speech models, and both live on v2 endpoints — so each provider must pin `version: "v2"`. Omit it and the provider falls back to v1, where the Flux model names are not valid.

```python theme={null}
_listen_provider = {
    "type": "deepgram",
    "version": "v2",                 # Flux is v2-only
    "model": "flux-general-en",
    "keyterms": INDIA_KEYTERMS,      # bias recognition toward Indian vocabulary
    "eot_threshold": 0.7,            # v2 only - Nova rejects these
    "eot_timeout_ms": 3000,
    "eager_eot_threshold": 0.4,
}

AGENT_SETTINGS = {
    "type": "Settings",
    "audio": {"input": PROFILE.agent_input, "output": PROFILE.agent_output},
    "agent": {
        "listen": {"provider": _listen_provider},
        "think":  {"provider": {"type": "anthropic", "model": "claude-haiku-4-5"}, "prompt": PROMPT},
        "speak":  {"provider": {"type": "deepgram", "version": "v2", "model": "flux-meena-en"}},
        "greeting": GREETING,
    },
}
```

Sending the settings frame is what starts the conversation, greeting included. To swap the LLM, change the `think` provider — every provider in the [benchmark table](#choosing-the-language-model) is Deepgram-managed.

### Turn-taking

The end-of-turn knobs belong to the **Flux v2 listen provider**. `app.py` attaches them only when the locale resolves to v2, because Nova is a v1 provider that does its own endpointing and rejects them.

| Setting | Default | What it does |
| - | - | - |
| `EOT_THRESHOLD` | `0.7` | Confidence needed to end a turn, `0.5`–`1.0`. Raise it on a noisy line so background speech is less likely to be read as the caller taking a turn |
| `EOT_TIMEOUT_MS` | `3000` | End the turn this long after speech regardless of confidence. Deepgram's own default is `5000`, which is a long silence on a phone call |
| `EAGER_EOT_THRESHOLD` | `0.4` | Start generating the reply on a *medium*-confidence turn end and discard the work if the caller was mid-sentence. `0` disables it |

Eager generation is the cheapest latency win available here: it overlaps the LLM call with the tail of the caller's sentence, at the cost of occasionally throwing that work away.

### Barge-in

Deepgram detects the caller talking over the agent and emits `UserStartedSpeaking`. Vobiz may still have seconds of the agent's reply buffered, so the bridge flushes it:

```python theme={null}
if isinstance(message, AgentV1UserStartedSpeaking):
    await stream.clear()   # {"event": "clearAudio", "streamId": ...}
```

Vobiz confirms with a `clearedAudio` event. Without this the agent keeps talking over the caller. See [`clearAudio`](/docs/xml/stream/clear-audio).

**Playback then waits for that confirmation.** Sending `playAudio` straight after `clearAudio` lets the new reply race the in-flight flush and be partially dropped — the caller hears the next turn starting mid-word. Audio arriving during a flush is held and released on the acknowledgement, with `CLEAR_ACK_TIMEOUT_S` (default `1.0`) as a backstop so a lost `clearedAudio` cannot strand the agent in silence.

### Knowing the caller actually heard it

`playAudio` means *sent*, not *heard*. After each turn the bridge sends a [`checkpoint`](/docs/xml/stream/checkpoint-event) and Vobiz answers `playedStream` once the buffered audio has played out:

```python theme={null}
if isinstance(message, AgentV1AgentAudioDone):
    await stream.checkpoint()   # {"event": "checkpoint", "name": "turn-3", ...}
```

That signal is what lets an agent say goodbye and then hang up without clipping its own last word. The bridge tracks outstanding checkpoints and reports any turn the caller never confirmed hearing, so a silently dropped reply shows up in the log instead of only in the call.

### Frame slicing

Deepgram hands over arbitrarily sized audio chunks. Vobiz is happiest with steady telephony-sized frames, so `VobizStream.play()` re-slices into 20 ms — **160 bytes** mu-law at 8 kHz, **960 bytes** L16 at 24 kHz — rather than forwarding blindly. Any leftover partial frame is carried across chunk boundaries and the tail is flushed at end of turn, so every frame that reaches Vobiz is exactly 20 ms and no audio is lost at the seams.

### Format mismatches are silent

Since the bridge never resamples, a `contentType` that disagrees with `AUDIO_MODE` is just garbage audio into the agent. `read_start()` compares the XML against `start.mediaFormat` and prints `[audio] WARNING` instead of failing quietly.

## Security

Both public endpoints are reachable by anyone who learns the URL, so the bridge ships two opt-in controls:

| Control | What it protects | How |
| - | - | - |
| `STREAM_SECRET` | The media socket | A random ASCII-alphanumeric string becomes a path segment on the `wss://` URL and is compared byte-wise **at the handshake, before `accept()`** — so an unauthorised socket never opens a billed Deepgram session. A mismatch closes with `1008` |
| `VERIFY_SIGNATURE` | All three webhooks | Validates the `X-Vobiz-Signature-V3` (or V2) HMAC on `/answer`, `/stream-status` and `/hangup`, keyed by `VOBIZ_AUTH_TOKEN` |

<Note>
  The secret must be ASCII alphanumeric and this is enforced at startup rather than per call — it becomes a URL path segment and is compared as bytes, so a non-ASCII character would otherwise fail every call instead of failing once, loudly. `/health` never echoes it.
</Note>

<Note>
  **`extraHeaders` cannot authenticate the media socket.** The values never reach the WebSocket — not as an upgrade header, and not in the `start` frame, whose `extra_headers` field stays the literal `"{}"`. They surface only in the `statusCallbackUrl` payload, as `X-VH-<key>`. That makes `extraHeaders` status-callback metadata rather than stream credentials, which is why the secret rides in the URL path instead.
</Note>

<Note>
  **The webhook signature covers the URL and a nonce, never the body.** Voice webhooks are form-encoded, so any scheme that hashes a JSON body will not verify. Query parameters are stripped first, and behind a tunnel the public URL has to be rebuilt — `request.url` is the internal address Vobiz never saw. Signature headers are only emitted when the callback URL has auth credentials configured on it, which is why `VERIFY_SIGNATURE` is opt-in. See [Validating callbacks](/docs/concepts/validating-callbacks).
</Note>

## Security

Three mechanisms guard two different doors.

| | Protects | Set by |
| - | - | - |
| `VERIFY_SIGNATURE` | The three HTTP webhooks | `VOBIZ_AUTH_TOKEN`, plus callback auth credentials on the URL in the console |
| `STREAM_SECRET` | The `/media` WebSocket | A random value in `.env`, checked before the socket is accepted |
| TLS | Everything | Your tunnel or load balancer |

**Set `STREAM_SECRET` before you share the tunnel URL.** An accepted `/media` socket opens a billed Deepgram session on your key, so while the secret is unset anyone who learns the hostname can start one. `openssl rand -hex 16` is enough.

**What the webhook signature proves:** that the request was made by someone holding your account auth token, for that exact URL. It is HMAC-SHA256 over `baseURL + nonce` (V2) or `baseURL + "." + nonce` (V3), compared in constant time.

**What it does not prove** — worth reading before you rely on it:

* **A captured request verifies indefinitely.** The signed material carries a random nonce and no timestamp, so there is nothing to check freshness against. Anyone who records one signed `/answer` request can replay it. Rate-limit and monitor `/answer` if that matters to you.
* **The body is unsigned.** Every form field — `CallUUID`, `From`, `To` — is attacker-controllable on a replayed or forged request, so do not use webhook parameters as an authorisation decision.
* **Signature headers appear only when the callback URL has auth credentials configured** in the console. That is why `VERIFY_SIGNATURE` is opt-in: turning it on without configuring them returns `403` on every call, and the log distinguishes that case from a genuine mismatch.

`STREAM_SECRET` is the stronger of the two, and it is why the secret rides in the WebSocket path — `extraHeaders` never reaches the socket, so the path is the only place the media server can carry a credential. Rotating it is a one-line `.env` change and a restart.

## Test without placing a call

`mock_vobiz.py` stands in for Vobiz — it speaks the media-stream protocol against a running `app.py`, answers `checkpoint` with `playedStream`, and reports what came back.

```bash theme={null}
python mock_vobiz.py                        # 4s of silence — transport and greeting
python mock_vobiz.py --wav question.wav     # stream a real question
```

It prints `PASS` whenever `playAudio` frames were returned, along with the formats, frame count, checkpoints and time to first audio.

<Warning>
  **Read the printed output, not the exit code.** `PASS` only means frames came back — it does not assert that the format matches what the XML requested.
</Warning>

`--wav` takes audio that already matches the profile: nothing in the mock resamples or transcodes. The encoding, channel count and sample rate are read from the RIFF header, and a mismatch is refused with the `ffmpeg` line that fixes it.

| `AUDIO_MODE` | Expected file | Convert with |
| - | - | - |
| `mulaw` *(default)* | mu-law WAV, mono, 8 kHz | `ffmpeg -i in.wav -ar 8000 -ac 1 -c:a pcm_mulaw out.wav` |
| `l16` | 16-bit PCM WAV, mono, 16 kHz | `ffmpeg -i in.wav -ar 16000 -ac 1 -c:a pcm_s16le out.wav` |

A headerless `.ulaw`, `.raw`, `.pcm` or `.l16` file is accepted and taken on trust, since there is no header to check it against.

## Configuration reference

**Required**

| Variable | Notes |
| - | - |
| `DEEPGRAM_API_KEY` | Runs the whole agent — STT, LLM and TTS |
| `PUBLIC_HOSTNAME` | Bare hostname Vobiz reaches. A scheme or trailing slash is stripped; a path is rejected |

**Region, language and voice**

| Variable | Default | Notes |
| - | - | - |
| `DEEPGRAM_REGION` | `india` | `india` (`api.in.deepgram.com`, AWS ap-south-2) or `global` |
| `AGENT_LOCALE` | `en-in` | `en-in`, `hi-in`, `indic`, `en-us` |
| `INDIC_LANGUAGE` | `ta` | Only when `AGENT_LOCALE=indic`: `ta`, `te`, `mr`, `bn`, `gu`, `pa`, `kn`, `as`, `ur` |
| `DG_TTS_MODEL` | per locale | Override the voice — `flux-meena-en`, `flux-priya-en`, `flux-naveen-en` |
| `GREETING` | per locale | Override the first thing the caller hears |

**Language model** — all Deepgram-managed, so no provider key is needed

| Variable | Default | Notes |
| - | - | - |
| `LLM_PROVIDER` | `anthropic` | `anthropic`, `open_ai`, `google`, `groq`, `aws_bedrock` — the SDK types this as a strict literal, so anything else exits at startup |
| `LLM_MODEL` | `claude-haiku-4-5` | Fastest and most consistent of the managed models measured from India |

**Turn-taking** — Flux only; the `indic` locale uses Nova, which does its own endpointing

| Variable | Default | Notes |
| - | - | - |
| `EOT_THRESHOLD` | `0.7` | Confidence needed to end a turn, `0.5`–`1.0` |
| `EOT_TIMEOUT_MS` | `3000` | End the turn this long after speech regardless of confidence |
| `EAGER_EOT_THRESHOLD` | `0.4` | Begin generating on a medium-confidence turn end, `0.3`–`0.9`, or `0` to disable |

**Transport**

| Variable | Default | Notes |
| - | - | - |
| `HTTP_PORT` | `5050` | Server port |
| `BIND_HOST` | `127.0.0.1` | Bind address. Loopback assumes a tunnel in front |
| `DEV_RELOAD` | *(unset)* | Set to enable the auto-reloader. Off by default — a reload drops every live call |
| `AUDIO_MODE` | `mulaw` | `mulaw` or `l16` |
| `CLEAR_ACK_TIMEOUT_S` | `1.0` | How long to wait for `clearedAudio` before resuming playback anyway |

**Security** — both off until configured

| Variable | Notes |
| - | - |
| `STREAM_SECRET` | ASCII-alphanumeric; becomes a path segment on the stream URL and is checked before the socket is accepted |
| `VERIFY_SIGNATURE` | `true` to validate the `X-Vobiz-Signature-V3`/`V2` HMAC on all three webhooks |

**Outbound calls** — `call.py` only; inbound needs none of these

| Variable | Notes |
| - | - |
| `VOBIZ_AUTH_ID` | Vobiz account auth ID |
| `VOBIZ_AUTH_TOKEN` | Vobiz auth token; also the webhook signing key |
| `FROM_NUMBER` | A DID this account owns |
| `TO_NUMBER` | Default destination for `call.py` |

## Troubleshooting

| Symptom | Cause | Resolution |
| - | - | - |
| Call hangs up immediately; log shows *End Of XML Instructions* | `keepCallAlive="true"` missing, or `audioTrack="both"` with `bidirectional="true"` | Set `keepCallAlive="true"` and `audioTrack="inbound"` |
| Silence in both directions | `bidirectional="true"` missing — `playAudio` is ignored on a one-way stream | Add the attribute |
| Garbled or chipmunk audio | `<Stream contentType>` and `AUDIO_MODE` disagree | Match them; the app prints `[audio] WARNING` on the start event |
| Speech sounds slow, stretched or broken | The voice is being given non-English text — every Flux voice is an English model | Keep replies in English and let the accent come from the voice |
| Replies feel sluggish | One pipeline stage dominates | Read the `[latency]` line to see which, then change `LLM_MODEL` if the language model is responsible. Confirm `DEEPGRAM_REGION=india` for Indian callers |
| Agent cuts the caller off mid-sentence | `EOT_THRESHOLD` too low for the line, or `EOT_TIMEOUT_MS` too short | Raise both |
| Brand or domain words mistranscribed | The keyterm list does not cover them | Add them to `INDIA_KEYTERMS` in `app.py` |
| Next reply starts mid-word after an interruption | New playback raced an in-flight flush | Expected to be handled — check `clearedAudio` is arriving and raise `CLEAR_ACK_TIMEOUT_S` if the line is slow |
| Agent talks over the caller | `clearAudio` is not reaching Vobiz | Check `streamId` is set before the first `playAudio` |
| Stream connects but no usable media arrives | `rate=24000` set on `<Stream contentType>` | 24 kHz is outbound-only — use 8000 or 16000 inbound |
| WebSocket closes with `1008` | `STREAM_SECRET` does not match the secret in the stream URL path | Re-copy the value, or clear it while testing |
| Startup exits naming `LLM_PROVIDER` | The SDK types the provider as a strict literal, so `openai` for `open_ai` — or any provider outside the five — is rejected | Use `anthropic`, `open_ai`, `google`, `groq` or `aws_bedrock` |
| Startup exits naming `DG_TTS_MODEL` | An Aura voice was set; `speak` is pinned to v2, which rejects them | Use a Flux voice — `flux-meena-en`, `flux-priya-en`, `flux-naveen-en` |
| Agent goes quiet mid-call and the call ends | The Deepgram socket dropped — revoked key, exhausted quota, a network blip, or the documented 2-hour session cap | The bridge closes the media socket with `1011` and logs the reason rather than leaving the caller on a silent line |
| Startup exits with *STREAM\_SECRET must be ASCII alphanumeric* | The secret becomes a URL path segment and is compared byte-wise | Regenerate it with `secrets.token_hex(16)` |
| Startup exits naming `PUBLIC_HOSTNAME` | Unset, still the placeholder, or contains a path | Use a bare hostname — the tunnel's host, no scheme |
| A webhook returns `403` | `VERIFY_SIGNATURE=true` but the callback URL has no auth credentials configured, so no signature headers are sent | Set the credentials in the console first, then enable it. The log distinguishes this from a genuine mismatch |
| Outbound call returns `401` or `402` | `401` credentials, `402` balance. *"from number … not owned"* means the DID belongs to another account | Check `VOBIZ_AUTH_ID`/`VOBIZ_AUTH_TOKEN` and the `from` DID |
| Inbound call is never answered | The number has no Voice Application attached, or the application's answer URL does not point at this server | See [Step 3 → Inbound](#step-3-place-a-call) |
| Inbound call does not connect | The number was dialled without a prefix | Dial with `0` or `+91` |
| Hangup webhook reports zero cost | Voice and stream are billed as separate line items that appear only in the CDR | Read [`GET /cdr/{call_uuid}`](/docs/cdr/get-cdr) |

## Next steps

* Clone the reference bridge: [vobiz-ai/Vobiz-Deepgram-Voice-Agent](https://github.com/vobiz-ai/Vobiz-Deepgram-Voice-Agent)
* Tuning detail — where the latency goes, model benchmarks, turn-taking and region: [docs/PERFORMANCE.md](https://github.com/vobiz-ai/Vobiz-Deepgram-Voice-Agent/blob/main/docs/PERFORMANCE.md)
* Read the [`<Stream>` reference](/docs/xml/stream), [audio formats](/docs/xml/stream/audio-formats), [stream events](/docs/xml/stream/stream-events) and [`playAudio`](/docs/xml/stream/play-audio)
* Deepgram's [Voice Agent API](https://developers.deepgram.com/docs/voice-agent) and [Flux](https://developers.deepgram.com/docs/flux/feature-overview) docs
* Bridging a different model over the same socket? See [WebSockets](/docs/integrations/websockets) and [Gemini Live](/docs/integrations/gemini-live)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.