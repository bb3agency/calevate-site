/**
 * WHICH credential this build presents — decided by configuration once, never inferred
 * from what happens to work.
 *
 * This module survived the removal of Clerk (D-177) and only its enum changed: `clerk`
 * became `session`, because the non-local credential is now the first-party `__Host-`
 * cookie the browser attaches itself rather than a vendor token this code fetches. What
 * did NOT change is the argument, which is the whole reason the file exists:
 *
 * ## Two independent guards, and why one is not enough
 *
 * The dev credential is `dev:<realm>:<subject-uuid>`, which the API accepts only when
 * `APP_ENV=local` AND the deployment holds no `PLATFORM_KEK` (`core/auth.py`). Shipping a
 * browser that presents one is therefore not itself an authentication bypass — but it is
 * the half a bypass needs, and the two halves are configured by different people on
 * different days. So this file refuses `dev` in a production build outright, and
 * `lib/api/client.ts::devToken` refuses it AGAIN at the moment the credential would reach
 * `fetch`. The first guard catches a misconfigured deployment; the second catches a
 * refactor that reached the dev builder by a path that skipped the mode.
 *
 * ## Why an unset variable is `session` in a production build
 *
 * Because the safe reading of a forgotten variable is the one that cannot authenticate
 * anybody by itself. `session` presents no credential this code can construct: it relies
 * on a cookie that only a completed sign-in can produce.
 *
 * It lives in `lib/authn/` rather than the deleted `lib/auth/` because the thing it now
 * decides is which of THIS package's two credentials a build speaks.
 */

export class AuthConfigError extends Error {}

export type AuthMode = "session" | "dev";

/** The variable, named once so the error messages and the parity guard cannot drift. */
export const AUTH_MODE_ENV = "NEXT_PUBLIC_AUTH_MODE";

export function resolveAuthMode(raw: string | undefined, isProductionBuild: boolean): AuthMode {
  const value = (raw ?? "").trim().toLowerCase();

  if (value === "session") return "session";

  if (value === "dev") {
    if (isProductionBuild) {
      throw new AuthConfigError(
        `${AUTH_MODE_ENV}=dev in a production build. The dev credential is ` +
          "`dev:<realm>:<subject-uuid>`, which the API accepts only when APP_ENV=local " +
          "and the deployment has no PLATFORM_KEK — shipping it would be half of an " +
          `authentication bypass. Set ${AUTH_MODE_ENV}=session, or build with ` +
          "NODE_ENV=development for local work.",
      );
    }
    return "dev";
  }

  if (value === "") {
    // Unset. Locally that is the ordinary state and dev tokens are what a developer
    // wants; in a production build it is a forgotten variable, and the safe reading of
    // a forgotten variable is the one that cannot authenticate anybody by itself.
    return isProductionBuild ? "session" : "dev";
  }

  throw new AuthConfigError(
    `${AUTH_MODE_ENV}=${JSON.stringify(value)} is not a mode. Use "session" (the ` +
      'first-party session cookie) or "dev" (local `dev:<realm>:<subject-uuid>` tokens, ' +
      "refused in a production build).",
  );
}

/**
 * True when this bundle was produced by `next build` / served by `next start`.
 *
 * Read through a `const` so the two call sites cannot drift, and written as a literal
 * `process.env.NODE_ENV` comparison because that is the form Next's compiler inlines.
 */
export const IS_PRODUCTION_BUILD = process.env.NODE_ENV === "production";

/** This deployment's answer. Computed once, at module load, so a misconfiguration
 * surfaces at build time rather than on the first request a user makes. */
export const AUTH_MODE: AuthMode = resolveAuthMode(
  process.env.NEXT_PUBLIC_AUTH_MODE,
  IS_PRODUCTION_BUILD,
);
