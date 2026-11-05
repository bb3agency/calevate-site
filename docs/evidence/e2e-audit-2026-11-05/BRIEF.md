# End-to-end audit, 5 Nov 2026: shared brief for every lane

The founder asked for a full audit of every part of Calevate before it goes live with paying
clients: **map everything first, gather information from sources, research, then correct and
build.** This is PHASE 1: map, research, find. **No code changes in phase 1** — each lane
writes only its own file in this folder. Fixes come in phase 2, planned from these files.

## Why this exists (real failures found on the live account in one day)

Rytu Khata (a farmer/shop accounting app) uses a Telugu outbound agent, Varsha, to call people
who just registered for the app, to check whether they have doubts. On 5 Nov 2026 alone the
founder hit, on production:

- A caller's "I'll try" (Telugu) listed as a question the agent failed to answer.
- Pip (the dashboard copilot) asked to rewrite the script: refused its own Telugu, then said
  "applied" when nothing was applied.
- "Fix them first" on Put it live replaced the opening line with nothing.
- Lead-detail suggestions offered "Main crops grown" to a support agent.
- A deploy-time cleanup job that was handed off but never ran.

Every one was found by the founder, not by us. Your job is to find the rest first.

## Founder's standing rules (each one is a finding if broken)

1. **Nothing hardcoded per business.** Calevate is a multi-tenant SaaS for any Indian small
   business. Never clinic-centric, never real-estate-centric, never Rytu-Khata-centric. Any
   business-specific example, word list, field, label, default or prompt line baked into code
   is a finding. Dynamic per business = derived from that business's own data (profile, script,
   knowledge, capability profile `GeneratedCopy.capabilities`, `caller_words`, AI-written copy).
2. **Never hand-write Telugu or Hindi** in code. Spoken words come from the founder
   (`spoken_style.json` and similar data files) or from the model at runtime.
3. **No provider names on client screens** (ThinnestAI, Gemini, Sarvam, Cartesia, Azure…).
4. **Plain language for non-technical owners.** Short lines (~60 chars), buttons not
   paragraphs, explanations behind a "Why?" tap. No internal ids, field keys, backticks, codes.
5. **Nothing chopped off at desktop width; mobile-optimised everywhere (375px).**
6. **Truthful UI.** Never claim something happened that did not; a failed read is never shown
   as "all clear"; errors say what to do.
7. **DON'T ASSUME.** Every finding cites file:line, a screenshot path, or a request/response
   you actually observed. A vendor/regulator/library claim cites a primary source you read this
   session (URL + date). "Probably" is not a finding — verify or label UNVERIFIED.

Also binding: `CLAUDE.md` (hard rules 1–13) and `docs/` (the blueprint).

## How to look

- **Read the code** for your area (routes, screens, workers, prompts). Use the rememory MCP
  (`search_code`, `search_memory`, project `calevate`) before reading whole files.
- **Drive the real app headless** where your area has screens: web dev server
  `http://localhost:3000`, real API `http://localhost:8000` (seeded account `sunrise-homes`,
  a real-estate business; owner login is in `scripts/seed_dev.py` — local test values; never
  print them in your file). Use `playwright-core` from `apps/web/node_modules` with headless
  Chromium; example scripts: `C:/Users/jumes/AppData/Local/Temp/claude/a50a3f0a872c1724/0c51a750-0b23-4950-961e-84972febca40/scratchpad/shots/shoot-main.mjs`.
  Check 1440px and 375px. Save screenshots under
  `C:/Users/jumes/AppData/Local/Temp/claude/a50a3f0a872c1724/0c51a750-0b23-4950-961e-84972febca40/scratchpad/audit/<lane>/`.
  **Do not restart, stop or reseed** the dev server, API container or databases — other lanes
  share them. Read-only use; harmless writes inside the seeded account (saving a draft, adding
  a test lead) are fine.
- **Never run Python on the Windows host.** Python goes through Docker (see
  `scratchpad/lane/lane-tests.sh` usage in other docs; image
  `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` with volume `calevate-test-venv:/opt/venv`).
- **Research** where your area follows a standard (form UX, copilot/agent tool-use safety,
  outbound calling etiquette, TRAI/DPDP, SaaS onboarding, dashboards): web search, cite.
- Use the installed UI skills' guidance for UI judgement (`no-ai-design-slop`,
  `critique-information-density`, `ux-writing`).

## What to write: `docs/evidence/e2e-audit-2026-11-05/<lane>.md`

1. **Map** — every screen, route, button, job, prompt and data path in your area, as a table:
   what it is, where it lives (file), what it's for. This is the inventory phase 2 works from.
2. **Findings**, ranked. Each: `ID | severity (P0 breaks money/law/data or a core flow for a
   client; P1 wrong or broken but has a workaround; P2 confusing/ugly/slow; P3 polish) | where
   (file:line / screen) | what happens (observed) | what should happen | evidence | rule broken`.
3. **Research notes** — what the established standard is, with sources, where it changes a fix.
4. **Proposed fixes** — grouped so phase 2 lanes can take them without touching each other's
   files. Name the files each group touches.

Be exhaustive in your area; be honest about what you could not check and why. Keep the file
plain and scannable. Return a short summary (counts by severity, top 5 P0/P1) as your final
message.
