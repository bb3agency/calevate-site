import type { NextConfig } from "next";

/**
 * The build-time refusal for the browser tier's configuration.
 *
 * `next build` INLINES every `NEXT_PUBLIC_*` at build time, and a key that is absent
 * compiles to the empty string rather than throwing (`apps/web/.env.example` opens with
 * that sentence). So a deploy whose `apps/web/.env.local` was never placed produces a
 * bundle that builds green, passes the deploy's `/` health poll — the landing page
 * answers 200 with no configuration at all — and is unusable:
 *
 *   - `NEXT_PUBLIC_API_BASE_URL` empty → the reader's `?? "http://localhost:8000"` does
 *     NOT fire (`??` falls back on undefined, not on ""), so every browser at
 *     app.calevate.tech calls a relative path that 404s against the Next server;
 * THE SECOND ENTRY USED TO BE THE TWO CLERK PUBLISHABLE KEYS, and D-177 deleted them:
 * authentication configures NOTHING in the browser now, because the credential is a cookie
 * the server sets. That removes the circularity this file was mostly written about — you
 * no longer need a key baked into the bundle in order to reach the ops screen where the
 * other fifty are set — and it leaves this gate with one key. One is enough for it to
 * still be worth having: an empty API base is the failure that builds green, health-polls
 * green and serves an unusable app.
 *
 * WHY HERE AND NOT AT MODULE INIT, where `lib/authn/mode.ts` throws for
 * `NEXT_PUBLIC_AUTH_MODE=dev`. That throw only fires if the module is evaluated during
 * the build, which depends on which routes Next chooses to prerender — a guarantee that
 * changes with a `dynamic` export somebody adds later. `next.config.ts` is evaluated by
 * `next build` unconditionally, once, before any of that. It also never reaches the
 * bundle, so the flag below costs the browser nothing.
 *
 * WHY A STATED FLAG rather than "always require these". CI runs `pnpm -C apps/web build`
 * as a COMPILE check with no environment at all, and that is a legitimate build — it is
 * asking whether the routes and the bundle are valid, not whether this host is
 * configured. Inferring the difference from what happens to be set is exactly the
 * mistake `Settings.app_env` used to make (D-49: a deployment that does not say which
 * environment it is in was treated as `local`, where the API accepts a dev token whose
 * subject the caller picks). So the deploy STATES it: `scripts/vps-deploy.sh` exports
 * `CALEVATE_DEPLOY_BUILD=1` and nothing else does.
 */
const DEPLOY_BUILD = process.env.CALEVATE_DEPLOY_BUILD === "1";

/** Every key whose empty value ships a broken screen, with what breaks. */
const REQUIRED_IN_A_DEPLOY_BUILD: Record<string, string> = {
  NEXT_PUBLIC_API_BASE_URL:
    "every request would go to a relative path and 404 against the Next server " +
    "(the reader's ?? default fires on undefined, never on an empty string)",
  // Added after the bug it describes reached the live console. `viewAsHref()` falls back
  // to a bare `/c/<slug>` path when this is empty, which is right for a single-origin
  // development box and WRONG for this deployment: `admin.` and `app.` are separate
  // hostnames and each 404s the other's tree (D-177/P7.3), so every operator opening
  // "View as" landed on a not-found screen. A deploy build is by definition the
  // multi-hostname case, and an empty value there is not a default — it is the defect.
  NEXT_PUBLIC_CLIENT_CONSOLE_ORIGIN:
    "every \"View as\" link would be built as a bare /c/<slug> path and 404 against the " +
    "admin hostname, which refuses the client tree by design",
  // The mirror, added after the mirror bug reached the live console: "Exit and return to
  // the admin console" is rendered on `app.`, and the operator auth screens are served on
  // the apex, and BOTH hostnames answer 404 for `/admin`. A bare path is right only on
  // `admin.` itself, which is the one hostname those two screens are never on.
  NEXT_PUBLIC_ADMIN_CONSOLE_ORIGIN:
    "leaving a view-as session and signing in as an operator would both build a bare " +
    "/admin path and 404 against the client and apex hostnames, which refuse the " +
    "operator tree by design",
};

if (DEPLOY_BUILD) {
  const missing = Object.entries(REQUIRED_IN_A_DEPLOY_BUILD)
    .filter(([name]) => !(process.env[name] ?? "").trim())
    .map(([name, consequence]) => `  ${name} — ${consequence}`);
  if (missing.length > 0) {
    throw new Error(
      "This is a deploy build (CALEVATE_DEPLOY_BUILD=1) and the browser tier is not " +
        "configured. Next inlines NEXT_PUBLIC_* at BUILD time from apps/web/.env.local, " +
        "so these would ship as empty strings and the build would still succeed:\n" +
        missing.join("\n") +
        "\n\nPlace apps/web/.env.local from the secrets manager (see " +
        "apps/web/.env.example) and rebuild. DEPLOYMENT §6 tier 1.",
    );
  }
}

const nextConfig: NextConfig = {
  /* config options here */
};

export default nextConfig;
