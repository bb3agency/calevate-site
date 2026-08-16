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
 *   - both publishable keys empty → every realm renders "sign-in is not configured",
 *     and `resolveAuthMode` correctly returns "clerk" without throwing, so nothing else
 *     objects.
 *
 * The second one is circular and is why this check has to be at BUILD time rather than
 * on the ops screen: DEPLOYMENT §9 step 10a says the remaining keys are set live from
 * `admin.calevate.tech/ops`, but you cannot reach that screen until the admin realm's
 * publishable key is already baked into the bundle.
 *
 * WHY HERE AND NOT AT MODULE INIT, where `lib/auth/mode.ts` throws for
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
  NEXT_PUBLIC_CLERK_CLIENT_PUBLISHABLE_KEY:
    "app.calevate.tech would render 'sign-in is not configured' for every client",
  NEXT_PUBLIC_CLERK_ADMIN_PUBLISHABLE_KEY:
    "admin.calevate.tech would render 'sign-in is not configured' — and /ops, where " +
    "DEPLOYMENT §9 step 10a sends you to fix the other 50 keys, is behind it",
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
