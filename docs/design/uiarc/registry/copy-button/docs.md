# Copy button

> Copy a value with immediate confirmation.

- Type: Component (actions)
- Access: Free, open source
- Page: https://uiarc.dev/components/copy-button
- Markdown: https://uiarc.dev/components/copy-button/markdown
- Registry item: https://uiarc.dev/r/copy-button.json
- Source file: `registry/components/copy-button/copy-button.tsx`
- Dependencies: motion, lucide-react
- Keywords: action, utility, react copy button, copy to clipboard, copy button animation, clipboard button, copy code button, copied feedback

## When to use

- Next to API keys, install commands, links, or code snippets.
- Icon-only copy controls in dense rows, with an accessible label.
- Any copy action that should confirm Copied or Could not copy in place.

## When not to use

- Use split-button when copying has alternatives, such as Copy link and Copy as Markdown.
- Use code-block for full code samples, which include their own copy control.

## Installation

### CLI

Run one of these in a project set up with `shadcn init`:

```bash
npx shadcn@latest add @uiarc/copy-button
pnpm dlx shadcn@latest add @uiarc/copy-button
yarn dlx shadcn@latest add @uiarc/copy-button
bunx --bun shadcn@latest add @uiarc/copy-button
```

The `@uiarc` name needs `"registries": { "@uiarc": "https://uiarc.dev/r/{name}.json" }` in `components.json`. Without it, use the full URL:

```bash
npx shadcn@latest add https://uiarc.dev/r/copy-button.json
```

### Manual

1. Install the dependencies:

```bash
npm install motion lucide-react
```

2. Copy the source into your project. Main file: `registry/components/copy-button/copy-button.tsx`

   The source is in the registry item: https://uiarc.dev/r/copy-button.json

3. Arc imports use the `@/` alias for `registry/` and `lib/`. Keep the same folders or update the import paths.

## Usage

```tsx
import { CopyButton } from "@/components/arc/copy-button/copy-button";

export function ApiKeyRow({ apiKey }: { apiKey: string }) {
  return (
    <div className="row">
      <code>{apiKey}</code>
      <CopyButton value={apiKey} label="Copy key" iconOnly />
    </div>
  );
}
```

## API reference

### CopyButton

Copies a string to the clipboard and crossfades its icon and label to Copied or Failed.

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `value` (required) | `string` | – | The text to copy. |
| `label` | `string` | `"Copy"` | Idle label and accessible name. |
| `iconOnly` | `boolean` | `false` | Hides the text and shows only the icon. |
| `variant` | `"outline" \| "plain"` | `"outline"` | Bordered or borderless. |
| `disabled` | `boolean` | – | Disables the button. |
| `onCopied` | `() => void` | – | Called after a successful copy. |
| `className` | `string` | – | Extra class on the button. |

## Keyboard interactions

| Keys | Action |
| --- | --- |
| Enter / Space | Copies the value. |

## Accessibility

- Native button named by label, including when iconOnly.
- A polite role="status" region announces "<label>: Copied" or "<label>: Could not copy".
- The label cell reserves the widest of its three states, so the layout never shifts.

## Motion

- The old icon and word fade out in about 100ms while the new ones fade in over about 160ms, with no blur; the check draws its stroke in.
- The label changes as one word, never letter by letter, and the same crossfade plays when it resets.
- Reduced motion swaps icon and text with an instant fade and skips the stroke draw.

## Responsive behavior

- The label reserves the width of its widest state, so the button never shifts its neighbours when it changes.
- It sizes to max-content with max-width 100%, so it stays compact in narrow rows.

## Performance

- Each copy is one short crossfade of the icon and the word (about 160ms) plus a quick stroke draw on the check; nothing animates per letter.
- Clipboard access is async and needs a secure context; failures show the Failed state rather than throwing.

## Notes for AI

- Use next to any copyable value: API keys, install commands, links, code. For a copy action that also has alternatives use split-button.
- Named export only; there is no default export.
- Clipboard state and reset timing come from lib/use-copy-feedback, so copy that file along with the component.

## Related

- [Button](https://uiarc.dev/components/button/markdown): A clear, responsive action with quiet secondary states.
- [Code block](https://uiarc.dev/components/code-block/markdown): Present code with legible hierarchy and copy access.
- [Split button](https://uiarc.dev/components/split-button/markdown): A primary action with a menu of nearby alternatives.
- [Action button](https://uiarc.dev/components/action-button/markdown): A compact button for frequent toolbar actions.

## Also in buttons

- [Button group](https://uiarc.dev/components/button-group/markdown): Related actions joined into one surface with hairline dividers: a hover highlight glides between segments, the pressed one answers in place, and an attached menu can close the row.
- [Floating button group](https://uiarc.dev/components/floating-button-group/markdown): Separate soft buttons in a quiet tray, with one shared highlight that morphs from button to button as you move, and a pressed state that settles in place.
- [Expanding button group](https://uiarc.dev/components/expanding-button-group/markdown): Icon buttons in a compact group: the one you point at or focus grows to reveal its label while its neighbours slide aside, and an action confirms in place.
- [Action swap](https://uiarc.dev/components/action-swap/markdown): Swap an action label while preserving its place and intent.
- [Icon morph](https://uiarc.dev/components/icon-morph/markdown): Icons that morph between states: menu to close, play to pause, copy to check, and more.
- [Confirm morph](https://uiarc.dev/components/confirm-morph/markdown): A destructive button that morphs into an inline confirmation, a spinner, and a result with undo.

## Guidance for AI tools

Copy button: Copy a value with immediate confirmation. Follow the declared prop types and do not invent props. Keep keyboard access, reduced motion support, and both light and dark themes intact when adapting it.

Full library index: https://uiarc.dev/llms.txt
