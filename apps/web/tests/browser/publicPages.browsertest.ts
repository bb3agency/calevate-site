import { afterAll, beforeAll, describe, expect, it } from "vitest";

import type { Browser } from "playwright-core";

import {
  AUTHENTICATED_REALM_NOTE,
  AXE_TAGS,
  formatScan,
  launchBrowser,
  PALETTES,
  REQUIRED_RULE,
  resolveChromium,
  SCAN_TARGETS,
  scanTarget,
  startStubApi,
  startWebServer,
  unlistedPublicRoutes,
  VIEWPORTS,
  type PageScan,
  type ServerMode,
  type StubApi,
  type WebServer,
} from "./gate";

/**
 * The browser accessibility gate — WCAG A/AA over the real composed documents.
 *
 * Runs under its own config (`vitest.browser.config.mts`), NOT with the jsdom suite,
 * because it needs a node environment, a served app and a real browser. `tests/browser/
 * gate.ts` holds the argument for why it exists and every reason it refuses to skip.
 *
 * ## The floor this asserts, in one place
 *
 * `EXPECTED_SCANS` below is the declared surface: pages x viewports x palettes. The run
 * is held to it exactly — not "at least one page scanned", which is the assertion a
 * hollow gate passes. If the browser is missing, the server dies, a route 404s, the page
 * list is empty, or `color-contrast` did not actually run, this file fails and says which.
 */

/** Mode is switchable so the dev-vs-build equivalence can be re-measured. See gate.ts. */
const MODE: ServerMode = process.env.CALEVATE_A11Y_SERVER === "build" ? "build" : "dev";

/**
 * THE FLOOR ON COVERAGE. `/` plus the seven nav routes is eight public pages; the rest
 * are the signup form, the legal index and a legal document, and the two realm sign-in
 * screens. A change that shrinks the list below eight fails here rather than quietly
 * scanning less.
 */
const MINIMUM_PUBLIC_PAGES = 8;
const EXPECTED_SCANS = SCAN_TARGETS.length * VIEWPORTS.length * PALETTES.length;

let api: StubApi;
let server: WebServer;
let browser: Browser;
let browserPath = "";
let browserSource = "";
const scans: PageScan[] = [];
let startedAt = 0;

beforeAll(async () => {
  startedAt = Date.now();
  // ORDER MATTERS: the page list is checked before anything expensive starts, so an
  // empty or shrunken list fails in milliseconds instead of after a browser download's
  // worth of setup — and can never be the reason a run "found no violations".
  if (SCAN_TARGETS.length < MINIMUM_PUBLIC_PAGES) {
    throw new Error(
      `the browser a11y gate has ${SCAN_TARGETS.length} page(s) declared, below the ` +
        `floor of ${MINIMUM_PUBLIC_PAGES}. An empty or thinned page list is the way this ` +
        `gate would pass while checking nothing, so it is a failure, not a smaller run.`,
    );
  }
  // The browser is resolved (not launched) BEFORE the server boots, for the same
  // fail-fast reason: a machine with no Chromium should hear about it in a second, not
  // after a minute of `next build`.
  resolveChromium();
  api = await startStubApi();
  server = await startWebServer(MODE, api.port);
  const launched = await launchBrowser();
  browser = launched.browser;
  browserPath = launched.path;
  browserSource = launched.source;

  for (const target of SCAN_TARGETS) {
    for (const viewport of VIEWPORTS) {
      scans.push(...(await scanTarget(browser, server.baseUrl, target, viewport)));
    }
  }
}, 900_000);

afterAll(async () => {
  await browser?.close();
  await server?.close();
  await api?.close();
});

describe("browser accessibility gate (WCAG 2.2 A/AA, real Chromium)", () => {
  it("scanned exactly the declared surface, and did not skip anything", () => {
    expect(
      scans.length,
      `expected ${EXPECTED_SCANS} scans (${SCAN_TARGETS.length} pages x ` +
        `${VIEWPORTS.length} viewports x ${PALETTES.length} palettes) and got ` +
        `${scans.length}. A short run is a failure: this gate's whole value is that it ` +
        `cannot report green on pages it never opened.`,
    ).toBe(EXPECTED_SCANS);
    expect(scans.every((s) => s.status === 200)).toBe(true);
  });

  it("ran the rules it claims to run, on every scan", () => {
    for (const scan of scans) {
      const where = `${scan.path} ${scan.viewport}/${scan.palette}`;
      expect(scan.runOnly, `${where}: axe reported a different tag set`).toEqual([...AXE_TAGS]);
      // THE ANTI-VACUITY ASSERTION. Zero violations means nothing unless the one rule
      // this gate exists for was evaluated: under jsdom `color-contrast` is disabled and
      // reports nothing at all, which is exactly the shape of a silent pass.
      expect(
        scan.evaluatedRules,
        `${where}: axe did not evaluate ${REQUIRED_RULE} at all. A scan without the ` +
          `contrast rule is the jsdom blind spot this gate was built to close, so a ` +
          `clean result from it is not a pass.`,
      ).toContain(REQUIRED_RULE);
      // A real page evaluates dozens of rules. A handful means the document was a stub,
      // an error page or an empty shell.
      expect(
        new Set(scan.evaluatedRules).size,
        `${where}: axe evaluated only ${new Set(scan.evaluatedRules).size} distinct ` +
          `rules — the document is almost certainly not the page`,
      ).toBeGreaterThan(20);
    }
  });

  it("has no page whose links escape the declared list", async () => {
    const unlisted = await unlistedPublicRoutes(browser, server.baseUrl);
    expect(
      unlisted,
      `the home page links to ${unlisted.join(", ")}, which SCAN_TARGETS does not name. ` +
        `Add it to tests/browser/gate.ts (with why), or add its prefix to the covered / ` +
        `not-public lists there. A sweep that silently falls behind the navigation is how ` +
        `a green tick comes to mean less every release.`,
    ).toEqual([]);
  });

  it.each(SCAN_TARGETS.map((t) => t.path))("has no WCAG A/AA violation on %s", (path) => {
    const forPath = scans.filter((s) => s.path === path);
    expect(forPath.length, `${path} produced no scan at all`).toBe(
      VIEWPORTS.length * PALETTES.length,
    );
    const failing = forPath.filter((s) => s.violations.length > 0);
    const message = failing
      .map(
        (s) =>
          `${s.path} @ ${s.viewport}/${s.palette} — ${s.violations.length} violation(s):\n` +
          formatScan(s),
      )
      .join("\n\n");
    expect(failing.map((s) => `${s.viewport}/${s.palette}`), message).toEqual([]);
  });

  it("prints what it checked, so a green tick can be audited", () => {
    const rules = new Set(scans.flatMap((s) => s.evaluatedRules));
    const lines = [
      "",
      "BROWSER A11Y GATE — what actually ran",
      `  browser        : ${browserPath}`,
      `  resolved via   : ${browserSource}`,
      `  server         : next ${server.mode} on ${server.baseUrl} ` +
        `(up in ${(server.startupMs / 1000).toFixed(1)}s)`,
      `  stub api       : GET /v1/public/rate-card from tests/fixtures/rateCard.ts` +
        (api.unexpected.length
          ? `; UNSTUBBED requests seen: ${[...new Set(api.unexpected)].join(", ")}`
          : "; no other server-side request was made"),
      `  pages          : ${SCAN_TARGETS.length} (${SCAN_TARGETS.map((t) => t.path).join(" ")})`,
      `  viewports      : ${VIEWPORTS.map((v) => `${v.name} ${v.width}x${v.height}`).join(", ")}`,
      `  palettes       : ${PALETTES.join(", ")} (dark forced by the harness only — D-471)`,
      `  axe tags       : ${AXE_TAGS.join(", ")}`,
      `  scans          : ${scans.length}, all HTTP 200`,
      `  distinct rules : ${rules.size} evaluated, including ${REQUIRED_RULE}`,
      `  wall clock     : ${((Date.now() - startedAt) / 1000).toFixed(1)}s`,
      `  NOT covered    : ${AUTHENTICATED_REALM_NOTE}`,
      "",
    ];
    // This line IS part of the deliverable: a gate that reports only "passed" cannot be
    // told apart from a gate that checked nothing. `disableConsoleIntercept` in
    // vitest.browser.config.mts is what gets it to a non-TTY log.
    console.log(lines.join("\n"));
    expect(rules.size).toBeGreaterThan(20);
  });
});
