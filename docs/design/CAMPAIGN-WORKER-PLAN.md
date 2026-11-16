# The campaign is the worker: build plan

Founder decision, 16 Nov 2026 (rememory `7f9ef306`). Calevate is organised like a real calling company:

- every client has one **company training**, the same for every agent;
- **agents** are the staff: a name, a voice, languages, a speaking style, settings and actions, with **no script of their own**;
- **campaigns** are the work: main task, materials, script and what to note, spoken in **one** agent's voice;
- **inbound** gets its own section, end to end.

Build it following the campaign page that already exists (main task, materials, Pip Generate, script review, coloured fold sections).

The research behind this plan is in rememory `5e127481`. Every file reference below comes from it.

## 1. Engine facts the design rests on (ThinnestAI, docs mirror 2026-11-12)

| Fact | Source | Consequence |
| --- | --- | --- |
| One set of instructions per engine agent (20,000 chars) | `snapshots/2026-10-07/pages/api-reference/agents/update-agent.md:426-431` | A campaign with its own script needs its own engine agent. |
| A per-call override is 4,000 chars and replaces the built-in call rules | `calls/place-call.md:1283-1289`, `channels/voice.md:359-364` | Too small for a campaign script plus speech rules. Not used for scripts. |
| A number is answered by at most one engine agent; the greeting belongs to the agent | `channels/phone-numbers.md:543-550, 724`; `update-phone-number.md:144, 625-627`; `voice.md:366-371` | An inbound line with its own greeting needs its own engine agent. |
| A number can be lent to one agent to call out on | `phone-numbers.md:748-766` | A campaign agent dials by borrowing a number, even the voice agent's own. |
| Agents per client workspace on pay-as-you-go: 2, raised on request | `docs/vendor/thinnest-relationship-2026-10-23.md:82, 101, 140-142` (VENDOR-STATED) | The founder asks ThinnestAI for a raise. We count before Start and retire a campaign's engine agent when it ends. |

## 2. The shape

```
                 company training (one per client)
                              │
   ┌──────────────────────────┼───────────────────────────┐
 agent (voice)           campaign A                 inbound line (number)
 engine agent:           engine agent:              engine agent:
 training only           training + A's script      training + line brief
 (Make a call,           in agent X's voice         in agent Y's voice
  tests, try chat)
```

Each engine agent is composed as:

1. platform rules
2. the client fence, holding first the company training, then this holder's script
3. what the account can do
4. confidentiality
5. truthful answers
6. this call

Hard rule 5, `CONFIDENTIALITY_RULE` and the speech rules are composed into every holder exactly as today.

The agent keeps its own engine agent, holding the company training only, for:
- "Make a call", which adds the why as call variables, as today;
- test calls and try chat;
- serving as the voice template its campaign and line agents copy.

This keeps the existing persona machinery working.

## 3. Data

| Table / change | Holds | Notes |
| --- | --- | --- |
| `company_trainings` (new, one per tenant, FORCE RLS) | The owner's overview text and materials (the knowledge base, unchanged). Pip's training as a structured doc: business line, who we are, how we speak (tone, address form, phrases, pronunciations), policies, objections, taught rules. Version and proposal. | Campaign workspace pattern: main task → materials → Pip Generate → review. Pinned facts, profile and `fact_lines`/T0 stay where they are and are composed in. |
| `campaigns` | Unchanged, plus `extraction_fields` ("What it notes", per campaign). | `agent_held_at` and `held_overrides` retire. Overrides become part of the campaign engine agent's own config. |
| `inbound_lines` (new, FORCE RLS) | number_id, agent_id (voice), main task, materials, script (greeting and steps), what to note, handover, hours behaviour. | One line per number. |
| `engine_agent_routes` | Adds `holder_kind` (agent / variant / test_copy / campaign / line), `campaign_id`, `inbound_line_id`. | Intake stamps `calls.campaign_id` from the route. |
| `engine_kb_routes` | Adds the campaign and line holders. | Knowledge reaches every holder. |
| `extraction_schemas` | `agent_id` becomes nullable; `campaign_id` / `inbound_line_id` added. | The post-call pipeline picks the schema by the call's holder. |

Every new tenant table ships with its RLS policy and a cross-tenant zero-rows test (hard rule 1). Every new `{id}` route gets an `_IDOR_ROUTES` entry in `tests/adversarial_pass_test.py` in the same change.

## 4. Build order (each phase ships green on its own)

### Phase 1: Company training (built, D-995)
- Table, API and page. The page is a new client screen following the campaign workspace, with sidebar and `copilot/screens.py` entries.
- Pip writes the training from the overview, the business profile, knowledge and the first-run answers.
- Composition: the training is the first section, `[COMPANY TRAINING]`, inside the client fence of every agent and A/B arm (`agents/company_training.with_training`). It sits inside the fence rather than as a platform layer because the business wrote it. An account with no training composes byte for byte as before.

### Phase 2: Campaign engine agents
Hazards to fix first:
- `thinnest._name_tag` includes the holder id. Today a second holder with the same agent id would overwrite the agent's engine agent.
- Drift and settings repair become holder-aware: `publishing.engine_drift_for`, `engine_reconciliation:431`.

Then:
- `publish_campaign_agent`, modelled on `publish_variant`/`publish_variants`: create, read back, route row, webhook, knowledge, number lending, orphan reclaim.
- Start creates or updates the campaign's engine agent. The `agent_busy_with_campaign` refusal, `put_script_live` and `held_overrides` retire. Stop, complete and archive retire the engine agent.
- Fan out every agent change (voice, settings, notices, actions, platform prompt) to that agent's campaign and line agents.
- Intake stamps `campaign_id` (pipeline `_resolve_agent`/`_upsert_call_row`, `engine_actions` `ActionRoute`).
- The number hold is keyed on the engine ref.
- Silences (healer, credit stop, maintenance, voice fallback) cover every holder.
- The dial gate is scoped per holder.
- A pre-flight engine agent count runs before Start, with a plain message when the allowance is full.
- Campaign Test call rings the campaign agent itself.
- "What it notes" becomes per campaign.

### Phase 3: Inbound section (built before Phase 2, founder 16 Nov 2026; rememory `86161cac`, `298ad6cb`)

Founder answers: the section is called "Inbound"; several numbers may share one line; outside hours uses the business profile's opening hours (`business_profiles.hours`, `agents/business_hours.py`), never Leads & hours, which are outbound calling hours; every number always has a line; actions are set up on the agent, and each line switches that agent's actions on or off for itself.

Build, in slices that each ship green:

1. **Engine holders.**
   - `AgentConfig.holder` (excluded from dumps) joins `thinnest._name_tag` and the fake's stable id, so a line's engine agent never overwrites its agent's own.
   - `engine_agent_routes.inbound_line_id` and `calls.inbound_line_id` are added.
   - Intake stamps the call's line from the route.
2. **Lines.**
   - `inbound_lines` (FORCE RLS) holds: name, agent_id (the voice), main task, `script` (a `CallScript`, as campaigns hold it), Pip's proposal, `extraction_fields`, `actions_off`, engine_agent_ref, version, archived_at.
   - `inbound_line_sources` (FORCE RLS) holds the knowledge sources the line was written from, picked from What your agents know.
   - `phone_numbers.inbound_line_id` is added.
   - The routes are `/v1/inbound-lines/**`, with `_IDOR_ROUTES` entries.
3. **Publish.**
   - A line's engine agent is the agent's own `_to_config` over the line's compiled script. It is the variant pattern: `prompt` and `structured_script` are substituted, and the pinned facts and `[T0 FACTS]` come from the agent's body.
   - It is read back, gets a route row, and is reclaimed when orphaned. Its built-in tools are the agent's minus `actions_off`.
   - `engine_numbers.wanted_attachment` takes the line's ref for the answering agent.
   - Every agent change fans out to the agent's lines, as `republish_running_variants` does for arms. The drift sweep and the silences (healer, credit stop, maintenance, voice fallback) cover lines.
4. **Pip.**
   - The line's script is written by the campaign script writer: `workers/script_assist.draft_script` from the main task and the picked sources.
   - It is reviewed part by part and saved with "Put it live".
5. **Every number has a line.**
   - A migration and backfill make one line per answering agent, from that agent's applied script, and attach its numbers.
   - Callers hear the same words on day one.
   - Assigning a number now means choosing its line.
6. **Web.**
   - "Inbound" goes in the sidebar, with a list of lines, each showing its numbers, voice, status and calls.
   - The line page has coloured folds: Voice, Main task, Sources, Script (Pip Generate and review), What it notes, Actions, Handover, Outside hours (the business profile's hours, linked), Numbers, Test call, and Calls taken.
7. **Agent page.**
   - The agent page becomes Overview / Actions / Settings / Training.
   - Its Try it chooses "Just the business" (the company training, no script) or one of its lines and campaigns.

The original sketch:
- New sidebar section "Inbound", following the campaign pattern per number:
  - which agent's voice answers;
  - what it says (greeting, steps, what to note);
  - hours behaviour;
  - handover;
  - calls taken.
- Line engine agents are bound as the number's answering agent (`engine_numbers.wanted_attachment` re-pointed to the line).
- Number assignment moves here from the Phone numbers page. Forwarding and line protection link here.

### Phase 3b: Onboarding, rebuilt on the new model (founder, 16 Nov 2026; rememory `f284d8bb`)

1. **Sign up.** Unchanged.
2. **About your business.** Typed or spoken, with files, plus up to 3 profile questions.
   - The words become the company training's overview.
   - Pip's training is saved straight away as version 1.
3. **Name and voice.** The default agent is admin-configurable (today "Anjali", with a female Studio voice). It is the free-trial agent and the starter agent on paid tiers.
4. **What first?** Two cards:
   - "Answer my calls" drafts an Inbound line, which may exist with no number;
   - "Call people" drafts a campaign.
   - Pip writes either one.
5. **Hear it.** The same ticks screen, with notices untouched. The test call rings the draft line or campaign's own engine agent.
6. **Result.** The transcript, plus buttons for "Change what it says" and "How they speak".
7. **Go live (paid).** Verify, then buy a number. A new number is answered by the first inbound line; with none, the owner is asked to create one.

Also:
- "New agent" becomes name → voice → done.
- The readiness score and the Overview checklist drop their script items.
- Pip's first-agent guide is rewritten.

### Phase 4: Migration, and the agent page shrinks
- Each agent's script is split:
  - company facts are merged into the company training, and the owner chooses where agents disagree;
  - an inbound or both agent becomes an inbound line on each of its numbers;
  - an outbound or both agent becomes a draft campaign "<Agent>'s calls".
- The extraction schema is copied to the new line or campaign. Nothing is deleted; old prompt versions stay readable.
- The agent page becomes Overview, Actions, Settings, Training (`agentSections.tsx` and `copilot/screens.py` `AGENT_PAGE_TABS` together).
- Voice moves into Settings. "What it notes" moves to campaigns and lines.
- Every `?section=script` link lands on Overview with one line, "Scripts now live in Inbound and Campaigns", and a button to each. `LEGACY_SECTIONS` maps script → overview and voice/captured → settings.
- The new-agent and first-run flows become name → voice → test call.
- The readiness score and the Overview checklist drop their script items.
- The Pip agent-script tools retire. Pip writes the company training, campaign scripts and line briefs instead.

## 5. Decisions (founder, 16 Nov 2026)

1. A campaign may change a company fact for its own calls (a festival price): its script wins over the training on its own calls, and Pip marks the override.
2. Caller memory stays per engine agent (D-973) for now: a caller known to the inbound line is unknown to a campaign.
3. A/B opening tests stay on campaigns (opening B is already campaign-level). Per-agent experiments retire with the script.
