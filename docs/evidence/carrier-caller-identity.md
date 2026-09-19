# Carrier caller identity — can the voice worker know who called?

**Date:** 19 September 2026
**Scope:** `apps/voice-worker/voice_worker/carrier.py`, the Pipecat/carrier handshake, and
the `calls.from_e164` NULL that breaks lead filing, caller memory and in-call opt-out.
**Short answer:** on **Plivo** the number is **not available to us today, and whether the
carrier sends it at all is UNKNOWN** — the vendor's documentation host is egress-blocked
from this container. On **Telnyx**, **Exotel** and **Twilio** the pinned client does hand
it over. The gap is in the **client's parse**, not provably on the carrier's wire, and
that distinction decides the fix.

Every claim below carries its evidence class. Repo-internal values are claims, not
evidence (hard rule 11).

---

## 1. The premise, verified (VERIFIED-VENDOR-DOCS)

Source: `pipecat-ai==1.10.0`, hash-pinned by `uv.lock`, installed at
`.venv/lib/python3.12/site-packages/pipecat/`. Read 19 Sep 2026.

`parse_telephony_websocket` builds a **per-carrier dict** and only then validates it onto
`CallData`, whose calling-party field is `from_number: str | None = Field(default=None,
alias="from")` (`runner/types.py:94`). A branch that writes no `"from"` key therefore
leaves the field at its `None` default **with nothing having been consulted**.

| Carrier | Writes a `"from"` key? | Line | What it reads |
|---|---|---|---|
| Twilio | yes | `runner/utils.py:240` | `start.customParameters["from_number"]` (:232) |
| Telnyx | yes | `runner/utils.py:253` | `start.from`, defaulting to `""` |
| **Plivo** | **no** | `runner/utils.py:257-262` | only `start.streamId`, `start.callId` |
| Exotel | yes | `runner/utils.py:270` | `start.from`, defaulting to `""` |

Verbatim, the whole Plivo branch (`runner/utils.py:257-262`):

```python
elif transport_type == "plivo":
    start_data = call_data_raw.get("start", {})
    call_data = {
        "stream_id": start_data.get("streamId"),
        "call_id": start_data.get("callId"),
    }
```

Two keys. No third.

**The asymmetry is real and it is the single most important fact in this task.** It is
driven rather than quoted by
`tests/carrier_identity_states_test.py::test_plivos_parse_names_no_calling_party_while_telnyx_and_exotel_do`,
which hands the parser a Plivo start message **that does contain `"from"`** and asserts
`call_data.from_number is None`. A dependency bump that changes this fails there.

Two consequences that are easy to get wrong:

1. **The raw start payload is not recoverable afterwards.** The parse caches only the
   `(transport_type, call_data)` tuple on the websocket (`runner/utils.py:291-294`), and
   `websocket.iter_text()` is single-use (`:174-176`). So a field Pipecat drops cannot be
   picked up later by us — reading it would mean **replacing** `parse_telephony_websocket`
   with our own reader, not supplementing it.
2. **Empty string ≠ missing key.** Telnyx and Exotel default `"from"` to `""`
   (`:253`, `:270`). On those carriers an empty value is the *carrier's own answer*
   ("nothing was sent"); on Plivo the field was never looked at. Different facts, so
   different states.

### The serializers keep nothing (VERIFIED-VENDOR-DOCS)

`serializers/plivo.py`, `telnyx.py`, `exotel.py` are all constructed **with** the ids
(`runner/utils.py:513-546`) and never see the `start` event: each `deserialize` handles
only `media` and `dtmf` (`plivo.py:224,245`; `telnyx.py:253,283`; `exotel.py:141,161`).
There is no second place in the wheel where a calling party could be hiding.

---

## 2. Is the number on the wire at all? — **UNKNOWN**

This is the question that separates "a small parse fix in our module" from "a handshake
design problem", and it **cannot be answered from this container**.

- **UNKNOWN — `www.plivo.com` is egress-blocked here.** Measured 19 Sep 2026:
  `curl -sS -o /dev/null -m 15 -w '%{http_code}'` returns **`000`** (connection failure,
  not an HTTP status) for `https://www.plivo.com/docs/voice/api/call/`,
  `https://api.plivo.com/` and `https://www.exotel.com/`. This matches the earlier
  measurement recorded in `docs/evidence/pre-build-blockers-2026-09-13.md` §10.
- **Therefore: no statement anywhere in this repository may say "Plivo does not send the
  caller's number."** `CALLER_IDENTITY_PARSE["plivo"].maps_calling_party is False` is a
  claim about **our client**, and its comment says so.

**What closes it:** §5's research prompt, run in a browser by the founder, or a single
inbound test call once an account exists (BLOCKER-1) with the raw `start` frame captured.

---

## 3. Could we fetch it from the carrier's REST API? — **NO, THIS PLATFORM CANNOT** (REPORTED, repo-internal, consistent across four independent places)

The founder's second suggestion was a pre-handshake identity fetch from the Plivo REST
API. **It is not buildable by us**, because of the product's commercial shape, not for a
technical reason:

- **D-474, Model B** (`docs/ROADMAP.md:716`): *"the client buys the connection on their own
  Exotel/Plivo/Vobiz account, passes that carrier's KYC, remains the subscriber of record
  and issues us revocable API credentials."* Calevate does not supply, sell, rent, allocate
  or port a phone number.
- `apps/api/agents/handoff.py:17-21` states it as an operational fact: *"We hold NO
  telephony credential: no Plivo or Exotel client, no auth id, no auth token, and
  `campaigns/provisioning.PROVISIONING_IMPLEMENTED` is False."*
- `apps/api/campaigns/provisioning.py:145` — `PROVISIONING_IMPLEMENTED: Final = False`,
  and D-474 records that the capability is **REFUSED, not unbuilt**; flipping it is
  adopting Model A, a legal decision.
- There is **no per-tenant carrier-credential store anywhere in the tree.** The only
  carrier secrets that exist are `plivo_auth_id` / `plivo_auth_token`, and they are
  deployment-wide values in the `calevate-pipecat-worker` secret set whose stated single
  purpose is **hanging the leg up** (`apps/api/core/settings.py:255-268`;
  `voice_worker/boot.py:132-144`). One shared pair cannot authenticate a REST lookup
  against **the client's own account**, which is the account an inbound call arrives on
  under Model B.

**Stated plainly, as asked:** a REST identity fetch is a design this platform cannot
build. It is not deferred and not hard — there is no key to perform it with, and acquiring
one means changing the commercial model. It should not appear in any plan.

*(Evidence class note: these are repo-internal statements, so REPORTED rather than
primary. They are mutually corroborating and one of them — the absence of a per-tenant
credential column — was checked directly. The underlying legal instrument is
`docs/legal/LEGAL-OPS-PLAYBOOK.md`, cited by D-474 and not re-read in this session.)*

---

## 4. Which carrier are we actually building for? (REPORTED)

- **D-05 picks Exotel** — `docs/ROADMAP.md:348`: *"Telephony | Vobiz/Exotel; inbound-priced
  favorably"*, reaffirmed in D-36's canonical M1 stack: *"Telephony: **Exotel** (140 via
  Vobiz / 160 via Plivo per their DLT runbook)"*.
- **Exotel is the carrier whose calling party Pipecat DOES parse** (`runner/utils.py:270`).
- `apps/api/compliance/kyc.py:38-42` (research summary, VENDOR-PUBLISHED via Exotel's own
  support pages, read by an earlier session): Exotel *"requires KYC plus a Customer
  Acquisition Form for VoIP accounts, requires the address proof to match the city the
  number is bought in, and **blocks outgoing calls until KYC is verified**."*

**This is why the seam is keyed on the carrier and not on Plivo.** Plivo signup failed, a
Telnyx ticket is open and unanswered, and the decided carrier is Exotel — which would
simply hand the number over. A Plivo-only design would be thrown away with Plivo, and,
worse, the carrier that *can* answer would arrive with nothing ready to receive the answer.

---

## 5. COMET RESEARCH PROMPT — the vendor question that is still open

Paste into Comet. The last question is the important one and is **not** in the founder's
original brief.

> Open these pages and answer only from what they say. Quote the exact wording and give
> the page URL and heading for each answer.
>
> 1. https://www.plivo.com/docs/voice/api/call/ — the XML/PHLO `<Stream>` element
>    reference (look under Voice → XML → Stream, and Voice → Getting started →
>    Audio streaming / WebSocket streaming).
> 2. Plivo's "Audio Streaming" / "Stream XML" page, whichever covers the JSON messages
>    Plivo sends over the WebSocket.
> 3. https://www.plivo.com/docs/voice/api/call/#answer-url — the parameters Plivo POSTs
>    to the answer URL.
>
> **Questions:**
>
> **(a)** In the JSON `start` event Plivo sends on a bidirectional `<Stream>` WebSocket,
> is the CALLER's phone number present? Give the **exact field name and its exact
> casing**, and say **where it sits** — top level, or nested under `start`, or under
> something else. Paste the documented example `start` message verbatim if one is shown.
> If no caller number appears in the documented `start` event, say **"not present in the
> documented start event"** rather than inferring.
>
> **(b)** Is that field present for **inbound** calls only, or for **outbound** calls too?
> Is it present when the caller has withheld their caller ID (CLIR)? What value appears
> then — absent, empty string, or a placeholder like `anonymous`?
>
> **(c)** **THE IMPORTANT ONE.** Does Plivo's `<Stream>` XML element support **custom /
> extra parameters or headers that WE supply in the answer XML** and that Plivo then
> echoes back inside the WebSocket `start` event? (Twilio has exactly this — TwiML
> `<Parameter name="..." value="..."/>` inside `<Stream>`, surfaced as
> `start.customParameters`.) If Plivo has an equivalent:
>   - what is the element or attribute called, with exact casing and an example;
>   - what key does it appear under in the `start` event JSON;
>   - are there length or character limits on the value?
>
> If Plivo has **no** such mechanism, say so explicitly.
>
> **(d)** Separately: which parameters does Plivo POST to the **answer URL** when a call
> arrives? Give the exact names of the caller-number and dialled-number parameters
> (casing matters) and confirm whether they are form-encoded POST fields or query
> parameters.
>
> **Answer format:** for each of (a)–(d), give `URL + heading + verbatim quote`, then a
> one-line plain answer. If a page does not say, write **"the documentation does not
> say"** — do not infer from another provider's behaviour.

**Why (c) is the one that matters:** if Plivo echoes custom stream parameters, we do not
need Plivo's own field at all. `apps/voice-runtime/carrier_routes.plivo_answer_document`
already builds the `<Stream>` element with an XML serializer, and the answer URL (question
d) already receives the caller number on the HTTP request — so we could attach it to the
stream ourselves at answer time. That is exactly the route Pipecat already supports for
Twilio (`runner/utils.py:232,240-241`), which means the receiving half is a known shape.

**Why (d) matters even if (c) fails:** the answer URL is the carrier's HTTP request into
`apps/voice-runtime`, a process we control. If the number is on that request, it can be
folded into the stream URL's route token — no carrier credential, no REST call, no vendor
cooperation beyond what the answer document already does. **That is the design to reach
for if (c) is negative**, and it needs question (d) answered first.

---

## 6. What was built in this session

`apps/voice-worker/voice_worker/carrier.py`:

- `CallerIdentity` — a state, a human-readable ground, and an optional `e164`. Four
  states, and the fourth is the whole defect:
  - `known`, `withheld_by_carrier`, `unparsed_by_client`, `not_read`.
  - `not_read` is the default and is the only state that may mean "nobody asked".
    Before this change all four were the same `None`.
- `CALLER_IDENTITY_PARSE` — per-carrier capability table, each row citing the pinned
  wheel by `file:line`, checked against the real parser by test.
- `caller_identity_of(transport_type, call_data)` — carrier-agnostic: reads the one field
  the client normalises across carriers, consults the table only to *explain* an absence.
  A new carrier needs a table row and nothing else.
- `PlivoHandshake.caller` — the handshake now carries the verdict.
- `start_carrier_call(..., caller=...)` logs `caller_identity` and
  `caller_identity_ground` at call start. Hard rule 6: the number is never logged; both
  logged strings are written in `carrier.py` and never built from wire data, asserted by
  `test_no_state_or_ground_can_carry_a_number` and
  `test_the_call_start_log_line_records_the_state_and_not_the_number`.

`normalize_phone` (`calevate_shared/extraction.py:176`) is reused rather than
re-implemented, because `dnc_list.phone_e164` is matched exactly by the dispatch gate — a
number stored in another form would be a suppression that suppresses nothing.

## 7. What is NOT done, and is out of this change's fence

1. **The identity does not yet reach the database.** The server half already exists:
   `calevate_shared/worker_api.py:145-166` declares `ObservationsIn.from_e164` /
   `to_e164` and says in terms that *"the producer is unbuilt and is a named gate"*
   (DEPLOYMENT §12.5 gate 9). The hop runs
   `carrier.start_carrier_call` → `session.start_session` → `pipeline.SessionConfig` →
   `sink` → `ObservationsIn`, through `session.py`, `pipeline.py` and `sink.py`.
   `pipeline.NormalizedEventBoundary._event` (`pipeline.py:374-383`) constructs every
   `CallEvent` and sets neither field.
2. **The in-call opt-out path** — see §8.
3. **A Plivo-specific reader** replacing `parse_telephony_websocket`, which is only worth
   writing if §5(a) comes back positive.

## 8. Hard rule 5: what the opt-out path must do when the number is unknown

The existing machinery is closer to correct than expected, and the remaining defect is
narrow and specific.

**What is already right** (VERIFIED — read in this session):

- `apps/workers/optout.py:114-124` — `record_in_call_optout` takes
  `subject = snapshot.from_e164 if inbound else snapshot.to_e164`; when it is empty it
  raises `WORKER_TERMINAL` alert `in_call_optout_unattributable` and returns
  `"unattributable"`. It does **not** invent a number.
- `apps/api/compliance/optout.py:413-422` — `record_call_optout` refuses a number it
  cannot normalise with `optout_phone_invalid`, on the stated ground that *"a row that
  looks like protection and blocks nothing is worse than no row."*
- `apps/api/worker/service.py:746-775` — `_alert_if_nobody_was_on_the_call` already
  raises an operator alert for a settled call with neither party known.

**The defect, precisely** (`apps/voice-runtime/tool_routes.py:181-239`, **out of fence**):
`_opt_out` acks the model with `{"status": "accepted"}` **unconditionally**, before
anything has established whether a number exists. The agent therefore tells the caller
"I've taken you off our list" on a call where the suppression will terminate as
`"unattributable"` minutes later. That is the silent success the brief names: the client's
screen and the caller both believe somebody was suppressed.

**The required change, specific enough to implement without re-deriving it:**

1. The tool must be able to answer **"I cannot key this suppression"** and the agent must
   say so. Add a third outcome beside the existing ack and the existing 422 — something
   like `{"status": "unattributable"}` — with a sentence the prompt tells the model to
   speak: an honest *"I'm not able to identify this number from my end; please tell me the
   number to remove, or I'll pass this to a person."* Never a bare success.
2. **It must be decided synchronously**, because the ARQ job's `"unattributable"` return
   arrives long after the caller has hung up. This needs the caller-identity verdict to be
   available at the voice-runtime tool endpoint, which means item §7.1 lands first — the
   worker must carry `CallerIdentity` into the session record the tool endpoint reads.
   Until then the tool cannot distinguish the cases and should not claim to.
3. **Keep the number out of the tool payload.** `apps/workers/optout.py:9-15` argues this
   correctly and it must not be weakened: the endpoint is unsigned and IP-allowlisted, so
   a payload-supplied number would let anyone inside that allowlist suppress an arbitrary
   number on an arbitrary tenant. If a caller *speaks* their number, it is a new signal
   with its own evidence rule and its own confirmation step — not a shortcut into this one.
4. **A caller-spoken number is the honest fallback for `unparsed_by_client` and
   `withheld_by_carrier` alike**, and it is the only fallback that exists. It is a
   different `consent_ledger` evidence rule from `engine_tool_call` because it is a
   different strength of evidence, and it must be read back to the caller for confirmation
   before it is suppressed.
5. **Do not raise `_alert_if_nobody_was_on_the_call` to `page`.** It fires on every call of
   this engine until gate 9 closes; `attention` is right (D-591).

## 9. Evidence classes, summarised

| Claim | Class | Source |
|---|---|---|
| Pipecat parses no calling party for Plivo; does for Telnyx/Exotel/Twilio | VERIFIED-VENDOR-DOCS | `pipecat-ai==1.10.0`, `runner/utils.py:230-272`, `runner/types.py:94`; pinned by `uv.lock`; read 19 Sep 2026 |
| The raw start payload is unrecoverable after the parse | VERIFIED-VENDOR-DOCS | `runner/utils.py:174-176`, `:291-294` |
| Serializers never see the `start` event | VERIFIED-VENDOR-DOCS | `serializers/{plivo,telnyx,exotel}.py` deserialize branches |
| Whether Plivo sends the caller number on `<Stream>` | **UNKNOWN** | `www.plivo.com` egress-blocked, `curl` → 000, 19 Sep 2026 |
| Whether Plivo supports custom stream parameters | **UNKNOWN** | same; §5(c) is the question that closes it |
| Model B — we hold no telephony credential | REPORTED (repo-internal, four corroborating places) | D-474 `docs/ROADMAP.md:716`; `agents/handoff.py:17-21`; `campaigns/provisioning.py:145`; absence of any per-tenant credential store |
| D-05 picks Exotel | REPORTED | `docs/ROADMAP.md:348`, D-36 canonical stack |
| Exotel blocks outgoing calls until KYC clears | VENDOR-PUBLISHED (relayed, not re-read here) | `apps/api/compliance/kyc.py:38-42`, citing Exotel support/docs |
