# Colour direction (28 Nov 2026)

Status: **DECIDED — A, "Khata ledger"**. Decided by Claude on 28 Nov 2026 under the founder's
rule of the same day ("be creative, never copy Outpero, don't ask — decide"; rememory 729dfe15).
Built in `apps/web/src/app/globals.css`; screenshots in `shots/colour-*`.

## Why the colours changed
Founder, 28 Nov 2026, after building the same agent on Outpero and Calevate side by side
(docs/evidence/outpero-vs-calevate-2026-11-28/): "we are lacking proper colours … it's white and
green only". He said not to copy Outpero ("we can be creative") and rejected "forest green + warm
off-white + warm accent" as the same structure as Outpero's (off-white + grey + one strong hue).

Binding earlier decisions the palette keeps:
- No large dark panels anywhere (founder, 23 Oct 2026, rememory f0b9ae8b).
- Dark mode stays dormant (D-471). The `.dark` block still compiles and passes its contrast
  tests; only two series marks were lifted there so the outcome dots stay at 3:1.
- REDESIGN-2 (docs/design/REDESIGN-2.md): calm, hairlines, one filled action per view, type
  roles, 4px grid, no resting shadows.
- WCAG AA; `tests/contrast.test.ts`, `tests/contrastTokens.test.ts` and the real-Chromium axe
  gate (`test:a11y-browser`) recompute it from the stylesheet.

## What A is, and how it differs from what was rejected
The account book every Indian shop keeps: cream paper, navy ink, green for money, a vermilion
stamp. What makes it not "off-white + grey + one strong hue":
- the neutrals are paper and ink, not grey: no slate token is left in the light palette;
- the main button is **ink**, and green is held back for meaning (money, success, live, done);
- the second colour is a **stamp**, an outlined mark used once per view, never a fill;
- the one texture, ruled paper with a red margin line, exists only on blank pages (a first-use
  empty state, the first-run brief card), never on a data screen.

Choices made while building it:
- **No serif titles.** The direction table offered serif headings; cream + serif display +
  warm accent is the most common generated-design look (frontend-design skill, trait 1), so the
  ledger character is carried by ink, stamp and ruling instead, and Nilo stays for everything.
- **Vermilion, not terracotta.** #B5401B is redder and deeper than the clay accent that reads
  as a generated default, and is kept apart from danger (crimson) and warn (ochre).
- **Tertiary text actions stay green** (`TEXT_ACTION`): they are the brand's voice in a row
  ("Change", "Show"), and turning them ink would make them indistinguishable from labels.

## Final palette (light)

Ratios are WCAG 2.x contrast. "Surface" is #FFFCF4, "app" #F9F3E4, "muted" #F4ECD9.

| Token | Hex | Role | Contrast |
|---|---|---|---|
| `--app` | #F9F3E4 | page and shell behind content (paper) | — |
| `--surface` | #FFFCF4 | the sheet content sits on | — |
| `--surface-muted` | #F4ECD9 | read-only well, inline status | — |
| `--line` | #E6DBC2 | hairlines and borders | 1.34 on surface (decorative) |
| `--ledger-rule` | ink at 8% | ruling of `.ledger-surface` | decorative |
| `--text` | #1E2B3C | navy ink: text, headings | 13.97 surface · 12.94 app · 12.17 muted |
| `--text-muted` | #4D4A45 | warm graphite: secondary text | 8.60 · 7.97 · 7.50 |
| `--text-faint` | #655F56 | hints, captions | 6.16 · 5.71 · 5.37 (1.40 apart from muted) |
| `--action` | #1E2B3C | the one main button | label `--on-action` #FFFCF4 13.97 |
| `--action-hover` | #121C2A | its hover/pressed | label 16.72 |
| `--on-action` | #FFFCF4 | label on the main button | — |
| `--brand` | #1F8A4C | logo green; fills, dots, bars (never under white text) | 4.27 surface · 3.95 app (non-text ≥3) · white on it 4.38 |
| `--brand-strong` | #14683A | green text; filled done marks with white | 6.67 surface · 6.18 app · 5.86 on brand-soft · white on it 6.84 |
| `--brand-deep` | #0F5530 | pressed green | — |
| `--brand-bright` | #2FB36A | live pip | non-text |
| `--brand-soft` | #E5F1E0 | tint behind a done mark | — |
| `--accent-stamp` | #B5401B | vermilion stamp: tag, selected step, one highlight | 5.52 surface · 5.11 app · 4.81 muted · 4.77 on stamp-soft |
| `--accent-stamp-soft` | #FBE8DE | stamp ground | — |
| `--accent-stamp-line` | #E9B9A4 | stamp border, ledger margin rule | decorative |
| `--warn` / soft / line | #86500A / #FBF0D4 / #ECD59C | needs a look (ochre ink) | 6.47 surface · 5.99 app · 5.85 soft |
| `--danger` / soft / line | #A81E32 / #FBE9E6 / #F0C3BD | failed, refused (crimson) | 7.07 · 6.55 · 6.18; white on it 7.25 |
| `--success` / soft / line | #17643A / #E7F2E2 / #BCDCBF | done, paid | 7.01 · 6.50 · 6.23 |
| `--info` / soft / line | #1F4F8F / #E9EFF6 / #C3D3E8 | neutral news, in progress | 7.96 · 7.37 · 7.05 |
| `--chart-warn` | #E0A526 | chart mark | marks only |
| `--chart-danger` | #D64A3E | chart mark | marks only |
| `--chart-neutral` | #D5CAB2 | chart mark | marks only |
| `--series-1..6` | #1F8A4C, #2F4D73, #C4501E, #18788C, #A87A12, #7D3F78 | green, ink, vermilion, teal, ochre, plum | 4.27, 8.43, 4.54, 4.99, 3.75, 7.18 on surface (all ≥3) |

Series separation: smallest OKLab distance between any two series is 10.8 (ΔE×100). Not
re-run through a colour-vision-deficiency simulator; see "Not verified".

Elevation (overlays only): the same three layered steps, shadow tinted warm sepia
`rgb(64 46 20 / …)` instead of slate, so a menu on cream does not look dirty.

## Utilities
- `ledger-surface`: surface + faint ruling every 1.75rem + one vermilion margin rule at
  2.25rem. Only for a first-use empty state (`components/console/emptyState.tsx` applies it)
  and the first-run brief card (lane 1's file). Never on tables, lists or data screens.
- `stamp` (+ optional `stamp-tilt`, −2°): an outlined vermilion tag at 11px, 600 weight.

## Where it is applied
- Primary buttons (`PRIMARY_BUTTON`, `_LG`, `_SM`, `SplitButton` chevron, the wizard footer,
  the audio player's play button, the update notice, marketing CTAs): ink with paper label.
- Wizard rail: the step you are on is stamped (vermilion outline on stamp-soft).
- Neutral washes (`hover:bg-black/5`, scrims, skeletons) moved to ink alpha in the kit.
- PLAN.md §8 literals fixed: successRipple, UpdateWatcher fallbacks, collapsible-banner,
  floating-label, otp-input, live-activity, load-more, section.tsx, modelLogo, iconTile,
  routeLoading, button-group, the Wide/Mobile switch.

## Left for the screen lanes (their files, PLAN.md §10)
- Lane 1 (`agents/first/**`): the brief card should take `ledger-surface`; step bars and the
  current-step chip use `bg-brand-strong` (green = done) — the current step should use the
  stamp tokens, done steps stay green.
- Lane 2 (`agents/[agentId]/**` sections): no literals found; re-check the tab underline.
- Lane 3 (`campaigns/**`, `script/**`): `StartCampaign.tsx` `var(--danger, #b91c1c)` fallback
  (drop the literal); `CampaignScreen.tsx:314` "Set up" tab accent `bg-brand-strong text-white`
  (should be `bg-action text-on-action`, or no fill); `FoldSection` TONE uses `series-*` as
  section identity — the series moved (ink, teal, plum), so re-check that the five folds still
  read as distinct; `ScenarioFlow.tsx` / `FlowCanvas.tsx` connector dots `bg-brand-strong`
  are fine (marks).
- Lane 4 (`ClientSidebar.tsx`, `ClientShellFallback.tsx`): the selected nav item is
  `bg-brand-soft text-brand-strong`; in this palette a selection is not "done", so consider
  `bg-ink/[0.06] text-ink` with a stamp-coloured left rule.

## Not verified
- No colour-vision-deficiency simulation of the series or status set.
- Real-device viewing (low-end Android at outdoor brightness) of the cream ground.
- Screens were seen against a schema-synthesised mock API, not real data (the mock invents
  contradictory states, e.g. an archived campaign with both Start and Restore showing).
- The sign-in page itself: local dev auth signs straight in, so `shots/` has the public home
  page instead (`colour-home-*`); sign-in uses the same tokens and kit buttons.
