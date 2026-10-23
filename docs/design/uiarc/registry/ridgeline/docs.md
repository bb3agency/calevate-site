# Ridgeline

> Overlapping distributions, one ridge per group: hover to lift a ridge and read its quartiles, switch datasets and every curve morphs.

- Type: Component (data)
- Access: Free, open source
- Page: https://uiarc.dev/components/ridgeline
- Markdown: https://uiarc.dev/components/ridgeline/markdown
- Registry item: https://uiarc.dev/r/ridgeline.json
- Source file: `registry/components/ridgeline/ridgeline.tsx`
- Dependencies: motion
- Keywords: data, chart, new, ridgeline, joy plot, joyplot, density plot, distribution, kde, quartiles

## When to use

- Seasonal or categorical distributions such as temperatures by month or response times by region.
- Showing where two groups differ in shape, such as bimodal winters.

## When not to use

- Use beeswarm when each individual observation matters.
- Use bar-chart when only one summary number per group matters.

## Installation

### CLI

Run one of these in a project set up with `shadcn init`:

```bash
npx shadcn@latest add @uiarc/ridgeline
pnpm dlx shadcn@latest add @uiarc/ridgeline
yarn dlx shadcn@latest add @uiarc/ridgeline
bunx --bun shadcn@latest add @uiarc/ridgeline
```

The `@uiarc` name needs `"registries": { "@uiarc": "https://uiarc.dev/r/{name}.json" }` in `components.json`. Without it, use the full URL:

```bash
npx shadcn@latest add https://uiarc.dev/r/ridgeline.json
```

### Manual

1. Install the dependencies:

```bash
npm install motion
```

2. Copy the source into your project. Main file: `registry/components/ridgeline/ridgeline.tsx`

   The source is in the registry item: https://uiarc.dev/r/ridgeline.json

3. Arc imports use the `@/` alias for `registry/` and `lib/`. Keep the same folders or update the import paths.

## Usage

```tsx
import { Ridgeline } from "@/components/arc/ridgeline/ridgeline";

export function Latency({ regions }: { regions: { id: string; label: string; values: number[] }[] }) {
  return <Ridgeline series={regions} label="API latency by region" unit=" ms" />;
}
```

## API reference

### Ridgeline

A ridgeline (joy) plot: one smoothed distribution per row, overlapping like mountain ridges, tinted by median. Hover lifts a ridge above its neighbours to read its quartiles; switching datasets morphs every curve.

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `series` (required) | `{ id: string; label: string; values: number[] }[]` | – | One ridge per series, drawn top to bottom. Values are raw observations; the ridge is their kernel density. |
| `label` (required) | `string` | – | What is measured. Names the chart for assistive technology. |
| `unit` | `string` | – | Unit after each value, such as "°" or " ms". |
| `formatValue` | `(value: number) => string` | – | Formats values. Overrides unit. |
| `domain` | `[number, number]` | – | Value range of the axis. Fix it to keep the axis still across datasets. Defaults to the data with room on each side. |
| `overlap` | `number` | `2.4` | How far the tallest ridge rises into the rows above, in row heights. |
| `rowHeight` | `number` | `30` | Height of one row in pixels. |
| `bandwidth` | `number` | – | Smoothing in value units. Defaults to Silverman's rule per series. |
| `tint` | `boolean` | `true` | Shades each ridge by its median, from a light tint to the full first series color, with a stepped scale under the axis. |
| `active` | `string \| null` | – | Controlled id of the lifted ridge. |
| `defaultActive` | `string \| null` | `null` | Initial lifted ridge when uncontrolled. |
| `onActiveChange` | `(id: string \| null) => void` | – | Called when the lifted ridge changes. |
| `emptyLabel` | `string` | `"No data yet"` | Shown when there are no values. |
| `className` | `string` | – | Extra class on the root figure. |

## Keyboard interactions

| Keys | Action |
| --- | --- |
| ArrowUp / ArrowDown | Lifts the previous or next ridge. |
| ArrowLeft / ArrowRight | Moves the reading cursor along the values by one axis step. |
| Home / End | Lifts the first or last ridge. |
| Escape | Lowers the ridge and clears the reading. |

## Accessibility

- The plot is a focusable group; the lifted ridge's median, middle half, range, and count are announced through a polite live region.
- A visually hidden table lists median, quartiles, extremes, and count for every series.
- Every row is labelled in text; the median tint is backed by the table and tooltip.

## Motion

- Curves are sampled on a shared grid, so a new dataset or domain interpolates every point: ridges swell, slide, and split in one spring.
- The first reveal rolls the ridges in from the top row down.
- The lifted ridge is a copy drawn above the others that rises 6px on a spring, with its middle half shaded and its median marked.
- The tooltip glides after the pointer and stays inside the chart. Reduced motion draws final shapes immediately.

## Responsive behavior

- Label gutter and tick count adapt to width; the plot redraws at the measured size so strokes stay crisp.
- Touch taps lift a ridge and read at the tapped value.

## Performance

- Densities are computed once per dataset (96 samples per ridge); animation interpolates arrays and writes path strings directly.
- Suitable for up to a few thousand observations per series.

## Notes for AI

- Choose it to compare the shape of many distributions: spread, skew, and bimodality, not just averages.
- Pass raw observations, at least 20 per series, and fix domain when switching datasets so shapes move on a still axis.
- Keep rows to about 20; beyond that, use small multiples or a box plot.
- Colors come from the shared --series-1 to --series-4 tokens in foundation.css: series 1 is the accent itself and series 2 to 4 rotate its hue, validated all-pairs for color vision deficiency across every accent in light and dark. Override the tokens on any ancestor to rebrand.

## Related

- [Streamgraph](https://uiarc.dev/components/streamgraph/markdown): Layered streams on a wiggle baseline that morph between ranges, with a layer you can isolate and read week by week.
- [Line chart](https://uiarc.dev/components/line-chart/markdown): A multi-series line chart with a gliding crosshair, legend toggles, and paths that morph between ranges.
- [Activity heatmap](https://uiarc.dev/components/activity-heatmap/markdown): See a year of activity at a glance, one square per day.

## Also in charts

- [Bar chart](https://uiarc.dev/components/bar-chart/markdown): Compare one measure across days and scrub any bar for its value.
- [Donut chart](https://uiarc.dev/components/donut-chart/markdown): A donut whose arcs morph between datasets, with the active value rolling into the center.
- [Brush chart](https://uiarc.dev/components/brush-chart/markdown): A dense time series with an overview strip: drag a window to zoom, resize it by its handles, and read events in place.
- [Waffle chart](https://uiarc.dev/components/waffle-chart/markdown): A ten by ten unit chart where every cell is one percent, and cells fly to their new group when the data changes.
- [Slope chart](https://uiarc.dev/components/slope-chart/markdown): Before and after on two axes: lines draw in, rank moves sit beside each value, and switching datasets slides every line to its new slope.
- [Sparkline](https://uiarc.dev/components/sparkline/markdown): Show a compact trend beside a value.
- [Gauge](https://uiarc.dev/components/gauge/markdown): Show a value against a known range.
- [Animated counter](https://uiarc.dev/components/animated-counter/markdown): Give changing totals a clear sense of movement.
- [Treemap](https://uiarc.dev/components/treemap/markdown): A squarified treemap: click to drill and the tiles grow to fill the view, with a breadcrumb back and metrics that morph every tile.
- [Split bar](https://uiarc.dev/components/split-bar/markdown): A single 100% bar split into shares: rest on a segment to widen it and read its exact figures, toggle segments from the legend and the rest reflow, with labels inside when they fit and on leader lines when they don't.

## Guidance for AI tools

Ridgeline: Overlapping distributions, one ridge per group: hover to lift a ridge and read its quartiles, switch datasets and every curve morphs. Follow the declared prop types and do not invent props. Keep keyboard access, reduced motion support, and both light and dark themes intact when adapting it.

Full library index: https://uiarc.dev/llms.txt
