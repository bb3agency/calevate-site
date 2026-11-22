# Script quality at creation (D-1031): why the first script read worse, and what the guides say

The request (founder, 22 Nov 2026): a campaign's or Inbound line's script written as it is
made must be as good as one written later with Pip's Generate, and the writer's prompts must
meet industry practice for voice agents.

## 1. Why a script written at creation read worse

Traced in the code at commit e21e99170 (0.5.5). Every path that writes a holder's script queues
the same job (`apps/workers/campaign_script.draft_campaign_script` / `draft_line_script`):
the first run (`apps/api/first_run/work.py:291-299, 326-334`, `request_proposal(auto_save=True)`),
the page's Generate (`apps/api/campaigns/workspace_routes.py:472-534`,
`apps/api/inbound/routes.py:413`) and Pip's `script_draft`
(`apps/api/copilot/script_actions.py:440-475`). The web's new campaign (`NewCampaignScreen.tsx`)
makes an empty draft and the owner presses Generate on its page, so it is the page path.

| # | Finding | Evidence | Holds? |
| - | - | - | - |
| 1 | **A first script was one pass; a later press is a second pass.** With no script on the holder the job writes it whole (`campaign_script._write`, `if base is None`, the generic writer instruction with the campaign ask folded into "In the owner's words"). A later press on a holder that now has that script records it as `base_script` (`workspace.request_proposal`, `record["base_script"] = row.script`) and the job sends an EDIT of it with the whole ask again (`EDIT_INSTRUCTION`, `campaign_change(edit=True)`). So "written later" was the first draft refined once against the same ask. | `apps/workers/campaign_script.py` (before this change, lines 643-648); `apps/api/campaigns/workspace.py:374-381` | Root cause |
| 2 | **The holder's details to collect never reached the writer.** D-1028 (019ad2f45, 22 Nov 2026) set `brief_for(...).collect=()` because an agent's own script asks for none, and nothing put the campaign's or line's own "What it notes" back. `call_rules.SCRIPT_FLOW_RULE` ("every detail to collect is asked in a stage") then had nothing to place, for creation and later presses alike. | `apps/api/agents/script_proposals.py:195-196` | Root cause (both paths) |
| 3 | The draft is requested before its inputs exist. | The job reads the main task, sources, name, purpose, goal, consent source and language when it runs, in a later transaction than the request; the first run saves the main task and sources before `request_proposal` in the same transaction (`first_run/work.py:274-299, 301-334`). | Disproved |
| 4 | A ready-made template is used instead of Pip. | Only when the account has no AI allowance or is in a view-as session (`first_run/work.py:290`), or when Pip's draft fails or cannot be saved (`campaign_script._ready_made_if_asked`, `_save_if_asked`). A fallback, not the normal path; a later press then edits the template. | Holds for those cases only |
| 5 | A shorter system prompt, a different focus or ask, a size cap or a fallback model at creation. | Same job, same `CAMPAIGN_ASK`/`LINE_ASK`, same `PROPOSAL_MAX_TOKENS` and timeouts, same `standby_after_answer=False`; `focus` exists only on one-part rewrites, which need a script. `auto_save` only changes what happens after the draft is written. | Disproved |
| 6 | The first run's main task is the owner's "About your business" words, not the call's job. | `first_run/work.main_task_of`; the brief step tells the owner Pip writes the first calls' script from it. A later press reads the same main task unless the owner edits it, so this is not a creation-versus-later difference. | Not changed (the main task is the owner's own words by decision, pinned by `tests/first_run_work_test.py`) |

## 2. What the guides say

All sources read 22 Nov 2026. VVD = the vendor's own documentation. "Covered" names where our
writer or the composed call prompt already does it.

| # | Practice | Source | Class | Ours |
| - | - | - | - | - |
| 1 | Separate the prompt into clean sections (identity, tone, goal, guardrails, tools, error handling); be as concise as possible; keep prompts under about 2,000 tokens | elevenlabs.io/docs/agents-platform/best-practices/prompting-guide | VVD | The script is compiled into sections by `calevate_shared.call_script`; the composed prompt has its own sections (`engine.compose_engine_prompt`). New: `CONCISE_RULE`. |
| 2 | Acknowledge when you do not know instead of guessing; confirm consequential details before acting | same | VVD | Covered: `GROUNDING_RULE`, `engine.VOICE_STYLE_GUIDANCE` ("Read back what you heard and wait for a yes"). |
| 3 | One or two sentences a turn; one question a turn; a turn budget (a simple booking runs 5 to 7 turns) | docs.vapi.ai/prompting-guide | VVD | Covered: `TURN_RULE`, `VOICE_STYLE_GUIDANCE`. New: "the fewest steps reach the main task" (`CONCISE_RULE`). |
| 4 | Numbers, money, dates and phone numbers in spoken form; phone numbers in digit groups | same | VVD | Covered: the spoken-style guide's number rules in the writer's brief, `VOICE_STYLE_GUIDANCE` ("digit by digit, a mobile five, a comma, five"). |
| 5 | Interrupted: stop, listen, respond; unclear input: ask to repeat | same | VVD | Covered: `VOICE_STYLE_GUIDANCE` ("Talked over or too fast? Stop, answer..."; "Unclear ... Ask one thing again, reworded"). |
| 6 | Transactional flows read back the fields; soft intake acknowledges instead | same | VVD | New: `DETAILS_RULE`. |
| 7 | Never infer or fabricate prices, schedules or policies; a positive principle beats long "never say" lists | same | VVD | Covered: `GROUNDING_RULE`, the review's evidence check. |
| 8 | State each instruction once; AI-written prompts are over-cautious, with instructions for situations that never come up; every extra instruction makes the agent slower and worse at the rest | docs.retellai.com/build/prompt-engineering-guide | VVD | New: `CONCISE_RULE` (no speaking rules in step instructions: the platform adds them on every call). |
| 9 | Dates read aloud as words | same | VVD | Covered: spoken-style guide. |
| 10 | Labelled sections: role and objective, personality and tone, context, pronunciations, tools, rules, conversation flow as states with transitions, safety and escalation; bullets over paragraphs; samples are followed closely | developers.openai.com/cookbook/examples/realtime_prompting_guide | VVD | Covered: stages with `exit_when`, `next` and ways out are the states and transitions; `example_exchange` "shows style only". |
| 11 | Identity, output rules, tools, goals, guardrails; plain text, numbers spelled out; one to three sentences; one question at a time; load known user details to avoid redundant questions; personality as observable speech behaviour, not traits | docs.livekit.io/agents/start/prompting | VVD | New: `DETAILS_RULE` (never ask what the call already knows), `CONCISE_RULE` (style.tone as behaviour). Rest covered. |
| 12 | Clear specific instructions; supply context so output is grounded; put all context first and the specific instructions near the end; split complex work into chained prompts | aistudio.google.com/docs/prompting-strategies (redirected from ai.google.dev/gemini-api/docs/prompting-strategies) | VVD | New: `TASK_REMINDER` after the sources. The chained passes (draft, refine, shorten, review, repair) are the split. |
| 13 | State the goal plainly; map the call's start, middle and end; give background on the business and the person; the agent introduces itself and the organisation | bland.ai/blog/prompting-guide-ai-phone-calls | Vendor blog | Covered: `CAMPAIGN_ASK`, `situation_block`, `OPENING_LINE_RULE`. |
| 14 | Opening with the reason for the call roughly doubles success; "Did I catch you at a bad time?" scores lowest; a permission opener that acknowledges the call works | gong.io/blog/cold-calling-tips; gong.io/blog/the-best-and-worst-cold-call-openers-backed-by-data-from-300m-calls (search snippets; figures differ between Gong's publications) | Vendor research, snippets only | Covered: `call_rules.PLACED_OPENING_RULE` (who, from where, the one reason, then whether they can talk). |
| 15 | Code-mixed callers: keep the English terms people use (EMI, UPI), follow the caller's mix rather than forcing one language | exotel.com/blog/hinglish-conversational-ai-benchmarks-for-indian-banks; tatacommunications.com/knowledge-base/voice-ai/code-switching-voice-ai (search snippets) | Vendor blogs, snippets only | Covered by the founder-reviewed spoken-style guides (D-744) the writer follows. No source on Telugu-English mixing was found: UNKNOWN beyond our own reviewed guides. |
| 16 | Generate, critique and refine improves output over one pass | arxiv.org/abs/2303.17651 (Self-Refine) | Academic | New: the refining edit of a first draft (`REFINE_TAIL`). The existing review stays a separate call, because a model rarely finds its own errors unprompted (arxiv.org/abs/2310.01798). |
| 17 | Voicemail | not covered by any guide read here | - | Not built: we place single calls; the engine's voicemail message is a ThinnestAI campaign-builder feature (D-1004). |

Pipecat's own documentation was not found by search; the NVIDIA voice-agent docs that build on
it (docs.nvidia.com/nemo/labs-voice-agent/build-voice-agents/configure/system-prompts, search
snippet) say TTS reads output verbatim, which is why markdown is forbidden; covered by
`VOICE_STYLE_GUIDANCE`.

## 3. What this decides

- **A first script gets the press a later Generate would give it.** After the whole draft the
  job sends the same ask again as an edit of that draft, with `REFINE_TAIL` naming what to
  rewrite (rows 1 and 16). It is skipped when the job is short of time and a refusal keeps
  the paid first draft; both are metered. Creation and the page's first Generate now match a
  draft refined by a second press.
- **The holder's details reach the writer.** `campaign_inputs` / `line_inputs` put the
  campaign's or line's own "What it notes" into `ScriptBrief.collect` (finding 2), so
  `SCRIPT_FLOW_RULE` places each ask.
- **New writer rules** (`campaign_script_ask`): `DETAILS_RULE` (rows 6, 11), `CONCISE_RULE`
  (rows 1, 3, 8, 11), `TASK_REMINDER` (row 12). They go to the writer only; the composed
  call prompt is unchanged, so `OWNER_RESERVE` and the prompt budget are untouched.
- **The composed call prompt already meets the guides** (rows 2-5, 7, 9-11): short turns, one
  question, read-back, digits, interruptions, unclear input, no markdown, grounding. Nothing
  was added there; the budget tests pin its size.
