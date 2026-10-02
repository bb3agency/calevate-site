> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Voicemail

> Capture caller voice messages on Vobiz using the Record verb, store recordings as MP3, and retrieve them via the admin API - Python and XML example.

Caller leaves a voice message - recording saved as an MP3 and retrievable via admin API.

**XML elements used:** `<Speak>`, `<Record>`, `<Hangup>`

<Card title="View on GitHub" icon="github" href="https://github.com/vobiz-ai/Vobiz-Voicemail-XML-Python">
  Clone and run the full working example
</Card>

## Getting started

```bash theme={null}
git clone https://github.com/vobiz-ai/Vobiz-Voicemail-XML-Python.git
cd Vobiz-Voicemail-XML-Python
cp .env.example .env
pip install -r requirements.txt
python server.py
```

## Overview

When a caller dials in, they hear a greeting and are prompted to leave a message after the beep. The recording is saved immediately when the caller hangs up or presses `#`. When the MP3 file is ready, a second callback fires with the download URL. All voicemails are stored and accessible via a simple admin API.

## Call flow

```text theme={null}
Caller dials in
  └── /answer  → "Please leave a message after the beep. Press # when done."
        └── <Record> begins
              └── Caller leaves message, presses # or hangs up
                    └── /voicemail-done  → fires immediately (recording ended)
                          └── /voicemail-file  → fires when MP3 is ready (with URL)
                    └── /hangup  → cleanup
```

## Vobiz webhooks

Set `/answer` as the **Answer URL** in your Vobiz application.

| Method | Path | Description |
| - | - | - |
| POST | `/answer` | Greeting + start recording |
| POST | `/voicemail-done` | Action URL - fires immediately when recording ends |
| POST | `/voicemail-file` | Callback - fires when MP3 file is ready |
| POST | `/hangup` | Call ended webhook |

## App API

| Method | Path | Description |
| - | - | - |
| GET | `/voicemails` | List all voicemails, newest first |
| GET | `/voicemails/stats` | Total / unread count |
| GET | `/voicemails/{id}` | Single voicemail + MP3 URL |
| PATCH | `/voicemails/{id}/read` | Mark as read |
| DELETE | `/voicemails/{id}` | Delete a voicemail |

## Environment variables

| Variable | Required | Description |
| - | - | - |
| `HTTP_PORT` | No | Server port (default: 8000) |
| `PUBLIC_URL` | No | Production URL - skips ngrok if set |
| `NGROK_AUTH_TOKEN` | No | ngrok auth token for local dev |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.