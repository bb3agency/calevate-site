# Call scripts: Calevate against Outpero — 23 October 2026

**What this is.** It compares the script Outpero's AI wrote for the founder's test agent "Gayatri"
(Madhav Real Estate, bulk follow-up, Telugu) with how Calevate builds, stores, composes, writes and
tests scripts today (current main, read from the code). Outpero's side comes from the founder's
screenshots and Outpero's own "Copy script" JSON export (`bundle_version: 2`), both 22–23 Oct 2026.
Everything about how Outpero builds it internally is **inferred, not seen**.

Related: `outpero-onboarding-2026-10-22.md`, `onboarding-vs-outpero-2026-10-23.md` (D-855),
`telugu-register-2026-10-21.md`, `docs/PROMPT-GUIDE.md`.

---

## 1. Outpero's script, as exported

- **`first_response`:** "హలో అండి, {{lead_name}} తో మాట్లాడుతున్నానా?" — spoken word for word when the
  call connects. The business, the AI disclosure and the reason come in the first section.
- **Six `sections`,** each with `section_key`, `label`, `order`, `enabled`, `node_type: "llm"`,
  `edges` (`to_key` + a plain-language `condition`) and one `prompt`:
  1. Reason For Call & Check Interest → qualify (if still interested) / not_interested.
  2. Qualify Area & Budget → book_site_visit.
  3. Book Site Visit → close.
  4. Handle Not Interested → close.
  5. Close (no edges).
  6. FAQs: "Answer ONLY from what's written here", with sample Q/A left as e.g.
- **Each `prompt`** has the same shape:
  - English instructions;
  - one behaviour rule set per step ("Ask ONE thing at a time", "React to each answer", "Use any
    pre-call info you have — do not re-ask", "Only mention WhatsApp details once per call", "Never
    force the call to end");
  - the objections it should handle naturally ("busy", "call later", "how did you get my number",
    "just WhatsApp me");
  - **one example line in code-mixed spoken Telugu, with English words in Latin letters**, e.g.
    "మీరింకా హైదరాబాద్ లో property కోసం చూస్తున్నారా, లేదా already settle అయ్యారా అండి?".
- **The founder's three onboarding answers are dropped in verbatim:** the business name in Telugu
  letters, the five property types, and Hyderabad.
- **`variables`: one list for both kinds.**
  - `source: pre` (lead_name, phone) or `capture` (area, budget, property_type, interest_level,
    site_visit_time, future_updates_opt_in).
  - Each has `extract_hint`, `value_type` (all `text` here), `choices` (all null), `required`, and
    `is_phone` / `is_lead_name` / `is_headline`.
- **In the editor:**
  - a "Telugu enhance" tick box (on);
  - a 40,000-character budget (2,398 used);
  - a 1–5 "how strictly it follows" slider at 2 (Flexible);
  - "When the call ends": a built-in rule plus the owner's extra rules (here written for them);
  - Copy/paste of the script JSON;
  - Swara, which rewrites the whole script from a spoken or typed change.
- **Inference, not verified (founder, 23 Oct 2026).** The script was written by AI from the template
  brief plus three answers, so Outpero probably keeps a per-trade writer prompt or skeleton. The
  identical five-step shape, the template-style branch conditions and the uniform
  instruction-plus-example pattern fit that. The quality of the call itself (natural Telugu, the
  handling of half answers, barge-in) depends on their in-call system prompt, model and voice stack,
  which we cannot see. Their stack was REPORTED in August as Sarvam + Cartesia
  (`outpero-teardown-aug2026.md`). **Which LLM runs their calls is UNKNOWN.**

## 2. Calevate today (from the code; file:line in the conversation's code map)

**Already equivalent or richer:**
- **The opening line,** with a greeting budget that counts the notices (D-846).
- **Up to 12 sections,** each with:
  - English `instruction` and a spoken `sounds_like` example (≤200 characters);
  - `mode` guide/say;
  - `branches {when, target}` and `otherwise`, with targets checked; special targets `end`,
    `hand_over` and `call_back`;
  - `collect` per step.
- **A canvas view** that draws the branches.
- **Script v2 extras:** business line, identity, goal, outbound purpose, style (tone, address form,
  code_mix light/natural/heavy, sample phrases, pronunciations), objections, policies, ending, an
  example call.
- **Typed capture fields:** text, number, bool, enum, date, with reason and required, plus six core
  fields.
- **Autosaved draft and versions:** a separate publish, full version history with restore and undo,
  and A/B experiments.
- **Size limits:** a per-layer size meter, and a publish refused when over the limit.
- **Locked platform layers:** truthful answers (hard rule 5), confidentiality (D-674), the
  client-text fence, HOW TO SPEAK, the "Hello never switches language" rule (D-849).
- **One rule list** (`call_rules.py`) shared by the writer, judge, improver and in-call prompt;
  AI-written output checked in code (no Telugu script in instructions, no textbook words, no vendor
  names) with one repair round.
- **Testing:** practice tests with a judge from a different model family, and auto-improve (D-844,
  D-845); a register evaluation tool (D-837).
- **Telugu register guidance is always on** for every Telugu agent. There is no switch to forget, and
  the founder agrees ("our Telugu should already be enhanced").

**Missing compared with Outpero:**
1. **Strictness:** 2 levels (flexible/strict), not 1–5.
2. **No per-section on/off.**
3. **No copy/paste of the script as JSON** (import or export).
4. **Pip takes typed changes only,** not spoken ones.
5. **Pre-call variables are untyped** (`{key, label, example}`) and live apart from capture fields.
   Outpero keeps one list with `source pre|capture`, `value_type`, `choices`, phone and lead-name
   flags.
6. **FAQs are not owned by the script.** On save they move into business-wide pinned facts, and the
   v2 prompt tells the agent to search knowledge first. Outpero fences: "answer ONLY from what's
   written here".
7. **No per-trade writer skeleton.** Starters are static per trade, and the AI writer (`script_assist`)
   works from a brief plus five owner questions with no trade-specific step shape. D-855 is wiring
   brief → script now.
8. **Branches are not native on ThinnestAI.** They exist in our data, but ThinnestAI's `steps` take
   free-text `branches {when, action}` (`thinnest-findings/.../update-agent.md:1122-1158`), so jumps
   are sentences the model may or may not follow. This is the same for Outpero as far as we know:
   their edges are plain-language conditions too.

**Measured, not guessed.** On our production prompt, 36% of Telugu replies contain a textbook word,
mostly మరియు and వివరాలు (`telugu-register-2026-10-21.md`). No prompt variant beat it. The founder
judged Outpero's call natural throughout. **That is one call, not a measurement, and their transcript
was not scored with our textbook-word matcher.**

## 3. What could explain the gap (hypotheses, each testable)

| # | Hypothesis | How to test it cheaply |
|---|---|---|
| H1 | Their script is better (per-trade skeleton, an explicit example line per step, "one thing at a time" rules) | Import their exact exported script into a Calevate agent (our v2 holds every part of it) and run practice tests and a register evaluation against our own script for the same business |
| H2 | Their in-call model writes Telugu better than ours (`gemini-3.1-flash-lite` on ThinnestAI) | Same script, different model, on the register evaluation. Which models ThinnestAI's own-model mode accepts must be read from their docs first |
| H3 | Our composed prompt is too big or busy for a "lite" model (many platform layers) | `register_chat_eval` variants with leaner layers; the D-837 tooling exists |
| H4 | Their voice stack smooths the words (a TTS that reads loanwords well) | Not testable from our side without their stack; note only |

The founder's experience suggests H1 and H2 matter most. **None is proven.**

## 4. Questions for the founder

Asked in the conversation of 23 Oct 2026. The founder's answers, the same day:

1. **No test of Outpero's script inside Calevate.** We take inspiration from Outpero and build
   something better; we do not run their output.
2. **The in-call model stays `gemini-3.1-flash-lite`.** The founder states that Outpero runs Gemini
   2.5 Flash and Flash Lite. That is REPORTED by the founder; their in-call model was not seen here.
   H2 is therefore set aside by decision, not by measurement.
3. **A step plan per trade for the AI script writer, for EVERY client domain,** not only real estate:
   all trades in `agents/starters.TRADES`, including custom. The aim is the best performance.
4. **Strictness stays at two levels.**
5. **No per-step on/off switch.**
6. **Copy and paste of the script as text (JSON): yes.**
7. **Spoken script changes to Pip, through the D-855 recorder: yes.**
8. **These script changes wait until D-855 is merged.**

Not answered yet: Q8 (typed lead-list variables in one list with the call fields) and Q9 (FAQ
"answer only from these" line).
