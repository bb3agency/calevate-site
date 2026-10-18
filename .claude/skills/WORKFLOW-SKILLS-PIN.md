# Workflow and design skills (wshobson, Vercel, Anthropic, taste-skill): pinned vendor copies

Installed 2026-10-19 at the founder's request. The method is the one `DESIGN-SKILLS-PIN.md` uses:
- each repository cloned read-only at the commit below;
- skill folders copied byte for byte;
- no installer run (`npx skills add`, `install.sh` and `skill.sh` were read and not used).

| Skill folder here | Source | Pinned commit | Licence |
| --- | --- | --- | --- |
| `responsive-layout-patterns` | https://github.com/wshobson/agents `plugins/ui-design/skills/responsive-design` | `0874a27b17a22e2b7c2e2bcd725768e0803cad06` | MIT, Seth Hobson, `WSHOBSON-SKILLS-LICENSE` |
| `modern-javascript-patterns` | same repo, `plugins/javascript-typescript/skills/modern-javascript-patterns` | same | same |
| `nextjs-app-router-patterns` | same repo, `plugins/frontend-mobile-development/skills/nextjs-app-router-patterns` | same | same |
| `vercel-react-best-practices` | https://github.com/vercel-labs/agent-skills `skills/react-best-practices` | `063bee94c3f4df8453406c830b0a7df0f2860278` | MIT (the README's License section and the SKILL.md frontmatter; the repo ships no LICENSE file) |
| `frontend-design` | https://github.com/anthropics/skills `skills/frontend-design` | `dbd4588f9e1033efb41dad4bef2f7947c8993d44` | Apache 2.0, `frontend-design/LICENSE.txt` |
| `design-taste-frontend` | https://github.com/Leonxlnx/taste-skill `skills/taste-skill` | `f624f37a8c650b9cc550253104925efe4c8de246` | MIT, Leonxlnx, `TASTE-SKILL-LICENSE` |

## Deviations from byte for byte

- **`responsive-layout-patterns`:** the folder and the frontmatter `name:` were renamed from `responsive-design`. Owl-Listener's `responsive-design` (see `DESIGN-SKILLS-PIN.md`) already uses that name. Nothing else changed.
- **`vercel-react-best-practices`:** copies `SKILL.md`, `AGENTS.md`, `metadata.json` and `rules/`. It leaves out `README.md`, which is that repo's build guide for the skill (`pnpm install`).

## Where the repo wins

`CLAUDE.md` and `docs/` take precedence over every skill. These rules do not apply here:

- **`client-swr-dedup` and the Next.js skill's Server Actions advice.**
  - Data on the client goes through the generated OpenAPI client and TanStack Query, never SWR.
  - Mutations go to the FastAPI api. There is no `"use server"` in `apps/web`.
- **`modern-javascript-patterns`' `'use strict'`.** ES modules and TypeScript are already strict.
- **`design-taste-frontend` (taste-skill) covers the public marketing pages only:** `/`, `/pricing`, `/industries`, `/solutions`, `/why-calevate` and the like. Its own description says it is not for dashboards or app screens. The admin console and the client dashboards keep the "calm and plain" direction in `DESIGN-SKILLS-PIN.md` and the shared kit in `components/ui.tsx`.
- **`frontend-design` and taste-skill both push for a distinctive look.** On existing screens, the Tailwind v4 tokens in `globals.css` are the brand. Pass `--keep palette,type` to taste-skill's draw and map the tokens onto its roles.
- **No CDN scripts and no new dependencies come from a skill's examples.**

## taste-skill's scripts (Node 22+, read before vendoring)

- **`scripts/draw.mjs`**
  - Reads `library/*.json` and writes a direction sheet to `.taste-skill/` (gitignored).
  - Keeps a history file at `~/.taste-skill/history.json`.
- **`scripts/lint.mjs`:** scans source files and writes nothing.
- **`scripts/inspect.mjs`** with `scripts/lib/cdp.mjs`, `probe.mjs` and `rules.mjs`:
  - starts a local Chrome or Edge in a temporary profile and drives it over the DevTools protocol;
  - serves local files on 127.0.0.1;
  - writes screenshots and `report.json` under `.taste-skill/inspect/`.
- **`scripts/assets.mjs`:**
  - the only script that uses the network;
  - fetches public, keyless APIs: Openverse, Wikimedia Commons, the Art Institute of Chicago, the Met, NASA images and archive.org;
  - downloads into the project with a credits file.

None of these scripts uses `exec` or a shell, reads environment secrets, or sends project content anywhere. The only environment it reads is the Chrome path and the home and program directories. The one `spawn` launches the browser.

Every found picture is credited on the page (D-679 still applies: no provider names on client screens; a photo credit is not a provider). Before running `assets.mjs` against a page, check that the licences it reports permit commercial use.

## Review

- **Scan:** every Markdown file was checked for shell blocks, installers, network fetches, script tags and "ignore previous / system prompt" phrasing.
- **Hits, all illustrative:**
  - `npx svgo` in one Vercel rule;
  - `<script src="https://example.com/…">` in the Vercel rules on deferring scripts;
  - the `node <skill>/scripts/…` commands in the taste-skill SKILL.md.
- **Links:** public documentation (react.dev, nextjs.org, MDN, web.dev, vercel.com and the like).

To update, re-clone at the new commit, review the diff file by file (for taste-skill, re-read every changed `.mjs`), and update the commits above.
