"use client";

/**
 * Restore-on-mount, as a React hook (D-174, §5.4).
 *
 * The state machine is small and every transition in it is a decision §5.4 argues for:
 *
 * ```
 *              ┌── ok ─────────────────► ready
 *  restoring ──┼── partial ────────────► partial      (alive, one door short)
 *              ├── signed_out ─────────► signed-out   (HARD: blocks, clears)
 *              └── timeout|unreachable ► unreachable  (SOFT: retries on remount)
 * ```
 *
 * ## The hook takes its realm as an argument, and that is not realm sharing
 *
 * `useRealmSession(adminAuthn, "session")` and `useRealmSession(clientAuthn, "session")`
 * are two calls with two literal instances, made from two provider files that never
 * import each other. There is no branch on `realm` anywhere below — the same argument
 * `lib/authn/realm.ts` and `apps/api/authn/routes.py::_realm_router` both make, and the
 * same one CLAUDE.md's "never share session logic" is aimed at: what must be impossible
 * is a runtime path that carries a caller between realms, not a function written once.
 * `tests/authnRealmSeparation.test.ts` pins that each provider names exactly one instance.
 *
 * ## The generation counter
 *
 * A restore that started before a sign-in must not be able to resolve after it and
 * overwrite the fresh session with its stale answer — including with `signed_out`, which
 * would log out a user who has just successfully logged in. `authn.generation()` is
 * captured before the await and compared after it; a mismatch drops the result on the
 * floor. §5.4 calls this "the kind of thing nobody writes until it bites", which is the
 * reason it is written here before it has.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { AuthnSession, RealmAuthn, RestoreAudience } from "./realm";

export type RealmSessionStatus =
  /** The restore is in flight. A gate shows its waiting state; it does NOT show a shell. */
  | "restoring"
  /** A live, fully authenticated session. */
  | "ready"
  /** Password proved, emailed code not yet answered. Alive, and one route wide. */
  | "partial"
  /** The server said this session is not valid. The one state that clears. */
  | "signed-out"
  /** We could not find out. Soft: nothing cleared, nothing blocked, retry is offered. */
  | "unreachable";

export interface RealmSessionState {
  status: RealmSessionStatus;
  /** The server's answer, or `null`. Never derived from anything this browser decoded. */
  session: AuthnSession | null;
  /** Run the restore again — the remedy offered for `unreachable`. */
  retry: () => void;
  /** Adopt a session this tab just obtained (sign-in, second factor), without a round trip. */
  adopt: (session: AuthnSession) => void;
}

export function useRealmSession(
  authn: RealmAuthn,
  audience: RestoreAudience,
): RealmSessionState {
  const [status, setStatus] = useState<RealmSessionStatus>("restoring");
  const [session, setSession] = useState<AuthnSession | null>(null);
  /** Bumped by `retry()` to re-run the effect without touching the realm's generation. */
  const [attempt, setAttempt] = useState(0);
  /**
   * Set by `adopt`, so the effect below cannot start a restore that would race a session
   * this tab already holds. A ref rather than state because the effect must see the new
   * value on the SAME render that set it, and because changing it must not itself cause
   * a re-render.
   */
  const adopted = useRef(false);

  const adopt = useCallback((next: AuthnSession) => {
    adopted.current = true;
    setSession(next);
    setStatus("ready");
  }, []);

  const retry = useCallback(() => {
    adopted.current = false;
    setAttempt((n) => n + 1);
  }, []);

  useEffect(() => {
    if (adopted.current) return;

    // A HARD failure already recorded for this audience: do not ask again. The guest
    // audience has its own flag, which is what stops a dead console session from
    // disabling the sign-in page that exists to fix it (§5.4).
    if (authn.isBlocked(audience)) {
      setStatus("signed-out");
      setSession(null);
      return;
    }

    setStatus("restoring");
    const generationAtStart = authn.generation();
    /** Guards against a resolve landing after this component unmounted. */
    let live = true;

    void authn.restore(audience).then((outcome) => {
      if (!live) return;
      // §5.4's generation check. A sign-in, a second factor or a sign-out bumped the
      // generation while this was in flight, so its answer describes a session that no
      // longer exists. Dropping it is the whole point: `signed_out` from a stale restore
      // would eject a user who is, at this instant, signed in.
      if (generationAtStart !== authn.generation()) return;

      if (outcome.ok) {
        setSession(outcome.session);
        setStatus("ready");
        return;
      }
      if (outcome.reason === "partial") {
        setSession(null);
        setStatus("partial");
        return;
      }
      if (outcome.reason === "signed_out") {
        setSession(null);
        setStatus("signed-out");
        return;
      }
      // SOFT. Nothing is cleared and nothing is blocked — see `RestoreOutcome`. The
      // session, if there is one, is still whatever the cookie says it is; all this tab
      // knows is that it could not find out.
      setStatus("unreachable");
    });

    return () => {
      live = false;
    };
  }, [authn, audience, attempt]);

  return { status, session, retry, adopt };
}
