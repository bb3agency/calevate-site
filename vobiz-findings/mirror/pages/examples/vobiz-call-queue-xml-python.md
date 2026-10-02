> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Call queue

> Build a hold-music call queue on Vobiz featuring round-robin agent dispatch, configurable retry cycles, and voicemail fallback - Python and XML example.

Hold music queue with round-robin agent dispatch, retry cycles, and voicemail fallback.

<Card title="View on GitHub" icon="github" href="https://github.com/vobiz-ai/Vobiz-Call-Queue-XML-Python">
  Clone and run the full working example
</Card>

## Getting started

```bash theme={null}
git clone https://github.com/vobiz-ai/Vobiz-Call-Queue-XML-Python.git
cd Vobiz-Call-Queue-XML-Python
cp .env.example .env
pip install -r requirements.txt
python server.py
```

## Overview

Inbound callers hear a greeting and are placed in a queue with hold music. The server dials available agents round-robin. If no agent answers after `MAX_WAIT_CYCLES` attempts, the caller is offered voicemail. Agents register themselves as available or offline via a REST API. Real-time queue metrics track wait times, connections, and abandonment rate.

## Call flow

```text theme={null}
Caller dials in
  └── /answer  → "Thank you for calling. Please hold."
        └── /queue-hold  → Play hold music (HOLD_WAIT_SECS)
              └── /queue-try-agent  → Dial next available agent (round-robin)
                    ├── Agent answers → Connected  → /dial-complete
                    └── No answer / busy
                          ├── cycles < MAX_WAIT_CYCLES → back to /queue-hold
                          └── cycles ≥ MAX_WAIT_CYCLES → /queue-voicemail
                                └── Caller leaves message → /voicemail-done
```

## Vobiz webhooks

Set `/answer` as the **Answer URL** in your Vobiz application.

| Method | Path | Description |
| - | - | - |
| POST | `/answer` | Greeting + join queue |
| POST | `/queue-hold` | Play hold music + wait per cycle |
| POST | `/queue-try-agent` | Dial next available agent (round-robin) |
| POST | `/dial-complete` | Agent answered or no-answer - retry or fallback |
| POST | `/queue-voicemail` | Fallback after `MAX_WAIT_CYCLES` exhausted |
| POST | `/voicemail-done` | Recording saved |
| POST | `/hangup` | Cleanup + abandoned tracking |

## App API

| Method | Path | Description |
| - | - | - |
| POST | `/agents` | Register agent as available `{number, name}` |
| DELETE | `/agents/{number}` | Take agent offline |
| GET | `/agents` | List available agents |
| GET | `/queue/status` | Callers waiting + agents available |
| GET | `/queue/metrics` | Avg wait, connected, abandoned, abandonment rate |

## Environment variables

| Variable | Required | Description |
| - | - | - |
| `VOBIZ_AUTH_ID` | Yes | Vobiz account auth ID |
| `VOBIZ_AUTH_TOKEN` | Yes | Vobiz account auth token |
| `FROM_NUMBER` | Yes | Your Vobiz DID |
| `AGENT_NUMBER` | Yes | Default agent number (fallback if none registered) |
| `HOLD_MUSIC_URL` | No | URL to MP3/OGG hold music |
| `MAX_WAIT_CYCLES` | No | Max hold attempts before voicemail (default: 3) |
| `HOLD_WAIT_SECS` | No | Seconds of hold per cycle (default: 20) |
| `HTTP_PORT` | No | Server port (default: 8000) |
| `PUBLIC_URL` | No | Production URL - skips ngrok if set |
| `NGROK_AUTH_TOKEN` | No | ngrok auth token for local dev |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.