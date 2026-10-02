> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Number capture

> Collect a caller's phone number on Vobiz via DTMF keypad input with the # terminator, validation, and duplicate detection in a Python XML example.

Collect a caller's phone number via keypad (DTMF + # terminator) with validation and duplicate detection.

**XML elements used:** `<Speak>`, `<Gather inputType=dtmf finishOnKey=#>`, `<Redirect>`, `<Hangup>`

<Card title="View on GitHub" icon="github" href="https://github.com/vobiz-ai/Vobiz-Number-Capture-XML-Python">
  Clone and run the full working example
</Card>

## Getting started

```bash theme={null}
git clone https://github.com/vobiz-ai/Vobiz-Number-Capture-XML-Python.git
cd Vobiz-Number-Capture-XML-Python
cp .env.example .env
pip install -r requirements.txt
python server.py
```

## Overview

The caller is prompted to enter a phone number using their keypad, followed by `#`. The server validates the digits, reads them back one at a time for confirmation, and stores the number with deduplication. Captured numbers are accessible via API for CRM import or lead management.

## Call flow

```text theme={null}
Caller dials in
  └── /answer  → "Please enter your phone number followed by #"
        └── /number-received  → Validates digits, reads back digit by digit
              └── /number-confirm  → "Press 1 to confirm, 2 to re-enter, 3 to cancel"
                    ├── 1 → Saved to leads store → Hangup
                    ├── 2 → Back to /answer
                    └── 3 → "Cancelled." → Hangup

  └── GET /leads/export.csv   → CRM import
  └── GET /leads/analytics    → {total: 234, unique: 198, duplicates: 36, today: 12}
```

## Vobiz webhooks

Set `/answer` as the **Answer URL** in your Vobiz application.

| Method | Path | Description |
| - | - | - |
| POST | `/answer` | Prompts for number + `#` |
| POST | `/number-received` | Validates + reads back digit by digit |
| POST | `/number-confirm` | 1=confirm / 2=re-enter / 3=cancel |
| POST | `/number-received-repeat` | Re-reads number on invalid key press |
| POST | `/hangup` | Cleanup |

## App API

| Method | Path | Description |
| - | - | - |
| GET | `/leads` | List all captured numbers |
| GET | `/leads/export.csv` | Download as CSV |
| GET | `/leads/analytics` | Total, unique, duplicates, today count |
| GET | `/leads/{id}` | Single lead detail |
| DELETE | `/leads/{id}` | Remove a lead |

## Environment variables

| Variable | Required | Description |
| - | - | - |
| `HTTP_PORT` | No | Server port (default: 8000) |
| `PUBLIC_URL` | No | Production URL - skips ngrok if set |
| `NGROK_AUTH_TOKEN` | No | ngrok auth token for local dev |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.