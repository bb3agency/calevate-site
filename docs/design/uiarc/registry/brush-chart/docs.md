# Brush chart

> A dense time series with an overview strip: drag a window to zoom, resize it by its handles, and read events in place.

- Type: Component (data)
- Access: Free, open source
- Page: https://uiarc.dev/components/brush-chart
- Markdown: https://uiarc.dev/components/brush-chart/markdown
- Registry item: https://uiarc.dev/r/brush-chart.json
- Source file: `registry/components/brush-chart/brush-chart.tsx`
- Dependencies: motion
- Keywords: data, chart, new, brush chart, zoomable time series, chart with overview, range selector chart, focus and context chart, stock chart brush, d3 brush react, annotated line chart

## When to use

- Product analytics with a year or more of daily data.
- Incident reviews where events need to be read against a metric.
- Any chart where people ask to zoom into a stretch without losing context.

## When not to use

- Use line-chart for a few weeks of data or several series.
- Use sparkline for a small inline trend without interaction.
- Avoid it for data that dips below zero or needs a log scale.

## Installation

### CLI

Run one of these in a project set up with `shadcn init`:

```bash
npx shadcn@latest add @uiarc/brush-chart
pnpm dlx shadcn@latest add @uiarc/brush-chart
yarn dlx shadcn@latest add @uiarc/brush-chart
bunx --bun shadcn@latest add @uiarc/brush-chart
```

The `@uiarc` name needs `"registries": { "@uiarc": "https://uiarc.dev/r/{name}.json" }` in `components.json`. Without it, use the full URL:

```bash
npx shadcn@latest add https://uiarc.dev/r/brush-chart.json
```

### Manual

1. Install the dependencies:

```bash
npm install motion
```

2. Copy the source into your project. Main file: `registry/components/brush-chart/brush-chart.tsx`

   The source is in the registry item: https://uiarc.dev/r/brush-chart.json

3. Arc imports use the `@/` alias for `registry/` and `lib/`. Keep the same folders or update the import paths.

## Usage

```tsx
import { useState } from "react";
import { BrushChart } from "@/components/arc/brush-chart/brush-chart";

export function ActiveUsers({ days }: { days: { date: number; value: number }[] }) {
  const [range, setRange] = useState<[number, number]>([days[days.length - 90].date, days[days.length - 1].date]);
  return <BrushChart data={days} label="Daily active users" unit="users" range={range} onRangeChange={setRange}
    annotations={[{ date: Date.UTC(2026, 2, 24), label: "v2", description: "Offline mode and shared spaces" }]} />;
}
```

## API reference

### BrushChart

A detailed time series with an overview strip. Drag the window to pan, its handles to resize, or across empty track to draw a new one; double click resets. Zoomed out, a seven point average and band replace the raw line.

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `data` (required) | `{ date: Date \| number; value: number }[]` | – | Points in ascending time order. |
| `label` (required) | `string` | – | Names the chart for assistive technology. |
| `unit` | `string` | `""` | Unit after values in the tooltip and table. |
| `formatValue` | `(value: number) => string` | – | Formats values in the tooltip and table. |
| `formatTick` | `(value: number) => string` | – | Formats the value axis. Defaults to a compact number. |
| `formatDate` | `(date: Date) => string` | – | Formats dates in the tooltip and announcements. |
| `annotations` | `{ date: Date \| number; label: string; description?: string }[]` | `[]` | Events drawn as markers on both charts; labels show where they fit. |
| `range` | `[number, number]` | – | Controlled window as epoch milliseconds. A new value glides the window there. |
| `defaultRange` | `[number, number]` | – | Initial window when uncontrolled. Defaults to the whole series. |
| `onRangeChange` | `(range: [number, number]) => void` | – | Called while the window is dragged, resized, stepped, or reset. |
| `minSpan` | `number` | `7 days` | Smallest window in milliseconds. |
| `height` | `number` | `240` | Main plot height in pixels. |
| `overviewHeight` | `number` | `52` | Overview strip height in pixels. |
| `emptyLabel` | `string` | `"No data yet"` | Shown with fewer than two points. |
| `className` | `string` | – | Extra class on the figure. |

## Keyboard interactions

| Keys | Action |
| --- | --- |
| ArrowLeft / ArrowRight (plot) | Moves the crosshair between points in view. |
| ArrowLeft / ArrowRight (window) | Pans by a tenth of the window; Shift or PageUp and PageDown pan by half. |
| + / - (window) | Zooms in or out around the window's centre. |
| ArrowLeft / ArrowRight (handles) | Moves that edge by one point; Shift moves by ten. |
| Home / End | Moves the window or edge to the start or end. |
| Escape / 0 | Resets the window to the whole series. |

## Accessibility

- The window and both handles are sliders with dates as aria-valuetext.
- The plot is a focusable group; each reading is announced with its date, value, and any event on that day.
- A visually hidden table lists every point in the window with its event.
- Event markers pair the second series hue with a text label or tooltip; they never rely on color alone.

## Motion

- The line draws in from the left once, the first time it is seen.
- Dragging tracks the pointer 1:1; presets, resets, and controlled changes glide the window on a spring.
- The value axis springs to the tallest point in view, and the raw line crossfades with the smoothed trend as density changes.
- Reduced motion places the window directly and keeps the crosshair without travel.

## Responsive behavior

- Both charts fill their container; date ticks pick days, weeks, months, or years to fit the width.
- Handles have a 28 by 44px hit area for touch, and the strip keeps vertical page scroll free.
- Event labels are placed left to right and skip themselves when they would collide.

## Performance

- Past two points per pixel, each pixel column keeps only its low and high, so spikes survive and paths stay small.
- The overview path is built once per width; the rolling average is computed once per data change.
- Window moves re-render one component; a few thousand points stay smooth.

## Notes for AI

- Choose it for long daily or hourly series where people need both the whole history and a close look.
- Control range to sync presets (30D, 90D, 1Y) or other charts with the window.
- Use annotations for launches, incidents, and pricing changes; keep labels to a word or two.
- The value axis starts at zero, so it suits counts and totals rather than prices that hover far from zero.

## Related

- [Line chart](https://uiarc.dev/components/line-chart/markdown): A multi-series line chart with a gliding crosshair, legend toggles, and paths that morph between ranges.
- [Streamgraph](https://uiarc.dev/components/streamgraph/markdown): Layered streams on a wiggle baseline that morph between ranges, with a layer you can isolate and read week by week.
- [Sparkline](https://uiarc.dev/components/sparkline/markdown): Show a compact trend beside a value.
- [Date range picker](https://uiarc.dev/components/date-range-picker/markdown): A range picker that grows from its trigger into two months with presets and a stretching range highlight.

## Also in charts

- [Bar chart](https://uiarc.dev/components/bar-chart/markdown): Compare one measure across days and scrub any bar for its value.
- [Donut chart](https://uiarc.dev/components/donut-chart/markdown): A donut whose arcs morph between datasets, with the active value rolling into the center.
- [Waffle chart](https://uiarc.dev/components/waffle-chart/markdown): A ten by ten unit chart where every cell is one percent, and cells fly to their new group when the data changes.
- [Slope chart](https://uiarc.dev/components/slope-chart/markdown): Before and after on two axes: lines draw in, rank moves sit beside each value, and switching datasets slides every line to its new slope.
- [Gauge](https://uiarc.dev/components/gauge/markdown): Show a value against a known range.
- [Activity heatmap](https://uiarc.dev/components/activity-heatmap/markdown): See a year of activity at a glance, one square per day.
- [Animated counter](https://uiarc.dev/components/animated-counter/markdown): Give changing totals a clear sense of movement.
- [Ridgeline](https://uiarc.dev/components/ridgeline/markdown): Overlapping distributions, one ridge per group: hover to lift a ridge and read its quartiles, switch datasets and every curve morphs.
- [Treemap](https://uiarc.dev/components/treemap/markdown): A squarified treemap: click to drill and the tiles grow to fill the view, with a breadcrumb back and metrics that morph every tile.
- [Split bar](https://uiarc.dev/components/split-bar/markdown): A single 100% bar split into shares: rest on a segment to widen it and read its exact figures, toggle segments from the legend and the rest reflow, with labels inside when they fit and on leader lines when they don't.

## Guidance for AI tools

Brush chart: A dense time series with an overview strip: drag a window to zoom, resize it by its handles, and read events in place. Follow the declared prop types and do not invent props. Keep keyboard access, reduced motion support, and both light and dark themes intact when adapting it.

Full library index: https://uiarc.dev/llms.txt
