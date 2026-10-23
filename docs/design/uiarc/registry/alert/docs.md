# Alert

> A persistent message that helps people recover or continue.

- Type: Component (feedback)
- Access: Free, open source
- Page: https://uiarc.dev/components/alert
- Markdown: https://uiarc.dev/components/alert/markdown
- Registry item: https://uiarc.dev/r/alert.json
- Source file: `registry/components/alert/alert.tsx`
- Dependencies: motion, lucide-react
- Keywords: status, message, react alert, alert banner, inline notification, warning message, animated alert, dismissible alert, callout

## When to use

- Persistent, in-flow messages about a page or form, such as an expiring card.
- Status that changes over time, where one alert should morph between tones.
- Dismissible notices that should collapse and close the gap below them.

## When not to use

- Use toast or toast-stack for transient results of an action.
- Use empty-state when there is no content to show.
- Use dialog when people must respond before continuing.

## Installation

### CLI

Run one of these in a project set up with `shadcn init`:

```bash
npx shadcn@latest add @uiarc/alert
pnpm dlx shadcn@latest add @uiarc/alert
yarn dlx shadcn@latest add @uiarc/alert
bunx --bun shadcn@latest add @uiarc/alert
```

The `@uiarc` name needs `"registries": { "@uiarc": "https://uiarc.dev/r/{name}.json" }` in `components.json`. Without it, use the full URL:

```bash
npx shadcn@latest add https://uiarc.dev/r/alert.json
```

### Manual

1. Install the dependencies:

```bash
npm install motion lucide-react
```

2. Copy the source into your project. Main file: `registry/components/alert/alert.tsx`

   The source is in the registry item: https://uiarc.dev/r/alert.json

3. Arc imports use the `@/` alias for `registry/` and `lib/`. Keep the same folders or update the import paths.

## Usage

```tsx
import { Alert } from "@/components/arc/alert/alert";

export function BillingNotice() {
  return (
    <Alert tone="warning" title="Card expires soon" onDismiss={() => track("dismissed")}>
      Update your payment method before March 1 to avoid interruption.
    </Alert>
  );
}
```

## API reference

### Alert

An inline message with a tone icon, title, and optional details that morph when they change.

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `title` (required) | `string` | – | Headline. A new title rises in over the old one. |
| `tone` | `"info" \| "success" \| "warning" \| "danger"` | `"info"` | Colour and icon. Danger uses role="alert"; the rest use role="status". |
| `children` | `ReactNode` | – | Details under the title. String children crossfade when they change. |
| `open` | `boolean` | – | Controls presence. Hiding collapses the height and fades it out. |
| `onDismiss` | `() => void` | – | Shows a dismiss button. Uncontrolled alerts collapse first, then call this. |
| `...props` | `HTMLAttributes<HTMLDivElement>` | – | Forwarded to the alert element, such as className and id. |

## Keyboard interactions

| Keys | Action |
| --- | --- |
| Enter / Space | Activates the dismiss button when present. |

## Accessibility

- Danger alerts use role="alert" and interrupt; other tones use role="status" and announce politely.
- Outgoing copies are aria-hidden while they fade, so the live region reads only the current text.
- The dismiss button is labelled "Dismiss: <title>"; the tone icon is aria-hidden.

## Motion

- Presence collapses or expands the height on a smooth spring with a fade, so content below closes the gap.
- Tone changes morph the icon through a small scale and blur; copy changes rise in while the height springs to fit.
- Reduced motion swaps content with short fades and no height animation.

## Responsive behavior

- The alert fills its container and the copy wraps; the icon and dismiss button keep fixed sizes.
- Hover styles on the dismiss button apply only on hover-capable fine pointers.

## Performance

- A ResizeObserver lets the height spring when copy changes; keep only a few alerts mounted per page.

## Notes for AI

- Use for persistent, in-flow messages tied to a page or form. Use toast or toast-stack for transient results of an action.
- Keep one Alert mounted and change tone, title, and children to morph between states instead of swapping components.

## Related

- [Toast](https://uiarc.dev/components/toast/markdown): Brief confirmation for a completed background action.
- [Toast stack](https://uiarc.dev/components/toast-stack/markdown): Stack short results at the edge until you reach for them.
- [Empty state](https://uiarc.dev/components/empty-state/markdown): A useful next step when there is nothing to show yet.

## Also in messages

- [Announcement bar](https://uiarc.dev/components/announcement-bar/markdown): A top banner that rotates messages, counts down, and collapses smoothly when dismissed.
- [Cookie consent](https://uiarc.dev/components/cookie-consent/markdown): A consent bar that morphs into preferences and folds into a reopen button.

## Guidance for AI tools

Alert: A persistent message that helps people recover or continue. Follow the declared prop types and do not invent props. Keep keyboard access, reduced motion support, and both light and dark themes intact when adapting it.

Full library index: https://uiarc.dev/llms.txt
