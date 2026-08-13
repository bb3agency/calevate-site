/**
 * WHICH credential this build presents to the API — decided by configuration, once.
 *
 * The API accepts two kinds of bearer token (`apps/api/core/auth.py`):
 *
 *  - a real Clerk session JWT, verified against the realm's own JWKS, and
 *  - `dev:<realm>:<clerk_user_id>`, which `_verify_dev_token` accepts ONLY when
 *    `APP_ENV=local` AND that realm has no Clerk secret configured.
 *
 * The browser has to choose. It cannot ask the server which one it will accept — there
 * is no such endpoint, and a probe would be one more thing to be down — so the choice is
 * configuration, stated by the deployment, never inferred from what happens to work.
 *
 * ## The failure mode this file exists to make impossible
 *
 * A build that means to use Clerk but cannot get a token MUST fail loudly. If it fell
 * back to `dev:client:<anything>` instead, then any deployment that also set
 * `APP_ENV=local` on the API — the DEFAULT of `Settings.app_env`, as `core/auth.py`'s
 * own docstring warns — would authenticate a stranger as any user id they cared to type.
 * That is not a login bug; hard rule 1 keys RLS off the tenant resolved from that
 * identity, so it is a cross-tenant read of other businesses' customer data.
 *
 * So the dev path is guarded twice, on purpose, by two independent facts:
 *
 *  1. **`resolveAuthMode` never returns `"dev"` in a production build.** An explicit
 *     `NEXT_PUBLIC_AUTH_MODE=dev` there throws at module initialisation — which happens
 *     during `next build`, so the mistake is a failed build rather than a live bypass.
 *     An UNSET variable resolves to `"clerk"` in a production build: forgetting the
 *     variable is the likeliest mistake there is, and it must fail towards the strict
 *     answer.
 *  2. **`devToken()` (lib/api/client.ts) re-checks the same fact at call time** and
 *     refuses regardless of how it was reached. Guard 1 is about configuration; guard 2
 *     is about the credential itself, so a future refactor that mis-wires the first
 *     cannot silently re-open the path.
 *
 * `NODE_ENV` is the production signal because Next sets it and it cannot be forgotten:
 * `next build`/`next start` are `production`, `next dev` is `development`, Vitest is
 * `test`. A deployment cannot ship a production bundle with `NODE_ENV` accidentally
 * unset the way it can forget a bespoke variable.
 *
 * ## Why an unknown value is refused rather than defaulted
 *
 * `NEXT_PUBLIC_AUTH_MODE=production` or `=true` is somebody's reasonable guess at the
 * name. Reading it as either mode would be guessing back; one of the two guesses is an
 * auth bypass. It throws instead, naming the two legal values.
 */

/** The two credentials the API will accept, named from the browser's side. */
export type AuthMode = "clerk" | "dev";

/** Spelled once so the error messages, the docs and the reader agree. */
export const AUTH_MODE_ENV = "NEXT_PUBLIC_AUTH_MODE";

/**
 * A deployment whose auth configuration cannot be honoured.
 *
 * Deliberately NOT an `ApiProblem`: nothing was asked of the API and nothing refused.
 * This is thrown at module initialisation, where the only reader is the build log or a
 * developer's console, so it wants a sentence an operator can act on and no HTTP dress.
 */
export class AuthConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthConfigError";
  }
}

/**
 * The decision, as a pure function so it can be tested at every combination.
 *
 * @param raw - the value of `NEXT_PUBLIC_AUTH_MODE`, exactly as configured.
 * @param isProductionBuild - `process.env.NODE_ENV === "production"`.
 */
export function resolveAuthMode(raw: string | undefined, isProductionBuild: boolean): AuthMode {
  const value = (raw ?? "").trim();

  if (value === "clerk") return "clerk";

  if (value === "dev") {
    if (isProductionBuild) {
      throw new AuthConfigError(
        `${AUTH_MODE_ENV}=dev in a production build. The dev credential is ` +
          "`dev:<realm>:<user-id>`, which the API accepts only when APP_ENV=local and " +
          "that realm has no Clerk secret — shipping it would let anyone sign in as " +
          `anyone. Set ${AUTH_MODE_ENV}=clerk and configure the realms' publishable ` +
          "keys, or build with NODE_ENV=development for local work.",
      );
    }
    return "dev";
  }

  if (value === "") {
    // Unset. Locally that is the ordinary state and dev tokens are what a developer
    // wants; in a production build it is a forgotten variable, and the safe reading of
    // a forgotten variable is the one that cannot authenticate anybody by itself.
    return isProductionBuild ? "clerk" : "dev";
  }

  throw new AuthConfigError(
    `${AUTH_MODE_ENV}=${JSON.stringify(value)} is not a mode. Use "clerk" (real Clerk ` +
      'sessions) or "dev" (local `dev:<realm>:<id>` tokens, refused in a production build).',
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
