import { execSync } from "node:child_process";

import type { NextConfig } from "next";

import packageJson from "./package.json";

/**
 * THIS BUILD'S IDENTITY (global rule 8): the version in package.json, the commit it was built
 * from and when. Inlined into the bundle as `NEXT_PUBLIC_APP_*` and served live by
 * `/version.json`, so a page can tell that the server now runs a newer build than the one it
 * loaded. The commit is read from git at build time (the deploy builds inside the checkout);
 * `CALEVATE_BUILD_COMMIT` overrides it where there is no git.
 */
function buildCommit(): string {
  if (process.env.CALEVATE_BUILD_COMMIT) return process.env.CALEVATE_BUILD_COMMIT.slice(0, 12);
  try {
    return execSync("git rev-parse --short=9 HEAD", { stdio: ["ignore", "pipe", "ignore"] }).toString().trim();
  } catch {
    return "unknown";
  }
}
const APP_VERSION: string = packageJson.version;

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
  // Added with the enforce flip (D-541). Empty does not fail loudly here either — the
  // reader falls back to the LOCAL MinIO origin, so the deployed policy would admit
  // `http://localhost:9000` for `media-src` and refuse the real object store. The symptom
  // is every call recording failing to load, on every client, with nothing in any server
  // log: a CSP refusal happens in the browser.
  NEXT_PUBLIC_MEDIA_ORIGIN:
    "the Content-Security-Policy would admit the local MinIO origin for media and refuse " +
    "the real object store, so no client could play any call recording",
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
  // No `X-Powered-By: Next.js` on any response (OWASP ASVS 4.0.3 14.3.3).
  poweredByHeader: false,
  // A deploy builds into `.next-build` beside the live `.next` and swaps the two once the
  // build is complete (`scripts/vps-deploy.sh deploy_web`); the server always runs `.next`.
  distDir: process.env.CALEVATE_DIST_DIR || ".next",
  // Lint and type checks belong to CI's frontend job; a deploy build skips them because on
  // the live host they took 95 of 270 seconds and change nothing that ships.
  ...(process.env.CALEVATE_SKIP_BUILD_CHECKS === "1"
    ? { typescript: { ignoreBuildErrors: true }, eslint: { ignoreDuringBuilds: true } }
    : {}),
  env: {
    NEXT_PUBLIC_APP_VERSION: APP_VERSION,
    NEXT_PUBLIC_APP_COMMIT: buildCommit(),
    NEXT_PUBLIC_APP_BUILT_AT: new Date().toISOString(),
  },
  async headers() {
    // The HTML and the version file are never cached, so a reload always reaches the newest
    // deploy; Next already serves the hashed `/_next/static` files as immutable.
    return [
      { source: "/version.json", headers: [{ key: "Cache-Control", value: "no-store, max-age=0" }] },
      {
        source: "/((?!_next/static|_next/image|.*\\.(?:png|jpg|jpeg|gif|svg|ico|webp|avif|woff2?)$).*)",
        headers: [{ key: "Cache-Control", value: "no-store, max-age=0" }],
      },
    ];
  },
};

export default nextConfig;
