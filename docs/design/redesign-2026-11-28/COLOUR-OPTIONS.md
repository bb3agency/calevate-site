# Colour direction: open founder decision (28 Nov 2026)

Status: OPEN. The founder asked to document the options and decide later. Until then the
redesign lanes keep today's token values; every screen reads colours from the tokens in
`apps/web/src/app/globals.css`, so the chosen palette lands later as a token change.

## Why the colours are changing
Founder, 28 Nov 2026, after building the same agent on Outpero and Calevate side by side
(docs/evidence/outpero-vs-calevate-2026-11-28/): "we are lacking proper colours … it's white and
green only". Outpero uses violet, off-white and light grey and looks better. The founder said not
to copy them ("we can be creative") and rejected "forest green + warm off-white + warm accent" as
the same structure as Outpero's (off-white + grey + one strong hue).

Binding earlier decisions any option must keep:
- No large dark panels in the first run (founder, 23 Oct 2026, rememory f0b9ae8b).
- Dark mode stays dormant (D-471); design the light palette.
- REDESIGN-2 system (approved 10 Oct, docs/design/REDESIGN-2.md): calm, hairlines, one filled
  action per view, type roles, 4px grid. A new palette evolves it, not replaces it.
- WCAG AA contrast; the axe browser test runs both palettes and never skips.

## The options shown to the founder

| | Direction | Page | Brand / type | Second colour | Shape and feel |
|---|---|---|---|---|---|
| A | Khata ledger | paper cream #FBF6EA with faint ruled lines #E9DFC8 | ink navy #1E2B3C for type and the main button; green #15803D for money and success | vermilion #C2410C as a "stamp" accent (outlined, slightly rotated tag) | serif headings, square-ish 4px corners; feels like the account book Indian shop owners keep |
| B | Bazaar blocks | crisp white | black type, black 2px outlines | bold flat tiles per job: emerald #0E9F6E, turmeric #F2B705, terracotta #C8553D | big rounded tiles, loud and friendly, like a market sign |
| C | Monsoon | mint wash #EEF6F3 | teal-green #0F766E brand, deep teal #0B3B36 type | rain-sky blue #38A3D1 (tint #CDE8F6) | pill shapes, soft round corners; calm and fresh, no off-white, no grey |
| — | Today | white #FFFFFF, app #FAFAFA | near-black #171A1C, one bright green #16A05D | none | slate greys #E2E8F0 / #475569 |

Mix-and-match and "none of these" were also offered.

## How the decision will be applied
1. Map the chosen palette onto the existing token names (brand, brand-strong, brand-soft, app,
   surface, surface-muted, line, text, text-muted, status, series) plus any new role a direction
   needs (A: stamp accent; B: job tile colours; C: secondary blue).
2. Fix the hard-coded colours listed in PLAN.md §8 so they follow the tokens.
3. Check contrast numerically and in the browser on sign-in, dashboard, agents, an agent page,
   a campaign page, first run and a call page; run test:a11y-browser.
