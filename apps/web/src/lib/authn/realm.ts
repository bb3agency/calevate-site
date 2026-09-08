/**
 * One realm's whole session machinery: single-flight rotation, and restore-on-mount.
 *
 * D-174. Built against `docs/evidence/raghava-platform-teardown.md` §5.2 and §5.4, and
 * against the contract in `apps/api/authn/routes.py`.
 *
 * ═══ ONE FACTORY, TWO REALMS, AND WHY THAT IS NOT WHAT §3 WARNS ABOUT ═══
 *
 * CLAUDE.md is emphatic that the two realms "must never share session logic", and
 * AUTH-MIGRATION §3 says why: "a `realm` parameter on one shared module is one bad
 * conditional away from presenting an admin credential on a client surface".
 *
 * `createRealmAuthn(realm)` has no such conditional. It is the same argument
 * `apps/api/authn/routes.py::_realm_router` makes for the server half, and it holds for
 * the same reason: the realm is a **closure constant** fixed when the module is
 * constructed at import, it appears in every path as a literal, and there is no
 * request-time input — no argument, no context value, no route param — that can move a
 * call from one realm to the other. What comes out is two objects with two independent
 * caches, two independent restore runtimes and two independent generation counters: the
 * same end state as writing the file twice, minus the copy that would drift.
 *
 * The two are constructed in `adminAuthn.ts` and `clientAuthn.ts`, once each, and nothing
 * else may call this factory. `tests/authnSourceGuards.test.ts` asserts both halves of
 * that: that the two instances share no state, and that no other module imports the
 * factory.
 *
 * ═══ WHY ROTATION IS THE DANGEROUS OPERATION HERE ═══
 *
 * §5.2 describes the reference implementation's live bug — "randomly logged out
 * mid-session on desktop" — caused by two concurrent refreshes sending the same
 * single-use cookie, the first rotating it and the second being told it was consumed.
 *
 * **Ours is worse, and the mitigation therefore has to be stronger.** `POST
 * /v1/auth/{realm}/session/refresh` calls `sessions.rotate_session`, which supersedes the
 * old row under a CAS and mints a new one in the same family. Presenting the superseded
 * token afterwards is not a stale request to that backend, it is theft: `verify_session`
 * revokes the ENTIRE FAMILY with `reuse_detected` (RFC 9700 §4.14.2). And
 * `apps/api/authn/sessions.py` records that this is deliberately done **without a
 * concurrency grace window**, on the stated premise that rotation happens on privilege
 * change only and is "never a burst of background fetches".
 *
 * That premise is a requirement on this file. Two things enforce it:
 *
 *  1. **The single-flight plus result cache** (§5.2), so concurrent callers — including a
 *     React Strict Mode double-mount, which is the ordinary case in development — collapse
 *     into one rotation.
 *  2. **A rotation barrier**, which the reference does not have and which our missing
 *     grace window makes necessary. While a rotation is in flight, every other call to
 *     this realm waits for it before dispatching, so no request can be carrying the old
 *     cookie at the moment the new one is minted. Without it the hazard is not a failed
 *     request; it is the victim's entire session family revoked as a replay.
 *
 * FOUR routes rotate this realm's cookie, not one, and every one of them has to HOLD the
 * barrier rather than merely wait on it. Read off the service (7 Sep 2026):
 *
 *   * `POST /session/refresh` — `sessions.rotate_session` (§5.2's own case).
 *   * `POST /login/otp` — `service.complete_second_factor`: "Rotates the session on
 *     success", because completing a second factor is a privilege change and OWASP's
 *     session-fixation defence asks for a new identifier at that moment.
 *   * `POST /step-up/verify` — `service.complete_step_up`, rotating for the same reason.
 *   * `POST /password/change` — `service.change_password` rotates the caller's session and
 *     then revokes every other one, the superseded row INCLUDED.
 *
 * All four go out through `underRotation` (the last two via `rotatingRequest`, which is
 * how the two realm modules reach it for their own routes). `rotationInFlight` is the one
 * flag the barrier reads: a route that kept its own would be a second barrier, i.e. none,
 * and a route that only WAITS on the barrier is protected FROM a rotation without
 * protecting anything from its own — which is the half-measure this paragraph replaced.
 */

import type { components } from "../api/schema";
import { authnRequest, type AuthnRequestOptions } from "./transport";
import { isSessionGone, needsSecondFactor } from "./problems";

/** The two realms, spelled once. Never a variable at a call site — always a literal. */
export type AuthnRealm = "admin" | "client";

/** `SessionOut` — deliberately ids and state, with NO email address (routes.py). */
export interface AuthnSession {
  realm: string;
  subject_id: string;
  mfa_complete: boolean;
  email_verified: boolean;
}

/** `PasswordChangeOut` — how many OTHER sessions the change ended. */
type PasswordChangeOut = components["schemas"]["PasswordChangeOut"];

/** `LoginOut`. There is no third value: the second factor is the emailed code (D-170). */
export type SignInStatus = "authenticated" | "otp_required";

/**
 * Who is asking for a restore, within one realm.
 *
 * `"session"` is the protected console; `"guest"` is that realm's sign-in and reset pages.
 * The split is §5.4's, and the reason is precise: without it a failed restore on the
 * console leaves the SIGN-IN page permanently convinced restore is impossible, because
 * they share one `blocked` flag — so the one screen whose whole job is to fix a dead
 * session is the screen the dead session disables.
 *
 * Two audiences per realm rather than the reference's three overall, because that is what
 * §5.4's "ours is three-way in a different sense: admin realm, client realm, and the guest
 * pages of each" actually asks for: four runtimes, kept apart by realm first.
 */
export type RestoreAudience = "session" | "guest";

/**
 * The outcome of a restore, split by what a caller is entitled to DO about it.
 *
 * The split is §5.4's central lesson and the one this port must not collapse. `signed_out`
 * is the only hard failure: the server said this session is not valid, so clearing local
 * state is a fact rather than a guess. `timeout` and `unreachable` are SOFT — the session
 * may be perfectly good and the network merely slow, so nothing is cleared and nothing is
 * blocked, and a remount or a navigation retries. Collapsing the two is how a valid
 * session on a weak mobile link gets thrown away, which is the "works on desktop, drops on
 * mobile" report the reference's deadline comment records.
 *
 * `partial` is ours and has no analogue there: an admin session that has proved a password
 * but not the emailed code is ALIVE and can reach exactly one route. `GET /session`
 * refuses it with `second_factor_required`, which is neither a dead session nor a slow
 * one — it is a navigation to the code entry step.
 */
export type RestoreOutcome =
  | { ok: true; session: AuthnSession }
  | { ok: false; reason: "signed_out" | "partial" | "timeout" | "unreachable" };

/** Soft failures leave the session alone and stay retryable. See `RestoreOutcome`. */
export function isSoftRestoreFailure(outcome: RestoreOutcome): boolean {
  return !outcome.ok && (outcome.reason === "timeout" || outcome.reason === "unreachable");
}

/**
 * How long a restore may take before the UI stops waiting on it. §5.4's number, kept.
 *
 * The reference shipped 8 seconds first and its comment records what that cost: it
 * "spuriously logged out valid sessions on 3G/weak links (the request eventually
 * succeeds, but the race already resolved)". 15 seconds is the number they arrived at
 * after that, and the evidence for it is the kind this repo would otherwise have to buy
 * again from its own users.
 *
 * The reason a generous number is cheap here is that the deadline only ever bites a
 * SLOW-BUT-WORKING connection. A genuinely dead one — no DNS, no route, TLS refused —
 * rejects the `fetch` in well under a second and takes the `unreachable` path, which is
 * soft too. So the deadline is not the failure detector; it is the bound on how long a
 * gate may show a spinner. And because timing out is soft, being wrong about it costs a
 * retry rather than a session.
 */
export const RESTORE_DEADLINE_MS = 15_000;

/**
 * How long a completed rotation answers for its callers without rotating again. §5.2's 3s.
 *
 * The in-flight promise alone is not enough, and the gap it leaves is small and real: a
 * rotation RESOLVES, its promise is cleared, and a component that mounted a millisecond
 * later asks for another. React Strict Mode's development double-mount does exactly this
 * on every page load. With no grace window on the server (see the module docstring) a
 * second rotation is not merely wasteful — it is a second supersede, and any request still
 * carrying the token the first one retired revokes the family.
 *
 * Three seconds is chosen against what it has to cover and what it could hide. It has to
 * cover a Strict Mode remount and a burst of guards mounting through one navigation, both
 * of which are milliseconds; a value in the tens of milliseconds would cover them on a
 * fast machine and not on a cheap Android, which is the phone this console is used on. It
 * could hide a session that died within three seconds of a successful rotation — and the
 * shortest bound that could do that is the admin realm's 30-minute idle timeout
 * (`REALM_TIMEOUTS`, `apps/api/authn/sessions.py`), six hundred times longer. The margin
 * either way is three orders of magnitude, which is why the exact number does not need to
 * be defended more finely than "the same one the reference measured".
 */
export const ROTATION_RESULT_CACHE_MS = 3_000;

/**
 * How many times a caller will re-check the barrier before giving up on ordering.
 *
 * The barrier waits for an in-flight rotation, and a new rotation can begin while it
 * waits. A `while (inFlight)` loop is therefore the natural spelling and is also
 * unbounded, which is a hang wearing a correctness argument. Rotations are user-initiated
 * and single-flighted, so two consecutive ones are already unusual and three are a bug
 * somewhere else; after this many turns the request goes out rather than waiting forever,
 * which is the right failure — an ordering risk beats a frozen console.
 */
const BARRIER_MAX_TURNS = 3;

interface RestoreRuntime {
  /** Set only by a HARD failure. A soft one must leave this false — see `RestoreOutcome`. */
  blocked: boolean;
  inFlight: Promise<RestoreOutcome> | null;
}

export interface RealmAuthn {
  readonly realm: AuthnRealm;

  /** `POST /login`. Sets the cookie either way; `otp_required` means one door is open. */
  signIn(input: { email: string; password: string }): Promise<SignInStatus>;
  /** `POST /login/otp`. Rotates the session, so it goes through the barrier. */
  submitSecondFactor(code: string): Promise<AuthnSession>;
  /** `POST /login/otp/resend`. A new code retires the previous one. */
  resendSecondFactor(): Promise<void>;

  /**
   * `GET /session` — the bootstrap read. Does not rotate.
   *
   * The optional `signal` is what lets `restore`'s deadline CANCEL this read rather than
   * abandon it; see `runRestoreWithDeadline`.
   */
  readSession(signal?: AbortSignal): Promise<AuthnSession>;
  /** `POST /session/refresh`, single-flighted and cached. The ONLY refresh caller. */
  rotateSession(): Promise<AuthnSession>;

  /**
   * `POST /password/change` — the signed-in change. Answers how many OTHER sessions died.
   *
   * IT ROTATES, so it goes out UNDER THE ROTATION BARRIER exactly as `session/refresh`
   * does, and that is not a nicety. `service.change_password` rotates the caller's own
   * session and then revokes every other one INCLUDING the superseded row, so the moment
   * the response lands the cookie every other in-flight request is carrying is retired —
   * and `verify_session` reads a retired token as replay and revokes the whole family
   * (RFC 9700 §4.14.2). The failure that produces is the worst kind to debug: the person
   * who just changed their password is signed out, sometimes, depending on whether a
   * background query happened to be in the air.
   *
   * There is no result cache for it, unlike `rotateSession`: a second change is a second
   * deliberate act by a person, never a remount, and answering it from a cache would
   * report a revocation count that did not happen.
   */
  changePassword(input: {
    currentPassword: string;
    newPassword: string;
  }): Promise<number>;

  signOut(): Promise<number>;
  signOutEverywhere(): Promise<number>;

  requestPasswordReset(email: string, idempotencyKey: string): Promise<void>;
  confirmPasswordReset(
    input: { token: string; password: string },
    idempotencyKey: string,
  ): Promise<void>;

  /** Email verification, scoped to the caller's own subject — there is no address field. */
  requestEmailCode(): Promise<void>;
  verifyEmailCode(code: string): Promise<void>;

  /** §5.4's restore, per audience, deduplicated and deadlined. */
  restore(audience: RestoreAudience): Promise<RestoreOutcome>;
  /** True once a HARD failure has been seen for this audience. */
  isBlocked(audience: RestoreAudience): boolean;
  /**
   * Forget everything cached about this realm and invalidate every in-flight restore.
   *
   * Called on sign-in, on sign-out and on second-factor completion — the three moments
   * when what is cached became false. Bumping the generation is §5.4's counter: a restore
   * that started before a fresh sign-in must not be able to resolve afterwards and clear
   * the session it knows nothing about.
   */
  reset(): void;
  /** The current generation, captured by a caller before it awaits. */
  generation(): number;

  /** Escape hatch for the two realm modules' realm-specific routes. Not for screens. */
  request<T>(path: string, options?: AuthnRequestOptions): Promise<T>;

  /**
   * `request`, for a realm-specific route that ROTATES this realm's cookie.
   *
   * The difference is which side of the barrier the call is on: `request` WAITS for a
   * rotation to finish, this one HOLDS the barrier closed while it runs. A rotating route
   * that used `request` would be protected from everybody else and would protect nobody
   * from itself — the concurrent reader still carrying the retired cookie is read as
   * replay and the whole family is revoked (RFC 9700 §4.14.2).
   *
   * Exists because two of the four rotating routes are declared on the admin router only
   * (`/step-up/verify`) or are already spelled here (`/login/otp`), and neither may reach
   * `underRotation` any other way without each inventing its own flag.
   */
  rotatingRequest<T>(path: string, options?: AuthnRequestOptions): Promise<T>;
}

export function createRealmAuthn(realm: AuthnRealm): RealmAuthn {
  const base = `/v1/auth/${realm}`;

  /**
   * ANY rotating call in flight — the barrier's subject, not just the refresh.
   *
   * `Promise<unknown>` because two different routes rotate this realm's cookie and they
   * answer different bodies (`session/refresh` a session, `password/change` a count).
   * The barrier only ever awaits it for ORDERING and swallows its outcome, so the value
   * type is genuinely irrelevant here — and giving the two rotations two variables would
   * be two barriers, i.e. no barrier.
   */
  let rotationInFlight: Promise<unknown> | null = null;
  /** The refresh's own single-flight. See `rotateSession`. */
  let refreshInFlight: Promise<AuthnSession> | null = null;
  let recentRotation: { session: AuthnSession; expiresAt: number } | null = null;
  let generation = 0;

  const runtimes: Record<RestoreAudience, RestoreRuntime> = {
    session: { blocked: false, inFlight: null },
    guest: { blocked: false, inFlight: null },
  };

  /**
   * Wait for any in-flight rotation before dispatching. See the module docstring.
   *
   * The rotation's FAILURE is swallowed on purpose: a caller waiting here wants the
   * ordering, not the outcome. Letting the rejection through would make an unrelated
   * request report "your rotation failed", which is neither true of it nor actionable.
   */
  async function barrier(): Promise<void> {
    for (let turn = 0; turn < BARRIER_MAX_TURNS && rotationInFlight; turn += 1) {
      try {
        await rotationInFlight;
      } catch {
        // Ordering only — see above.
      }
    }
  }

  async function request<T>(path: string, options: AuthnRequestOptions = {}): Promise<T> {
    await barrier();
    return authnRequest<T>(`${base}${path}`, options);
  }

  function rotatingRequest<T>(path: string, options: AuthnRequestOptions = {}): Promise<T> {
    // NOT `request` — see the interface. `request` would put this call on the WAITING side
    // of the barrier it is itself supposed to be holding.
    return underRotation(() => authnRequest<T>(`${base}${path}`, options));
  }

  const post = <T>(path: string, body?: unknown, idempotencyKey?: string): Promise<T> =>
    request<T>(path, { method: "POST", body, idempotencyKey });

  function reset(): void {
    generation += 1;
    rotationInFlight = null;
    refreshInFlight = null;
    recentRotation = null;
    runtimes.session = { blocked: false, inFlight: null };
    runtimes.guest = { blocked: false, inFlight: null };
  }

  /**
   * Run a call that ROTATES this realm's cookie, with the barrier closed around it.
   *
   * One helper rather than each rotating route arranging its own, because "the barrier"
   * has to mean one thing: a second route that set its own flag would be a second
   * mechanism, and the request waiting on the first would sail past the second. The
   * cleanup is guarded by identity so a `reset()` (or a later rotation) that replaced the
   * flag while this one was in flight is not undone by this one finishing.
   */
  function underRotation<T>(run: () => Promise<T>): Promise<T> {
    // `const` with a self-reference inside its own callback: the callback cannot run
    // before the assignment completes (the promise it is attached to settles later), and
    // a `let` here is what `prefer-const` refuses.
    const held: Promise<T> = run().finally(() => {
      if (rotationInFlight === held) rotationInFlight = null;
    });
    rotationInFlight = held;
    return held;
  }

  /**
   * The refresh's single-flight (§5.2). Every `session/refresh` goes through here, and
   * `underRotation` above is what makes it — and the password change — hold the barrier.
   *
   * Note what is NOT here: no timer touches `rotationInFlight` or `recentRotation`. §5.7
   * defect 1 is a restore deadline whose uncleared `setTimeout` fires later and resets
   * exactly these two fields — nulling an in-flight promise that a DIFFERENT caller is
   * awaiting, so the next caller starts a second rotation and the two send the same
   * superseded cookie. That is the very bug the single-flight exists to prevent,
   * reintroduced by the timeout added to fix a different one. Here the deadline lives
   * entirely inside `runRestoreWithDeadline`, clears itself on every exit path, and has no
   * reference to this state at all.
   */
  function rotateSession(): Promise<AuthnSession> {
    const now = Date.now();
    if (recentRotation && recentRotation.expiresAt > now) {
      return Promise.resolve(recentRotation.session);
    }
    if (!refreshInFlight) {
      refreshInFlight = underRotation(() =>
        authnRequest<AuthnSession>(`${base}/session/refresh`, { method: "POST" }).then(
          (session) => {
            recentRotation = { session, expiresAt: Date.now() + ROTATION_RESULT_CACHE_MS };
            return session;
          },
        ),
      ).finally(() => {
        refreshInFlight = null;
      });
    }
    return refreshInFlight;
  }

  /**
   * One restore attempt, raced against the deadline — with the timer cleared and the
   * LOSER CANCELLED every way out.
   *
   * §5.7 defect 1, stated as code: `clearTimeout` runs in a `finally`, so a restore that
   * WINS the race leaves nothing behind that can fire fifteen seconds later. The reference
   * left the timer running and had it reset the refresh cache when it fired, which is how
   * a completed restore came to be able to break a later, unrelated rotation.
   *
   * `Promise.race` settles on the first outcome and the loser keeps running. This used to
   * say that was "unavoidable and harmless"; it is neither any more, and the second half is
   * why the first changed. `lib/api/client.ts` now puts every request under a deadline of
   * its own, so an abandoned `fetch` is not an inert promise — it holds a `setTimeout` until
   * `REQUEST_TIMEOUT_MS`, which is exactly the class of leftover timer §5.7 defect 1 is
   * about, and `tests/authnSession.test.ts` fails on the count. Aborting the loser settles
   * that request, which clears that timer, and frees a socket nobody is reading. The abort
   * is a no-op when the READ won, because there is nothing left in flight to cancel.
   *
   * It cannot resolve the race the wrong way: the cancelled read is the promise that
   * already lost, `readSessionOutcome` never rejects, and its value is dropped.
   */
  async function runRestoreWithDeadline(): Promise<RestoreOutcome> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const abandoned = new AbortController();
    try {
      return await Promise.race<RestoreOutcome>([
        readSessionOutcome(abandoned.signal),
        new Promise<RestoreOutcome>((resolve) => {
          timer = setTimeout(() => resolve({ ok: false, reason: "timeout" }), RESTORE_DEADLINE_MS);
        }),
      ]);
    } finally {
      clearTimeout(timer);
      abandoned.abort();
    }
  }

  /** `GET /session`, classified. The only place a refusal becomes a restore outcome. */
  async function readSessionOutcome(signal?: AbortSignal): Promise<RestoreOutcome> {
    try {
      return { ok: true, session: await readSession(signal) };
    } catch (error) {
      if (needsSecondFactor(error)) return { ok: false, reason: "partial" };
      if (isSessionGone(error)) return { ok: false, reason: "signed_out" };
      // EVERYTHING ELSE IS SOFT, and the default direction is the whole point. A 429, a
      // 503, a proxy error page, an aborted navigation and a dropped connection are all
      // statements about this REQUEST, not about the session — and the one thing a gate
      // must never do on them is throw away a credential that still works. Only the
      // server saying `unauthorized` is evidence that it does not.
      return { ok: false, reason: "unreachable" };
    }
  }

  function restore(audience: RestoreAudience): Promise<RestoreOutcome> {
    const runtime = runtimes[audience];
    if (!runtime.inFlight) {
      runtime.inFlight = runRestoreWithDeadline()
        .then((outcome) => {
          // A hard failure blocks; a soft one must not. See `RestoreOutcome`.
          if (!outcome.ok && outcome.reason === "signed_out") runtime.blocked = true;
          return outcome;
        })
        .finally(() => {
          runtime.inFlight = null;
        });
    }
    return runtime.inFlight;
  }

  async function readSession(signal?: AbortSignal): Promise<AuthnSession> {
    return await request<AuthnSession>("/session", { signal });
  }

  return {
    realm,

    async signIn({ email, password }) {
      // Everything cached is about to be false — a new cookie is being set either way,
      // including on the `otp_required` branch.
      reset();
      const out = await post<{ status: SignInStatus }>("/login", { email, password });
      return out.status;
    },

    async submitSecondFactor(code) {
      // Rotates. `reset()` FIRST so no stale rotation cache can answer for the new
      // session, and so a restore that is already in flight cannot resolve into it.
      reset();
      // `rotatingRequest`, not `post`: this is one of the four routes that mints a new
      // cookie, so it HOLDS the barrier. It used to only wait on one, which — after the
      // `reset()` directly above cleared the flag — was a wait on nothing.
      return await rotatingRequest<AuthnSession>("/login/otp", {
        method: "POST",
        body: { code },
      });
    },

    async resendSecondFactor() {
      // No body at all. The live session IS the challenge — see `AdminSignInForm` on why
      // the password is not held across this step (§5.7 defect 5).
      await post<void>("/login/otp/resend");
    },

    readSession,
    rotateSession,

    async signOut() {
      try {
        const out = await post<{ revoked: number }>("/logout");
        return out.revoked;
      } finally {
        // Local state is cleared whether or not the server agreed. A logout that failed
        // still means this browser must stop believing it holds a session — the cookie may
        // be gone, the network may be down, and either way continuing to render a signed-in
        // console is the one outcome nobody wants.
        reset();
      }
    },

    async signOutEverywhere() {
      try {
        const out = await post<{ revoked: number }>("/logout/all");
        return out.revoked;
      } finally {
        reset();
      }
    },

    async requestPasswordReset(email, idempotencyKey) {
      await post<void>("/password/reset/request", { email }, idempotencyKey);
    },

    async changePassword({ currentPassword, newPassword }) {
      // `rotatingRequest`, not `post`: this route rotates, so it HOLDS the barrier rather
      // than waiting on it — see the interface for why the two sides are not the same.
      const out = await rotatingRequest<PasswordChangeOut>("/password/change", {
        method: "POST",
        // The API's own field names. Nothing between here and the wire renames them.
        body: { current_password: currentPassword, new_password: newPassword },
      });
      // A NEW cookie is on this response and every other session in this realm is dead, so
      // the cached rotation result — which describes the token that was just superseded —
      // is a lie. Same reason `confirmPasswordReset` resets.
      reset();
      return out.revoked;
    },

    async confirmPasswordReset({ token, password }, idempotencyKey) {
      await post<void>("/password/reset/confirm", { token, password }, idempotencyKey);
      // Confirming revokes every session server-side, so anything cached here is a lie.
      reset();
    },

    async requestEmailCode() {
      await post<void>("/otp/request", { purpose: "email_verify" });
    },

    async verifyEmailCode(code) {
      await post<void>("/otp/verify", { purpose: "email_verify", code });
    },

    restore,
    isBlocked: (audience) => runtimes[audience].blocked,
    reset,
    generation: () => generation,
    request,
    rotatingRequest,
  };
}
