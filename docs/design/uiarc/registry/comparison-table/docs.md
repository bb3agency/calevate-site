# Comparison table

> An us versus them table with a sticky header, a highlighted column, and a stacked phone view.

- Type: Block
- Page: https://uiarc.dev/components/blocks/comparison-table
- Markdown: https://uiarc.dev/components/blocks/comparison-table/markdown

- Access: Free, open source
- Registry id: `comparison-table`
- Source file: `registry/blocks/comparison-table/comparison-table.tsx`
- Built from: Switch, Button
- Keywords: comparison table, us vs them, competitor comparison, feature comparison, alternatives page, sticky header table, react comparison table

Use this on a pricing or alternatives page. Describe your columns and feature rows in comparison-table-data.ts, mark your product with highlight, and point the cta at signup; stickyTop offsets the header under a fixed site header.

## When to use

- Showing how your product stacks up against named alternatives.
- Feature matrices with three to five columns and grouped rows.

## When not to use

- Use plan-comparison to compare your own pricing tiers.
- Use a sortable data table for large datasets.

## Installation

### CLI

Run one of these in a project set up with `shadcn init`:

```bash
npx shadcn@latest add @uiarc/comparison-table
pnpm dlx shadcn@latest add @uiarc/comparison-table
yarn dlx shadcn@latest add @uiarc/comparison-table
bunx --bun shadcn@latest add @uiarc/comparison-table
```

The `@uiarc` name needs `"registries": { "@uiarc": "https://uiarc.dev/r/{name}.json" }` in `components.json`. Without it, use the full URL:

```bash
npx shadcn@latest add https://uiarc.dev/r/comparison-table.json
```

### Manual

1. Install the dependencies:

```bash
npm install motion lucide-react
```

2. Copy the source into your project. Main file: `registry/blocks/comparison-table/comparison-table.tsx`

   The source is in the registry item: https://uiarc.dev/r/comparison-table.json

3. Arc imports use the `@/` alias for `registry/` and `lib/`. Keep the same folders or update the import paths.

## Usage

```tsx
import { ComparisonTable } from "@/components/arc/blocks/comparison-table/comparison-table";

export function Alternatives() {
  return (
    <ComparisonTable
      columns={[
        { id: "us", name: "Relay", caption: "$10 per seat", highlight: true },
        { id: "them", name: "Legacy suite", caption: "$24 per seat" },
      ]}
      sections={[{ id: "core", title: "Core", rows: [
        { id: "offline", feature: "Offline mode", values: { us: true, them: false } },
        { id: "sso", feature: "SSO", values: { us: true, them: { value: "partial", note: "Enterprise plan" } } },
      ] }]}
      cta={{ label: "Start free trial", href: "/signup" }}
      stickyTop={64}
    />
  );
}
```

## API reference

### ComparisonTable

An us versus them table with sections, check, partial and not included marks, a tinted band behind your column, a sticky frosted header, a differences only switch, and a stacked two column view on phones.

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `columns` | `ComparisonColumn[]` | – | Products to compare. Mark yours with highlight: true. |
| `sections` | `ComparisonSection[]` | – | Grouped feature rows. Values: true, false, "partial", a string, or { value, note }. |
| `title` | `string` | `"How Relay compares"` | Section heading. |
| `description` | `string` | – | Line under the heading. |
| `differencesOnly` | `boolean` | – | Hide rows where all visible columns match (controlled). |
| `defaultDifferencesOnly` | `boolean` | `false` | Initial switch state when uncontrolled. |
| `onDifferencesOnlyChange` | `(value: boolean) => void` | – | Called when the switch flips. |
| `compareWith` | `string` | – | Competitor shown beside yours in the stacked phone view (controlled). |
| `onCompareWithChange` | `(id: string) => void` | – | Called when a competitor is picked on phones. |
| `cta` | `{ label: string; href?: string; onClick?: () => void; doneLabel?: string }` | – | Button at the foot of your column. doneLabel morphs in after a click. |
| `stickyTop` | `number` | `0` | Offset for the sticky header, such as a fixed site header height. |
| `maxHeight` | `number \| string` | – | Caps the table height and scrolls it inside the block with the header pinned. |
| `stackBelow` | `number` | `640` | Block width below which the phone view takes over. |
| `className` | `string` | – | Extra class on the section. |

## Keyboard interactions

| Keys | Action |
| --- | --- |
| Tab | Moves to the differences switch, the phone competitor picker, and the call to action. |
| Space | Flips the differences switch. |

## Accessibility

- Built with table, row, columnheader, rowheader and cell roles, so screen readers navigate it as a table.
- Marks have text alternatives: Included, Partial (with its note), Not included.
- The switch is a real checkbox with role switch; a polite live region says when rows are filtered.
- Meaning never relies on color: checks, half circles and dashes differ in shape, with a legend.

## Motion

- Checks in your column draw in once, staggered down the table, when they scroll into view.
- Differences only collapses matching rows on the smooth spring and closes the gap.
- Picking a competitor on phones swaps its header and marks with a small pop.
- The call to action morphs its label to the done state.
- Reduced motion shows every mark at once and swaps collapses for instant changes.

## Responsive behavior

- Below 640px (stackBelow) it shows your column beside one competitor with a picker above.
- Column widths are fractions, so it never scrolls sideways.

## Performance

- A width observer switches layouts; no per frame work while scrolling.
- Row collapses animate height only on rows that change.

## Notes for AI

- Use this for a /compare or /alternatives page or under pricing.
- Keep competitor names generic or factual; values should be verifiable.
- Set stickyTop to your fixed header height; use maxHeight only when embedding the table in a panel.

## Related

- [Plan comparison](https://uiarc.dev/components/blocks/plan-comparison/markdown): Compare meaningful differences between plans and billing periods.
- [Pricing calculator](https://uiarc.dev/components/blocks/pricing-calculator/markdown): A seat slider and billing toggle drive plan cards with rolling prices and a moving recommended badge.
- [Usage pricing](https://uiarc.dev/components/blocks/usage-pricing/markdown): A pricing calculator that finds your plan as you drag seats and traffic.
- [FAQ section](https://uiarc.dev/components/blocks/faq-section/markdown): FAQs as an accordion, a topic rail, or a searchable list that highlights matches.

## Guidance for AI tools

Blocks are complete, self-contained screens with sample data. Replace the sample data and connect the callbacks described above. Follow the declared prop types and do not invent props. Keep keyboard access, reduced motion support, and both light and dark themes intact when adapting it.

Full library index: https://uiarc.dev/llms.txt
