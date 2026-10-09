# Design skills (garden, MengTo, Owl-Listener): pinned vendor copies

Installed 2026-10-10 for UI redesign #2, at the founder's request. The method is the same
as `EMIL-SKILLS-PIN.md`:
- fetched at a pinned commit through the GitHub API;
- only Markdown copied;
- byte-for-byte as published;
- no installer used.

| Source | Pinned commit | Licence |
| --- | --- | --- |
| https://github.com/ConardLi/garden-skills | `aaf9a82f5efd73e87cc0998edc398e75bfc35901` (2026-07-12) | MIT, `GARDEN-SKILLS-LICENSE` |
| https://github.com/MengTo/Skills | `83a47fee32f0b6349bff1fede99257a5ef03dc93` (2026-10-06) | MIT, Meng To, `MENGTO-SKILLS-LICENSE` |
| https://github.com/Owl-Listener/designer-skills | `9a6930cf84a822eb458624bd11c61aac5bbdf224` (2026-09-05) | MIT, MC Dean, `OWL-SKILLS-LICENSE` |

## Installed

- **garden `web-design-engineer`:**
  - `SKILL.md`;
  - `references/` block-library, browser-acceptance, critique-guide, design-calibration, design-directions, failure-patterns and redesign-protocol;
  - style recipes `INDEX`, `stripe-press` and `notion-pre-ai`. These match the founder's chosen direction, "calm and plain".
- **MengTo:** `no-ai-design-slop` (with `ARTICLE.md` and `REFERENCES.md`), `audit-ai-design-slop` (with `REFERENCES.md`) and `beautiful-shadows`.
- **Owl-Listener:**
  - visual-hierarchy, spacing-system, typography-scale, color-system, data-visualization, responsive-design, readable-measure;
  - form-design, error-handling-ux, loading-states, feedback-patterns, navigation-patterns, onboarding-design;
  - ux-writing;
  - critique-information-density, critique-visual-hierarchy, critique-typography;
  - design-token, component-spec.

  Each is `SKILL.md` only.

## Deliberately not installed

- **garden `references/advanced-patterns.md`.** It holds standalone-HTML prototype recipes that load React and Chart.js from a CDN through `<script>` tags. In this Next.js app that would mean a new dependency and a CSP change. The garden `SKILL.md` still mentions it, and still describes CDN/Babel prototypes. **In this repository the app's own stack wins:** Next.js App Router, Tailwind v4 tokens in `globals.css`, the shared kit in `components/ui.tsx` and `components/console/`, and no CDN scripts.
- **The other 22 garden style recipes.** They don't match the chosen direction.
- **MengTo `tailwindcss`:** generic examples on default indigo, the look being removed. **`number-details`:** decorative 01/02/03 markers. **`product-proof-saas`** and **`operational-enterprise-ai`:** marketing landing pages. **`design-first-ui-prompting`:** prompting for generators. **Every `demo/` folder:** HTML and JPG files.
- **The other ~90 Owl skills**, which cover research, ops, strategy and design laws, and that repo's `.claude-plugin` and `.gemini` configs.

## Review

- Every file was scanned for executable or steering content: shell blocks, installers, network fetches, script tags, credential words, and "ignore previous / system prompt" phrasing.
  - The only hits were "token" in the design-token sense.
  - Code samples were HTML/JS in `tailwindcss` and `advanced-patterns.md`, both excluded.
- `REFERENCES.md` files are plain lists of public links: X posts, NN/g, Material, the Apple HIG, GOV.UK.
- The frontmatter keys are only `name` and `description`.

Before you update, re-fetch at the new commit, review the diff file by file, and update the commits above.
