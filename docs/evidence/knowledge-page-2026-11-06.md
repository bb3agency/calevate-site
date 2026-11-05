# What reaches an agent, and where "What your agents know" shows it (6 Nov 2026)

Founder report, 6 Nov 2026, on `/c/rytu-khata/knowledge`: the page did not show what the
agents know. It listed a 21 KB guide as one row ("27 call instructions kept for call
scripts"), with nothing of what the file taught. This is the map of every piece of business
knowledge that reaches an agent, read from the code at `394564e8b`, and what the page now
does with each.

## Shared by every agent of the business (D-689): on this page

| Source | Where it is stored | How it reaches the agent | On the page |
|---|---|---|---|
| Pinned facts | `kb_facts` with `pinned` (`apps/api/teach/facts.py:67`) | Spliced into every agent's script as `[QUICK FACTS]` (`apps/api/teach/pinned.py:313`, cap `MAX_PINNED_CHARS` :51) | "Pinned facts" (unchanged) |
| Facts and answers, including answers to "Questions to answer" | `kb_facts`, not pinned (`teach/facts.py:136`; `teach/questions.py:411` saves an answer through `add_facts`) | Compiled into one knowledge source, "Facts you taught" (`teach/facts.py:32`), attached to every agent's knowledge base like any source | "Facts and answers" (unchanged) |
| Business details: hours, each address, what it offers, common questions, team, booking rules | `business_profiles` (`apps/api/tenancy/business_profile.py`) | `fact_lines` (`business_profile.py:254`) writes the business half of `[T0 FACTS]` (`agents/t0.py:169`, `:234`); on ThinnestAI that block goes as the "Business facts" knowledge document (`agents/engine_facts.py:58`, `:75`; `agents/t0_block.py:65`). Prices are left out when the business quotes none (`business_profile.py:294`). Contact numbers never reach it | Offers and common questions (unchanged, D-968); **new** "Hours, places and team" group with the rest |
| Files and photos | `kb_uploads` + `kb_sources`; what was read is `kb_documents`, one chunk per heading section for a Markdown guide (`kb/service.py:655`, `kb/structured_text.py`) | The approved chunks rendered as one document per source (`kb/service.py:2077`, `:976`) and attached to every agent | **New**: the row says "N things learned"; "Show what it learned" lists each chunk under its heading, from `GET /v1/kb/sources/{id}/preview`. The count is `UploadOut.facts_count` (same table, same source) |
| Call instructions in a file | `kb_uploads.call_instructions` (`kb/service.py:642`) | **Not used on calls.** Only "Use in call scripts" (`kb/uploads.py:844`) turns them into a script suggestion the owner reviews | **New**: "Show call instructions" lists them in place, says "Not said on calls until they are in a script.", and offers the button |
| Links | `kb_uploads` kind `url` | Sent as the address; the engine reads the page itself (`kb/service.py:969` `_DELIVERED_HEAD`) | Row as before; "Show what we read" lists our copy and says the agents read the page itself |
| Notes typed before the teach box | `kb_sources` kind `text` (`kb/store.py:197`) | Attached like any source | "Notes you wrote earlier" (unchanged) |

The count at the top adds only what reaches the agents now: business-detail lines (one per
row, as `fact_lines` writes them), pinned facts, facts once published, things read from files
in use, links in use (one each, the engine reads the page), notes in use. Waiting or broken
items are counted beside it ("N waiting", "N not working"), as before.

## One agent only: named here, opened on the agent

| Source | Where | On the page |
|---|---|---|
| The agent's own script (its job, steps, words) | The `client_script` layer of `compose_engine_prompt` (`packages/shared/src/calevate_shared/engine.py:5010`); `[T0 FACTS]` is taken out of it on an engine that holds facts as knowledge (`apps/api/agents/service.py:3285`) | **New** "Each agent's own script" group: one row per agent, "Open its script" |
| Caller memory | Per caller, not per business: `voice.pastConversations` `recap`/`fresh` (`apps/api/engine/thinnest.py:2373`), rendered by `_caller_memory_section` (`engine.py:4897`) | Said on the agent's row only ("Also remembers each caller"); its content is never listed here |
| Rules waiting for a script | `agent_rule_proposals` pending (`kb/store.py:340`) | Not knowledge until applied; on the agent's Script page |

## Not business knowledge: never shown here

Platform text in every prompt: the preamble, how to speak, languages, the business-facts
guidance (`engine.py:3132`), the cannot-help rules (`engine.py:3595`), the confidentiality
rule (`engine.py:5061`, D-674), the truthful-answer block (`engine.py:5064`, hard rule 5) and
the per-call values (`engine.py:5066`).

## Not verified

- What ThinnestAI holds for each agent is not read on this page; the operator's per-agent
  list (`kb/agent_view.py`) does that. "In use" here is our own record.
- For a link, our copy of the page may differ from what the engine fetched.
