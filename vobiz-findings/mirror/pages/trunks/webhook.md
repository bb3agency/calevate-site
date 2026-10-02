> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Trunk Webhooks

> Configure HTTP webhooks on Vobiz SIP trunks to receive real-time call events globally - call admitted, rejected, or ended with duration, cost, and quality metrics.

Vobiz supports real-time HTTP webhook notifications on SIP trunk calls. Configure a webhook URL on any trunk to receive callbacks for two events: when a call is initiated (admitted or rejected) and when a call ends (with full details including duration, cost, and quality metrics).

<Info>
  **Configure in the Console**

  Webhook URL and method are configured per trunk in the [Vobiz Console → SIP → Outbound Trunks](https://console.vobiz.ai/app/sip/out/trunks). You can also set them when creating or updating a trunk via the API.
</Info>

## Configuration

Each trunk can optionally have a webhook configured with two fields:

| Field | Type | Description |
| - | - | - |
| `webhook_url` | string | Your publicly accessible HTTP endpoint (max 500 characters). Private IPs, localhost, and AWS metadata endpoints are blocked. |
| `webhook_method` | string | HTTP method for the callback. Accepts `POST` (default) or `GET`. |

## Security validation

When a webhook URL is configured, Vobiz validates it against SSRF attacks before accepting it. The following are blocked:

* **Schemes:** Only http and https are allowed.
* **Localhost:** 127.0.0.1, ::1, and 0.0.0.0 are blocked.
* **Private IP ranges:** 10.0.0.0/8, 172.16.0.0/12, and 192.168.0.0/16 are blocked.
* **Link-local addresses:** 169.254.0.0/16 is blocked, including the AWS metadata endpoint (169.254.169.254).
* **IPv6:** ULA (fc00::/7) and multicast (ff00::/8) addresses are blocked.

## Webhook events

Vobiz delivers two event types to your configured webhook URL.

### CallInitiated

Fired for **every outbound call attempt** during call admission, whether the call is allowed or rejected. Use this event for real-time call monitoring and rejection alerting.

**Fires when:**

* Call is admitted - `Allowed: true`
* Call is rejected - `Allowed: false` with a `Reason`

**Possible rejection reasons:**

* Insufficient balance
* CLI ownership validation failed
* Aadhaar verification pending
* KYC verification required
* Rate limit or concurrent call limit exceeded
* No routes available

<CodeGroup>
  ```json Payload - allowed call theme={null}
  {
    "Event": "CallInitiated",
    "CallUUID": "aabbccdd-1234-5678-90ab-cdef12345678",
    "RequestID": "aabbccdd-1234-5678-90ab-cdef12345678",
    "Timestamp": "2026-03-18T12:00:00Z",
    "From": "+919876543210",
    "To": "+918012345678",
    "Direction": "outbound",
    "Status": "initiated",
    "auth_id": "MA_XXXXXXXX",
    "TrunkID": "aabbccdd-1234-5678-90ab-cdef12345678",
    "Domain": "1486467e.sip.vobiz.ai",
    "SourceIP": "10.0.0.1",
    "SIPCallID": "abc123@10.0.0.1",
    "Allowed": true,
    "Reason": ""
  }
  ```

  ```json Payload - rejected call theme={null}
  {
    "Event": "CallInitiated",
    "CallUUID": "aabbccdd-1234-5678-90ab-cdef12345678",
    "RequestID": "aabbccdd-1234-5678-90ab-cdef12345678",
    "Timestamp": "2026-03-18T12:00:00Z",
    "From": "+919876543210",
    "To": "+918012345678",
    "Direction": "outbound",
    "Status": "initiated",
    "auth_id": "MA_XXXXXXXX",
    "TrunkID": "aabbccdd-1234-5678-90ab-cdef12345678",
    "Domain": "1486467e.sip.vobiz.ai",
    "SourceIP": "10.0.0.1",
    "SIPCallID": "abc123@10.0.0.1",
    "Allowed": false,
    "Reason": "Insufficient balance: 0.50 INR"
  }
  ```
</CodeGroup>

### Hangup

Fired when a call ends. Includes the full call record - duration, billable seconds, ring time, cost, currency, voice quality (MOS), the bridged-leg UUID, and hangup cause details (name, code, and which party released the call).

| Field | Type | Description |
| - | - | - |
| `Duration` | integer | Total call duration in seconds (ring + talk time). |
| `Billsec` | integer | Billable seconds - time the call was actually connected. |
| `RingTime` | integer | Time in seconds the call rang before being answered. |
| `Cost` | float | Call cost deducted from account balance. |
| `Currency` | string | Currency of the cost (e.g. INR). |
| `MOS` | float | Mean Opinion Score - voice quality (1.0–5.0, higher is better). |
| `BridgeUUID` | string | UUID of the bridged (B-leg) call. |
| `HangupCauseName` | string | Human-readable hangup cause (e.g. `Normal Hangup`). |
| `HangupCauseCode` | integer | Numeric hangup cause code (e.g. `4000`). See [Hangup Causes](/docs/concepts/hangup-causes). |
| `HangupSource` | string | Which party released the call - `Caller` or `Callee`. |

```json Hangup Payload theme={null}
{
  "Event": "Hangup",
  "CallUUID": "aabbccdd-1234-5678-90ab-cdef12345678",
  "RequestID": "aabbccdd-1234-5678-90ab-cdef12345678",
  "Timestamp": "2026-03-18T12:00:08Z",
  "From": "+919876543210",
  "To": "+918012345678",
  "Direction": "outbound",
  "Status": "completed",
  "AccountId": "MA_XXXXXXXX",
  "TrunkID": "aabbccdd-1234-5678-90ab-cdef12345678",
  "Domain": "1486467e.sip.vobiz.ai",
  "SourceIP": "10.0.0.1",
  "SIPCallID": "abc123@10.0.0.1",
  "BridgeUUID": "bbccddee-2345-6789-01bc-def234567890",
  "Reason": "NORMAL_CLEARING",
  "StartTime": "2026-03-18T12:00:00Z",
  "EndTime": "2026-03-18T12:00:08Z",
  "Duration": 8,
  "Billsec": 3,
  "RingTime": 5,
  "Cost": 0.07,
  "Currency": "INR",
  "MOS": 4.5,
  "HangupCauseName": "Normal Hangup",
  "HangupCauseCode": 4000,
  "HangupSource": "Caller"
}
```

## HTTP request details

### Headers sent with every webhook

| Header | Value |
| - | - |
| `Content-Type` | application/json |
| `User-Agent` | Vobiz-Vapor/1.0 |
| `X-Vobiz-Event` | CallInitiated or Hangup |
| `X-Vobiz-Request-ID` | Unique request identifier |

### Timeouts

| Phase | Timeout |
| - | - |
| Call admission webhook (CallInitiated) | 10 seconds |
| Hangup webhook - CDR to Vapor | 5 seconds |
| Hangup webhook - Vapor to customer endpoint | 10 seconds |

### Verify the payload

Because webhooks are delivered to a publicly reachable URL, verify each request before trusting it. Compute an HMAC-SHA256 over the **raw** request body using your trunk's signing secret and compare it in constant time against the signature header on the request. Use `X-Vobiz-Request-ID` to de-duplicate retries and tie the `CallInitiated` and `Hangup` events for the same call together.

<CodeGroup>
  ```python Python (Flask) theme={null}
  import hmac, hashlib
  from flask import request, abort

  SIGNING_SECRET = "your-trunk-signing-secret"

  def verify(raw_body: bytes, signature: str) -> bool:
      expected = hmac.new(SIGNING_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
      return hmac.compare_digest(expected, signature or "")

  @app.post("/vobiz/trunk-webhook")
  def handle():
      raw = request.get_data()  # raw bytes, before JSON parsing
      sig = request.headers.get("X-Vobiz-Signature", "")
      if not verify(raw, sig):
          abort(401)
      event = request.get_json()
      # event["Event"] is "CallInitiated" or "Hangup"
      return "", 200
  ```

  ```javascript Node.js (Express) theme={null}
  import crypto from "crypto";

  const SIGNING_SECRET = "your-trunk-signing-secret";

  function verify(rawBody, signature) {
    const expected = crypto
      .createHmac("sha256", SIGNING_SECRET)
      .update(rawBody)
      .digest("hex");
    return crypto.timingSafeEqual(
      Buffer.from(expected),
      Buffer.from(signature || "")
    );
  }

  // Mount with express.raw({ type: "application/json" }) so rawBody stays intact.
  app.post("/vobiz/trunk-webhook", (req, res) => {
    const sig = req.header("X-Vobiz-Signature") || "";
    if (!verify(req.body, sig)) return res.sendStatus(401);
    const event = JSON.parse(req.body.toString());
    res.sendStatus(200);
  });
  ```
</CodeGroup>

<Warning>
  **Confirm the signature header and secret.** The exact signature header name and the per-trunk signing secret are configured in the Console; confirm both against your account before enforcing verification. The snippets above show the HMAC-SHA256 pattern - keep the comparison constant-time and always hash the raw body, not the re-serialized JSON.
</Warning>

## Behavior & reliability

### Non-blocking

All webhooks are sent **asynchronously**. Webhook requests never delay the SIP call flow - call admission and CDR processing proceed independently of webhook delivery.

### Fail-open

Webhook failures do **not** affect calls:

* If the webhook URL is unreachable, the call still proceeds normally.
* Non-2xx responses are logged but do not affect the call.
* Network timeouts are logged as errors with no retry.

### Informational only

Webhooks are **one-way notifications**. The response from your endpoint does not influence call routing, billing, or any platform behavior. You cannot accept or reject calls via a webhook response.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.