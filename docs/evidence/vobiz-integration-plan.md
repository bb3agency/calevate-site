# Vobiz integration plan — mapping the carrier contract onto our seams

**Status:** Phase A research (2 Oct 2026). Nothing here is built. Phase B implements it
after review.
**Inputs:** `docs/evidence/vobiz-api-contract.md` (the vendor contract, every fact cited
to the hash-pinned mirror `vobiz-findings/mirror/`), and a survey of every carrier seam in
this tree. Vendor facts below cite the contract's section (`contract §n`) rather than
repeating the page and line.

---

## 0. The decision this plan carries, and two it does not make

**Carried:** the founder chose Vobiz as the carrier at least through live in-call testing
(2 Oct 2026). The code was written for Plivo, but **no Plivo account ever existed** (signup
failed, `docs/evidence/carrier-caller-identity.md` §4) and **no Plivo request has ever
been sent**. The Plivo code is a set of refusals plus Pipecat's own serializer.

**Recommendation on Plivo: REPLACE, do not run two carriers.** CLAUDE.md's
one-way-per-problem rule and the fact that the Plivo half never executed both point the
same way. The seams that were already written carrier-keyed (`CARRIER_ANSWER_CONTRACT`,
`CALLER_IDENTITY_PARSE`, `CarrierCdr.carrier`, `TRANSFER_PROVIDERS`, `KNOWN_PROVIDERS`)
stay keyed and gain a `vobiz` row; every Plivo-only symbol is renamed or deleted in the
same change. No plugin framework is built for a second carrier nobody has: when one
arrives, the keyed tables are where it lands.

**Not made here, and each blocks something specific:**

1. **Whose account is it (D-474 Model B vs D-537 Model A).** Model B says the client is
   the subscriber of record on their own carrier account and we hold no carrier
   credential. Live testing on the founder's own Vobiz account is Calevate as
   subscriber, i.e. Model A for the test numbers. Vobiz's `customer_use` sub-accounts
   (KYC'd in the client's own name, contract §12) are a third shape that may satisfy
   both: the client is the KYC'd subscriber, and we drive the API from the parent. This
   needs a founder decision and a decision-log row before **number provisioning** and
   **billing the carrier cost** are built. The media leg, the answer route, the dial and
   the CDR reader do not depend on it: they take one credential pair either way.
2. **Resale.** A previous pass recorded Vobiz's Terms as prohibiting resale without prior
   written consent (`docs/evidence/carrier-plivo-vs-exotel-2026-09-16.md:167`, REPORTED,
   not re-read). The docs now describe a non-self-serve **Partner Programme** (contract
   §12). Whether partner onboarding is that written consent is a commercial question for
   Vobiz, not a docs question. It blocks taking a client live, not testing.

---

## 1. voice-runtime answer route

**Today:** `apps/voice-runtime/carrier_routes.py` serves
`GET|POST /carrier/v1/plivo/answer/{ref}`, with every `CARRIER_ANSWER_CONTRACT["plivo"]`
cell `UNKNOWN`, no signature check, an empty IP allowlist, and no body read.

**Becomes:** `GET|POST /carrier/v1/vobiz/answer/{ref}` (and the outbound form in §4).

| Cell | Vobiz value | Evidence |
| --- | --- | --- |
| `calling_party` | `("From",)` | VDOCS, contract §3 |
| `source_ip_allowlist` | the three callback IPs `15.206.6.156`, `35.154.59.246`, `15.207.8.226` | VDOCS, contract §6; "subject to change", so an operator gate (§13) |
| `signature_header` | `X-Vobiz-Signature-V3` (+ `-V3-Nonce`; `-MA-V3` for sub-accounts) | VDOCS, contract §6 |
| `echoes_stream_parameters` | stays `None` | populated `extra_headers` shape is UNKNOWN (contract §4) |

Changes:

- **Read the form body.** Vobiz POSTs `application/x-www-form-urlencoded` by default and
  sends the same fields as a query on GET (contract §3). `_answer_request_params` already
  handles both; it starts reading once `calling_party` is non-empty. That ends the
  "no IO" property the route's test asserts. The new cost is one bounded `parse_qsl` over
  an already-buffered body, as the module docstring anticipated.
- **Verify the signature, fail closed when configured.** Add `X-Vobiz-Signature-V3`
  verification: `base64(HMAC-SHA256(auth_token, base_url + "." + nonce))`, constant-time
  compare (contract §6). Two cautions:
  - `base_url` must be the URL **as Vobiz requested it**, i.e. the public
    `https://hooks.<domain>/carrier/v1/vobiz/answer/<ref>` with the query stripped. Behind
    nginx, rebuild it from configuration (the public hooks origin) plus the request path,
    never from `request.url`. A scheme or host mismatch fails every call.
  - Vobiz only sends signature headers when "auth credentials" are configured on the URL
    (contract §6). Until a console reading says how, the verifier is **data-driven like
    the IP allowlist**: a configured `VOBIZ_REQUIRE_SIGNATURE=true` makes a missing or bad
    signature a refusal; until then the route logs `auth_method="source_ip"` or `"none"`.
    Never a guessed scheme.
- **The signature covers the path and nonce, not the body** (contract §6). So the agent
  ref, which sits in the path, is authenticated; `From` is not. Keep treating the caller
  as a claim (D-649), and keep the IP allowlist as the second factor.
- **The document is unchanged in shape.** `<Response><Stream bidirectional="true"
  keepCallAlive="true" contentType="audio/x-mulaw;rate=8000">wss://…</Stream></Response>` is
  valid Vobiz grammar and is what Vobiz's own Pipecat guide serves (contract §4). Its
  evidence moves from "Pipecat's Plivo template" to VDOCS. Add nothing else in Phase B.
  In particular, add no `<Record>` (§9) and no `statusCallbackUrl` until §5's events
  route exists. `maxRetries` stays at its default of 0: a reconnect gets a new `streamId`
  and a second `start` (contract §4), which our one-session container would have to treat
  as a second call.
- **Renames:** `ANSWER_CARRIER = "vobiz"`; `plivo_answer_document` →
  `answer_document`; `plivo_stream_url` → `stream_url`; route path `/plivo/` → `/vobiz/`.
  Nothing else calls the Plivo names.
- **Hard rule 3 holds:** still no DB, Redis or queue on this route. The ack budget is
  Vobiz's: "aim for under 1-2 seconds" (contract §3), comfortably met.

## 2. The stream URL and the signed caller claim (D-649)

**Unchanged in design.** `From` from §1 becomes `AnswerCallerIdentity(state="known")`, and
the number travels on the stream URL's query only under the `caller_claim_mac` MAC,
120 s TTL, keyed by `CARRIER_CLAIM_SECRET`.

What Vobiz adds:

- **The query probably survives.** Vobiz's own Pipecat reference app puts per-call
  context on the WebSocket URL (contract §4). That is evidence, not a guarantee, so the
  first live call is the test (§13, gate V-3). If the query is stripped, the claim is
  absent rather than wrong, as today.
- **A route off the URL exists: `extraHeaders`.** The `<Stream>` element can carry
  `[A-Za-z0-9]` key=value pairs echoed as `extra_headers` on `start` (contract §4). That
  would take the caller number out of Pipecat Cloud's edge access logs (hard rule 6), as
  `carrier_routes.py` already notes for Twilio-style parameters. Its populated shape is
  UNKNOWN, so it is a follow-up after the first live call, not Phase B. The MAC is hex,
  and the E.164 digits without `+` fit the charset.
- **Number normalisation:** Vobiz examples print numbers with and without `+`. The worker
  already normalises with `normalize_phone`, and that must stay the only canonicaliser.

## 3. Worker transport and serializer

**Today:** `apps/voice-worker/bot.py:261` calls Pipecat's `create_transport` with
`_TRANSPORT_PARAMS = {"plivo": …}`. Pipecat auto-detects the carrier from the `start`
frame. Vobiz's `start` (`start.streamId` + `start.callId`) **is detected as `"plivo"`**,
and the media envelopes are identical (contract §5). So media would flow today, but the
serializer's REST hangup is hard-coded to `api.plivo.com` with Basic auth and swallows
its error (`pipecat/serializers/plivo.py:184-205`). Every agent-ended call would rely on
something else to end the carrier leg.

The helpers in `voice_worker/carrier.py` (`read_plivo_handshake`, `build_plivo_transport`,
`start_carrier_call`) are tested but **not on the shipped path**.

**Becomes:**

1. **Our own `VobizFrameSerializer` in `apps/voice-worker/voice_worker/vobiz_serializer.py`**
   (§3a explains why we do not adopt `pipecat-vobiz`). It is about 150 lines against the
   documented protocol:
   - inbound `start` (adopt `mediaFormat`; refuse anything but `audio/x-mulaw`/8000 for
     now), `media` → `InputAudioRawFrame`, `dtmf` → `InputDTMFFrame` **only once its body
     is known** (until then, log the event name and drop it), and `playedStream` /
     `clearedAudio` ignored;
   - outbound `playAudio` (μ-law 8 kHz, matching `TELEPHONY_SAMPLE_RATE_HZ`) and
     `clearAudio` on `InterruptionFrame`;
   - **on `EndFrame`/`CancelFrame`, send `{"event":"stop","streamId":…}`**. With no XML
     after `<Stream>`, Vobiz hangs the call up (cause 4010). This needs **no carrier
     credential in the worker**, unlike Plivo's REST DELETE.
   - It must call `super().__init__(params)` with a `FrameSerializer.InputParams`
     subclass, so `resampler_clear_after_secs` and the base object state are set
     (`pipecat/serializers/base_serializer.py:46-54`).
2. **Bot entry stops using `create_transport`'s auto-detection** and builds the transport
   explicitly. That is `carrier.read_plivo_handshake` + `build_plivo_transport` renamed to
   `read_handshake` + `build_transport`, so the tested helpers become the shipped path.
   The control plane's claimed carrier (`carrier=vobiz` on the stream URL) is checked
   against Pipecat's detection by a small map: wire family `"plivo"` is what a Vobiz
   socket detects as. That turns the current mismatch refusal into a correct check
   rather than a false alarm.
3. **`CALLER_IDENTITY_PARSE["vobiz"]`:** `maps_calling_party=False`, with evidence
   `contract §5` (the `start` event carries no `from`). The answer-leg claim is therefore
   the only source of the calling party, exactly as designed.
4. **Direction.** `bot.INBOUND` is a constant today. An outbound call reaches the worker
   through the same answer route (§4), so the control plane adds `direction` and, for
   outbound, our own `call_id` to the stream URL. Both go inside the claim MAC; direction
   decides billing and the consent path. `resolve_call_identity` reads them and falls back
   to a fresh uuid7 plus `inbound` only when no valid claim is present.
5. **Carrier call id.** Persist `start.callId` (= `CallUUID`, contract §5) as
   `calls.carrier_call_id`. The column exists and has no writer today. It is the join key
   for the hangup webhook, the CDR and transfer.
6. **Renames/deletes in the worker:** `PlivoCredentials`, `PLIVO_TRANSPORT_TYPE`,
   `PlivoHandshake`, the `"plivo"` key in `_TRANSPORT_PARAMS`, and `vendor_logging`'s
   suppression of `pipecat.serializers.plivo` line 221 (the new serializer must log no
   payload instead). `boot.py` drops `PLIVO_AUTH_ID`/`PLIVO_AUTH_TOKEN` from the required
   environment.

### 3a. `pipecat-vobiz`: vetted under hard rule 9 — do not adopt; write our own

| Question | Finding |
| --- | --- |
| Source | PyPI `pipecat-vobiz`. Repo `github.com/Piyush-sahoo/Pipecat-Vobiz` (personal account; created 23 Jan 2026; 0 stars, 0 forks; last push 15 May 2026). The maintainer is a public member of the `vobiz-ai` GitHub org and lists "Vobiz.ai" as his company, so it is vendor-adjacent but not under the vendor's organisation. |
| Vendor endorsement | Vobiz's own Pipecat guide and reference app depend on it: `pipecat-vobiz>=0.0.3,<0.1` (mirror `integrations/pipecat.md:23,396,752`; `vobiz-ai/Vobiz-X-Pipecat@f80b4eec requirements.txt`) |
| Licence | BSD-2-Clause. `LICENSE` names Piyush Sahoo; the module header says "Copyright (c) 2024-2026, Daily", because it is derived from Pipecat's Plivo serializer. |
| Versions | 0.0.1 and 0.0.2 (23 Jan 2026), 0.0.3 (15 May 2026). "Development Status :: 3 - Alpha". The 0.0.1 sdist is 7.1 MB against 17–21 KB for the later ones; the reason was not investigated. |
| Artefact | wheel `pipecat_vobiz-0.0.3-py3-none-any.whl` sha256 `7b226289ae1f19fff8a22f3d7e4997c1b3f31724e6371212f0678bec0facbf54`; sdist sha256 `340d06f268a3ebad8f45f0a432ad2904017b45dab02cdeae2c7d0881e6365c74`. |
| Install scripts | None. It is a pure wheel built by hatchling; `RECORD` lists one module plus metadata. No `postinstall`, no native code. |
| Dependencies | `pipecat-ai>=0.0.80` (**unbounded** above) and `aiohttp>=3.8.0`. Both are already in our lock (`pipecat-ai 1.10.0`, `aiohttp 3.14.3`), so no new transitive packages. |
| Packaging | **It installs `pipecat/serializers/vobiz.py` into another distribution's package directory.** That is a namespace overlay onto `pipecat-ai`; the vendor's guide states it (`integrations/pipecat.md:752`). Uninstalling or reinstalling `pipecat-ai` can orphan it, and hash pinning of `pipecat-ai` no longer describes what is in `pipecat/`. |
| Pin compatibility with 1.10.0 | Imports resolve in our tree: `create_stream_resampler`, `pcm_to_ulaw`, `ulaw_to_pcm`, `KeypadEntry`, `InterruptionFrame`, `OutputTransportMessage[Urgent]Frame`. The vendor's reference app pins `pipecat-ai>=1.8.1,<1.9`, so **1.10.0 is not what Vobiz tests against**. |
| Code defects found reading 0.0.3 | (1) It does not call `FrameSerializer.__init__` and its `InputParams` is a bare `BaseModel`, so `BaseObject` state and `resampler_clear_after_secs` are never set. It works today only because 1.10.0's transport never reads them (`fastapi.py` uses only `setup`/`serialize`/`deserialize`). (2) Default `hangup_method="both"` sends a REST DELETE as well as `stop`, so the worker needs carrier credentials. (3) It logs the raw first WebSocket message when it is not JSON (`parse_vobiz_start`) and the full error body of a failed hangup. Neither is PII by design, but both are vendor data in our logs. (4) It parses `dtmf.digit`, a Plivo-shaped guess: Vobiz documents no `dtmf` body. |
| What it does | It is Pipecat's Plivo serializer with four changes: a configurable encoding (μ-law or big-endian L16), 8/16/24 kHz, adopting `start.mediaFormat`, and a WS `stop` on End/Cancel. |

**Recommendation: write our own (§3 item 1).**

- The protocol is small, fully documented apart from `dtmf`, and wire-identical to the
  Plivo serializer we already pin.
- Our version can be stop-only (no worker credential), μ-law-only (the PSTN codec is PCMU,
  contract §15), and log nothing from the wire.
- It avoids a namespace overlay, an unbounded dependency on `pipecat-ai`, and an alpha
  single-maintainer package on the hottest path in the product.

If the founder prefers adoption anyway, the only acceptable form is an exact pin with
hashes, e.g. `pipecat-vobiz==0.0.3 --hash=sha256:7b226289…bf54` in
`apps/voice-worker/pyproject.toml` and `uv.lock`, constructed with
`hangup_method="ws_stop"`, plus a test asserting that `pipecat/serializers/vobiz.py`
hashes to `RECORD`'s value. That is more machinery than the 150 lines it replaces.

## 4. Outbound dialling: campaigns, call-backs, "call this lead"

**Today:** every dial goes through `apps/api/agents/service.py:2856 dispatch_call`, which
writes an intent `calls` row and calls `PipecatEngine.start_outbound_call`
(`apps/api/engine/pipecat.py:1471`), which **refuses** (`_carrier_not_written`). Callers:

- campaigns: `apps/workers/campaign_dispatch.py:1088`
- call-backs: `apps/workers/callbacks.py:152`
- "call this lead": `apps/api/crm/routes.py:1456`
- call back from a call: `apps/api/crm/routes.py:1715`
- ingest auto-dial: `apps/api/ingest/service.py:538`

There is **no "test call" feature**: the admin prompt page says it is done by hand.

**Becomes:** `start_outbound_call` posts `POST /api/v1/Account/{auth_id}/Call/`
(contract §2) with:

- `from` = the agent's bound caller-ID number (a Vobiz-rented Indian number, contract §14);
- `to` = the lead's E.164;
- `answer_url` = `https://hooks.<domain>/carrier/v1/vobiz/answer/{ref}/outbound/{call_id}`
  — **the call id goes in the PATH, not the query, because the signature covers the path
  and strips the query** (contract §6);
- `answer_method=POST`, `hangup_url`/`ring_url` = the events route (§5) with the same
  path suffix;
- `time_limit` = the agent's duration cap plus a margin, so the carrier enforces a ceiling
  even if the worker dies.

Rules for the dial path:

- **No idempotency key exists** (contract §2). Never retry a dial whose outcome is unknown
  (timeout, 5xx, connection reset): mark it `dial_outcome_unknown` and let reconciliation
  (§8) find it by `to_number` and time window in the CDR. Retry only on a definite refusal
  such as 429 (CPS/concurrency; honour `retryAfter`). 402 (balance) is not retryable and
  alarms. 401 means credentials or path casing.
- `request_uuid` from the 200 response is the `CallUUID` (contract §2). Store it as
  `calls.carrier_call_id` at once.
- **CPS pacing.** The account's CPS may be 1 (REPORTED for the trial account, contract
  §14). `campaign_dispatch` must space dials by `1 / cps_limit` seconds, read from
  `GET …/concurrency` and the account object (contract §14), not from a constant.
- **Compliance stays where it is.** The dispatch gate, DNC and consent checks run before
  `start_outbound_call`. Vobiz's own NDNC scrub (contract §14) is a second layer, never
  the first.
- **AMD:** `machine_detection=true` with `machine_detection_url` maps to our `voicemail`
  status. That is optional in Phase B and off by default.
- **Test call:** no new feature. Use "call this lead" against a consented test lead on
  the founder's own number; it exercises the real dispatch path, gate included.

## 5. Status and hangup webhooks → `CallEvent`

**Today:** no carrier callback route exists. The pipecat engine declares
`webhook_auth="none"` because "nothing external calls us"
(`apps/api/engine/pipecat.py:1396-1424`).

**Becomes:** one route, `POST /carrier/v1/vobiz/events/{ref}[/outbound/{call_id}]`, used as
`hangup_url` (on the application and on each dial) and `ring_url`, and later as
`statusCallbackUrl`.

- **Reuse the existing intake machinery, do not fork it.** `webhook_routes._receive`
  already does source check → inbox claim (`webhook_deliveries`) → ARQ enqueue → `X-Ack-Ms`
  under `AckMeter`. The carrier events route calls the same path with a carrier-kind
  source verifier (signature V3 + IP allowlist, as in §1). Dedupe key: `CallUUID` +
  `Event`, because Vobiz retries non-200 up to 3 times (contract §6).
- **Ack < 500 ms** (hard rule 3) is well inside Vobiz's 3 s requirement (contract §6).
- **Normalisation** (in the worker job, not the route): `Ring` → `ringing`; `StartApp` →
  `in_progress`; `Hangup` → terminal, mapped from `HangupCause` (`NORMAL_CLEARING` →
  `completed`, `USER_BUSY` → `busy`, `NO_ANSWER`/`ORIGINATOR_CANCEL` → `no_answer`,
  everything else → `failed`; contract §15 lists the causes); `MachineDetection` →
  `voicemail`. `Hangup` is the authoritative end of the call; the WebSocket close is the
  worker's end of the media, and the two are reconciled, not merged.
- **Timestamps:** `StartTime`/`AnswerTime`/`EndTime` on the hangup callback are in the
  **console's local timezone** (contract §6). Either set the console timezone to UTC and
  record that as an operator gate, or ignore those fields and take times from the CDR (ISO
  8601 UTC). Prefer the CDR.
- **Hard rule 6:** the callback carries `From`/`To`. The route logs ids only.
- `PIPECAT_CAPABILITIES.webhook_auth` changes from `"none"` to the carrier's verified
  method, and `engine_intake.verify_source` gains the carrier kind rather than a second
  verifier.

## 6. Hangup

- **Agent-ended call:** the serializer sends `stop` (§3). No credential is needed.
- **Caller hangs up:** the socket closes and `arm_first_turn`'s disconnect handler pushes
  `EndWorkerFrame`. Unchanged.
- **Control-plane hangup** (`PipecatEngine.end_call`, today a refusal, plus the
  reconciler's "stuck call" sweep): `DELETE …/Call/{carrier_call_id}/` from the API or
  workers, which hold the credential (contract §7). The worker never does.
- **Backstops:** `time_limit` on every dial (§4), and `streamTimeout` set to the agent cap
  rather than the 24 h default.

## 7. Transfer / human handoff

**Today:** `request_handoff` answers `not_available` (`apps/api/worker/tools.py:489-524`),
because the registry maps `pipecat` → `plivo` → `PlivoTransfers` with
`contract_verified=False`.

**Vobiz supports it** (contract §8):

1. `POST …/Call/{carrier_call_id}/` with `legs=aleg` and
   `aleg_url=https://hooks.<domain>/carrier/v1/vobiz/transfer/{handoff_token}`.
2. That URL returns `<Dial callerId="<owned number>" timeout="…" timeLimit="…"
   callbackUrl="…/events/…" action="…" redirect="false"
   confirmSound="…">+91…</Dial>`.
3. `DialHangup`/`action` report the B-leg's duration and outcome, so the second leg is
   meterable.

**The gate is fact 3, and Vobiz answers it against us:** `confirmKey` "enforcement as an
acceptance gate is currently unverified, so do not depend on a keypress" (contract §8).
The whisper (`confirmSound`) works; accept-by-keypress is not vouched for.

Plan: add `apps/api/agents/transfer_providers/vobiz.py` (`VobizTransfers`), replacing
`plivo.py`. `TRANSFER_PROVIDERS = ("vobiz", "fake")`, and the registry maps `pipecat` →
`vobiz`. Keep `contract_verified=False` until a live test shows the whisper and the
bridge working, and until the founder decides between:

- a whisper-only warm transfer (the agent is told, cannot decline by key), or
- keeping `not_available`.

Building it does not need that decision; enabling it does.

The `<handoff_token>` must carry the destination and the brief under a MAC, because the
transfer route, like the answer route, may not read the database (hard rule 3).

**Interaction with the stream:** the transfer interrupts the `<Stream>` flow (contract
§8), so the worker sees its socket close. The worker must tell a transfer-close from a
hangup-close, or the call settles as `completed` mid-transfer. Phase B: the control plane
sets a per-call "transfer in progress" fact that settlement reads. That is a design item
for the transfer change, not the first live call.

## 8. Reconciliation poller and the CDR reader

**Today:**

- `reconcile_executions` → `PipecatEngine.list_executions` returns
  `incomplete_reason="carrier_cdr_unavailable"`.
- `voice_worker/carrier.py::fetch_call_detail_record` refuses.
- `meter.CarrierCdr` has no producer, and every call settles `meter_carrier_cdr_missing`.

**Becomes:**

- A **CDR reader in `apps/workers`**, not the worker container, so the carrier credential
  stays off Pipecat Cloud: `GET /api/v1/Account/{auth_id}/cdr/{CallUUID}` (contract §15).
- It is triggered by the `Hangup` event job (§5). On 404 ("CDR exists only after the call
  ends"), it re-enqueues with backoff. The 10-minute `reconcile_executions` sweep catches
  anything the event missed, using `cdr/search` by date and direction.
- It produces `CarrierCdr(connected_seconds=billsec, carrier="vobiz", cdr_id=uuid)` plus
  the cost fields (§10).
- `fetch_call_detail_record` moves out of the worker package. The worker never calls it.
- `list_executions` lists CDRs for the window and reports `complete=True` when
  pagination is exhausted.
- **The reconciler also closes stuck calls:** a `calls` row in progress with no worker
  heartbeat and a `?status=live` hit (contract §2) is hung up by REST.

## 9. Recordings and retention

- **We do not ask Vobiz to record.** No `<Record>` in the answer document, no record API
  call (contract §9). `PIPECAT_CAPABILITIES.records_audio=False` is unchanged.
- **Gate:** confirm in the console that no account-level or number-level auto-recording is
  on (contract §9 says no default is documented). If one exists, turn it off and record
  the reading.
- If recording is ever wanted, take it from our own pipeline into our storage
  (`apps/workers/storage.py`), because Vobiz recordings live in its storage (a blog says a
  30-day window, REPORTED) and would need a separate erasure path.
- Erasure register: `compliance/deletion.py::TELEPHONY_OUTCOME` and
  `processor_erasure.PROCESSORS["telephony"]` change their cited source from the Plivo
  serializer to Vobiz. Vobiz holds CDRs (numbers, times, costs) with **UNKNOWN retention**
  (§14), and **no CDR delete endpoint is documented**. The erasure outcome for the carrier
  is "retained by the processor, period unknown" until a DPA says otherwise.

## 10. Telephony metering and cost (hard rule 7)

**Today (D-648):** billable seconds come from the worker's measured duration, and
`unit_cost_paid` is NULL. `billing/rates.py:1182-1450` holds a **Plivo** India card
(VENDOR-PUBLISHED, relayed) that reaches no bill; `tests/telephony_cost_test.py` pins it.

**Becomes:**

- **Quantity:** `billsec` from the CDR replaces the worker duration as the authority for
  the carrier minute, once the CDR exists (D-651's `billable_ready` flips on it).
- **Cost:** the CDR carries `cost`, `total_cost` (includes streaming), `streaming_cost`
  and `currency` per call (contract §15). That is the vendor's own per-call charge record.
  Write `unit_cost_paid` from `total_cost` only when `currency == "INR"`, parsed as
  `Decimal` from the JSON string (never via float). Anything else stays NULL with an
  alarm.
  - Whether `cost` can be revised after first read is **UNKNOWN** (§14). Because
    `usage_events` is append-only (hard rule 4), read the CDR once it is stable (a second
    read after N minutes agreeing with the first), or write a compensating entry on
    change.
- **Whose cost** is the Model A/B question in §0. On the founder's own test account it is
  Calevate's cost.
- **The Plivo rate card is deleted with its test**, not converted. Vobiz's published
  figures disagree with each other (₹0.45 vs ₹0.65/min, contract §16), so none of them is
  fit for a constant. If a floor needs a planning figure, add an operator-attested
  telephony price, following the pattern `ops/model_pricing.py` uses for LLMs. Per-call
  truth is the CDR.
- **Number rental:** `number_price_attestations` (operator-attested) already covers it.
  The contract shows `setup_fee`/`monthly_fee` on the number object, which is a
  vendor-reported reference for the attestation, not a substitute for it.

## 11. Number provisioning: `NUMBER_PROVIDER` and `phone_numbers`

- `KNOWN_PROVIDERS` already contains `vobiz` (`apps/api/campaigns/provisioning.py:116`).
  Set `NUMBER_PROVIDER=vobiz`.
- `PROVISIONING_IMPLEMENTED=False` stays until the §0 Model decision. For live testing,
  the founder buys the test number in the Vobiz console and an operator records it
  through the existing admin route `POST /tenants/{id}/numbers`, with `provider="vobiz"`
  and `engine_number_ref` = the Vobiz number id.
- **Inbound routing is per Application, not per number** (contract §11). Each agent with
  an inbound number gets one Vobiz Application whose `answer_url` is
  `…/carrier/v1/vobiz/answer/{ref}` and whose `hangup_url` is the events route, then the
  number is attached to it. Two gaps to fill:
  - `phone_numbers` needs a column for the Vobiz `app_id` (or the app id is derived and
    stored in `engine_number_ref` metadata). A migration with RLS unchanged, hard rule 8.
  - `bind_inbound_number`/`unbind_inbound_number` (`pipecat.py:1563-1579`, refusals today)
    become create-or-update application + attach/detach number. The application name must
    match `[A-Za-z0-9_-]`, so use the agent's uuid without braces.
  - Hard rule 1 / D-603 is preserved: routing stays in the URL path we mint, never a
    lookup by dialled number.
- **Carrier application / KYC:** `compliance/carrier_application.py` hard-codes
  `CARRIER="plivo"`, and the CHECK in `alembic/versions/c7a4f9e15b03_…py:182` allows only
  `'plivo'`. Add `'vobiz'` in a new reversible migration. Drop `'plivo'` only in a later
  release (two-step, hard rule 8). The `customer_use` sub-account KYC (contract §12) is the
  natural backing for this flow under Model B; it waits for §0.
- **140/160/92 series** are provisioned by request to Vobiz support, not by API (contract
  §14). `PURCHASABLE_SERIES="standard"` stays.

## 12. Settings and secrets (env-only, never in the DB)

| Setting | Where | Notes |
| --- | --- | --- |
| `VOBIZ_AUTH_ID`, `VOBIZ_AUTH_TOKEN` | API + workers + voice-runtime (signature key) | Added to `ENV_ONLY_REASONS` in `apps/api/core/settings.py`, so `tests/conftest._no_ambient_credentials` strips them automatically. **Not** in the Pipecat worker secret set. |
| `PLIVO_AUTH_ID`, `PLIVO_AUTH_TOKEN` | removed | From `config.py:494-495`, `settings.py:255-268,327-332`, `boot.py:157-158,432-433`, `scripts/deploy/pipecat-worker-setup.sh:213-221,277-278,705-710`, `ConfigPanel.tsx:159-167`, and `DEPLOYMENT.md` §12.5 gate 11. |
| `CARRIER_CLAIM_SECRET` | unchanged | VPS env + worker secret set. |
| `PIPECAT_STREAM_BASE_URL` | unchanged | |
| `VOBIZ_REQUIRE_SIGNATURE` (or a contract-table flag) | voice-runtime | Off until the console gate in §13 is closed. |
| `NUMBER_PROVIDER=vobiz` | live config | |

- `apps/api/ops/secret_probes.py` can now probe the carrier credential safely with
  `GET /api/v1/auth/me` (contract §1). Plivo had no safe probe.
- `scripts/check_subprocessor_coverage.py` derives vendors from `_auth_id`/`_auth_token`
  fields, so adding `vobiz_auth_*` means: `VENDOR_OF["vobiz"]="Vobiz"`, remove Vobiz from
  `REGISTER_ONLY`, and give Plivo a `REGISTER_ONLY` entry or remove it from the register
  (legal decision, §15).
- Lock the Vobiz API to our egress IPs (`ip_auth_enabled`/`ip_whitelist_rules`, contract
  §1) once the console shows how. That is a console gate.

## 13. nginx routes and rate zones

**Today** there is no `/carrier/v1/` location. The answer route rides the `hooks` vhost's
catch-all `location /` with `zone=webhooks` at 600 r/m
(`infra/nginx/calevate.conf.template:682-696`; `rate-zones.conf.template:53`).

**Becomes:**

- A dedicated `location ^~ /carrier/v1/` on the hooks vhost with its own
  `limit_req_zone … zone=carrier`, so a webhook flood cannot starve the answer
  documents a ringing call is waiting on. Size it from the account's concurrency, not
  guessed. `proxy_request_buffering on` for this location, because the route reads small
  form bodies.
- **The IP allowlist stays in the application** (data-driven `source_ip_allowlist`), not
  in nginx `allow/deny`. Vobiz says the addresses "are subject to change" (contract §6),
  and an nginx deny would turn a renumbering into an outage with no log line in our code.
- The WebSocket is terminated by Pipecat Cloud, not our nginx. Nothing changes there.

## 14. What the documentation does not answer

These need someone logged in to the Vobiz console or holding the account. Section 16 is
the browser-agent prompt that collects them.

1. **Signature enablement:** what "auth credentials configured on the callback URL"
   means, where it is set, and whether the **answer URL** request is then signed
   (contract §6). This decides whether §1 and §5 can verify anything.
2. **Our account:** `auth_id` type (MA_/SA_); trial or paid; KYC status (individual vs
   company); "India data region" or not; inbound enabled (trial is outbound-only).
3. **Limits:** `concurrent_calls_limit`, `cps_limit`, base vs purchased.
4. **Numbers held:** e164, series (standard / 140 / 160 / 92), status,
   `aadhaar_verification_required`, `setup_fee`, `monthly_fee`, currency, attached
   application.
5. **Recording defaults:** any account-, number- or application-level auto-record
   setting; the retention of Vobiz-held recordings and CDRs.
6. **Rates for our account:** per-minute inbound and outbound (mobile and landline),
   streaming surcharge, billing increment and minimum, and number rental. Taken from the
   rate card or invoice view, with GST treatment.
7. **The console timezone** (it stamps hangup-callback times, contract §6).
8. **API IP allowlist settings** (`ip_auth_enabled`) and the callback IP-change
   notification subscription.
9. **The populated `extra_headers` shape** and the **`dtmf` event body**. These are best
   captured from one live test call's logs rather than the console.
10. **Whether the parent's credentials act on a sub-account's resources.**
11. **Whether CDR `cost` is final at creation.**
12. **Partner programme / resale consent status** (commercial).
13. **Where Vobiz processes media** for a `<Stream>` to an Indian `wss://` endpoint, and
    whether Pipecat Cloud's edge for our worker is in India, given media anchoring
    (contract §14).

## 15. Sub-processor disclosure (legal impacts — listed, not edited)

Vobiz becomes **the** named telephony sub-processor. It carries caller and called numbers,
live call audio in transit both ways, call metadata and CDRs (numbers, times, costs), and
KYC documents if `customer_use` sub-accounts are used.

- `apps/web/src/lib/legal/subprocessors.ts:282-304`: the carrier row says
  "Exotel · Vobiz · Plivo … not settled". It must name Vobiz (Ilaimitado Private Limited),
  the data categories above, the processing location (CDR `region: ap-south-1`, contract
  §14; full residency **UNKNOWN**), and retention (UNKNOWN until §14 item 5).
- `/legal/privacy` and `/legal/dpa`: the telephony processor, its location and transfers,
  and whether Vobiz trains on or analyses audio (not addressed in the docs; needs their
  privacy policy and terms read).
- A **DPA with Vobiz** does not exist (no evidence of one). Needed before client data
  flows.
- `docs/LEGAL-SURFACE.md` and `scripts/check_subprocessor_coverage.py` (§12).
- Erasure reach (`docs/evidence/subprocessor-erasure-reach.md`): CDRs at Vobiz have no
  documented delete.
- The UCC/NDNC complaint process (contract §14) gives Vobiz a 24-hour enforcement lever
  over the account. It belongs in the outbound compliance runbook, and possibly in the
  `account/ndnc-webhook` intake feeding our DNC list (a later seam).

## 16. Browser-agent research prompt (founder's Comet)

Paste the block below into Comet while logged in to `https://console.vobiz.ai` as the
account owner. It only reads: it must not change a setting, buy or release anything,
place a call, or reveal a secret.

```text
You are collecting evidence from the Vobiz console (https://console.vobiz.ai) for an
engineering team. I am logged in as the account owner. READ ONLY: do not click Save,
Buy, Release, Delete, Regenerate, Call, Top up, or anything that changes state, and do
not accept any dialog. NEVER copy, type out or screenshot an Auth Token, password, API
secret or full card/bank number — if a value is a secret, write "[secret, present]" or
"[secret, absent]" instead. Mask all but the last 4 digits of any phone number that is
not one of the account's own rented numbers.

For EVERY item below, report in exactly this format:
  Item: <number and name>
  URL: <full console URL of the page you read it on>
  Read at: <date and time, with timezone>
  Navigation: <menu path you clicked, e.g. Settings > API>
  Exact labels and values: <each field label exactly as printed, and its value exactly as
    printed, including units and currency>
  Screenshot: <describe what a screenshot of that panel shows; take one and keep it>
  Not found: <if the console does not show it, write "NOT SHOWN ON <URL>" — do not guess,
    do not infer from documentation or marketing pages>

Items:
1. Account identity: the Auth ID prefix (MA_ or SA_) and its last 4 characters only;
   account type (trial/paid); KYC status and KYC type (Individual or Company); whether
   the account is an "India data region" account; account timezone setting; currency
   of the balance.
2. Limits: concurrent calls limit and CPS limit as shown, and whether the console splits
   them into base and purchased.
3. Inbound: is inbound calling enabled or blocked (trial accounts are outbound-only)?
   Exact wording of any banner about it.
4. Phone numbers: for each number the account holds — number (full; these are ours),
   number type/series (standard mobile, landline, 140, 160, 92, toll-free), status,
   monthly fee, setup fee, currency, minimum commitment, Aadhaar verification flag, and
   the Application it is attached to (name and app id), if any.
5. Applications: for each Application — name, app id, Answer URL and method, Hangup URL
   and method, Fallback URL, and any field about callback authentication, credentials,
   signing or "auth" on the URL. Open the edit form (without saving) and list every
   field label on it.
6. Callback signing: search the whole console (Settings, Developer, API, Webhooks,
   Applications, Security) for anything that enables or configures webhook/callback
   signatures, "auth credentials" for callback URLs, HMAC, X-Vobiz-Signature, or a
   shared secret. Report the exact labels and where they are. If nothing exists, say
   NOT SHOWN and list the pages you checked.
7. Recording: any account-, number- or application-level setting that records calls
   automatically; its current value. Any recording retention or storage-period setting
   and its value. Whether the Recordings page lists any recordings (count only).
8. Rates: the rate card or pricing page for THIS account — per-minute rate for inbound
   and outbound to Indian mobile and landline, WebSocket/audio-streaming surcharge,
   billing increment (pulse) and minimum billable duration, number rental by series,
   and whether GST is included or extra. Also open the most recent invoice or
   transaction list and report the line-item labels (not amounts tied to personal data).
9. CDR / call logs: open one completed call's detail (if any exist). List every field
   label shown, and whether "cost" or "total cost" appears, its currency, and whether
   the page says it can change later. Do not copy the other party's number.
10. Security: any API IP allowlist / "IP authentication" setting (label, current state);
    any IP-change notification subscription; two-factor status.
11. Sub-accounts: does the account have sub-accounts; the create form's field labels
    (especially kyc_mode / "customer use" / "personal use"); any statement about whether
    the parent's credentials can act on a sub-account.
12. Partner programme: any Partner Portal menu, partner status, reseller or white-label
    terms shown, and the exact wording of any terms acceptance the account has made about
    resale. Also open https://www.vobiz.ai/legal#terms and quote, with heading, the
    clause about resale or sublicensing, with the page's "last updated" date.
13. Region and media: anything in the console that states where calls, media or data are
    processed or stored (region names, "India", "ap-south-1"), with exact wording.
14. Compliance contacts: the UCC/NDNC compliance contact field(s) and whether they are
    filled in (yes/no only), and whether the NDNC complaint webhook is shown as active.

Finish with a list of every item number you could NOT answer and the URLs you checked
for it.
```

Two items in §14 are better captured from a live test call than from the console: the
populated `extra_headers` shape and the `dtmf` event body (log the raw `start` and one
`dtmf` frame in a test run, with numbers masked).

## 17. Docs, gates and tests to change

**Docs**

- `docs/ROADMAP.md`: a decision row for "Vobiz replaces Plivo as the carrier". It
  supersedes the Plivo assumption in D-603/D-610/D-614, amends D-05, and names the open
  Model A/B question.
- `docs/PIPECAT-MIGRATION.md` §6 steps 6-7 and §7 unknowns (rewrite against the contract);
  `docs/DEPLOYMENT.md` §12.2/§12.5; `runbooks/first-deploy.md:62-69`; `CLAUDE.md:776` area
  (`PLIVO_AUTH_ID` mention).
- `docs/evidence/carrier-caller-identity.md` §5: (d) and (f) are answered for Vobiz;
  (c) is partly answered (`extraHeaders`).

**OPERATIONS §2 gates**

- **Gate 55 is re-aimed:** "Vobiz signs the answer request (V3) once callback credentials
  are configured; verified on the first live call". Bolna-era gates 25, 25c and 28 can be
  retired.
- New gates:
  - V-1: callback IPs current, with the change subscription.
  - V-2: no auto-recording.
  - V-3: the stream URL query survives (claim arrives) and the path is preserved through
    Pipecat Cloud.
  - V-4: `dtmf` body and `extra_headers` shape captured.
  - V-5: concurrency/CPS read from the account.
  - V-6: console timezone.
  - V-7: CDR cost stability.
  - V-8: media anchoring with Pipecat Cloud's region.
  - V-9: API IP lock.
  - V-10: written resale consent / partner onboarding before a client goes live.

**Tests**

- Change (carrier core): `tests/voice_worker_carrier_test.py`,
  `voice_runtime_carrier_answer_test.py`, `carrier_answer_identity_test.py`,
  `carrier_identity_states_test.py`, `carrier_compliance_test.py`,
  `handoff_transfer_seam_test.py`, `pipecat_credentials_test.py`,
  `voice_worker_boot_test.py`, `telephony_cost_test.py` (delete the Plivo card),
  `telephony_provisioning_test.py`, `number_supply_test.py`,
  `model_b_credential_binding_dial_test.py`, `calls_carrier_call_id_test.py`, and
  `packages/shared/tests/engine_conformance/contract_test.py` (`provider="plivo"`).
- Change (metering): `voice_worker_meter_test.py`, `voice_worker_sink_test.py`,
  `pipecat_call_billing_test.py`, `remetering_test.py`, `worker_api_test.py`.
- Incidental string changes: `voice_worker_pipeline_test.py` (vendor_logging pin),
  `voice_worker_gnani_tts_test.py`, `platform_config_test.py`; web
  `a11y.test.tsx`, `adminCarrierApplication.test.tsx`, `adminNumberAttachment.test.tsx`,
  `opsHardening.test.tsx`, `verification.test.tsx`.
- New:
  - `tests/vobiz_serializer_test.py`: every documented envelope both ways, from the
    contract's JSON, including `stop` on End/Cancel and no REST call.
  - `tests/vobiz_signature_test.py`: V2/V3 vectors computed from the documented formula;
    query-stripping; a missing header when required → refused.
  - `tests/vobiz_dial_test.py`: request shape, call id in the path, no retry on unknown
    outcome, 429/402 mapping.
  - `tests/vobiz_events_route_test.py`: inbox dedupe on retry, ack meter, normalisation
    table.
  - `tests/vobiz_cdr_reader_test.py`: `billsec`, INR `Decimal` cost, 404 → retry,
    non-INR → NULL + alarm.
  - `tests/vendor_evidence_guard_test.py`: extend to `vobiz-findings/mirror/MANIFEST.json`
    (every page hashes to its manifest entry), the ruff exclusion, and the
    `.gitattributes` `-text` line.

## 18. Estimated files to change

About 45 Python/TS files, 1–2 migrations and about 8 docs.

**voice-runtime**

- `apps/voice-runtime/carrier_routes.py`
- `apps/voice-runtime/main.py`
- `apps/voice-runtime/webhook_routes.py`
- `apps/voice-runtime/engine_intake.py`

**voice-worker**

- `apps/voice-worker/bot.py`
- `voice_worker/carrier.py`
- `voice_worker/vobiz_serializer.py` (new)
- `voice_worker/boot.py`
- `voice_worker/meter.py`
- `voice_worker/vendor_logging.py`
- `voice_worker/lifecycle.py` (comments)
- `voice_worker/pipeline.py` (comments)
- `voice_worker/gnani_tts.py` (comments)
- `apps/voice-worker/pyproject.toml` (no new dependency if §3a is followed)

**api**

- `apps/api/engine/pipecat.py`: dial, end_call, transfer, bind/unbind,
  list_executions, capabilities
- `apps/api/engine/vobiz_client.py` (new): a thin `httpx` client for Call, CDR,
  Application and numbers
- `apps/api/agents/transfer_providers/{base,registry,vobiz(new)}.py`; `plivo.py` deleted
- `apps/api/agents/service.py`: dial outcome codes
- `apps/api/worker/tools.py`
- `apps/api/core/settings.py`
- `packages/shared/src/calevate_shared/config.py`
- `apps/api/ops/secret_probes.py`
- `apps/api/compliance/{carrier_application,models,deletion,processor_erasure}.py`
- `apps/api/billing/rates.py` (Plivo card removed)
- `apps/api/agents/models.py` (Vobiz app id)

**workers**

- `apps/workers/pipeline.py`: hangup event job, CDR reader trigger, reconcile
- `apps/workers/cdr.py` (new)
- `apps/workers/campaign_dispatch.py` (CPS pacing)
- `apps/workers/settings.py` (job registration)

**shared**

- `packages/shared/src/calevate_shared/engine.py`: capabilities, `webhook_auth`

**migrations**

- `alembic/versions/<new>_carrier_application_vobiz.py`
- `alembic/versions/<new>_phone_numbers_vobiz_app_id.py`

**infra and scripts**

- `infra/nginx/calevate.conf.template`
- `infra/nginx/rate-zones.conf.template`
- `scripts/deploy/pipecat-worker-setup.sh`
- `scripts/check_subprocessor_coverage.py`

**web**

- `apps/web/src/app/admin/ops/ConfigPanel.tsx`
- `apps/web/src/lib/legal/subprocessors.ts` (legal revision, after review)

**Docs** are listed in §17.

**Tests:** about 25 existing tests change and 6 new ones are added (§17).

## Phase B: as built (2 Oct 2026)

Recorded from the working tree on the day it was written, D-662. The test suite and the
coverage ratchet were not run as part of writing this section.

**Where the build departs from this plan.**

1. **A switch, not a replacement** (founder decision, D-662). §0 recommended deleting the
   Plivo half. Instead `Settings.carrier` is `vobiz` or `plivo`, default `vobiz`, applied
   as needs-republish; both carriers' answer and events routes stay served, and Plivo's
   REST side is `apps/api/engine/plivo_carrier.py`, the refusals it always was.
2. **The CDR sets our cost, not the client's quantity.** §10 had `billsec` replacing the
   worker's duration. As built (`apps/workers/carrier_events.py`), the client's minutes
   stay on the D-648 `telephony_s` row, and the CDR writes one compensating `other` row
   with the carrier's INR `total_cost` as `unit_cost_paid`, `billsec` in its `meta`,
   keyed on the carrier call id so it is written once. Billing a client from `billsec` is
   left to the billing owner.
3. **`total_cost` is a JSON number, not a string** (`vobiz-findings/mirror/pages/
   cdr.md:171,278`), contrary to §10's wording. The reader parses the body with
   `parse_float=Decimal` (`apps/api/engine/vobiz.py::VobizCarrier.fetch_cdr`), so no cost
   passes through a float.
4. **No nonce replay cache.** The answer route stays free of IO; the events route's inbox
   already makes a replayed (`CallUUID`, `Event`) a no-op
   (`apps/voice-runtime/carrier_auth.py`).
5. **A bad signature is refused even when signing is not required.** A missing one is
   refused only under `vobiz_signature_required` (the plan's `VOBIZ_REQUIRE_SIGNATURE`).
6. **Transfer is built and off** (`carrier_transfer_enabled`, default False). The `<Dial>`
   destination rides an AES-256-GCM sealed token (`apps/api/core/carrier_token.py`, key
   derived from `CARRIER_CLAIM_SECRET`) rather than a MAC, so the number is not readable in
   access logs.

**What exists, by deployable.**

- **Shared:** `calevate_shared.carrier` (names, `answer_path` / `events_path` /
  `transfer_path` with our call id as a path segment, `VOBIZ_CALLBACK_IPS`,
  `CARRIER_EVENT_JOB = "ingest_carrier_event"`); `worker_api.call_claim_mac` /
  `verify_call_claim` for the outbound call id and direction on the stream URL.
- **voice-runtime:** `carrier_routes.py` (answer and transfer routes; `authenticate`
  checks the source address, then the V3 signature over the URL rebuilt from
  `webhook_base_url`), `carrier_auth.py` (the pure checks), `carrier_events.py` (the
  events route, through `webhook_routes.settle` into the inbox and ARQ). nginx has a
  `location ^~ /carrier/v1/` with its own `carrier` zone, 600r/m, burst 100.
- **Worker:** `voice_worker/vobiz_serializer.py` (μ-law 8 kHz only; `stop` on End/Cancel;
  `dtmf` dropped; nothing from the wire logged); `voice_worker/carrier.py` chooses the
  serializer from the stream URL's carrier claim, falling back to `CARRIER`; `boot.py`
  requires `PLIVO_AUTH_*` only when `CARRIER=plivo`.
- **API:** `apps/api/engine/carrier.py` (`CarrierClient`, `get_carrier`),
  `apps/api/engine/vobiz.py` (call create with `time_limit` = the agent's cap plus 60 s,
  at most 14,400; hangup; transfer; CDR; Application create and number attach; the
  `/auth/me` probe). Only 429 is retried (`apps/api/engine/vendor_http.py`). Binding
  needs the number's `engine_number_ref` set and stores the Application id in
  `phone_numbers.carrier_binding_id` (migration `d4a7b2c91e30`, which also admits
  `vobiz` in the `carrier_compliance_applications` CHECK).
- **Workers:** `ingest_carrier_event` (status moves forward only), `read_carrier_cdr`
  (first read 60 s after the hangup, retried while the CDR is absent),
  `reconcile_carrier_cdrs` (cron), and `carrier_pacing.py` (a Redis spacing lease of
  `1000 / carrier_cps` ms in front of both dial loops; fails open).

**Not built, and why.** Number purchase through the API and every client-account model
(waits on §0's Model A/B decision); `extraHeaders` and keypad input (gate V-4); answering
machine detection and `statusCallbackUrl` (optional in §4/§1); the sub-processor
disclosure (§15, a legal revision for the founder). The console readings are OPERATIONS §2
gate 55 and V-1 to V-10, and the first call is `runbooks/vobiz-first-live-call.md`.
