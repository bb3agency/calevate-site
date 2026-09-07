import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { toPosix } from "./repoPaths";

/**
 * THE EDGE HALF of this app's response headers, and the one property the CSP depends on.
 *
 * `lib/security/csp.ts` is tested by `csp.test.ts` and covers the app tier. Everything
 * else a browser is told about this origin is set once, at the edge, in
 * `infra/nginx/snippets/calevate-headers.conf` — and nothing anywhere read that file back.
 * Two failures were therefore invisible from any test in either tree:
 *
 *  1. **A header simply not being there.** `Permissions-Policy` was absent from the whole
 *     repository, so the microphone, the camera and the sensor APIs were available to this
 *     origin by browser default on a console whose product is telephone calls. An absence
 *     is exactly what a suite that only checks values cannot see, which is why the
 *     assertion below is a required SET rather than a per-header value check.
 *  2. **nginx's `add_header` inheritance rule**, which is the trap that makes this file
 *     worth a test rather than a review. A single `add_header` inside a `location` block
 *     DISCARDS every `add_header` inherited from the enclosing `server` — silently, with
 *     no warning from `nginx -t`. So one future line adding a cache header to
 *     `location ^~ /_next/static/` would strip HSTS, the framing refusal and the sniffing
 *     refusal from every build asset, and nothing would look broken.
 *
 * WHY THIS LIVES IN THE VITEST SUITE. The frontend owns these headers — they are the
 * browser tier's contract and they are argued for in the app's own security module — and
 * `residencyWarrantyMirror.test.ts` already established that a web test may read up out of
 * `apps/web` to hold a property that spans two trees.
 */

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const NGINX = resolve(REPO_ROOT, "infra/nginx");
const HEADERS_SNIPPET = resolve(NGINX, "snippets/calevate-headers.conf");

/** Lines with the `#` comments removed, so a header NAMED in prose is not a header SET. */
function directives(path: string): string[] {
  return readFileSync(path, "utf8")
    .split("\n")
    .map((line) => line.replace(/#.*$/, "").trim())
    .filter(Boolean);
}

/** `add_header <Name> ...` -> `Name`, for every add_header in a file. */
function headerNames(lines: string[]): string[] {
  return lines
    .map((line) => /^add_header\s+([A-Za-z-]+)\b/.exec(line)?.[1])
    .filter((name): name is string => name !== undefined);
}

/**
 * Every `.conf`/`.template` under `infra/nginx`, so a NEW vhost or snippet is covered the
 * day it is added rather than the day somebody remembers to list it here.
 */
function nginxFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) return nginxFiles(full);
    return /\.(conf|template)$/.test(entry) ? [full] : [];
  });
}

describe("the edge security headers", () => {
  const lines = directives(HEADERS_SNIPPET);

  it("sets every header the browser tier relies on the edge for", () => {
    // The CSP is deliberately NOT here — it carries a per-request nonce and is set by
    // `src/middleware.ts`. The snippet says so in its own comment; this asserts the rest.
    expect(headerNames(lines).sort()).toEqual(
      [
        "Cross-Origin-Opener-Policy",
        "Permissions-Policy",
        "Referrer-Policy",
        "Strict-Transport-Security",
        "X-Content-Type-Options",
        "X-Frame-Options",
      ].sort(),
    );
  });

  it("denies the powerful features this app never uses, to every origin including itself", () => {
    const policy = lines.find((line) => line.startsWith("add_header Permissions-Policy"));
    expect(policy).toBeDefined();
    // `()` and not `(self)`: an empty allowlist is denial, and denial to our OWN origin is
    // the half that an XSS foothold would otherwise walk through.
    for (const feature of ["camera", "microphone", "geolocation", "usb", "serial", "midi"]) {
      expect(policy).toContain(`${feature}=()`);
    }
    expect(policy).not.toContain("=(*)");
  });

  it("carries `always` on every header, so an error page is not the unprotected one", () => {
    for (const line of lines.filter((l) => l.startsWith("add_header"))) {
      expect(line, `${line} — without \`always\` nginx omits it on 4xx/5xx`).toMatch(
        /\balways;$/,
      );
    }
  });

  it("keeps HSTS at two years with subdomains", () => {
    const hsts = lines.find((line) => line.includes("Strict-Transport-Security"));
    expect(hsts).toContain("max-age=63072000");
    expect(hsts).toContain("includeSubDomains");
  });

  /**
   * The inheritance trap, asserted over EVERY nginx file rather than the one that has the
   * headers today. nginx replaces the inherited `add_header` set the moment a nested block
   * declares one of its own, so the safe shape for this repository is: all `add_header`
   * directives live in `calevate-headers.conf`, included at `server` scope, and nowhere
   * else. If a per-location header ever becomes genuinely necessary, that block must
   * re-include this snippet — and this test is where that argument gets written down.
   */
  it("declares add_header in exactly one file, so no location block can shadow the set", () => {
    const offenders = nginxFiles(NGINX)
      .filter((file) => file !== HEADERS_SNIPPET)
      .filter((file) => headerNames(directives(file)).length > 0)
      .map((file) => toPosix(file.slice(REPO_ROOT.length + 1)));
    expect(offenders).toEqual([]);
  });
});
