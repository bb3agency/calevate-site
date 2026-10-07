# Runbook — the first live call on Vobiz

**For:** the founder or an operator placing the first real phone call through the owned
runtime (D-592) on the Vobiz carrier (D-662), on the founder's own Vobiz account.

**What it proves.** No call has ever been placed on this product. This sitting closes the
gates only a live call can: OPERATIONS §2 gate 55 (signing) and V-1, V-2, V-3, V-4 and V-8,
and it takes the first call readings for V-6 and V-7 (V-5's limits were read in the
console on 2 Oct 2026). Write each result into its gate row with the date. §10 and §11 are the
token and callback-secret rotation procedures, which are not part of the sitting.

**Ground rules for the whole sitting.**

- Only the founder's own phones are called, and only the founder's own number calls in.
  No client number and no lead from a real client.
- Never paste an Auth Token, a signature header value or a full phone number into a
  ticket, a chat or a gate row. Phone numbers are recorded with all but the last four
  digits masked (`+91XXXXXX1234`), except the account's own rented Vobiz number.
- Vendor facts below are cited into `docs/evidence/vobiz-api-contract.md` ("contract §n"),
  which cites the hash-pinned mirror `vobiz-findings/mirror/pages/`.

---

## 1. Vobiz console prerequisites

Check each in the console (`https://console.vobiz.ai`) and record what the page says.
The console was read once on 2 Oct 2026 (Vobiz console, founder-relayed, VENDOR-PUBLISHED;
`docs/evidence/vobiz-integration-plan.md` §16a). Where that reading answered an item it
is noted; re-read anything the recharge below could change.

- [ ] **The account is recharged, or converted to a full account, before any live call.**
      On 2 Oct 2026 it was a trial account: banner "Complete your first recharge to
      convert to a full account and unlock all features", ₹25 trial credit, and the one
      number tagged TRIAL. Vobiz documents that trial numbers cannot take inbound calls
      (`faq/trial-inbound.md:9`), which is why inbound waits for the recharge. The founder
      states that recharging is all it takes to activate the account and convert the
      trial (2 Oct 2026). After the recharge, record whether the TRIAL banner and the
      number's TRIAL tag are gone. If the number stays TRIAL, inbound needs a newly bought
      number.
- [ ] **KYC is complete.** Only India-registered businesses may rent Indian numbers and
      use domestic routes, and KYC comes first (contract §14). Read 2 Oct 2026: "Verified"
      (PAN and Aadhaar); individual or company KYC type not shown.
- [ ] **The account is an India data region account.** It is a distinct signup for
      domestic inventory (contract §14). Record the account's Auth ID prefix (`MA_`) and
      its last four characters only. Read 2 Oct 2026: `MA_`, country IN; "India data
      region" not shown.
- [ ] **Inbound is enabled.** Trial numbers take no inbound calls (contract §11). No
      inbound switch was shown on 2 Oct 2026; record any that appears after the recharge.
- [ ] **One number is bought**, a standard Indian number. 140, 160 and 92 series are
      obtained by request to Vobiz support and are not needed for this test (contract
      §14). Outbound caller ID must be a number rented from Vobiz. Read 2 Oct 2026: one
      number ending 4620, Karnataka, mobile, TRIAL, Active, attached to no application.
- [ ] **No automatic recording** at account, number or application level (gate V-2).
      None was shown on 2 Oct 2026. Since D-668 we DO ask Vobiz to record calls to agents
      published while `CARRIER_RECORDING_ENABLED` is on (§8a); this check is now about
      recording we did NOT ask for.
- [ ] **The console timezone**, as shown (gate V-6). Read 2 Oct 2026: Asia/Kolkata.
- [ ] **Concurrency and CPS limits**, as shown on the account (gate V-5). Read
      2 Oct 2026: CPS 1, concurrent 3, none purchased. Vobiz refuses a 4th simultaneous
      call, inbound or outbound, so this sitting never has more than one call up at once.
- [ ] **The balance** covers a few minutes of calls. A dial with too little balance is
      refused with 402 (contract §2). The India rate card prices our calls at ₹0.44/min
      plus tax (contract §16); its billing pulse is UNKNOWN, so the first call's CDR and
      transaction row are the first real cost reading (gate V-7).

## 2. Our side: configuration

DEPLOYMENT §12.6 is the full table and the deploy order. For this sitting:

- [ ] **The callback secret is set FIRST, before any number is bound** (D-673). On your
      own machine run `openssl rand -hex 32` and put the output in the VPS `.env` as
      `VOBIZ_CALLBACK_SECRET` (never in a chat, ticket, gate row or the Pipecat secret
      set; it must differ from `CARRIER_CLAIM_SECRET` and `VOBIZ_AUTH_TOKEN`). Deploy
      api, workers and voice-runtime (`scripts/vps-deploy.sh api workers voice-runtime`)
      and confirm `/healthz/ready` on `:8000` and `:8100` does not name
      `VOBIZ_CALLBACK_SECRET`. Every URL we give Vobiz from then on ends
      `?callback_key=…`, and voice-runtime refuses a Vobiz request without it.
- [ ] VPS `.env` has `VOBIZ_AUTH_ID`, `VOBIZ_AUTH_TOKEN` and `CARRIER_CLAIM_SECRET`, and
      the Pipecat secret set has the same `CARRIER_CLAIM_SECRET`, `CARRIER=vobiz` and no
      Vobiz or Plivo credential.
- [ ] In the ops console: `CARRIER` is `vobiz`; `VOBIZ_SIGNATURE_REQUIRED` is **off**;
      `CARRIER_TRANSFER_ENABLED` is **off**; `CARRIER_CPS` is the account's CPS limit (1 on
      2 Oct 2026, which is the default); `CARRIER_CONCURRENCY` is the account's concurrent
      call limit (3 on 2 Oct 2026, the default) with `INBOUND_RESERVE_RATIO` at its default,
      so 1 line is kept for callers and 2 may dial out;
      `VOBIZ_CALLBACK_IPS` is unset (the published list is used);
      `CARRIER_RECORDING_ENABLED` is **on** (the default, D-668);
      `PIPECAT_STREAM_BASE_URL` is the REGIONAL endpoint,
      `wss://ap-south.api.pipecat.daily.co/ws/plivo?serviceHost=calevate-pipecat-worker.<ORG>`
      (`runbooks/first-deploy.md` §9a step 4). Without the `ap-south.` prefix the stream is
      sent to Pipecat's `us-west`, where no worker runs.
- [ ] The ops console's Vobiz credential probe is green. It calls `GET /api/v1/auth/me`
      (contract §1), which changes nothing at Vobiz.
- [ ] `bot.py --preflight` printed OK inside the deployed worker (DEPLOYMENT §12.5).
- [ ] One test agent is published, inbound and outbound, with its AI disclosure line and
      its recording notice switched ON — **published AFTER `CARRIER_RECORDING_ENABLED` was
      on**. An agent published before that is not recorded and does not announce it: its
      answer URL carries no `recorded` segment. Check it in the Vobiz console: the path of
      the agent's Application's answer URL ends `/recorded` (followed by
      `?callback_key=…`), and the binding was redone by the publish (§3).

## 2a. What the dial gate needs before the outbound call

"Call this lead" goes through the same compliance gate as every outbound call
(`compliance/service.check_dispatch`), and there is no test bypass (hard rule 5). The
console greys the button out and names the first rule that fails. For the test client and
agent, every one of these must be TRUE, not merely recorded; recording a registration that
does not exist is a false compliance record. In gate order:

- [ ] No outbound halt, no maintenance drain, and the test account is not stopped.
- [ ] The test agent is `live`, direction `outbound` or `both`, with an AI disclosure line
      on file, and no truthful-answer drift on its last check.
- [ ] KYC is verified for the test account (self-serve and trial plans only).
- [ ] The test account has accepted every blocking agreement at its current version (the
      same check refuses the publish in §2, so a published agent usually has).
- [ ] Credit balance above zero (prepaid) and no spend cap reached.
- [ ] The time is between 09:00 and 21:00 IST.
- [ ] The lead's number is `+91`, not on any DNC list, and its consent is not declined,
      withdrawn or expired (a recorded `callback` consent is required if the account is
      on a service/transactional footing).
- [ ] **Calevate's own DLT telemarketer registration is live** (`POST
      /v1/ops/platform/tm-registration`, rule `tm_registration_missing`).
- [ ] **The test client's DLT Principal Entity registration and TM link are active**
      (`POST /v1/admin/tenants/{tenant_id}/dlt-registration`).
- [ ] **The number from §3 is DLT `registered`** (`POST
      /v1/admin/tenants/{tenant_id}/numbers/{number_id}/dlt-status`), on provider `vobiz`,
      direction `both`; rules `number_not_registered`, `number_not_on_carrier`,
      `number_inbound_only`.
- [ ] **The client's auto-dialler notice (TCCCPR Regulation 4) is recorded, in effect, and
      declares that number** (`/v1/compliance/autodialer-notice`).
- [ ] A free outbound line: fewer than 2 calls holding a line on Vobiz (`carrier_lines_busy`).

The four bold items are regulatory facts outside this repository. If any of them is not
true yet, the outbound half of §5 waits for it; the inbound half does not need any of
them.

## 3. Bind the number to the agent

Before binding, **republish the test agent once after the D-674 deploy** (agent page →
Publish): its version was composed before the confidentiality rule existed, so the drift
screen reads `not_applied` ("published before that rule existed (D-674)") until it is, and
must read `applied` after.

From the admin console, on the test client's numbers page:

1. Record the number the founder bought, with the provider `vobiz`, direction `both` and
   its platform reference (`POST /v1/admin/tenants/{tenant_id}/numbers`). The direction
   defaults to `inbound`, and an inbound-only number is refused as the outbound caller ID
   (`number_inbound_only`), so the §5 outbound call would never leave. The reference is required:
   without one the bind in the next step is refused with `engine_number_not_linked`. Use
   the number's Vobiz `id`, a UUID on the number object
   (`account-phone-number/account-phone-number-object.md:15`); if the console does not
   show it, it is in the response of `GET /api/v1/Account/{auth_id}/numbers` (contract
   §11). The binding itself addresses the number by its E.164.
2. Choose the test agent for it (`POST /v1/admin/tenants/{tenant_id}/numbers/{number_id}/agent`).
   With `CARRIER=vobiz` this creates a Vobiz Application whose answer URL is the agent's
   `/carrier/v1/vobiz/answer/…` route and whose hangup URL is its events route, attaches
   the number to it, and stores the Application id on the number.

Then confirm in the Vobiz console, without editing anything: the Application exists, its
answer URL starts with our public hooks origin and `/carrier/v1/vobiz/answer/` and ends
`?callback_key=` followed by the secret (so does its hangup URL; an Application without it
was bound before the secret was set, so re-attach the agent here), the method
is POST, its **fallback answer URL** is our hooks origin plus `/carrier/v1/vobiz/fallback`
ending `?callback_key=` (D-675; an Application without one was bound before that release,
so re-attach the agent here), the number shows that Application, and Public URI is off ("Anyone can call this
application over SIP without authentication"; we never set it, and the API default is
false, `applications/create-application.md:45`). If the screen refused, record the refusal
code and stop: do not create or edit the Application by hand in the Vobiz console, because
our record and Vobiz's would then disagree about what answers the number.

## 3a. Prove a callback without the secret is refused (D-673)

A request from outside Vobiz's addresses is refused before the secret is looked at, so this
check briefly adds the VPS's own public address to the allowlist. It applies live; undo it
in step 4 whatever happens.

1. In the ops console set `VOBIZ_CALLBACK_IPS` to Vobiz's three published addresses
   (`calevate_shared.carrier.VOBIZ_CALLBACK_IPS`) plus the VPS's public IPv4, comma
   separated.
2. From the VPS, take the Application's answer URL from the Vobiz console and drop
   everything from `?` on (call it `URL`). Over IPv4, so the address Cloudflare reports is
   the one you added:

   ```sh
   curl -4 -sS -o /dev/null -w "%{http_code}\n" -X POST "URL"
   curl -4 -sS -o /dev/null -w "%{http_code}\n" -X POST "URL?callback_key=wrong"
   ```

   Both must print **404**, and voice-runtime must log `carrier_request_refused` with
   reason `callback secret missing`, then `callback secret invalid`.
3. POST once more with the real secret, read from `.env` inside the command so it never
   reaches shell history:

   ```sh
   sudo -u calevate bash -lc 'cd /var/www/calevate && set -a && . ./.env && set +a && curl -4 -sS -o /dev/null -w "%{http_code}\n" -X POST "URL?callback_key=$VOBIZ_CALLBACK_SECRET"'
   ```

   It must print **200** (an answer document; nothing dials).
   Then the same for the fallback URL (D-675), which is what Vobiz fetches when an answer
   fails: `URL` is now our hooks origin plus `/carrier/v1/vobiz/fallback`, and the command
   is the one above with `-w "%{http_code}\n"` replaced by `-w "\n%{http_code}\n"` and
   `-o /dev/null` removed. It must print the document
   `<Response><Hangup reason="busy" /></Response>` and **200**, and voice-runtime must log
   `carrier_answer_fallback_served` and raise the alarm of that name (a page; acknowledge
   it, it was you). Without the key it prints the same document and raises no alarm.
4. **Set `VOBIZ_CALLBACK_IPS` back to unset** in the ops console, and confirm a repeat of
   step 3 now prints 404 (`source ip not allowlisted`).
5. In `/var/log/nginx/access.log`, every request that carried a key shows
   `callback_key=[redacted]` and never the value. If the value appears there or in any
   `docker compose logs` output, stop and report it as a defect.

On the live calls in §5, voice-runtime's `carrier_answer_served` line must show
`auth_method` `callback_secret` (or `signature` once gate 55 passes). If every real Vobiz
request is instead refused with `callback secret missing` from a Vobiz address, Vobiz is
not returning the query string we registered: record it under gate 55 and stop. There is
no switch that turns the check off; the fix is a code change that moves the secret into
the path.

## 4. Signing (gate 55)

Vobiz signs callbacks only when "auth credentials" are configured on the callback URL, and
no page says how (contract §6). The 2 Oct 2026 reading found no such field on the
Applications create form and nothing on Security, Profile, Voice Overview or Subaccounts;
the console has no Developer or Webhooks menu.

The whole downloaded mirror was searched on 2 Oct 2026 and does not say either: no
callback URL with a username and password in it, no `Authorization` header on a callback,
and no credential field on the Application or on `<Stream>` (contract §6). Nothing was
built for it, so the steps below are about finding the setting, not about our code.

1. **Look in the console.** Read the pages not yet checked: **Endpoints, Push
   Notifications, Campaign Agents, the SIP Trunk create flow, Auto-Recharge**. Also open
   the edit form of the Application §3 created, which did not exist on 2 Oct 2026. Record
   the exact label and page. Do not save anything that changes the answer URL itself.
2. **If none shows it, ask Vobiz support in writing**, by email so the reply is dated,
   with this text:

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

   Record the reply and its date under gate 55. Do not paste any credential into the
   email. **If the reply says the credentials go in the URL and the signed URL includes
   them, stop here:** our verifier rebuilds the URL without them and would refuse every
   signed call. That is a code change, made on the reply.
3. **Enable it**, once the setting is found and the reply does not call for a code change,
   for the test Application only, then place one inbound call straight away. Once Vobiz
   sends a signature, voice-runtime refuses one that does not verify even with
   `VOBIZ_SIGNATURE_REQUIRED` off, so a wrong `WEBHOOK_BASE_URL` (scheme or host not
   exactly what Vobiz calls) shows up now as a refused call with reason
   `signature invalid`. If that happens, disable the console setting, correct
   `WEBHOOK_BASE_URL`, and try again. If every signature is still invalid with
   `WEBHOOK_BASE_URL` correct, disable the setting, record it under gate 55, and stop; the
   likely cause is that the signed URL is not the one we rebuild (contract §6).
4. **Record the outcome** of the answer request and the hangup callback, each as
   verified, absent or invalid, from voice-runtime's log. Never the header values.
5. Leave `VOBIZ_SIGNATURE_REQUIRED` off for now; §6 decides when to turn it on.

**Changing the callback credentials later** (once they exist): turn
`VOBIZ_SIGNATURE_REQUIRED` off in the ops console (it applies live), disable signing in
the Vobiz console, change the credentials, re-enable signing, place one inbound call, and
turn the flag back on only when that call shows a verified signature. With signing off for
that minute a call is admitted on the source-address check alone, which is safer than a
window in which every signed call is refused. The auth token, which is the
signing key, rotates by §10.

If no such setting exists, record "not shown" with the pages checked, and carry on: the
source-address check is still in force. It runs before the signature check whatever
`VOBIZ_SIGNATURE_REQUIRED` says, and refuses any address outside Vobiz's published list
(`apps/voice-runtime/carrier_routes.py::authenticate`).

## 5. The calls

**Inbound.** Only on a number that is no longer tagged TRIAL (§1): a trial number takes no
inbound calls (`faq/trial-inbound.md:9`), so a failed inbound call on one says nothing
about our side. From the founder's own mobile, call the bound number. Expect NO beep (we
send `playBeep="false"`, D-670): the agent speaks first, with the recording notice in its
opening (§8a), then:

- ask it a question it should answer from its knowledge;
- ask "am I talking to a bot?" — it must answer truthfully (hard rule 5);
- ask "is this call being recorded?" — it must answer yes (hard rule 5, D-668);
- press a keypad digit once (this produces a `dtmf` event, gate V-4), then `#` once, and
  note the time of each press for §8a step 6;
- hang up from the phone.

**Outbound.** From the client console, use "call this lead" on a test lead whose number is
the founder's own mobile and whose consent is recorded. It goes through the real dispatch
path, compliance gate included, so every item of §2a must hold first. Answer, speak a few
turns, and let the agent end the call if it will; otherwise hang up.

**One call at a time.** The account allows 3 simultaneous calls, shared by inbound and
outbound. Every dial counts the calls holding a line in both directions and keeps one line
for callers, so at most 2 of ours are ever out at once; a third is refused with "All lines
are busy" (`carrier_lines_busy`, gate V-5). Keep to one call at a time anyway, so each
reading in §6 belongs to one call. Do not start a campaign during this sitting.

**If a call fails to connect,** stop and read §6 before placing another. A 5xx or a
timeout on dial is never retried by our code, because Vobiz documents no idempotency key
and the phone may already be ringing (contract §2); placing it again by hand is a new call.

## 6. What to watch in the logs

No phone number, transcript text or header value appears in any of these logs by design
(hard rule 6). If one does, that is a defect: stop and report it.

| Where | What tells you it worked | Gate |
|---|---|---|
| voice-runtime | `carrier_answer_served` for the agent's tenant and agent ids, `auth_method` `callback_secret`; no `carrier_request_refused` for the call (a refused source address reads `source ip not allowlisted`) | V-1 |
| voice-runtime | the signature outcome in `auth_reason`: on `carrier_answer_served` for the answer request, on `carrier_event_admitted` for the hangup and `RecordStop` callbacks. `unsigned` is absent, `signature verified` is verified; a failing signature is refused as `signature invalid` | 55 |
| voice-runtime | `carrier_event_admitted` for the hangup (`event` `Hangup`, or `unknown` for an Application hangup, which carries no `Event`), then `carrier_event_acked` with `status` `accepted` (a Vobiz retry of the same callback reads `duplicate`) and its `ack_ms` | V-1 |
| voice-runtime | one call's lines share its `carrier_call_id` (Vobiz's `CallUUID`): `carrier_answer_served`, `carrier_event_admitted`, `carrier_event_acked`. Search by it to follow one call; `ack_ms` on the answer line is our server time, well under the 500 ms budget | — |
| voice-runtime | NO `carrier_answer_fallback_served`. One means the answer URL failed for that call and the caller heard a busy tone; read `runbooks/alarm-index.md` for it | — |
| Pipecat Cloud (`pipecat cloud agent logs calevate-pipecat-worker`) | `carrier session routed` with the test agent's `tenant_id` and `agent_id` (the path reached the worker), `direction` `inbound` with `call_claim` `absent`, or `outbound` with `call_claim` `verified` (`unverified` is a red: the claim key differs between the VPS and the worker); then `carrier leg opened` with `carrier` `vobiz` and, inbound, `caller_identity` `known` (the sealed caller claim opened) | V-3 |
| Pipecat Cloud | one line saying a `dtmf` event was ignored, and no other line about the keypad | V-4 |
| Pipecat Cloud | one `call timings` line per call, with `setup_ms`, `greeting_first_audio_ms`, `median_turn_ms` and `turns`: record the four numbers for each test call as the first live latency reading | — |
| Pipecat Cloud | NO `carrier session refused`. One names a reason class only (a malformed `start`, a media format other than 8 kHz μ-law, a missing credential); the caller heard the call end without the agent speaking. Record the reason and stop | V-3 |
| Pipecat Cloud | the stream ended with our `stop` (agent-ended call) or with the socket closing (caller hung up), and the session settled | — |
| workers | `ingest_carrier_event` moved the call to its final status, and the CDR reader ran | V-7 |
| voice-runtime | `carrier_answer_served` with `recorded: true` | V-11 |
| voice-runtime, then workers | a second callback on the events route (`Event=RecordStop`), handed to `ingest_carrier_event`, whose outcome ends `:copy_enqueued`; then `copy_carrier_recording` returned `copied` and logged `carrier_recording_copied` | V-11 |

**Turning on signature enforcement.** If both the answer request and the hangup callback
showed a verified signature, set `VOBIZ_SIGNATURE_REQUIRED` on in the ops console (it
applies live) and place one more inbound call. It must connect. If it does not, turn the
flag off at once and record what the log said. If only the status callbacks are signed and
the answer request is not, leave the flag off: it covers both routes.

## 7. Capturing the `dtmf` and `extra_headers` shapes (gate V-4)

The shipped serializer drops `dtmf` and logs nothing from the wire, and that stays true:
do not add wire logging to it, even temporarily. These shapes come from a primary source
instead, in this order:

1. **Ask Vobiz support in writing** for a sample `dtmf` event and a sample `start` event
   with a populated `extra_headers`, and record the reply with its date. This is the
   preferred route.
2. **A one-off capture**, only if support cannot answer: a separate Vobiz Application,
   on a separate test number, whose answer document streams to a throwaway WebSocket
   receiver you run for the purpose, never to the Pipecat worker. No such tool is in this
   repository. Record only the `start` frame and one `dtmf` frame, mask every phone number
   in them to its last four digits, delete the raw capture the same day, and delete the
   Application afterwards.

## 8. Reading the CDR

A CDR exists only after the call ends (contract §15). Read it in the Vobiz console's call
logs first. To read the raw record, from the VPS, without putting the token in shell
history:

```sh
read -r VOBIZ_ID; read -rs VOBIZ_TOKEN; read -r CALL_UUID
curl -sS -H "X-Auth-ID: $VOBIZ_ID" -H "X-Auth-Token: $VOBIZ_TOKEN" \
  "https://api.vobiz.ai/api/v1/Account/$VOBIZ_ID/cdr/$CALL_UUID" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin)["data"]; print({k: d.get(k) for k in ("uuid","duration","billsec","cost","total_cost","streaming_cost","currency","hangup_cause","hangup_source","region")})'
unset VOBIZ_TOKEN
```

The selection leaves out the two party-number fields of the CDR on purpose. The
`CALL_UUID` is the call's `CallUUID`, which our call row stores as its carrier call id;
pass the uuid, not the numeric id (`cdr/get-cdr.md:11-13`).

What to record:

- `billsec` (talk time) against the call's duration on our side. The client is billed
  on our measured duration; `billsec` is recorded beside it, and a large gap between the
  two is worth a note under gate V-7.
- `total_cost` and `currency`. Our ledger takes `total_cost` as our cost for the call only
  when `currency` is `INR`. Read the same CDR again after 24 hours: if any of `billsec`, `cost`,
  `total_cost` or `streaming_cost` changed, record it under gate V-7 before any client is
  billed.
- `hangup_cause` and `hangup_source`. An agent-ended call is expected to show
  `hangup_source` `Vobiz` and cause code 4010 after our `stop`
  (`xml/stream/stream-events.md:262-293`). A "violates media anchoring" hangup cause on either call fails
  gate V-8.
- `region`.
- Whether any cost field moved for the recording (₹0.10/min on the card, contract §16):
  the CDR documents no recording line, so record whether `total_cost` exceeds `cost` +
  `streaming_cost` by about that much (gate V-11(c)).

## 8a. Verifying the recording (gate V-11, D-668)

Do this for BOTH calls in §5, within the hour.

1. **It arrived.** In the admin console, or by a read-only SELECT on the audited path,
   the call row has `carrier_recording_id` set (minutes after the hangup) and then
   `recording_url` set to `recordings/<tenant>/<call>.wav`. No alarm named
   `carrier_recording_*` is on `/admin/ops/alerts`. If `carrier_recording_id` stays empty
   for 15 minutes, the `RecordStop` never came: read voice-runtime for a refused events
   request (`carrier_source_rejected`); the sweep looks the recording up by call id at
   :11/:31/:51.
2. **It was copied.** The object exists in the bucket under that key. Its content type is
   `audio/mpeg` or `audio/wav` according to its bytes, whatever the `.wav` in the key says.
3. **It plays in the dashboard.** Open the call in the client console and play it. Listen
   for the whole call: no beep, the agent's opening (the AI disclosure and the recording
   notice, both switched on for the test agent in §2), BOTH voices, to the hangup. Only the
   caller's voice is a red on V-11(a) — stop and report it before any client call. A
   recording that stops early (a `carrier_recording_ended_early` alarm, reason
   `FinishedOnKey`, after the keypad presses in §5) is V-11(b); see step 6.
4. **The opening was the two notices, spoken verbatim, then the greeting**, on the phone
   (§5) and as the first agent turn in the transcript. A new agent volunteers neither by
   default (D-669); if the test agent's switches were left off, the opening is the
   greeting only and the recording notice is not heard, which is the D-669 posture and not
   a defect. Either way, ask the agent "is this call recorded?" once: it must answer yes
   (hard rule 5).
5. **Vobiz's copy.** The Vobiz console's Recordings page lists the call, with its Storage
   Life. Record the Storage Life shown on day 0 (gate V-11(d), contract §9a). We delete
   Vobiz's copy one day after ours is stored (D-670): between 24 hours and 24 hours 20
   minutes after `recording_copied_at`, the call row's `carrier_recording_deleted_at` is
   set and the Recordings page no longer lists the call. If neither has happened by 48
   hours, `carrier_recording_delete_overdue` pages.
6. **A keypress did not stop the recording (gate V-11(b)).** Vobiz documents no way to
   switch `finishOnKey` off, so we narrowed it to `*` alone
   (`apps/voice-runtime/carrier_routes.RECORDING_FINISH_ON_KEY`). Play the recording past
   the digit and the `#` you pressed in §5: the audio must run on to the hangup, with no
   gap, and no `carrier_recording_ended_early` alarm may name the call. The call itself
   must have carried on after each press. Do NOT press `*` on these calls; whether `*`
   ends the recording is the vendor's documented behaviour (`xml/record.md:22,61`) and
   needs no test. A keypress reaches the worker's stream as a `dtmf` event, which the
   worker logs and ignores (`voice_worker/vobiz_serializer.py`); nothing here changes
   that. A red stops client calls until the founder decides (OPERATIONS gate V-11(b)).
7. **The recording API, as the way to drop the `*` stop (founder, 3 Oct 2026).** Vobiz's
   REST recording has no stop key (`call/record-calls/start-recording.md:28-36`), but no
   page says it captures the audio we stream back to the caller. Settle it on the second
   call in §5: while the call is in progress, start a REST recording from the VPS, then
   hang up as usual.

   ```bash
   sudo -u calevate bash -lc 'cd /var/www/calevate && set -a && . ./.env && set +a && curl -sS -X POST "https://api.vobiz.ai/api/v1/Account/$VOBIZ_AUTH_ID/Call/<CallUUID>/Record/" -H "X-Auth-ID: $VOBIZ_AUTH_ID" -H "X-Auth-Token: $VOBIZ_AUTH_TOKEN" -H "Content-Type: application/json" -d "{\"time_limit\":600,\"file_format\":\"wav\",\"record_channel_type\":\"stereo\"}"'
   ```

   `<CallUUID>` is the call's `carrier_call_id`. The answer carries a `recording_id`
   and `url` (`:75-89`). Open that recording in the Vobiz console and listen to each
   channel: the caller on one, the agent on the other, and note whether it beeped. Both
   voices present means the founder's choice applies: the build moves recording to the
   REST API and drops `<Record>`, and with it the `*` stop. Record the result under
   OPERATIONS gate V-11(b). This test recording is not copied by our pipeline; delete it
   in the Vobiz console afterwards.

## 9. Rollback

- **Stop new dials on Vobiz:** set `CARRIER` to `plivo` in the ops console. New dials and
  new bindings stop going to Vobiz at once. There is no Plivo account, so nothing is
  dialled at all; Plivo's side refuses by name.
- **Stop a number answering:** detach the agent from the number on the admin numbers
  page, which releases the binding at Vobiz. If that fails, detach the number from its
  Application in the Vobiz console and record that our record and Vobiz's now disagree
  until it is fixed.
- **A call that will not end:** hang it up in the Vobiz console's live calls view. The
  carrier enforces its own ceiling too: every dial carries a `time_limit`, and Vobiz's
  default is 4 hours (contract §7).
- **Signature enforcement refused a good call:** turn `VOBIZ_SIGNATURE_REQUIRED` off; it
  applies live.
- **Credentials leaked:** rotate the token as §10 describes, without waiting for a quiet
  moment.

## 10. Rotating `VOBIZ_AUTH_TOKEN`

The console's Security page has an "Auth Token Rotation" panel that says "The current
token stays valid for the grace window" (Vobiz console, founder-relayed, 2 Oct 2026,
VENDOR-PUBLISHED). The docs say the old token stops working at once
(`api-reference/authentication.md:54`). The length of the grace window is UNKNOWN, so
plan as if it were zero; if it turns out to be long, the steps below simply have slack.

The token lives only in the VPS `.env`, read by api, workers and voice-runtime. The
Pipecat worker holds no Vobiz credential and is not touched.

1. **Before rotating:** have the VPS shell open in the deploy checkout with `.env` ready to
   edit. Prefer a moment with no live call and no campaign running; a leaked token is the
   exception, rotate at once. Take each container's token fingerprint (12 hex characters
   of a SHA-256, never the token):

   ```sh
   for s in api workers voice-runtime; do
     docker compose -p calevate -f compose.prod.yml exec -T "$s" python -c \
       'import hashlib,os; print(hashlib.sha256(os.environ["VOBIZ_AUTH_TOKEN"].encode()).hexdigest()[:12])'
   done
   ```

2. **Rotate** in the console. Copy the new token straight into the VPS `.env` as
   `VOBIZ_AUTH_TOKEN`; never into a chat, ticket or shell history.
3. **Deploy the three services by name:** `scripts/vps-deploy.sh api workers
   voice-runtime`. Name them: with no code change, the default `--changed` mode deploys
   nothing. Until they restart, REST calls use the old token, which works only while the
   grace window lasts.
4. **Verify:** run the step 1 loop again. All three fingerprints must agree with each
   other and differ from step 1; a container still printing its old value did not pick up
   `.env` and must be redeployed. Then the ops console's Vobiz credential probe
   (`GET /api/v1/auth/me`) must be green. A green probe alone proves nothing during the
   grace window, because the old token still works. Record the rotation date; the
   console's "last rotated" should now show it.
5. **If callbacks are signed** (gate 55 passed): between step 2 and step 3 Vobiz may sign
   with the new token while voice-runtime still holds the old one, and a signature that
   does not verify is refused even with `VOBIZ_SIGNATURE_REQUIRED` off. Which token Vobiz
   signs with during the grace window is UNKNOWN. Keep steps 2 and 3 to a minute, and
   check voice-runtime's log for `signature invalid` refusals in that minute.

## 11. Rotating `VOBIZ_CALLBACK_SECRET` (D-673)

The secret is in the VPS `.env` only, read by api and workers (which write it onto every
URL they give Vobiz) and by voice-runtime (which checks it). Vobiz holds a copy on every
Application and on every call already dialled, so a rotation runs two secrets side by side
until both are re-registered. `VOBIZ_CALLBACK_SECRET_RETIRED` is accepted and never
written. Rotate at once if the secret leaked: anyone holding it, from a Vobiz account, can
point a number at our agents.

1. **Generate** the new value on your own machine with `openssl rand -hex 32`.
2. **Edit the VPS `.env`:** move the current value to `VOBIZ_CALLBACK_SECRET_RETIRED` and
   put the new one in `VOBIZ_CALLBACK_SECRET`. The deploy preflight refuses the two being
   equal (`retired_key_equals_active`).
3. **Deploy the three services by name:** `scripts/vps-deploy.sh api workers
   voice-runtime`. From here new dials carry the new secret and voice-runtime accepts both.
4. **Re-register every Vobiz Application.** Inbound URLs live on the Application, and
   nothing rewrites them on its own. For each agent that answers a Vobiz number, either
   republish the agent or, on the admin numbers page, choose the same agent for the number
   again (`POST /v1/admin/tenants/{tenant_id}/numbers/{number_id}/agent`). Both run
   `VobizCarrier.bind_number`, which updates that agent's Application in place
   (`applications/update-application.md:9-14`). Then check in the Vobiz console that each
   Application's answer, hangup and fallback answer URLs end with the new value (compare
   the last four characters). Do not edit the URL by hand in the Vobiz console.
5. **Wait out the old calls.** A call dialled before step 3 sends its hangup and
   `RecordStop` callbacks under the old secret. Our dials carry a `time_limit` of at most
   14,400 s (`engine/pipecat.CARRIER_TIME_LIMIT_CEILING_S`), and the recording callback
   follows the hangup, so keep the retired value for at least 24 hours after step 4.
6. **Remove `VOBIZ_CALLBACK_SECRET_RETIRED`** from `.env` and deploy voice-runtime
   (`scripts/vps-deploy.sh voice-runtime`). A request still carrying the old secret is now
   refused with `callback secret invalid` (alarm `carrier_source_rejected`, method
   `callback_secret`); one from a Vobiz address names an Application step 4 missed.
