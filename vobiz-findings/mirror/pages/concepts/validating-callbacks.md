> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Validating Callbacks

> Verify that every callback your server receives genuinely came from Vobiz by checking the HMAC signatures sent in each request.

Every callback Vobiz sends to your endpoint includes HMAC signatures in the request headers. Validating these signatures proves the request came from Vobiz and was not tampered with in transit.

<Info>
  **Your auth token is the signing key.** Vobiz uses your account's auth token (visible in the [Vobiz Console](https://console.vobiz.ai)) to sign each callback. Keep it secret - anyone who has it can forge valid signatures.
</Info>

## Signature headers

Vobiz sends the following headers with every callback:

| Header | Description |
| - | - |
| `X-Vobiz-Signature` | V1 - HMAC-SHA1, base64-encoded (legacy, included for backwards compatibility) |
| `X-Vobiz-Signature-V2` | V2 - HMAC-SHA256, base64-encoded |
| `X-Vobiz-Signature-V2-Nonce` | Random 20-digit nonce used to produce the V2 signature |
| `X-Vobiz-Signature-MA-V2` | V2 signed with the **parent (main) account** auth token - present for sub-account callbacks |
| `X-Vobiz-Signature-V3` | V3 - HMAC-SHA256, base64-encoded |
| `X-Vobiz-Signature-V3-Nonce` | Random 20-digit nonce used to produce the V3 signature |
| `X-Vobiz-Signature-MA-V3` | V3 signed with the **parent (main) account** auth token - present for sub-account callbacks |

<Tip>
  **Recommended:** Validate `X-Vobiz-Signature-V2` or `X-Vobiz-Signature-V3`. Both use HMAC-SHA256 and are the actively maintained signature schemes. V1 (HMAC-SHA1) is provided only for legacy compatibility.
</Tip>

## How signatures are computed

### V2 signature

1. Take your callback URL and strip all query parameters to get the **base URL** (e.g. `https://your-domain.com/webhook`).
2. Concatenate: `baseURL + nonce` (where nonce is the value of `X-Vobiz-Signature-V2-Nonce`).
3. Compute `HMAC-SHA256` of that string using your auth token as the key.
4. Base64-encode the result.

```
X-Vobiz-Signature-V2 = base64( HMAC-SHA256( key=authToken, msg=baseURL + nonce ) )
```

### V3 signature

Identical to V2 except the nonce is joined to the base URL with a `.` separator:

```
X-Vobiz-Signature-V3 = base64( HMAC-SHA256( key=authToken, msg=baseURL + "." + nonce ) )
```

### Multi-account (MA) variants

<Warning>
  **Signature headers are emitted only when the callback URL has auth credentials
  configured on it.** If no credentials are set for that URL, the callback arrives
  with no signature headers at all - which is why some accounts observe the full
  set and others observe none. Coverage also varies by callback type.

  Configure credentials on your callback URLs before relying on signature
  validation, and fail closed if a signature you expect is absent.
</Warning>

<Note>
  The signature covers the **URL and a nonce**, never the request body. Voice
  webhooks are delivered as `application/x-www-form-urlencoded`, so any scheme that
  hashes a JSON body will not verify.
</Note>

For callbacks on sub-accounts, Vobiz additionally signs with the **parent account's** auth token and sends the result in `X-Vobiz-Signature-MA-V2` / `X-Vobiz-Signature-MA-V3`. The algorithm is identical - only the key differs. This lets you verify callbacks using either the sub-account or the main account auth token.

***

## Validation examples

<CodeGroup>
  ```python Python theme={null}
  import hmac
  import hashlib
  import base64
  from urllib.parse import urlparse, urlunparse

  def get_base_url(url: str) -> str:
      parsed = urlparse(url)
      return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))

  def validate_v2(callback_url: str, auth_token: str, request_headers: dict) -> bool:
      signature = request_headers.get("X-Vobiz-Signature-V2", "")
      nonce     = request_headers.get("X-Vobiz-Signature-V2-Nonce", "")

      base_url = get_base_url(callback_url)
      msg      = (base_url + nonce).encode()
      key      = auth_token.encode()

      expected = base64.b64encode(hmac.new(key, msg, hashlib.sha256).digest()).decode()
      return hmac.compare_digest(signature, expected)

  def validate_v3(callback_url: str, auth_token: str, request_headers: dict) -> bool:
      signature = request_headers.get("X-Vobiz-Signature-V3", "")
      nonce     = request_headers.get("X-Vobiz-Signature-V3-Nonce", "")

      base_url = get_base_url(callback_url)
      msg      = (base_url + "." + nonce).encode()
      key      = auth_token.encode()

      expected = base64.b64encode(hmac.new(key, msg, hashlib.sha256).digest()).decode()
      return hmac.compare_digest(signature, expected)

  # Usage (e.g. Flask)
  from flask import request, abort

  AUTH_TOKEN = "your_auth_token_here"

  @app.route("/webhook", methods=["POST"])
  def webhook():
      url = request.url
      if not validate_v2(url, AUTH_TOKEN, request.headers):
          abort(403, "Invalid signature")
      # ... handle event
  ```

  ```javascript Node.js theme={null}
  const crypto = require("crypto");

  function getBaseUrl(url) {
    const parsed = new URL(url);
    return `${parsed.protocol}//${parsed.host}${parsed.pathname}`;
  }

  function validateV2(callbackUrl, authToken, headers) {
    const signature = headers["x-vobiz-signature-v2"] ?? "";
    const nonce     = headers["x-vobiz-signature-v2-nonce"] ?? "";

    const baseUrl  = getBaseUrl(callbackUrl);
    const expected = crypto
      .createHmac("sha256", authToken)
      .update(baseUrl + nonce)
      .digest("base64");

    return crypto.timingSafeEqual(
      Buffer.from(signature),
      Buffer.from(expected)
    );
  }

  function validateV3(callbackUrl, authToken, headers) {
    const signature = headers["x-vobiz-signature-v3"] ?? "";
    const nonce     = headers["x-vobiz-signature-v3-nonce"] ?? "";

    const baseUrl  = getBaseUrl(callbackUrl);
    const expected = crypto
      .createHmac("sha256", authToken)
      .update(baseUrl + "." + nonce)
      .digest("base64");

    return crypto.timingSafeEqual(
      Buffer.from(signature),
      Buffer.from(expected)
    );
  }

  // Usage (Express)
  const AUTH_TOKEN = "your_auth_token_here";

  app.post("/webhook", (req, res) => {
    const callbackUrl = `${req.protocol}://${req.get("host")}${req.originalUrl}`;
    if (!validateV2(callbackUrl, AUTH_TOKEN, req.headers)) {
      return res.status(403).json({ error: "Invalid signature" });
    }
    // ... handle event
    res.sendStatus(200);
  });
  ```

  ```go Go theme={null}
  package main

  import (
  	"crypto/hmac"
  	"crypto/sha256"
  	"encoding/base64"
  	"fmt"
  	"net/http"
  	"net/url"
  )

  func getBaseURL(rawURL string) (string, error) {
  	parsed, err := url.Parse(rawURL)
  	if err != nil {
  		return "", err
  	}
  	return fmt.Sprintf("%s://%s%s", parsed.Scheme, parsed.Host, parsed.Path), nil
  }

  func computeHMAC(key, msg string) string {
  	h := hmac.New(sha256.New, []byte(key))
  	h.Write([]byte(msg))
  	return base64.StdEncoding.EncodeToString(h.Sum(nil))
  }

  func validateV2(callbackURL, authToken string, headers http.Header) bool {
  	signature := headers.Get("X-Vobiz-Signature-V2")
  	nonce     := headers.Get("X-Vobiz-Signature-V2-Nonce")

  	baseURL, err := getBaseURL(callbackURL)
  	if err != nil {
  		return false
  	}

  	expected := computeHMAC(authToken, baseURL+nonce)
  	return hmac.Equal([]byte(signature), []byte(expected))
  }

  func validateV3(callbackURL, authToken string, headers http.Header) bool {
  	signature := headers.Get("X-Vobiz-Signature-V3")
  	nonce     := headers.Get("X-Vobiz-Signature-V3-Nonce")

  	baseURL, err := getBaseURL(callbackURL)
  	if err != nil {
  		return false
  	}

  	expected := computeHMAC(authToken, baseURL+"."+nonce)
  	return hmac.Equal([]byte(signature), []byte(expected))
  }

  // Usage
  const authToken = "your_auth_token_here"

  func webhookHandler(w http.ResponseWriter, r *http.Request) {
  	callbackURL := "https://your-domain.com" + r.URL.RequestURI()
  	if !validateV2(callbackURL, authToken, r.Header) {
  		http.Error(w, "Invalid signature", http.StatusForbidden)
  		return
  	}
  	// ... handle event
  	w.WriteHeader(http.StatusOK)
  }
  ```

  ```ruby Ruby theme={null}
  require "openssl"
  require "base64"
  require "uri"

  def get_base_url(url)
    uri = URI.parse(url)
    "#{uri.scheme}://#{uri.host}#{uri.path}"
  end

  def validate_v2(callback_url, auth_token, headers)
    signature = headers["X-Vobiz-Signature-V2"].to_s
    nonce     = headers["X-Vobiz-Signature-V2-Nonce"].to_s

    base_url = get_base_url(callback_url)
    expected = Base64.strict_encode64(
      OpenSSL::HMAC.digest("SHA256", auth_token, base_url + nonce)
    )

    ActiveSupport::SecurityUtils.secure_compare(signature, expected)
  end

  def validate_v3(callback_url, auth_token, headers)
    signature = headers["X-Vobiz-Signature-V3"].to_s
    nonce     = headers["X-Vobiz-Signature-V3-Nonce"].to_s

    base_url = get_base_url(callback_url)
    expected = Base64.strict_encode64(
      OpenSSL::HMAC.digest("SHA256", auth_token, "#{base_url}.#{nonce}")
    )

    ActiveSupport::SecurityUtils.secure_compare(signature, expected)
  end
  ```
</CodeGroup>

***

## Sub-account callbacks

If your Vobiz account uses sub-accounts, callback requests include both the sub-account signature and the parent (main) account signature. You can validate using either auth token.

| Header | Signed with |
| - | - |
| `X-Vobiz-Signature-V2` | Sub-account auth token |
| `X-Vobiz-Signature-MA-V2` | Parent account auth token |
| `X-Vobiz-Signature-V3` | Sub-account auth token |
| `X-Vobiz-Signature-MA-V3` | Parent account auth token |

The algorithm for MA variants is identical - only the key differs. Use the same validation code, substituting your parent account auth token as the key.

***

## Best practices

<Warning>
  Always use **constant-time comparison** when comparing signatures. Standard string equality (`==`) is vulnerable to timing attacks. Use `hmac.compare_digest` (Python), `crypto.timingSafeEqual` (Node.js), or `hmac.Equal` (Go).
</Warning>

* **Validate on every request.** Reject any callback missing the signature headers with HTTP 403.
* **Use HTTPS.** Plaintext HTTP exposes the nonce and signature, which an attacker could replay before you process the request.
* **Check the nonce is fresh (optional but recommended).** Nonces are randomly generated per request, not time-based, so replay protection requires you to store and check seen nonces for a short window (e.g. 5 minutes).
* **Prefer V2 or V3 over V1.** V1 uses HMAC-SHA1, which is weaker than SHA-256.
* **Rotate your auth token if compromised.** Rotating your auth token immediately invalidates all signatures computed with the old key.

<CardGroup cols={2}>
  <Card title="Callbacks overview" icon="webhook" href="/docs/concepts/callbacks">
    Understand how Vobiz delivers callbacks and what parameters to expect.
  </Card>

  <Card title="Callback configurations" icon="gear" href="/docs/concepts/callback-configurations">
    Configure callback URLs, methods, and retry behaviour for your applications.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.