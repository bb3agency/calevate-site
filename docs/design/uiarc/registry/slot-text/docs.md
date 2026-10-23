# Slot text

> Text and numbers that spin into their new value on staggered slot machine reels.

- Type: Component (special)
- Access: Free, open source
- Page: https://uiarc.dev/components/slot-text
- Markdown: https://uiarc.dev/components/slot-text/markdown
- Registry item: https://uiarc.dev/r/slot-text.json
- Source file: `registry/components/slot-text/slot-text.tsx`
- Dependencies: motion
- Keywords: special, text, numbers, new, slot machine text, rolling number, number ticker, odometer react, slot text animation, price animation, animated digits

## When to use

- Pricing toggles, KPI cards, dashboards changing period.
- Launch moments, raffles, and reveals.

## When not to use

- Values that update several times a second.
- Long sentences; reels are for short values.

## Installation

### CLI

Run one of these in a project set up with `shadcn init`:

```bash
npx shadcn@latest add @uiarc/slot-text
pnpm dlx shadcn@latest add @uiarc/slot-text
yarn dlx shadcn@latest add @uiarc/slot-text
bunx --bun shadcn@latest add @uiarc/slot-text
```

The `@uiarc` name needs `"registries": { "@uiarc": "https://uiarc.dev/r/{name}.json" }` in `components.json`. Without it, use the full URL:

```bash
npx shadcn@latest add https://uiarc.dev/r/slot-text.json
```

### Manual

1. Install the dependencies:

```bash
npm install motion
```

2. Copy the source into your project. Main file: `registry/components/slot-text/slot-text.tsx`

   The source is in the registry item: https://uiarc.dev/r/slot-text.json

3. Arc imports use the `@/` alias for `registry/` and `lib/`. Keep the same folders or update the import paths.

## Usage

```tsx
import { SlotText } from "@/components/arc/slot-text/slot-text";

<SlotText value={revenue} format={value => `$${value.toLocaleString("en-US")}`} announce />

<SlotText value={live ? "Live now" : "Soon"} spins={2} />
```

## API reference

### SlotText

Text or a number where every character is a reel. On change, digits count through the wheel in the direction the number moved, letters shuffle through the alphabet, and reels land left to right without overshoot.

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `value` (required) | `string \| number` | – | The value to show. Numbers pass through format. |
| `format` | `(value: number) => string` | – | Formats number values. Defaults to en-US grouping (12,480). |
| `duration` | `number` | `0.9` | Seconds the first reel spins. |
| `stagger` | `number` | `0.07` | Seconds between reels stopping, left to right. |
| `spins` | `number` | `1` | Extra full turns before landing. 0 rolls straight to the new digit. |
| `align` | `"start" \| "end"` | – | Which end reels are matched from when the length changes. Numbers default to end, strings to start. |
| `announce` | `boolean` | `false` | Announces new values politely to screen readers. |
| `className` | `string` | – | Extra class on the root. Font size and color come from the parent. |

## Accessibility

- The full value is real text in a visually hidden span; the reels are aria-hidden.
- announce adds a polite live region for values that change without user action.

## Motion

- Each reel spins with a fast start and a long, soft landing that never passes the target.
- Reels stop one after another left to right; blur follows each reel's speed, so fast spins smear and landings are sharp.
- A reel's width follows its new character on a critically damped spring, and new characters grow in while removed ones collapse.
- Leading symbols such as a currency sign stay on their own reels, and separators stay aligned from the end, so 999 to 1,000 only spins digits.
- Changing the value mid-spin restarts from the cell on screen, keeping its offset, so nothing jumps.
- Reduced motion swaps values instantly.

## Responsive behavior

- It is inline text and scales with its font size; reels are measured in em.

## Performance

- Each reel is one transform on a motion value; React re-renders only when the value changes.
- Blur is removed when a reel is still.

## Notes for AI

- Use it where a change deserves a beat: prices switching plans, stats changing period, a launch status flipping.
- Put it inside text you style; it inherits font, size, weight, and color. Digits use tabular numerals.
- For values that tick every second, use a counter with spins={0} or animated-counter; long spins on every tick get tiring.

## Related

- [Animated counter](https://uiarc.dev/components/animated-counter/markdown): Give changing totals a clear sense of movement.
- [Countdown](https://uiarc.dev/components/countdown/markdown): A launch countdown with rolling digits that morphs into a live state at zero.
- [Text morph](https://uiarc.dev/components/text-morph/markdown): Morph a label into its next state, letter by letter.
- [Billing toggle](https://uiarc.dev/components/billing-toggle/markdown): A monthly and yearly switch with a savings badge and prices that roll to the new amount.

## Also in type

- [Keycap keyboard](https://uiarc.dev/components/keycap-keyboard/markdown): Mechanical keycaps that sink and light up as you type, with the text above the board.
- [Sand text](https://uiarc.dev/components/sand-text/markdown): A headline made of sand that pours into the letters, crumbles where the cursor digs, and heals itself.
- [Typewriter terminal](https://uiarc.dev/components/typewriter-terminal/markdown): A terminal that types a scripted CLI session with a seeded human cadence, colors the shell syntax, and streams output lines, progress bars and spinners, with a scrubber, play/pause and replay controls.

## Guidance for AI tools

Slot text: Text and numbers that spin into their new value on staggered slot machine reels. Follow the declared prop types and do not invent props. Keep keyboard access, reduced motion support, and both light and dark themes intact when adapting it.

Full library index: https://uiarc.dev/llms.txt
