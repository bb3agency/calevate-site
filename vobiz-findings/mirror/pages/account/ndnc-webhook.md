> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# NDNC Webhook

> Receive real-time UCC / NDNC complaint alerts on your own HTTPS endpoint. Send your webhook URL and shared secret to ndnc@vobiz.ai to activate, then verify the X-VoBiz-Signature on every request.

The **NDNC webhook** pushes real-time **UCC (Unsolicited Commercial Communication) complaint alerts** to your own systems. Whenever a complaint is processed against your account, Vobiz sends a signed `POST` request to your HTTPS endpoint with the complaint details, so you can react immediately - pause a campaign, scrub a number, or open an internal ticket - instead of waiting to discover it in the console.

<Note>
  This is a webhook **you receive**, not a REST endpoint you call. It is activated manually by the Vobiz team - there is no self-serve API to register it yet. See [UCC Management](/docs/compliance/india/ucc) for the regulatory background on complaints and NDNC.
</Note>

## Activate the webhook

To turn on notifications, email your **webhook URL** and **shared secret** to **[ndnc@vobiz.ai](mailto:ndnc@vobiz.ai)**, keeping **[piyush@vobiz.ai](mailto:piyush@vobiz.ai)** and **[goutham@vobiz.ai](mailto:goutham@vobiz.ai)** in CC.

<Steps>
  <Step title="Prepare what you'll send">
    | # | What | Example |
    | - | - | - |
    | 1 | **Webhook URL** - your HTTPS endpoint that will receive complaints | `https://hooks.yourcompany.com/vobiz-complaints` |
    | 2 | **Shared secret** - a string you generate, used to sign requests | `your_secret_key_here` |
  </Step>

  <Step title="Email the Vobiz team">
    Send both values to **[ndnc@vobiz.ai](mailto:ndnc@vobiz.ai)**, with **[piyush@vobiz.ai](mailto:piyush@vobiz.ai)** and **[goutham@vobiz.ai](mailto:goutham@vobiz.ai)** in CC.

    <Card title="Email ndnc@vobiz.ai (CC piyush, goutham)" icon="envelope" href="mailto:ndnc@vobiz.ai?cc=piyush@vobiz.ai,goutham@vobiz.ai&subject=NDNC%20Webhook%20Setup&body=Webhook%20URL%3A%20%0AShared%20Secret%3A%20">
      Opens a pre-addressed email - just fill in your webhook URL and shared secret.
    </Card>
  </Step>

  <Step title="Wait for confirmation">
    The Vobiz team registers your endpoint and confirms once notifications are live.
  </Step>
</Steps>

<Warning>
  Treat the shared secret like a password - send it only to **[ndnc@vobiz.ai](mailto:ndnc@vobiz.ai)** over email, never paste it into client-side code, screenshots, or public repositories.
</Warning>

## How it works

When a complaint is processed against your account, Vobiz sends a `POST` request to your webhook URL with the complaint details in JSON. All requests originate from a single, dedicated IP address.

<Info>
  **Vobiz outbound IP:** `15.207.141.89` - whitelist this on your firewall if your infrastructure requires it.
</Info>

| Property | Value |
| - | - |
| Method | `POST` |
| Content-Type | `application/json` |
| Signature header | `X-VoBiz-Signature` |
| Timeout | 5 seconds |
| Origin IP | `15.207.141.89` |

## Payload structure

Every webhook `POST` contains a JSON body in this format:

```json Example payload theme={null}
{
  "accountName": "Your Company Name",
  "totalComplaints": 2,
  "complaints": [
    {
      "urn": "XXXXXXXXXXXXXXXXXXXXXXXXX",
      "did": "9876543210",
      "complainantNumber": "9123456789",
      "complaintDate": "2026-06-08",
      "description": "Received telemarketing call in the SPAM category",
      "accountId": "MA_XXXXXXXX",
      "accountName": "Your Company Name",
      "accountEmail": "contact@yourcompany.com"
    }
  ]
}
```

### Field reference

| Field | Type | Description |
| - | - | - |
| `accountName` | string | Your registered account name with Vobiz. |
| `totalComplaints` | integer | Total number of complaints in this notification. |
| `complaints` | array | List of individual complaint records. |
| `complaints[].urn` | string | Unique system reference number assigned by the regulator. |
| `complaints[].did` | string | The DID (phone number) the complaint is against, without country code. |
| `complaints[].complainantNumber` | string | The complainant's phone number. |
| `complaints[].complaintDate` | string | Date the complaint was filed (`YYYY-MM-DD`). |
| `complaints[].description` | string | Short description / category of the complaint. |
| `complaints[].accountId` | string | Your Vobiz account ID. |
| `complaints[].accountName` | string | Your Vobiz account name. |
| `complaints[].accountEmail` | string | Your registered email on the Vobiz account. |

## Verifying the signature

Every request includes an `X-VoBiz-Signature` header - an HMAC-SHA256 signature computed over the request body using your shared secret. Always verify it before processing any payload.

```text How the signature is computed theme={null}
X-VoBiz-Signature = HMAC-SHA256(shared_secret, raw_request_body)
```

The body is serialised as compact JSON with no extra spaces before signing. Verify against the **raw request body bytes** - never re-serialise parsed JSON.

<CodeGroup>
  ```javascript Node.js theme={null}
  const crypto = require('crypto');

  function verifyVobizWebhook(rawBody, receivedSignature, sharedSecret) {
    const expected = crypto
      .createHmac('sha256', sharedSecret)
      .update(rawBody) // raw body bytes - do not re-serialise
      .digest('hex');
    return crypto.timingSafeEqual(
      Buffer.from(expected),
      Buffer.from(receivedSignature)
    );
  }

  app.post('/vobiz-complaints', express.raw({ type: 'application/json' }), (req, res) => {
    const sig = req.headers['x-vobiz-signature'];
    if (!verifyVobizWebhook(req.body, sig, 'YOUR_SHARED_SECRET'))
      return res.status(401).send('Invalid signature');

    const data = JSON.parse(req.body);
    res.status(200).send('OK');
  });
  ```

  ```python Python (Flask) theme={null}
  import hmac, hashlib
  from flask import request

  def verify_vobiz_webhook(raw_body, received_signature, shared_secret):
      expected = hmac.new(
          shared_secret.encode(),
          raw_body,  # raw request body bytes - do not re-serialise
          hashlib.sha256
      ).hexdigest()
      return hmac.compare_digest(expected, received_signature)

  @app.route('/vobiz-complaints', methods=['POST'])
  def handle_webhook():
      sig = request.headers.get('X-VoBiz-Signature', '')
      if not verify_vobiz_webhook(request.data, sig, 'YOUR_SHARED_SECRET'):
          return 'Invalid signature', 401
      data = request.get_json()
      return 'OK', 200
  ```
</CodeGroup>

<Warning>
  Always verify against the **raw request body bytes** - never re-serialise parsed JSON. Use a timing-safe comparison (`hmac.compare_digest` / `timingSafeEqual`) to prevent timing attacks.
</Warning>

## Responding to a webhook

Your endpoint must return an HTTP `2xx` status (e.g. `200 OK`) within **5 seconds** to acknowledge receipt. If your processing takes longer, acknowledge immediately and handle the data asynchronously in the background.

## Choosing a strong shared secret

Your shared secret is the key used to sign every notification. Keep it confidential - treat it like a password.

* Use a randomly generated string of at least 32 characters.
* Generate one with `openssl rand -hex 32`.
* Do not reuse passwords or other credentials as the secret.
* Never expose it in client-side code or public repositories.

## Setup checklist

<Steps>
  <Step title="Stand up an HTTPS endpoint">
    Accept `POST` requests with a JSON body.
  </Step>

  <Step title="Generate a strong shared secret">
    Run `openssl rand -hex 32`.
  </Step>

  <Step title="Send your details to Vobiz">
    Email your webhook URL and shared secret to **[ndnc@vobiz.ai](mailto:ndnc@vobiz.ai)**, CC **[piyush@vobiz.ai](mailto:piyush@vobiz.ai)** and **[goutham@vobiz.ai](mailto:goutham@vobiz.ai)**.
  </Step>

  <Step title="Whitelist the origin IP">
    Allow `15.207.141.89` on your firewall if required.
  </Step>

  <Step title="Verify signatures">
    Implement `X-VoBiz-Signature` verification using your shared secret.
  </Step>

  <Step title="Acknowledge quickly">
    Return HTTP `200` within 5 seconds of receiving a webhook.
  </Step>
</Steps>

For questions or setup assistance, contact [ndnc@vobiz.ai](mailto:ndnc@vobiz.ai?cc=piyush@vobiz.ai,goutham@vobiz.ai\&subject=NDNC%20Webhook%20Setup).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.