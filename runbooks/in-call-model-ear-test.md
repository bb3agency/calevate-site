# In-call model ear test: GPT-OSS 120B vs Prana [Voice] (founder, D-714)

Goal: hear whether the agent speaks natural, local, spoken Telugu (everyday Telangana/Andhra
speech, the English words people use, andi/garu, short sentences) and not textbook Telugu.
Two models x two prompts = four runs of the same six lines. Everything below is done by the
founder from the ops console and a phone; nothing here is automatic.

## 0. Before you start
- Deploy this change (script v2 + the new prompt layers) first; the old prompt is on every
  agent until it is republished.
- Use one test agent of Raghava Organics on a Clear (Premium) voice. Note its current voice
  and model on the agent's Voice section so you can put them back.
- Price: GPT-OSS 120B shows no surcharge tag in ThinnestAI's dropdown (founder reading,
  10 Oct 2026); Prana [Voice] none either. Do NOT test GPT-5 Mini here: it is tagged
  premium ₹2.50/min.

## 1. The four runs
| Run | Model | Prompt |
|-----|-------|--------|
| A | Prana [Voice] (today's default) | old script, as published now |
| B | Prana [Voice] | new: open the script builder, check the sections and the example call, Save, Apply |
| C | GPT-OSS 120B | new (as B) |
| D | GPT-OSS 120B | new, with the example call deleted (Save, Apply) — tells you what the examples add |

Run A first, before applying anything. For B, C and D:
1. Model: ops console -> Settings -> Voice engine -> ThinnestAI -> "In-call language model
   for Clear agents". For C and D type `GPT-OSS 120B` and save; the console stores the id
   ThinnestAI lists for it and refuses it if it is not call-capable on our plan. For B
   leave it empty (Prana [Voice]).
2. Republish the agent (switch it off and on, or Apply a script change) so the model and
   prompt reach ThinnestAI. Check the agent's Voice section shows the model you expect.
3. Place a dashboard test call to your own phone and read the six lines below, in order,
   pausing for each answer. Record the call (the call detail page keeps the recording).

## 2. The six caller lines (read exactly)
1. `హలో, మీ దగ్గర ఎండు మిర్చి ఉందా అండి?` (product question)
2. `కిలో ఎంత అండి?` (price question)
3. `ఇప్పుడు busy గా ఉన్నా, తర్వాత call back చేస్తారా?` (call-back request)
4. `మీరు మనిషా లేక AI ఆ?` (are you an AI)
5. `delivery ఉంటుందా? ఎన్ని రోజుల్లో వస్తుంది?` (delivery, likely not in knowledge)
6. `సరే అండి, thanks.` (closing)

## 3. What to listen for (score each run 1-5)
- **Register:** spoken Telugu with English words where people use them ("price", "order",
  "delivery", "call back"), or written/news Telugu ("ధన్యవాదాలు", "క్షమించండి", "దయచేసి",
  "తెలియజేయండి", "అందుబాటులో ఉంది")? Count the formal words.
- **Length:** one short sentence a turn, or speeches?
- **Search:** line 1 and 2 answered from knowledge (needs the product and price in
  Knowledge), not "I'll connect you" or an instant call-back offer.
- **Honesty:** line 4 answered plainly as an AI. Line 5: says it does not have the detail.
- **Call back:** on a trial account the agent must NOT promise a call back (it says the
  business will get back to you); on a paying account it may offer one.
- **Variety:** does it start every turn the same way ("సరే అండి, ...")?
- **Speed:** silence before each answer (GPT-OSS 120B ~221 ms vs Prana [Voice] ~560 ms in
  ThinnestAI's console; the phone adds speech-to-text and voice time).
- **Names:** "Raghava Organics" said correctly; no "Dr." pause.

## 4. After
- Pick the model; leave the console setting on it (empty = Prana [Voice]).
- Send the example calls and word list in `packages/shared/src/calevate_shared/spoken_style.json`
  to a native Telugu and Hindi speaker; change `review` to `native_reviewed` with their name
  in `reviewed_by` once read.
- Put the test agent's voice back if you changed it.

## 5. Text comparison across models (script, D-739)
The ear test above judges the voice. This one judges the words, the same callers on every
model, scored by the same rules the agent tests use: no textbook words from the spoken-style
list, no brackets, dashes, slashes, ellipses or bullets, no time read out, prices and
quantities in words rather than "₹450" or "1 kg", never the caller's part, one question with
its "?" and then wait, at most two sentences unless the caller asked for detail
(`apps/api/agents/turn_checks.py`). Run it from the VPS deploy root;
it needs the ThinnestAI key, which the api image adopts from the ops console.

1. **Which model is the agent on now?** (changes nothing)
   ```sh
   docker compose -p calevate -f compose.prod.yml run --rm --no-deps \
     --entrypoint python api -m scripts.compare_in_call_models show \
     --tenant <tenant uuid> --agent <agent uuid>
   ```
   It prints the model ThinnestAI holds for the agent, the agent's own choice in our
   database and the console's in-call default. ThinnestAI's call record names no model, so
   for a past call this is the answer only if nobody changed the agent or the console
   setting since that call.
2. **Make a test copy.** The agent answers real calls on whatever model it holds while the
   script runs. In the client dashboard create a second outbound agent for the same client
   from the same starter (or copy the script into it), put it live, attach no number and
   start no campaign. Note its id.
3. **Run it** (about 14 test messages per model, 4 s apart: roughly 4 minutes for four
   models; add `--judge` for the AI judge's verdicts too):
   ```sh
   docker compose -p calevate -f compose.prod.yml run --rm --no-deps \
     -v /tmp:/out --entrypoint python api -m scripts.compare_in_call_models run \
     --tenant <tenant uuid> --agent <test copy uuid> --agent-takes-no-calls \
     --models "GPT-OSS 120B,Prana [Voice],GPT-5 Mini,GPT-4.1 Nano" --judge \
     --out /out/model-compare.json
   ```
   It switches the copy to each model, talks the standard callers through ThinnestAI's
   test chat, and puts the copy back on the model it started on, even if it fails part-way.
   A model missing from ThinnestAI's list, not call-capable or not on our plan is skipped
   and named.
4. **Read the table.** One row per model: its price band and latency as ThinnestAI's console
   lists them (founder's reading, 10 Oct 2026; GPT-5 Mini is tagged Premium ₹2.50/min, the
   others carry no surcharge and bill at the voice's band), how many conversations passed
   the hard checks, which shape problems it showed, the judge's verdicts, the model that
   judged, and the average reply length. The judge avoids the family of the model under test
   where another approved dashboard leg exists (a GPT model is judged on our Gemini leg when
   that leg is attested, a Gemini model on Azure); the "Judged by" column says which ran, so
   a row judged by its own family is read with that in mind. `/tmp/model-compare.json` on
   the host holds every transcript.
5. **Decide**, then set the console's "In-call language model for Clear agents" to the
   winner; saving it republishes every live agent (D-720). GPT-5 Mini can only be chosen
   beside a voice whose band is at least Premium. Delete the test copy.

Costs: test chats are billed by ThinnestAI at a rate it does not publish; `--judge` uses the
dashboard AI chain at our cost and is not charged to the client.
