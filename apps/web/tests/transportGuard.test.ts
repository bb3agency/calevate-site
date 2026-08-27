import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";
import { describe, expect, it } from "vitest";

import { relPosix } from "./repoPaths";

/**
 * "No ad-hoc fetch" (CLAUDE.md, Conventions), made executable.
 *
 * ## What the convention is actually protecting
 *
 * `fetch` is not banned because a typed client is tidier. Every request this console makes
 * has to carry things a bare `fetch` does not know about, and each of them fails SILENTLY
 * when it is missing:
 *
 * - **The credential.** The session is an `HttpOnly` `__Host-` cookie and admin requests
 *   additionally carry the view-as grant (D-22). A `fetch` without `credentials` sends no
 *   cookie at all and gets a 401 that reads like a signed-out session.
 * - **The RFC-9457 refusal.** `apiRequest` turns a `problem+json` body into `ApiProblem`,
 *   which is what `ProblemNotice` renders as a title, a remediation and a retry. A raw
 *   `fetch` hands back a `Response`; every one of those sentences — written by the API
 *   specifically so the person on the other end knows what to do next — is discarded at
 *   the last hop.
 * - **The deadline and the abort.** `lib/api/client.ts` gives every request a timeout, so
 *   a hung request eventually stops being hung. A bare `fetch` hangs until the tab closes.
 * - **The typed response.** The whole `openapi.json -> schema.d.ts` chain, and the
 *   guardrail that keeps the two in step, only binds code that goes through the client.
 *
 * None of that is visible in a diff that adds one `fetch(...)`, and all of it is visible
 * to a user as "the console is broken" rather than as a message they can act on.
 *
 * ## Why a test rather than a lint rule
 *
 * `no-restricted-globals` would say it in the editor, which is better — but it cannot
 * express the exemption. The two transport modules MUST call `fetch`; they are the
 * chokepoint. A lint rule would need an inline disable in each of them, which is a
 * per-file waiver anybody can copy into a third file, and the moment there are three the
 * rule means nothing. The allowlist below is a visible diff in a shared file, which is the
 * discipline `check_redaction_exposure.KNOWN_SAFE_FIELDS` and `tests/a11y.ts`'s exemption
 * tables already use here.
 */

const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SRC = resolve(WEB_ROOT, "src");

/**
 * The ONLY modules that may call `fetch`, each with what it is the chokepoint for.
 *
 * Adding a row here is adding a second way to talk to the API, which CLAUDE.md calls a
 * defect even when both work. The bar is not "this module needs a request" — every module
 * needs a request — it is "this module cannot go through `apiRequest` because it IS
 * `apiRequest`".
 */
const TRANSPORTS: Record<string, string> = {
  "lib/api/client.ts":
    "THE client. `apiRequest` is what carries the session cookie, the view-as grant, the " +
    "request deadline and the RFC-9457 -> ApiProblem conversion every screen renders.",
  "lib/authn/transport.ts":
    "The AUTHN transport, deliberately separate (D-177): the admin realm and the client " +
    "realm have separate first-party session modules and must not share session logic, " +
    "and this is the one that can run before a session exists.",
  "lib/copilot/stream.ts":
    "The SSE transport for POST /v1/copilot/ask. It CANNOT go through `apiRequest`: " +
    "`readBody` consumes the whole response and resolves once, which is precisely what a " +
    "`text/event-stream` must not do, and the browser's `EventSource` cannot be used at " +
    "all because `EventSourceInit` has only `withCredentials` — no method, no headers, no " +
    "body — so a screen description cannot be POSTed by it. It imports `ApiProblem`, " +
    "`problemFrom`, `TimeoutProblem` and `API_BASE` from the client rather than " +
    "re-implementing them, so every refusal still reaches `ProblemNotice` unchanged.",
};

/** Every `.ts`/`.tsx` under `src`, as repo-relative `/` paths. */
function sourceFiles(): string[] {
  const found: string[] = [];
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) walk(path);
      else if (/\.tsx?$/.test(entry.name) && !entry.name.endsWith(".d.ts")) found.push(path);
    }
  };
  walk(SRC);
  return found.sort();
}

/**
 * Is this call expression a call to the global `fetch`?
 *
 * Matches the bare identifier and the three ways it is reached through a global object.
 * NOT a regex, because `fetch(` occurs in prose in a dozen comments in this tree — the
 * module header above is itself one — and a guard that fires on a comment about the rule
 * is a guard somebody deletes.
 *
 * A method named `fetch` on some other object (`queryClient.fetchQuery`, a mock's
 * `.fetch`) is deliberately NOT matched: those are not the global, and over-matching costs
 * the same trust as under-matching.
 */
function isGlobalFetch(node: ts.CallExpression): boolean {
  const callee = node.expression;
  if (ts.isIdentifier(callee)) return callee.text === "fetch";
  if (ts.isPropertyAccessExpression(callee) && callee.name.text === "fetch") {
    return (
      ts.isIdentifier(callee.expression) &&
      ["window", "globalThis", "global"].includes(callee.expression.text)
    );
  }
  return false;
}

/** `file:line` for every global `fetch` call in the file. */
function fetchSites(path: string): string[] {
  const file = ts.createSourceFile(
    path,
    readFileSync(path, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    path.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const sites: string[] = [];
  const visit = (node: ts.Node): void => {
    if (ts.isCallExpression(node) && isGlobalFetch(node)) {
      const { line } = file.getLineAndCharacterOfPosition(node.getStart(file));
      sites.push(`${relPosix(SRC, path)}:${line + 1}`);
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return sites;
}

describe("every request goes through the typed client", () => {
  it("scans a plausible number of source files and finds the transports", () => {
    // The premise, first and alone. A scan that has silently stopped matching — a moved
    // `src`, a changed extension, an AST shape this selector no longer recognises —
    // reports a perfectly clean tree, which is indistinguishable from a passing one.
    const files = sourceFiles();
    expect(files.length, "the source walk found almost nothing — has src/ moved?")
      .toBeGreaterThan(100);
    const withFetch = files.filter((file) => fetchSites(file).length > 0).map((f) => relPosix(SRC, f));
    for (const transport of Object.keys(TRANSPORTS)) {
      expect(withFetch, `the scan cannot see the fetch in ${transport}`).toContain(transport);
    }
  });

  it("has no ad-hoc fetch outside the two transport modules", () => {
    const offenders = sourceFiles()
      .filter((file) => !Object.hasOwn(TRANSPORTS, relPosix(SRC, file)))
      .flatMap(fetchSites);

    expect(
      offenders,
      "these call the global `fetch` directly instead of `apiRequest` " +
        "(src/lib/api/client.ts). A bare fetch sends no session cookie and no view-as " +
        "grant, has no request deadline, and throws away the API's RFC-9457 refusal — so " +
        "the sentence the server wrote for the user never reaches ProblemNotice and the " +
        "screen shows a generic failure instead. Route it through `apiRequest`, or add a " +
        "row to TRANSPORTS in this file saying why this module IS the transport.",
    ).toEqual([]);
  });
});
