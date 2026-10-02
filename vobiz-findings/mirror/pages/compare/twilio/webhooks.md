> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Twilio Webhooks & Signatures → Vobiz

> Migrate Twilio voice webhooks to Vobiz: map request params (CallSid, From, To, Direction, CallStatus, Digits, SpeechResult) to Vobiz call params and Ring/StartApp/Hangup events, and swap X-Twilio-Signature (HMAC-SHA1 RequestValidator) for X-Vobiz-Signature-V3 (HMAC-SHA256 + nonce). Before/after Flask and Node code.

Twilio and Vobiz drive calls the same way: the platform makes an HTTP request to your app, you return XML, and each request is signed so you can prove it came from the platform. Migrating is a matter of renaming a few request parameters, branching on Vobiz's `Event` field instead of Twilio's separate callback URLs, and swapping Twilio's `X-Twilio-Signature` (HMAC-SHA1) validator for Vobiz's `X-Vobiz-Signature-V3` (HMAC-SHA256 + nonce). This page maps every piece and shows before/after validation code.

<Note>
  `AUTH_TOKEN` is your Vobiz Auth Token (the `api_key` you pass to the SDK is your Auth ID → `X-Auth-ID`; the Auth Token → `X-Auth-Token`). The same Auth Token is the HMAC key that signs your inbound webhooks.
</Note>

## Request parameter mapping

Twilio POSTs `application/x-www-form-urlencoded` params to your voice URL; Vobiz posts the same content type to your `answer_url`. The values you already read carry over under Vobiz names.

| Twilio param | Vobiz param | Notes |
| - | - | - |
| `CallSid` | `CallUUID` | Unique ID for the call leg. |
| `From` | `From` | Caller's number in E.164 (or caller ID you set for outbound). |
| `To` | `To` | Called party / your inbound number. |
| `Direction` (`inbound`, `outbound-api`, `outbound-dial`) | `Direction` (`inbound`, `outbound`) | Inbound calls arrive ringing; API-initiated calls arrive answered. |
| `CallStatus` (`ringing`, `in-progress`, `completed`, `busy`, `failed`, `no-answer`, `canceled`) | `CallStatus` (`ringing`, `in-progress`, `completed`, `busy`, `failed`, `timeout`, `no-answer`) | Same lifecycle vocabulary. |
| `ForwardedFrom` | `ForwardedFrom` | Present when the carrier passes it on forwarded calls. |
| `ParentCallSid` | `ALegUUID` | The originating leg's ID on outbound child legs. |
| `CallDuration` (status callback) | `Duration` | Wall-clock seconds; present after hangup. |
| - (Twilio bills separately) | `BillDuration` | Billed seconds, delivered on the same hangup payload. |
| `HangupCause` (via `DialCallStatus` / SIP `code`) | `HangupCause` | Standard telephony hangup cause on end-of-call. |
| `CallStatus=in-progress` after answer | `Event=StartApp` | Vobiz signals "answered / app started" as an event. |
| `StatusCallback` (`ringing`) | `Event=Ring` | Ringing notification. |
| `StatusCallback` (`completed`) | `Event=Hangup` | End-of-call notification. |

## `<Gather>` action-URL parameters

Twilio's `<Gather>` posts `Digits` and `SpeechResult` (plus `Confidence`) to its `action` URL. Vobiz's [`<Gather>`](/docs/xml/gather) posts the same input under Vobiz names.

| Twilio Gather param | Vobiz Gather param | Notes |
| - | - | - |
| `Digits` | `Digits` | DTMF entered, excluding `finishOnKey`. |
| `SpeechResult` | `Speech` | Transcribed speech result. |
| `Confidence` | `SpeechConfidenceScore` | 0.0–1.0 recognition confidence. |
| `input="dtmf speech"` | `inputType="dtmf speech"` | First input detected wins. |
| - | `InputType` | Vobiz also tells you which input type (`dtmf`/`speech`) fired. |

<Note>
  Twilio's `<Gather timeout=…>` becomes Vobiz's `executionTimeout`; `speechTimeout` becomes `speechEndTimeout`; `numDigits`, `finishOnKey`, and `hints` keep their names. Full attribute list: [Gather reference](/docs/xml/gather).
</Note>

## Callback flow: separate URLs → one `Event` field

Twilio uses a primary voice URL plus a separate `StatusCallback` for lifecycle events. Vobiz delivers lifecycle transitions to your flow as an `Event` value, so you branch on one field.

| Twilio | Vobiz | Meaning |
| - | - | - |
| Voice URL returns TwiML | `answer_url` + `answer_method` returns XML | Drives the call. |
| `StatusCallback` = `ringing` | `Event=Ring` | Call is ringing. |
| `StatusCallback` = `in-progress` | `Event=StartApp` | Call answered, app started. |
| `StatusCallback` = `completed` | `hangup_url` / `Event=Hangup` | Call ended. |
| `action` on a verb (Gather/Record/Dial) | `action` on the verb (Gather/Record/Dial) | Returns XML to continue the flow. |

## Signature validation: X-Twilio-Signature → X-Vobiz-Signature-V3

**Twilio** signs with **HMAC-SHA1** keyed by your Auth Token over the full URL (scheme, host, port, query) with every POST field appended in alphabetical order, base64-encoded, sent as `X-Twilio-Signature`. The `RequestValidator` helper reproduces the string and compares.

**Vobiz** signs with **HMAC-SHA256** keyed by your Auth Token over `baseURL + "." + nonce` (query stripped), base64-encoded, sent as `X-Vobiz-Signature-V3` with the random nonce in `X-Vobiz-Signature-V3-Nonce`.

| Twilio | Vobiz | Scheme |
| - | - | - |
| `X-Twilio-Signature` | `X-Vobiz-Signature-V3` | Twilio: HMAC-SHA1(URL + sorted params). Vobiz: HMAC-SHA256(baseURL + `.` + nonce). Both base64. |
| - | `X-Vobiz-Signature-V3-Nonce` | Random per-request nonce mixed into the V3 hash. |
| - | `X-Vobiz-Signature-V2` (+ `-Nonce`) | HMAC-SHA256 of `baseURL + nonce` (no separator). |
| - | `X-Vobiz-Signature-MA-V3` | Same scheme, signed with the **parent (main-account)** token on sub-account callbacks. |

### Before / after - Flask (Python)

<CodeGroup>
  ```python Twilio · Python (Flask) theme={null}
  from flask import Flask, request, abort
  from twilio.request_validator import RequestValidator

  app = Flask(__name__)
  AUTH_TOKEN = "your_twilio_auth_token"

  @app.route("/voice", methods=["POST"])
  def voice():
      validator = RequestValidator(AUTH_TOKEN)
      # HMAC-SHA1 over full URL + sorted POST params
      valid = validator.validate(
          request.url,
          request.form,
          request.headers.get("X-Twilio-Signature", ""),
      )
      if not valid:
          abort(403)

      call_sid = request.form["CallSid"]
      direction = request.form["Direction"]
      digits = request.form.get("Digits")
      speech = request.form.get("SpeechResult")
      # ... return TwiML
  ```

  ```python Vobiz · Python (Flask) theme={null}
  import hmac, hashlib, base64
  from urllib.parse import urlparse, urlunparse
  from flask import Flask, request, abort

  app = Flask(__name__)
  AUTH_TOKEN = "your_vobiz_auth_token"

  def _base_url(url: str) -> str:
      p = urlparse(url)
      return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))  # strip query

  def validate_v3(url: str, headers, token: str) -> bool:
      nonce = headers.get("X-Vobiz-Signature-V3-Nonce", "")
      msg = (_base_url(url) + "." + nonce).encode()          # HMAC-SHA256
      expected = base64.b64encode(
          hmac.new(token.encode(), msg, hashlib.sha256).digest()
      ).decode()
      return hmac.compare_digest(headers.get("X-Vobiz-Signature-V3", ""), expected)

  @app.route("/voice", methods=["POST"])
  def voice():
      if not validate_v3(request.url, request.headers, AUTH_TOKEN):
          abort(403)

      call_uuid = request.form["CallUUID"]
      direction = request.form["Direction"]
      digits = request.form.get("Digits")
      speech = request.form.get("Speech")     # Twilio's SpeechResult
      event = request.form.get("Event")       # Ring | StartApp | Hangup
      # ... return VobizXML
      return "", 200
  ```
</CodeGroup>

### Before / after - Node

<CodeGroup>
  ```javascript Twilio · Node (Express) theme={null}
  import express from 'express';
  import twilio from 'twilio';

  const app = express();
  app.use(express.urlencoded({ extended: false }));
  const AUTH_TOKEN = 'your_twilio_auth_token';

  app.post('/voice', (req, res) => {
    const signature = req.header('X-Twilio-Signature');
    const url = `${req.protocol}://${req.get('host')}${req.originalUrl}`;
    // HMAC-SHA1 over full URL + sorted POST params
    const valid = twilio.validateRequest(AUTH_TOKEN, signature, url, req.body);
    if (!valid) return res.sendStatus(403);

    const callSid = req.body.CallSid;
    const digits = req.body.Digits;
    const speech = req.body.SpeechResult;
    // ... return TwiML
  });
  ```

  ```javascript Vobiz · Node (Express) theme={null}
  import express from 'express';
  import crypto from 'crypto';

  const app = express();
  app.use(express.urlencoded({ extended: false }));
  const AUTH_TOKEN = 'your_vobiz_auth_token';

  function validateV3(req) {
    const nonce = req.header('X-Vobiz-Signature-V3-Nonce') || '';
    const baseUrl = `${req.protocol}://${req.get('host')}${req.path}`; // no query
    const expected = crypto
      .createHmac('sha256', AUTH_TOKEN)            // HMAC-SHA256
      .update(`${baseUrl}.${nonce}`)
      .digest('base64');
    const got = Buffer.from(req.header('X-Vobiz-Signature-V3') || '');
    const exp = Buffer.from(expected);
    return got.length === exp.length && crypto.timingSafeEqual(got, exp);
  }

  app.post('/voice', (req, res) => {
    if (!validateV3(req)) return res.sendStatus(403);

    const callUuid = req.body.CallUUID;
    const digits = req.body.Digits;
    const speech = req.body.Speech;      // Twilio's SpeechResult
    const event = req.body.Event;        // Ring | StartApp | Hangup
    // ... return VobizXML
    res.sendStatus(200);
  });
  ```
</CodeGroup>

### Handling the lifecycle event in one handler

<CodeGroup>
  ```python Vobiz · Python theme={null}
  @app.route("/voice", methods=["POST"])
  def voice():
      if not validate_v3(request.url, request.headers, AUTH_TOKEN):
          abort(403)

      event = request.form.get("Event")
      if event == "Ring":
          return "", 200                          # notify-only
      if event == "Hangup":
          log_cdr(request.form["CallUUID"],
                  request.form.get("HangupCause"),
                  request.form.get("BillDuration"))
          return "", 200
      # StartApp (or first answer request): return XML to drive the call
      return app_xml(), 200, {"Content-Type": "application/xml"}
  ```

  ```javascript Vobiz · Node theme={null}
  app.post('/voice', (req, res) => {
    if (!validateV3(req)) return res.sendStatus(403);

    switch (req.body.Event) {
      case 'Ring':
        return res.sendStatus(200);              // notify-only
      case 'Hangup':
        logCdr(req.body.CallUUID, req.body.HangupCause, req.body.BillDuration);
        return res.sendStatus(200);
      default:                                    // StartApp / first answer request
        return res.type('application/xml').send(appXml());
    }
  });
  ```
</CodeGroup>

## Key differences

* **One signature helper, HMAC-SHA256.** Where Twilio's `RequestValidator` rebuilds the full URL plus every sorted POST field, Vobiz signs `baseURL + "." + nonce` with SHA-256 - a short, deterministic string that's easy to reproduce in any language with the standard library (no param-sorting step). Validate values you read from the body in your handler, as you would on any platform.
* **A nonce per request.** Vobiz adds `X-Vobiz-Signature-V3-Nonce`, giving each signed request a fresh random component. Read it case-insensitively and feed it straight into the HMAC.
* **Events in the same handler.** Instead of wiring a separate `StatusCallback` URL, branch on the `Event` field (`Ring`, `StartApp`, `Hangup`) inside your existing endpoint - fewer URLs to register and secure.
* **Same parameter vocabulary.** `CallStatus` and `Direction` use the same words you already parse; mostly you rename `CallSid → CallUUID` and `SpeechResult → Speech`.
* **Constant-time compares.** Use `hmac.compare_digest` (Python) or `crypto.timingSafeEqual` (Node) - never `==` - exactly as Twilio's helper does internally.
* **Sub-account safety built in.** On sub-account callbacks Vobiz adds `X-Vobiz-Signature-MA-V3`, signed with the parent-account token, so a parent can independently verify child traffic with the same validator.

<CardGroup cols={2}>
  <Card title="Twilio migration overview" icon="map" href="/docs/compare/twilio/overview">
    The at-a-glance matrix and recommended migration order.
  </Card>

  <Card title="Voice Call API mapping" icon="phone" href="/docs/compare/twilio/voice-call-api">
    REST calls: create, fetch, and control live calls on Vobiz.
  </Card>
</CardGroup>

<Tip>
  Full request-parameter reference: [XML request params](/docs/xml/request).
</Tip>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.