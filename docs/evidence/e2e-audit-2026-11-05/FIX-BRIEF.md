# Phase 2: fixing everything the audit found (5 Nov 2026)

Every fix lane follows this. Read `BRIEF.md` (same folder), the root `CLAUDE.md`, and the
FULL lane report(s) named in your lane — never a summary. The founder's words: "don't
consolidate and forget things", "don't assume anything at all", "fix all and everything",
"don't hardcode anything", "make this work like a SaaS product".

## The loop, per finding

1. **Store it first.** Before changing code for a finding, store it in rememory
   (`store_memory`, project `calevate`, memory_type `bug`, tags include `e2e-audit-2026-11-05`
   and its ID such as `a-03`). Content: the finding in full detail — what happens, where
   (file:line), evidence, rule broken, what should happen. One memory per finding. Store
   EVERY finding in your scope, including P2/P3 and ones you decide not to change (say why).
2. **Verify the premise.** Re-read the cited code. The audit reports are claims, not proof
   (CLAUDE.md hard rule 11/12). If a finding is wrong or already fixed, say so in its memory.
3. **Fix it properly** — the established standard or better (CLAUDE.md quality bar), one way
   per problem, migrate old callers in the same change, no half-wired seams.
4. **Test it.** A test that fails without the fix. Python via Docker only (never on the
   Windows host):
   `MSYS_NO_PATHCONV=1 docker run --rm --network calevate-dev_default -w /app -v "<your worktree>:/app" -v "D:\Agency\calevate\.env:/repoenv/.env:ro" -v "C:\Users\jumes\AppData\Local\Temp\claude\a50a3f0a872c1724\0c51a750-0b23-4950-961e-84972febca40\scratchpad\lane:/lane:ro" -v calevate-test-venv:/opt/venv ghcr.io/astral-sh/uv:python3.12-bookworm-slim sh /lane/lane-tests.sh <lane-name> <your redis db> <test paths> -q`
   (read `/lane/lane-tests.sh` first). Web: `pnpm -C apps/web vitest run <files>` and
   `pnpm -C apps/web typecheck` from your worktree (run `pnpm install --frozen-lockfile`
   in the worktree first if node_modules is missing).
5. **Update the memory** (`update_memory`) with: fixed / not changed and why, the commit sha,
   the test name.

## Hard constraints

- **Nothing hardcoded per business.** Wording comes from that business's own data:
  `apps/api/tenancy/caller_words.py` (server) / `callersWord` (web), the capability profile
  (`GeneratedCopy.capabilities`), business outcomes, the agent's own script/job, console
  settings. "Hot lead", "booking", "order", "patient", "prices", "deliver" etc. are findings
  wherever a business may not have that concept.
- **Never hand-write Telugu or Hindi (or any Indian-language) words.** Move existing lists
  into founder-owned JSON data files beside `spoken_style.json` (same loader pattern), keep the
  existing content as-is in the data file (moving is fine; inventing is not), and list in your
  final report every line the founder must write. Where a line is missing, fall back safely
  (say the stored sentence, skip a check, or use English only where that is safe) and say so.
- Client screens: plain short lines (~60 chars), buttons not paragraphs, no ids/backticks/
  provider names, truthful states, nothing cut off at 1440px, works at 375px.
- Hard rules 1–13 bind. Money NUMERIC INR, times IST, no PII in logs.
- **Migrations:** only if unavoidable; set `down_revision = "e3b8d1f6a924"`; the merger
  re-chains. RLS in the same migration for any new tenant table.
- **Stay inside your lane's files.** If a fix needs a file another lane owns, do not edit it:
  write the needed change in your final report under "Needs another lane".
- Run `ruff check`, `ruff format`, `mypy apps packages`, `lint-imports` (Docker) and web
  typecheck/lint on what you touch. If the API wire changes, regenerate OpenAPI
  (`PYTHONPATH=/app /opt/venv/bin/python -m scripts.check_openapi_fresh --write` in Docker)
  and `pnpm -C apps/web gen:api` — note it in your report so the merger re-runs it.
- **UI proof:** the shared dev server on :3000 runs the MAIN checkout, not your worktree. For
  screens you change, render them headless from your worktree (vitest render → HTML →
  `C:/Users/jumes/AppData/Local/Temp/claude/a50a3f0a872c1724/0c51a750-0b23-4950-961e-84972febca40/scratchpad/shots/shoot-main.mjs`
  pattern) at 1440 and 375, or start your own `next dev -p <your port>` from the worktree.
  Do not restart/stop/reseed the shared stack.
- Commit to your worktree branch with messages ending
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push. Do not run the full
  suite or coverage ratchet (the merger does).

## Founder decisions already made (5 Nov 2026)

- D-971 woven-notice opening rewrite goes live automatically, WITH a visible "what changed"
  and an Undo on the Script tab (finding A-05).
- Free-trial test calls stay as they are: the "This number is my own" tick only (OB-7 is
  not to be changed).
- A lead = a caller who reached interested/hot/won (`crm/lead_definition.py`, Meta
  cost-per-lead model). Test calls must not count.

## Lane ownership (who may edit what)

| Lane | Scope | Owns |
|---|---|---|
| A Pip | report 4 all; report 2 Pip items (A-06, A-07 Pip side); founder F-1 (step list: refused-then-repaired shown as failure, changed-fields list shown 3×, "saved as a draft" said before autosave) | `apps/api/copilot/**`, `apps/web/src/components/copilot/**`, `apps/web/src/lib/copilot/**`, `docs/COPILOT-*.md` |
| B Agent script & knowledge | report 2 all non-Pip items (A-01..A-05 incl. Undo, A-08..A-11, rest), knowledge screens | `apps/api/agents/script_*.py`, `apps/api/agents/opening_*.py`, `apps/api/agents/field_suggestions.py`, `apps/api/agents/caller_help.py`, `apps/api/agents/agent_pass.py`, `apps/workers/script_*.py`, `apps/workers/opening_*.py`, `apps/workers/field_suggestions.py`, `apps/workers/caller_help.py`, `apps/api/kb/**`, `packages/shared/src/calevate_shared/opening_notices.py`, the notice-joining code in `packages/shared/src/calevate_shared/engine.py`, `apps/web/src/app/c/[slug]/agents/**` (except `CallHandling`/patient-caller UI owned by D), `apps/web/src/app/c/[slug]/knowledge/**`, `apps/web/src/lib/api/script.ts`, `lib/api/kb*.ts` |
| C Call pipeline & workers | report 5 all | `apps/voice-runtime/**`, `apps/workers/` post-call/outbox/dispatcher/caller-memory/extraction/turn checks/call quality/after-call/retention/settings, `apps/api/insights/**`, `apps/api/agents/call_mistakes.py`, `apps/api/agents/turn_checks.py`, `apps/api/caller_memory*`, `apps/api/reliability/**`, `apps/api/core/queue.py`, `scripts/vps-deploy.sh`, `compose.prod.yml`, and new founder-owned word-list data files for those heuristics |
| D Dynamic per business | report 6 all (G1 neutral fallback + per-agent job, G2 trade tables, G3 prompt examples, G4 hand-written languages outside C/B files, G5 language gaps incl. staged-language opt-out, G7 fallbacks, G8 prices in code, G9 guards) | `apps/api/tenancy/business_copy.py`, `apps/api/tenancy/caller_words.py`, `apps/api/agents/business_fit.py`, `apps/api/agents/handoff.py`, `apps/api/agents/test_conversations.py`, `apps/api/agents/patient_caller.py`, `apps/api/agents/languages.py`, `apps/api/agents/starters.py`, `apps/api/compliance/**`, `packages/shared/src/calevate_shared/extraction.py`, `.../lead_fields.py`, other `calevate_shared` language data, `apps/web/src/lib/verticalExamples.ts`, `apps/web/src/lib/useVerticalExamples.ts`, `apps/web/src/lib/businessCapabilities.ts`, `apps/web/src/components/patientCallerRow.tsx`, `apps/api/billing/ai_quota.py`, guard scripts/tests for hardcoding |
| E Campaigns, calls, leads, dashboard, notifications | report 3 all; report 6 G6 wording on these screens; founder: "Hot lead" hardcoded in Needs attention, the bell, notifications and emails — must use the business's own words (e.g. Rytu Khata has no hot leads) | `apps/api/crm/**`, `apps/api/campaigns/**`, `apps/api/analytics/**`, `apps/api/notifications/**`, `apps/workers/` notification/digest/alert/email workers (`notifications.py`, `owner_digest.py`, `team_alerts.py`, `campaign_dispatch.py`), email templates, `apps/web/src/app/c/[slug]/` dashboard files, `attention/**`, `campaigns/**`, `calls/**`, `leads/**`, `performance/**`, `follow-ups`, `call-backs`, `apps/web/src/components/notifications/**`, `apps/web/src/lib/api/` for those areas |
| F Onboarding & billing | report 1 all (except OB-7, decided) | `apps/api/go_live/**`, `apps/api/billing/**` (except `ai_quota.py`), `apps/api/payments*`, `apps/api/numbers/**`, `apps/api/first_run/**`, `apps/api/authn/**`, `apps/api/tenancy/signup.py`, `apps/web/src/app/c/[slug]/billing/**`, `go-live`, `verify-business/**`, `numbers`/`phone-numbers`, `settings/**`, `agents/first/**`, `apps/web/src/app/(auth)`/sign-in/signup, `components/authn/**`, `components/forwarding/**`, `scripts/seed_dev.py` |
| G Admin console | report 7 all | `apps/web/src/app/admin/**`, `apps/api/admin/**`, `apps/api/ops/**`, `apps/web/src/lib/api/admin*.ts` |

Shared files (`apps/web/src/lib/api/schema.d.ts`, `openapi.json`, `apps/workers/settings.py`
registrations, `docs/ROADMAP.md`): edit only if your fix needs it; the merger resolves.

## Final report (your last message)

Per finding ID: fixed / not changed + why, commit, test. Then: files changed, migrations,
wire changes, "Needs another lane", founder inputs needed (exact lines), what you could not
verify.
