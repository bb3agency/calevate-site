# Toast stack

> Stack short results at the edge until you reach for them.

- Type: Component (feedback)
- Access: Free, open source
- Page: https://uiarc.dev/components/toast-stack
- Markdown: https://uiarc.dev/components/toast-stack/markdown
- Registry item: https://uiarc.dev/r/toast-stack.json
- Source file: `registry/components/toast-stack/toast-stack.tsx`
- Dependencies: motion, lucide-react
- Keywords: toast, notification, sonner, react toast stack, toast notifications, sonner alternative, stacked toasts, notification queue, promise toast, undo toast

## When to use

- App-wide notifications for async results, errors, and undo.
- Loading toasts that morph into success or error when work finishes.
- Toasts with an action button, like View or Undo.

## When not to use

- Use toast for a single locally controlled confirmation.
- Use alert for persistent messages tied to a page.
- Use notification-center for a history people can come back to.

## Installation

### CLI

Run one of these in a project set up with `shadcn init`:

```bash
npx shadcn@latest add @uiarc/toast-stack
pnpm dlx shadcn@latest add @uiarc/toast-stack
yarn dlx shadcn@latest add @uiarc/toast-stack
bunx --bun shadcn@latest add @uiarc/toast-stack
```

The `@uiarc` name needs `"registries": { "@uiarc": "https://uiarc.dev/r/{name}.json" }` in `components.json`. Without it, use the full URL:

```bash
npx shadcn@latest add https://uiarc.dev/r/toast-stack.json
```

### Manual

1. Install the dependencies:

```bash
npm install motion lucide-react
```

2. Copy the source into your project. Main file: `registry/components/toast-stack/toast-stack.tsx`

   The source is in the registry item: https://uiarc.dev/r/toast-stack.json

3. Arc imports use the `@/` alias for `registry/` and `lib/`. Keep the same folders or update the import paths.

## Usage

```tsx
import { ToastStack, ToastStackProvider, useToastStack } from "@/components/arc/toast-stack/toast-stack";

function PublishButton() {
  const { toast, update } = useToastStack();
  async function publish() {
    const id = toast({ type: "loading", title: "Publishing" });
    await api.publish();
    update(id, { type: "success", title: "Published", action: { label: "View", onClick: openSite } });
  }
  return <button type="button" onClick={publish}>Publish</button>;
}

export function App() {
  return <ToastStackProvider><PublishButton /><ToastStack /></ToastStackProvider>;
}
```

## Examples

### Undo action

```tsx
const { toast, dismiss } = useToastStack();

toast({
  type: "info",
  title: "Message archived",
  action: { label: "Undo", onClick: id => { restore(); dismiss(id); } },
});
```

## API reference

### ToastStackProvider

Scopes a toast queue to its subtree. Wrap the app or panel once.

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `children` (required) | `ReactNode` | – | Subtree that can raise toasts. |
| `duration` | `number` | `5000` | Base lifetime in ms. Warnings and errors stay 1.6 times longer; loading waits for an update. |
| `limit` | `number` | `12` | Oldest toasts beyond this count are dropped. |

### ToastStack

The viewport. Toasts rise from the bottom, tuck behind each other, and fan out on hover or focus.

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `label` | `string` | `"Notifications"` | Accessible name of the region. |
| `position` | `"bottom-right" \| "bottom-center" \| "bottom-left"` | `"bottom-right"` | Corner of the viewport. |
| `contained` | `boolean` | `false` | Pins the stack inside the nearest positioned ancestor instead of the window. |
| `visibleToasts` | `number` | `3` | How many toasts show at once. |
| `hotkey` | `boolean` | `true` | Alt+T moves focus into the stack. |
| `className` | `string` | – | Class on the region. |

### useToastStack

Hook returning { toast, update, dismiss, count }. Must be called inside ToastStackProvider.

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `toast` | `(options: ToastOptions) => string` | – | Shows a toast and returns its id. Options: id, type ("success" \| "info" \| "warning" \| "error" \| "loading"), title, description, action { label, onClick(id) }, duration. |
| `update` | `(id: string, patch: Partial<Omit<ToastOptions, "id">>) => void` | – | Morphs a toast in place and restarts its timer. Pass action: undefined to remove the action. |
| `dismiss` | `(id?: string) => void` | – | Dismisses one toast, or all when called without an id. |
| `count` | `number` | – | How many toasts are queued. |

## Keyboard interactions

| Keys | Action |
| --- | --- |
| Alt+T | Moves focus to the front toast and fans out the stack. |
| Tab | Moves between toast actions and dismiss buttons. |
| Escape | Dismisses the focused toast. |

## Accessibility

- The viewport is a labelled section with aria-live="polite" and aria-relevant="additions text", so new and updated toasts are announced.
- Each toast prefixes a screen-reader-only type label such as "Error:"; outgoing copy is aria-hidden while it fades.
- Hidden and leaving toasts are inert. When a focused toast closes, keyboard focus moves to the next toast or back to where it came from.
- Timers pause while the stack is hovered, focused, dragged, or the tab is hidden.

## Motion

- New toasts rise from their own height below the edge; older ones tuck behind at 14px peeks and 0.05 scale steps, and fan out on a morph spring.
- Swiping right follows the finger and throws with velocity; left rubber-bands. Updates morph the icon, copy, height, and action width in place.
- Reduced motion jumps positions and uses short opacity fades.

## Responsive behavior

- The viewport is min(22.5rem, 100% minus a 32px gutter) wide; below 30rem it centers at the bottom regardless of position.
- Below a 21rem toast width the action button drops under the copy instead of squeezing it.
- On touch, a tap fans out the stack, and a right swipe dismisses a toast.

## Performance

- At most 12 toasts are kept by default and only 3 show; each has its own ResizeObserver for height.
- Timers pause while hovered, focused, dragged, or when the tab is hidden.

## Notes for AI

- Default for app-wide notifications, async results, and undo. Use toast for a single locally controlled confirmation and alert for persistent inline messages.
- Render ToastStack once inside ToastStackProvider and call useToastStack anywhere below. Reuse an id or call update to morph loading into success or error.

## Related

- [Toast](https://uiarc.dev/components/toast/markdown): Brief confirmation for a completed background action.
- [Alert](https://uiarc.dev/components/alert/markdown): A persistent message that helps people recover or continue.
- [Hold to confirm](https://uiarc.dev/components/hold-to-confirm/markdown): Confirm a destructive action by holding, not tapping.

## Also in messages

- [Announcement bar](https://uiarc.dev/components/announcement-bar/markdown): A top banner that rotates messages, counts down, and collapses smoothly when dismissed.
- [Cookie consent](https://uiarc.dev/components/cookie-consent/markdown): A consent bar that morphs into preferences and folds into a reopen button.

## Guidance for AI tools

Toast stack: Stack short results at the edge until you reach for them. Follow the declared prop types and do not invent props. Keep keyboard access, reduced motion support, and both light and dark themes intact when adapting it.

Full library index: https://uiarc.dev/llms.txt
