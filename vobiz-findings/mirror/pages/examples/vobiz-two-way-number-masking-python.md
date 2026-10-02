> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Two-way number masking

> Connect a field agent and a customer through two masking DIDs so neither sees the other's real number, bidirectional call masking with FastAPI and Vobiz XML.

Connect two parties, a field agent and a customer, through masking numbers so neither ever sees the other's real number. Either side can call, and both directions are private.

**XML elements used:** `<Dial callerId=…>`, `<Number>`, `<Speak>`, `<Hangup>`

<Card title="View on GitHub" icon="github" href="https://github.com/vobiz-ai/Vobiz-Two-Way-Number-Masking">
  Clone and run the full working example
</Card>

<Note>
  New to the concept? Read [What is Number Masking?](/docs/blogs/what-is-number-masking) for the why and the call-flow theory, then come back here to build it.
</Note>

## Getting started

```bash theme={null}
git clone https://github.com/vobiz-ai/Vobiz-Two-Way-Number-Masking.git
cd Vobiz-Two-Way-Number-Masking
cp .env.example .env
pip install -r requirements.txt
uvicorn app:app --reload --port 8001
```

## Overview

You provision **two** masking DIDs and attach both to a single Vobiz [application](/docs/platform/voice/applications). When either number is dialed, Vobiz POSTs the call to your `/answer` webhook. Your backend looks up the dialed number (`To`), checks the caller (`From`) is authorized, and returns a [`<Dial>`](/docs/xml/dial) that bridges to the real destination, showing the *masking* number as caller ID. Neither party sees a real number.

The whole system is two rows of mapping:

* **`M1`** is the number the **agent** dials to reach the **customer**.
* **`M2`** is the number the **customer** dials to reach the **agent**.

Caller IDs are **cross-mapped** so each party always sees one consistent number for the other: dial `M1` and the customer sees `M2`; dial `M2` and the agent sees `M1`.

| Dialed number (`To`) | Allowed caller (`From`) | Bridges to | Caller ID shown |
| - | - | - | - |
| `M1` | the agent | the customer | `M2` |
| `M2` | the customer | the agent | `M1` |

## Call flow

```text theme={null}
Agent calls the customer
  Agent (FE) ── dials ──▶ M1
        └── Vobiz ── POST /answer  From=FE, To=M1 ──▶ your backend
                       resolve(): authorize FE, dial CUSTOMER, show M2
              ◀── <Dial callerId="M2"><Number>CUSTOMER</Number></Dial> ──┘
        └── Vobiz dials CUSTOMER, who sees M2 ── both legs bridge

Customer calls the agent  (mirror image)
  Customer ── dials ──▶ M2
        └── Vobiz ── POST /answer  From=CUSTOMER, To=M2 ──▶ your backend
                       resolve(): authorize CUSTOMER, dial FE, show M1
              ◀── <Dial callerId="M1"><Number>FE</Number></Dial> ──┘
        └── Vobiz dials FE, who sees M1 ── both legs bridge
```

If the caller is **not** the registered party for that masking number, the backend rejects the call with a spoken message instead of bridging.

## Vobiz webhook

Set `/answer` as the **Answer URL** on your Vobiz application (the included `setup_live.py` does this for you).

| Method | Path | Description |
| - | - | - |
| POST | `/answer` | Resolves the dialed masking number and returns a `<Dial>` (or a rejection) |
| GET | `/health` | Health check |

## Environment variables

| Variable | Required | Description |
| - | - | - |
| `VOBIZ_AUTH_ID` | Yes | Vobiz account auth ID |
| `VOBIZ_AUTH_TOKEN` | Yes | Vobiz account auth token |
| `VOBIZ_API_BASE` | No | API base (defaults to `https://api.vobiz.ai/api/v1`) |
| `PUBLIC_BASE_URL` | Yes | Your public HTTPS tunnel (Cloudflare/ngrok), used as the Answer URL |
| `M1` | Yes | Masking DID the **agent** dials → reaches the customer |
| `M2` | Yes | Masking DID the **customer** dials → reaches the agent |
| `FE` | Yes | Field agent's real number |
| `CUSTOMER` | Yes | Customer's real number |

## Step 1: The number map

All numbers come from the environment, so no real numbers live in source. The `resolve()` function returns a `Leg` only when the dialed number is a known masking number **and** the caller is the registered party for it. Matching is format-tolerant (compares the final 10 digits), so `+`, spaces, a leading `0`, or a missing country code all still match.

```python mappings.py theme={null}
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

FE = os.environ.get("FE", "918888800001")              # field agent real number
CUSTOMER = os.environ.get("CUSTOMER", "918888800002")  # customer real number
M1 = os.environ.get("M1", "919000000001")              # masking: FE -> Customer
M2 = os.environ.get("M2", "919000000002")              # masking: Customer -> FE


@dataclass
class Leg:
    masking_number: str   # the number that was dialled (the `To`)
    allowed_caller: str   # only this registered real number may use it
    destination: str      # the real number to bridge to
    caller_id_shown: str  # the masking number the destination should SEE


# Keyed by the number that was *dialled* (the `To`).
# Cross-mapped caller ID: dial M1 -> customer sees M2; dial M2 -> agent sees M1.
MAPPINGS: dict[str, Leg] = {
    M1: Leg(masking_number=M1, allowed_caller=FE, destination=CUSTOMER, caller_id_shown=M2),
    M2: Leg(masking_number=M2, allowed_caller=CUSTOMER, destination=FE, caller_id_shown=M1),
}


def _norm(number: str) -> str:
    """Digits only, last 10 - tolerant of '+', spaces, leading 0, country code."""
    digits = "".join(c for c in (number or "") if c.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


_NORM_MAPPINGS = {_norm(k): v for k, v in MAPPINGS.items()}


def resolve(to_number: str, from_number: str) -> Leg | None:
    """Return the Leg if `to_number` is a masking number AND `from_number` is its
    registered caller; otherwise None."""
    leg = _NORM_MAPPINGS.get(_norm(to_number))
    if leg is None or _norm(leg.allowed_caller) != _norm(from_number):
        return None
    return leg
```

## Step 2: The XML builders

`vobiz_xml.py` holds a few small helpers (`response()`, `dial()`, `speak()`, `hangup()`) that return Vobiz XML strings so handlers don't concatenate strings by hand. The only one that matters for masking is `dial()`, whose `caller_id` argument becomes the [`callerId`](/docs/xml/dial) the *called* party sees, and for masking that is **always the masking number, never the real caller**:

```python theme={null}
dial(leg.destination, caller_id=leg.caller_id_shown, timeout=30)
# → <Dial callerId="919000000002" timeout="30"><Number>918888800002</Number></Dial>
```

The full builder module is in the repo, you can also just return the XML as a literal string if you prefer.

## Step 3: The webhook

The `/answer` handler is stateless and idempotent: it reads `From` and `To`, resolves the mapping, and returns either a bridging `<Dial>` or a spoken rejection. Every request carries everything it needs, so retries are safe and you can run many instances behind a load balancer.

```python app.py theme={null}
from fastapi import FastAPI, Form, Response

import mappings
from vobiz_xml import dial, hangup, response, speak

app = FastAPI(title="Vobiz masking - two-way (client-hosted)")

XML = "application/xml"


@app.post("/answer")
async def answer(
    From: str = Form(...),
    To: str = Form(...),
    CallUUID: str = Form(default=""),
    Direction: str = Form(default=""),
    CallStatus: str = Form(default=""),
) -> Response:
    """Vobiz POSTs call details here when a masking number is dialled."""
    leg = mappings.resolve(to_number=To, from_number=From)
    if leg is None:
        xml = response(
            speak("Sorry, this number is not authorised for your account."),
            hangup(reason="rejected"),
        )
        return Response(content=xml, media_type=XML)

    xml = response(
        dial(leg.destination, caller_id=leg.caller_id_shown, timeout=30),
    )
    return Response(content=xml, media_type=XML)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "strategy": "two-way-client-hosted"}
```

When the agent dials `M1`, this returns:

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial callerId="919000000002" timeout="30">
    <Number>918888800002</Number>
  </Dial>
</Response>
```

## Step 4: Expose your server over HTTPS

Vobiz needs a public **HTTPS** Answer URL. In development, tunnel your local port:

```bash theme={null}
# Cloudflare tunnel (or use ngrok http 8001)
cloudflared tunnel --url http://127.0.0.1:8001
```

Copy the `https://…` URL it prints into `PUBLIC_BASE_URL` in your `.env`.

## Step 5: Go live

Run the bundled one-time setup script:

```bash theme={null}
python setup_live.py
```

It [creates a Vobiz application](/docs/applications/create-application) whose Answer URL is `PUBLIC_BASE_URL/answer`, then [attaches](/docs/applications/attach-number) **both** masking DIDs to it, so inbound calls to either number hit your server. (You can also do this in the dashboard: create one application and point both numbers at it.)

## Test it

Offline (no real call), simulate Vobiz's webhook with a `POST`:

```bash theme={null}
curl -X POST localhost:8001/answer -d "From=918888800001" -d "To=919000000001"
```

Expected response, dial the customer, show `M2` as caller ID:

```xml theme={null}
<Response><Dial callerId="919000000002" timeout="30"><Number>918888800002</Number></Dial></Response>
```

An unregistered caller is rejected:

```bash theme={null}
curl -X POST localhost:8001/answer -d "From=910000000000" -d "To=919000000001"
# → <Response><Speak>Sorry, this number is not authorised…</Speak><Hangup reason="rejected"/></Response>
```

Then place a **real** call: from the agent phone, dial `M1`, the customer's phone should ring showing `M2`.

## Troubleshooting

<AccordionGroup>
  <Accordion title="The call connects but the recipient sees a real number, not the masking number">
    The `callerId` on `<Dial>` must be a Vobiz DID you own. Confirm `leg.caller_id_shown` resolves to `M1`/`M2` (your masking numbers), not the real `FE`/`CUSTOMER` values. Using a number you don't own is rejected as `Unknown Caller ID` (hangup code `3030`, see [Hangup Causes](/docs/concepts/hangup-causes)).
  </Accordion>

  <Accordion title="Every call is rejected as 'not authorised'">
    `resolve()` requires the `From` number to match the registered caller for that masking number. Check the caller is dialing from their registered handset and that `FE`/`CUSTOMER` in `.env` match the real numbers (matching uses the last 10 digits, so country-code formatting is tolerant but the digits must match).
  </Accordion>

  <Accordion title="Vobiz never hits my webhook">
    Verify `PUBLIC_BASE_URL` is reachable over **HTTPS** and that `setup_live.py` attached the application to both DIDs. A non-2xx or unreachable Answer URL fails with code `7011`; an invalid XML response fails with `8011`, see [Hangup Causes](/docs/concepts/hangup-causes).
  </Accordion>

  <Accordion title="The bridge takes too long or drops">
    Your `/answer` handler must respond well within the webhook timeout (aim for sub-second). Keep the mapping in fast in-memory or cache storage and avoid slow DB calls on the hot path.
  </Accordion>
</AccordionGroup>

## What's next

* **Expire mappings.** Create a pairing when a transaction starts and remove it when the order is delivered or the ride ends, after that, dialing the masking number connects to nothing.
* **Scale beyond one pair.** Reuse a pool of DIDs across many simultaneous pairings by keying the mapping on (masking number + caller) and rotating numbers.
* **Add recording or IVR.** Compose the masked leg with [call recording](/docs/solutions/call-recording) or a [cloud IVR](/docs/solutions/cloud-ivr) greeting before bridging.
* **Validate callbacks.** [Verify webhook authenticity](/docs/concepts/validating-callbacks) before acting on a request in production.

<Card title="Number masking, the use case" icon="user-shield" href="/docs/solutions/number-masking">
  See where two-way masking fits, ride-hailing, delivery, marketplaces, and how Vobiz powers it.
</Card>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.