# Runbook — the first live call on Vobiz

**For:** the founder or an operator placing the first real phone call through the owned
runtime (D-592) on the Vobiz carrier (D-662), on the founder's own Vobiz account.

**What it proves.** No call has ever been placed on this product. This sitting closes the
gates only a live call can: OPERATIONS §2 gate 55 (signing) and V-1, V-2, V-3, V-4 and V-8,
and it takes the first readings for V-5, V-6 and V-7. Write each result into its gate row
with the date.

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

- [ ] **KYC is complete.** Only India-registered businesses may rent Indian numbers and
      use domestic routes, and KYC comes first (contract §14).
- [ ] **The account is an India data region account.** It is a distinct signup for
      domestic inventory (contract §14). Record the account's Auth ID prefix (`MA_`) and
      its last four characters only.
- [ ] **Inbound is enabled.** Trial accounts are outbound-only (contract §11).
- [ ] **One number is bought**, a standard Indian number. 140, 160 and 92 series are
      obtained by request to Vobiz support and are not needed for this test (contract
      §14). Outbound caller ID must be a number rented from Vobiz.
- [ ] **No automatic recording** at account, number or application level (gate V-2).
- [ ] **The console timezone**, as shown (gate V-6).
- [ ] **Concurrency and CPS limits**, as shown on the account (gate V-5).
- [ ] **The balance** covers a few minutes of calls. A dial with too little balance is
      refused with 402 (contract §2).

## 2. Our side: configuration

DEPLOYMENT §12.6 is the full table and the deploy order. For this sitting:

- [ ] VPS `.env` has `VOBIZ_AUTH_ID`, `VOBIZ_AUTH_TOKEN` and `CARRIER_CLAIM_SECRET`, and
      the Pipecat secret set has the same `CARRIER_CLAIM_SECRET`, `CARRIER=vobiz` and no
      Vobiz or Plivo credential.
- [ ] In the ops console: `CARRIER` is `vobiz`; `VOBIZ_SIGNATURE_REQUIRED` is **off**;
      `CARRIER_TRANSFER_ENABLED` is **off**; `CARRIER_CPS` is the account's CPS limit;
      `VOBIZ_CALLBACK_IPS` is unset (the published list is used).
- [ ] The ops console's Vobiz credential probe is green. It calls `GET /api/v1/auth/me`
      (contract §1), which changes nothing at Vobiz.
- [ ] `bot.py --preflight` printed OK inside the deployed worker (DEPLOYMENT §12.5).
- [ ] One test agent is published, inbound and outbound, with its AI disclosure line.

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
is POST, and the number shows that Application. If the screen refused, record the refusal
code and stop: do not create or edit the Application by hand in the Vobiz console, because
our record and Vobiz's would then disagree about what answers the number.

## 4. Signing (gate 55)

Vobiz signs callbacks only when "auth credentials" are configured on the callback URL, and
no page says how (contract §6).

1. Search the console for the setting: Applications (the edit form), Settings, Developer,
   API, Webhooks, Security. Record the exact label and page. Do not save anything that
   changes the answer URL itself.
2. If the setting exists, enable it for the test Application, then place one inbound
   call straight away. Once Vobiz sends a signature, voice-runtime refuses one that does
   not verify even with `VOBIZ_SIGNATURE_REQUIRED` off, so a wrong `WEBHOOK_BASE_URL`
   (scheme or host not exactly what Vobiz calls) shows up now as a refused call with
   reason `signature invalid`. If that happens, disable the console setting, correct
   `WEBHOOK_BASE_URL`, and try again.
3. Leave `VOBIZ_SIGNATURE_REQUIRED` off for now; §6 decides when to turn it on.

If no such setting exists, record "not shown" with the pages checked, and carry on: the
source-address check is still in force.

## 5. The calls

**Inbound.** From the founder's own mobile, call the bound number. Expect the agent to
speak first, then:

- ask it a question it should answer from its knowledge;
- ask "am I talking to a bot?" — it must answer truthfully (hard rule 5);
- press a keypad digit once (this produces a `dtmf` event, gate V-4);
- hang up from the phone.

**Outbound.** From the client console, use "call this lead" on a test lead whose number is
the founder's own mobile and whose consent is recorded. It goes through the real dispatch
path, compliance gate included. Answer, speak a few turns, and let the agent end the call
if it will; otherwise hang up.

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
- **Credentials leaked:** regenerate the token in the Vobiz console, which invalidates the
  old one at once (`api-reference/authentication.md:54`), put the new one in the VPS
  `.env`, and restart api, workers and voice-runtime together. The token is also the
  callback signing key, so until voice-runtime restarts every signed callback fails.
