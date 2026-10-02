> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Webhooks & signature validation

> Migrate your Plivo webhook handlers and signature verification to Vobiz - the params and the HMAC-SHA256 scheme are nearly identical, you mostly swap header names.

If you already validate Plivo webhooks, moving to Vobiz is a small change. Both providers POST callbacks as `application/x-www-form-urlencoded`, both carry the same kind of params, and both sign requests with **HMAC-SHA256 over the base URL plus a nonce**. In most cases you swap the header names and point your validator at Vobiz's headers.

## Header mapping

The signing scheme is identical - HMAC-SHA256 keyed by your auth token, base64-encoded, with a random nonce sent in a companion header. Only the header names change.

| Plivo | Vobiz | Scheme |
| - | - | - |
| `X-Plivo-Signature-V3` | `X-Vobiz-Signature-V3` | HMAC-SHA256 of `baseURL + "." + nonce` |
| `X-Plivo-Signature-V3-Nonce` | `X-Vobiz-Signature-V3-Nonce` | Random nonce used in the V3 signature |
| *(no direct equivalent)* | `X-Vobiz-Signature-V2` | HMAC-SHA256 of `baseURL + nonce` |
| *(no direct equivalent)* | `X-Vobiz-Signature-V2-Nonce` | Random nonce used in the V2 signature |
| `X-Plivo-Signature-V2` (legacy, HMAC-SHA1) | `X-Vobiz-Signature` (legacy, HMAC-SHA1) | Backwards compatibility only - avoid |

<Note>
  Plivo's `plivo.utils.validate_v3_signature(...)` and Vobiz's V3 validation compute the **same thing**: `base64(HMAC-SHA256(authToken, baseURL + "." + nonce))`. Vobiz also offers a V2 variant that joins the nonce without the `.` separator. Validate `X-Vobiz-Signature-V2` or `X-Vobiz-Signature-V3` - both are actively maintained HMAC-SHA256 schemes.
</Note>

## Before / after: verifying the signature

The Plivo SDK ships a helper (`validate_v3_signature`). Vobiz doesn't require an SDK for this - the verification is a few lines of HMAC. Below, the "before" column shows the Plivo approach and the "after" column shows the equivalent Vobiz V2/V3 verification.

<CodeGroup>
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
          request.form.to_dict(),
          request.headers.get("X-Plivo-Signature-V3", ""),
      )
      if not valid:
          abort(403, "Invalid signature")
      # ... handle event

  # ---------- AFTER: Vobiz ----------
  import hmac
  import hashlib
  import base64
  from urllib.parse import urlparse, urlunparse
  from flask import request, abort

  AUTH_TOKEN = "your_vobiz_auth_token"

  def get_base_url(url: str) -> str:
      parsed = urlparse(url)
      return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))

  def validate_v2(callback_url: str, auth_token: str, headers: dict) -> bool:
      signature = headers.get("X-Vobiz-Signature-V2", "")
      nonce     = headers.get("X-Vobiz-Signature-V2-Nonce", "")
      msg       = (get_base_url(callback_url) + nonce).encode()
      expected  = base64.b64encode(
          hmac.new(auth_token.encode(), msg, hashlib.sha256).digest()
      ).decode()
      return hmac.compare_digest(signature, expected)

  def validate_v3(callback_url: str, auth_token: str, headers: dict) -> bool:
      signature = headers.get("X-Vobiz-Signature-V3", "")
      nonce     = headers.get("X-Vobiz-Signature-V3-Nonce", "")
      msg       = (get_base_url(callback_url) + "." + nonce).encode()
      expected  = base64.b64encode(
          hmac.new(auth_token.encode(), msg, hashlib.sha256).digest()
      ).decode()
      return hmac.compare_digest(signature, expected)

  @app.route("/webhook", methods=["POST"])
  def webhook_vobiz():
      if not validate_v2(request.url, AUTH_TOKEN, request.headers):
          abort(403, "Invalid signature")
      # ... handle event (Ring, StartApp, Hangup)
  ```

  ```javascript Node.js (Express) theme={null}
  // ---------- BEFORE: Plivo ----------
  const plivo = require("plivo");

  const AUTH_TOKEN = "your_plivo_auth_token";

  app.post("/webhook", (req, res) => {
    const url = `${req.protocol}://${req.get("host")}${req.originalUrl}`;
    const valid = plivo.validateV3Signature(
      req.method,
      url,
      req.headers["x-plivo-signature-v3-nonce"] ?? "",
      AUTH_TOKEN,
      req.body,
      req.headers["x-plivo-signature-v3"] ?? ""
    );
    if (!valid) return res.status(403).json({ error: "Invalid signature" });
    // ... handle event
    res.sendStatus(200);
  });

  // ---------- AFTER: Vobiz ----------
  const crypto = require("crypto");

  const AUTH_TOKEN = "your_vobiz_auth_token";

  function getBaseUrl(url) {
    const parsed = new URL(url);
    return `${parsed.protocol}//${parsed.host}${parsed.pathname}`;
  }

  function validateV2(callbackUrl, authToken, headers) {
    const signature = headers["x-vobiz-signature-v2"] ?? "";
    const nonce     = headers["x-vobiz-signature-v2-nonce"] ?? "";
    const expected  = crypto
      .createHmac("sha256", authToken)
      .update(getBaseUrl(callbackUrl) + nonce)
      .digest("base64");
    return crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected));
  }

  function validateV3(callbackUrl, authToken, headers) {
    const signature = headers["x-vobiz-signature-v3"] ?? "";
    const nonce     = headers["x-vobiz-signature-v3-nonce"] ?? "";
    const expected  = crypto
      .createHmac("sha256", authToken)
      .update(getBaseUrl(callbackUrl) + "." + nonce)
      .digest("base64");
    return crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected));
  }

  app.post("/webhook", (req, res) => {
    const callbackUrl = `${req.protocol}://${req.get("host")}${req.originalUrl}`;
    if (!validateV2(callbackUrl, AUTH_TOKEN, req.headers)) {
      return res.status(403).json({ error: "Invalid signature" });
    }
    // ... handle event (Ring, StartApp, Hangup)
    res.sendStatus(200);
  });
  ```
</CodeGroup>

<Note>
  Your callback **params** carry over almost unchanged - `CallUUID`, `From`, `To`, `Direction`, `CallStatus`, and friends are the same `application/x-www-form-urlencoded` fields you read from Plivo. The main thing to relabel is event names: Vobiz sends `Ring`, `StartApp` (answer), and `Hangup`. See [Validating callbacks](/docs/concepts/validating-callbacks) for the canonical signature reference and [Callbacks](/docs/concepts/callbacks) for the full param and event list.
</Note>

## Sub-accounts

If you use sub-accounts, Vobiz also signs each callback with the **parent (main) account** auth token and sends it in `X-Vobiz-Signature-MA-V2` / `X-Vobiz-Signature-MA-V3`. The algorithm is identical to V2/V3 - only the key differs - so you can reuse the same validation code with your parent account auth token. This lets you verify callbacks using either the sub-account or the main account token.

## Next

<CardGroup cols={2}>
  <Card title="Migration gotchas" icon="triangle-exclamation" href="/docs/guides/plivo-to-vobiz/gotchas">
    Edge cases and differences to watch for when moving from Plivo to Vobiz.
  </Card>

  <Card title="Plivo to Vobiz overview" icon="right-left" href="/docs/guides/plivo-to-vobiz">
    Back to the full migration guide.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.