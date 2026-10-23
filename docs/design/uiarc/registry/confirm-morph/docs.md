# Confirm morph

> A destructive button that morphs into an inline confirmation, a spinner, and a result with undo.

- Type: Component (actions)
- Access: Free, open source
- Page: https://uiarc.dev/components/confirm-morph
- Markdown: https://uiarc.dev/components/confirm-morph/markdown
- Registry item: https://uiarc.dev/r/confirm-morph.json
- Source file: `registry/components/confirm-morph/confirm-morph.tsx`
- Dependencies: motion, lucide-react
- Keywords: actions, new, react confirm button, inline confirmation, delete confirmation button, confirm delete without modal, undo button, two step button, destructive action button

## When to use

- Deleting a selection in a table or file list, right where the button sits.
- Revoking access, removing a member, or discarding a draft.
- Actions that should offer Undo in place after they finish.

## When not to use

- Use dialog when the consequence needs more than one line, or when typing a name to confirm is required.
- Use action-button for safe async actions that need no question.
- Use hold-to-confirm when an accidental tap must be nearly impossible.

## Installation

### CLI

Run one of these in a project set up with `shadcn init`:

```bash
npx shadcn@latest add @uiarc/confirm-morph
pnpm dlx shadcn@latest add @uiarc/confirm-morph
yarn dlx shadcn@latest add @uiarc/confirm-morph
bunx --bun shadcn@latest add @uiarc/confirm-morph
```

The `@uiarc` name needs `"registries": { "@uiarc": "https://uiarc.dev/r/{name}.json" }` in `components.json`. Without it, use the full URL:

```bash
npx shadcn@latest add https://uiarc.dev/r/confirm-morph.json
```

### Manual

1. Install the dependencies:

```bash
npm install motion lucide-react
```

2. Copy the source into your project. Main file: `registry/components/confirm-morph/confirm-morph.tsx`

   The source is in the registry item: https://uiarc.dev/r/confirm-morph.json

3. Arc imports use the `@/` alias for `registry/` and `lib/`. Keep the same folders or update the import paths.

## Usage

```tsx
import { Trash2 } from "lucide-react";
import { ConfirmMorph } from "@/components/arc/confirm-morph/confirm-morph";

export function DeleteSelection({ ids }: { ids: string[] }) {
  return (
    <ConfirmMorph
      label="Delete files"
      icon={<Trash2 size={16} strokeWidth={1.75} />}
      prompt={`Delete ${ids.length} files?`}
      confirmMode="hold"
      onConfirm={() => deleteFiles(ids)}
      onUndo={() => restoreFiles(ids)}
    />
  );
}
```

## API reference

### ConfirmMorph

A button for destructive or important actions that morphs in place into an inline question, then a spinner, then a result with Undo. Answer it with a click, a press and hold, or a click and a short countdown.

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `label` (required) | `ReactNode` | – | The resting label, such as "Delete project". |
| `icon` | `ReactNode` | – | A plain icon before the resting label. |
| `prompt` | `ReactNode` | – | The question while confirming, such as "Delete 3 files?". Defaults to the label with a question mark. |
| `confirmLabel` | `string` | `"Delete"` | Confirm button label. |
| `cancelLabel` | `string` | `"Cancel"` | Cancel button label. |
| `pendingLabel` | `string` | `"Deleting"` | Shown beside the spinner while onConfirm resolves. |
| `doneLabel` | `string` | `"Deleted"` | Result label. |
| `errorLabel` | `string` | `"Couldn’t finish"` | Error label. |
| `retryLabel` | `string` | `"Retry"` | Retry button label on the error face. |
| `undoLabel` | `string` | `"Undo"` | Undo button label. |
| `undoingLabel` | `string` | `"Restoring"` | Shown beside the spinner while onUndo resolves. |
| `tone` | `"danger" \| "neutral"` | `"danger"` | danger gives the confirm button the danger colour, for actions that destroy something; neutral gives it the accent, for important actions that can be reversed. The resting button is neutral either way. |
| `confirmMode` | `"press" \| "hold" \| "countdown"` | `"press"` | press confirms on a press. hold asks for the confirm button to be held for holdDuration while it fills. countdown confirms, then counts down countdown seconds that Cancel or Escape can still stop. |
| `holdDuration` | `number` | `1000` | Milliseconds the confirm button must be held in hold mode. |
| `countdown` | `number` | `3` | Seconds counted down before the action runs in countdown mode. |
| `countdownLabel` | `string` | – | Text before the seconds in countdown mode, such as "Deleting in". Defaults to pendingLabel followed by "in". |
| `onConfirm` | `() => void \| Promise<unknown>` | – | Runs on confirm. Return a promise to show the pending face; a rejection shows the error face with Retry. |
| `onUndo` | `() => void \| Promise<unknown>` | – | Adds Undo to the result. Return a promise to show a pending face while it runs. |
| `onCancel` | `() => void` | – | Called when the question is cancelled, including by Escape, outside press, or timeout. |
| `state` | `"idle" \| "confirming" \| "pending" \| "done" \| "error"` | – | Controlled state. Pair it with onStateChange. |
| `defaultState` | `"idle" \| "confirming" \| "pending" \| "done" \| "error"` | `"idle"` | Starting state when uncontrolled. |
| `onStateChange` | `(state: ConfirmMorphState) => void` | – | Called on every state change. |
| `confirmTimeout` | `number` | `6000` | Milliseconds before an unanswered question returns to rest. Hovering pauses it; 0 turns it off. |
| `resultTimeout` | `number` | `5000` | Milliseconds a result stays before returning to rest. Hovering pauses it; 0 turns it off. |
| `cancelOnOutsidePress` | `boolean` | `true` | A press outside the control cancels an open question. |
| `disabled` | `boolean` | `false` | Disables the resting button. |
| `className` | `string` | – | Class on the root. |
| `ref` | `Ref<HTMLDivElement>` | – | The root element, which also takes focus while the action is pending. |

## Keyboard interactions

| Keys | Action |
| --- | --- |
| Enter / Space | Presses the focused face button: start, Confirm, Cancel, Undo, or Retry. In hold mode, holding Enter or Space on Confirm fills it. |
| Enter | While asking, confirms from the question (Confirm takes focus when it opens); during a countdown, runs the action now. |
| Tab / Shift+Tab | Moves between Cancel and Confirm while asking. |
| Escape | Cancels the question or the countdown, or dismisses a result back to rest. |

## Accessibility

- The question face is a group labelled by the prompt. Confirm takes focus so Enter answers yes, but a press within 280ms of opening and auto-repeated keys are ignored, so a double click or a held Enter never confirms by accident.
- Focus follows the morph: Confirm while asking, the root during a countdown or while pending (with aria-busy), Undo or Retry on a result, and the trigger back at rest.
- In hold mode the confirm button is described as "Press and hold", and letting go early announces that it needs a longer hold.
- Prompts, pending labels, results, and "Undo is available" are announced through a polite live region.
- Timeouts pause while the pointer rests on the control and while the tab is hidden.

## Motion

- Only the pill's width moves, on the morph spring growing and the smooth spring shrinking, so corners and text never scale or wobble and nothing around it jumps.
- Every face sits at its natural width against the pill's leading edge: the question starts where the label was and the springing edge reveals the rest, so text never squashes, slides, or leaves its baseline.
- The new face's parts arrive in reading order, each clearing a small blur; the old face fades out where it stood. The done check pops and draws itself, and countdown digits swap on tabular figures.
- In hold mode a solid danger copy of the button is revealed from the left as the hold fills and drains back on a spring if released early.
- Reduced motion removes the width spring, blur, and draw; faces crossfade and the spinner slows. The hold fill and countdown ring still show progress.

## Responsive behavior

- The control is as wide as its current face; leave room beside it for the question face, which is wider than the resting button.
- Hover styles apply only on hover-capable fine pointers; the control keeps the small control height, so give Cancel and Confirm some space from nearby targets on touch layouts.

## Performance

- Only the current face and the one leaving render; a ResizeObserver per face measures width for the spring.
- The timeout is a single linear motion value animation that pauses and resumes, not a timer per frame.

## Notes for AI

- Use for destructive or important actions that deserve a second press but not a modal: delete, revoke, discard.
- Return the real promise from onConfirm; rejections show the error face with Retry, which reruns the same handler.
- Offer onUndo when the action can be reversed; then consider a short confirmTimeout or skipping the question in your own flow.
- Use confirmMode="hold" for the riskiest deletes and "countdown" when there is no Undo; use dialog when the consequence needs a full explanation.
- Keep the resting button neutral; tone="danger" only colours the confirm answer, and tone="neutral" moves it to the accent for reversible actions.

## Related

- [Hold to confirm](https://uiarc.dev/components/hold-to-confirm/markdown): Confirm a destructive action by holding, not tapping.
- [Action button](https://uiarc.dev/components/action-button/markdown): A compact button for frequent toolbar actions.
- [Action morph](https://uiarc.dev/components/action-morph/markdown): A floating button that morphs into a quick-action menu, then an inline form, then back with a check.
- [Dialog](https://uiarc.dev/components/dialog/markdown): A focused surface for decisions that need attention.
- [Toast](https://uiarc.dev/components/toast/markdown): Brief confirmation for a completed background action.

## Also in buttons

- [Button](https://uiarc.dev/components/button/markdown): A clear, responsive action with quiet secondary states.
- [Split button](https://uiarc.dev/components/split-button/markdown): A primary action with a menu of nearby alternatives.
- [Button group](https://uiarc.dev/components/button-group/markdown): Related actions joined into one surface with hairline dividers: a hover highlight glides between segments, the pressed one answers in place, and an attached menu can close the row.
- [Floating button group](https://uiarc.dev/components/floating-button-group/markdown): Separate soft buttons in a quiet tray, with one shared highlight that morphs from button to button as you move, and a pressed state that settles in place.
- [Expanding button group](https://uiarc.dev/components/expanding-button-group/markdown): Icon buttons in a compact group: the one you point at or focus grows to reveal its label while its neighbours slide aside, and an action confirms in place.
- [Copy button](https://uiarc.dev/components/copy-button/markdown): Copy a value with immediate confirmation.
- [Action swap](https://uiarc.dev/components/action-swap/markdown): Swap an action label while preserving its place and intent.
- [Icon morph](https://uiarc.dev/components/icon-morph/markdown): Icons that morph between states: menu to close, play to pause, copy to check, and more.

## Guidance for AI tools

Confirm morph: A destructive button that morphs into an inline confirmation, a spinner, and a result with undo. Follow the declared prop types and do not invent props. Keep keyboard access, reduced motion support, and both light and dark themes intact when adapting it.

Full library index: https://uiarc.dev/llms.txt
