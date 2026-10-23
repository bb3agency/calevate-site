# Notification center

> A home for updates with read state, grouped information, and animated disclosure.

- Type: Block
- Page: https://uiarc.dev/components/blocks/notification-center
- Markdown: https://uiarc.dev/components/blocks/notification-center/markdown

- Access: Free, open source
- Registry id: `notification-center`
- Source file: `registry/components/notification-center/notification-center.tsx`
- Built from: Popover, Badge, Action list
- Keywords: react notification center, notification bell, notification dropdown, inbox popover, unread notifications, activity feed popover

Use it when updates need a persistent home instead of a brief toast. Connect read state to your data store.

## When to use

- A bell in the app header with an unread badge and an inbox of recent updates.
- Notifications people can mark read, expand, and dismiss in bulk.

## When not to use

- Use toast-stack for transient messages that should disappear.
- Use inbox-triage for a full-page inbox.
- Use badge for a count without a panel.

## Installation

### CLI

Run one of these in a project set up with `shadcn init`:

```bash
npx shadcn@latest add @uiarc/notification-center
pnpm dlx shadcn@latest add @uiarc/notification-center
yarn dlx shadcn@latest add @uiarc/notification-center
bunx --bun shadcn@latest add @uiarc/notification-center
```

The `@uiarc` name needs `"registries": { "@uiarc": "https://uiarc.dev/r/{name}.json" }` in `components.json`. Without it, use the full URL:

```bash
npx shadcn@latest add https://uiarc.dev/r/notification-center.json
```

### Manual

1. Install the dependencies:

```bash
npm install motion lucide-react @radix-ui/react-popover
```

2. Copy the source into your project. Main file: `registry/components/notification-center/notification-center.tsx`

   The source is in the registry item: https://uiarc.dev/r/notification-center.json

3. Arc imports use the `@/` alias for `registry/` and `lib/`. Keep the same folders or update the import paths.

## Usage

```tsx
import { NotificationCenter } from "@/components/arc/notification-center/notification-center";

export function HeaderBell() {
  return (
    <NotificationCenter
      notifications={[
        { id: "1", title: "Deploy finished", time: "2m", tone: "success" },
        { id: "2", title: "Ana commented", time: "1h", actor: { name: "Ana", photo: "/ana.jpg" } },
      ]}
      onReadChange={(item, read) => markRead(item.id, read)}
      onDismiss={item => dismiss(item.id)}
    />
  );
}
```

## API reference

### NotificationCenter

A bell trigger with an unread badge that opens a popover of notifications with All and Unread views, expandable rows, and bulk actions.

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `notifications` (required) | `NotificationItem[]` | – | Initial notifications. The component keeps its own copy after mount. |
| `label` | `string` | `"Notifications"` | Panel heading and trigger label. |
| `onReadChange` | `(notification: NotificationItem, read: boolean) => void` | – | Called for each item marked read or unread, including Mark all read. |
| `onDismiss` | `(notification: NotificationItem) => void` | – | Called for each dismissed item, including Clear read. |
| `open` | `boolean` | – | Controlled open state. |
| `onOpenChange` | `(open: boolean) => void` | – | Called when the popover opens or closes. |
| `avoidCollisions` | `boolean` | `true` | Lets the popover flip or shift to stay in the viewport. |

### NotificationItem

Item type: { id: string; title: string; description?: string; time: string; read?: boolean; tone?: "info" | "success" | "warning"; actor?: { name: string; photo: string } }. actor shows an avatar instead of a tone icon.

No props.

## Keyboard interactions

| Keys | Action |
| --- | --- |
| Enter / Space | Opens the panel from the trigger, toggles a row's details, and activates actions. |
| Escape | Closes the panel and returns focus to the trigger (Radix Popover). |
| Tab | Moves through view toggles, rows, and row actions. |

## Accessibility

- The trigger's aria-label includes the unread count; the visual badge is aria-hidden.
- The summary line is aria-live polite, and outgoing text copies are aria-hidden while they fade.
- Row toggles use aria-expanded and announce unread state; view toggles use aria-pressed.
- Focus moves to the next row, or a view toggle, after an item is read, dismissed, or cleared.

## Motion

- The bell tilts when open; counts roll like an odometer in the direction of change.
- Rows open and collapse their own height on a spring, and bulk actions cascade down the list in under a quarter second.
- Reduced motion replaces height, roll, and tilt with instant fades.

## Responsive behavior

- The panel is min(424px, 100vw minus 24px) wide and at most min(590px, 100vh minus 24px) tall, with the list scrolling inside.
- Below 380px padding tightens, the details indent shrinks, and the Mark all read label becomes icon only.
- Titles and previews ellipsize on one line.

## Performance

- The list is not virtualized and keeps its own copy of the notifications; cap what you pass in.
- The panel mounts in a portal only while open.

## Notes for AI

- Use in an app header for an inbox of updates. Use toast or toast-stack for transient messages and inbox-triage for a full-page inbox.
- notifications seeds internal state; sync changes back to your server through onReadChange and onDismiss rather than re-passing the array.

## Related

- [Popover](https://uiarc.dev/components/popover/markdown): A small anchored surface for contextual information.
- [Toast stack](https://uiarc.dev/components/toast-stack/markdown): Stack short results at the edge until you reach for them.
- [Badge](https://uiarc.dev/components/badge/markdown): A small label for status, category, or metadata.
- [Avatar](https://uiarc.dev/components/avatar/markdown): A compact identity marker for people and accounts.
- [Inbox triage](https://uiarc.dev/components/blocks/inbox-triage/markdown): Process a focused inbox with archive, snooze, and restore actions.

## Guidance for AI tools

Blocks are complete, self-contained screens with sample data. Replace the sample data and connect the callbacks described above. Follow the declared prop types and do not invent props. Keep keyboard access, reduced motion support, and both light and dark themes intact when adapting it.

Full library index: https://uiarc.dev/llms.txt
