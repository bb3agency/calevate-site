# Morph select

> A select whose trigger grows into the list, with a gliding highlight and type-ahead.

- Type: Component (inputs)
- Access: Free, open source
- Page: https://uiarc.dev/components/morph-select
- Markdown: https://uiarc.dev/components/morph-select/markdown
- Registry item: https://uiarc.dev/r/morph-select.json
- Source file: `registry/components/morph-select/morph-select.tsx`
- Dependencies: motion, lucide-react
- Keywords: inputs, new, react select, animated select, morphing dropdown, listbox, select with search, grouped select, custom select component, type-ahead select

## When to use

- Form fields and property panels where one value is picked from a known list.
- Grouped lists like time zones, assignees, or projects, with optional icons and meta.
- Compact toolbars where the picker should look like a pill until opened.

## When not to use

- Use combobox when users type free text or the list is very long and remote.
- Use multi-select when more than one value can be chosen.
- Use dropdown-menu for actions rather than a stored value.

## Installation

### CLI

Run one of these in a project set up with `shadcn init`:

```bash
npx shadcn@latest add @uiarc/morph-select
pnpm dlx shadcn@latest add @uiarc/morph-select
yarn dlx shadcn@latest add @uiarc/morph-select
bunx --bun shadcn@latest add @uiarc/morph-select
```

The `@uiarc` name needs `"registries": { "@uiarc": "https://uiarc.dev/r/{name}.json" }` in `components.json`. Without it, use the full URL:

```bash
npx shadcn@latest add https://uiarc.dev/r/morph-select.json
```

### Manual

1. Install the dependencies:

```bash
npm install motion lucide-react
```

2. Copy the source into your project. Main file: `registry/components/morph-select/morph-select.tsx`

   The source is in the registry item: https://uiarc.dev/r/morph-select.json

3. Arc imports use the `@/` alias for `registry/` and `lib/`. Keep the same folders or update the import paths.

## Usage

```tsx
import { useState } from "react";
import { MorphSelect } from "@/components/arc/morph-select/morph-select";

export function TimezoneField() {
  const [zone, setZone] = useState<string | null>("europe/zurich");
  return (
    <MorphSelect
      label="Time zone"
      name="timezone"
      value={zone}
      onValueChange={setZone}
      items={[
        { label: "Europe", options: [
          { value: "europe/london", label: "London", meta: "UTC+0" },
          { value: "europe/zurich", label: "Zurich", meta: "UTC+1", keywords: "switzerland" },
        ] },
        { label: "Americas", options: [
          { value: "america/new_york", label: "New York", meta: "UTC−5" },
          { value: "america/los_angeles", label: "Los Angeles", meta: "UTC−8" },
        ] },
      ]}
    />
  );
}
```

## API reference

### MorphSelect

A select whose trigger grows into the option list, with groups, type-ahead, optional search, and a label that flies back into the trigger.

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `label` (required) | `string` | – | Visible label, also the accessible name of the trigger and the list. |
| `hideLabel` | `boolean` | `false` | Keeps the label for assistive technology only. |
| `items` (required) | `MorphSelectItem[]` | – | Options { value, label, icon?, meta?, keywords?, disabled? } or groups { label, options }, in display order. |
| `value` | `string \| null` | – | Controlled selected value. |
| `defaultValue` | `string \| null` | `null` | Uncontrolled starting value. |
| `onValueChange` | `(value: string, option: MorphSelectOption) => void` | – | Called with the new value and its option. |
| `placeholder` | `string` | `"Select"` | Trigger text with no selection. |
| `searchable` | `boolean \| "auto"` | `"auto"` | Shows a search field in place of the trigger when open. auto turns it on above eight options. |
| `searchPlaceholder` | `string` | – | Search field placeholder. Defaults to the selected label, then "Search". |
| `panelWidth` | `number` | `272` | Width of the open surface in px. Never narrower than the trigger. |
| `maxListHeight` | `number` | `296` | Tallest the option list gets before it scrolls, in px. |
| `align` | `"start" \| "end"` | `"start"` | Which edge of the trigger stays put while the surface grows. |
| `name` | `string` | – | Adds a hidden input for native form submission. |
| `disabled` | `boolean` | `false` | Disables the trigger. |
| `className` | `string` | – | Extra class on the root. |

## Keyboard interactions

| Keys | Action |
| --- | --- |
| Enter / Space / ArrowDown / ArrowUp | Opens the list on the selected option; Enter or Space picks the active option when open. |
| ArrowDown / ArrowUp | Moves the active option, skipping disabled ones. |
| PageDown / PageUp | Moves eight options at a time. |
| Home / End | Moves to the first or last option; when closed, opens on it. |
| Alt + ArrowUp | Picks the active option and closes. |
| Printable characters | Type-ahead jumps to a matching label, or starts a search when search is on. |
| Escape | Closes and returns focus to the trigger. |
| Tab | Closes and moves focus on without picking. |

## Accessibility

- The trigger is a role="combobox" with aria-haspopup="listbox", aria-expanded, and aria-activedescendant pointing at the active option.
- With search on, the input takes over as the combobox with aria-autocomplete="list", and the trigger turns inert.
- Options are role="option" with aria-selected and aria-disabled; groups are role="group" labelled by their heading.
- A polite status announces the number of search results or No matches.

## Motion

- The trigger surface grows into the list on a physical spring with slight bounce and folds back without overshoot; the corner radius morphs with it.
- One highlight glides between options; the chosen label lifts out of the list and flies into the trigger while the trigger width springs.
- Values in the trigger roll up or down depending on whether the new option is later or earlier in the list.
- Reduced motion jumps the size, removes the fly and roll, and uses short fades.

## Responsive behavior

- The closed trigger sizes to its label up to min(20rem, 100vw - 2rem); the open list is max(trigger width, min(panelWidth, 100vw - 2rem)).
- Set align="end" for triggers near the right edge so the surface grows leftward.
- Hover highlight follows the mouse only; on touch a tap picks directly, and hover styles apply only on fine pointers.

## Performance

- A hidden measuring copy and a ResizeObserver size the trigger and list; the surface animates width, height, and radius through motion values.
- All options render; there is no virtualization, so keep lists to a few hundred items.
- Search filters in memory on label, meta, and keywords.

## Notes for AI

- Use for compact property pickers and form fields with up to a few hundred options, including avatars or icons.
- Add keywords to options so search matches synonyms; meta shows trailing detail like counts or offsets.
- Pass name to submit with a native form; the hidden input carries the value.
- Use combobox when people mostly type free text, and multi-select for several values.

## Related

- [Select](https://uiarc.dev/components/select/markdown): A compact choice field with a keyboard friendly menu.
- [Combobox](https://uiarc.dev/components/combobox/markdown): Search and select from a list without leaving the field.
- [Multi-select](https://uiarc.dev/components/multi-select/markdown): Select several values while keeping the field readable.
- [Dropdown menu](https://uiarc.dev/components/dropdown-menu/markdown): A focused list of actions anchored to a trigger.

## Also in selects

- [Chip group](https://uiarc.dev/components/chip-group/markdown): Filter by a few facets with chips that morph as you pick them.

## Guidance for AI tools

Morph select: A select whose trigger grows into the list, with a gliding highlight and type-ahead. Follow the declared prop types and do not invent props. Keep keyboard access, reduced motion support, and both light and dark themes intact when adapting it.

Full library index: https://uiarc.dev/llms.txt
