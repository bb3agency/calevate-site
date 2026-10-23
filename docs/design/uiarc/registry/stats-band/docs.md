# Stats band

> Headline numbers that count up in view, each with a tiny visual that proves it and a context line on hover, plain or in a hairline grid.

- Type: Block
- Page: https://uiarc.dev/components/blocks/stats-band
- Markdown: https://uiarc.dev/components/blocks/stats-band/markdown

- Access: Free, open source
- Registry id: `stats-band`
- Source file: `registry/blocks/stats-band/stats-band.tsx`
- Built from: Segmented control
- Keywords: stats, statistics, numbers, count up, counter, metrics band, social proof, kpi

Use this under a hero or between sections to back a claim with numbers. Replace the sample stats in stats-band-data.ts.

## When to use

- Marketing pages that back a claim with a few numbers.
- About and investor pages with headline metrics.

## When not to use

- Live product metrics with trends. Use Metric card or Metrics dashboard.
- More than four numbers. Split them or use a table.

## Installation

### CLI

Run one of these in a project set up with `shadcn init`:

```bash
npx shadcn@latest add @uiarc/stats-band
pnpm dlx shadcn@latest add @uiarc/stats-band
yarn dlx shadcn@latest add @uiarc/stats-band
bunx --bun shadcn@latest add @uiarc/stats-band
```

The `@uiarc` name needs `"registries": { "@uiarc": "https://uiarc.dev/r/{name}.json" }` in `components.json`. Without it, use the full URL:

```bash
npx shadcn@latest add https://uiarc.dev/r/stats-band.json
```

### Manual

1. Install the dependencies:

```bash
npm install motion
```

2. Copy the source into your project. Main file: `registry/blocks/stats-band/stats-band.tsx`

   The source is in the registry item: https://uiarc.dev/r/stats-band.json

3. Arc imports use the `@/` alias for `registry/` and `lib/`. Keep the same folders or update the import paths.

## Usage

```tsx
import { StatsBand } from "@/components/arc/blocks/stats-band/stats-band";

export function Numbers() {
  return (
    <StatsBand
      layout="divided"
      stats={[
        {
          value: 2_334_000, notation: "compact", decimals: 1, label: "Deploys in the last 12 months",
          detail: "Across 12,400 teams", context: "Up from 1.4M the year before",
          visual: { kind: "trend", values: [141, 148, 139, 162, 171, 184, 196, 203, 221, 238, 257, 274] },
        },
        { value: 38, suffix: "ms", label: "Median response time", detail: "At the edge, worldwide" },
        { value: 35, label: "Edge regions on six continents", visual: { kind: "map", points: [[-122.4, 37.8], [-0.1, 51.5], [139.7, 35.7]] } },
      ]}
    />
  );
}
```

## API reference

### StatsBand

A band of three or four headline numbers, each with an optional tiny visual that proves it. Numbers count up in sequence as the band enters view, then the visuals draw in; hover or focus reveals one line of context.

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `stats` | `Stat[]` | `stats` | Each has value and label, plus optional prefix, suffix, decimals, notation ("compact" for 2.3M), detail, context (the hover line), and visual: a trend, uptime strip, latency distribution, or world map. Every visual is optional. |
| `layout` | `"plain" \| "divided"` | `"plain"` | plain lets the stats float on whitespace; divided sets them in a hairline grid ruled above and below. |
| `title` | `string` | – | Optional heading above the band. Without it the band is labelled "Key numbers". |
| `description` | `string` | – | Optional line under the heading. |
| `duration` | `number` | `1.6` | Seconds each number takes to count up. |
| `locale` | `string` | `"en-US"` | Number formatting locale. Fixed by default so server and client agree. |
| `className` | `string` | – | Extra class on the section. |

## Accessibility

- Stats are a description list: the label is the term, the number, detail, and context are its descriptions. Screen readers get both the detail and the context line.
- Stats with a context line are focusable, so keyboard and touch users reveal it too. Visuals are decorative and aria-hidden; the copy carries the meaning.
- Screen readers get the final formatted value once; the counting digits are aria-hidden.
- The section is labelled by the title or, without one, by "Key numbers".

## Motion

- Each number counts from zero with a strong ease out over 1.6s, staggered 90ms per stat, the first time the band is half in view.
- Digits are tabular and the final value reserves the width underneath, so nothing shifts while counting.
- Stats rise 8px and fade in; in the divided layout the top and bottom rules draw across and the hairlines grow between stats.
- Once a number has mostly landed, its visual draws in: the sparkline and map wipe in from the left, bars grow from the baseline in a short sweep, and the trend end dot settles last.
- Hover or focus cross-fades the detail line to the context line and gives that stat's visual the accent; the others stay neutral.
- Reduced motion shows final values, lines, and visuals at once.

## Responsive behavior

- One row of up to four stats, two columns below 760px container width, one column below 420px.
- Dividers reflow with the grid: vertical between neighbours, horizontal between rows.
- Number size scales with container width between 36px and 72px.

## Performance

- Counting writes text straight to the DOM from one Motion tween per stat; React does not rerender per frame.
- One IntersectionObserver for the band, disconnected after the first view.

## Notes for AI

- Use three or four stats with specific, verifiable numbers. Round numbers read as made up.
- Put units in suffix (%, ms, +, /5) so they render smaller and muted beside the number. Use notation: "compact" for large counts; it counts within its final unit.
- Give each stat a visual that proves the number, and a context line that compares it (up from, down from, p95). Leave both out for a plain numbers band.
- Place it under a hero or between a features section and testimonials.
- Edit stats-band-data.ts to replace the sample numbers.

## Related

- [Metric card](https://uiarc.dev/components/metric-card/markdown): A compact summary for a number that needs context.
- [Animated counter](https://uiarc.dev/components/animated-counter/markdown): Give changing totals a clear sense of movement.
- [Logo marquee](https://uiarc.dev/components/blocks/logo-marquee/markdown): A quiet, continuously moving row of brand marks with a pause control.

## Guidance for AI tools

Blocks are complete, self-contained screens with sample data. Replace the sample data and connect the callbacks described above. Follow the declared prop types and do not invent props. Keep keyboard access, reduced motion support, and both light and dark themes intact when adapting it.

Full library index: https://uiarc.dev/llms.txt
