import type {
  DeadLetterQueue,
  EngineDrift,
  KbDrift,
  PlatformState,
} from "@/lib/api/admin";

/**
 * WHAT THIS SCREEN MAY KNOW ABOUT THE THREE SUMMARIES ON THE PLATFORM ROW.
 *
 * One subject, three readers, and the reason they are together is that they are the same
 * rule three times: loading is a skeleton, failure is a refusal, and neither is a number.
 */

/**
 * The dead-letter queue as this screen may know it — three states, and never a fourth.
 *
 * BUILD-LOG §52's rule, expressed as a type rather than as discipline: loading is a
 * skeleton, failure is a refusal, and neither is a number. A depth of 0 and a depth that
 * could not be read are OPPOSITE facts — one says "there is nothing to replay", the other
 * says "we have no idea what you are about to send" — and the whole reason this field
 * exists is to stop the second being confirmed as if it were the first. A
 * `DeadLetterQueue | undefined` would have collapsed them at the first `??`.
 */
export type DeadLetterState =
  | { status: "loading" }
  | { status: "unreadable" }
  | { status: "read"; queue: DeadLetterQueue };

export function deadLetterState(query: {
  data: PlatformState | undefined;
  error: unknown;
  isLoading: boolean;
}): DeadLetterState {
  // Error first: a refetch that fails leaves the previous `data` in place, and a stale
  // depth rendered as current is the same lie as an invented one.
  if (query.error) return { status: "unreadable" };
  if (query.isLoading || !query.data) return { status: "loading" };
  return { status: "read", queue: query.data.outbox_dead_letters };
}

/**
 * The drift summary as this screen may know it — the same three states, and never a
 * fourth, for `DeadLetterState`'s reason: "no agent has drifted" and "we could not find
 * out whether any agent has drifted" are OPPOSITE facts, and a `EngineDrift | undefined`
 * collapses them at the first `??`.
 */
export type EngineDriftState =
  | { status: "loading" }
  | { status: "unreadable" }
  | { status: "read"; drift: EngineDrift };

export function engineDriftState(query: {
  data: PlatformState | undefined;
  error: unknown;
  isLoading: boolean;
}): EngineDriftState {
  if (query.error) return { status: "unreadable" };
  if (query.isLoading || !query.data) return { status: "loading" };
  // A PLATFORM READ THAT CARRIES NO `engine_drift` IS UNREADABLE, not empty. The field is
  // required on the wire, so this cannot happen against a current server — it happens
  // against an OLDER one, and mid-deploy is exactly when someone is on this screen. The
  // narrowing has to be defended at runtime because `read !== null` is TRUE for
  // `undefined`, which is not a type error and is a blank ops console (axe's screen scan
  // found it, by rendering the page with a bare payload).
  //
  // This is NOT the `?? 0` trap it superficially resembles: nothing here invents a count.
  // "The server did not send it" and "we could not read it" are the same fact to an
  // operator, and the panel says so instead of reporting an all-clear it never received.
  const drift: EngineDrift | undefined = query.data.engine_drift;
  if (!drift) return { status: "unreadable" };
  return { status: "read", drift };
}

/**
 * The knowledge-drift summary as this screen may know it. Three states and never a fourth,
 * `EngineDriftState`'s reason: "no agent's knowledge has drifted" and "we could not find
 * out whether any has" are OPPOSITE facts, and a `KbDrift | undefined` collapses them at
 * the first `??`.
 */
export type KbDriftState =
  | { status: "loading" }
  | { status: "unreadable" }
  | { status: "read"; drift: KbDrift };

export function kbDriftState(query: {
  data: PlatformState | undefined;
  error: unknown;
  isLoading: boolean;
}): KbDriftState {
  if (query.error) return { status: "unreadable" };
  if (query.isLoading || !query.data) return { status: "loading" };
  // Defended at runtime for `engineDriftState`'s reason: the field is required on the
  // wire, so this cannot happen against a current server — it happens against an OLDER
  // one, and mid-deploy is exactly when someone is on this screen. `read !== null` is TRUE
  // for `undefined`, which is not a type error and is a blank panel.
  const drift: KbDrift | undefined = query.data.kb_drift;
  if (!drift) return { status: "unreadable" };
  return { status: "read", drift };
}
