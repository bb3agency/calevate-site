# Changelog feed

> Release notes you can filter, open in place, and scroll through month by month.

- Type: Block
- Page: https://uiarc.dev/components/blocks/changelog-feed
- Markdown: https://uiarc.dev/components/blocks/changelog-feed/markdown

- Access: Free, open source
- Registry id: `changelog-feed`
- Source file: `registry/blocks/changelog-feed/changelog-feed.tsx`
- Built from: Copy button
- Keywords: react changelog, release notes page, changelog component, product updates feed, what's new page, changelog with filters

Use this for a product changelog page. Load entries from your release notes source and connect the subscribe control to your mailing list.

## When to use

- A product changelog or release notes page grouped by month.
- Release notes with type filters such as features, fixes, and improvements.
- Changelogs that should offer an email subscribe action in the header.

## When not to use

- Use timeline for a short vertical list of events without filters.
- Use accordion for plain expandable content that is not dated.

## Installation

### CLI

Run one of these in a project set up with `shadcn init`:

```bash
npx shadcn@latest add @uiarc/changelog-feed
pnpm dlx shadcn@latest add @uiarc/changelog-feed
yarn dlx shadcn@latest add @uiarc/changelog-feed
bunx --bun shadcn@latest add @uiarc/changelog-feed
```

The `@uiarc` name needs `"registries": { "@uiarc": "https://uiarc.dev/r/{name}.json" }` in `components.json`. Without it, use the full URL:

```bash
npx shadcn@latest add https://uiarc.dev/r/changelog-feed.json
```

### Manual

1. Install the dependencies:

```bash
npm install motion lucide-react
```

2. Copy the source into your project. Main file: `registry/blocks/changelog-feed/changelog-feed.tsx`

   The source is in the registry item: https://uiarc.dev/r/changelog-feed.json

3. Arc imports use the `@/` alias for `registry/` and `lib/`. Keep the same folders or update the import paths.

## Usage

```tsx
import { ChangelogFeed } from "@/components/arc/blocks/changelog-feed/changelog-feed";

export default function ChangelogPage() {
  return (
    <main>
      <ChangelogFeed />
    </main>
  );
}
```

## API reference

### ChangelogFeed

Release notes grouped by month, with type filter chips, expandable entries with media, a month jump nav, and an inline subscribe form. Entries, images, and the webhook snippet are sample data.

No props.

## Keyboard interactions

| Keys | Action |
| --- | --- |
| Escape | Cancels the subscribe form and returns to the Subscribe button. |

## Accessibility

- Each entry row is a button with aria-expanded and aria-controls pointing at its detail panel.
- Filter chips are toggle buttons with aria-pressed, and the visible count is announced in a polite status region.
- The month nav marks the current month with aria-current, and the scroll area is focusable with an aria-label.

## Motion

- Entries open in place on a spring while the chevron rotates; the month label slides in the scroll direction.
- The subscribe control morphs from button to form to a drawn check with a short blur crossfade.
- Reduced motion makes these changes instant.

## Responsive behavior

- Below 640px the header stacks, rows move date and type above the text, and the scroller drops from 560px to 520px.
- Below 480px month counts and the shown count are hidden so the month nav fits on one line.
- Hover styles apply only on hover-capable fine pointers.

## Performance

- The feed scrolls inside a fixed-height area; entries are not virtualized, so paginate or load older months on demand.
- Scroll tracking for the month bar is batched to one requestAnimationFrame, and a ResizeObserver resyncs it on resize.

## Notes for AI

- Use for a product changelog or release notes page.
- Replace the entries array and the imported sample images with data from your release notes source or CMS.
- The subscribe submit only changes local state; post the email to your mailing list provider.

## Related

- [Timeline](https://uiarc.dev/components/timeline/markdown): Follow what happened, newest first, grouped by day.
- [Accordion](https://uiarc.dev/components/accordion/markdown): Progressively reveal supporting information in place.
- [Copy button](https://uiarc.dev/components/copy-button/markdown): Copy a value with immediate confirmation.
- [Chip group](https://uiarc.dev/components/chip-group/markdown): Filter by a few facets with chips that morph as you pick them.

## Guidance for AI tools

Blocks are complete, self-contained screens with sample data. Replace the sample data and connect the callbacks described above. Follow the declared prop types and do not invent props. Keep keyboard access, reduced motion support, and both light and dark themes intact when adapting it.

Full library index: https://uiarc.dev/llms.txt
