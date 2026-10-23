# Split button

> A primary action with a menu of nearby alternatives.

- Type: Component (actions)
- Access: Free, open source
- Page: https://uiarc.dev/components/split-button
- Markdown: https://uiarc.dev/components/split-button/markdown
- Registry item: https://uiarc.dev/r/split-button.json
- Source file: `registry/components/split-button/split-button.tsx`
- Dependencies: @radix-ui/react-dropdown-menu, motion, lucide-react
- Keywords: action, menu, react split button, button with dropdown, split button menu, merge button, dropdown button, primary action with options

## When to use

- One default action with a few close variants, like Merge with Squash and Rebase.
- Export or share actions where one format is the usual pick and others sit behind the chevron.
- Copy actions that swap the label to Copied in place while offering alternatives.

## When not to use

- Use dropdown-menu when there is no default action and every option is equal.
- Use button when there are no alternatives.
- Use context-menu for actions tied to a piece of content rather than a toolbar.

## Installation

### CLI

Run one of these in a project set up with `shadcn init`:

```bash
npx shadcn@latest add @uiarc/split-button
pnpm dlx shadcn@latest add @uiarc/split-button
yarn dlx shadcn@latest add @uiarc/split-button
bunx --bun shadcn@latest add @uiarc/split-button
```

The `@uiarc` name needs `"registries": { "@uiarc": "https://uiarc.dev/r/{name}.json" }` in `components.json`. Without it, use the full URL:

```bash
npx shadcn@latest add https://uiarc.dev/r/split-button.json
```

### Manual

1. Install the dependencies:

```bash
npm install @radix-ui/react-dropdown-menu motion lucide-react
```

2. Copy the source into your project. Main file: `registry/components/split-button/split-button.tsx`

   The source is in the registry item: https://uiarc.dev/r/split-button.json

3. Arc imports use the `@/` alias for `registry/` and `lib/`. Keep the same folders or update the import paths.

## Usage

```tsx
import { SplitButton } from "@/components/arc/split-button/split-button";

export function MergeButton() {
  return (
    <SplitButton
      label="Merge pull request"
      onClick={merge}
      actions={[
        { label: "Squash and merge", onSelect: squash },
        { label: "Rebase and merge", onSelect: rebase },
        { label: "Close pull request", onSelect: close, destructive: true },
      ]}
    />
  );
}
```

## API reference

### SplitButton

A primary action joined to a chevron that opens a Radix dropdown of related actions.

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `label` (required) | `string` | – | Main action label. Changes morph letter by letter. |
| `actions` (required) | `SplitButtonAction[]` | – | Menu items: { label, onSelect?, disabled?, destructive?, icon? }. |
| `onClick` | `() => void` | – | Runs the main action. |
| `icon` | `ReactNode` | – | Leading icon on the main half. A different icon element crossfades in. |
| `variant` | `"primary" \| "secondary"` | `"primary"` | Visual weight of both halves. |
| `disabled` | `boolean` | – | Disables both the main action and the menu trigger. |

## Keyboard interactions

| Keys | Action |
| --- | --- |
| Enter / Space | Runs the main action, or opens the menu from the chevron. |
| ArrowDown / ArrowUp | Moves between menu items, looping at the ends. |
| Escape | Closes the menu and returns focus to the chevron. |

## Accessibility

- Two native buttons; the chevron is labelled "<label> more actions".
- The menu is a Radix DropdownMenu with menu and menuitem roles and focus management.
- The main label is announced through a polite live region when it changes.

## Motion

- The main label and icon morph in place while its width springs; the menu half never scales, so the menu opens from a still anchor.
- Menu items fade in with a short stagger.
- Reduced motion removes the press scale, width spring, and menu transform, leaving a quick opacity fade.

## Responsive behavior

- The menu opens aligned to the end of the button with 12px collision padding, so it stays on screen near viewport edges.
- The secondary variant sets a 142px minimum on the main half; the pair does not collapse on narrow screens, so give it its own row on mobile.

## Performance

- The main label animates per letter with a ResizeObserver-driven width spring; the menu mounts only while open through a Radix portal.

## Notes for AI

- Use when one action is the default and two to five close variants exist. For a menu with no default action use dropdown-menu.
- Keep the menu actions as variations of the main action; put unrelated commands elsewhere.
- Swap label and icon (Copy page → Copied) to show the result in place.

## Related

- [Button](https://uiarc.dev/components/button/markdown): A clear, responsive action with quiet secondary states.
- [Dropdown menu](https://uiarc.dev/components/dropdown-menu/markdown): A focused list of actions anchored to a trigger.
- [Action button](https://uiarc.dev/components/action-button/markdown): A compact button for frequent toolbar actions.
- [Copy button](https://uiarc.dev/components/copy-button/markdown): Copy a value with immediate confirmation.

## Also in buttons

- [Button group](https://uiarc.dev/components/button-group/markdown): Related actions joined into one surface with hairline dividers: a hover highlight glides between segments, the pressed one answers in place, and an attached menu can close the row.
- [Floating button group](https://uiarc.dev/components/floating-button-group/markdown): Separate soft buttons in a quiet tray, with one shared highlight that morphs from button to button as you move, and a pressed state that settles in place.
- [Expanding button group](https://uiarc.dev/components/expanding-button-group/markdown): Icon buttons in a compact group: the one you point at or focus grows to reveal its label while its neighbours slide aside, and an action confirms in place.
- [Action swap](https://uiarc.dev/components/action-swap/markdown): Swap an action label while preserving its place and intent.
- [Icon morph](https://uiarc.dev/components/icon-morph/markdown): Icons that morph between states: menu to close, play to pause, copy to check, and more.
- [Confirm morph](https://uiarc.dev/components/confirm-morph/markdown): A destructive button that morphs into an inline confirmation, a spinner, and a result with undo.

## Guidance for AI tools

Split button: A primary action with a menu of nearby alternatives. Follow the declared prop types and do not invent props. Keep keyboard access, reduced motion support, and both light and dark themes intact when adapting it.

Full library index: https://uiarc.dev/llms.txt
