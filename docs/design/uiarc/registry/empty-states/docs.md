# Empty states

> Four empty states in one illustration whose shapes morph between scenes as you switch tabs.

- Type: Block
- Page: https://uiarc.dev/components/blocks/empty-states
- Markdown: https://uiarc.dev/components/blocks/empty-states/markdown

- Access: Free, open source
- Registry id: `empty-states`
- Source file: `registry/blocks/empty-states/empty-states.tsx`
- Keywords: react empty state, empty state illustration, no results state, offline state, 404 page illustration, inbox zero, morphing svg illustration

Use this for no results, offline, inbox zero and missing page moments. Wire each action to your real filter reset, retry, refresh or search; the preview simulates them locally.

## When to use

- A reference for no results, offline, inbox zero, and 404 moments with one shared illustration style.
- Extracting one scene as a richer empty state for a key screen.

## When not to use

- Use empty-state for a simple empty state with an icon, text, and action.
- Use onboarding-illustration for first-run screens that teach the product.
- Use skeleton while content is still loading.

## Installation

### CLI

Run one of these in a project set up with `shadcn init`:

```bash
npx shadcn@latest add @uiarc/empty-states
pnpm dlx shadcn@latest add @uiarc/empty-states
yarn dlx shadcn@latest add @uiarc/empty-states
bunx --bun shadcn@latest add @uiarc/empty-states
```

The `@uiarc` name needs `"registries": { "@uiarc": "https://uiarc.dev/r/{name}.json" }` in `components.json`. Without it, use the full URL:

```bash
npx shadcn@latest add https://uiarc.dev/r/empty-states.json
```

### Manual

1. Install the dependencies:

```bash
npm install motion
```

2. Copy the source into your project. Main file: `registry/blocks/empty-states/empty-states.tsx`

   The source is in the registry item: https://uiarc.dev/r/empty-states.json

3. Arc imports use the `@/` alias for `registry/` and `lib/`. Keep the same folders or update the import paths.

## Usage

```tsx
import { EmptyStates } from "@/components/arc/blocks/empty-states/empty-states";

export default function EmptyGallery() {
  return (
    <main>
      <EmptyStates />
    </main>
  );
}
```

## API reference

### EmptyStates

Four empty states (no results, offline, inbox zero, missing page) in one illustration that morphs between scenes via tabs, each with a simulated action. Scene copy is in empty-states.tsx and shapes in empty-states-art.ts.

No props.

## Keyboard interactions

| Keys | Action |
| --- | --- |
| Left / Right | Move between scene tabs (wraps around). |
| Home / End | Jump to the first or last scene. |

## Accessibility

- Scenes use role="tablist", "tab" and "tabpanel" with aria-selected and aria-controls.
- The illustration is a role="img" labelled by the scene; a polite live region reports action results.

## Motion

- Each shape morphs its path to the next scene with slight per-shape delays, and the tab indicator glides with a layoutId.
- Reduced motion swaps scenes with a short fade and no morph.

## Responsive behavior

- The block is a container query root; from a 560px container the title steps up a size.
- Pointer parallax only turns on for hover-capable fine pointers, so touch devices get a still illustration.

## Performance

- Shape morphs run on a small requestAnimationFrame loop that stops as soon as every shape settles.
- A ResizeObserver springs the copy height when scenes change.

## Notes for AI

- Use as a reference for no results, offline, inbox zero or 404 moments; usually you extract one scene rather than ship the tabbed gallery.
- Actions (clear filters, retry, refresh, search) are simulated; wire them to your real handlers.
- For a single simple empty state, prefer the empty-state component.

## Related

- [Empty state](https://uiarc.dev/components/empty-state/markdown): A useful next step when there is nothing to show yet.
- [Onboarding illustration](https://uiarc.dev/components/blocks/onboarding-illustration/markdown): A compact onboarding card whose line illustration morphs from folder to files, team, and badge.
- [Tabs](https://uiarc.dev/components/tabs/markdown): Switch between related content in the same context.

## Guidance for AI tools

Blocks are complete, self-contained screens with sample data. Replace the sample data and connect the callbacks described above. Follow the declared prop types and do not invent props. Keep keyboard access, reduced motion support, and both light and dark themes intact when adapting it.

Full library index: https://uiarc.dev/llms.txt
