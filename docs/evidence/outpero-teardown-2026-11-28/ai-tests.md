# Outpero's built-in AI, tested 28 Nov 2026

## 1. Rehearse (typed call), employee "Tarun" (Rytu Khata install script), ₹0.20/message, 7 messages
Opening shown: "హలో అండి, తో మాట్లాడుతున్నానా?" — the {Lead Name} variable is blank in a rehearsal
and the line keeps the gap (no fallback wording).

| # | Caller (typed) | Agent |
|---|---|---|
| 1 | Avunu, cheppandi. | Who/why/what/offer in one turn: from Rytu Khata; you registered on our website but haven't started; app tracks expenses, sales, profit; "free for farmers in Hyderabad, Telangana" (the location answer misused as a price condition, again); shall we set it up together? |
| 2 | Rytu khata ante enti? Naaku register chesinattu gurthu ledu. | Explains the app in one line; "once you register on the website the data stays there"; offers help. Does not claim to have checked records. |
| 3 | Sare, help cheyandi. Android phone. | TWO actions in one turn: open Chrome and type rytukhata.com, then "tell me once it opens" (asks the caller to report back). |
| 4 | Okay. | Does NOT take "Okay" as done: "Did you open rytukhata.com in Chrome?" (good) |
| 5 | Open chesanu. Ippudu em cheyali? | Tap the menu (three dots or three lines) then choose "Add to Home Screen"; "tell me once done" (two actions, report back). |
| 6 | Price entha? Free ena? | Answers from training: free for farmers, no charges; then returns to the step ("Did you Add to Home Screen?"). Good. |
| 7 | Chaalu andi, migatadi tarvata chustanu. | "Okay, whenever you want to set it up I'm here to help; anything else?" Does not claim the setup is done (good) but does not ask when to call back nor say what is left. |

Strengths: natural code-mixed Telugu; answers a side question and comes back to the step;
treats a bare "Okay" as not done. Weaknesses: bundles actions; asks to be told when done; wrong
fact composition ("free in Hyderabad"); no call-back offer on an early stop; blank-variable gap.
Cost: ₹1.40 shown for the 7 messages.

Rehearse shows the agent's tool calls inline, e.g. after the caller's second "Chaalu…":
"end_call — would hang up · {reason: caller not ready to proceed now} · Not actually run." and a
"Rehearse again" button. Total shown ₹1.60 (8 messages). A good debugging aid we lack in text.

## 2. Swara edit (AI script editor), same employee, ~30 s, about ₹0.2
Request typed: one action per turn in every step; never ask the farmer to tell you when done,
ask what they see instead; on an early stop say which steps are left and ask when to call back;
remove WhatsApp and support timings.
Result note from Swara: "Rewrote every step to give only one action per turn and ask what is on
the screen, not 'is it done'; added handling for stopping early with steps left and callback in
all relevant sections; removed WhatsApp/support timings from close." + Undo + "Helpful?".
Each changed step is tagged "updated". Step 2 became: open Chrome/Safari → ask what they see →
type rytukhata.com → ask what they see → find "Add to Home Screen" → for each action wait and
ask what is on the screen → log in step by step → on early stop tell which steps are left and
ask when to call back. Example line now ends with "what do you see on your screen now?".
Verdict: followed all four instructions in one pass, kept the owner's structure, and marked what
it changed. It did NOT fix the untouched error ("free for farmers in Hyderabad, Telangana") —
it edits only what it is asked. Our equivalent (Pip script edit) — compare in the gap analysis.

## 3. New employee from scratch: inbound clinic receptionist (fictional "Sri Sai Clinic")
Brief (ours, fictional): family clinic in Kukatpally, Hyderabad, one GP Dr. Ravi; tell timings
(Mon–Sat 9–1 and 5–9, Sun closed), fee Rs 300, book a slot with Dr. Ravi, take a message
(name + number) otherwise; emergency → nearest hospital or call 108.
Flow: Inbound + Telugu + brief → only ONE follow-up question ("Anything they must never say or
promise?" — "Your brief had what it needs" for the rest); the chips stayed generic (never
guarantee returns / offer discounts) — not adapted to a clinic. We added "Never give medical
advice or a diagnosis" and "Never share other patients' details". Build ~40 s → employee
"Ishita", "Clinic Receptionist · Answer calls · P01 voice · Telugu", Draft/Not published, 6
steps, 2,540 chars. Tabs now say "Answer calls" instead of "Campaigns".

Opening: "Namaste! Thanks for calling Sri Sai Clinic. How can I help?" (Telugu script).
Steps: 1 find out why they called, watch for emergency; 2 emergency → hospital/108, nothing else;
3 timings + fee; 4 book with Dr. Ravi: date/time within hours, then name, ONE at a time, suggest
another slot if unavailable; 5 take a message: name, number, message one at a time; 6 wrap up.
Empty FAQ step.

Faults found:
- Step 6 example says "your booking is confirmed" and offers to WhatsApp details — with NO
  calendar or WhatsApp action connected; nothing checks slot availability (step 4 "if any slot
  is unavailable" — it cannot know). Promises an action it cannot perform.
- Numbers spoken as English words in Telugu letters: fee "రూ త్రి హండ్రెడ్" (Rs three hundred),
  108 as "వన్ ఓ ఎట్" (one-o-eight). For an emergency number, digit-by-digit Telugu is safer.
- Step 5's example asks name, number AND message in one breath despite "one at a time".
- No "never give medical advice" anywhere in the script (it went to Training as a rule, if at all
  — check), and no guidance for symptom questions beyond emergency.
- Emergency is handled twice (steps 1 and 2) — fine for safety, but duplicated.
Good: emergency first; one-at-a-time booking; message-taking fallback; natural code-mixed
Telugu; built from a one-paragraph brief with one question.
Training built from the brief: Facts "Areas you cover: Kukatpally, Hyderabad" (location again
filed as a service area), "Prices: Rs 300", "Timings: Mon–Sat 9–1 and 5–9, Sunday closed";
Rules: our two never-rules. Outcomes "What to capture" auto-made for the job: Caller Name,
Appointment Date (type **Date** — typed fields exist now, Aug was untyped), Appointment Time,
Message for Dr. Ravi, Phone Number, Reason for Call (free text).
