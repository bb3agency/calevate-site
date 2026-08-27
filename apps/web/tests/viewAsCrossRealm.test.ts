import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/**
 * "View as client" 404'd in production, and could not fail anywhere else.
 *
 * The operator console linked to a RELATIVE `/c/<slug>?view=admin`. In development both
 * realms are one origin on `localhost:3000`, so it worked. In production they are two
 * hostnames and `admin.` REFUSES `/c/` — deliberately, in
 * `infra/nginx/calevate.conf.template`, so an operator hostname cannot serve a client
 * dashboard. The link was asking the operator console for the one tree it is designed
 * never to serve.
 *
 * NOTHING COULD HAVE CAUGHT IT AT RUNTIME. Every test renders one origin; jsdom has no
 * hostnames; the a11y sweep does not follow links. The property is about a STRING in an
 * `app/admin/**` file, so it is checked as one — the same shape as the nginx guards, and
 * for the same reason: the failure is a deployment topology, not a behaviour.
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const ADMIN = resolve(HERE, "../src/app/admin");

/** Every `.tsx` under `app/admin`, walked the way `authnSourceGuards` walks its tree. */
function adminSources(
  dir = ADMIN,
  prefix = "",
): { file: string; text: string }[] {
  const found: { file: string; text: string }[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const rel = prefix === "" ? entry.name : `${prefix}/${entry.name}`;
    if (entry.isDirectory())
      found.push(...adminSources(join(dir, entry.name), rel));
    else if (entry.name.endsWith(".tsx"))
      found.push({
        file: rel,
        text: readFileSync(join(dir, entry.name), "utf8"),
      });
  }
  return found;
}

/** `href="/c/…"` or `href={`/c/${…}`}` — a client-realm path built in the admin tree. */
const BARE_CLIENT_HREF = /href=\{?["'`]\/c\//;

describe("every operator-console link into the client realm", () => {
  it("finds the admin tree at all", () => {
    // The premise. A moved directory would make every assertion below vacuous.
    const sources = adminSources();
    expect(sources.length).toBeGreaterThan(10);
    expect(sources.some((s) => s.file === "page.tsx")).toBe(true);
  });

  it("never hard-codes a relative /c/ path", () => {
    const offenders = adminSources()
      .filter(({ text }) => BARE_CLIENT_HREF.test(text))
      .map(({ file }) => file);
    expect(
      offenders,
      [
        "These build a client-realm link relative to the OPERATOR hostname, which refuses",
        "`/c/` in production. Use `viewAsHref` / `clientConsoleUrl` from `lib/api/session`,",
        "which resolve against NEXT_PUBLIC_CLIENT_CONSOLE_ORIGIN and fall back to a relative",
        "path when the realms share one origin.",
      ].join(" "),
    ).toEqual([]);
  });

  it("routes through the helper, so there is somewhere for the origin to be applied", () => {
    // The negative above is satisfiable by having no view-as links at all. This is the
    // other half: the feature exists and goes through the one place that knows the origin.
    const users = adminSources().filter(({ text }) =>
      text.includes("viewAsHref"),
    );
    expect(users.length).toBeGreaterThanOrEqual(3);
  });
});

describe("clientConsoleUrl", () => {
  it("leaves the path alone when the realms share an origin", async () => {
    // `pnpm dev` is this case, and it must need no configuration.
    const { clientConsoleUrl } = await import("@/lib/consoleOrigin");
    expect(clientConsoleUrl("/c/acme")).toBe("/c/acme");
  });

  it("is still reachable from `lib/api/session`, where the admin screens import it", async () => {
    // It MOVED to `lib/consoleOrigin` (the auth layer and the marketing header need it
    // and should not import a query provider for a hostname) and is re-exported. Two
    // import paths for one function is worth one assertion that they are one function.
    const moved = await import("@/lib/consoleOrigin");
    const reexported = await import("@/lib/api/session");
    expect(reexported.clientConsoleUrl).toBe(moved.clientConsoleUrl);
  });
});

describe("the way OUT of the marketing site, which is served on the apex", () => {
  /**
   * THE SECOND HALF OF THE SIGN-IN BUG, and the half a CORS fix alone would have left.
   *
   * `calevate.tech` serves the three auth screens and the marketing header, and nginx
   * refuses `/c/` there. So `window.location.assign("/c")` after a successful sign-in
   * reached the junction — which the apex DOES serve — and the junction forwarded to
   * `/c/<slug>`, which it does not. A correct password ended on a not-found page.
   *
   * Both exits are read as source rather than rendered, for the reason the guard above
   * gives: what is wrong is a literal in the code, and a rendered assertion would pass on
   * a dev box where the bare path is right.
   */
  const EXITS = [
    ["src/app/(auth)/auth/sign-in/page.tsx", "the destination after a successful sign-in"],
    ["src/components/authn/marketingAccountNav.tsx", "the header's link into the console"],
  ] as const;

  it.each(EXITS)("%s sends the user through clientConsoleUrl", (file, what) => {
    const text = readFileSync(join(process.cwd(), file), "utf8");
    expect(
      text.includes("clientConsoleUrl(CLIENT_CONSOLE_PATH)"),
      `${what} must be resolved against NEXT_PUBLIC_CLIENT_CONSOLE_ORIGIN — a bare ` +
        `CLIENT_CONSOLE_PATH is a 404 one redirect later for anyone on the apex`,
    ).toBe(true);
  });
});

/**
 * THE MIRROR, and it reached production too — the symmetry was there the whole time and
 * only one half was guarded.
 *
 * `app.calevate.tech` refuses `/admin` in exactly the way `admin.` refuses `/c/`, and the
 * apex refuses both. So a bare `/admin` is a 404 everywhere except the one hostname the
 * screens below are never served on:
 *
 *   - The impersonation banner in `app/c/[slug]/layout.tsx` — "Exit and return to the
 *     admin console" — assigned `/admin` from the CLIENT hostname. The one control an
 *     operator is guaranteed to use, at the one moment they are guaranteed to be on the
 *     wrong host for it.
 *   - Every `/admin` destination on the operator AUTH screens, which live under
 *     `app/(auth)/` and are served on the apex.
 *
 * Read as source for the reason the guard above gives: on a single-origin dev box the
 * bare path is correct, so nothing rendered can fail.
 */
const CLIENT_TREE = resolve(HERE, "../src/app/c");
const AUTH_TREE = resolve(HERE, "../src/app/(auth)");

/** `href="/admin…"` or `window.location.assign("/admin…")` — an operator-realm literal. */
const BARE_ADMIN_LINK = /(?:href=\{?|location\.assign\()["'`]\/admin/;

function sourcesUnder(root: string, prefix = ""): { file: string; text: string }[] {
  const found: { file: string; text: string }[] = [];
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const rel = prefix === "" ? entry.name : `${prefix}/${entry.name}`;
    if (entry.isDirectory())
      found.push(...sourcesUnder(join(root, entry.name), rel));
    else if (entry.name.endsWith(".tsx") || entry.name.endsWith(".ts"))
      found.push({ file: rel, text: readFileSync(join(root, entry.name), "utf8") });
  }
  return found;
}

describe("every link out of the client realm and the auth screens into the operator console", () => {
  it("finds both trees at all", () => {
    // The premise, as above: a moved directory makes the assertions vacuous.
    expect(sourcesUnder(CLIENT_TREE).length).toBeGreaterThan(5);
    expect(sourcesUnder(AUTH_TREE).length).toBeGreaterThan(5);
  });

  it.each([
    ["app/c", CLIENT_TREE, "app.calevate.tech, which answers 404 for /admin"],
    ["app/(auth)", AUTH_TREE, "the apex, which answers 404 for /admin"],
  ])("%s never hard-codes a relative /admin path", (_label, root, where) => {
    const offenders = sourcesUnder(root)
      .filter(({ text }) => BARE_ADMIN_LINK.test(text))
      .map(({ file }) => file);
    expect(
      offenders,
      `These build an operator-realm link relative to ${where}. Use ` +
        "`adminConsoleUrl(ADMIN_CONSOLE_PATH)` from `lib/consoleOrigin`, which resolves " +
        "against NEXT_PUBLIC_ADMIN_CONSOLE_ORIGIN and falls back to a relative path when " +
        "the realms share one origin.",
    ).toEqual([]);
  });

  it("routes the exit from a view-as session through the helper", () => {
    // The other half: the negative above is satisfiable by deleting the exit entirely,
    // and there was no exit at all before D-4xx. This asserts the feature still exists.
    const layout = readFileSync(
      join(process.cwd(), "src/app/c/[slug]/layout.tsx"),
      "utf8",
    );
    expect(layout).toContain("adminConsoleUrl(ADMIN_CONSOLE_PATH)");
    expect(layout).toContain("Exit and return to the admin console");
  });
});

describe("adminConsoleUrl", () => {
  it("leaves the path alone when the realms share an origin", async () => {
    const { adminConsoleUrl } = await import("@/lib/consoleOrigin");
    expect(adminConsoleUrl("/admin")).toBe("/admin");
  });
});

describe("the deploy build refuses to ship either origin empty", () => {
  it("names both NEXT_PUBLIC_*_CONSOLE_ORIGIN variables", () => {
    // Both bugs shipped because an unset NEXT_PUBLIC_ value inlines as "" and the build
    // still succeeds. `next.config.ts` is the only thing standing between that and a
    // deploy; a variable missing from its list is a variable that can silently be empty.
    const config = readFileSync(join(process.cwd(), "next.config.ts"), "utf8");
    expect(config).toContain("NEXT_PUBLIC_CLIENT_CONSOLE_ORIGIN:");
    expect(config).toContain("NEXT_PUBLIC_ADMIN_CONSOLE_ORIGIN:");
    const example = readFileSync(join(process.cwd(), ".env.example"), "utf8");
    expect(example).toContain("NEXT_PUBLIC_ADMIN_CONSOLE_ORIGIN=");
  });
});
