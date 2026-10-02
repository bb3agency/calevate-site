> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# OTP call

> Generate a six-digit OTP, place a Vobiz outbound call, read it digit by digit to the caller, and verify the response on your backend - Python example.

Phone-based two-factor authentication - generate a 6-digit OTP, call the user, and read it digit by digit.

**XML elements used:** `<Speak>`, `<Gather inputType=dtmf numDigits=1>`, `<Redirect>`, `<Hangup>`

<Card title="View on GitHub" icon="github" href="https://github.com/vobiz-ai/Vobiz-OTP-call-XML-Python">
  Clone and run the full working example
</Card>

## Getting started

```bash theme={null}
git clone https://github.com/vobiz-ai/Vobiz-OTP-call-XML-Python.git
cd Vobiz-OTP-call-XML-Python
cp .env.example .env
pip install -r requirements.txt
python server.py
```

## Overview

Your app calls `POST /send-otp` with a phone number. The server generates a 6-digit OTP with a 5-minute TTL, triggers an outbound Vobiz call, and reads the code aloud one digit at a time with 1-second pauses. The user can press 1 to hear the code again. Your app then calls `POST /verify-otp` to check the code.

## Call flow

```text theme={null}
Your app
  └── POST /send-otp {"phone": "+91XXXXXXXXXX"}
        └── OTP generated (6 digits, 5-min TTL)
        └── Vobiz outbound call triggered
              └── /answer  → "Your verification code is: 6. 1. 0. 3. 8. 9."
                              "Press 1 to hear it again."
                    ├── 1 → /otp-choice  → Repeat OTP
                    └── (hangup) → /hangup  → OTP marked as delivered

  └── POST /verify-otp {"phone": "+91...", "otp": "610389"}
        └── 200 OK {"valid": true} or 400 {"valid": false}
```

## Vobiz webhooks

Set `/answer` as the **Answer URL** in your Vobiz application.

| Method | Path | Description |
| - | - | - |
| POST | `/answer` | Reads OTP digit by digit |
| POST | `/otp-choice` | Handles press 1 to repeat |
| POST | `/hangup` | Marks OTP as delivered, cleanup |

## App API

| Method | Path | Description |
| - | - | - |
| POST | `/send-otp` | Generate OTP + trigger outbound call |
| POST | `/verify-otp` | Verify OTP entered by user |
| GET | `/otp-status/{phone}` | Check delivery status |

## Environment variables

| Variable | Required | Description |
| - | - | - |
| `VOBIZ_AUTH_ID` | Yes | Vobiz account auth ID |
| `VOBIZ_AUTH_TOKEN` | Yes | Vobiz account auth token |
| `FROM_NUMBER` | Yes | Your Vobiz DID (outbound caller ID) |
| `HTTP_PORT` | No | Server port (default: 8000) |
| `PUBLIC_URL` | No | Production URL - skips ngrok if set |
| `NGROK_AUTH_TOKEN` | No | ngrok auth token for local dev |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.