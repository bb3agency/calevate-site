# Grounding Pip's campaign and line scripts in what the owner gave

The failure (Rytu Khata campaign, agent Varsha, 20-21 Nov 2026, founder-relayed): a script
written to help farmers who had already registered install the app told the person, as a
fact, that they had given their name in the app and that it was in the business's records,
and padded the call with stock lines. The person did not recognise the claim. Whether the
brief stated that fact is UNKNOWN; the defect holds either way, because a claim about the
person was told to them, not asked. The 9 Nov call on the same campaign showed the same
class (`docs/evidence/speech-naturalness-2026-11-09/PRESUPPOSITION.md`).

All sources read 21 Nov 2026.

| # | Practice | Source | Class | What it means for our writer |
| - | - | - | - | - |
| 1 | Restrict the output to the provided documents; after drafting, find a direct quote supporting each claim and retract any claim with no quote | platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations ("Verify with citations", "External knowledge restriction") | VVD (Anthropic) | The review lists each spoken claim with an `evidence` field: a word-for-word passage of the sources. The code, not the model, checks that the passage is really in the sources; a claim whose quote is missing or not found is unsourced and goes to the repair. |
| 2 | Retrofit attribution: find evidence for each claim, then post-edit only the unsupported content, preserving the rest | arxiv.org/abs/2210.08726 (RARR, Gao et al., ACL 2023) | Academic | Unsupported lines are rewritten by the existing targeted repair, which may change only the lines named (`script_proposals.kept_to_paths`); the rest of the draft is kept. |
| 3 | Generate, critique, refine improves output, but depends on the model's ability to judge; tested in English only | arxiv.org/abs/2303.17651 (Self-Refine, Madaan et al., NeurIPS 2023, §6 Limitations) | Academic | One critique pass with a fixed rubric, feeding the repair round we already run. No unbounded loop. Our scripts are Telugu-first, outside what the paper tested, so the checks that can be made in code are made in code. |
| 4 | Without external feedback a model rarely finds its own errors and can make answers worse | arxiv.org/abs/2310.01798 (Huang et al., ICLR 2024) | Academic | The critique is a separate call from the writer, and its verdict on sourcing is overruled by a code check against the source text (row 1). A line the repair changed is not judged again by a second paid call. |
| 5 | LLM judges show position, verbosity and self-preference bias; mitigations are calibrated rubrics and structured judgments | arxiv.org/abs/2410.02736 (CALM, "Justice or Prejudice?"); arxiv.org/abs/2411.15594 (Survey on LLM-as-a-Judge) | Academic | The rubric is checklist items, not a score; parts are judged one by one against the sources. Leniency on sourcing is cut by the code check. Self-preference (same model family writes and judges) is not removed: UNKNOWN how much it costs here. |
| 6 | Prefer binary pass/fail checks over 1-5 ratings; split a quality into separate binary checks | hamel.dev/blog/posts/evals-faq/why-do-you-recommend-binary-passfail-evaluations-instead-of-1-5-ratings-likert-scales.html | 3P (practitioner) | Each rubric item is a yes/no the model must commit to: `asked` true or false, `evidence` found or empty, a part listed under `off_task`, `generic` or `repeats` or not. |
| 7 | Voice agents: tell the agent to say it does not know rather than guess; never invent information; put non-negotiables in guardrails | elevenlabs.io/docs/agents-platform/best-practices/prompting-guide ("Dedicate a guardrails section", "Handle tool call failures gracefully") | VVD (vendor guide) | Already in `GROUNDING_RULE`. Added: the person rule, below. |
| 8 | Contact-centre scripts: define the reason for the call and the audience first; cold and warm calls need different openings; reference the real relationship | aircall.io/blog/support/phone-call-scripting/, phoneburner.com/blog/cold-calling-script-resources, vida.io/blog/outbound-call-script (search snippets only) | 3P, snippets only | The writer's brief now carries the campaign's own settings: its name, purpose, goal, and how the business has these people's numbers (`campaigns.consent_source`), plus the agent's name. |
| 9 | Verification questions should not give the answer away: ask open questions rather than state what the records hold | callcentrehelper.com/question-what-level-of-security-questions-need-to-be-asked-2516.htm (search snippet) | 3P, snippet only | A claim about the person, even one the sources give, is asked as a question they can answer, never told to them. The review flags `about_person` claims with `asked` false, and the repair rewrites them. |

## What this decides

- **Evidence per claim, checked in code.** The review returns `claims[]` with `evidence`; a
  quote not found in the sources (case, punctuation and spacing ignored) makes the claim
  unsourced whatever the model said. This is the structured-output form of row 1 and the
  guard against judge leniency (rows 4, 5).
- **One review, feeding the one repair loop.** The review now runs before the call-mistake
  repair, and its findings on repairable lines (steps, goal, ending) join that repair's
  findings (`script_proposal._Fix.noted`). A finding counts as cleared once the repair
  rewrote its line; one on a line the repair did not change stays as a warning for the
  owner. Openings, quick facts and objections are never rewritten by this loop: findings
  there stay warnings.
- **Rubric** (binary, rows 5 and 6): each claim traceable to the sources; anything about the
  person asked, not told; each part serves the main task; no stock line that would fit any
  business; nothing repeated across parts.
- **Brief**: the campaign's purpose, goal, name, audience relationship and the agent's name
  travel with the main task, sources, business facts and the details to collect.

## Not established

- Whether the founder's Rytu Khata brief stated that the farmers' names were on record:
  UNKNOWN (the brief was not read here).
- How often the code check rejects a true claim because the model paraphrased its quote:
  UNKNOWN until real drafts are measured; a rejected true claim costs a repair of that line,
  never a refusal of the draft.
