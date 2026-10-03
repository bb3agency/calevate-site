# Vobiz API contract — what the vendor's own documentation says

**Status:** research, Phase A of the Vobiz carrier decision (founder, 2 Oct 2026); product
code now cites it throughout (`engine/vobiz.py`, `apps/voice-runtime/carrier_routes.py`).
**Evidence class:** every row marked **VDOCS** is VERIFIED-VENDOR-DOCS and is cited as
`<page>:<line>`, where `<page>` is relative to `vobiz-findings/mirror/pages/` (a hash-pinned
snapshot fetched 2 Oct 2026; see `vobiz-findings/mirror/README.md` and `MANIFEST.json`).
**UNKNOWN** means no page in the mirror states it. It does NOT mean the vendor lacks the
feature (hard rule 11). Rows marked **REPORTED** come from this repository or from a
third party, and are not to be re-stated as fact.

The docs are a Mintlify site that contradicts itself in a few places. Where two pages
disagree, both are cited and the **API reference page plus its embedded OpenAPI block** is
preferred over a concept or blog page. Section 17 lists the contradictions.

---

## 1. Authentication and base URLs

| Fact | Value | Source |
| --- | --- | --- |
| Base URL | `https://api.vobiz.ai/api/v1` (OpenAPI `servers: https://api.vobiz.ai`, paths carry `/api/v1/...`) | VDOCS `applications/create-application.md:10,147` |
| Auth headers | `X-Auth-ID: <auth_id>` and `X-Auth-Token: <auth_token>` on every request | VDOCS `api-reference/authentication.md:9-16`; OpenAPI security schemes `applications/create-application.md:288-298` |
| Auth ID shape | `MA_XXXXXXXX` (main account); sub-accounts are `SA_...` | VDOCS `api-reference/authentication.md:26`; `account-phone-number/purchase-from-inventory.md:15,23` |
| Bearer tokens | Accepted only on the capacity pricing/purchase endpoints | VDOCS `api-reference/authentication.md:38-46` |
| Credential check | `GET /api/v1/auth/me` returns the account object | VDOCS `api-reference/authentication.md:30-36` |
| Rotation | The docs say regenerating the token invalidates the old one immediately; the console's Auth Token Rotation panel says "The current token stays valid for the grace window", length not stated (Vobiz console, founder-relayed, 2 Oct 2026, VENDOR-PUBLISHED). Section 17 item 7 | VDOCS `api-reference/authentication.md:54`; integration plan §16a item 10 |
| Path casing | `Account` and `Call` are PascalCase with a trailing slash; lowercasing or dropping the slash returns **401**, not 404 | VDOCS `guides/plivo-to-vobiz/gotchas.md:21-27`; `call/make-call.md:131` |
| CDR path casing | `Account` capitalised, `cdr` lowercase | VDOCS `cdr/get-cdr.md:26` |
| API IP allowlist | Account object carries `ip_auth_enabled` and `ip_whitelist_rules` "for API access" | VDOCS `account/account-object.md:49-50` — **how to set it is UNKNOWN** (no write endpoint documented, and the console's Security page did not show it, integration plan §16a item 10) |
| Error body | Two shapes are documented: `{"status":"error","error":{"code","message","details"},"requestId"}` and the flatter `{"error": "...", "details": {...}}` | VDOCS `errors.md:13-41`; `applications/create-application.md:84-98` |

**Python SDK.** Vobiz publishes SDKs only as GitHub repositories (`github.com/vobiz-ai`),
not as a pinned package index entry (`llms.txt` "Developer resources"). We do not need one:
every call below is a few lines of `httpx`.

## 2. Outbound call create

`POST /api/v1/Account/{auth_id}/Call/` — VDOCS `call/make-call.md:9-11`, JSON body
(`Content-Type: application/json`, `:15-21`).

| Parameter | Required | Meaning | Source |
| --- | --- | --- | --- |
| `from` | yes | Caller ID, E.164 (examples omit the `+`) | `call/make-call.md:31` |
| `to` | yes | Destination(s); `<` separates up to 1000 bulk destinations; comma breaks routing | `:32`, `:136-138` |
| `answer_url` | yes | Fetched when the call is answered; must return XML | `:33` |
| `answer_method` | no | default POST | `:39` |
| `ring_url`/`ring_method` | no | notified on ringing | `:40-41` |
| `hangup_url`/`hangup_method` | no | notified on hangup | `:42-43` |
| `fallback_url`/`fallback_method` | no | invoked if `answer_url` fails after 3 retries or a 60 s timeout | `:44-45` |
| `machine_detection` (+5 tuning params, `machine_detection_url`) | no | `true` or `hangup`; async callback | `:53-62` |
| `caller_name` | no | up to 50 chars | `:68` |
| `send_digits`, `send_on_preanswer` | no | DTMF after connect | `:69-70` |
| `time_limit` | no | max seconds after answer; default 14400; ≥ 86400 is cut at 24 h | `:71` |
| `hangup_on_ring` | no | max seconds from ring start to hangup | `:72` |
| `ring_timeout` | **appears only in the request example**, not in the parameter table | `:83` vs `:27-72` — UNKNOWN whether honoured |

**Response** `200 OK`: `{"api_id", "message": "Call fired", "request_uuid"}`;
`request_uuid` equals `call_uuid`. 200 means **accepted and queued**, not answered
(`call/make-call.md:108-124`).

**Errors** (`call/make-call.md:126-134`): 400 (missing/malformed field, >1000
destinations), 401 (credentials or lowercase path), 402 (balance too low), 404 (unknown
`auth_id` or missing trailing slash), 429 (CPS or concurrency exceeded — "back off and retry
with jitter").

**Idempotency:** no idempotency key is documented on call create. **UNKNOWN** whether a
retried POST after a timeout places a second call. Our dial path must therefore never
retry blind (section 2 of the integration plan).

**Rate limits:** CPS and concurrency are per account (`account/account-object.md:41-46`;
`account/concurrency.md:60-62`). Exceeding either gives 429 on the API or SIP 503 for an
inbound caller (`faq/concurrency.md:19-21`; `faq/error-429.md:11-25`). The 429 body
carries `details.limitType`, `limit`, `current`, `retryAfter` (`errors.md:205-223`). An
API-wide request rate limit separate from CPS is **UNKNOWN**.

**Live calls:** retrieving in-progress calls requires `?status=live` (or `queued`);
omitting it returns a CDR or a 404 (`guides/plivo-to-vobiz/gotchas.md:29-35`).

## 3. The answer URL request (what Vobiz sends us)

| Fact | Value | Source |
| --- | --- | --- |
| Encoding | `application/x-www-form-urlencoded`; POST by default; **GET puts the same parameters in the query string** | VDOCS `xml/request.md:11` |
| Method | Configured per application (`answer_method`, GET or POST, default POST) or per call | `applications/create-application.md:31`; `call/make-call.md:39` |
| `CallUUID` | call id; matches `start.callId` on the WebSocket and the `hangup_url` webhook | `xml/request.md:29`; `xml/stream/stream-events.md:101` |
| `From` | **the calling party.** Inbound: the caller's caller ID. Outbound: our `from` | `xml/request.md:30` |
| `To` | the called party. Inbound: our number. Outbound: the destination | `xml/request.md:31` |
| `ForwardedFrom` | only on forwarded calls, carrier-dependent | `xml/request.md:32` |
| `CallStatus` | `ringing`, `in-progress`, `completed` (+ outbound finals) | `xml/request.md:33` |
| `Direction` | `inbound` / `outbound` | `xml/request.md:34` |
| `ALegUUID`, `ALegRequestUUID` | outbound only | `xml/request.md:35-36`; `call/make-call.md:159-175` |
| `Event` | `StartApp` on the answer URL (not `Answer`) | `call/make-call.md:171`; `concepts/callbacks.md:86-91` |
| Outbound extras | `CallerName`, `RequestUUID`, `STIRVerification`, `STIRAttestation`, `SessionStart` (UTC) | `call/make-call.md:159-175` |
| Response | one `<Response>` document, `application/xml` or `text/xml`, ≤ 100 KB, over HTTPS; `text/html`/`text/plain` is a parse error | `xml/request.md:11-21` |
| Latency | "aim for under 1-2 seconds"; the applications page says the answer URL "must respond within 10 seconds"; the call-create page says fallback fires after 3 retries or 60 s | `xml/request.md:17`; `applications.md:72`; `call/make-call.md:44` |
| Fallback | `fallback_answer_url` is used if `answer_url` is unreachable, times out or returns invalid XML; with none set the call drops | `applications/create-application.md:34` |

**Number format.** Examples print E.164 both with and without the leading `+`
(`applications.md:39` without; `xml/overview/how-it-works.md:49` with;
`xml/stream.md:98-99` without). Normalise every number with
`calevate_shared.extraction.normalize_phone`; never compare raw strings.

**This closes `docs/evidence/carrier-caller-identity.md` §5(d) for Vobiz**: the calling
party is the form field `From` on the answer request.

## 4. Answer XML — the `<Stream>` element

Grammar: VDOCS `xml/stream.md:38-50`.

| Attribute | Meaning | Default | Source |
| --- | --- | --- | --- |
| `bidirectional` | `true` lets us send `playAudio` back | — | `xml/stream.md:42` |
| `audioTrack` | `inbound`/`outbound`/`both`; must be `inbound` when bidirectional | `inbound` | `:43` |
| `streamTimeout` | max seconds | 86400 | `:44` |
| `statusCallbackUrl`/`Method` | stream lifecycle callbacks | POST | `:45-46` |
| `contentType` | **inbound** format only: `audio/x-l16;rate=8000`, `audio/x-l16;rate=16000`, `audio/x-mulaw;rate=8000` | **`audio/x-l16;rate=8000`** | `:47` |
| `extraHeaders` | key=value pairs sent to the WebSocket service; ≤ 512 bytes; characters `[A-Za-z0-9]` only | — | `:48` |
| `maxRetries` | reconnect attempts if the socket fails or drops | 0, max 10 | `:49` |
| `keepCallAlive` | `true`: the Stream runs exclusively; later XML runs only after the stream disconnects | `false` | `:50`; requires `bidirectional="true"` per `xml/stream/initiate.md:54` |

- Outbound (`playAudio`) format is declared per event and is independent of `contentType`:
  L16 at 8000/16000/24000, μ-law at 8000 (`xml/stream.md:42`;
  `concepts/streaming-websockets.md:78-99`). A 24 kHz payload is not 24 kHz at the handset
  (`concepts/streaming-websockets.md:101-103`).
- `maxRetries` reconnects open a **new socket with a new `start` and a new `streamId`**; the
  `callId` is unchanged (`xml/stream/initiate.md:148-153`).
- Our current document `<Stream bidirectional="true" keepCallAlive="true"
  contentType="audio/x-mulaw;rate=8000">wss://…</Stream>` is valid Vobiz grammar
  (all three attributes are in the table above). Vobiz's own Pipecat guide serves exactly
  this shape (`integrations/pipecat.md:572-590`).
- **Custom parameters (§5(c) of the caller-identity evidence).** `extraHeaders` exists and
  every `start`/`media` message carries a top-level `extra_headers` string
  (`xml/stream/stream-events.md:95,175`; `xml/stream/initiate.md:84,103`). Only the EMPTY
  form `"{}"` is ever shown. **UNKNOWN:** the populated shape, whether the values also
  arrive as HTTP headers on the WebSocket upgrade (the REST stream API says "additional
  HTTP headers sent when opening the WebSocket connection", `audio-streams/start-audio-stream.md:77`),
  and whether underscores are really refused (`xml/stream/initiate.md:253` uses
  `session_id=`, contradicting `[A-Za-z0-9]` at `xml/stream.md:48`).
- **Query strings on the stream URL:** not stated. Vobiz's own Pipecat reference app puts
  per-call context on the WebSocket URL ("base64-encoded onto the WebSocket URL",
  `integrations/pipecat.md:525`), which is evidence it survives, not a guarantee.

Other verbs that matter to us: `<Dial>` (section 8), `<Record>` (section 9), `<Hangup>`
(`xml/hangup`), `<Redirect>`. `<Gather>` replaces Plivo's `<GetDigits>`/`<GetInput>` and
uses `executionTimeout`, never `timeout` (`guides/plivo-to-vobiz/gotchas.md:13-19`).

## 5. The WebSocket media protocol

Vobiz is the WebSocket **client**; our `wss://` URL is the server
(`concepts/ip-whitelisting.md:109-113`). JSON text frames, base64 payloads.

**Vobiz → us**

| Event | Shape | Source |
| --- | --- | --- |
| `start` | `{"sequenceNumber":0,"event":"start","start":{"callId","streamId","accountId","tracks":["inbound"],"mediaFormat":{"encoding","sampleRate"}},"extra_headers":"{}"}` — once per socket. **No `from`/`to`.** | `xml/stream/stream-events.md:78-107` |
| `media` | `{"sequenceNumber","streamId","event":"media","media":{"track","timestamp","chunk","payload"},"extra_headers"}` — 20 ms frames, ~50/s/track; `media` does not repeat the format | `:161-185`; `xml/stream/initiate.md:107` |
| `playedStream` | `{"event":"playedStream","name"}` — **no `streamId`**; only if playback up to the checkpoint completed | `:144-158`, `:69-71` |
| `clearedAudio` | `{"event":"clearedAudio","streamId"}` | `:199-207` |
| `dtmf` | the event name is documented; **its body is UNKNOWN** (no example anywhere in the mirror) | `integrations/gemini-live.md:27,287-289` |
| end of call | **no inbound `stop`**; the socket closes. Close is the in-band end signal | `:63-67`, `:242-258` |

**Us → Vobiz** (every command carries the `streamId` from `start`, `:127-129`)

| Command | Shape | Source |
| --- | --- | --- |
| `playAudio` | `{"event":"playAudio","streamId","media":{"contentType":"audio/x-mulaw"\|"audio/x-l16","sampleRate","payload"}}` — raw mono, no container header; 20–60 ms chunks recommended | `:110-130`; `concepts/streaming-websockets.md:99,141-152` |
| `checkpoint` | `{"event":"checkpoint","streamId","name"}` → `playedStream` | `:132-142` |
| `clearAudio` | `{"event":"clearAudio","streamId"}` — barge-in flush | `:188-197` |
| `stop` | `{"event":"stop","streamId"}` — stream stops, socket closes, the next XML element runs; **with none, Vobiz hangs up** (`HangupCauseCode=4010`, `HangupSource=Vobiz`) | `:226-236`, `:262-293` |

**Wire compatibility with the code we already run.** The `start` event's `start.streamId`
plus `start.callId` is exactly what pinned Pipecat 1.10.0 uses to detect **Plivo**
(`.venv/.../pipecat/runner/utils.py:89-96`), and `playAudio`/`clearAudio`/`media` match the
Plivo serializer's envelopes (`pipecat/serializers/plivo.py:139-163`). So a Vobiz socket
is auto-detected as `"plivo"` today. The one Plivo-specific behaviour that breaks is the
serializer's REST hangup, which is hard-coded to `api.plivo.com` with HTTP Basic auth
(`serializers/plivo.py:184-191`) and swallows every error.

## 6. Status, hangup and stream callbacks

| Fact | Value | Source |
| --- | --- | --- |
| Encoding | form-encoded POST (or GET); the example on the callbacks page labels the body form-encoded but prints JSON | `xml/request.md:11`; `concepts/callbacks.md:37-55` |
| Standard fields on every callback | `Event`, `timestamp`, `auth_id`, `CallUUID` | `concepts/callbacks.md:96-105` |
| Events | `CallInitiated`, `Ring`, `StartApp`, `Hangup` (authoritative end), `Record`/`RecordStop`, `Dial*`, `Conference*`, stream events, `MachineDetection`, `Redirect` | `concepts/callbacks.md:70-84` |
| `hangup_url` fields (call create page) | `From`, `To`, `RequestUUID`, `ALegRequestUUID`, `CallUUID`, `Direction`, `ALegUUID`, `Event=Hangup`, `stir_verification`, `CallStatus=completed`, `StartTime`/`AnswerTime`/`EndTime` (**local time**), `SessionStart` (UTC), `STIRAttestation` | `call/make-call.md:177-195` |
| Duration/cause on hangup | `HangupCause`, `Duration`, `BillDuration` are present once the call has ended | `xml/request.md:37-39`; `applications.md:64` |
| Hangup default | `hangup_url` defaults to `answer_url` when omitted on an application | `applications/create-application.md:32` |
| Ack | respond 200 within **3 seconds**; non-200 is retried **up to 3 times with exponential backoff**; make handlers idempotent | `concepts/callbacks.md:125-126`; `concepts/callback-configurations.md:15-22,146` |
| Stream status callbacks | `StartStream`, `PlayedStream`, `ClearedAudio`, `DegradedStream`, `DroppedStream`, `StopStream`; fields `CallUUID`, `StreamID`, `Event`, `From`, `To`, `Timestamp`, `Name`, `ServiceURL`, `Error`, `ParentAuthID`; `StopStream` only on a stop WE initiate; `ClearedAudio` fires per barge-in (15 callbacks on a 125 s call) | `xml/stream.md:68-204` |
| Timestamp zone | Call-object and hangup-callback times are in the **console's local timezone**, `yyyy-MM-dd HH:mm:ss`; CDR times are ISO 8601 `Z` | `call/call-object.md:19,25,30`; `call/make-call.md:191-194`; `cdr.md:271-276` |

### Request signatures

VDOCS `concepts/validating-callbacks.md`:

- Headers: `X-Vobiz-Signature` (V1, HMAC-SHA1, legacy), `X-Vobiz-Signature-V2` +
  `-V2-Nonce`, `X-Vobiz-Signature-V3` + `-V3-Nonce`, and `X-Vobiz-Signature-MA-V2`/`-MA-V3`
  signed with the **parent** account's token on sub-account callbacks (`:15-27`, `:281-292`).
- Key: the account **auth token** (`:11-13`).
- V2: `base64(HMAC-SHA256(authToken, baseURL + nonce))`; V3: `… baseURL + "." + nonce`,
  where baseURL is the callback URL **with its query string stripped** (`:35-52`).
- **What is signed: the URL path and a nonce. Never the body** (`:66-70`). The nonce is
  random, not time-based; replay protection is ours to build by remembering nonces for a
  short window (`:304`).
- ⚠ **Signatures are sent only "when the callback URL has auth credentials configured on
  it"; otherwise the callback arrives with no signature headers at all, and coverage
  varies by callback type** (`:56-64`). How to configure those credentials is **UNKNOWN**
  (no page, no API field). This is the console question that decides whether we can
  verify anything. What the mirror does say, all of it:
  - The vendor's Deepgram guide says the credentials are set "on the URL in the console"
    (`integrations/deepgram.md:486`, again at `:498` and `:606`), without naming a page or
    a field.
  - The callback configuration page says only "configure shared secrets and verify HMAC
    signatures" (`concepts/callback-configurations.md:131-133`), with no field for one.
  - Neither the Application API (`applications/create-application.md:27-48`,
    `update-application.md`) nor the console guide's create form
    (`platform/voice/applications.md:52-60`) has a credential field. The console reading
    agrees: the Applications create form has no auth, credential or signing field (Vobiz
    console, founder-relayed, 2 Oct 2026, VENDOR-PUBLISHED; integration plan §16a item 5).
  - Endpoints are SIP softphone logins (username and password for `registrar.vobiz.ai`,
    `platform/voice/endpoints.md:9,31-32`; `endpoint/endpoint-object.md:121-133`), not
    callback credentials.
  - Trunk webhooks use a different scheme, an HMAC over the raw body under a per-trunk
    secret "configured in the Console" (`trunks/webhook.md:169,220`). That covers trunk
    events, not Application callbacks.
  - No page shows a callback URL carrying userinfo (`https://user:pass@host/…`). That
    reading of "auth credentials … on the URL" is a guess, not a finding. A sweep of the
    whole mirror on 2 Oct 2026 (`pages/`, `llms-full.txt`, `root-site/openapi.json`) for
    userinfo-shaped URLs, "basic auth", `Authorization`, "auth credentials", "shared
    secret" and credential fields found:
    - no URL with userinfo anywhere;
    - every "HTTP Basic" mention is about OUR requests to Vobiz's REST API
      (`account-phone-number/cancel-release.md:30`, `account/transactions.md:21`) or about
      Plivo's (`guides/plivo-to-vobiz/auth-and-base-url.md:20,76`); none says Vobiz sends
      an `Authorization` header on a callback;
    - no credential field on the Application in the OpenAPI schema
      (`root-site/openapi.json:496-613`: answer, hangup, fallback, message and SIP-transfer
      URLs and methods, and flags only);
    - no auth attribute on `<Stream>`; `extraHeaders` is the only per-stream key-value
      field (`xml/stream.md:48`), and the vendor's own guide says it never reaches the
      socket (`integrations/deepgram.md:473`);
    - the `username`/`password` fields in the OpenAPI spec belong to SIP endpoints and
      deprecated trunk credentials (`root-site/openapi.json:622,6546-6556`), not callbacks;
    - two other pages repeat the claim without the mechanism: "Every callback Vobiz sends
      includes HMAC-SHA256 signatures" (`concepts/callbacks.md:117`) and "checking
      signatures or an IP allowlist" (`xml/overview/best-practices.md:129-131`).
    - The vendor's Deepgram bridge, which turns on signature checks once credentials are
      set "on the URL in the console", rebuilds the signed URL from a bare hostname
      (`integrations/deepgram.md:477,533`), so its own guide verifies against a URL with
      no userinfo, as ours does. That is a hint, not a test result: the guide's source is
      not in the mirror.

    **Conclusion: the docs do not support credentials carried in the callback URL, so
    nothing was built for it.** The verifier was not widened either: a with-userinfo
    candidate can only be built from credentials we hold, and we hold none.
  - **If it is userinfo, the vendor's own validators disagree on whether it is signed.**
    The Python sample rebuilds the base URL from `netloc`, which includes userinfo
    (`concepts/validating-callbacks.md:85-87`); the Node, Go and Ruby samples use the host
    alone (`:127-130`, `:189-194`, `:248-251`). Our verifier rebuilds the URL from
    `webhook_base_url` plus the path, with no userinfo
    (`apps/voice-runtime/carrier_auth.py::signed_base_urls`), so it matches only if Vobiz
    signs without it. If Vobiz signs with it, every signed request reads as invalid and is
    refused even with `vobiz_signature_required` off. The runbook's signing step watches
    for exactly that.
  - **The question for Vobiz support, in writing** (also in the runbook, §4):
    > On a Voice Application, how do we configure the "auth credentials" on the answer URL
    > and hangup URL that make Vobiz send `X-Vobiz-Signature-V3` (your Validating
    > Callbacks page, "Signature headers are emitted only when the callback URL has auth
    > credentials configured on it")? Which console page and field, or which API field?
    > Once configured: (1) is the answer request signed, as well as the hangup callback?
    > (2) Is the URL that is signed the URL with the credentials in it
    > (`https://user:pass@host/path`), or without them? Your Python sample keeps them and
    > your Node, Go and Ruby samples drop them. (3) Do you also send an `Authorization`
    > header carrying those credentials? (4) After an auth token rotation, which token
    > signs callbacks during the grace window?
- Whether the **answer URL** request (as opposed to status callbacks) is signed is not
  stated separately; the page says "every callback" (`:9`), qualified by the warning above.
- The migration guide says the scheme is "identical" to Plivo's V3 (`guides/plivo-to-vobiz/webhooks-and-signatures.md:13-25`),
  yet its own "before" example passes the form parameters into Plivo's validator
  (`:41-48`) while Vobiz signs none. Treat Vobiz's canonical page as authoritative.

**Consequence for us:** a valid signature proves that Vobiz requested *this path*. It does
not authenticate `From`, `CallUUID` or any other body field. Body integrity rests on TLS.

### Source IPs (VDOCS `concepts/ip-whitelisting.md`)

| Use | India addresses | Source |
| --- | --- | --- |
| HTTP callbacks (answer, hangup, status) | `15.206.6.156`, `35.154.59.246`, `15.207.8.226` | `:93-107` |
| WebSocket client (media fleet) | `3.110.99.6`, `65.1.145.87`, `13.234.214.51`, `13.200.197.87`, `13.202.13.57`, `18.96.230.96/28`, `18.96.230.112/28`, `18.96.230.208/29`, `18.96.232.168/29` | `:109-135` |
| NDNC complaint webhook | `15.207.141.89` | `account/ndnc-webhook.md:46-58` |

"IP addresses are subject to change … contact support@vobiz.ai to subscribe to IP change
notifications" (`:27-29`). The fleet CIDRs are the ones to allowlist, not single hosts
(`:87-91`).

## 7. Hangup

- REST: `DELETE /api/v1/Account/{auth_id}/Call/{call_uuid}/`, no body, `204 No Content`
  (the OpenAPI spec lists the same path WITHOUT the trailing slash,
  `vobiz-findings/mirror/root-site/openapi.json:2298`, while the gotchas page says a missing
  slash returns 401; use the doc page's form and test it);
  fires the `hangup_url` callback (`call/hangup-call.md:9-60`). A-leg/B-leg selection is
  mentioned in the description (`:13`) but no parameter for it is documented.
- In-band: send `stop` on the stream; with no XML after `<Stream>`, Vobiz hangs up with
  cause 4010 (`xml/stream/stream-events.md:262-293`). **This needs no credential.**
- `time_limit` on call create (default 4 h) and `streamTimeout` (default 24 h) are the
  carrier-side ceilings (`call/make-call.md:71`; `xml/stream.md:44`).

## 8. Transfer

- REST: `POST /api/v1/Account/{auth_id}/Call/{call_uuid}/` with `legs` (`aleg` default,
  `bleg`, `both`), `aleg_url`/`aleg_method`, `bleg_url`/`bleg_method`; `202
  {"message":"call transferred"}`. The live flow is interrupted and the XML returned by
  the URL runs immediately; an unreachable URL may drop the leg (`call/transfer-call.md:9-110`).
- The XML that bridges is `<Dial>`: `callerId` (must be a Vobiz number owned or
  authorised by the account, else the B-leg may fail), `timeout` (default effectively
  120 s), `timeLimit`, `action` + `redirect`, `callbackUrl` with `DialAnswer`,
  `DialConnected`, `DialHangup` (with duration, bill duration, hangup cause), final
  `DialStatus` (`completed`, `busy`, `failed`, `cancel`, `timeout`, `no-answer`)
  (`xml/dial.md:12-14,44-60,77-104`).
- **Whisper-and-accept:** `confirmSound` plays XML to the called party after answer, but
  "`confirmKey` … enforcement as an acceptance gate is currently unverified, so do not
  depend on a keypress to control whether the B-leg connects" (`xml/dial.md:55-57`). The
  vendor itself does not vouch for the accept step.
- SIP REFER exists on verified SIP trunks only (`faq/call-transfer.md:13-19`).

These answer facts 1, 2, 4 and 5 of `apps/api/agents/transfer_providers/plivo.py`'s five
for Vobiz, and answer fact 3 with the vendor's own caveat.

## 9. Recording

- Recording happens only when asked: the `<Record>` verb (`xml/record`), or the call
  record REST endpoints (`call/record-calls.md`, `call/record-calls/start-recording.md`). Vobiz's own
  Pipecat example adds `<Record>` to the answer XML explicitly and lets you turn it off by
  omitting the element (`integrations/pipecat.md:465,572-590`).
- **Whether any account-level or number-level automatic recording default exists is
  UNKNOWN.** No page documents one.
- Stored recordings are fetched with `X-Auth-ID`/`X-Auth-Token` (not public URLs), the
  container may not match the extension, and storage is billed with durations rounded to
  60 s (`recording.md:24-41,75-77`).
- Retention: a **blog** says "Vobiz keeps recordings for a 30-day window in-console and
  auto-deletes older ones" (`blogs/call-recording-apis-compliant-pipelines.md:76`). The
  console's Recordings page states "Recordings are available for the last 30 days" (Vobiz
  console, founder-relayed, 2 Oct 2026, VENDOR-PUBLISHED). That confirms the 30-day window;
  the auto-delete half is still the blog's alone.
- No auto-record setting was shown at account, number or application level in the same
  reading. Not shown is not absent, so the default stays UNKNOWN.
- Delete: the recordings overview's operation table has no delete row
  (`recording.md:65-73`), but the vendor's OpenAPI specification declares
  `DELETE /api/v1/Account/{auth_id}/Recording/{recording_id}/` -> `204 Recording deleted`,
  "Permanently delete a recording from the account"
  (`vobiz-findings/mirror/root-site/openapi.json:8459-8484`, under the path at `:8328`), and
  the recording object page lists the same route with `204 No Content` and says deleting is
  permanent (`recording/recording-object.md:152,155`). A live recording can be stopped with
  `DELETE …/Call/{call_uuid}/Record/` (`call/record-calls/stop-recording.md:10`).

### 9a. Recording alongside the bidirectional stream (D-668, read 3 Oct 2026)

The founder decided on 3 Oct 2026 that Vobiz records the calls (its ₹0.10/min add-on,
section 16). What the build rests on, every row VDOCS:

| Fact | Source |
| - | - |
| `<Record>` and `<Stream>` can run together: "simultaneously record a call and stream its audio to a WebSocket in real-time" | `xml/record/stream-with-record.md:9` |
| The shape: `<Record/>` self-closing, a SIBLING placed BEFORE `<Stream>`, `recordSession="true"` so it continues while later elements run, `redirect="false"` so the recording callback does not interrupt the stream | `xml/record/stream-with-record.md:11`; example with `<Stream bidirectional="true" keepCallAlive="true">` at `:15-25` |
| Vobiz's own Pipecat guide serves exactly `<Record recordSession="true" .../>` + `<Stream bidirectional="true" audioTrack="inbound" ...>` | `integrations/pipecat.md:569-581` |
| `recordSession="true"`: records the entire session; ends when the call hangs up, final callback reports `RecordingEndReason=HungUp` | `xml/record.md:23,94-112` |
| `maxLength` default **60 s**, `timeout` (silence) default **60 s**, `finishOnKey` default **every key**, `playBeep` default true, `fileFormat` `mp3`/`wav` default `mp3` | `xml/record.md:17-22` |
| `callbackUrl` receives `RecordStop`; a `recordSession` flow may use `callbackUrl` without `action` | `xml/record.md:15,28,43-62,145` |
| `RecordStop` fields: `RecordingID`, `RecordFile`, `RecordUrl`, `RecordingDuration`, `RecordingDurationMs`, `RecordingStartMs`, `RecordingEndMs`, `RecordingEndReason`, plus `CallUUID`, `From`, `To`, `Direction`, `BillRate`, `CallStatus`, `ALegUUID`, `ALegRequestUUID`, `RequestUUID`, `SessionStart`, `ParentAuthID` | `xml/record/stream-with-record.md:54-78`; `xml/record.md:43-55,130-140`; `concepts/callbacks.md:78` ("`RecordStop` carries the recording identity and URL") |
| `RecordingEndReason` values: `RecordingTimeout`, `maxLength`, `FinishedOnKey`, `HungUp` | `xml/record.md:57-62` |
| Retrieve one: `GET /Account/{auth_id}/Recording/{recording_id}/` returns a FLAT object with `call_uuid`, `recording_url`, `recording_format`; 404 "Recording not found" | `recording/retrieve-recording.md:9-66` |
| List by call: `GET /Account/{auth_id}/Recording/?call_uuid=…`; no match is `200` with `objects: []` | `recording/list-all-recordings.md:41,165` |
| The download needs `X-Auth-ID` and `X-Auth-Token`; use the exact `recording_url` the retrieve returns; host varies over `media.vobiz.ai`, `recordings.vobiz.ai`, `storage.vobiz.ai`; follow redirects | `recording/download-recording.md:39-58`; `recording.md:39-40`; `recording/recording-object.md:22` |
| The container may not match the extension, content type or `recording_format`; detect from magic bytes; an MP3 sync is 11 bits (`0xFF 0xE3` valid) | `recording.md:24-37` |
| `call_uuid` and `request_uuid` are the same id | `call/make-call.md:120-123` |
| Storage is billed per 60 s, recordings under 60 s round up | `recording.md:75-77` |

**Both legs, and the format.** The Pipecat guide reports the recorded file as "a RIFF/WAVE
container (8 kHz, 16-bit, stereo)" when `fileFormat="wav"` (`integrations/pipecat.md:811`),
while the console page says WAV is "8 kHz mono PCM by default" and MP3 is "CBR 64 kbps"
(`platform/voice/recordings.md:61`). The REST start-recording call has a `record_channel_type`
mono/stereo switch (`call/record-calls/start-recording.md:36`); the `<Record>` element
documents none (`xml/record.md:13-29`). **No page states in words that a `recordSession`
recording beside a bidirectional stream contains the audio we stream BACK** (the agent's
voice). UNKNOWN until the first live call (OPERATIONS §2 gate V-11(a)).

**Retention — UNRESOLVED, and built to the shorter reading.** The Recordings page says "the
last 30 days" and "older recordings are deleted automatically" (`platform/voice/recordings.md:
9,21`), and "Export critical recordings within 30 days. The retention window is hard"
(`:82`). The same page's screenshot shows a recording with "Storage Life of 3 days" (`:18`,
the image's alt text), and the page defines Storage Life as "Days remaining before automatic
deletion. The clock starts at recording creation" (`:63`). Three days REMAINING is consistent
with a 30-day window on a 27-day-old recording and with a 3-day window; the page does not say
which. The API adds only "Recording URLs may be temporary" (`recording/recording-object.md:139`)
and `recording_storage_duration` "Number of days since the recording was created" (`:49`). So
the copy runs on the callback, retries in minutes, and pages at six hours
(`apps/workers/carrier_recordings.COPY_OVERDUE_AFTER`).

**Undocumented here, and therefore gated (V-11):** whether `finishOnKey` applies to a
`recordSession` recording (a caller's keypress would then end it); whether the CDR's
`total_cost` includes the recording add-on (`cdr.md:277-279` names streaming only, and no CDR
field names recording); whether `RecordStop` is signed like the hangup callback (the
signature page covers "callbacks" generally, `concepts/validating-callbacks.md:15-52`).

**What we send** (`apps/voice-runtime/carrier_routes.record_element`):
`<Record recordSession="true" redirect="false" fileFormat="mp3" maxLength="14400"
timeout="14400" playBeep="true" callbackUrl="{WEBHOOK_BASE_URL}/carrier/v1/vobiz/events/{ref}
[/outbound/{call_id}]" callbackMethod="POST"/>` before the `<Stream>`. The two limits are
Vobiz's own default call `time_limit` (`call/make-call.md:71`), because both 60 s defaults
would cut a conversation's recording short. No `action`, and `finishOnKey` is not set (no
"none" value is documented).

## 10. DTMF

- Inbound on the stream: `dtmf` events exist; body shape **UNKNOWN** (section 5).
- Outbound: `POST …/Call/{call_uuid}/DTMF/` (send digits; `call/dtmf.md:51-52`,
  `call/dtmf/send-digits.md`), or `send_digits` on call create (`call/make-call.md:69`).
- `<Gather inputType="dtmf">` for XML collection (`guides/plivo-to-vobiz/gotchas.md:13-19`).

## 11. Phone numbers and inbound configuration

| Operation | Endpoint | Source |
| --- | --- | --- |
| List owned | `GET /api/v1/Account/{auth_id}/numbers` (paginated; masters can include sub-account numbers) | `account-phone-number.md:42-44`; `account-phone-number/list-account-phone-numbers.md` |
| Browse inventory | `GET …/numbers/inventory` with `exclude` prefix filters (country code included) | `account-phone-number/list-inventory-numbers.md:35-43` |
| Buy | `POST /api/v1/Account/{auth_id}/numbers/purchase-from-inventory` `{"e164": "+91…", "currency"}`; debits setup + monthly fee; **a sub-account purchase charges the parent**; a failed debit surfaces as **500** | `account-phone-number/purchase-from-inventory.md:9-53` |
| Release | `DELETE …` "unrent" with an account-specific release fee | `account-phone-number.md:46` |
| Assign to sub-account | `POST /api/v1/account/{auth_id}/numbers/{e164}/assign-subaccount` `{"sub_account_id": "SA_…"}`; unassign has a **15-day cool-off** (`409 did_cool_off_in_effect`) | `account-phone-number/assign-subaccount.md:32-65`; `account-phone-number.md:50-56` |
| Route inbound | Create an **Application** (`POST …/Application/`, `app_name` [A-Za-z0-9_-], `answer_url`, `answer_method`, `hangup_url`, `fallback_answer_url`, `sub_account`), then `POST …/numbers/{e164}/application` `{"application_id"}` | `applications/create-application.md:9-49`; `applications/attach-number.md:9-60` |
| Number object | `e164`, `status` (`active`/`pending_purchase`/`pending_release`/`released`/`blocked`), `application_id`, `setup_fee`, `monthly_fee`, `currency`, `minimum_commitment_months`, `aadhaar_verification_required` | `account-phone-number/account-phone-number-object.md:11-59` |

Inbound routing is by **Application, not by a per-number URL**: the `answer_url` lives on
the application and the number points at the application. Porting a number in from
another provider is not offered (`guides/plivo-to-vobiz/number-porting.md`; REPORTED
earlier as "blocks it outright", `docs/evidence/dlt-roles-and-operating-model-2026-09-18.md:56`).
Trial numbers cannot take inbound calls; inbound needs KYC, a payment method and a
dedicated DID (`faq/trial-inbound.md:9-35`). The founder's account is a trial account and
its one number is tagged TRIAL (Vobiz console, founder-relayed, 2 Oct 2026,
VENDOR-PUBLISHED). Whether a trial account also limits outbound calls or WebSocket
streaming is UNKNOWN: the console banner says only that a first recharge will "unlock all
features". The founder states that recharging is all it takes to activate the account and
that KYC is done (founder decision, 2 Oct 2026). That is the founder's statement, not a
page of Vobiz's; the trial-inbound rule above is still why inbound waits for the recharge.

## 12. Sub-accounts and the partner programme

- `…/Account/{auth_id}/Subaccount/`; each gets its own `auth_id`/`auth_token`; "parent
  account retains full administrative control" (`sub-accounts.md:11-24`).
- `kyc_mode`: `personal_use` (default, inherits the parent's KYC) or `customer_use` (must
  KYC in its own name; created `kyc_calls_blocked: true` until it does). Sub-account KYC
  has a hosted-session flow and a test mode (`sub-accounts.md:58-67`).
- Callbacks for a sub-account are signed with both tokens (section 6).
- Partner programme: not self-serve; the partner is the master account, funds customer
  wallets and has read visibility over their traffic; "Typical response time: 1 business
  day" (`partner.md:13-33`, `:72-74`).
- The console's Subaccounts create form offers KYC Mode "Personal use (inherits your
  KYC)" or "Customer use (independent KYC)" (Vobiz console, founder-relayed, 2 Oct 2026,
  VENDOR-PUBLISHED).
- **UNKNOWN:** whether the parent's credentials can place a call or attach a number
  *on a sub-account's path*, or whether the sub-account's own token is required.

## 13. SIP trunking (only as far as it matters)

We do not need a trunk: the `<Stream>` path terminates on our WebSocket with no SIP or RTP
on our side (`concepts/ip-whitelisting.md:109-111`). Trunks matter only if a future
design bridges a PBX or uses SIP REFER (`faq/call-transfer.md:15-18`).

## 14. India specifics, concurrency, region

| Fact | Source |
| --- | --- |
| Only India-registered businesses may rent Indian numbers and use domestic routes; KYC first | `compliance/india/calling-regulations.md:17-36` |
| Outbound caller ID must be a Vobiz-rented Indian number; a non-Vobiz number is "best-effort" | `compliance/india/calling-regulations.md:35`; `faq/domestic-calling-india.md:13,27-29` |
| **Media anchoring**: both legs must stay in India, else `violates_media_anchoring` | `compliance/india/calling-regulations.md:38-48`; `faq/domestic-calling-india.md:31-37` |
| An "India data region" account is a distinct signup for domestic inventory | `compliance/india/calling-regulations.md:76-86` |
| 140 = promotional only, 9 AM–9 PM, TATA DLT + consent template; 160 = service/transactional, BFSI only; 92-series mobile numbers are Aadhaar-bound, max 5 per KYC identity; all three by request to support | `faq/number-series.md:11-34` |
| 140 acquisition via Vobiz's pool requires TATA DLT specifically; documents: GST, Certificate of Incorporation, signatory KYC, LOI | `best-practices/140-160-acquisition.md:25,47-95` |
| Vobiz scrubs NDNC on the outbound path for regulated series and blocks unconsented DND numbers | `compliance/india/ucc.md:36-42` |
| UCC complaint timeline: 24 h to submit proof, else the compliance ID is blocked; 5+ complaints in 10 days suspends 15 days; repeat = TRAI blacklist | `compliance/india/ucc.md:64-112` |
| NDNC complaint webhook: JSON, `X-VoBiz-Signature = hex(HMAC-SHA256(shared_secret, raw body))`, origin `15.207.141.89`, 5 s timeout, activated by email | `account/ndnc-webhook.md:15-58,99-157` |
| Concurrency `max_concurrent = base + purchased`; CPS likewise; `GET …/concurrency` reports live use | `account/concurrency.md:15-62`; `account/account-object.md:41-46` |
| Infrastructure region in CDRs: `ap-south-1`, `origination_region: mumbai` | `cdr.md:190-192,313` |

Our account's limits are CPS 1 (1 base + 0 purchased) and 3 concurrent calls (3 base + 0
purchased) (Vobiz console, founder-relayed, 2 Oct 2026, VENDOR-PUBLISHED), matching the
earlier REPORTED figure (`docs/evidence/carrier-pricing-concurrency-2026-09-17.md:49`).
The console prices more CPS at ₹1,299 per unit in blocks of 3 and more concurrency at
₹499 per unit in blocks of 10; the India rate card agrees and adds ₹599 per unit in packs
of 30 for 140/160 numbers (section 16). `GET …/concurrency` reports live use. The founder
has decided CPS 1 and 3 concurrent are enough for live testing (2 Oct 2026, gate V-5).

## 15. CDR (the billing authority)

`GET /api/v1/Account/{auth_id}/cdr/{call_uuid}` — pass the **uuid** (= `CallUUID`), not
the numeric id (`cdr/get-cdr.md:9-26`). A CDR exists **only after the call ends**
(`:25`). Fields (`cdr.md:257-318`): `duration` (ring + talk), **`billsec` (talk only)**,
`answer_time`/`start_time`/`end_time` (ISO 8601 UTC), **`cost`, `total_cost` (includes
streaming), `streaming_cost`, `currency`** (`INR` in the example), `hangup_cause`,
`hangup_cause_code`, `hangup_source`, `codec`, `mos`, `region`. List/search/recent/export
variants exist (`cdr.md:15-23`). The Call object additionally shows `billed_duration`,
which "may differ … depending on the billing interval of the destination"
(`call/call-object.md:20-21`).

This answers facts 1, 2, 3 (partly) and 4 of `voice_worker/carrier.py::fetch_call_detail_record`.
**UNKNOWN:** whether `cost` is final at CDR creation or can be revised later, and the
billing increment (fact 5).

## 16. Pricing (published only)

### The India rate card (VENDOR-PUBLISHED, founder-relayed, 2 Oct 2026)

Vobiz's "India Pricing" rate card, supplied by the founder as an image on 2 Oct 2026 and
read figure by figure from that image. It is not in the mirror and was not fetched from
here. Header: "Currency: INR (₹)", "Billing: monthly", "Geography: India".

| Numbers | Monthly | One-time setup |
| --- | --- | --- |
| Standard Local DID (080/022/011 and other city codes) | ₹500 per number | ₹100 |
| 79 series (Ahmedabad circle local DID) | ₹600 per number | ₹100 |
| 92 series (special series) | ₹1,000 per number | ₹100 |
| 140 series (regulatory number) | ₹599 per number | ₹100 |
| 160 series (regulatory number) | ₹599 per number | ₹100 |

| Usage | Per minute |
| --- | --- |
| Connected SIP trunk calls ("Inbound and outbound calls over your Vobiz SIP trunk") | ₹0.38 |
| **Voice API / streaming calls ("Calls placed or controlled via Voice APIs and WebSocket media streaming")** | **₹0.44** |
| Recording ("Call recording with storage") | ₹0.10 |
| Transcription ("Recording is mandatory") | ₹0.30 |
| PII redaction ("Recording + transcription are mandatory") | ₹0.30 |

| Capacity | Rate |
| --- | --- |
| Included | 1 CPS, 3 concurrency |
| Additional CPS | ₹1,299 per CPS per month, packs of 3 |
| Additional concurrency, Local DIDs and 79 | ₹499 per concurrency per month, packs of 10 |
| Additional concurrency, 140/160 | ₹599 per concurrency per month, packs of 30 |

Footnotes on the card: "All charges in Indian Rupees and exclusive of applicable taxes and
statutory levies."; "Number allocation is subject to TRAI/DoT eligibility, KYC and
use-case approval."; "Volume and annual-commitment pricing available on request."

What it means for us:

- **Our calls are the ₹0.44 row.** We dial through the REST API and carry audio on a
  `<Stream>` WebSocket, which is the card's "Voice API / streaming calls". The ₹0.38 SIP
  trunk row is not ours (section 13).
- **Every figure is before tax.** Tax is added on top. No GST percentage is applied
  anywhere in this tree, because none has been read from a primary source.
- **UNKNOWN, not on the card:** the billing pulse or increment, and any minimum duration
  (gate V-7). Also UNKNOWN: whether the held trial number's ₹159.00/month in the console
  is a different price from the card's ₹500 for a standard local DID. The console lists
  that number as mobile series, so it may not be on that row at all.
- The capacity rows agree with the console's ₹1,299 and ₹499 (section 14); the 140/160
  concurrency row is new.
- **It is a catalogue reference, not a cost.** `billing/rates.py::VOBIZ_INR_PER_MIN`
  carries the per-minute rows with no path to `unit_cost_paid`; a call's cost remains the
  CDR's INR `total_cost` (section 15, hard rule 7).
- It supersedes the marketing figures below as the reference for our per-minute cost, and
  the REPORTED ₹0.38 + ₹0.06 streaming reading below sums to the same ₹0.44.

### Earlier published figures

The docs publish list rates only in marketing contexts, and they disagree:

| Figure | Where | Class |
| --- | --- | --- |
| ₹0.45/min SIP channel, ₹0.65/min WebSocket, ₹500/month per number | `concepts/sip-vs-websockets.md:87-108` | VENDOR-PUBLISHED (concept page) |
| "flat ₹0.65/min" in and out | `blogs/what-is-a-voice-api.md:19-35` and several blogs | VENDOR-PUBLISHED (blog) |
| ₹0.45/min outbound | `compare/vobiz-vs-twilio.md:40,68` | VENDOR-PUBLISHED (comparison) |
| ₹25 free credit on signup | `quick-start.md:37` | VENDOR-PUBLISHED |
| Recording storage rounded up to 60 s | `recording.md:75-77` | VDOCS |

None of these is an invoice or a rate card for our account. The console itself shows no
per-minute rate card, streaming surcharge, pulse, minimum duration or GST treatment, and
has no invoice page; it shows number costs only (₹159.00/month for the held trial number,
"+₹100 setup", "₹700 release (if released)", and ₹500, ₹600 and ₹1,000 a month for
Karnataka 91-80, Gujarat 91-79 and the 92 series) (Vobiz console, founder-relayed,
2 Oct 2026, VENDOR-PUBLISHED). Hard rule 7: no telephony
figure may reach `unit_cost_paid` except an operator attestation or the CDR's own
`cost`/`total_cost` per call. A previous session REPORTED account-level figures read from
an authenticated trial console (₹0.38/min, +₹0.06 streaming, 60 s round-up,
`docs/evidence/carrier-pricing-concurrency-2026-09-17.md:80`,
`docs/evidence/per-minute-cost-model-2026-09-21.md:234,288`); re-verify before use.

## 17. Contradictions inside the vendor's docs

1. **Callback configuration page vs API reference.** `concepts/callback-configurations.md:60-129`
   uses `/applications/`, `/calls/`, `name`, `callback_url`, `callback_events` and
   `status_url`; the API reference uses `/Application/`, `/Call/`, `app_name`,
   `hangup_url` (`applications/create-application.md:10-49`; `call/make-call.md:9-45`).
   Build against the API reference.
2. **Error envelope** — two shapes (section 1).
3. **160-series scope** — "BFSI sector only" (`compliance/india/calling-regulations.md:59`;
   `faq/number-series.md:14`) vs "Service / informational voice" with 140 as
   "Promotional / transactional" (`compliance/india/ucc.md:21-25`). TRAI's text, not
   Vobiz's, governs (see `docs/evidence/telephony-regulatory-brief-2026-09-17.md`).
4. **Answer latency** — 1–2 s, 10 s, and "3 retries or 60 s" on three pages (section 3).
5. **`extraHeaders` charset** — `[A-Za-z0-9]` vs an example with `_` (section 4).
6. **Signature equivalence to Plivo** (section 6).
7. **Token rotation.** The docs say the old token stops working at once
   (`api-reference/authentication.md:54`, `concepts/validating-callbacks.md:306`); the
   console says it "stays valid for the grace window" (section 1). Plan a rotation as if
   the window were zero.
8. **Signed base URL.** The Python validator keeps userinfo in the signed URL, the Node,
   Go and Ruby ones drop it (section 6).
9. **Recording retention: 30 days vs 3.** `platform/voice/recordings.md:9,21,82` say 30
   days; the same page's screenshot shows "Storage Life of 3 days" (`:18`), defined as days
   REMAINING (`:63`). UNRESOLVED (section 9a); built to the shorter reading.
10. **Recording channels.** "8 kHz mono PCM by default" (`platform/voice/recordings.md:61`)
    vs a stereo 8 kHz WAV from the Pipecat guide's `<Record>` (`integrations/pipecat.md:811`).
11. **Recording delete.** Absent from the overview's operation table (`recording.md:65-73`),
    present in the OpenAPI (`root-site/openapi.json:8459-8484`) and the object page
    (`recording/recording-object.md:152`). Built against the OpenAPI.

## 18. What the docs do not answer

See `docs/evidence/vobiz-integration-plan.md` §14 for the full list and the console
research prompt, and §16a for what the 2 Oct 2026 console reading answered. The
load-bearing ones still open: how callback "auth credentials" are configured (and so
whether signatures are sent at all); the `dtmf` event body; the populated `extra_headers`
shape; whether call create is idempotent; account-level recording defaults (none shown);
our account's region; the billing pulse and minimum duration (the India rate card,
section 16, states the per-minute rates but neither of these); whether parent credentials act on a
sub-account; whether `cost` on a CDR is final; and the token rotation grace window.
Concurrency and CPS are answered (section 14).
