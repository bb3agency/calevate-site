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
    const { clientConsoleUrl } = await import("@/lib/api/session");
    expect(clientConsoleUrl("/c/acme")).toBe("/c/acme");
  });
});
