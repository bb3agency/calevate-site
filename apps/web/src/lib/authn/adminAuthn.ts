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

import { createRealmAuthn, type AuthnSession } from "./realm";

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

/* --- Step-up: re-proving a factor without leaving the screen (D-178, D-210) --------
 *
 * `POST /v1/auth/admin/step-up` and `.../step-up/verify` are declared on the ADMIN
 * router only (`apps/api/authn/routes.py`: the client realm requires no second factor,
 * so a client-realm step-up would be a route with nothing to re-prove and nobody to call
 * it). The browser half mirrors that structurally by living here and having no
 * client-realm spelling — the same choice `confirmAdminBootstrap` above makes.
 *
 * Both go through `adminAuthn.request`, so both wait on the rotation barrier, and that is
 * not a detail: answering a step-up code ROTATES the session server-side
 * (`service.complete_step_up`), and a concurrent request still carrying the retired token
 * is read as replay and revokes the whole family (RFC 9700 §4.14.2 — `realm.ts`).
 */

/** Email this operator a `step_up`-purpose code. Issuing one retires the previous. */
export async function requestAdminStepUp(): Promise<void> {
  await adminAuthn.request<void>("/step-up", { method: "POST" });
}

/**
 * Answer the code, restamping `mfa_verified_at` on this session.
 *
 * `reset()` FIRST, exactly as `submitSecondFactor` does and for the same reason: the
 * route rotates, so no cached rotation result may answer for the session it replaced, and
 * no restore already in flight may resolve into it.
 */
export async function confirmAdminStepUp(code: string): Promise<AuthnSession> {
  adminAuthn.reset();
  return await adminAuthn.request<AuthnSession>("/step-up/verify", {
    method: "POST",
    body: { code },
  });
}
