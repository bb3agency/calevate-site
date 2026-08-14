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

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

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
 * `?? []` on an envelope read, feeding a list whose empty case is guarded elsewhere on
 * the screen (`admin/health/page.tsx`, `admin/holds/page.tsx`). Whether this is honest
 * depends on which branch renders it, which no source-level check can decide — so it is
 * OUT OF SCOPE and must not be flagged. The test file says so in full.
 */
export function safeGuardedListFallback(): string[] {
  const board = useBoard();
  return board.data?.rows ?? [];
}

/**
 * An absence MARKER, not a value. "—" claims nothing about the world; `0` and `false`
 * do. `c/[slug]/layout.tsx` renders the org name this way while `/v1/me` is in flight.
 */
export function safeAbsenceMarker(): React.JSX.Element {
  const board = useBoard();
  return <span>{board.data?.label ?? "—"}</span>;
}
