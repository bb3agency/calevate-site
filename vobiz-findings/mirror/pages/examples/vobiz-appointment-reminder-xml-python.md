> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Appointment reminder

> Send outbound appointment reminder calls on Vobiz with confirm, reschedule, and cancel DTMF options - every outcome stored per appointment in Python.

Outbound reminder call with confirm / reschedule / cancel - all outcomes stored per appointment.

**XML elements used:** `<Speak>`, `<Gather inputType=dtmf numDigits=1>`, `<Redirect>`, `<Hangup>`

<Card title="View on GitHub" icon="github" href="https://github.com/vobiz-ai/-Vobiz-Appointment-reminder-XML-Python">
  Clone and run the full working example
</Card>

## Getting started

```bash theme={null}
git clone https://github.com/vobiz-ai/-Vobiz-Appointment-reminder-XML-Python.git
cd -Vobiz-Appointment-reminder-XML-Python
cp .env.example .env
pip install -r requirements.txt
python server.py
```

## Overview

A CRM or booking system triggers outbound reminder calls before appointments. The callee presses **1** to confirm, **2** to request a reschedule, or **3** to cancel (with a double-confirm step). All outcomes are stored and queryable via API with bulk scheduling support.

<Note>
  **Status lifecycle:** `pending` → `calling` → `confirmed` / `reschedule_requested` / `cancelled` / `no_answer`. Cancel via API before the call fires: `aborted`.
</Note>

## Call flow

```text theme={null}
Your CRM
  └── POST /appointments {"phone":"+91...", "name":"John", "date":"Apr 5", "time":"3 PM"}
        └── AppointmentStore.create() → status: pending
        └── Trigger Vobiz outbound call → status: calling
              └── /answer
                    "Hello John! Reminder: appointment on Apr 5 at 3 PM."
                    Gather: 1=Confirm  2=Reschedule  3=Cancel  9=Repeat
                      ├── 1 → "Confirmed. See you soon!" → Hangup  (status: confirmed)
                      ├── 2 → "Please call us to reschedule." → Hangup (status: reschedule_requested)
                      ├── 3 → "Are you sure?" → Gather 1=Yes / 2=No
                      │         ├── 1 → "Cancelled." → Hangup  (status: cancelled)
                      │         └── 2 → Back to reminder
                      └── (no input) → Hangup  (status: no_answer)
```

## Vobiz webhooks

Set `/answer` as the **Answer URL** in your Vobiz application.

| Method | Path | Description |
| - | - | - |
| POST | `/answer` | Reads reminder, collects DTMF |
| POST | `/appt-choice` | Routes 1=confirm / 2=reschedule / 3=cancel |
| POST | `/appt-cancel-confirm` | Double confirms cancellation |
| POST | `/hangup` | Marks `no_answer` if no digit was pressed |

## App API

| Method | Path | Description |
| - | - | - |
| POST | `/appointments` | Schedule a single reminder call |
| POST | `/appointments/bulk` | Schedule multiple at once (JSON array) |
| GET | `/appointments` | List all with outcomes (`?status=` to filter) |
| GET | `/appointments/{id}` | Single appointment status |
| PATCH | `/appointments/{id}/cancel` | Cancel before call is made |
| GET | `/appointments/stats` | Outcome breakdown by status |

## Environment variables

| Variable | Required | Description |
| - | - | - |
| `VOBIZ_AUTH_ID` | Yes | Vobiz account auth ID |
| `VOBIZ_AUTH_TOKEN` | Yes | Vobiz account auth token |
| `FROM_NUMBER` | Yes | Your Vobiz DID |
| `HTTP_PORT` | No | Server port (default: 8000) |
| `PUBLIC_URL` | No | Production URL - skips ngrok if set |
| `NGROK_AUTH_TOKEN` | No | ngrok auth token for local dev |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.