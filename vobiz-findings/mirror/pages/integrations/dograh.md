> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Dograh integration

> Connect Vobiz telephony to a self-hosted Dograh instance to place and receive AI voice-agent calls - Docker setup, telephony config, and the bidirectional audio stream.

<img className="block w-14 h-14 rounded-xl border border-gray-200 dark:border-zinc-800 p-1.5 mb-4" src="https://mintcdn.com/vobizai/228rTXC4mfN_jNWw/images/dograh/logo.png?fit=max&auto=format&n=228rTXC4mfN_jNWw&q=85&s=034a28a5adabe65cfbbbe8cd68f88746" alt="Dograh" width="200" height="200" data-path="images/dograh/logo.png" />

[Dograh](https://github.com/dograh-hq/dograh) is an open-source, self-hosted platform for building AI voice agents. Connecting it to Vobiz gives your agents real phone numbers and global calling through premium SIP trunking.

<iframe width="100%" height="420" src="https://www.youtube.com/embed/pEs-aajNgTs" title="Dograh + Vobiz Integration Tutorial" frameBorder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowFullScreen style={{ borderRadius: "12px", marginTop: "1rem", marginBottom: "1rem" }} />

## What you'll build

A self-hosted Dograh instance that places and receives AI voice-agent calls over Vobiz - Dograh dials via the Vobiz REST API, Vobiz fetches a `<Stream>` instruction, and audio streams bidirectionally over a WebSocket to your agent (STT → LLM → TTS).

## Prerequisites

* A **Vobiz account** with an **Auth ID** (e.g. `MA_XXXXXXXX`) and **Auth Token** - from the [Vobiz Console](https://console.vobiz.ai).
* At least one **Vobiz phone number** (your caller ID), in E.164 **without** the `+` (e.g. `91XXXXXXXXXX`).
* **Docker** + **Docker Compose** installed.
* A way for Vobiz's cloud to reach your server. For local dev, Dograh auto-creates a Cloudflare quick tunnel (see [Step 5](#step-5-make-dograh-reachable-from-vobiz)).

## Step 1: Run Dograh

```bash theme={null}
git clone https://github.com/dograh-hq/dograh.git
cd dograh

# Required secret for OSS auth (any strong random string)
echo "OSS_JWT_SECRET=$(openssl rand -hex 32)" > .env

REGISTRY=ghcr.io/dograh-hq ENABLE_TELEMETRY=false docker compose up -d --pull always
```

First boot pulls images (2–3 min). When healthy, open [http://localhost:3010](http://localhost:3010).

<Tip>
  Health check: `curl http://localhost:8000/api/v1/health` should return `{"status":"ok", ...}`.
</Tip>

## Step 2: Create your account

Open [http://localhost:3010](http://localhost:3010), sign up (local auth - no email needed), and you're in the dashboard.

## Step 3: Get your Vobiz credentials

From the [Vobiz Console](https://console.vobiz.ai), copy:

* **Auth ID** (`MA_…`)
* **Auth Token**
* **(Optional) Application ID** - leave it blank and Dograh auto-creates one and stores it.
* Your **Vobiz number(s)** you'll call from.

## Step 4: Add Vobiz in Dograh

In the dashboard, go to **Telephony → Configure Telephony**.

<img className="block max-w-sm mx-auto rounded-xl border border-gray-200 dark:border-zinc-800 my-4 shadow-sm" src="https://mintcdn.com/vobizai/228rTXC4mfN_jNWw/images/dograh/telephony%20sidepanel.png?fit=max&auto=format&n=228rTXC4mfN_jNWw&q=85&s=937634d75ca391802bbf222eee3b2eff" alt="Dograh Configure Telephony side panel" width="265" height="630" data-path="images/dograh/telephony sidepanel.png" />

Select **Vobiz** as the provider.

<img className="block max-w-sm mx-auto rounded-xl border border-gray-200 dark:border-zinc-800 my-4 shadow-sm" src="https://mintcdn.com/vobizai/228rTXC4mfN_jNWw/images/dograh/select%20vobiz.png?fit=max&auto=format&n=228rTXC4mfN_jNWw&q=85&s=9ac53037756d06cabaf53cfecb9e71aa" alt="Select Vobiz provider in Dograh" width="534" height="891" data-path="images/dograh/select vobiz.png" />

Enter your credentials:

| Field | Value |
| - | - |
| **Provider** | `vobiz` |
| **Auth ID** | `MA_XXXXXXXX` |
| **Auth Token** | your Vobiz auth token |
| **Application ID** | *(optional - auto-created if blank)* |
| **From numbers** | your Vobiz number(s), E.164 without `+` (e.g. `91XXXXXXXXXX`) |

<img className="block max-w-sm mx-auto rounded-xl border border-gray-200 dark:border-zinc-800 my-4 shadow-sm" src="https://mintcdn.com/vobizai/228rTXC4mfN_jNWw/images/dograh/add%20config.png?fit=max&auto=format&n=228rTXC4mfN_jNWw&q=85&s=b2cde041f69fa7f8b089fb0405870a73" alt="Add Vobiz telephony configuration in Dograh" width="548" height="362" data-path="images/dograh/add config.png" />

Save, and set it as the **default outbound config** if prompted.

<Check>
  Dograh is now authorized to place and receive calls through your Vobiz account.
</Check>

## Step 5: Make Dograh reachable from Vobiz

Vobiz's cloud calls back into Dograh for call control and audio:

| Endpoint | Purpose |
| - | - |
| `POST /api/v1/telephony/vobiz-xml` | Returns the `<Stream>` instruction. |
| `POST /api/v1/telephony/vobiz/ring-callback/{run_id}` | Ring status. |
| `POST /api/v1/telephony/vobiz/hangup-callback/{run_id}` | Call ended. |
| `WS /api/v1/telephony/ws/{workflow_id}/{user_id}/{run_id}` | Bidirectional audio stream. |

For these to work, Dograh must be **publicly reachable**:

* **Local dev** - Dograh auto-starts a Cloudflare quick tunnel and uses it automatically (no setup). Check it in the health output's `backend_api_endpoint`.
* **Production** - deploy on a server with a real domain (HTTPS) and set `BACKEND_API_ENDPOINT=https://your-domain` so the callbacks and `wss://` stream use a stable, low-latency endpoint. See Dograh's Docker deployment guide for the remote profile (nginx + HTTPS).

## Step 6: Build an agent

Go to **Create agent**, pick **Inbound** or **Outbound**, name it, and describe the use case in a sentence (e.g. *"Qualify inbound insurance leads"*). Dograh generates a workflow you can edit.

<img className="block max-w-sm mx-auto rounded-xl border border-gray-200 dark:border-zinc-800 my-4 shadow-sm" src="https://mintcdn.com/vobizai/228rTXC4mfN_jNWw/images/dograh/workflow%20created%20successfully%20.png?fit=max&auto=format&n=228rTXC4mfN_jNWw&q=85&s=37c3d586e27e90dcbe77d90a202390a1" alt="Dograh workflow created successfully" width="549" height="331" data-path="images/dograh/workflow created successfully .png" />

## Step 7: Place an outbound call

Open your agent and click **Call** (phone icon):

<img className="block max-w-sm mx-auto rounded-xl border border-gray-200 dark:border-zinc-800 my-4 shadow-sm" src="https://mintcdn.com/vobizai/228rTXC4mfN_jNWw/images/dograh/click%20phone%20call.png?fit=max&auto=format&n=228rTXC4mfN_jNWw&q=85&s=fa25bb99260215f253b1f2e53e0055a4" alt="Place an outbound call in Dograh" width="669" height="420" data-path="images/dograh/click phone call.png" />

* **Telephony configuration:** `vobiz (vobiz)` - default
* **Caller ID (from):** your Vobiz number
* **To:** the destination number (E.164)

Click **Call**, pick up, and talk to your agent. Dograh dials via the Vobiz REST API, Vobiz fetches the `<Stream>` XML, and audio streams over the WebSocket to your agent.

## Inbound calls *(optional)*

Attach a workflow to a Vobiz number on the account - Dograh updates that Vobiz application's `answer_url` so incoming calls route to the agent.

<img className="block max-w-sm mx-auto rounded-xl border border-gray-200 dark:border-zinc-800 my-4 shadow-sm" src="https://mintcdn.com/vobizai/228rTXC4mfN_jNWw/images/dograh/click%20on%20add%20phone%20numebr.png?fit=max&auto=format&n=228rTXC4mfN_jNWw&q=85&s=d870c63bb9d8fdeb6e98517234fb1fb0" alt="Add a phone number in Dograh" width="1550" height="669" data-path="images/dograh/click on add phone numebr.png" />

<img className="block max-w-sm mx-auto rounded-xl border border-gray-200 dark:border-zinc-800 my-4 shadow-sm" src="https://mintcdn.com/vobizai/228rTXC4mfN_jNWw/images/dograh/add%20your%20phone%20number.png?fit=max&auto=format&n=228rTXC4mfN_jNWw&q=85&s=1b6afd28e2e308622c7a7ed88545414e" alt="Enter your Vobiz phone number in Dograh" width="568" height="458" data-path="images/dograh/add your phone number.png" />

<img className="block max-w-sm mx-auto rounded-xl border border-gray-200 dark:border-zinc-800 my-4 shadow-sm" src="https://mintcdn.com/vobizai/228rTXC4mfN_jNWw/images/dograh/add%20the%20number.png?fit=max&auto=format&n=228rTXC4mfN_jNWw&q=85&s=b6d732b30698b794d4e7beca207f0b99" alt="Assign the Vobiz number to an agent" width="633" height="693" data-path="images/dograh/add the number.png" />

## How it works

```text theme={null}
Dograh REST dial → Vobiz places call → ring-callback → answered
  → Vobiz fetches /vobiz-xml
  → <Stream bidirectional="true" contentType="audio/x-mulaw;rate=8000">
  → WebSocket opens → caller audio (media) ⇄ bot audio (playAudio)
  → hangup-callback on end
```

## Troubleshooting

<AccordionGroup>
  <Accordion title="401 on every request / can't create agent">
    Stale browser session after a re-clone or secret change. Clear site data for `localhost:3010`, or use an Incognito window.
  </Accordion>

  <Accordion title="Call connects but no audio">
    Check your STT/LLM/TTS provider keys in **Settings** (if using the built-in hosted models, verify the account/key is active). Confirm `backend_api_endpoint` in the health output is a reachable public URL.
  </Accordion>

  <Accordion title="Robotic or slow voice with OpenAI TTS">
    This Dograh configuration uses μ-law at 8 kHz. Ensure the transport resamples the provider output and encodes it as μ-law/8 kHz before sending `playAudio`. Do not label 24 kHz PCM as 8 kHz without converting it. Other custom transports can send supported L16 playback directly when their `playAudio` metadata matches the real payload.
  </Accordion>

  <Accordion title="Bot greets but won't continue the conversation">
    Turn-taking depends on the *bot-stopped-speaking* signal. Avoid a continuous output mixer on telephony.
  </Accordion>

  <Accordion title="Ports clash with another local stack">
    Remap host ports via a `docker-compose.override.yaml` (e.g. postgres `5433`, redis `6380`, api `8001`).
  </Accordion>
</AccordionGroup>

## Resources

| Resource | Link |
| - | - |
| Dograh on GitHub | [github.com/dograh-hq/dograh](https://github.com/dograh-hq/dograh) |
| Vobiz `<Stream>` XML | [Stream element](/docs/xml/stream) |
| Vobiz support | [support@vobiz.ai](mailto:support@vobiz.ai) |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.