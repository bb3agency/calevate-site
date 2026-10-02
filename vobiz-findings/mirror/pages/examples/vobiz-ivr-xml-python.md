> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# IVR menu

> Build a multi-level Interactive Voice Response menu on Vobiz with dynamic configuration, DTMF keypad routing, and call analytics tracking in Python.

Multi-level Interactive Voice Response menu with dynamic config and call analytics.

**XML elements used:** `<Gather inputType=dtmf>`, `<Speak>`, `<Redirect>`, `<Dial><Number>`, `<Hangup>`

<Card title="View on GitHub" icon="github" href="https://github.com/vobiz-ai/Vobiz-IVR-XML-Python">
  Clone and run the full working example
</Card>

## Getting started

```bash theme={null}
git clone https://github.com/vobiz-ai/Vobiz-IVR-XML-Python.git
cd Vobiz-IVR-XML-Python
cp .env.example .env
pip install -r requirements.txt
python server.py
```

## Overview

A company main phone line that routes callers to **Sales**, **Support**, **Billing**, or an **Operator** via keypad input. Transfer numbers are updated at runtime via a REST API - no server restart needed. Full call analytics track which menu options are pressed most.

## Call flow

```text theme={null}
/answer  →  Main Menu
              1 → Sales
              │     1 → Products & pricing (spoken)
              │     2 → Request a demo → Hangup
              │     3 → Connect to sales rep → <Dial>
              │     9 → Back to main menu
              2 → Technical Support
              │     1 → API issues → raise ticket option
              │     2 → Call quality → <Dial>
              │     3 → Account access (spoken)
              │     9 → Back
              3 → Billing
              │     1 → Balance info (spoken)
              │     2 → Payment issues → <Dial>
              │     3 → Invoice / GST info (spoken)
              │     9 → Back
              4 → Account Management
              │     1 → Upgrade plan → <Dial>
              │     2 → Update details (spoken)
              │     3 → Cancel → double confirm
              │     9 → Back
              0 → Operator → <Dial>
              9 → Repeat menu
```

## Vobiz webhooks

Set `/answer` as the **Answer URL** in your Vobiz application.

| Method | Path | Description |
| - | - | - |
| POST | `/answer` | Main IVR menu |
| POST | `/ivr-main-choice` | Routes digit 1–4 / 0 / 9 to sub-menu |
| POST | `/ivr-sales` | Sales sub-menu |
| POST | `/ivr-sales-choice` | Routes sales choice |
| POST | `/ivr-support` | Support sub-menu |
| POST | `/ivr-support-choice` | Routes support choice |
| POST | `/ivr-support-ticket` | Raises high priority ticket |
| POST | `/ivr-billing` | Billing sub-menu |
| POST | `/ivr-billing-choice` | Routes billing choice |
| POST | `/ivr-account` | Account management sub-menu |
| POST | `/ivr-account-choice` | Routes account choice |
| POST | `/ivr-account-cancel-confirm` | Double confirms cancellation |
| POST | `/ivr-operator` | Direct transfer to operator |
| POST | `/dial-complete` | Callback after any `<Dial>` ends |
| POST | `/hangup` | Call ended webhook |

## App API

| Method | Path | Description |
| - | - | - |
| GET | `/config` | View current department config |
| PUT | `/config/department/{dept}` | Update transfer number / enable-disable |
| GET | `/call-logs` | Full call history |
| GET | `/call-logs/analytics` | Which menu options are pressed most |

## Environment variables

| Variable | Required | Description |
| - | - | - |
| `VOBIZ_AUTH_ID` | Yes | Vobiz account auth ID |
| `VOBIZ_AUTH_TOKEN` | Yes | Vobiz account auth token |
| `FROM_NUMBER` | Yes | Your Vobiz DID (caller ID for transfers) |
| `HTTP_PORT` | No | Server port (default: 8000) |
| `PUBLIC_URL` | No | Production URL - skips ngrok if set |
| `NGROK_AUTH_TOKEN` | No | ngrok auth token for local dev |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.