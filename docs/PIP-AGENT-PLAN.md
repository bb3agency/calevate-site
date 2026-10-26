# D-893: Pip does the client's work — plan and contracts

Founder, 26 Oct 2026. A client tells Pip a job in plain words, from any screen, and Pip does
it end to end, across every area of the console: calls and call-backs, leads and do-not-call,
campaigns, agents, knowledge, numbers, team, settings, integrations, billing settings,
exports and reports. Every capability also has its own proper UI on its own page. The same
change adds the guided "questions your agent needs answered" list and a lighter Training tab.

This file is the contract every lane builds to. `docs/COPILOT-CONTRACT.md` (how to add a
tool) still binds; where this file adds to it, this file wins for D-893 work.

## 1. Founder decisions (26 Oct 2026)

| Question | Decision |
|---|---|
| Approval for work that reaches callers or spends credit | **One plan, one click.** One card: what Pip will do, to whom (count and list), why, when, estimated credit, and who it leaves out and why (do-not-call, calling hours, no consent, no agent). One click approves exactly that plan. |
| How many people one instruction may touch | **No fixed number.** Sized to the job and the conversation; the card always shows the count and the estimate. A dialling job runs as a campaign so the line limit, pacing, calling hours and retries apply. |
| Areas | **All 26** (list in §4), each with page UI and a Pip action. |
| Never | Taking a payment; accepting legal documents or the no-cold-calls pledge; KYC or identity documents; deleting the account or erasing its data. |
| Repeating jobs | **Yes, with approval.** Pip creates a routine after one confirm; each run prepares its plan and asks before calling anyone. |
| Guided questions | **Pip drafts, owner confirms.** A checklist, most-asked first; Pip pre-fills a draft where its sources allow; one tap keeps it, or the owner edits, types or speaks. |
| Training tab | **Checklist first, rest folded.** |
| Channel | **In the app**, every screen, desktop and phone. WhatsApp to Pip is a later, separate step. |
| Who | **Anyone, within their role.** Pip does exactly what that person's buttons allow. |

## 2. Standards this follows

- Tools: few, consolidated, workflow-shaped, readable fields rather than ids, filters and
  pagination, errors that say how to fix the call (Anthropic, "Writing effective tools for
  agents").
- Security: OWASP Top 10 for Agentic Applications (9 Dec 2025), especially ASI02 tool misuse
  and ASI03 identity and privilege abuse. Least privilege per person, human approval for
  consequential work, approval bound to the exact plan, durable resume without replaying a
  side effect.
- Prompt injection: plan-then-execute. Targets come from the person's request, the screen's
  selection or a filter the person can read on the card. Text a caller said, a lead form or
  a document is data; it can never add a target, change a recipient or approve anything.
- Hard rules 1–13 of `CLAUDE.md` bind every line. Every dial goes through
  `compliance.service.check_dispatch`; nothing here adds a bypass.

## 2a. Cost per answer (founder, 26 Oct 2026: best output for the fewest model tokens)

Binding on every lane; measured, not assumed.

- **Fixed, cacheable prefix.** The system prompt and the tool array stay byte-identical per
  surface (D-816), so the provider's cached-input price applies to most of every request.
  Nothing per tenant, per screen or per role goes into the prefix.
- **Fewer tokens of tools.** Area tools (F1) replace ~70 tool schemas; target ≤ 12,000 tokens
  for the client array.
- **Sets stay on the server.** A bulk job never lists thousands of rows into the model. The
  `_find` tools return a count, a few readable examples and a `lens` handle; the plan (F3)
  freezes the ids server-side. The model reasons over the filter, not the rows.
- **Concise by default.** Every read takes `detail: "summary" | "full"` and defaults to
  summary; pagination and truncation with sensible defaults; readable names, never raw ids
  except the one the next call needs.
- **Right model for the step.** `model_tiers.route_tier` keeps simple questions on the fast
  tier and multi-step jobs on the planning tier; a plan's execution runs no model at all.
- **Old results cleared.** Read results older than the latest exchange stay replaced by
  `cleared_result` (D-816).
- **One round trip where one is enough.** A `_do` action resolves its own targets from a lens
  rather than needing a `_find` call first.
- **Measured.** `scripts/copilot_tool_eval.py` records input, cached-input and output tokens
  and rupees per case. Each lane adds cases for its area; the integrator compares the totals
  with the pre-D-893 baseline and the change may not raise the average cost per answer.

## 3. Foundation (lane F) — built first, everything else uses it

### F1. Area tools (the model-facing surface)

Pip already has about 70 tools and the client tool array is near its 18,000-token budget.
Adding 40 more as separate tools would break the budget and the model's choice.

- The registry (`write_tools.WRITE_TOOLS`, `ActionTool`) is unchanged: each action keeps its
  own `tier`, `permission`, `plan`, `execute`, `undo`, audit and tests.
- `apps/api/copilot/areas.py` maps every action and read tool to one AREA:
  `calls, callbacks, leads, campaigns, agents, knowledge, numbers, team, settings,
  integrations, billing, reports, routines`. A test fails when a registered tool has no area.
- The model sees two tools per area, `<area>_find` (reads) and `<area>_do` (actions), each
  with an `action` enum and an `args` object. The service dispatches `<area>_do(action=x)` to
  the registry tool `x`, so the tier is still read only from the registry.
- The area description lists each action with a one-line argument summary. A wrong argument
  is refused with that action's exact argument schema, so the model corrects itself.
- Budget: client tool array ≤ 12,000 tokens (measured by `prompt_budget_test.py`). The
  offline tool-choice eval (`scripts/copilot_tool_eval.py`, fixture
  `tests/fixtures/copilot_tool_choice.json`) is rewritten to the area names and extended
  with the 26 areas' cases.

### F2. One lens for leads and calls

`apps/api/crm/lens.py`: `LeadLens` and `CallLens` server models, the ONE definition of
"which rows", used by the Leads and Calls screens, their exports, bulk routes, campaign
"add from a filter" and Pip's `_find` tools. Extends today's `LeadSearchIn` /
`service._lead_scope` (status, search, agent, assigned_to, field facets `f`, semantic `ask`)
with: created and last-call date ranges (IST days), last call outcome, direction,
include/exclude test calls, has an open call-back, follow-up done/not done, captured-field
text contains (bound parameter, never interpolated). The screens gain the same filters.
Bulk routes take a lens with no fixed size; the plan freezes the matching ids (F3).

### F3. Plans: one card, one click, exact execution

- Table `copilot_plans` (tenant-scoped, FORCE RLS, policy in the same migration, cross-tenant
  zero-rows test) and `copilot_plan_targets` (one row per target: id, status
  `pending|done|skipped|failed`, reason). A plan holds: actor, action (registry name),
  canonical args, the lens as the person reads it, the frozen target ids, exclusions with
  reasons and counts, the estimate in INR (Decimal, from attested rates, or "not known"),
  a hash of all of the above, status
  `proposed|approved|running|done|cancelled|expired`, expiry.
- The confirm token binds `plan_id` + hash. Approving runs EXACTLY the frozen targets; the
  world is re-checked per target at execution (do-not-call, hours, consent, credit), and a
  target that no longer qualifies is skipped with a reason, never swapped for another.
- Execution: outbox job `run_copilot_plan`, idempotent per (plan, target), resumable after a
  redeploy, cancellable, progress readable. Dialling plans create a campaign (kind `pip`,
  named after the request) and add the frozen targets, so the line limit, pacing, calling
  hours and retry policy apply; every other plan runs in the plan worker.
- When it finishes: a bell notification and the result on the plan card (done, skipped with
  reasons, failed with reasons).
- Small single-object actions keep today's confirm card; a plan is used whenever the action
  touches a set.

### F4. Security fixes found in the inventory

- `callback_book` / `_reschedule` call the same service as the HTTP route, so standing
  refusals and the 09:00–21:00 IST window apply.
- A Pip action whose console button needs an emailed code needs the same code on confirm
  (`withAccountCode`), e.g. buying a number, exports, owner invites, integrations endpoints.
- Confirmed and approved actions record `prior_state` where an exact inverse exists, so they
  appear with Undo in the activity log.
- `copilot_memories` are covered by `execute_deletion_request` and the erasure coverage check.

### F5. Pip chat UI

Plan card (who/why/when/estimate/excluded, expandable list, Approve / Change / Cancel),
progress and result states, from any screen; Approvals inbox and Tasks show the same card.
Built with the design skills in `.claude/skills/` and the interior components
(`components/ui`, `components/console`, `components/arc`, `components/copilot`).

## 4. Areas and lanes

Every lane, for every item: backend service (one per problem; route and Pip call the same
function) → route (permission, step-up where the button has one) → OpenAPI snapshot and
`schema.d.ts` → web hook (query key, invalidation, live topic) → page UI (loading, empty,
error, success states, mobile, accessible) → Pip action in its area via `areas.py` → audit →
tests at each layer → docs. No orphan route, job, column, setting or component.

| Lane | Items |
|---|---|
| L1 Calls & call-backs | 1 call a lead now · 2 call back about an earlier call with its context · 3 book/move/cancel call-backs, single and bulk · 4 retry unanswered/failed calls · 5 follow-up done/not done · 6 WhatsApp a lead · 7 translate a call |
| L2 Leads & DNC & exports | 8 status/owner/name, single and bulk by any lens · 9 saved views · 10 do-not-call add/remove/restore · exports of leads and calls |
| L3 Campaigns | 11 create/edit/schedule/repeat/pause/resume/stop/delete · 12 contacts from a lens or CSV, remove contacts · 13 retry policy |
| L4 Agents | 14 create/edit/publish/pause/archive/restore · 15 script changes · 16 voice, speaking style, call-handling and hand-over numbers, daily cap, AI model · 17 in-call actions · 19 lead fields |
| L5 Knowledge & training | 18 practice tests · 20 facts teach/edit/delete/pin · 21 guided questions · 22 files and links · the Training tab redesign |
| L6 Account | 23 numbers buy/release/assign/forwarding/call lines · 24 team · 25 profile, hours, line-protection phone, lead sources and calling rules · integrations · billing settings |
| L7 Reports & routines | 26 questions and summaries over calls, leads and spend · routines from chat (create/edit/pause/delete, each run asks) |

## 5. Guided questions (L5)

- One list, `GET /v1/teach/questions`: open knowledge gaps grouped by topic and ranked by
  calls affected; readiness questions the practice callers need (prices when callers ask
  prices and nothing known has one); setup questions the agent's script leaves open. Each
  item: the question in plain words, how many callers asked, the latest call, and a draft
  answer with its source when Pip can ground one in what the business already gave us
  (profile, earlier answers, files read). A draft without a source is not offered.
- Answer inline: Keep the draft, edit it, type or speak an answer, or "Not something we
  answer" (dismiss with a reason). Saving goes through the existing teach path (facts and
  rules, D-821), closes the gap, and the agent knows it on its next call.
- Every "Add prices"-style link opens this list filtered to that question, never a blank page.

## 6. Training tab (L5)

Top: "Questions to answer" with the count. Then one "Try it" card (chat and practice call
together). Then one-line summaries that open on click: what it knows, saved tests, practice
callers. Less text everywhere; the founder's 19 Oct tab structure (decision 5a08c365) stays.

## 7. Done means

Each lane: ruff, ruff format, strict mypy, lint-imports, every `scripts/check_*` gate,
targeted pytest green on a lane database, web typecheck, eslint and vitest green, the
OpenAPI snapshot fresh, the tool-choice eval passing, and a browser check of every changed
screen at desktop and 375 px. The integrator then runs the whole suite and the coverage
ratchet.
