# First live call review — 10 Oct 2026

Two outbound test calls from the trial account Raghava Organics (agent "Raghava Organics
receptionist", ENGINE=thinnest, Premium voice band) to the founder's own number, at 17:46 IST
(0:47) and 17:52 IST (1:04). Both connected, the agent spoke Telugu, took turns, booked a call
back and hung up. The pipeline works end to end. This file lists everything the founder and the
review found wrong, so none of it is lost. Status: OPEN unless marked.

Source: the founder's report and screenshots (call detail, call list, call-backs page, leads
table), and the transcript of the 17:52 call:

```
1  Agent   Namaskaram, idi Raghava Organics AI assistant.
2  Caller  ఓకే, ఎందుకు కాల్ చేశారు?
3  Agent   మీకు Raghava Organics products గురించి ఏమైనా కావాలా అని తెలుసుకోవడానికి call చేశాను. మీకు ఏ product ఆసక్తి ఉంది?
4  Caller  ఆ మీ దగ్గర చిల్లీ ఉందా అండి?
5  Agent   ఒక నిమిషం, చూస్తాను అండి. క్షమించండి అండి, ఇప్పుడు ఒక వ్యక్తికి connect చేయలేకపోతున్నాను. మీకు chilli గురించి వివరాలు తెలుసుకోవాలంటే, మా team నుంచి మీకు call back చేయించమంటారా?
6  Caller  ఆ కాల్ బ్యాక్ చేయండి అండి
7  Agent   సరే అండి. ఏ రోజు, ఏ time కి call back రావాలి?
8  Caller  ఈరోజే ఇంకొక పది నిమిషాల్లో చేపించండి.
9  Agent   అర్థమైంది అండి, ఈరోజు సాయంత్రం ఆరు గంటల మూడు నిమిషాలకి call back అనుకుంటాను. సరేనా?
10 Caller  అంతే అండి.
11 Agent   సరే అండి, ఈరోజు సాయంత్రం ఆరు గంటల మూడు నిమిషాలకి call back book అయింది. ధన్యవాదాలు అండి!
12 Caller  Okay andi, Okay sir.
13 Agent   ధన్యవాదాలు అండి, మళ్ళీ మాట్లాడతాము.
```

## F-1 Voice sounds robotic
The Premium band voice (ThinnestAI's own, ₹2.50/min) sounds synthetic. The founder accepts this
as the band's quality. Options to evaluate: the Studio band (₹3.00/min, needs ThinnestAI Pro),
the Studio rung on our Cartesia key through BYOK voice scope (₹1.50/min + Cartesia), and which
catalogue voices are best for Telugu and Hindi. Needs listening tests, not reading.

## F-2 The in-call language model writes textbook Telugu
The default in-call model (ThinnestAI catalogue, "Prana [Voice]") produces formal, written-style
Telugu. Wanted: regional, spoken Telugu (Telangana/Andhra register, natural code-mixing with
English words people actually use), the same for Hindi and every other language. A stronger model
may also call tools more reliably; the cost is price per minute and possibly latency. Also part of
this: the prompt itself (style instructions, few-shot spoken examples) — the model is only half of
it. Observed in the transcript:
- Line 3 opens with a generic "do you want any products" instead of the script's purpose.
- Line 5: asked "do you have chilli?", the agent did NOT look in the knowledge base or product
  list; it tried to reach a person ("can't connect you to a person right now") and offered a call
  back. Either the knowledge base has no product facts, the search tool was not used, or the
  handoff action fired first. Must be traced.
- Line 1: the AI notice ("Namaskaram, idi … AI assistant.") was spoken; the script's opening line
  was not. Fixed in the uncommitted D-708 work (greeting = notices + opening line).

## F-3 Transcript screen is poor
Call detail page: the transcript is a long list of "Agent / Caller" labels with icons, hard to
scan; the summary is the last utterance; the right column (Follow up, Recording, Ask the assistant)
does not read as one story. Redesign with the design skills, the illustrated mockups in the
marketing site, and current call-review UIs as reference. The summary must be generated
automatically after the call ends (today there is a manual "Re-summarise with AI").

## F-4 Wrong conclusion: a call-back request was marked "Resolved"
The caller asked for a call back and the agent booked one, yet the call's outcome is "Resolved"
and Follow up says "This call was marked resolved, so no follow-up is due". A call that ends
with a booked call back is not resolved; the outcome classification and the follow-up panel must
read the booked call back. Sentiment "neutral" should also be checked.

## F-5 The booked call back was never placed
The call-backs page shows it "Waiting" at 18:03 with "During your free trial, calls go out only
as test calls from your dashboard. Calling your leads opens once you add credit and verify your
business." This is the trial rule (D-697) working as written — but the agent PROMISED the caller a
call back it could not make. Either the trial must allow call backs to the number that was just
test-called, or the agent must not offer a call back it cannot keep during a trial. Founder
decision.

## F-6 Call list shows the last words instead of a summary
Call logs list and the call header show "agent: ధన్యవాదాలు అండి, మళ్ళీ మాట్లాడతాము." — the last
line spoken. Show a one-line summary of the call instead (generated after the call).

## F-7 Leads page needs proper work, front end and back end
Observed: the lead is "No name", Status "New", Owner "Unassigned", Source "campaign" (it was a
dashboard test call, not a campaign), and the columns are "Symptom / reason" and "Preferred
doctor" — a clinic template on an organic-produce business. The extraction schema did not
capture what the caller wanted (chilli) or the call back. Review: the extraction schema per
business type, what fields are filled from a call, source labels, the repeat badge, status
movement after a call, and the table layout (horizontal scroll).

## F-8 The script system is not built for best performance
The founder's view: the agent performs as well as its script, and the current script builder,
compile and backend logic are not built to produce the best-performing prompt. Review what the
builder captures (goal, persona, tone and register, knowledge, objections, call-back and handoff
policy, language style), how it compiles into the engine prompt, and what the best published
practice for voice-agent prompts is.

## Already fixed in uncommitted work (not yet deployed)
- Greeting carries notices + the script's opening line (D-708).
- Opening line mismatch between the script summary and builder.
- Usage and cost visible on admin Overview and Spend.
- IST everywhere (D-709).

## Root causes found (research, 10 Oct 2026; production facts still to confirm)

- **F-4, F-6 (and part of F-7): the offline extractor ran, not Sarvam.** The stored summary is
  the last transcript line with its speaker prefix, which only `OfflineExtractor` writes
  (`apps/workers/extraction.py` ~1125). It marks a call `resolved` unless the caller's text
  holds an English-letter "callback" phrase, so Telugu-script "కాల్ బ్యాక్" did not count.
  `get_extractor()` falls back to it when `sarvam_api_key` is unset. UNVERIFIED on production:
  `call_extractions.model` is always written NULL (`pipeline.py` ~1952), so the row cannot say.
  Also: `callback_requested` is computed and discarded (`pipeline.py` ~1846); the booked
  `scheduled_callbacks.source_call_id` is never read by the outcome or the Follow up panel;
  an unknown outcome defaults to `resolved`; the extraction prompt never defines the tags.
- **F-5:** `book_callback_for` books on trial agents, then `dispatch_due_callbacks` calls
  `check_dispatch` without `trial_call=True`, the trial rule refuses it, the refusal is not a
  person-level one, so the call back is deferred until it expires (2 h).
- **F-6:** a real summary already exists in the pipeline; on this call it was the offline
  fallback. ThinnestAI's own `summariseCalls` summary is switched off by our adapter.
- **F-7:** the schema is fixed at account creation from the vertical template; the operator
  create API defaults to `clinic`; there is no retail/food vertical; lead source is
  `campaign` for every outbound call (`pipeline.py` ~2263); test calls count as repeats; no
  status moves after a call; call backs are not linked to leads.
- **F-2 line 5:** the model called our `connect_to_staff_member` action (registered when no
  hand-over destination is on duty), which answers with the "cannot connect, offer a call
  back" sentence. The prompt says "offer a call back" in 5-6 places, never names
  `search_knowledge`, and the FAQ is an "answer ONLY from these" fence. If the trial account
  had no knowledge, the agent had no search tool at all. UNVERIFIED which tool fired.
- **F-2 register:** one line ("never force formal Telugu") is not enough; best practice is
  short spoken-register example exchanges. On ThinnestAI the per-minute price is set by the
  voice band, so a stronger catalogue model is probably ₹0 extra (UNKNOWN until `GET /models`
  and one call's `costMicro`). The Cartesia Studio rung restricts the model to Prana, GPT-OSS
  120B or nano models.
- **F-8:** the script has no identity or goal section, no conversation stages with exit
  conditions, no objections, no policies tied to what the account can actually do, duplicate
  and conflicting platform rules, no sample phrases, and no behaviour test before Switch on
  (ThinnestAI's Test Chat can run one).

## Founder decisions (10 Oct 2026)

1. **Trial call backs:** the agent never offers one during a trial; the call-back tool
   refuses on a trial account and tells the agent to say the business will follow up.
2. **In-call model:** switch the default (Clear) from Prana [Voice] to GPT-5 mini now.
3. **Script style:** instructions in English plus short spoken example exchanges in the
   call's language (natural code-mixing); AI drafts the examples per language, region and
   business type, the founder or a native speaker reviews them.
4. **Summary:** English, with a toggle to read it in the call's language (Telugu etc.).
5. **Transcript translation:** a "Show English" toggle under each turn; the original stays
   the record.
6. **Outcomes:** replace "Resolved" with Call back booked, Needs you, Answered, Transferred,
   Hung up early, Missed; derived from facts (a booked call back always reads as one).
7. **Test calls create leads**, labelled "Test call", never counted as a repeat caller.
8. **Lead status moves by rules** after a call (never backwards, never over a person's choice).
9. **No hand-over tool when nobody is on duty**; "I don't know" goes to knowledge search.
10. **New business types:** retail/shop/food & produce, salons & local services, automobile
    & repairs.
11. **Pre-launch test conversations:** advised, not required.
12. **Summary source:** ThinnestAI's built-in per-call summary (`summariseCalls`).
13. **Fonts:** bundle Noto Sans Telugu and Noto Sans Devanagari.
14. **Voice:** test the Premium Telugu voices by ear first; no plan change yet.
15. **Lead fields are not clinic-centric.** A hard-coded neutral core every business gets,
    plus fields about that business: the vertical's set for a known type, and for a custom
    business a set generated ONCE by AI from everything known about the business, never
    regenerated, always editable by the client, with a proper UI. Nothing defaults to clinic.

## Studio voice on pay-as-you-go (10 Oct 2026)
ThinnestAI's voice list returns Studio voices only on Pro and above
(`api-reference/voices/list-voices.md:7`); the "one Studio voice previews free" is a sample
in their console, not a voice an agent can use. Our sync drops nothing. Setting the Clear
band to Studio is now refused when the last refresh listed no Studio voice; admin copy
separates ThinnestAI's Studio tier from our Cartesia "Studio voices" switch.

## Correction: in-call model is GPT-OSS 120B, not GPT-5 mini (10 Oct 2026)
Decision 2 above is superseded. ThinnestAI's agent model dropdown (founder screenshot, 10 Oct
2026, VENDOR-PUBLISHED via founder) tags GPT-5 Mini "premium ₹2.50/min voice calls" at about
823 ms, so a model can move the minute's price band. Listed response times: Prana ~154 ms,
GPT-OSS 120B ~221 ms, Prana [Voice] ~560 ms (old default), GPT-4.1 Nano ~578 ms, GPT-5.4 Nano
~734 ms, GPT-5 Nano ~915 ms, GPT-5.6 Luna ~1072 ms. Decision: GPT-OSS 120B is the in-call
model (a console setting labelled in-call); Calevate's platform default for non-call AI stays
gemini-2.5-flash-lite. The main goal is natural, local, spoken Telugu (and Hindi etc.), not
textbook language; it is delivered mainly through the prompt (English rules, spoken-register
examples, a formal-to-spoken word list) and judged by an ear test.

## ThinnestAI voice settings to build on our side (founder, 10 Oct 2026)

The founder pasted ThinnestAI's agent Voice settings page and asked that every one of these be
configurable in Calevate, wired to ThinnestAI's API and kept in sync, for better agent
performance. Settings seen on that page (wording paraphrased from their console):

1. **Own keys (BYOK) switch per agent** — off: runs on ThinnestAI voices/models at their pricing.
2. **Unavailable message** — "Sorry, this number is not taking calls right now…" (said when paused).
3. **Caller lookup URL** — optional https endpoint called when someone rings, with number (and
   name, email, id if known); waits up to 2 s; answer `{ "variables": {...} }` usable as
   `{{name}}`; no answer → call goes ahead without them.
4. **Where it answers** — phone number, website call button, WhatsApp calls (each on/off).
5. **How it should speak** — call-only instructions box (one or two sentences, spoken style,
   no symbols, titles in full, never state facts it was not given, one question per turn…).
6. **Filler lines while thinking** — up to 8, one per line, per language, under 60 chars;
   default fillers if blank; **filler delay** (ms of quiet before speaking, default 900,
   200–5000); **filler gap** (ms between fillers / tool wait, default 2500, 1000–10000);
   an option that removes the wait entirely (always fill; best on slow models).
7. **Turn-taking** — end-of-turn silence (default 0.25 s, 0.2–3 s); **words needed to
   interrupt** the agent (default 3, 1–6); **never interruptible** switch (for disclosures,
   compliance readouts, price quotes); **keep words spoken over the agent** and answer them;
   **let the greeting finish** (phone lines).
8. **Background ambience** — a room sound behind the agent, off by default.
9. **Call recording** — on/off; web callers see a notice; recordings deleted after 30 days;
   telling callers is the business's responsibility.
10. **Answering-machine detection** on outbound — hang up on a machine.
11. **Ring timeout** on outbound — 10–60 s, default 30.
12. **Hang up when finished** — release the line when the agent is done (otherwise billed until
    the caller hangs up).
13. **Earlier conversations (caller memory)** — use past calls/WhatsApp/web with the same person.
14. **Call summary** — two or three sentences after the call (decision 12 uses this).
15. **Call length and silence** — max call length (e.g. 10 min), "are you still there?" after N
    seconds (or never), hang up after a silence (e.g. five minutes), and goodbye phrases that
    end the call ("bye, that's all, thank you goodbye").

Status: mapping each to the API field, our current handling and the right owner (client,
admin or fixed by the platform) before the founder's questions; then build and sync.

## Post-call API (lane 1)

Built 10 Oct 2026 for founder decisions 1, 4-8, 12 and F-4..F-7. Migration `c4e8a1f7d290`
(reversible; follows `b4e8d2a61c90`). Read with `GET /v1/calls`, `GET /v1/calls/{id}`,
`GET /v1/leads`, `GET /v1/leads/{id}`. Types are in `apps/web/src/lib/api/schema.d.ts`.

**Outcome** (`CallSummaryOut.outcome_tag`, also `?outcome=` on the list and CSV export):
`call_back_booked | needs_you | answered | transferred | hung_up_early | missed`, or `null`
(not decided yet, or nothing could be told). Derived after the call by
`apps/api/crm/outcomes.derive_outcome`, in this order: never connected -> `missed`; a call
back booked on the call -> `call_back_booked` (always); hand-over reached a person ->
`transferred`; hand-over tried and failed -> `needs_you`; connected, under 20 s, caller spoke
at most once -> `hung_up_early`; caller asked for a person or a call back nobody booked, or
asked something the agent could not handle -> `needs_you`; otherwise the model's reading
(`answered`, ...). Labels are the screen's job. Old stored words are mapped on read.

**Call list row** (`CallSummaryOut`) adds:
- `headline`: one line, English, at most 90 characters, redacted. Show it instead of the last
  utterance (F-6). `null` when none.
- `summary`: the English summary (redacted). `summary_state`: `pending` (still writing),
  `ready`, `failed` (could not be written), `empty` (nothing to summarise). Show "writing..."
  only for `pending`.
- `callback`: `{id, due_at, status, blocked_reason, blocked_rule}` for the call back booked
  on this call, or `null`. `status` is the `scheduled_callbacks` status (`scheduled`,
  `dialing`, `completed`, `cancelled`, `refused`, `missed`, `failed`); `blocked_reason` is
  the sentence to show when it was stopped (a trial account reads "Call backs are not placed
  during your free trial..."). `due_at` is an instant; show it in IST.
- `test_call`: a free-trial test call.

**Call detail** (`CallDetailOut`) adds, beyond the list fields:
- `summary_local` + `summary_language` (BCP-47, e.g. `te-IN`): the same summary in the call's
  language for the "show in Telugu" toggle; `null` for an English call or when none.
- `summary_source`: `engine` (ThinnestAI's own summary, `summariseCalls` now on) or
  `extraction` (our Sarvam pass). The engine's summary wins when it is in Latin script; an
  engine summary in Telugu/Devanagari becomes `summary_local` and the English one comes from
  our pass (or is translated from it).
- `next_step`: what the business should do next, English, redacted, or `null`.
- `callback_requested`: the caller asked for a call back (booked or not).
- `transcript[].text_en`: the turn in English for the "Show English" toggle (translated after
  the call from the redacted text; the original `text` stays the record). `null` when the
  turn was already English. `translation_state`: `pending | ready | failed | not_needed |
  unavailable` (`unavailable` = a call from before translation existed).
- `extraction_model`: which runner read the call (the Sarvam model id, or `offline-heuristic`); `null` before 10 Oct 2026.

**Follow up panel** (`GET /v1/calls/{id}/callback`) now reads the booked call back first:
`rule = callback_already_booked` ("A call back is already booked for 10 Oct at 18:03 (IST)")
or `callback_already_placed`; when the booked one was refused/missed/failed, a follow-up is
offered again. `callback_not_needed` sentences name the outcome in plain words.

**Lead** (`LeadOut`) adds `source` as a fixed enum (`inbound_call | webhook | campaign |
manual | test_call | outbound_call`), `status_set_by` (`system | person`),
`last_call_headline`, `last_call_outcome`, `next_step`, `next_callback_at` (soonest live call
back). Rules after each call: a connected call moves `new` -> `contacted`; a booked or
requested call back, or a keen caller, moves up to `interested`; the hot-lead rule may move
up to `hot`. Never backwards, never over a status a person set (any status change through the
screens, bulk or the assistant sets `status_set_by = person`). Test calls create leads with
`source = test_call` and never make a repeat caller; a later real call gives the lead its real
source. Call backs booked on a call are linked to its lead.

**Trial** (decision 1): the call-back tool (`book_callback_for`, both engines) answers
`not_booked`, reason `trial_call_back_unavailable`, telling the agent to say the business will
follow up; the dispatcher ends any trial-blocked call back at once as `refused` with that
sentence instead of "Waiting" for two hours. Not done here: dropping the
`arrange_return_call` action from trial agents at publish (owned by the prompt/tools lane,
`reliability/engine_actions.py`); the tool refuses either way.

**Decision (founder, 10 Oct 2026): the caller lookup URL is Calevate's own endpoint, not a
client-supplied one.** Callers and numbers live in our database, so we set ThinnestAI's lookup
URL at publish to a per-agent Calevate endpoint (authenticated like the in-call actions) that
answers within ThinnestAI's 2-second budget with variables from our CRM for that tenant (name,
last call headline, next step, language, open call back, products of interest), with a safe
empty answer on any miss. Caller data therefore never goes to a third-party URL.

### Mapping result (10 Oct 2026, mirror 2026-10-08 + live docs.thinnest.ai read 10 Oct)
The live docs moved past the mirror: `voice.ringSeconds` (10-60, default 30) and
`voice.callStartUrl` + `callStartSecret` exist live only (re-snapshot the mirror before citing
lines). The API's `voice` object holds only: answersCalls, voice, language, summariseCalls,
detectMachines, recordCalls, maxCallSeconds (60-1200), pastConversations (fresh/quiet/recap),
unavailableMessage (≤300; spoken only on Plivo/Twilio numbers), ringSeconds, callStartUrl,
surfaces (read-only); plus top-level `byok`. **Console-only, no API field:** fillers and their
timings, words-to-interrupt, end-of-turn silence, never-interruptible, keep-words, let the
greeting finish, ambience, hang up when finished, "are you still there?", end after silence,
end phrases, the call-only "how it should speak" box, and the web/WhatsApp surface ticks.
These cannot be set or drift-checked from Calevate until ThinnestAI adds fields.

Caller lookup contract (live update-agent and channels/voice): POST `{event:"call.started",
callId, surface, agentId, from, to, direction:"inbound", contact|null, sentAt}`, signed like a
webhook (`x-thinnest-signature-v2`, HMAC over `<delivered-at>.<body>`); answer in 2 s with
`{"variables":{...}}` (≤20 values, ≤150 chars, scalars). ThinnestAI mints the secret and returns
it once on the PATCH that sets the URL (`callStartSecret: "rotate"` to re-mint), so we seal it
on the agent route and verify with our existing v2 verifier. Inbound phone and WhatsApp only.

Doc drift: THINNEST-INTEGRATION says summariseCalls false (code sends true) and that no
pre-answer hook exists (callStartUrl now does).

## Script API (lane 2)

Backend contract for the script builder and agent page (D-714). Lane 4a builds the UI
against this; lane 2 owns the backend, OpenAPI and the generated web types. All routes are
client realm under `/v1/agents/{agent_id}/script`; reads need `agents:read`, writes
`org:manage`. Status: **BUILT** unless marked otherwise.

### The script model (`calevate_shared.call_script.CallScript`, `schema_version: 2`)

One saved model behind both the desktop canvas and the phone list.

| Field | Type / limit | Notes |
|---|---|---|
| `schema_version` | `1 \| 2` | Always send 2. A v1 script loads converted and is stored unchanged until saved. |
| `business_line` | ≤200 | One line on what the business is; also ThinnestAI `businessDescription`. |
| `identity`, `goal` | ≤1000 each | Plain English. |
| `outbound_purpose` | ≤300 | Calls the agent places only. |
| `opening_line` | ≤1000 | The greeting; the only line guaranteed word for word. |
| `style` | `{tone ≤300, address_form ≤200, code_mix: light\|natural\|heavy, sample_phrases[] ≤20, pronunciations[{word, say_as}] ≤50}` | |
| `stages` | ≤12 sections, **list order = call order** | See below. |
| `adherence` | `flexible \| strict` | Two values only (default `flexible`). |
| `objections` | `[{objection ≤300, response ≤1000}]` ≤30 | |
| `policies` | `{offer_call_backs, share_prices, take_bookings}` booleans | Call backs are also bounded by the account (never on a trial). |
| `ending` | ≤1000 | |
| `end_call_extra_rules` | `string[]` | End-call rules, one per entry. |
| `faqs` | `[{question, answer}]` | Quick facts (win over knowledge). Moving them to Knowledge pinned facts is **NOT BUILT** (see open items). |
| `example_exchange` | `[{speaker: caller\|agent, text ≤500}]` ≤20 | Style only, in the call's language. |
| `example_needs_review` | bool | True while AI-drafted; clear it when the owner edits. |
| `variables` | `[{key, label, example}]` | `{{key}}` merge fields. |
| `raw_override` | `string \| null` | Hand-written prompt mode: every structured field must be empty (422 otherwise). |

**A section (`stages[]`, model `ConversationStage`):**

| Field | Type / limit | Notes |
|---|---|---|
| `id` | `^[a-z0-9][a-z0-9_-]{0,39}$`, unique | Stable across edits and reorders; branches and the canvas point at it. The client mints it (e.g. `s` + a short random string). |
| `name` | 1–80 | Title (ThinnestAI step title). |
| `mode` | `guide \| say` | `say`: said as written, best effort. |
| `instruction` | 1–600 | |
| `sounds_like` | ≤200 | Optional line in the call's language. `instruction` + `sounds_like` must fit one 600-character step detail (422 otherwise). |
| `branches` | `[{when ≤300, target}]` ≤6 | `target` = a section `id`, or `end`, `hand_over`, `call_back`. |
| `otherwise` | `""` or a target | Where to go when no branch holds; empty = the next section. |
| `collect` | `string[]` ≤10 | What must be in hand first. |
| `position` | `{x, y} \| null` | Canvas layout only, never compiled. |

An unknown `target`/`otherwise` or a repeated `id` is a 422. `hand_over` and `call_back`
become what the account can do at publish (no hand-over destination on duty → "say nobody can
take the call"; a trial → "say the business will get back to them").

### Routes

- `GET /script` → `{script, draft, stored_schema_version, context, version, is_freeform,
  has_pending, standard_variables}`.
  - `draft` = `{script, saved_at}` or null: the autosaved working copy. Edit it in place of
    `script` when present.
  - `context` = `{collect[{label, reason, required}], call_backs_available, hand_over_enabled,
    direction, language, register_name, register_needs_review, business_type, limits}`.
  - `limits` = `{max_sections, section_title_max, section_detail_max, sounds_like_max,
    max_branches, max_collect, instructions_limit, native_steps, special_targets}`, per the
    deployment's engine. Today on ThinnestAI: 12, 80, 600, 200, 6, 10, 8000, true,
    `["call_back", "end", "hand_over"]`.
  - A new or v1 script arrives with an example call for its language and business type,
    `example_needs_review: true`.
- `PUT /script/draft {script, base_saved_at?}` → `{saved_at}`. Autosave: no version, no
  compile, not audited, never reaches a call. Validated, so a 422 names the bad field.
  `base_saved_at` is the `draft.saved_at` the editor loaded (`null` when there was no draft);
  when sent, a stored draft that moved since (another tab) is refused with
  `script_changed_elsewhere` (409) instead of being overwritten.
- `POST /script/publish {summary ≤200, script?, expected_version?}` → `{version, live}`.
  "Put it live": the draft (or `script`) becomes a version whose note is `summary`, the draft
  is cleared, and the version is applied to live calls in the same request. `live` is false
  when the agent is not switched on (the version is what it will use) or the push did not
  complete. `script_changed_elsewhere` (409) when `expected_version` is stale;
  `script_nothing_to_publish` when there is no draft and no `script`. Audited
  `agent.script_published`.
- `GET /script/versions` → `[{version, summary, created_at, is_live}]`, newest first.
- `POST /script/versions/{version}/restore` → `{script, saved_at}`: copies that version into
  the draft. Callers keep the live version until the draft is put live.
- `POST /script/convert {raw_text?}` → `{script, unplaced[], disclosure, metered}`: AI proposes
  sections for a hand-written prompt (`raw_text`, or the agent's own text-mode script). Never
  saved or applied: show it for review; save it as the draft only if accepted. `unplaced`
  lists the lines of the prompt that appear nowhere in the proposal. Spends the dashboard AI
  allowance (`billing/ai_quota`, the ₹250 default meter); refused under view-as.
- `POST /script/assist {answers: {what_you_offer, customers, good_outcome, common_questions,
  never_say}, description?, current?, change?}` → `{script, disclosure, metered}`: the AI
  helper. Without `change` it drafts every section from the answers. With `change` (≤600, the
  owner's request) and `current` (the editor's working copy), it returns `current` with only
  that change made, every section `id` kept (new sections get new ids). It proposes and never
  writes. At least 10 characters across `answers`, `description` and `change`
  (`script_assist_too_little` otherwise). Same allowance and view-as rule.
- `POST /script/preview {script}` → `{compiled, instructions_chars, instructions_limit,
  native_steps}`: the exact instructions (platform rules included), then on ThinnestAI the
  sections as sent in its step list. Show `instructions_chars / instructions_limit` as the
  owner types; publishing over the limit is refused with `engine_prompt_too_long`, saying
  how much to cut.
- `GET /script/tests` and `POST /script/tests` → `{available, unavailable_reason, cost_note,
  latest}`; `latest = {status: queued|running|done|failed, prompt_version, is_current,
  results[{key, title, said, reply, verdict: passed|attention|failed|read, advice}],
  created_at, completed_at}`. Runs six scripted caller lines in the agent's language against
  the **live** agent (no draft twin) through ThinnestAI Test Chat; poll while queued or
  running (about half a minute). POST is refused at the dashboard AI allowance ceiling and
  under view-as; no rupee amount is recorded because ThinnestAI does not publish its
  chat-reply rate. Needs the agent switched on once. Advised, never required.
- Still served for the current screens: `PUT /script` (save a version, staged on a live
  agent), `POST /script/apply`, `POST /script/undo`. "Put it live" replaces them in the new
  builder.

### On ThinnestAI

Sections go to the agent's native `steps` (`title`, `detail` = instruction plus "It sounds
like", `branches` as `{when, action}` with "Otherwise" last, `collect`) and leave the
instructions; `[]` is sent when a script has none, so the outline is never in two places
(snapshots/2026-10-08/pages/api-reference/agents/update-agent.md:588-595, :865-905; read back
as AgentStep, get-agent.md:709-743). The publish refuses when the saved steps read back
differently (`engine_steps_not_saved`); the half-hourly settings check reports and repairs
`script_steps`. Instructions are capped at 8,000 characters: ThinnestAI's console showed
"8249/8000" (founder screenshot, 10 Oct 2026) while its API reference says 20,000
(update-agent.md:519-524, and docs.thinnest.ai on 10 Oct 2026); the two VENDOR-PUBLISHED
figures conflict and the lower one is enforced. UNKNOWN: whether the steps count toward that
box.

**Measured** (`tests/agent_prompt_budget_test.py`: the Raghava Organics retail starter,
Telugu, facts in knowledge, sections as steps): 6,086 characters for "Answer my calls" and
6,288 for "Call my leads" before the owner adds anything; the platform layers alone are about
4,500 characters for one language and 5,650 for three. The test fails if a typical agent
leaves less than 1,700 of the 8,000.

### Open items (not built)

- Quick facts into Knowledge as pinned facts, with a migration of existing `faqs`: needs the
  knowledge base to hold pinned facts (owner: knowledge lane); until then `faqs` stay in the
  script as quick facts.
- "Taught rules" from the AI helper into the draft as anytime rules: no field yet; propose
  `anytime_rules: string[]` when the helper's design is settled.
- Metering a rupee amount for test chats: ThinnestAI publishes no chat-reply rate.

## Founder decisions: agent page, script builder and call settings (10 Oct 2026)

Design reports: script builder research (market evidence, vendor limits, critique, validation
states, AI change flow) and the whole-agent-page redesign around the founder's Outpero
screenshots ("don't copy; improvise and make a better version in function and UI/UX").

1. **Flow view:** a visual flow canvas on desktop; on phones an Outpero-like list whose order
   comes from drag-and-drop reordering (improved, not copied). Canvas and list are two views
   of ONE saved model: the order of sections, branches and content are identical on both, and
   any edit in one shows in the other.
2. **Strictness:** two options only (not three, not Outpero's five).
3. **Testing:** test what is live only — no hidden draft copy of the agent at ThinnestAI.
4. **Saving:** autosaved draft plus one "Put it live", with history and restore; no Save →
   Apply and no version numbers shown.
5. **AI helper and chat test cost:** counted against the client's dashboard-assistant AI
   quota (₹250 default, adjustable by admin).
6. **Hand-written prompt ("power prompting"):** available to clients inside Script, and later
   converted into sections by AI. The conversion must be flawless: nothing lost, reviewable
   before it replaces anything.
7. **Notice switches stay on Overview.** They are the two disclosure switches (D-163/D-708):
   on = said at the start of the call before the opening line; off = not volunteered, but
   always admitted truthfully when asked.
8. **Telugu style:** one neutral spoken Telugu; no regional picker.
9. **Quick facts** move into Knowledge as pinned facts (migrated); taught rules go to the script.
10. **Leads & hours is per CLIENT, not per agent** (lead sources, wait before calling,
    calling hours, after-hours handling incl. hold-for-me, retries), designed better than
    Outpero's Instant leads.
11. **Improvement loop in this build:** "Make this call a test" and "Where it struggled → Fix in
    script / Add the answer".
12. **"Say these exact words"** stays, with an honest note that only the opening line is
    guaranteed word for word on this engine.
13. **Recording:** always on; clients only control the recording-notice switch.
14. **Answering-machine detection:** a client switch, default off.
15. **Caller lookup variables:** name and interest always; last call topic, open call back and
    language only when "remember callers" is on.
16. **No-API ThinnestAI settings** (fillers, interruption words, greeting finish, silence rules,
    goodbye phrases, hang up when done, the call-only speaking box, surfaces): email
    ThinnestAI for API fields; vendor defaults meanwhile.

## Calling setup (lane, 10 Oct 2026, D-716)

Built for founder decisions 10, 13, 14, 15 and 16 and the caller-lookup decision above.
- **Caller lookup**: `voice.callStartUrl` = `POST /v1/worker/engine-lookups/thinnest?agent=<ref>`
  on every published agent; secret sealed on `engine_agent_routes.call_start_secret_*`
  (migration `a9c4e2f7d138`), rotated when lost; variables per decision 15 (`crm/caller_lookup.py`).
- **Call settings**: answering-machine switch per client (default off) -> `voice.detectMachines`;
  `voice.ringSeconds` 30; recording unchanged; call cap 1-20 minutes on ThinnestAI (API and UI);
  drift reads ring time, machine switch, lookup address and alarms on web/WhatsApp surfaces.
- **Leads & hours** per client: `GET/PUT /v1/lead-calling`, `GET /v1/lead-calling/held`,
  `POST /v1/lead-calling/held/{id}/release|drop`; screen at `/c/{slug}/lead-sources`
  (nav "Leads & hours"). Lead sources, test lead and recent arrivals are the existing API.
- **Decision 16**: email drafted at `docs/vendor/thinnest-api-requests-2026-10-10.md`.
- Doc drift fixed in `docs/THINNEST-INTEGRATION.md` (summariseCalls on, the pre-answer hook).

## Knowledge teach and improvement loop (lane 3)

Founder decisions 5, 9 and 11. Built 10 Oct 2026; migrations `a8d3f6c1e924` (tables) and
`c2f7e8a4d1b6` (quick facts become pinned facts). Server code in `apps/api/teach/`, workers
`apps/workers/kb_teach.py`, `pinned_facts.py`, `agent_test_cases.py`.

**Pinned facts (decision 9).** Quick facts are no longer the script's. They are `kb_facts`
rows with `pinned = true`, per CLIENT (D-689), managed on `/c/{slug}/knowledge` (add, edit,
pin/unpin, reorder, remove). `c2f7e8a4d1b6` copied every agent's `structured_script.faqs`
(draft and live) into them, de-duplicated per client, answers kept whole (text up to 2,000
characters). Every agent's compiled body carries them as its `[QUICK FACTS]` section through
`calevate_shared.call_script.splice_quick_facts` (a v1 `[FAQ]` section is replaced too); a
change re-splices every agent in the `recompile_pinned_facts` job (new prompt version,
re-published on a live agent unless a script edit is staged). A script save that still
carries `faqs` moves them into pinned facts and stores the script with none. The pinned
section is capped at 1,500 characters (`teach.pinned.MAX_PINNED_CHARS`) so it fits the
8,000-character instructions box; an agent that still refuses raises
`pinned_facts_not_delivered`. Unpinned facts compile into ONE knowledge source, "Facts you
taught", searched like any other.

**Script API contract additions (for the builder).**
- `GET /v1/agents/{id}/script/proposed-rules[?status=pending|applied|dismissed]` → rules the
  owner taught for this agent (`agent_rule_proposals`); CallScript has no "anytime rules"
  field, so they wait here. `POST .../proposed-rules/{rule_id} {status: applied|dismissed}`
  (`org:manage`) once the builder has written one in. Lane 4a's `TaughtRules.tsx` uses them.
- The builder no longer edits quick facts and links to Knowledge.

**Teach box.** `POST /v1/kb/teach {words, gap_id?}` or `POST /v1/kb/teach/upload` (multipart
`file`, `kind=photo|file|voice`) → a teaching, polled at `GET /v1/kb/teach/{id}`. A photo is
read by the OCR leg (metered `kb_ocr`), a file by the document reader, a voice note (≤30 s)
by Sarvam's REST speech-to-text (`saaras:v3`, `codemix`; sarvamai 0.1.28
`speech_to_text/raw_client.py`) and stops at `heard` until the owner confirms the words
(`POST .../words`). Sorting into facts and rules runs in the worker on the dashboard-assist
ladder, metered against the AI allowance as `kb_teach`; with the allowance used up or no
model, the words come back unsorted for the owner to mark. `POST .../save {items[{kind,
text, pinned}], agent_id}`: facts (and pinned facts) into knowledge now, rules to the chosen
agent's proposed rules; an answer opened from a struggle marks that knowledge gap taught.

**Where it struggled.** `GET /v1/kb/struggles` = open knowledge gaps (with the latest call)
plus last-30-day calls with outcome `needs_you` and no gap. The screen offers Add the answer
(teach box), Fix in script (`/agents/{id}/script#stages` or `#policies`) and Open the call.

**Make this call a test.** `GET /v1/calls/{id}/test-case-draft` (caller turns,
`text_redacted` only), `POST /v1/calls/{id}/test-case`, `GET/POST /v1/agents/{id}/test-cases`,
`POST .../test-cases/run`, `DELETE .../test-cases/{case_id}`. A run sends each test's lines
in one test-chat conversation to the LIVE agent; replies are stored for the owner to compare.
A caller's DPDP erasure deletes tests made from their calls.
**Integration note for the call-detail lane:** mount
`<MakeCallTest callId={call.id} />` (`apps/web/src/components/improvement/MakeCallTest.tsx`)
in the call detail header or follow-up area. **For the agent page lane:** mount
`<SavedTests agentId={id} />` and `<TryChat agentId={id} />` from the same folder.

**Try it chat.** `POST /v1/agents/{id}/try-chat {message, session?}` through ThinnestAI
test-chat (`snapshots/2026-10-08/pages/api-reference/agents/test-chat.md:328-460`). Refused
when the month's AI help is used up. UNKNOWN: the per-reply price for an agent on
ThinnestAI's own models (the page says "billing as the console's Playground"; the only
published figure, ₹0.02 a chat reply, is the all-keys BYOK rate), so no usage row is written
and the screen says replies are not charged. Closing this needs a founder-attested rate and
a usage unit.
