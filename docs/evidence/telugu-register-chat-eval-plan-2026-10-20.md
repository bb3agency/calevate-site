# Telugu register on the real stack: the test-chat eval plan (20 Oct 2026, D-837)

**Founder's goal (20 Oct 2026):** fix textbook Telugu with prompting only, on
`gemini-3.1-flash-lite`, with no extra server ever (rememory decisions c79138bf, 4bea603d).

**Tool:** `scripts/register_chat_eval.py`. **Status:** built and tested offline; **no reply has
been measured yet**. The operator runs it on the VPS.

## 1. What is measured, and why

Every earlier number came from `scripts/register_eval` (D-829, D-830). That harness sends
**our copy** of the prompt straight to Gemini on our Google key. A real conversation does not
run that prompt. ThinnestAI composes its own:

- its rules come first, and our instructions follow in a fenced block;
- the vendor gave the exact wording and sizes, about 4,700 characters per call (§18 of
  `docs/vendor/thinnest-replies-2026-10-12.md`, VENDOR-STATED, 19 Oct 2026);
- ThinnestAI makes the model call and handles the history itself.

So the earlier screen measured a prompt no caller ever reaches.

This eval measures on ThinnestAI's stack. It works like this:

- **One copy per variant.** For each variant it creates a temporary copy of a named Telugu
  agent in our developer workspace, through the adapter's own `create_agent`.
- **Only the instructions differ.** Every other field of the body is what a publish sends,
  and a test checks that.
- **Same callers for every copy.** It plays one fixed set of Telugu practice callers to every
  copy through ThinnestAI's test chat.
- **Scoring.** Each reply is scored with `spoken_guard.textbook_words(reply, "te-IN")`, the
  matcher the agent tests use.

**What test chat is, and is not (UNKNOWN until measured against a call):**

- **Website chat, not a phone call.** Test chat talks to the agent "through its website chat —
  the same prompt, model, knowledge, actions, limits and billing as the console's Playground"
  (`thinnest-findings/mirror/snapshots/2026-10-18/pages/api-reference/agents/test-chat.md:7`).
  - The vendor's core rule says the agent is "talking to a member of the public on a
    business's website" (§18).
  - Whether the chat composition carries the 1,876-character **speaking rules** that a call
    carries is not stated anywhere we have read.
- **Thinking level.** "A chat reply keeps the model's default" thinking level, while a call
  sends `minimal` (§18, VENDOR-STATED). A reply's word choice may differ between the two.
- **What the copies leave out:**
  - no hand-over;
  - none of our in-call actions;
  - the client's knowledge only as the source agent's whole [T0 FACTS] block, attached as one
    "Business facts" document. The published knowledge sources are not attached one by one.

So this is closer to a real call than `register_eval`, but it is still not a call.

## 2. What is already known (cited, not re-measured)

| Measurement | Source | Telugu textbook-word share |
|---|---|---|
| 8 real Telugu calls, 10–11 Oct (older prompt and model) | rememory 60903c48 | 26 of 57 agent turns (about 45%) |
| D-829 `register_eval`, Raghava retail, 5 runs, 100 replies | rememory 4bea603d | current 46%; examples 43%; positive and late: no difference |
| D-830 screen, 2 runs, 40 replies per form, ₹17.63 | rememory 61f2eb2d | current 42.5%; pack-en 40.0%; pack-en-pairs 62.5% (+20, interval [-1.4, +41.4]); pack-en-noavoid 52.5%; pack-native 47.5%; pack-native-pairs 50.0%; pack-native-noavoid 37.5% |
| Hindi, D-829 | rememory 4bea603d | 22% → 10% with examples (significant) |
| Founder's first Gemini call, 20 Oct, 19:25 IST | rememory 2c4af2e9 | "almost gone", but మరియు, సహజంగా, తెలుసుకోవాలనుకుంటున్నారా and the greeting's మీకు ఎలా సహాయపడగలను remained |

**Earlier conclusion (61f2eb2d).** On `register_eval`, no rule, positive wording, example set,
placement, instruction language or avoid-list form moved the Telugu share. The packs only
swapped one textbook word for another: వివరాలు went down, సమాచారం went up, and మరియు stayed.

**Our own note on that conclusion:** it is a finding about our copy of the prompt, sent
directly to Gemini.

## 3. Hypotheses

1. **H1.** Composition matters. ThinnestAI's English wrapper before our text may shift the
   register, so A's rate on test chat is not A's rate on `register_eval`.
2. **H2.** Naming a word primes it (Mann et al., arXiv:2511.12381, cited in D-829). Removing
   every `not "X" but "Y"` pair (B) lowers the share.
3. **H3.** A positive list of the English words callers mix in (C) moves the model to code-mixed
   Telugu, which is how people actually speak (Dutta and Rajeswari 2015, cited in
   `spoken_style.json`).
4. **H4.** Complete example calls in natural Telugu (D) anchor the register better than short
   exchanges. Few-shot examples worked for Hindi (D-829).
5. **H5.** B, C and D together (E) do better than any one of them.

## 4. The variants

Each variant changes only what the model reads, through `engine_prompt_layers`. The
confidentiality rule (D-674) and the truthful-answer block (hard rule 5) are never touched, and a
test proves both survive in every variant, recorded or not.

| Key | Change |
|---|---|
| A | The production prompt, `compose_engine_prompt` unchanged. |
| B | No ban lists. Two changes: the SPOKEN REGISTER `Spoken words: not "X" but "Y"` sentence is removed from every language line, and HOW TO SPEAK's bullet becomes `Match the caller's language; never "uhm".` The register line, the fillers and the approved examples stay. The client's own script is the owner's and is not edited; `--dry-run` counts its lines that hold a list word. |
| C | One positive line appended to SPOKEN REGISTER. It names the English words from the spoken side of `spoken_style.json`'s Telugu `word_swaps`, said in English letters inside Telugu sentences (the D-744 rule), and the everyday spoken forms written wholly in Telugu from the same list. |
| D | The script's [EXAMPLE CALL] section is replaced by two complete calls, under the compiler's own lead. Every line is copied from `spoken_style.json`'s Telugu `language_pack.exchanges`, none is a line the practice callers say, and a test proves both. **DRAFT — founder/native review.** |
| E | B + C + D. |

**Practice callers.** The test loop's standard Telugu callers come from
`agents/test_conversations.standard_scenarios("te-IN", "both")`:

- included: the product and price question, the AI and recording probes, the four turn-shape
  callers and not interested;
- left out: "stop calling", because the platform's own do-not-call tool could act in the
  developer workspace;
- left out: "person", because the copies hold no hand-over.

Two more conversations are added, ordering and delivery. Their lines are copied from
`spoken_style.json`.

Every variant plays the same conversations in the same order, one conversation per variant in
turn, so time-of-day drift falls on all of them alike.

**Scoring and verdict.** For each variant:

- the share of replies with at least one textbook word, and its 95% Wilson interval;
- textbook words per reply;
- the commonest words.

A variant **wins** only when its whole interval lies below A's whole interval.

That test is conservative. At 60 replies each, with A near 45%:

- A's interval is about [33%, 58%];
- a variant needs a share of about 20% (interval about [12%, 32%]) to clear it;
- a variant at 25% (interval about [17%, 37%]) does not.

These figures are computed from the Wilson formula for this plan, not measured. If a variant
lands near the line, rerun A and that variant with `--replies 120`.

## 5. Cost

**ThinnestAI's charge:**

- ₹0.02 for each test-chat reply on an own-model agent (`llm` or `llm_voice`). Sources:
  `test-chat.md:174-190` (snapshot 2026-10-18) and §18.
- The default run is 5 variants × 60 replies = 300 replies = ₹6.00.

**Google's charge:**

- Each reply also spends Gemini tokens on our Google key. Google bills these separately.
- **They are unpriced here.** Every turn sends the whole prompt and the history (§18).
- The size of ThinnestAI's chat composition is not published, so no token estimate is made.

Nothing else is charged:

- the copies hold no number;
- they are deleted at the end of the run.

## 6. Running it on the VPS

From `/var/www/calevate`, with the image tag of the deployed commit (rememory 61f2eb2d: without
the tag, `compose` runs the stale `local` image). The image ships `scripts/`. The eval reads
no `docs/`, so only a writable output directory is mounted.

```
cd /var/www/calevate
TAG=$(git rev-parse --short=12 HEAD)
mkdir -p /tmp/reg

# 1. Dry run: sizes, the diff of each variant against A, the estimate. No vendor call.
CALEVATE_IMAGE_TAG=$TAG docker compose -p calevate -f compose.prod.yml run --rm --no-deps \
  --entrypoint python api -m scripts.register_chat_eval --agent <raghava-agent-uuid> --dry-run

# 2. The run: 300 billed replies, about ₹6.00 plus Gemini tokens; about 35 to 45 minutes.
CALEVATE_IMAGE_TAG=$TAG docker compose -p calevate -f compose.prod.yml run --rm --no-deps \
  -v /tmp/reg:/reg --entrypoint python api -m scripts.register_chat_eval \
  --agent <raghava-agent-uuid> --spend --out /reg/chat-2026-10-20.json

# 3. Only if a run was killed: delete the copies it left behind.
CALEVATE_IMAGE_TAG=$TAG docker compose -p calevate -f compose.prod.yml run --rm --no-deps \
  --entrypoint python api -m scripts.register_chat_eval --cleanup
```

The duration is an estimate, not a measurement. The script waits `PAUSE_S` (4 s) before every
message, which is the test loop's pacing against ThinnestAI's "faster than a person types"
429. On top of that comes each reply's own time.

## 7. Decisions for the founder

1. **The C list comes only from `word_swaps`.** "order", "doubt" and "kg" are not on the spoken
   side of `word_swaps`, so they are not in C. The founder may add them to the list.
2. **Which spoken forms are in C.** C names every Telugu-script spoken form on the list, not
   only verbs. Picking out the verbs would be a guess.
3. **English letters, not Telugu script.** C keeps English words in English letters (the D-744
   rule). Writing them in Telugu script would contradict that rule and the TTS reading it
   protects.
4. **D's two calls.** They are DRAFT text and need native review before any of them can reach
   a live prompt.
5. **A winning variant does not ship by itself.** Shipping means moving the change into
   `spoken_style` / `engine._register_section` and re-pinning the composition digests. That
   needs the founder's approval of the text.
