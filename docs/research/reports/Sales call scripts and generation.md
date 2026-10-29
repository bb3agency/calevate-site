# Disclose first, then earn the next ten seconds

Calevate can make volunteered AI disclosure the outbound default without walking into the Luo et al. hang-up cliff. The only randomized study that measured the damage found it came from a **bare identity sentence said cold**: 56.3% of people hung up within 5 seconds, and purchases fell 79.7%. Calevate's current composed first turn, when the AI notice is on, reproduces most of that pattern. It drops the founder's "we are calling from {business}" half and keeps only the salutation, the AI sentence and a "can you talk now?" question. So the call names no reason, and it ends on the permission check that Gong's 2018 vendor data found did worse than baseline. The fix is small and sits in code that already exists. The first turn should carry identity, "AI", the business and a **generic, true reason tied to the lead's own enquiry**, and end on one question. The enquiry details wait until the right person is confirmed. The newer evidence makes this safer than Luo implies. A 2026 Management Science field experiment found an 11% response penalty, offset by human-like delivery (abstract only). An LLM-era working paper found no conversion penalty (snippet only). Ipsos reports that 67% of Indians expect AI use to be disclosed. None of this is Indian call data, so the switch must ship with per-contact measurement. For selling, the step plans need two additions. One is a value step: one configured fact, matched to what the lead just said, placed after qualification. The other is a close that offers two real date-and-time options plus an exit, then reads the date back once. Both stay behind four guards: the facts rule, `ACTION_CLAIM_RULE`, the `let_go` rule and a new promotional-content lint. The lint matters because any promotional sentence turns a whole service call promotional under TRAI. Generation and testing change in four places: the writer gets a capability manifest, the lints check scripts against it, every call gets a resolved IST date table, and the judge gains an advisory sales scorecard. A/B tests randomize per contact; samples of about 700 to 1,800 calls per arm are needed for the effects that matter.

Evidence classes used throughout. **Peer-reviewed RCT**: a randomized trial in a refereed journal, text read. **Peer-reviewed (abstract)**: only the abstract or a listing was read. **Working paper**: unrefereed. **Vendor data**: a company analysing its own data. **Vendor advice**: a company's how-to, which is opinion. **Survey**. **Secondary-legal**: a law-firm or press summary. **Opinion**. **Repo**: Calevate code or docs read at HEAD `6d2576d90`. **UNKNOWN**. No claim below is stated more strongly than its class allows.

## The 56% hang-up came from a bare sentence, and Calevate's opener is close to it

The anchor study is Luo, Tong, Fang and Qu (2019, *Marketing Science*), a **peer-reviewed RCT** with 6,255 customers of a Chinese fintech lender who received outbound loan-renewal calls. The disclosure was one sentence: the caller said it was the company's AI voice chatbot. Said before the conversation, it cut the purchase rate from **0.237 to 0.048**, and **56.3% of people hung up within 5 seconds**. Said after the conversation but before the decision, the purchase rate recovered to **0.110**, and hang-ups were 4.5%. The mechanism was bias, not a feeling of being tricked: callers who knew rated the bot less knowledgeable and less empathetic, although voice-mining showed it was as competent as skilled humans. There were **no complaints or cancellations**. **Prior AI experience significantly reduced the penalty** ([Luo et al. 2019, PDF](https://www.fox.temple.edu/sites/fox/files/Frontiers-Machines-versus-Humans-The-Impact-of-Artificial-Intelligence-Chatbot-Disclosure-on-Customer-Purchases.pdf)). It was pre-LLM technology, one offer, one country and a 77% male sample. Even so, the lesson for design is specific. The damage sat in the first five seconds, and it followed an identity statement that carried no reason to keep listening.

Later evidence points the same way and narrows the penalty, though it has been read less deeply. Xu, Dai and Yan (*Management Science* 2026, **peer-reviewed, abstract only**) randomized 11,000 truck drivers called by a freight dispatcher bot. Disclosure cut response by about **11%**. Anthropomorphic delivery, meaning interjections and fillers, raised response, conversation length and order acceptance by about **5.6–26.9%**, offsetting the penalty through trust ([INFORMS](https://pubsonline.informs.org/doi/epdf/10.1287/mnsc.2022.03833)). Habel, Zawadzki and Freise (**working paper, snippet only**; industry and country UNKNOWN) report that disclosing an LLM-era voice agent **no longer reduced conversion** (N=1,337). They also report that people recognize AI whether told or not, and that AI agents still undersold humans because they handled the sales process weakly ([SSRN 7013259](https://papers.ssrn.com/sol3/Delivery.cfm/7013259.pdf?abstractid=7013259&mirid=1)). On inbound, Upfirst's 450,702-call analysis (**vendor data, observational**) associated disclosure with about **20% fewer** hang-ups and a recording notice with about **30% fewer**. Ending the greeting on a question beat ending on a statement by about 15%, and greeting length made no difference ([Upfirst](https://upfirst.ai/blog/ai-receptionist-hang-ups)). Inbound callers chose to ring, so Luo remains the better guide for outbound. In India, **67% expect products and services using AI to disclose it** (**survey**, [Ipsos AI Monitor 2025](https://www.ipsos.com/en-in/trust-and-transparency-emerge-key-cornerstones-ai-usage-among-indians-ipsos-ai-monitor-2025)). **No Indian or Telugu field data on disclosure exists in anything read.** The one first-hand Indian account is an anecdote: a team calling warm leads with a Hindi AI agent expected 30–40% immediate hang-ups and saw 6% ([X post](https://x.com/Yash912/status/2041917124046991780?lang=en)). It is not evidence of a rate.

Now set that against what Calevate actually says (**repo**). With the AI notice on in Telugu or Hindi, `join_first_words` composes the first turn as follows: a fixed formal salutation from `INTRODUCTION_SALUTATIONS`, then the AI sentence ("I am {name} from {business}, the AI assistant"), then only the **question half** of the founder's stored outbound opener ("can you talk now, are you free?"), then the recording notice if it is on ([engine.py:4359-4411](../../../packages/shared/src/calevate_shared/engine.py); [spoken_style.json:587-594](../../../packages/shared/src/calevate_shared/spoken_style.json); [tests/ai_notice_introduction_test.py:205-211](../../../tests/ai_notice_introduction_test.py)). The half that says why the business is calling disappears. What remains is an identity sentence followed by a bare permission check. Gong's analysis of 90,380 US B2B cold calls (**vendor data**) found that a stated reason for calling scored about **2.1x** the 1.5% baseline, even when the reason was weak. The "bad time?" permission opener scored **0.9%** ([Gong Labs](https://www.gong.io/resources/labs/cold-call-opening-lines/)). A 2024 Gong re-analysis reportedly reverses the permission finding, but it could not be retrieved (secondary, unverified). The two sources agree that the reason is the active ingredient. So the current Calevate opener drops exactly the clause that both bodies of evidence say keeps people on the line.

## Default-on disclosure is a two-line change; the opener around it is the real work

### Where the default lives

The default is literally spelled in one place. `lifecycle.create_agent` inserts every agent with the literal `false, false` for `ai_disclosure_enabled, recording_notice_enabled`, with a comment citing D-669 ([lifecycle.py:364-389](../../../apps/api/agents/lifecycle.py), **repo**, read this pass). The column's `server_default="false"` cannot vary by direction ([models.py:694-705](../../../apps/api/agents/models.py)). The right change is therefore at the INSERT: bind the AI value from the direction, true for `outbound` and `both`, and leave the server default alone. The new agent must still pass the 200-character greeting budget that `set_disclosure_posture` enforces (D-846). Today that check runs only when the switch is flipped, not at create ([publishing.py:1369-1490](../../../apps/api/agents/publishing.py)). So the create path must either call that check or rely on a test that every starter's composed outbound first turn fits `GREETING_MAX_CHARS=200`. The per-agent toggle (D-163), the locked truthful answer, and the campaign rule that volunteering is "never a launch blocker" all stay as they are. Existing agents were not flipped when D-669 changed the default, and whether to flip them now is a founder decision. The 30 Oct decision has no D-number row yet (latest seen D-939), and it needs one.

### What the first turn should hold

Shipping default-on with today's composition would be the worst version of the change, so the opener must change first or together. Four inferences follow, each testable, and none of them measured in India.

The first is to put the **AI identity, the business, and a reason clause in one breath**, then one question. This is the opposite of Luo's bare sentence, and it is still "at or before the first interaction", which is the EU Art. 50 standard Calevate already uses as its strictest reference ([Art. 50](https://artificialintelligenceact.eu/article/50/)).

The second is to make the reason **generic and true by lead source**: "about the enquiry you made with {business}". It should not name the enquiry content, such as "2BHK in Kokapet". The enquiry is disclosed only after the person is confirmed, which protects the lead if someone else answers. Calevate's no-cold-calls pledge and seven-day inquiry window make "you enquired" true for the leads it may call. A lead from the three-month relationship limb needs a different reason form, such as "about your earlier visit with us". So the reason clause is a small set of founder-written lines keyed on lead source, not free text.

The third is to **say "AI" with the name, in the same clause**. A persona name with no "AI" beside it reads as a human claim. The current Telugu template already does this. The English template, which names no persona, is also fine. Whether rural callers understand the loanword "AI" is UNKNOWN, and is worth an A/B test against a native gloss.

The fourth is to **fold the recording notice into the same sentence** when both toggles are on, keeping the two as separate switches under hard rule 5. Upfirst's association supports it only on inbound (**vendor data**), and Regal's undisclosed-figure test also bundled them (**vendor advice**, [Regal](https://www.regal.ai/blog/ai-agent-ethics-disclosure-timing)).

The target is a first turn of about 8–10 seconds. That is an inference from Luo's 5-second window and from Rime/Miravoice's finding that 20–30-second disclosure intros on cold US landline calls lost 88–90% of people (**vendor data, no non-disclosure arm**, [Rime](https://www.rime.ai/resources/which-ai-voice-keeps-people-on-the-phone)). No source gives an optimal length.

### Code that blocks the new opener

Two pieces of current code get in the way. First, `INTRODUCTION_SALUTATIONS` fixes the formal salutation for every introduced agent. The founder's casual "hi" greeting therefore survives only when disclosure is off, and keeping a casual outbound greeting with disclosure on needs a direction-specific salutation. That is a code change, and the founder writes the line. Second, `OPENING_CONTINUES_RULE` currently says "Asked who or why? Say both in one line, then your first question" ([engine.py:4491-4496](../../../packages/shared/src/calevate_shared/engine.py), **repo**, read this pass). That sentence instructs the stacking that the 30 Oct comparison flagged: the agent answered "who is this?" and stacked its next question on top (rememory 518ac2e3). With identity and reason already in the first turn, "who is this?" should get the identity and reason again in one line and then a stop. That is a wording change inside the per-call budget.

Disclosure on outbound also needs an honest exit for people who refuse machines. Habel's finding that expected insincerity drives disengagement argues against persuading them. The agent should acknowledge the objection, offer a person or the business's number **only if a hand-over or call-back is configured**, record "prefers a person" against the lead, and close. A request not to be called again goes to DNC, which is already built.

## A value line and a two-choice close can sell without promising, if four guards hold

### The value step

No study tests a value statement on short qualification calls (UNKNOWN), so the design follows from constraints rather than a measured lift. The binding constraint is regulatory. Under TRAI's TCCCPR Second Amendment (Feb 2025), **promotional content mixed into a service or transactional call makes the whole call promotional** (**secondary-legal** in this pass, [Khaitan & Co](https://khaitanco.com/thought-leadership/Efforts-to-Curb-Spam-Continue-TRAI-Releases-Second-Amendment-to-the-TCCCPR-2018); the earlier market report in this series records reading the official text as clause 2(av)). So the value line has to be **information the lead asked for**, not a pitch: one configured fact that answers what this lead just said, such as possession date, location or configuration availability. It is placed **after qualification and before the close**, so it reads as an answer. It never carries a discount, a scheme, "best", an appreciation or return claim, or social proof the owner did not configure as a true, specific fact. If no configured fact matches, the step is skipped, never filled.

Gong's B2B vendor data says lost deals feature long monologues and more questions: about 20 questions against 15–16 on won calls, and 62% against 57% seller talk time ([Gong Labs](https://www.gong.io/resources/labs/talk-to-listen-conversion-ratio/)). That supports one sentence for the value line, not a paragraph. Whether a value line raises bookings at all is UNKNOWN until Calevate measures it. Whether a responsive fact on a warm callback could ever be read as promotional is a question for counsel. So is whether a real-estate call must state the RERA number, which was not verified.

The step plugs into `trade_playbooks.py`. A new step goes between "find out what they need" and "offer {booking}" in the `call_leads` plan ([trade_playbooks.py:201-246](../../../apps/api/agents/trade_playbooks.py)), plus a `TradeWords` field for the trade's typical value topics with `_trade_lines`/`ALL_LINES` updated. The writer's outbound sentence in `_SYSTEM_INSTRUCTION` changes to match ([script_assist.py:147-152](../../../apps/workers/script_assist.py)). Its source is always the owner's facts, enforced by the existing `facts` rule.

### The two-choice close

The close has the best-evidenced design of anything in this report, though the evidence comes from outside sales. Milkman et al. (*PNAS* 2011, **peer-reviewed RCT**, 3,272 employees) found that prompting people to plan a **specific date and time** raised follow-through by **4.2 percentage points** over a 33.1% control. A date-only prompt gave +1.5 pp, which was **not significant** ([PMC3127912](https://pmc.ncbi.nlm.nih.gov/articles/PMC3127912)). The useful element is the concreteness, not an "illusion of choice". No controlled study compares an alternative close with a direct ask (UNKNOWN, opinion only). "But you are free to say no" looked strong in a 2013 meta-analysis, but showed **no effect in the low-bias studies** of a 2023 pre-registered re-analysis (**peer-reviewed**, [Meta-Psychology](https://open.lnu.se/index.php/metapsychology/article/view/2640)). The exit option is therefore kept for honesty, not sold as a conversion tactic.

The close becomes: two **real** date-and-time options plus "or another time that suits you". The options come from a scheduling tool if the account has one, otherwise from configured visit windows in the facts. If neither exists, the agent asks the preference ("morning or evening?", already allowed in HOW TO SPEAK). Then comes a single read-back of the absolute date, weekday and time ([Vapi prompting guide](https://docs.vapi.ai/prompting-guide), **vendor advice**), ending in the honest next step. Without a booking tool, `ACTION_CLAIM_RULE` already forces "noted for the team to confirm". With `take_bookings=False`, the policy text turns the close into "note what they want and when it suits them" ([call_script.py:1003-1012](../../../packages/shared/src/calevate_shared/call_script.py)). The two-times pattern already exists inside "Offer {booking}". What changes is that both options must be concrete dates and times, the exit is explicit, and the read-back states the weekday that `DAYS_RULE` computed.

### Objections stay inside `let_go`

Objection handling should stay inside `let_go`: one short offer at most, then a polite close ([call_rules.py:121-133](../../../apps/api/agents/call_rules.py)). The harm evidence is the spam channel. Truecaller counted about **4,168 crore spam calls in India in 2025**, with sales and telemarketing the largest category at 36% (**vendor data via press**, [Business Today](https://www.businesstoday.in/amp/india/story/indians-received-over-4000-crore-spam-calls-in-2025-1189-crore-blocked-report-515765-2026-02-11)). TRAI's 2025 amendment reportedly lets a handful of complaints trigger action against a sender (**secondary-legal**, [Moneylife](https://moneylife.in/article/spam-calls-sms-regulations-tightened-by-trai-5-complaints-to-trigger-action-against-spammer/76368.html)). For a product positioned as "honest AI, not another spam caller", a second push costs more than it can win. The one data-backed technique is to **pause and acknowledge before answering**, Gong's "patience score" (**vendor data**; the "5x longer" multiplier is unverified) ([Gong Labs](https://www.gong.io/resources/labs/handling-sales-objections/)).

What the objection set lacks is **capability conditioning**. Objection responses compile as free text into [OBJECTIONS] "in this spirit" ([call_script.py:995-1000](../../../packages/shared/src/calevate_shared/call_script.py)). A written response can therefore imply a WhatsApp send, a call-back or a person on an account that has none. The platform's WHAT YOU CAN DO block sits after the script and wins at runtime ([engine.py:3441-3484](../../../packages/shared/src/calevate_shared/engine.py)), so the agent should not act on such a response. But the script contradicts the platform, and the contradiction is a defect the lint should catch at write time. Each objection then has a configured branch and an unconfigured one:

- **"I'm busy"**: offer two call-back times only if call-backs are on, and otherwise close.
- **Price**: the configured range if one exists, otherwise "the team shares exact pricing", with no discounts.
- **Timing**: accept it, ask once whether a later check is fine, and record it.
- **"Already bought"**: congratulate, close and mark the lead.
- **"Who gave my number?"**: give the true source from the lead record, and offer to stop calling.
- **"I don't want a machine"**: as described in the disclosure section above.

## Generation and testing need a capability manifest, a lint, a date table and a sales scorecard

### What the writer is told

The writer knows the business but not what the account can do. `ScriptBrief` carries the name, type, direction, language, the details to collect, knowledge titles and five owner answers ([script_assist.py:477-551](../../../apps/workers/script_assist.py), **repo**). It does not carry which actions exist: booking tool, WhatsApp send, call-backs, hand-over, scheduling windows. Nor does it carry where the leads come from. The writer is told to stay silent on call-backs and transfers because the platform adds them. That keeps disclosure clean but leaves objection and close lines blind. Adding a **capability manifest** and the **lead-source list** to the brief is a small change, and it lets a deterministic lint compare every spoken line against the manifest.

A sixth owner question would feed the value step directly: "What one true thing should an interested caller know about you?" The answer is stored as an owner fact, not a slogan. The vendor consensus favours describing outcomes and completion conditions over long ban-lists, which "can prime the banned phrases" ([Vapi](https://docs.vapi.ai/prompting-guide); [Retell](https://docs.retellai.com/build/prompt-engineering-guide), **vendor advice**). So the new constraints belong in code lints and step "done when" conditions, not in more prompt prose. That matters because the per-call budget has single- to double-digit headroom under `PER_CALL_MAX` ([tests/agent_prompt_budget_test.py](../../../tests/agent_prompt_budget_test.py)).

### What the lints check

`language_problems` and `said_line_problem` ([script_assist.py:279-341](../../../apps/workers/script_assist.py); [call_rules.py:179-200](../../../apps/api/agents/call_rules.py)) already reject done-claims, provider names and over-long openings. They should also catch:

- promotional and false-urgency vocabulary (offer, discount, scheme, limited, only today, last units), with Telugu and Hindi term lists supplied by the founder;
- action verbs not backed by the manifest (sent, booked, a person will call);
- any figure or price in a spoken line that does not appear in the facts;
- more than one question in any `sounds_like` or example turn;
- implied prior relationships;
- any personal name other than the configured agent name.

These are blocking and get one repair round, as today. The same promotional lint should also run at campaign launch, as the earlier market report recommended.

### Dates in every call

Dates already have the right foundation. Since D-888 every call gets `Today: {{today}}` in IST, and `DAYS_RULE` counts from it ([engine.py:3237-3298](../../../packages/shared/src/calevate_shared/engine.py)). The evidence says in-context date arithmetic is the weak point, and tools or precomputed values fix it. SPAN (AAAI-26, **peer-reviewed, snippet level**, cross-calendar rather than weekday) measured 34.5% average accuracy rising to 95.31% with a tool ([arXiv 2511.09993](https://arxiv.org/html/2511.09993v1)). The cheap step is a compact **seven-day table**, today through six days out with weekdays, computed in `Asia/Kolkata` beside `today_value`, sent the same way `{{today}}` is. It costs per-call characters that must be paid for elsewhere. A date-resolving custom function on ThinnestAI is the stronger option, and its support is UNKNOWN; it needs checking against the vendor snapshot. Chat and WhatsApp surfaces still get no date at all (D-888 gap). Either way, the close's read-back states the date and the weekday, and a turn check verifies that they agree with the IST calendar.

### What the tests score

The test loop already does most of what the vendors recommend: versioned sets, real calls first, compliance probes, repeated trials, platform rules checked in code and a cross-family judge ([test_conversations.py:1-60](../../../apps/api/agents/test_conversations.py); [agent_test_ai.py:380-416](../../../apps/workers/agent_test_ai.py)). It is, however, **blind to selling**: the judge scores task correctness only. The research supports a split. **Deterministic, blocking checks** in `turn_checks.py`:

- disclosure spoken when toggled;
- no action claimed without a tool event (the existing `unconfirmed_action`);
- at most one question per turn;
- no re-ask of a captured field;
- no promotional term;
- the stated weekday matches the date.

An **advisory sales scorecard** in the judge:

- reason stated early;
- value line drawn from facts, or rightly skipped;
- qualification within about 4–6 questions;
- two concrete options plus an exit;
- objection handled without a new promise;
- conciseness.

The scorecard should stay advisory. Judges are reported strong on single-turn errors and weak on cross-turn state (**vendor data, primary study not located**, [Cekura](https://www.cekura.ai/blogs/voice-ai-evals)). No public study ties any eval metric to bookings (UNKNOWN). For promise-safety scenarios the pass rule should be **all k trials pass**, not any. ServiceNow's EVA found a large gap between "can succeed" and "reliably succeeds" ([EVA](https://huggingface.co/blog/ServiceNow-AI/eva)). The practice-caller writer ([agent_test_ai.py:192-232](../../../apps/workers/agent_test_ai.py)) needs five new personas: the machine-averse callee, the wrong person, the NRI in another time zone, the price-first lead and the busy lead.

## Conclusion

The research reframes the founder's decision. The question is not whether disclosure costs conversions. It is **what the five seconds after the disclosure contain**, and today they contain the one combination, identity plus permission with no reason, that both the RCT and the vendor data point away from. Default-on is safe to ship only together with the opener change, and that change is small because the composition seam, the lead-source data and the toggle all exist. The second shift is that "sell better" and "stay honest" share a single mechanism in Calevate. The capability manifest that stops a script from promising a WhatsApp send is the same input that lets the close name two real slots. The facts rule that blocks invented prices is what makes a value line safe to add at all. Calevate's honesty machinery is also its sales machinery, and the build list below mostly connects pieces that already exist.

What stays unknown is the size of everything in India. Every effect size above comes from China, the US, B2B calls or inbound calls. So Calevate's own per-contact measurement is not optional polish. It is the only way the opener, the value line and the close become evidence rather than inference. And because a single client's traffic cannot power a booking test, pooled measurement across consenting clients is a product decision the founder has to make early.

## Proposed outbound warm-callback structure, turn by turn

This is described in English only. The founder writes every Telugu line, and no competitor wording is reused.

| Turn | Who | What happens | Guard |
|---|---|---|---|
| 1 | Agent | One breath: a greeting, the agent's name immediately followed by "AI assistant" for {business}, a generic reason keyed on lead source ("about the enquiry you made with us"), the recording notice folded in if that toggle is on, then **one** question. The question is either "is this {lead name}?" or "is now okay for two minutes?" (an A/B, decision 6). About 8–10 s. | ≤200 chars; no enquiry details yet; no offer |
| 2 | Callee | Confirms, or asks "who is this?", or declines | — |
| 3 | Agent | If confirmed: name what they enquired about in one line, then the first qualifying question. If "who is this?": repeat identity and reason in one line and stop. If busy: offer two call-back times only if call-backs are on, otherwise thank and close. If "no machine": acknowledge, offer a person only if configured, record the preference, close. | One question per turn |
| 4–7 | Both | Qualification, one detail per turn, confirming what the form already gave rather than re-asking. Real estate: area, configuration, budget band, timeline, who will come for the visit. Stop at about 4–6 questions. | No re-ask; short acknowledgements |
| 8 | Agent | Value line: one configured fact that answers what they said, one sentence, then move on. Skip it if no fact matches. | Facts only; no discount, scheme, superlative or urgency |
| 9 | Agent | Two-choice close: two real date-and-time options plus "or another time that suits you". Without slots, ask morning or evening and which day. | Slots from tool or configured windows only |
| 10 | Callee | Picks one, proposes another, or declines | If declined: one offer at most, then close (`let_go`) |
| 11 | Agent | One read-back: weekday, date, time, place, then the honest next step ("noted, the team will confirm" unless a tool confirmed it) | `ACTION_CLAIM_RULE`; weekday matches the IST date |
| 12 | Agent | "Anything else?", then one goodbye, with the memory notice if memory is on | Single close |

At any turn, "are you an AI?" or "is this recorded?" gets the platform's truthful answer, and "stop calling" goes to DNC before the next dispatch tick.

## Prioritised build list

| # | What | Why (evidence class) | Effort | Where it lands | Depends on |
|---|---|---|---|---|---|
| 1 | Rebuild the introduced outbound first turn: identity + AI + business + reason clause keyed on lead source + one question; direction-specific salutation | Bare disclosure first → 56% hang-ups (peer-reviewed RCT); reason ~2.1x, permission-only 0.9% (vendor data); question ending (vendor data, inbound) | M | `engine.py` `join_first_words`/`INTRODUCTION_SALUTATIONS`; `spoken_style.json` `outbound_introduced`; `compliance/disclosure.py`; `tests/ai_notice_introduction_test.py` | Founder Telugu and Hindi lines; native review; lead source in per-call values |
| 2 | Default the AI notice on for `outbound`/`both` at create; greeting-budget check at create; D-row | Founder decision 30 Oct (rememory 518ac2e3); Ipsos 67% (survey) | S | `agents/lifecycle.py:369-370`; `publishing.py` budget check; `models.py` comment; ROADMAP | #1 ships first or together |
| 3 | Fix `OPENING_CONTINUES_RULE` so "who is this?" gets identity and reason, then a stop | 30 Oct stacked-question defect (repo); one question per turn (vendor advice) | S | `engine.py:4491-4496`; budget test | Per-call budget |
| 4 | Capability manifest and lead sources in `ScriptBrief`; sixth owner question for the value fact | Writer is blind to configured actions (repo) | S–M | `workers/script_assist.py` | — |
| 5 | Script lint: promotional and urgency terms, unbacked action verbs, figures not in facts, >1 question per line, implied relationship, foreign names | TRAI mixing rule (secondary-legal); ban-lists in prompts prime phrases, so lint in code (vendor advice) | M | `agents/call_rules.py`; `script_assist.language_problems`; campaign launch check in `campaigns/service.py` | #4; founder term lists |
| 6 | Value step in the `call_leads` plan plus `TradeWords` value topics | No direct evidence of a lift (UNKNOWN); monologues lose (vendor data) | M | `agents/trade_playbooks.py`; `starters.py`; writer instruction | #5, so the lint guards it |
| 7 | Close step: two concrete date-time options + exit + single read-back with weekday | Date+time plan +4.2 pp, date-only not significant (peer-reviewed RCT) | M | `trade_playbooks.py` steps 4–5, `_CLOSE_INSTRUCTION`; HOW TO SPEAK if budget allows | #8 |
| 8 | Seven-day IST date table in THIS CALL; weekday-matches-date turn check; check ThinnestAI for a date function | In-context date arithmetic unreliable, tools fix it (peer-reviewed, indirect) | S–M | `engine.py` `TODAY_LINE`/`today_value`; `engine/thinnest.start_outbound_call`; `worker/engine_lookups.py`; `turn_checks.py` | Per-call budget trim |
| 9 | Capability-conditioned objection set (busy, price, timing, already bought, source, no machine) | Spam and complaint channel (vendor data, secondary-legal); acknowledge first (vendor data) | S–M | `trade_playbooks.py` objections; lint #5 | #4 |
| 10 | Deterministic sales and safety turn checks; advisory sales scorecard in the judge; all-k-pass for promise-safety | Judges weak cross-turn (vendor data); pass@k vs pass^k gap (industry study) | M | `agents/turn_checks.py`; `workers/agent_test_ai.py` `JUDGE_INSTRUCTION`; `agents/test_conversations.py` | — |
| 11 | Five new practice-caller personas | Untested paths (opinion) | S | `agent_test_ai.py` `GENERATE_INSTRUCTION` | — |
| 12 | Per-contact variant assignment, variant id on the call record, outcome metrics (early hang-up, DNC, AI questions, booking field) | One change at a time, regression on live traffic (vendor advice) | L | campaigns dispatch; engine adapter; workers extraction/analytics | ThinnestAI per-call greeting variable (UNKNOWN), or one agent per arm against the 2-agents-per-client-workspace cap (VENDOR-STATED, CLAUDE.md) |
| 13 | Optional per-agent "answer only from these facts" line | Approved 23 Oct, not found in code (repo) | S | `call_script.py` policies | — |

## Measurement plan

**Primary safety metric:** the share of answered outbound calls that end within 10 s of answer. This is a proxy for Luo's 5-seconds-after-disclosure measure, which needs turn timestamps that may not be available.

**Secondary metrics:**
- calls under 15 s;
- the share reaching the first qualifying answer;
- opt-out or DNC requests per answered call;
- complaints;
- "are you a robot?" questions per call;
- "prefers a person" flags.

**Primary business metric:** the visit or booking-agreed field from extraction. Later, the client-reported show-up rate where available.

### How the test runs

Randomize **per contact, not per campaign**, and stratify by client and trade. Pre-register each test and change one element at a time. Test the disclosure *variants*: today's composition against #1's reason-first composition, then the two question endings, then "AI" against a native gloss. Every arm discloses. A no-disclosure arm contradicts the decision and is the founder's call (decision 4).

### Sample sizes

Two-sided α=0.05 and 80% power:

- **10% → 15% early hang-up** needs about **690 answered calls per arm**.
- **10% → 13% booking** needs about **1,770 per arm**.
- **20% → 25% booking** needs about **1,090 per arm**.
- A Luo-sized gap, such as 10% → 50% early hang-up, shows within about **20–30 calls per arm**. A simple guardrail can therefore run from day one.

Hamming's rule of thumb of about 100 observations per arm ([Hamming](https://hamming.ai/blog/how-to-evaluate-voice-agents), vendor advice) detects only large effects. Booking tests will need pooled traffic across clients.

### What would make us reverse

The rule is placement, not disclosure.

- **Guardrail breach:** if, after 100 answered calls per variant, any disclosed variant's 10-second hang-up rate exceeds twice the pre-change baseline measured from disclosure-off calls, pause that variant. Then move the AI sentence to the second sentence of the first turn, still in the first turn. Turning disclosure off is not the response.
- **Value line:** if it shows no booking lift at the powered sample, and its opt-out rate rises by 2 points or more, drop the value step.
- **Two-choice close:** if it raises bookings but the client reports that show-ups fall, revisit the exit wording.
- **Correlation check:** compare advisory scorecard items with booking outcomes per call before promoting any of them to blocking.

## Decisions and questions for the founder

1. **Telugu and Hindi lines to write** (each needs native review):
   - the outbound introduced salutation (casual or formal, now that disclosure is on);
   - the AI-identity sentence, reviewed;
   - the reason clause in one form per lead source (enquiry form, earlier visit or call, existing customer);
   - the recording notice folded into the same sentence;
   - the turn-1 question in both variants (name check, time check);
   - the "who is this?" reply;
   - the reply to "I don't want to talk to a machine", with and without a hand-over;
   - the value-line bridge;
   - the two-choice close frame with its exit;
   - the read-back frame with weekday;
   - the busy call-back offer;
   - the promotional and urgency term lists for the lint.
2. Flip the AI notice on for **existing** outbound agents, or only for new ones, as D-669 did?
3. Default the AI notice on for **inbound** too? Upfirst's observational data points that way; it is not established.
4. May any test arm run **without** volunteered disclosure? The recommendation is no: test placement variants only.
5. Should the **recording notice** also default on for outbound, folded into the same sentence?
6. Which turn-1 question is the default: name check or time check? Or should both run as the first A/B?
7. Approve the value-line rule (one configured fact, matched to what the lead said, after qualification), and send the "responsive fact is not promotional" reading and the RERA-number question to counsel.
8. Allow social proof only when the owner configured a specific, true statement, or never?
9. Without a scheduling tool, should the close ask the preference, or propose two windows from configured hours?
10. Add the sixth owner question for the value fact?
11. Keep the sales scorecard advisory, never a failing test, until it is shown to correlate with bookings?
12. Approve pooled, consented A/B measurement across clients, and the client-agreement wording it needs?
13. Assign a D-number to the 30 Oct disclosure decision and record the opener change with it.
