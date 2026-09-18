import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { middleware } from "@/middleware";
import { ADMIN_BOOTSTRAP_PATH, ADMIN_RESET_PATH } from "@/lib/authn/adminAuthn";
import { CLIENT_ACCEPT_INVITE_PATH, CLIENT_RESET_PATH } from "@/lib/authn/clientAuthn";
import {
  LEGACY_INVITE_PATH,
  LINK_TOKEN_PATHS,
  LINK_TOKEN_REFERRER_POLICY,
  REFERRER_POLICY_HEADER_NAME,
  carriesLinkToken,
} from "@/lib/authn/linkTokenRoutes";

/**
 * THE `Referer` LEAK OF A LIVE SINGLE-USE TOKEN, pinned at all three of the places it was
 * open.
 *
 * The defect, in one sentence: `useLinkToken` strips `?token=` in a `useEffect` — after
 * first paint — so every chunk and font the document had already preloaded went out with
 * `Referer: https://…/auth/reset-password?token=<secret>`, the edge served
 * `strict-origin-when-cross-origin` (whose same-origin arm is the full URL), and
 * `00-log-format.conf.template` wrote `"$http_referer"` verbatim one field after the
 * `$request_uri` it carefully redacted. A live `password_reset` (1h),
 * `accept-invitation` (72h) or `admin_bootstrap` (60m) token, in
 * `/var/log/nginx/access.log`.
 *
 * Three properties are asserted, and each fails independently of the others because each
 * fix alone leaves a hole:
 *
 *  1. **The middleware sets `strict-origin` on those routes** — the browser half.
 *  2. **The nginx map redacts `token=` out of the LOGGED referer** — the half that holds
 *     regardless of what the app sent or what the client honoured.
 *  3. **The edge's own `Referrer-Policy` does not override the app's.** `add_header`
 *     APPENDS, and a browser takes the LAST value in the list, so an unconditional
 *     `add_header Referrer-Policy "strict-origin-when-cross-origin"` at the edge would
 *     have made property 1 inert in production while leaving every test in this file that
 *     only checked the middleware perfectly green. That is the assertion this suite would
 *     most regret not having.
 */

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const NGINX = resolve(REPO_ROOT, "infra/nginx");

const read = (p: string): string => readFileSync(resolve(NGINX, p), "utf8");
/** Lines with `#` comments removed, so a directive NAMED in prose is not a directive SET. */
const directives = (p: string): string[] =>
  read(p)
    .split("\n")
    .map((line) => line.replace(/#.*$/, "").trim())
    .filter(Boolean);

function policyFor(pathname: string): string | null {
  const response = middleware(new NextRequest(new URL(`https://app.calevate.tech${pathname}`)));
  return response.headers.get(REFERRER_POLICY_HEADER_NAME);
}

describe("the routes an emailed token lands on", () => {
  it("is exactly the set the screens and console_links.py mint", () => {
    // `linkTokenRoutes.ts` spells these as literals so `middleware.ts` does not drag the
    // realm session runtime into the edge bundle; this is what keeps the two in step.
    expect([...LINK_TOKEN_PATHS].sort()).toEqual(
      [
        CLIENT_RESET_PATH,
        CLIENT_ACCEPT_INVITE_PATH,
        ADMIN_RESET_PATH,
        ADMIN_BOOTSTRAP_PATH,
        LEGACY_INVITE_PATH,
      ].sort(),
    );
  });

  it("matches the trailing-slash spelling and nothing deeper", () => {
    expect(carriesLinkToken("/auth/reset-password/")).toBe(true);
    expect(carriesLinkToken("/auth/reset-password/anything")).toBe(false);
    expect(carriesLinkToken("/auth/sign-in")).toBe(false);
  });
});

describe("the middleware's Referrer-Policy", () => {
  it.each(LINK_TOKEN_PATHS)("serves origin-only on %s", (path) => {
    expect(policyFor(path)).toBe(LINK_TOKEN_REFERRER_POLICY);
  });

  it("sends the origin and never the path or query", () => {
    // The value itself is the assertion: `strict-origin` sends the origin on same-origin
    // AND cross-origin requests. `same-origin` and `strict-origin-when-cross-origin` both
    // send the FULL URL to our own origin, which is the arm that leaked.
    expect(LINK_TOKEN_REFERRER_POLICY).toBe("strict-origin");
  });

  it("leaves every other route on the edge default", () => {
    // Not a narrowing applied everywhere: the console's own navigation relies on the full
    // same-origin referer nowhere, but changing a global default is a separate decision
    // and this fix does not smuggle one in.
    for (const path of ["/auth/sign-in", "/c/dashboard", "/admin", "/"]) {
      expect(policyFor(path)).toBeNull();
    }
  });

  it("still sets the CSP on a token-bearing route", () => {
    // The header is ADDED to that response, not swapped for the one already there.
    const response = middleware(new NextRequest(new URL(`https://app.calevate.tech${CLIENT_RESET_PATH}`)));
    expect(response.headers.get("Content-Security-Policy")).toContain("frame-ancestors 'none'");
  });
});

describe("the access log", () => {
  const logFormat = directives("00-log-format.conf.template");

  it("logs a redacted referer, never $http_referer itself", () => {
    const format = logFormat.filter((line) => line.startsWith("log_format") || line.startsWith("'"));
    expect(format.join(" ")).toContain("$calevate_logged_referer");
    expect(format.join(" ")).not.toContain("$http_referer");
  });

  it("maps the referer through the same token redaction as the request uri", () => {
    const maps = logFormat.join("\n");
    expect(maps).toContain("map $http_referer $calevate_logged_referer");
    // Both maps must key on the parameter name, so adding a second secret-bearing
    // parameter is one change in one file.
    expect(maps.match(/token=/g)?.length ?? 0).toBeGreaterThanOrEqual(4);
  });
});

describe("the edge Referrer-Policy", () => {
  it("defers to the app's value instead of appending after it", () => {
    const header = directives("snippets/calevate-headers.conf").find((line) =>
      line.startsWith("add_header Referrer-Policy"),
    );
    expect(header).toBeDefined();
    // A literal here would be appended AFTER the app's header and would win.
    expect(header).toContain("$calevate_referrer_policy");
    expect(header).not.toContain("strict-origin-when-cross-origin");
  });

  it("keeps the default for everything the app does not answer for", () => {
    const template = directives("calevate.conf.template").join("\n");
    expect(template).toContain("map $upstream_http_referrer_policy $calevate_referrer_policy");
    // The default arm is the console-wide policy; the `~.` arm (upstream answered) is
    // empty, and nginx adds no header for an empty value.
    expect(template).toMatch(/default\s+"strict-origin-when-cross-origin";/);
    expect(template).toMatch(/"~\."\s+"";/);
  });
});
