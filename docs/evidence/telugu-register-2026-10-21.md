# Textbook Telugu in agent replies: what instructions can do, and the word-swap approach

21 Oct 2026. Measurements by the founder on production; research from public docs and papers.
Follows `telugu-register-chat-eval-plan-2026-10-20.md` (D-837).

## 1. What we measured

`scripts/register_eval` on production: our real composed prompt for a reference retail shop,
ThinnestAI's speaking rules after it (`docs/vendor/thinnest-speaking-rules-2026-10-18.md`),
`gemini-3.1-flash-lite` on our Google key, Telugu, 5 runs per caller line, 100 replies per
version, scored by `agents/turn_checks` (`formal_words` is a reply holding at least one word
from `spoken_style.json`'s Telugu list).

| Version | Replies with a textbook word | Against current |
|---|---|---|
| current (production) | 37% | |
| positive: "not X but Y" pairs replaced by words to use | 56% | +19% [+5.4, +32.6], worse |
| persona: "talk like the shop's staff" line | 36% | no change |
| positive + persona | 44% | no change |
| positive + persona + examples | 38% | no change |
| pack-en-noavoid | 49% | no change; too long 9% (up) |
| pack-native-noavoid | 39% | no change; too long 12% (up) |

Cost ₹44.04 (attested rate). Conclusion: **naming the words works**. Without the pairs, the
listed words come back (ధన్యవాదాలు 0 → 4, చేస్తాము 0 → 10, కొనుగోలు 0 → 2 per 100 replies).
No version beat production.

The commonest words left were not on the list, so commit `5ba96adb` added వివరాలు (founder,
19 Oct 2026: people say "details") and అందుబాటులో ఉంది to `prompt_swaps`, and dropped
సుమారు, అవసరం and యొక్క, which appeared in no reply of any version. Re-measured after deploy:

| | Replies with a textbook word | మరియు | వివరాలు | all other listed words |
|---|---|---|---|---|
| before `5ba96adb` | 37% | 11 | 17 | 16 |
| after `5ba96adb` | 36% | 18 | 14 | 10 |

(word counts per 100 replies). The difference is within chance at n=100. **The instruction
approach has reached its limit on this model: what remains is almost entirely మరియు and
వివరాలు**, which the model writes even when the prompt names them.

These are practice conversations against a reference shop, not real calls. The last real-call
reading (10-11 Oct 2026, older prompt and model) was about 45% of agent turns.

## 2. What public sources say

- **The published advice is what our prompt already does.** Ban the formal register by name,
  list the English loanwords people use, write in the native script, add everyday fillers:
  [Bolti](https://bolti.co.in/blog/multilingual-voice-ai-india),
  [Mirai Minds](https://docs.miraiminds.co/v2/prompting-guide),
  [Bolna](https://www.bolna.ai/docs/guides/writing-prompts-in-non-english-languages),
  ThinnestAI's own [Hindi guide](https://www.thinnest.ai/blog/build-hindi-voice-ai-agent).
  No vendor publishes how often its agents still use formal words.
- **The models lean formal by construction.** LLM code-switched output is "stylistically more
  refined than real informal usage" ([arXiv 2601.07153](https://arxiv.org/pdf/2601.07153));
  models are trained mostly on written standard varieties
  ([arXiv 2606.24172](https://arxiv.org/pdf/2606.24172)). No paper measures Telugu register
  control directly.
- **Sarvam's edge is its own Indic-trained models** (Sarvam-M,
  [Sarvam-30B](https://docs.sarvam.ai/api/models/sarvam-30b)); their published results are
  about understanding code-mixed input, not the register of what the agent says.
- **The platforms that remove a word entirely swap it between the model and the voice:**

| Platform | Text replacement before the voice |
|---|---|
| LiveKit | `tts_text_transforms` with `text_transforms.replace()`, buffered across streamed tokens ([docs](https://docs.livekit.io/agents/multimodality/text/)) |
| Pipecat | `add_text_transformer()` on the TTS service ([docs](https://docs.pipecat.ai/guides/learn/text-to-speech)) |
| ElevenLabs Agents | pronunciation dictionary alias tags "substitute spellings or phrases" ([docs](https://elevenlabs.io/docs/eleven-agents/customization/voice/pronunciation-dictionary)) |
| Smallest.ai, Voice.ai | dictionaries with text-replacement rules ([Smallest](https://atoms-docs.smallest.ai/deep-dive/voice-config/pronunciation-dictionaries), [Voice.ai](https://voice.ai/guides/text-to-speech/pronunciation-dictionaries.md)) |
| Retell | English agents only ([docs](https://docs.retellai.com/build/add-pronunciation)) |
| ThinnestAI | none found in its docs; Cartesia's `pronunciation_dict_id` is not passed (our question of 10 Oct 2026, unanswered) |

Evidence class: VENDOR-PUBLISHED docs, read 21 Oct 2026.

## 3. The approach (documented, not built)

A deterministic word swap applied to the agent's text before it is spoken:
మరియు → ఇంకా (or dropped), వివరాలు → details, and any further pair the measurements show the
prompt cannot hold. Three places it could live, in order of preference:

1. **ThinnestAI text-replacement rules on an agent.** A per-agent or per-workspace list applied
   before TTS, on every voice band (Clear and Studio). Nothing on our side but sending the list
   from `spoken_style.json`. Needs ThinnestAI to build it; to be asked in the next email.
2. **Cartesia pronunciation dictionary.** Cartesia applies a dictionary as search-and-replace
   on the transcript before synthesis, per request (`pronunciation_dict_id`). Studio only;
   Telugu is not stated in Cartesia's docs (test in play.cartesia.ai first); needs ThinnestAI
   to pass the id.
3. **Our own word-swap service on the model leg.** ThinnestAI's BYOK takes any
   OpenAI-compatible URL; a small streaming service of ours would forward to Gemini and replace
   the words in the reply stream. Guarantees the listed words go to zero on every voice band.
   Costs a new deployable (a decision-log entry, `docs/ROADMAP.md` §6), a hop on every model
   turn (latency UNMEASURED), and a new way for calls to fail. Reverses the founder's 11 Oct
   ("not now") and 19 Oct 2026 (prompt approach only) decisions, so it is the founder's call.

Still worth measuring alongside: the same `register_eval` on a larger Gemini model (about ₹7 at
n=100), to separate what model size explains from what only a swap can fix.

**Status:** documented only (founder, 21 Oct 2026). Nothing is built; the production prompt
stays as of `5ba96adb`.
