# Runbook — the first live call on Vobiz

**For:** the founder or an operator placing the first real phone call through the owned
runtime (D-592) on the Vobiz carrier (D-662), on the founder's own Vobiz account.

**What it proves.** No call has ever been placed on this product. This sitting closes the
gates only a live call can: OPERATIONS §2 gate 55 (signing) and V-1, V-2, V-3, V-4 and V-8,
and it takes the first call readings for V-6 and V-7 (V-5's limits were read in the
console on 2 Oct 2026). Write each result into its gate row with the date. §10 is the
token rotation procedure, which is not part of the sitting.

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

- [ ] VPS `.env` has `VOBIZ_AUTH_ID`, `VOBIZ_AUTH_TOKEN` and `CARRIER_CLAIM_SECRET`, and
      the Pipecat secret set has the same `CARRIER_CLAIM_SECRET`, `CARRIER=vobiz` and no
      Vobiz or Plivo credential.
- [ ] In the ops console: `CARRIER` is `vobiz`; `VOBIZ_SIGNATURE_REQUIRED` is **off**;
      `CARRIER_TRANSFER_ENABLED` is **off**; `CARRIER_CPS` is the account's CPS limit (1 on
      2 Oct 2026, which is the default);
      `VOBIZ_CALLBACK_IPS` is unset (the published list is used);
      `CARRIER_RECORDING_ENABLED` is **on** (the default, D-668).
- [ ] The ops console's Vobiz credential probe is green. It calls `GET /api/v1/auth/me`
      (contract §1), which changes nothing at Vobiz.
- [ ] `bot.py --preflight` printed OK inside the deployed worker (DEPLOYMENT §12.5).
- [ ] One test agent is published, inbound and outbound, with its AI disclosure line and
      its recording notice switched ON — **published AFTER `CARRIER_RECORDING_ENABLED` was
      on**. An agent published before that is not recorded and does not announce it: its
      answer URL carries no `recorded` segment. Check it in the Vobiz console: the agent's
      Application's answer URL ends `/recorded`, and the binding was redone by the publish
      (§3).

## 3. Bind the number to the agent

From the admin console, on the test client's numbers page:

1. Record the number the founder bought, with the provider `vobiz` and its platform
   reference (`POST /v1/admin/tenants/{tenant_id}/numbers`). The reference is required:
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
answer URL starts with our public hooks origin and `/carrier/v1/vobiz/answer/`, the method
is POST, the number shows that Application, and Public URI is off ("Anyone can call this
application over SIP without authentication"; we never set it, and the API default is
false, `applications/create-application.md:45`). If the screen refused, record the refusal
code and stop: do not create or edit the Application by hand in the Vobiz console, because
our record and Vobiz's would then disagree about what answers the number.

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
path, compliance gate included. Answer, speak a few turns, and let the agent end the call
if it will; otherwise hang up.

**One call at a time.** The account allows 3 simultaneous calls, shared by inbound and
outbound, and our campaign dispatcher does not cap itself at 3 (gate V-5). The founder has
decided that is enough for testing; the cap is required before client traffic, not now. Do
not start a campaign during this sitting.

**If a call fails to connect,** stop and read §6 before placing another. A 5xx or a
timeout on dial is never retried by our code, because Vobiz documents no idempotency key
and the phone may already be ringing (contract §2); placing it again by hand is a new call.

## 6. What to watch in the logs

No phone number, transcript text or header value appears in any of these logs by design
(hard rule 6). If one does, that is a defect: stop and report it.

| Where | What tells you it worked | Gate |
|---|---|---|
| voice-runtime | the answer request for the agent's ref was accepted, with its source address inside Vobiz's published list, and an answer document was served | V-1 |
| voice-runtime | the signature outcome on the answer request and on the hangup callback: present and verified, absent, or present and failing | 55 |
| voice-runtime | the hangup callback was accepted and handed to `ingest_carrier_event` | V-1 |
| Pipecat Cloud (`pipecat cloud agent logs calevate-pipecat-worker`) | the session started for the right agent ref, the carrier claimed on the stream URL was `vobiz`, the caller claim verified (inbound) or the call claim verified (outbound) | V-3 |
| Pipecat Cloud | one line saying a `dtmf` event was ignored, and no other line about the keypad | V-4 |
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
   for the whole call: no beep, the agent's greeting (agents volunteer no notice by default,
   D-669), BOTH voices, to the hangup. Only the caller's voice is a red on V-11(a) — stop and report it
   before any client call. A recording that stops early (a `carrier_recording_ended_early`
   alarm, reason `FinishedOnKey`, after the keypad presses in §5) is V-11(b); see step 6.
4. **The opening was the greeting only** on the phone (§5) and in the transcript, unless
   the test agent's notice switches were turned on. Ask the agent "is this call
   recorded?" once: it must answer yes (hard rule 5).
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
