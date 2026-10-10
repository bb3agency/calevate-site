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
