/**
 * BUILD-LOG §52's forbidden shapes, and their safe look-alikes, written out once so the
 * guard can be pointed at something that MUST fail.
 *
 *     loading is a skeleton, failure is a refusal, and neither is a number, a state,
 *     or an empty state.
 *
 * The mechanism the rule is about is a fallback applied to the QUERY ENVELOPE. A
 * TanStack `UseQueryResult.data` is `T | undefined`, and that `undefined` means exactly
 * one thing: *we have not got an answer* — still in flight, or the request failed.
 * Coalescing it to a literal converts "we could not read it" into a confident value,
 * which is how `platform?.outbound_halted ?? false` reported a HALTED platform as
 * running, and `?? 5430` showed 5,430 calls to a client whose calls had stopped.
 *
 * The safe shapes below are not invented for the test. Each is a transcription of a real
 * site the §52 sweep deliberately left alone, and each one would be flagged by an
 * earlier, wider draft of this guard — which is why they are here. See the rejected
 * drafts and their measured false-positive counts in tests/surfaceStatesGuard.test.ts.
 *
 * This file is deliberately NOT fixed. It is excluded from `pnpm lint` in
 * eslint.config.mjs and it type-checks cleanly, which is the whole point: `tsc` has no
 * objection to any of the banned lines, and that is why this guard exists at all.
 */

import { useMutation, useQuery, type UseMutationResult, type UseQueryResult } from "@tanstack/react-query";

interface Board {
  /** A server-side flag. `false` here is a FACT; `false` invented locally is a claim. */
  halted: boolean;
  /** A complete count from the server. */
  total: number;
  /** Nullable IN THE PAYLOAD — the server sends `null` on purpose when none was recorded. */
  label: string | null;
  rows: string[];
}

function useBoard(): UseQueryResult<Board> {
  return useQuery({ queryKey: ["fixture-board"], queryFn: async (): Promise<Board> => ({
    halted: false,
    total: 0,
    label: null,
    rows: [],
  }) });
}

function useSaveBoard(): UseMutationResult<Board, Error, void> {
  return useMutation({ mutationFn: async (): Promise<Board> => ({
    halted: false,
    total: 0,
    label: null,
    rows: [],
  }) });
}

// ─── BANNED ──────────────────────────────────────────────────────────────────────────

/**
 * bannedBooleanFallback — the ops-screen defect, in one line. A boolean has no absent
 * value, so a fallback does not defer the question, it ANSWERS it: the screen states
 * "not halted" on the strength of a request that never landed.
 */
export function bannedBooleanFallback(): boolean {
  const board = useBoard();
  return board.data?.halted ?? false;
}

/**
 * bannedBooleanFallbackDestructured — the same defect written the other common way.
 * `const { data } = useQuery(...)` hides the envelope behind a bare identifier; a guard
 * that only looked for `X.data` would wave this through, so the resolution follows the
 * binding element back to the query it was destructured from.
 */
export function bannedBooleanFallbackDestructured(): boolean {
  const { data } = useBoard();
  return data?.halted ?? false;
}

/**
 * bannedRenderedCount — the dashboard's `?? 5430`, generalised. The coalesce sits in a
 * JSX CHILD position, so the manufactured number is the pixel: an unread count printed
 * as a fact, indistinguishable from a real zero.
 */
export function bannedRenderedCount(): React.JSX.Element {
  const board = useBoard();
  return <span>{board.data?.total ?? 0}</span>;
}

/**
 * bannedBooleanCoercion — `?? false` wearing a different hat, and the spelling the
 * original rule missed. `Boolean(x)` where `x` is `boolean | undefined` maps our
 * ignorance onto `false` exactly as `?? false` does; the leads table used it to decide
 * whether the session was impersonating and answered "no" over a dead `/v1/me`.
 *
 * `Boolean(board.data)` — the OBJECT, not a flag off it — is the opposite shape and is
 * safe. See `safePresenceTest`.
 */
export function bannedBooleanCoercion(): boolean {
  const board = useBoard();
  return Boolean(board.data?.halted);
}

/**
 * bannedUnrefusedListFallback — `?? []` where the screen has no failure branch at all.
 *
 * The `[]` itself is not the defect and never was: `admin/health/page.tsx` writes the
 * identical line under a `isLoading ? … : error ? … :` ladder and is correct
 * (`safeGuardedListFallback` below). What makes this one a lie is that NOTHING in the
 * component ever reads `board.isError` — so the empty list is the only thing a failed
 * read can produce, and the screen states "you have none" when it means "we could not
 * ask". This is the lead-sources agent picker, which offered a client one option — "save
 * leads, don't call" — over a failed `/v1/agents`.
 */
export function bannedUnrefusedListFallback(): React.JSX.Element {
  const board = useBoard();
  const rows = board.data?.rows ?? [];
  return (
    <select>
      {rows.map((row) => (
        <option key={row}>{row}</option>
      ))}
    </select>
  );
}

/**
 * bannedVanishingControl — `{q.data && <control/>}` with no failure branch.
 *
 * §52's first clause says failure is a REFUSAL. Nothing is not a refusal: the client is
 * told neither that the action exists nor why they cannot take it, and the screen is
 * indistinguishable from one where the feature was never built. This is the call
 * detail's follow-up card, which hid itself on a failed eligibility read — the exact
 * silent-nothing that card's own comment says it exists to prevent.
 */
export function bannedVanishingControl(): React.JSX.Element {
  const board = useBoard();
  return <div>{board.data && <button type="button">Call back</button>}</div>;
}

/**
 * bannedFirstRowFallthrough — `?.[0]` and the branch under it, which is the worst shape
 * on this list because the fall-through is not "less", it is SOMETHING ELSE.
 *
 * `filed.data?.[0]` is undefined while the read is in flight and again after it 503s.
 * The admin lifecycle screen tested that value to decide between "an erasure has already
 * been filed" and the form that FILES one — so during the read, and forever after a
 * failure, it offered an irreversible DPDP tenant-wide erasure while stating that none
 * had been filed. The one it may already have been running.
 */
export function bannedFirstRowFallthrough(): React.JSX.Element {
  const board = useBoard();
  const first = board.data?.rows[0];
  if (first) {
    return <p>Already filed: {first}</p>;
  }
  return (
    <form>
      <button type="submit">File it</button>
    </form>
  );
}

// ─── SAFE — the guard must stay silent on every one of these ────────────────────────

/**
 * A PAYLOAD null, not an envelope undefined. `board.data` is narrowed to defined by the
 * two guards above it, so the only thing `??` can be catching is the `null` the server
 * deliberately sent — a fact about the world, correctly rendered as "—".
 *
 * This is the distinction the guard exists to keep, and getting it wrong in the tolerant
 * direction is what an earlier draft did: it read `verify.data.first_bad_entry_id ?? "an
 * entry it did not name"` on the ops screen as a violation, when that line is the
 * refusal doing its job.
 */
export function safePayloadNull(): React.JSX.Element {
  const board = useBoard();
  if (board.isPending) return <span>skeleton</span>;
  if (board.isError) return <span>we could not read this</span>;
  return <span>{board.data.label ?? "—"}</span>;
}

/** A form field's own draft state. Nothing here came off the wire. */
export function safeFormDefault(initial: boolean | undefined): boolean {
  return initial ?? false;
}

/** A local constant, computed here. Its absence is ours, not the server's. */
export function safeLocalConstant(rows: string[] | undefined): number {
  return rows?.length ?? 0;
}

/**
 * `?? []` on an envelope read, in a component that DOES refuse — `admin/health/page.tsx`
 * and `admin/holds/page.tsx`, transcribed with the ladder they actually carry.
 *
 * The literal is identical to `bannedUnrefusedListFallback`'s. What separates them is
 * the `board.isError` branch above: with it, the `[]` is only ever reached on a read
 * that succeeded and returned nothing, which is a fact. Without it, the `[]` IS the
 * failed read. That is the whole of the guard's gate, and it is why the rule asks a
 * question about the component rather than about the expression.
 */
export function safeGuardedListFallback(): React.JSX.Element {
  const board = useBoard();
  const rows = board.data?.rows ?? [];
  return (
    <div>
      {board.error != null && <p>We could not read this. Reload the page to try again.</p>}
      <span>{rows.length}</span>
    </div>
  );
}

/**
 * An absence MARKER, not a value. "—" claims nothing about the world; `0` and `false`
 * do. `c/[slug]/layout.tsx` renders the org name this way while `/v1/me` is in flight.
 */
export function safeAbsenceMarker(): React.JSX.Element {
  const board = useBoard();
  return <span>{board.data?.label ?? "—"}</span>;
}

/**
 * `Boolean(q.data)` — "has the answer arrived?", which is the honest question and this
 * repo's own settled spelling for it (`hasNoAgents` on /campaigns and /knowledge,
 * `showRows` on /leads, each with a comment saying why `!isLoading` was not enough).
 * The coerced value is an OBJECT, so nothing about the world is being guessed; the test
 * is about our own knowledge. `bannedBooleanCoercion` coerces a FLAG off that object,
 * which is the opposite.
 */
export function safePresenceTest(): React.JSX.Element {
  const board = useBoard();
  const arrived = Boolean(board.data);
  return <span>{arrived ? "loaded" : "still asking"}</span>;
}

/**
 * The NEGATIVE guard — `if (!q.data) return <refusal/>` — which is the correct spelling
 * of `bannedFirstRowFallthrough` and must never be confused with it. Polarity is the
 * whole difference: the author who writes `!` is asking the §52 question and answering
 * it, and the one who writes the positive test is treating "we do not know" as "no".
 */
export function safeNegativeGuard(): React.JSX.Element {
  const board = useBoard();
  if (!board.data) {
    return <p>We could not read this. Reload the page to try again.</p>;
  }
  return (
    <form>
      <button type="submit">File it</button>
    </form>
  );
}

/**
 * A MUTATION's `data`, which is a different word. For a query, `undefined` means "we
 * have not got an answer"; for a mutation it means "the user has not asked yet" — a
 * true statement about the world that the screen is right to render as nothing. Every
 * `{save.data && <notice/>}` in this app is this shape, so a guard that did not
 * distinguish the two envelopes would fire on all of them and be deleted within a week.
 */
export function safeMutationNotYetRun(): React.JSX.Element {
  const save = useSaveBoard();
  // The branch holds a CONTROL on purpose. With prose in it, rule 4 would skip this
  // function for the wrong reason — `offersAControl` would answer no — and the
  // query/mutation split it is here to pin would not be exercised at all. That is not a
  // hypothetical: this fixture DID hold a `<p>Saved.</p>`, and neutering the split in the
  // guard left the whole suite green.
  return <div>{save.data && <button type="button">Undo</button>}</div>;
}

/**
 * A note, not a control. §52 is about what the screen OFFERS: a button, a form field or
 * a link that silently vanishes leaves the client unable to act and unable to ask why,
 * while a sentence that is only printed when we know it applies is simply a sentence we
 * do not have. `leads/[leadId]/page.tsx` prints the read-only note this way.
 *
 * The line between them is the only thing keeping the rule at nine live hits instead of
 * a dozen more, and it is drawn where §52 draws it.
 */
export function safeProseWithoutControl(): React.JSX.Element {
  const board = useBoard();
  return <div>{board.data?.halted && <span>Outbound is halted.</span>}</div>;
}

/**
 * The FAIL-CLOSED permission check, which four screens spell exactly this way
 * (`/attention`, `/invoice`, `/performance`, `/usage`) and which is correct: the refusal
 * is only stated once the answer has ARRIVED, so an in-flight or failed read refuses
 * nothing and claims nothing.
 *
 * It is here because it sits one character from the defect and would be flagged by two
 * plausible drafts of rule 4. `board.data !== undefined` is an explicit comparison rather
 * than a truthiness test, and `refused` is a `boolean` rather than a value still carrying
 * the query's `undefined` — either narrowing alone keeps this out, and the guard has both.
 */
export function safeFailClosedPermissionCheck(): React.JSX.Element {
  const board = useBoard();
  const refused = board.data !== undefined && board.data.halted;
  if (refused) {
    return <p>Outbound is halted, so this cannot be sent.</p>;
  }
  return (
    <form>
      <button type="submit">Send</button>
    </form>
  );
}

/**
 * The vanishing control, FIXED — the shape every one of the nine sites was moved to.
 * The control is still conditional on the data, and now the failed read has somewhere
 * of its own to go, so the gate is satisfied and the same `&&` is no longer a lie.
 */
export function safeRefusedControl(): React.JSX.Element {
  const board = useBoard();
  if (board.isError) return <p>We could not check this. Reload the page to try again.</p>;
  return <div>{board.data && <button type="button">Call back</button>}</div>;
}
