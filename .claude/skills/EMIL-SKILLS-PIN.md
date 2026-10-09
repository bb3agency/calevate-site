# Emil Kowalski UI skills: pinned vendor copy

- **Source:** https://github.com/emilkowalski/skills
- **Pinned commit:** `e8a175de22ae1e49370fc144c1f3bb9aeedf988d` (2026-10-02, "Add break ui skill")
- **Installed:** 2026-10-09, founder-approved
- **Licence:** MIT, Copyright (c) 2026 Emil Kowalski. The full text is in `EMIL-SKILLS-LICENSE` beside this file.
- **Method:** `git clone` into a scratch folder, copied by hand, byte-identical to the pinned commit (`diff -r` clean). No `npx skills` or other installer was used.

## Installed skills

Each folder is copied exactly as published: `SKILL.md` plus its reference files.

| Skill | Files |
| --- | --- |
| emil-design-eng | SKILL.md |
| animate | SKILL.md, RECIPES.md |
| review-animations | SKILL.md, STANDARDS.md |
| improve-animations | SKILL.md, AUDIT.md, PLAN-TEMPLATE.md |
| find-animation-opportunities | SKILL.md |
| animation-vocabulary | SKILL.md |
| apple-design | SKILL.md |
| pick-ui-library | SKILL.md |
| prototype | SKILL.md, PICKER.md |
| mobile-native | SKILL.md |
| break-ui | SKILL.md, CATALOG.md |
| ask-sonner | SKILL.md, API.md |

Not installed (the upstream repo has them, but they are not for this web app): `animate-expo` (React Native) and `write-swift`.

## Review

Every file at the pinned commit was read and reviewed for executable content. They are plain Markdown instructions and examples. There are no scripts, hooks, `settings.json`, executables, automatic network fetches, permission or settings changes, or prompt-injection text. The only frontmatter keys besides `name` and `description` are `disable-model-invocation: true`, on `pick-ui-library`, `prototype` and `review-animations`. That key means only the user can invoke those three skills.

Before you update, re-clone at the new commit, review the diff file by file, and then update the commit above.
