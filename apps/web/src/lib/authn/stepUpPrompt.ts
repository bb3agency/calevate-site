/**
 * "Confirm it is still you", asked once and answered once, however many callers asked.
 *
 * D-210. The API refuses a dangerous admin action whose second factor is older than
 * `REAUTH_MAX_AGE` (5 minutes) with `403 reauthentication_required`, and prints the two
 * endpoints that clear it. Until now the operator console had NO way to call them: the
 * step-up gate shipped on sixteen routes and the browser had no prompt, so the only
 * remedy an operator had was to sign out and back in. This module is the missing half.
 *
 * ═══ WHY IT IS A MODULE-LEVEL STORE AND NOT A HOOK OR A CONTEXT ═══
 *
 * The caller that needs it most is not in React's render path. `lib/api/admin.ts::mint`
 * is invoked from a `GrantSource` — a plain async function the transport calls once per
 * request while assembling headers (`client.ts`) — and there is no component, no hook and
 * no provider in scope there. A context would force every such caller to become a hook,
 * which `admin.ts` already argues it cannot: `viewAsSession(slug)` is called from ~15
 * places, several of them outside render.
 *
 * So the shape is the one React ships for exactly this — an external store read through
 * `useSyncExternalStore`. The prompt COMPONENT subscribes; anything at all may ask.
 *
 * ═══ SINGLE-FLIGHT, FOR THE SAME REASON THE GRANT CACHE IS ═══
 *
 * A screen opens six queries at once and they can refuse together. Six prompts would be
 * six modals, six emailed codes and five of them retired by the sixth
 * (`service.request_step_up` retires the previous challenge on issue) — i.e. an operator
 * typing a code that has already been invalidated. One pending promise, shared by every
 * asker, and they all settle on the one answer.
 *
 * ═══ IT RESOLVES `false` RATHER THAN REJECTING ═══
 *
 * A dismissed prompt must make the action FAIL, and the truest failure is the one the
 * server already sent: the caller is holding a `reauthentication_required` problem with
 * its own title, sentence and remediation. So this reports the OUTCOME and the caller
 * rethrows what it has, rather than this module inventing a second refusal vocabulary for
 * a condition the API has already named. It also means a prompt nobody answers can never
 * become an unhandled rejection.
 */

/** What a subscriber is told. `null` = no prompt is open. */
export type StepUpPromptState = { readonly reason: string } | null;

type Listener = () => void;

const listeners = new Set<Listener>();

let state: StepUpPromptState = null;

/** The one in-flight ask. Every concurrent caller awaits this exact promise. */
let pending: { promise: Promise<boolean>; settle: (proved: boolean) => void } | null = null;

function publish(next: StepUpPromptState): void {
  state = next;
  for (const listener of listeners) listener();
}

/**
 * Ask the operator to prove a second factor. `true` once they have, `false` if they close.
 *
 * `reason` is shown in the prompt and says what is waiting. The FIRST asker's wins: a
 * second caller joining a live prompt is told about the action already on screen, rather
 * than having the sentence change under the person reading it.
 */
export function requireStepUp(reason: string): Promise<boolean> {
  if (pending) return pending.promise;
  let settle!: (proved: boolean) => void;
  const promise = new Promise<boolean>((resolve) => {
    settle = resolve;
  });
  // Installed BEFORE anything is published, so a synchronous subscriber reacting to the
  // open state cannot observe a prompt with no promise behind it.
  pending = { promise, settle };
  publish({ reason });
  return promise;
}

function close(proved: boolean): void {
  const settled = pending;
  pending = null;
  publish(null);
  settled?.settle(proved);
}

/** The operator proved a factor. Everything that was waiting proceeds. */
export function completeStepUpPrompt(): void {
  close(true);
}

/**
 * Close the prompt without a factor — the operator dismissed it, or the session changed
 * under it (sign-out, a realm reset). Everything that was waiting is told `false`.
 */
export function dismissStepUpPrompt(): void {
  close(false);
}

/** `useSyncExternalStore`'s two halves. The snapshot is referentially stable while open. */
export function subscribeToStepUpPrompt(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function readStepUpPrompt(): StepUpPromptState {
  return state;
}
