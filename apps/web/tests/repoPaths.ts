/**
 * Repo-relative paths that read the same on every developer's machine.
 *
 * WHY THIS EXISTS. Eight source-scanning guards in this suite compare a path they built
 * with `node:path` against a forward-slash literal — an exemption key, an expected
 * offender list, a prefix test. `node:path` uses the HOST separator, so on Windows every
 * one of those comparisons is between `src\lib\authn\adminAuthn.ts` and
 * `src/lib/authn/adminAuthn.ts`, and each fails in its own way:
 *
 * - **A false positive.** `contrast.test.ts` keys `BRAND_FILL_EXEMPT` on forward slashes,
 *   so an argued-for exemption stops matching and the guard reports a violation that was
 *   settled long ago. Loud, at least.
 * - **A false NEGATIVE, which is the dangerous one.** `wireFixtureGuard`,
 *   `surfaceStatesGuard` and `wireLookupGuard` select their inputs with
 *   `file.fileName.startsWith(resolve(WEB_ROOT, "src") + "/")`. TypeScript normalises
 *   `SourceFile.fileName` to forward slashes on every platform, so that prefix —
 *   `D:\...\web\src/`, backslashes with one forward slash welded on the end — matches
 *   NOTHING. The scan then walks zero files and finds zero violations. Each of those
 *   three has a premise check (`expect(sources.length).toBeGreaterThan(40)`) written
 *   precisely because its author knew a scan that stops matching is indistinguishable
 *   from a clean tree, and it is those premise checks that were failing rather than the
 *   guards themselves. They were right to be there.
 *
 * ONE HELPER RATHER THAN A FIX PER FILE, because this is one bug with eight call sites
 * and CLAUDE.md's rule is one way per problem. A repo path is a `/` path here, always,
 * whatever the host calls it.
 *
 * NOT a general path library: everything below is for COMPARING and REPORTING paths.
 * Opening a file still uses `node:path`, because that is the one job the host separator
 * is right for.
 */

import { relative, resolve, sep } from "node:path";

/**
 * The same path, spelled with `/`.
 *
 * A no-op on POSIX. On Windows it is what makes a path comparable to a literal written
 * by a person, which is how every exemption key and expected-offender list in this suite
 * is written.
 */
export function toPosix(path: string): string {
  return sep === "/" ? path : path.split(sep).join("/");
}

/** `node:path`'s `relative`, in the one spelling this suite compares against. */
export function relPosix(from: string, to: string): string {
  return toPosix(relative(from, to));
}

/**
 * A `/`-spelled directory prefix, trailing slash included, for `startsWith` against a
 * TypeScript `SourceFile.fileName`.
 *
 * The trailing slash is part of the contract and not a detail: without it `src` also
 * prefixes a sibling called `srcgen`, and the whole point of this helper is that the
 * three guards using it stop being able to select the wrong set silently.
 */
export function posixDirPrefix(...segments: string[]): string {
  return `${toPosix(resolve(...segments))}/`;
}
