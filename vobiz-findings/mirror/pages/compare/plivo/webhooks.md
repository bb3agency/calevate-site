> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Plivo vs Vobiz: Webhooks, Callbacks & Signature Validation

> Map Plivo answer/ring/hangup callbacks and X-Plivo-Signature-V3 (HMAC) verification to Vobiz answer_url events and X-Vobiz-Signature-V2/V3. Includes before/after verification code for Python and Node.

Plivo and Vobiz handle voice webhooks almost identically: both POST `application/x-www-form-urlencoded` callbacks with the same call params, and both sign each request with an HMAC keyed by your auth token plus a nonce. Two things to know when mapping: Vobiz delivers `Ring` / `StartApp` / `Hangup` as events to the answer flow, and Vobiz V2/V3 sign the base URL + nonce.

## Callback URL & event mapping

| Plivo | Vobiz | Notes |
| - | - | - |
| `answer_url` (mandatory) | `answer_url` + `answer_method` | Returns XML to drive the call. |
| `hangup_url` + `hangup_method` | `hangup_url` + `hangup_method` | Fire-and-forget end-of-call notification; also emits a `Hangup` event. |
| `fallback_url` / `fallback_answer_url` | `fallback_answer_url` + `fallback_method` | Invoked when the primary answer URL is unreachable. |
| `action` attribute (`Dial`, `Record`, `GetInput`…) | `action` attribute (`Dial`, `Record`, `Gather`…) | Expects an XML response to continue. |
| `callbackUrl` attribute (notify-only) | `callbackUrl` / `callback_url` attribute | Async notification; no XML expected. |
| Event: answered | Event: `StartApp` | "Call answered." |
| Event: hangup | Event: `Hangup` | "Call ended." |
| Event: ringing | Event: `Ring` | "Call is ringing." |

## Signature header mapping

| Plivo | Vobiz | Scheme |
| - | - | - |
| `X-Plivo-Signature-V3` | `X-Vobiz-Signature-V3` | HMAC-SHA256, base64. Signs `baseURL + "." + nonce`. |
| `X-Plivo-Signature-V3-Nonce` | `X-Vobiz-Signature-V3-Nonce` | Random nonce for the V3 signature. |
| - | `X-Vobiz-Signature-V2` (+ `-Nonce`) | HMAC-SHA256, base64. Signs `baseURL + nonce` (no `.`). |
| `X-Plivo-Signature-Ma-V3` | `X-Vobiz-Signature-MA-V3` | Same scheme, signed with the **main (parent) account** token on sub-account callbacks. |
| `X-Plivo-Signature-V2` (legacy SHA1) | `X-Vobiz-Signature` (legacy SHA1) | Backwards compatibility only - avoid. |

<Note>
  **Signature scheme.** Vobiz V3 signs `baseURL + "." + nonce` (query params stripped); V2 signs `baseURL + nonce`. Verify Vobiz callbacks with the HMAC validator below.
</Note>

## Before / after: verifying the signature

On Vobiz, verifying a callback is a few lines of stdlib HMAC.

```python Python (Flask) theme={null}
# ---------- BEFORE: Plivo ----------
import plivo
from flask import request, abort

AUTH_TOKEN = "your_plivo_auth_token"

@app.route("/webhook", methods=["POST"])
def webhook_plivo():
    valid = plivo.utils.validate_v3_signature(
        request.method,
        request.url,
        request.headers.get("X-Plivo-Signature-V3-Nonce", ""),
        AUTH_TOKEN,
        request.headers.get("X-Plivo-Signature-V3", ""),
        request.form.to_dict(),   # Plivo hashes the POST params too
    )
    if not valid:
        abort(403, "Invalid signature")
    # ... handle event

# ---------- AFTER: Vobiz ----------
import hmac, hashlib, base64
from urllib.parse import urlparse, urlunparse
from flask import request, abort

AUTH_TOKEN = "your_vobiz_auth_token"

def base_url(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))  # strip query

def validate(url, token, headers, v3=True):
    sep = "." if v3 else ""
    sig_h   = "X-Vobiz-Signature-V3" if v3 else "X-Vobiz-Signature-V2"
    nonce_h = sig_h + "-Nonce"
    msg = (base_url(url) + sep + headers.get(nonce_h, "")).encode()
    expected = base64.b64encode(
        hmac.new(token.encode(), msg, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(headers.get(sig_h, ""), expected)

@app.route("/webhook", methods=["POST"])
def webhook_vobiz():
    if not validate(request.url, AUTH_TOKEN, request.headers, v3=True):
        abort(403, "Invalid signature")
    event = request.form.get("Event")   # Ring | StartApp | Hangup
    # ... handle event
    return "", 200
```

Callback params are the same names you read from Plivo - `CallUUID`, `From`, `To`, `Direction`, `CallStatus`, `HangupCause`, `Duration`, plus `Event` / `timestamp` / `auth_id` on every callback. See the [Vobiz XML request params](/docs/xml/request) and [Callbacks reference](/docs/concepts/callbacks).

## Key differences & gotchas

* **Signed string.** Vobiz V2/V3 hash the base URL + nonce, which proves the request origin and URL - validate incoming param values in your handler as usual.
* **Events instead of dedicated URLs.** Branch on the `Event` field for `Ring`, `StartApp`, and `Hangup`.
* **Header casing & compares.** Nonces are 20-digit strings; read headers case-insensitively and compare with `hmac.compare_digest` / `crypto.timingSafeEqual`, never `==`.
* **Main-account (MA) signatures.** Sub-account callbacks add a parent-signed header (`X-Vobiz-Signature-MA-V3`) - reuse the validator with the parent token.

<CardGroup cols={2}>
  <Card title="Validating callbacks" icon="shield-check" href="/docs/concepts/validating-callbacks">
    Canonical Vobiz signature reference with Python, Node, Go, and Ruby.
  </Card>

  <Card title="Migration gotchas" icon="triangle-exclamation" href="/docs/guides/plivo-to-vobiz/gotchas">
    Edge cases when moving from Plivo to Vobiz.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.