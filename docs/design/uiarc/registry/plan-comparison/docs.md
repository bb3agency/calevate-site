# Plan comparison

> Compare meaningful differences between plans and billing periods.

- Type: Block
- Page: https://uiarc.dev/components/blocks/plan-comparison
- Markdown: https://uiarc.dev/components/blocks/plan-comparison/markdown

- Access: Free, open source
- Registry id: `plan-comparison`
- Source file: `registry/blocks/plan-comparison/plan-comparison.tsx`
- Built from: Segmented control, Button, Motion
- Keywords: react pricing comparison, plan comparison table, pricing table, monthly yearly toggle, feature matrix, saas pricing page

Use this when people need to weigh plans side by side. Replace the sample features and prices with your current offering.

## When to use

- Comparing two tiers side by side with a feature matrix.
- Pricing pages that switch between monthly and yearly prices.
- Long feature lists where people want to see only the differences.

## When not to use

- Use usage-pricing when price depends on seats or volume.
- Use segmented-control alone for a simple billing toggle.
- Use cancel-flow for downgrade or cancellation decisions.

## Installation

### CLI

Run one of these in a project set up with `shadcn init`:

```bash
npx shadcn@latest add @uiarc/plan-comparison
pnpm dlx shadcn@latest add @uiarc/plan-comparison
yarn dlx shadcn@latest add @uiarc/plan-comparison
bunx --bun shadcn@latest add @uiarc/plan-comparison
```

The `@uiarc` name needs `"registries": { "@uiarc": "https://uiarc.dev/r/{name}.json" }` in `components.json`. Without it, use the full URL:

```bash
npx shadcn@latest add https://uiarc.dev/r/plan-comparison.json
```

### Manual

1. Install the dependencies:

```bash
npm install motion lucide-react
```

2. Copy the source into your project. Main file: `registry/blocks/plan-comparison/plan-comparison.tsx`

   The source is in the registry item: https://uiarc.dev/r/plan-comparison.json

3. Arc imports use the `@/` alias for `registry/` and `lib/`. Keep the same folders or update the import paths.

## Usage

```tsx
import { PlanComparison } from "@/components/arc/blocks/plan-comparison/plan-comparison";

export function PricingPage() {
  return <PlanComparison />;
}
```

## API reference

### PlanComparison

A Team vs Studio comparison with a monthly or yearly toggle, animated prices, and a feature matrix. Takes no props; plans, prices, and features are sample data in the file.

No props.

## Accessibility

- The matrix uses table, row, columnheader, rowheader, and cell roles.
- Prices are aria-live with aria-atomic so the full value is read.
- The chosen plan is announced in a role="status" footer.

## Motion

- Prices count between billing periods and the selection highlight moves with layoutId.
- Extra feature rows expand in height with a light blur.
- Reduced motion jumps to the final values and disables height animation.

## Responsive behavior

- Below 640px the feature header column hides and each feature name spans the row above its two values.
- Below 365px plan and value padding tighten so both plans still fit side by side.

## Performance

- Prices tween with a single animate call per value; the selection highlight uses one layoutId.
- Showing extra rows animates height, so keep the matrix to a few dozen features.

## Notes for AI

- Use when people compare two tiers side by side.
- Edit the pricing and features constants; there is no selection callback, so wire the Button onClick yourself.
- Composes Arc Button, SegmentedControl, and Switch.

## Related

- [Usage pricing](https://uiarc.dev/components/blocks/usage-pricing/markdown): A pricing calculator that finds your plan as you drag seats and traffic.
- [Segmented control](https://uiarc.dev/components/segmented-control/markdown): Switch between a small set of related views.
- [Animated counter](https://uiarc.dev/components/animated-counter/markdown): Give changing totals a clear sense of movement.
- [Cancel flow](https://uiarc.dev/components/blocks/cancel-flow/markdown): A cancellation flow that answers each reason with a tailored offer and a calm hold-to-cancel.

## Guidance for AI tools

Blocks are complete, self-contained screens with sample data. Replace the sample data and connect the callbacks described above. Follow the declared prop types and do not invent props. Keep keyboard access, reduced motion support, and both light and dark themes intact when adapting it.

Full library index: https://uiarc.dev/llms.txt
