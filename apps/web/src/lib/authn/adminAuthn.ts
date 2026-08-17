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
