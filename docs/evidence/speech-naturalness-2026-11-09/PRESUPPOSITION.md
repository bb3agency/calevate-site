# Presupposition and split case markers: Rytu Khata call of 9 Nov 2026

What the founder saw on production (agent Varsha, te-IN, outbound):

- (a) "మీరు ఇంకా ఈ యాప్ ను ఇన్స్టాల్ చేసుకున్నారా?" (his paste began with a stray "a");
- (b) "మీరు ఇప్పటికే ఈ యాప్ ను వాడుతున్నారు కదా, దేని కోసం ఎక్కువగా వాడుతున్నారు?" ("you already
  use the app, right? what do you use it for most?"), said to a caller who had just said they
  only remembered registering.

Two defect classes: a case marker written apart from its noun ("యాప్ ను"), and a line that
takes the caller's state as given.

## 1. Research (read 9 Nov 2026)

| Finding | Source | Class |
| - | - | - |
| Telugu print joins a case marker to a virama-final English loanword, with a zero-width non-joiner (U+200C) after the virama: 453 such joins and 2 written apart (both BBC) on the five pages scanned | eenadu.net/telugu-news/technology (2), sakshi.com/tech (195), telugu.news18.com/tech (164), bbc.com/telugu (80 joined, 2 split), blog.whatsapp.com/introducing-message-translations?lang=te (12, e.g. "యాప్‌లు"); byte counts of `్` + U+200C + ను/లో/కి/తో/లు/ని/కు | Measured on the pages |
| ZWNJ after a virama asks the renderer to stop the conjunct, leaving a visible virama; how a shaper treats it differs by engine | en.wikipedia.org/wiki/Zero-width_non-joiner; HarfBuzz commit "Disable automatic ZWNJ handling for Indic features" | 3P |
| A Telugu loanword corpus standardised loanword spelling but says morpheme joining "is expected to vary" | catalog.ldc.upenn.edu/docs/LDC2018S16/LSP_303_final.pdf (search snippet) | 3P, not read in full |
| Standard Hindi writes a case marker apart from a noun and joined to a pronoun ("कारक चिह्न सभी प्रकार के संज्ञा शब्दों में प्रातिपदिक से पृथक् लिखे जाएँ") | Central Hindi Directorate rule as reproduced at bharatdiscovery.org/india/वर्तनी_(हिंदी); the Directorate's own PDF (chd.education.gov.in, devanagarilipiandhindivartanikamankikaran.pdf) is over 10 MB and was not read | REPORTED (secondary copy of a primary rule) |
| How Cartesia or ThinnestAI read U+200C | No Cartesia or ThinnestAI page mentions it | UNKNOWN |
| Ask a question before relying on its answer: "Don't ask the user a question if you're not prepared to handle their answer"; "Prompt the user with only a single question at a time" | developers.google.com/assistant/conversation-design/questions | VVD (Google's guide) |
| Conversation rests on the cooperative principle; the maxim of Quality is "the truth of what we say" | developers.google.com/assistant/conversation-design/learn-about-conversation | VVD |
| "Use what your customer has already said in the conversation at hand" | developer.amazon.com/en-US/alexa/alexa-haus/design-principles/be-natural (search snippet) | 3P, snippet only |
| About 21% of unanswerable questions in Natural Questions rest on "unverifiable presuppositions"; users preferred answers that name the failed presupposition | arxiv.org/abs/2101.00391 (Kim et al., ACL 2021) | Academic |
| Examples steer the output's format, tone and structure; make them diverse "so Claude doesn't pick up unintended patterns" | platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices | VVD (Anthropic) |
| The model "strongly closely follows sample phrases" | developers.openai.com/cookbook/examples/realtime_prompting_guide (RESEARCH.md P9) | 3P |

What this decides:

- The joined form is right for Telugu, and print joins with ZWNJ. Whether the voice reads
  "యాప్‌ను" (ZWNJ) differently from "యాప్ను" (conjunct) is UNKNOWN; an ear test decides it.
- "A suffix ... joins its word" was wrong for Hindi nouns. The rule now joins "as the
  language's print does", which is right for both.
- A step that needs the caller to have done something is reached only after asking it, and
  the agent branches on the answer.

## 2. Root cause

**(b) is the step's own line, reached by every caller.**

- `calevate_shared/call_script._stage_detail` compiles a step as `<instruction> It sounds like:
  "<sounds_like>"`, and the in-call model copies that line. The founder's paste has the splits
  "యాప్ ను" and "దేని కోసం". On the 9 Nov audit sample the model wrote "దేనికోసం" joined in its
  own words, which points at a copied line. This is UNVERIFIED until query 3a runs.
- `apps/api/agents/script_lint.order_problems` (6 Nov) flagged a usage question only on a
  path that also helps the caller set something up. A script with no install step, or with a
  way out for "installed" or "registered", passed. Install is not use: the caller had
  registered and never used the app.
- In-call, `engine.CALL_REASON_RULE` covered only "enquired or showed interest". Nothing said
  that a step's line is an example and not a fact about the person.
- No practice check looked for a presuming line.

**(a)'s split is the same kind of line.** "యాప్ ను" matches the split pattern in our own
founder-approved data (AUDIT.md §4: "సిక్స్ కి" in `spoken_style.json` prompt_examples). The
written-form rule has no Telugu example (`written_form` is "").

**(a)'s stray "a"** is UNVERIFIED. Our code adds no Latin letter to a spoken line:
`engine/thinnest.parse_transcript` stores ThinnestAI's text stripped and unprefixed. Since
d904f2acf, `script_assist.language_problems` refuses a Latin word in every spoken field that
a writer produces, but a line written before that is not re-checked. Two causes remain open:

- the stored example line or transcript text starts with a Latin letter (queries 3a and 3b
  answer this);
- the paste picked up the end of the speaker label. The call page prints the agent's name,
  "Varsha", directly above the bubble, and the name ends in "a" (`TranscriptCard.tsx`,
  `speakerName`).

## 3. Production queries (read-only, flags only)

3a. Varsha's live script: steps, ways out, and which lines hold the words of (a) and (b).

```
sudo -u postgres psql -d calevate -c "WITH a AS (SELECT ag.id, ag.live_prompt_id FROM agents ag JOIN organizations o ON o.id = ag.tenant_id WHERE o.name ILIKE '%rytu%' AND ag.name ILIKE 'varsha%' AND ag.deleted_at IS NULL), pv AS (SELECT p.version, p.structured_script AS s FROM a JOIN prompt_versions p ON p.id = a.live_prompt_id) SELECT pv.version, st.ord AS step, st.v->>'id' AS id, st.v->>'name' AS name, st.v->>'mode' AS mode, (SELECT string_agg((b->>'target') || ' when ' || (b->>'when'), ' | ') FROM jsonb_array_elements(coalesce(st.v->'branches', '[]'::jsonb)) b) AS ways_out, coalesce(nullif(st.v->>'otherwise', ''), '(next step)') AS otherwise, st.v->>'instruction' AS instruction, (st.v->>'sounds_like') LIKE '%చేసుకున్నారా%' AS line_a, (st.v->>'sounds_like') LIKE '%వాడుతున్నారు కదా%' AS line_b, (st.v->>'sounds_like') ~ 'యాప్ (ను|లో|కి|తో)' AS split_app, (st.v->>'sounds_like') ~ '[A-Za-z]' AS latin_any, (st.v->>'sounds_like') ~ '^\s*[A-Za-z]' AS latin_first, (pv.s->>'opening_line') ~ '^\s*[A-Za-z]' AS opening_latin_first FROM pv, jsonb_array_elements(pv.s->'stages') WITH ORDINALITY AS st(v, ord) ORDER BY st.ord;"
```

3b. The 9 Nov call turns that hold (a) or (b), as flags.

```
sudo -u postgres psql -d calevate -c "SELECT c.id AS call_id, c.started_at AT TIME ZONE 'Asia/Kolkata' AS started_ist, t.idx, t.speaker, t.text ~ '^\s*[A-Za-z]' AS starts_latin, t.text LIKE '%చేసుకున్నారా%' AS has_a, t.text LIKE '%వాడుతున్నారు కదా%' AS has_b, t.text LIKE '%యాప్ ను%' AS split_app_nu FROM calls c JOIN agents ag ON ag.id = c.agent_id JOIN organizations o ON o.id = c.tenant_id JOIN transcript_turns t ON t.call_id = c.id WHERE o.name ILIKE '%rytu%' AND ag.name ILIKE 'varsha%' AND c.started_at >= '2026-11-09 00:00+05:30' AND (t.text LIKE '%చేసుకున్నారా%' OR t.text LIKE '%వాడుతున్నారు కదా%') ORDER BY c.started_at, t.idx;"
```

3c. For the 20:32 call: whether Varsha is a screen agent, which steps greet or introduce, and
which lines open with the repeated reactions or hold English letters or the web address.

```
sudo -u postgres psql -d calevate -c "WITH a AS (SELECT ag.id, ag.caller_has_screen, ag.live_prompt_id FROM agents ag JOIN organizations o ON o.id = ag.tenant_id WHERE o.name ILIKE '%rytu%' AND ag.name ILIKE 'varsha%' AND ag.deleted_at IS NULL) SELECT a.caller_has_screen, (p.structured_script->>'opening_line') LIKE '%{{lead_name}}%' AS opening_has_name, st.ord AS step, st.v->>'name' AS name, (st.v->>'instruction') ~* 'greet|introduce|identify yourself|can talk now|good time' AS step_redoes_opening, (st.v->>'sounds_like') LIKE 'సరే అండి%' AS line_opens_sare, (st.v->>'sounds_like') LIKE 'చాలా మంచిది%' AS line_opens_chala, (st.v->>'sounds_like') ~ '[A-Za-z]' AS line_latin, (st.v->>'sounds_like' || ' ' || (st.v->>'instruction')) ~* 'www|\.com|డాట్' AS has_web_address FROM a JOIN prompt_versions p ON p.id = a.live_prompt_id, jsonb_array_elements(p.structured_script->'stages') WITH ORDINALITY AS st(v, ord) ORDER BY st.ord;"
```

How to read the results:

- **3a confirms the hypothesis** when a step has `line_b = t`, its instruction asks what they
  use the app for, and every way into it is "(next step)", an otherwise, or a condition about
  installing or registering.
- **The stray "a" came from us** if `latin_first = t` on either query. Otherwise it came from
  the paste.

- **3c**: `caller_has_screen = t` confirms that the screen agents' rule spelled the address.
  `step_redoes_opening = t` on step 1 confirms the double introduction. `line_opens_sare` or
  `line_opens_chala` on two or more steps confirms that the repeated reaction was copied from
  the step lines.

## 3d. The founder's call of 9 Nov 2026, 20:32: root causes

1. **Double introduction.** The opening (said by the engine, word for word) greets, names
   Varsha and Rytu Khata and asks if now suits. Step 1's instruction says to greet the lead
   by name, identify yourself, state why, and ask if they can talk now. START OF THE CALL
   already said "Never greet again in any turn ... repeat it or its names, or re-ask if now
   suits" (`engine.OPENING_CONTINUES_RULE`), but no rule named a step. The model follows the
   step it is on.
   - `script_lint.repeated_line_problems` compares lines only (a 0.6 word overlap), never an
     instruction, so the step was flagged at most for its line, which the owner left.
2. **Web address spelled letter by letter.** This is our rule. `engine.screen_steps_bullet`
   (D-906) said "Spell a web address one letter at a time, each by its English letter name".
   It is composed only for an agent with `caller_has_screen`; whether Varsha has it is
   UNVERIFIED until query 3c runs. If not, the address came from the step lines or the
   knowledge. The digit-by-digit rule names numbers and codes only, so it is not the cause.
   - Research (read 9 Nov 2026): Retell's guide says "Read recognizable words in website
     addresses normally, spell out initials, and say "dot" for periods" (nklaundry.com
     becomes "en kay laundry dot com"; docs.retellai.com/build/prompt-situation-guide).
   - Phonic's agents spell only "when confirming something easily misheard"
     (docs.phonic.ai prompting guide).
   - Vapi's support suggests a spoken "w w w dot", so leaving out www is our choice, not a
     consensus. The founder's ear decides.
3. **"Android" and "iPhone" in English letters.** The te-IN register line in every prompt says
   "every word in Telugu letters, English words too" (`spoken_style.json:11`). Two causes are
   possible, and the second is UNVERIFIED until 3c's `line_latin` answers it:
   - BUSINESS FACTS says "Say names as your facts give them, never translated"
     (`engine._NAMES_RULE`), which can read as keeping a brand in English letters;
   - the step's line holds the English words, and the model copies it.

   Writers have refused English letters in every spoken field since d904f2acf, but the
   readiness card never checked an owner's existing lines, and no practice check looked for
   English letters inside a Telugu reply (`turn_checks._foreign_letter` checks other Indian
   and non-Indian scripts, not Latin).
4. **The same reaction every turn.** `thinnest_call_instructions` is on in production (founder,
   9 Nov 2026), so the engine's default call rules are not read. The causes are ours:
   - every te-IN prompt says "Fillers, lightly: సరే అండి, హా, అవునా, కదా"
     (`spoken_style.register_guidance`, `spoken_style.json:603`, `PROMPT_FILLERS = 4`), and
     the first filler named is the repeated opener;
   - the writer's examples, which Pip's script writer reads, open with "సరే అండి" five times
     (`spoken_style.json:24, 72, 82, 156, 174`, and the punctuation example at `:711`), so
     Pip-written step lines open alike, which 3c's `line_opens_*` answers;
   - "never the same way twice" can be read as "not twice in a row".

   ThinnestAI's always-added speaking rules (about 1,876 characters, D-850) are not shared,
   so whether they ask for an acknowledgement is UNKNOWN.
5. **Long turns.** HOW TO SPEAK already says "one or two short sentences, then wait", and
   ThinnestAI's guide says "Two sentences is plenty" (`how-your-agent-sounds.md:59-72`).
   - Turn 4 was long because step 1 bundled a greeting, an introduction, why and a question
     (cause 1).
   - Turn 10 was long because of the spelled address (cause 2).
   - Turn 14's text was not read here.
   - No real-call check measured length: `too_long` was a practice note only.

The opening has no `{{lead_name}}`, because Pip rewrote it. This is noted only; it is
script-level.

## 3e. What changed for the 20:32 call

- `OPENING_CONTINUES_RULE` ends: "A step says to greet, say who you are or ask if now suits?
  That is done: do the rest."
- `script_lint.opening_redone_problems` (in `flow_problems`, so on the readiness card, in
  "Fix them first" and in the writer's repair round) finds a step that greets, introduces or
  asks if now suits in a script with an opening. `SCRIPT_FLOW_RULE` tells every writer that
  the first stage starts from what comes after the opening.
- `screen_steps_bullet`: "Say a web address as it reads, no www: a word as a word, initials
  each by its English letter name ..., "dot" as a word. Spell a word by letters only if they
  cannot find it, or send the link if a tool can."
- English letters:
  - `script_lint.script_problems` runs `latin_word_problem` on every spoken line in the
    call's own letters that mixes English letters in, with the agent's language
    (`LintContext.language`, set by `capability_manifest.lint_context_for`). It leaves out the
    business's and agent's names, and a line wholly in English;
  - `turn_checks.turn_problems(names=)` notes English letters in a reply that is in the
    call's own letters, as `foreign_script`;
  - practice runs pass the business name (`RuleContext.names`). Real calls do not, because
    the name is not known there.
- Same reaction:
  - HOW TO SPEAK says "never the same way twice in a call";
  - `script_lint.same_opener_problems` finds step lines that open with the same short
    reaction;
  - `SCRIPT_FLOW_RULE` says no two lines open alike;
  - the real-call page now names `same_opening` and `too_long` (`call_mistakes.LESSONS`).
- First words: when a repeat introduction is dropped, `engine._PERSON_NAME_FIELD` carries the
  name field and one word after it only when a break follows that word. "Hello {{lead_name}}
  this is Varsha." no longer carries "{{lead_name}} this," (audit X6).
- Per call 7,719 / 6,844 (caps raised by 6 for "in a call"). The founder decides whether to
  change the first filler or the five example lines, which are Telugu text.

## 4. What changed (code)

- `script_lint.order_problems` also finds a step that needs the caller to use the thing
  (`_presumes_use`: an experience question, or an instruction such as "already using").
  It finds that step when the call reaches it from the first step along any way out except
  one whose condition says they use it (`_reached_unasked`; "installed", "has" and
  "registered" do not count, and a negated condition does not count). A step passes if it
  asks first or goes on only for users (`_gates_itself`), which is the only gate a linear new
  draft can have.
- The finding reaches the readiness card, "Fix them first" (its ways out are taken from the
  writer, as for every order problem) and the writer's repair round (`shape_problems`).
- `call_rules.SCRIPT_FLOW_RULE`: nothing about the caller is taken as given. A step that needs
  it is reached through a way out whose condition says so, after a question, or it asks first.
  Its line asks rather than asserts. Having, installing or registering is not using.
- The rule reaches every writer: draft, convert by `writer_rules`, edit, Pip's change, the
  improver.
- `script_proposals.MAIN_TASK_CHANGE` names the rule. The opening writers'
  `OPENING_WRITER_INSTRUCTION` and `PLACED_TASK` add "has or uses something".
- `call_rules` facts judge: the practice judge also fails a reply that takes the caller's
  state as given.
- `engine.CALL_REASON_RULE` (placed calls, START OF THE CALL) now reads: "Never say they
  enquired, showed interest, have or use something unless they or THIS CALL said so; a
  step's "sounds like" is only an example."
- `turn_checks` kind `presumed_state` is in `JOB_KINDS` and `SCRIPT_KINDS`. A practice reply
  that says most of the line of a step that `order_problems` names fails the test, with the
  fix sent to the script (`script_step`), not to the platform. The lines come from
  `script_lint.presumed_lines` through `AgentBrief.presumed` and `RuleContext.presumed`. No
  word list is involved.
- `spoken_guard.WRITTEN_FORM_RULE`: "Join a suffix, particle or vowel to its word as the
  language's print does."

## 5. Prompt sizes (`tests/agent_prompt_budget_test.py` reference)

| | Before | After | Cap before → after |
| - | - | - | - |
| Three languages | 7,707 | 7,719 | 7,713 → 7,719 |
| One language | 6,832 | 6,844 | 6,838 → 6,844 |
| Full v2 reference (`agent_intelligence_test`) | 8,249 | 8,345 | 8,250 → 8,350 |
| START OF THE CALL less the quoted opening ("both" agent) | ≤919 | 1,077 | <920 → <1,080 |

Where the growth came from:

- The written-form rule: +2.
- "In a call" on the reaction rule: +10. The only cap raise on the per-call caps is the 6 this
  needed.
- CALL_REASON_RULE: +72, placed calls only.
- The step-redoes-the-opening sentence: +86, every agent with an opening.

The last two are in START OF THE CALL, which the per-call reference does not carry.

## 6. What only the founder can write (Telugu)

1. te-IN `written_form` (`spoken_style.json`): one joined line, for example "app" with its
   object marker. Say whether it is written with ZWNJ after the virama, as Telugu print does,
   or as a conjunct.
2. Rewrite the founder-approved `prompt_examples` turn "సిక్స్ కి" joined (both turns).
3. Rewrite the writer examples with a split marker: `spoken_style.json` lines 56, 78, 104,
   120, 130, 162. Also the nudge "లైన్ లో" (`spoken_lines.json:41`) and "నంబర్ కి" (`:453`).
4. Whether to add to `call_words.json` a Telugu split-marker list and the "right?" tag of an
   assertion about the caller, so the turn checks can catch them in any reply and not only
   in a script's own lines.
5. Ear test: one Studio and one Clear voice saying the same line with ZWNJ, joined as a
   conjunct, and split.
6. hi-IN `written_form`: a line with a postposition written apart from its noun, to confirm
   the Hindi reading of the new rule.
7. The te-IN fillers: the first filler every prompt names is the repeated "OK" reaction.
   Decide whether to move it, and whether to rewrite the five writer examples that open with
   it.

## 7. Pip prompt for Varsha's script (for the founder to send)

> Fix Varsha's script, keeping its opening line and close as they are:
>
> 1. Step 1 must not greet, say who is calling or ask if now is a good time, because the
>    opening already did. Start it with why we are calling.
> 2. Never take for granted that the person uses the app. Add a step that asks, as a
>    question, whether they have started using the Rytu Khata app. If they say they use it,
>    go to the step that asks what they use it for most. If they have not used it, only
>    registered, or have not installed it, go to the step that helps them install it or
>    shows the first thing to do. Never ask those callers what they use it for or how they
>    like it.
> 3. Rewrite every line that says they already use or have the app so it asks instead.
> 4. No two step lines start with the same words, and no line starts with a stock reaction.
>    Open each with its own point.
> 5. Every word in Telugu letters, phone and app names too. Each case ending and question
>    ending joined to its word, with no space between an English word and its Telugu ending.
> 6. Say the website as words with "dot com", or offer to send the link. Never spell it letter
>    by letter.
