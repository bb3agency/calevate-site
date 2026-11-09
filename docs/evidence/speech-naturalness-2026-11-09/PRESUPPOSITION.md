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

How to read the results:

- **3a confirms the hypothesis** when a step has `line_b = t`, its instruction asks what they
  use the app for, and every way into it is "(next step)", an otherwise, or a condition about
  installing or registering.
- **The stray "a" came from us** if `latin_first = t` on either query. Otherwise it came from
  the paste.

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

| | Before | After | Cap |
| - | - | - | - |
| Three languages | 7,707 | 7,712 | 7,713 |
| One language | 6,832 | 6,837 | 6,838 |

The CALL_REASON_RULE growth sits in START OF THE CALL, which only placed-call agents carry.

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
