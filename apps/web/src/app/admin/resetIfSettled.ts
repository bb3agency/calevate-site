/**
 * Clears a write's last answer (its refusal, its "Saved"), but never while it is in flight.
 *
 * TanStack's `reset()` on a PENDING mutation detaches the request from the screen rather than
 * cancelling it: the button reads idle again, so a second press sends a second write while the
 * first is still running, and the first one's per-call `onSuccess` never runs. Screens clear
 * the answer when a field changes or a panel opens, which a person can do mid-request.
 */
export function resetIfSettled(mutation: { isPending: boolean; reset: () => void }): void {
  if (!mutation.isPending) mutation.reset();
}
