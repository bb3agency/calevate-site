/**
 * The ADMIN realm's session — `admin.calevate.tech`, operators only (D-174).
 *
 * A file of its own, holding its own instance, because CLAUDE.md forbids the two realms
 * sharing session logic and AUTH-MIGRATION §3 says what that forbids in practice: no
 * runtime path may carry a caller from one realm to the other. `createRealmAuthn("admin")`
 * is evaluated once, here, with a literal — see `realm.ts` for why a factory whose realm
 * is a closure constant is the same thing as writing the file twice, and why the server's
 * `_realm_router` makes the identical argument on its side.
 *
 * The admin extras live here rather than in the factory, structurally rather than by
 * convention: `POST /v1/auth/admin/bootstrap/confirm` is **not declared on the client
 * realm's router at all** (`routes.py`: "a client-realm `/bootstrap/confirm` would be a
 * 404, which is the correct answer for a route that should not exist there"), so the
 * browser half mirrors that by having no client-realm spelling of it either.
 */

import { createRealmAuthn } from "./realm";

/** The admin realm's session. One instance, module-scoped, never re-created. */
export const adminAuthn = createRealmAuthn("admin");

/** Where an operator signs in. Spelled once so no screen invents a second URL. */
export const ADMIN_SIGN_IN_PATH = "/auth/admin/sign-in";
export const ADMIN_SESSION_PATH = "/auth/admin";
export const ADMIN_FORGOT_PATH = "/auth/admin/forgot-password";
export const ADMIN_RESET_PATH = "/auth/admin/reset-password";
export const ADMIN_BOOTSTRAP_PATH = "/auth/admin/bootstrap";

/**
 * Redeem a first-administrator setup link (D-171).
 *
 * Unauthenticated by necessity — it is how a deployment acquires its first operator, and
 * there is nobody to authenticate as until it succeeds. The token is what stands in for a
 * session: 256 bits, single-use, one hour, and refused outright once the named account has
 * a password, so a leaked link from a finished deploy opens nothing.
 */
export async function confirmAdminBootstrap(input: {
  token: string;
  password: string;
}): Promise<void> {
  await adminAuthn.request<void>("/bootstrap/confirm", { method: "POST", body: input });
}

/**
 * Ask for a step-up code to be emailed to this operator (D-178, D-340).
 *
 * ADMIN REALM ONLY, mirroring the server structurally rather than by refusing at runtime:
 * `authn/routes.py` declares `/step-up` inside `if realm == stepup.STEP_UP_REALM`, so a
 * client-realm spelling would be a 404 — the same argument `/bootstrap/confirm` above
 * makes, and the reason both live in this file instead of in the realm factory.
 *
 * No arguments and no address: the live session IS the subject (`service.request_step_up`),
 * so there is nothing to probe and no way to make us mail a stranger.
 */
export async function requestStepUp(): Promise<void> {
  await adminAuthn.request<void>("/step-up", { method: "POST" });
}

/**
 * Answer the emailed step-up code, restamping this session's second factor.
 *
 * **THIS ROTATES THE SESSION.** `service.complete_step_up` treats re-proving a factor as a
 * privilege change and mints a new identifier for it, which makes `realm.ts`'s ordering
 * discipline load-bearing here for exactly the reason it is in `submitSecondFactor`:
 * `reset()` FIRST, so no cached rotation result can answer for the session about to be
 * superseded and no restore already in flight can resolve into it. Without that, a request
 * still carrying the retired cookie is `reuse_detected` and the whole family is revoked —
 * an operator who typed the RIGHT code signed out of everything.
 *
 * `adminAuthn.request` also puts the POST behind the rotation barrier, which is the other
 * half: nothing else on this realm dispatches while the new cookie is being minted.
 *
 * The response body (`SessionOut`) is deliberately dropped. The session state this console
 * renders comes from `AdminSessionProvider`'s own restore, and returning a second copy of
 * it here would be two answers to "who am I" that can disagree.
 */
export async function verifyStepUp(code: string): Promise<void> {
  adminAuthn.reset();
  await adminAuthn.request<unknown>("/step-up/verify", { method: "POST", body: { code } });
}
