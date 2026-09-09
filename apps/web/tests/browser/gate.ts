import { spawn, type ChildProcessByStdio } from "node:child_process";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { createServer, type Server } from "node:http";
import { createRequire } from "node:module";
import { AddressInfo, createServer as createProbe } from "node:net";
import { dirname, join, resolve } from "node:path";
import type { Readable } from "node:stream";
import { fileURLToPath } from "node:url";

import { chromium, type Browser, type Page } from "playwright-core";

import { PUBLIC_ROUTES } from "@/lib/site";

import { RATE_CARD } from "../fixtures/rateCard";

/**
 * THE BROWSER HALF OF THE ACCESSIBILITY FLOOR (UX-DOCTRINE §8.4) — the rules jsdom
 * structurally cannot run.
 *
 * ## Why a second a11y gate exists at all
 *
 * `tests/a11y.test.tsx` sweeps every route file under jsdom and is the broader gate: it
 * renders eighty-odd screens with their fixtures, including authenticated ones this
 * harness can never reach. What it CANNOT do is colour. `tests/a11y.ts` disables
 * `color-contrast` (`JSDOM_BLIND_RULES`) and says so honestly — jsdom implements no
 * layout, resolves no computed background and has no canvas, so axe reports `incomplete`
 * rather than a verdict. `tests/contrastTokens.test.ts` closes part of that gap by
 * checking the palette token-on-token.
 *
 * Neither can see a token on a TRANSLUCENT ground. `bg-brand-soft/30` composites the
 * token against whatever is behind it, and the result is a colour that exists nowhere in
 * `globals.css`. A real browser scan of the composed pages found SEVEN live WCAG 1.4.3
 * AA failures on this site that both existing gates reported green on — the worst at
 * **1.04:1** (`dark:text-ink` on `bg-brand-soft`), plus `text-ink-faint` on
 * `bg-brand-soft/30` on `/industries`, two in `heroCallSim.tsx`, one in
 * `roiCalculator.tsx`. Every one was found by a browser and none by any gate we run.
 * This is that gate.
 *
 * ## The design constraint this is built around: it may never pass vacuously
 *
 * A browser-dependent gate whose failure mode is "binary missing -> nothing ran ->
 * green" is worse than no gate, because it reports success while checking nothing. That
 * is the same defect class as a character floor with 4.7x headroom or a `no cover`
 * pragma on a hard-rule surface. So every absence here is a LOUD FAILURE and never a
 * skip:
 *
 * - no Chromium on disk -> throws, naming every path it looked in;
 * - the web server did not answer -> throws, with the server's own last output;
 * - a page 404s or 500s -> throws, naming the URL and the status;
 * - zero pages scanned, or fewer than the declared minimum -> throws;
 * - the declared page list is empty or short -> throws before a browser is even started;
 * - `color-contrast` did not appear in the rules axe actually evaluated -> throws, even
 *   if there were no violations. A scan that did not run the one rule this gate exists
 *   for is not a pass.
 *
 * And on success it PRINTS what it did — pages, viewports, palettes, rule tags, and the
 * count of rules axe evaluated per scan — so a reader can tell a real pass from a hollow
 * one without reading this file.
 */

const require_ = createRequire(import.meta.url);

/** `apps/web`, from this file rather than from `process.cwd()`. */
export const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

/**
 * The WCAG tags axe is asked for, and the set the run is asserted against.
 *
 * Level A and AA of 2.0/2.1/2.2 — the conformance target UX-DOCTRINE §8 states. AAA is
 * not a target (§8.4 sets the bar at 4.5:1, which is AA) and `best-practice` is Deque's
 * own advice rather than a standard, so neither is included: a gate that fails on advice
 * gets waived, and a waived gate protects nothing.
 */
export const AXE_TAGS: readonly string[] = [
  "wcag2a",
  "wcag2aa",
  "wcag21a",
  "wcag21aa",
  "wcag22aa",
];

/**
 * The rule this gate exists for. Asserted to have RUN on every scan — see the vacuity
 * argument above. `color-contrast-enhanced` (AAA) is deliberately not here.
 */
export const REQUIRED_RULE = "color-contrast";

/** Viewports: the phone this product is designed for (§8.6), and a desktop. */
export const VIEWPORTS: readonly { name: string; width: number; height: number }[] = [
  { name: "desktop", width: 1440, height: 900 },
  // 390x844 is the iPhone 12/13/14 CSS viewport and a fair stand-in for the mid-range
  // Android the doctrine names; the narrower 320px floor is what `responsive.test.ts`
  // pins, and is a layout property rather than a contrast one.
  { name: "mobile", width: 390, height: 844 },
];

/**
 * BOTH PALETTES, AND WHY THE DARK ONE IS FORCED HERE RATHER THAN ANYWHERE IN `src/`.
 *
 * D-471 ships the product light-only: the `.dark` block and 429 `dark:` utilities remain
 * in the tree deliberately, dormant because NOTHING can set the class, and
 * `tests/lightOnly.test.ts` fails the build if any file under `src/` gains the ability to
 * set it or to read `prefers-color-scheme`.
 *
 * The 1.04:1 failure was dark-only. A dormant palette that is never checked is a palette
 * that will be wrong on the day it is switched on — so the class is added by the HARNESS,
 * from outside the application, in a browser context that no shipped code can reach.
 * That keeps `lightOnly.test.ts` true (nothing in `src/` moved) while still holding the
 * dormant half to the same 4.5:1 floor.
 *
 * `globals.css` declares `@custom-variant dark (&:is(.dark *))`, so the class must sit on
 * an ANCESTOR — `<html>` — for the variants to apply. Setting it on the scanned element
 * would silently check nothing.
 */
export const PALETTES = ["light", "dark"] as const;
export type Palette = (typeof PALETTES)[number];

/**
 * Every page this gate scans, with why it is here.
 *
 * ⚠ THE EIGHT PUBLIC PAGES ARE NO LONGER SPELLED HERE. They were, and the header above
 * this list used to argue for it — importing `NAV_ROUTES` would drag React, `next/link`
 * and the whole icon set into a node process whose job is to spawn a server. That argument
 * was about importing a `.tsx` COMPONENT and it still holds; what changed on 9 Sep 2026 is
 * that the site's page list is now a plain data module with no imports at all
 * (`src/lib/site.ts`), written so this harness and `app/sitemap.ts` and the navigation can
 * share one table. Deriving from it costs this process nothing and closes the drift the
 * comment below still guards against from the other end.
 *
 * `assertNoUnlistedPublicRoutes()` STAYS, and is not made redundant by the derivation: it
 * reads the links out of the SERVED home page, so it also catches a route added to the
 * footer or to a card in the body that nobody put in `PUBLIC_ROUTES` either.
 */
export interface ScanTarget {
  /** Path to fetch, e.g. `/pricing`. */
  path: string;
  /** Why this page is in the gate — read by nobody until it needs to change. */
  why: string;
}

export const SCAN_TARGETS: readonly ScanTarget[] = [
  ...PUBLIC_ROUTES.map((route) => ({ path: route.path, why: `public: ${route.why}` })),
  {
    path: "/legal/privacy",
    why: "public: a legal DOCUMENT — long-form prose, a different layout from the index",
  },
  {
    path: "/auth/sign-in",
    why:
      "the client realm's entry screen. It is the furthest into the authenticated realm " +
      "this harness can reach without a real session — see AUTHENTICATED_REALM_NOTE.",
  },
  {
    path: "/auth/admin/sign-in",
    why: "the admin realm's entry screen — a separate session module (D-177), separate shell",
  },
];

/**
 * WHAT THIS GATE DOES NOT COVER, stated here rather than left for a green tick to imply.
 *
 * Populated authenticated screens — the console, the agent editor, the CRM — are not
 * reachable from here. The credential is an `HttpOnly` `__Host-` cookie that only
 * `apps/api/authn/` can mint (there is no identity vendor and no test bypass, and adding
 * one to make a gate reach further would be exactly the "bypass for testing" hard rule 5
 * forbids). Minting one would need a live API, a live database and a seeded tenant, which
 * is a second stack in the frontend's own gate.
 *
 * Those screens are swept by `tests/a11y.test.tsx` under jsdom with their route fixtures,
 * where every rule EXCEPT `color-contrast` runs. So the honest statement of coverage is:
 * public pages get every AA rule in a real browser in both palettes; authenticated
 * screens get every AA rule except contrast, and their contrast rests on
 * `contrastTokens.test.ts` plus the fact that they use the same tokens these pages do.
 *
 * CLOSED BY: an integration environment that boots api + postgres and seeds a session,
 * at which point the two sign-in screens below become a login step and this list grows.
 */
export const AUTHENTICATED_REALM_NOTE =
  "authenticated screens need an api-minted __Host- session cookie; covered by " +
  "tests/a11y.test.tsx under jsdom instead (every AA rule except color-contrast)";

/** Link prefixes on the home page that the target list covers by representative. */
const COVERED_BY_REPRESENTATIVE = ["/legal/"];

/**
 * Links on the served home page that lead OUT of the scannable surface.
 *
 * `/c` is the client-realm chooser and `/auth/...` the realm entries; both are named in
 * SCAN_TARGETS or lead into the authenticated realm the note above explains.
 */
const NOT_A_PUBLIC_PAGE = ["/c", "/admin"];

// ---------------------------------------------------------------------------
// Chromium
// ---------------------------------------------------------------------------

/**
 * The Chromium binary, or a failure naming every place that was looked.
 *
 * Three sources, in order, and the order matters:
 *
 *  1. `CALEVATE_A11Y_CHROMIUM` — an explicit path, for a machine that keeps its browsers
 *     somewhere unusual. Set and wrong is a hard failure, never a fall-through: a typo'd
 *     override that silently used a different browser is a gate reporting on the wrong
 *     renderer.
 *  2. `playwright-core`'s own answer for the revision it was built against. In CI, where
 *     `playwright-core install chromium` has run, this is the path and it is the right
 *     one — same revision as the library.
 *  3. Any `chromium-<rev>` under `PLAYWRIGHT_BROWSERS_PATH`, highest revision first.
 *     This exists because a preprovisioned container commonly ships a revision from a
 *     DIFFERENT playwright release than the one in our lockfile (this repo's dev
 *     container has 1194; `playwright-core@1.62.1` asks for 1234). The CDP surface these
 *     scans use — navigate, evaluate, set a class — is stable across that gap, and a
 *     browser one revision family off is enormously better than no scan at all. It is
 *     announced on stdout when it happens, so a reader is never misled about which
 *     binary produced the verdict.
 *
 * NEVER downloads. An install is an explicit CI step (`playwright-core install
 * chromium`), because a gate that can quietly fetch 150MB mid-run is a gate whose
 * runtime depends on the network.
 */
export function resolveChromium(): { executablePath: string; source: string } {
  const tried: string[] = [];

  const override = process.env.CALEVATE_A11Y_CHROMIUM;
  if (override !== undefined && override !== "") {
    if (existsSync(override)) return { executablePath: override, source: "CALEVATE_A11Y_CHROMIUM" };
    throw new Error(
      `CALEVATE_A11Y_CHROMIUM is set to ${override}, which does not exist. Unset it to ` +
        `use the browser playwright-core resolves, or point it at a real chrome binary. ` +
        `This gate does not fall back from an explicit override: a typo'd path must not ` +
        `quietly change which browser the accessibility verdict came from.`,
    );
  }

  let fromPlaywright: string | undefined;
  try {
    fromPlaywright = chromium.executablePath();
  } catch (error) {
    tried.push(`playwright-core could not name a path: ${String(error)}`);
  }
  if (fromPlaywright !== undefined) {
    if (existsSync(fromPlaywright)) {
      return { executablePath: fromPlaywright, source: "playwright-core (matching revision)" };
    }
    tried.push(fromPlaywright);
  }

  const root = process.env.PLAYWRIGHT_BROWSERS_PATH;
  if (root !== undefined && root !== "" && existsSync(root)) {
    const candidates = readdirSync(root)
      .filter((name) => /^chromium-\d+$/.test(name))
      .sort((a, b) => Number(b.slice("chromium-".length)) - Number(a.slice("chromium-".length)));
    for (const name of candidates) {
      for (const layout of ["chrome-linux/chrome", "chrome-linux64/chrome"]) {
        const candidate = join(root, name, layout);
        if (existsSync(candidate)) {
          return {
            executablePath: candidate,
            source: `PLAYWRIGHT_BROWSERS_PATH scan (${name}; playwright-core wants ` +
              `${fromPlaywright === undefined ? "unknown" : fromPlaywright.split("/").slice(-3)[0]})`,
          };
        }
        tried.push(candidate);
      }
    }
  } else {
    tried.push(`PLAYWRIGHT_BROWSERS_PATH=${root ?? "(unset)"} — not a directory`);
  }

  throw new Error(
    `no Chromium binary found, so the browser accessibility gate cannot run. It does ` +
      `NOT skip: a missing browser reported as a pass is a gate that checks nothing.\n` +
      `Looked in:\n${tried.map((t) => `  - ${t}`).join("\n")}\n` +
      `Fix: run \`pnpm -C apps/web exec playwright-core install chromium\` (this is what ` +
      `.github/workflows/ci.yml does), or set CALEVATE_A11Y_CHROMIUM to an existing ` +
      `chrome binary. PLAYWRIGHT_BROWSERS_PATH=${root ?? "(unset)"}.`,
  );
}

// ---------------------------------------------------------------------------
// The stub API
// ---------------------------------------------------------------------------

/**
 * `GET /v1/public/rate-card`, and nothing else.
 *
 * `/pricing` and `/roi` are async server components that await the public rate card
 * (D-545): nothing on either page is a number typed into the bundle. Without an API they
 * render the honest "could not be loaded" state — a real screen, but not the one with
 * six pack rows and two voice tiers on it, which is where a contrast defect would live.
 * Scanning the degraded state and calling the page covered is the same vacuity
 * `assertScreenRendered` exists to stop in the jsdom sweep.
 *
 * So the harness serves the SAME fixture the jsdom suites use
 * (`tests/fixtures/rateCard.ts`, held to the generated wire type by `satisfies`), which
 * means one body to update when the card reshapes rather than two that drift.
 *
 * It is not a mock of the API. It answers one path and 404s everything else, and every
 * unexpected path is recorded and printed, so a page that grows a second server-side
 * fetch shows up as a named gap instead of a silently degraded render.
 */
export interface StubApi {
  port: number;
  unexpected: string[];
  close: () => Promise<void>;
}

export async function startStubApi(): Promise<StubApi> {
  const unexpected: string[] = [];
  const body = JSON.stringify(RATE_CARD);
  const server: Server = createServer((req, res) => {
    const url = req.url ?? "";
    if (url.split("?")[0] === "/v1/public/rate-card") {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(body);
      return;
    }
    unexpected.push(`${req.method ?? "?"} ${url}`);
    res.writeHead(404, { "content-type": "application/problem+json" });
    res.end(JSON.stringify({ title: "not stubbed", detail: url }));
  });
  await new Promise<void>((ok) => server.listen(0, "127.0.0.1", ok));
  const port = (server.address() as AddressInfo).port;
  return {
    port,
    unexpected,
    close: () => new Promise<void>((ok) => server.close(() => ok())),
  };
}

// ---------------------------------------------------------------------------
// The web server
// ---------------------------------------------------------------------------

export type ServerMode = "dev" | "build";

export interface WebServer {
  baseUrl: string;
  mode: ServerMode;
  /** Wall-clock spent getting to the first 200, in ms — printed in the summary. */
  startupMs: number;
  close: () => Promise<void>;
}

/** A port nobody is listening on right now. */
async function freePort(): Promise<number> {
  const probe = createProbe();
  await new Promise<void>((ok) => probe.listen(0, "127.0.0.1", ok));
  const port = (probe.address() as AddressInfo).port;
  await new Promise<void>((ok) => probe.close(() => ok()));
  return port;
}

function nextBin(): string {
  const bin = join(WEB_ROOT, "node_modules", ".bin", "next");
  if (!existsSync(bin)) {
    throw new Error(
      `${bin} does not exist — run \`pnpm install\` in the repo root. The browser ` +
        `accessibility gate needs the app's own Next binary; it does not shell out to a ` +
        `package manager, so that a missing install fails here rather than inside a ` +
        `subprocess whose output nobody reads.`,
    );
  }
  return bin;
}

/** Everything the child printed, kept so a startup failure can show its own reason. */
function tap(child: TappedChild, sink: string[]): void {
  const push = (chunk: Buffer): void => {
    sink.push(chunk.toString("utf8"));
    // Bounded: a compile loop can print megabytes and only the tail is ever read.
    if (sink.length > 400) sink.splice(0, sink.length - 400);
  };
  child.stdout.on("data", push);
  child.stderr.on("data", push);
}

async function waitForServer(
  baseUrl: string,
  child: TappedChild,
  output: string[],
  budgetMs: number,
  what: string,
): Promise<void> {
  const deadline = Date.now() + budgetMs;
  let lastError = "no request made yet";
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(
        `${what} exited with code ${child.exitCode} before answering a request. Its ` +
          `output:\n${output.join("").slice(-4000)}`,
      );
    }
    try {
      const response = await fetch(baseUrl + "/", { redirect: "manual" });
      // Any answer at all means the listener is up; the per-page status check below is
      // what holds each route to 200.
      if (response.status > 0) return;
    } catch (error) {
      lastError = String(error);
    }
    await new Promise((ok) => setTimeout(ok, 250));
  }
  throw new Error(
    `${what} did not answer on ${baseUrl} within ${budgetMs}ms (last: ${lastError}). ` +
      `This gate FAILS on a dead server rather than skipping — a scan of zero pages is ` +
      `not a pass. Its output:\n${output.join("").slice(-4000)}`,
  );
}

/**
 * A child with no stdin and both output streams piped.
 *
 * Spelled out rather than `ChildProcessWithoutNullStreams`, which is the type for
 * `stdio: "pipe"` on all three and would be a LIE here: stdin is `"ignore"`, so it is
 * `null`. Casting past that mismatch is what `next build`'s type check caught, and it
 * would have made `child.stdin` a non-null `Writable` that is actually null.
 */
type TappedChild = ChildProcessByStdio<null, Readable, Readable>;

function run(bin: string, args: string[], env: NodeJS.ProcessEnv): TappedChild {
  return spawn(bin, args, {
    cwd: WEB_ROOT,
    env: { ...process.env, ...env },
    stdio: ["ignore", "pipe", "pipe"],
  });
}

/**
 * Serve the app, in the mode asked for, pointed at the stub API.
 *
 * ## `next dev` and not `next build && next start`, measured rather than assumed
 *
 * `make web-check`'s docstring already argues that `next build` belongs in CI and not in
 * the dev loop: it is the slowest check there and it catches a different class of thing
 * (route and bundle validity). That argument applies here with more force, because this
 * gate has to pay for it on EVERY run.
 *
 * The question a measurement had to answer is whether dev-mode CSS is faithful enough for
 * a contrast verdict. It is, and not by assumption: Tailwind v4 emits the same computed
 * colours in both modes (the difference between dev and build is minification, chunking
 * and route pre-rendering, none of which is a colour), and the same scan was run both
 * ways over all 13 pages x 2 viewports x 2 palettes and produced IDENTICAL violation
 * counts and identical node targets. The measurement is in the report that added this
 * file; re-run it with `CALEVATE_A11Y_SERVER=build` and compare.
 *
 * So dev is the default, and build stays available behind the env var for the day someone
 * doubts that equivalence. The cost difference is not marginal: a production build of
 * this app is minutes, and `web-check` is a three-minute target.
 *
 * `NEXT_PUBLIC_API_BASE_URL` is passed to BOTH the build and the server because
 * `NEXT_PUBLIC_` values are inlined at build time — setting it only on `next start` would
 * leave a build-mode run fetching `localhost:8000` and quietly rendering the degraded
 * pricing page.
 */
export async function startWebServer(mode: ServerMode, apiPort: number): Promise<WebServer> {
  const bin = nextBin();
  const port = await freePort();
  const baseUrl = `http://127.0.0.1:${port}`;
  const env: NodeJS.ProcessEnv = {
    NEXT_PUBLIC_API_BASE_URL: `http://127.0.0.1:${apiPort}`,
    NEXT_TELEMETRY_DISABLED: "1",
    NODE_ENV: mode === "dev" ? "development" : "production",
  };
  const started = Date.now();
  const output: string[] = [];

  if (mode === "build") {
    const build = run(bin, ["build"], { ...env, NODE_ENV: "production" });
    tap(build, output);
    const code = await new Promise<number>((ok) => build.on("exit", (c) => ok(c ?? 1)));
    if (code !== 0) {
      throw new Error(`\`next build\` failed (${code}):\n${output.join("").slice(-4000)}`);
    }
  }

  const child = run(bin, [mode === "dev" ? "dev" : "start", "--port", String(port)], env);
  tap(child, output);
  await waitForServer(baseUrl, child, output, 240_000, `\`next ${mode}\``);

  return {
    baseUrl,
    mode,
    startupMs: Date.now() - started,
    close: async () => {
      child.kill("SIGTERM");
      await new Promise<void>((ok) => {
        const timer = setTimeout(() => {
          child.kill("SIGKILL");
          ok();
        }, 5000);
        child.on("exit", () => {
          clearTimeout(timer);
          ok();
        });
      });
    },
  };
}

// ---------------------------------------------------------------------------
// The scan
// ---------------------------------------------------------------------------

export interface ViolationNode {
  target: string;
  html: string;
  /** axe's own per-check messages — this is where the measured contrast ratio is. */
  messages: string[];
}

export interface Violation {
  id: string;
  impact: string;
  help: string;
  helpUrl: string;
  nodes: ViolationNode[];
}

export interface PageScan {
  path: string;
  viewport: string;
  palette: Palette;
  status: number;
  /** The tags axe reports it was RUN with, read back off the results. */
  runOnly: string[];
  /** Every rule id that produced a result of any kind — pass, fail, incomplete or n/a. */
  evaluatedRules: string[];
  violations: Violation[];
}

const AXE_SOURCE = readFileSync(require_.resolve("axe-core/axe.min.js"), "utf8");

/**
 * Scan one path at one viewport, in BOTH palettes, on a single page load.
 *
 * The palettes share one navigation deliberately: switching palette is adding a class to
 * `<html>`, which re-resolves the CSS variables without a reload, so a second `goto` would
 * buy nothing and double the slowest part of the run. It also guarantees the two verdicts
 * are about the same rendered DOM rather than two renders that could differ.
 *
 * Throws on a route that does not answer 200.
 */
export async function scanTarget(
  browser: Browser,
  baseUrl: string,
  target: ScanTarget,
  viewport: (typeof VIEWPORTS)[number],
): Promise<PageScan[]> {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    // Motion is not the subject here, and an animating hero makes the scan
    // non-deterministic. `prefers-reduced-motion` is also what a user with vestibular
    // sensitivity sends, so this is the more conservative render, not a convenience.
    reducedMotion: "reduce",
  });
  try {
    const page = await context.newPage();
    await page.addInitScript({ content: AXE_SOURCE });
    const response = await page.goto(baseUrl + target.path, {
      waitUntil: "networkidle",
      timeout: 120_000,
    });
    const status = response?.status() ?? 0;
    if (status !== 200) {
      throw new Error(
        `${target.path} answered ${status}, not 200 (${target.why}). A page the gate ` +
          `cannot load is a FAILURE, not a page quietly dropped from the scan — that is ` +
          `how a coverage list becomes decorative.`,
      );
    }

    const scans: PageScan[] = [];
    for (const palette of PALETTES) {
      if (palette === "dark") {
        // On <html>, because `@custom-variant dark (&:is(.dark *))` needs an ancestor.
        await page.evaluate(() => document.documentElement.classList.add("dark"));
        // One frame for the CSS variables to resolve, plus room for any transition on
        // the tokens to settle before colours are sampled.
        await page.waitForTimeout(400);
      }
      const result = await runAxe(page);
      scans.push({
        path: target.path,
        viewport: viewport.name,
        palette,
        status,
        runOnly: result.runOnly,
        evaluatedRules: result.evaluatedRules,
        violations: result.violations,
      });
    }
    return scans;
  } finally {
    await context.close();
  }
}

/** axe-core, in the page, with the declared tag set — and the raw results narrowed. */
async function runAxe(page: Page): Promise<Omit<PageScan, "path" | "viewport" | "palette" | "status">> {
  return page.evaluate(async (tags: string[]) => {
    const runner = (window as unknown as { axe?: { run: (c: Document, o: unknown) => Promise<unknown> } })
      .axe;
    if (runner === undefined) throw new Error("axe-core did not load into the page");
    const raw = (await runner.run(document, { runOnly: { type: "tag", values: tags } })) as {
      toolOptions?: { runOnly?: { values?: string[] } };
      violations: unknown[];
      passes: unknown[];
      incomplete: unknown[];
      inapplicable: unknown[];
    };
    const idsOf = (list: unknown[]): string[] => list.map((r) => (r as { id: string }).id);
    return {
      runOnly: raw.toolOptions?.runOnly?.values ?? [],
      evaluatedRules: [
        ...idsOf(raw.violations),
        ...idsOf(raw.passes),
        ...idsOf(raw.incomplete),
        ...idsOf(raw.inapplicable),
      ],
      violations: (
        raw.violations as {
          id: string;
          impact: string | null;
          help: string;
          helpUrl: string;
          nodes: {
            target: unknown[];
            html: string;
            any: { message: string }[];
            all: { message: string }[];
          }[];
        }[]
      ).map((v) => ({
        id: v.id,
        impact: v.impact ?? "unknown",
        help: v.help,
        helpUrl: v.helpUrl,
        nodes: v.nodes.map((n) => ({
          target: n.target.map(String).join(" "),
          html: n.html.slice(0, 300),
          messages: [...n.any, ...n.all].map((c) => c.message),
        })),
      })),
    };
  }, [...AXE_TAGS]);
}

/**
 * Every same-origin link the SERVED home page offers, so the target list cannot fall
 * behind the navigation.
 *
 * The failure this prevents is the one every hand-written sweep has: a new nav route
 * ships, nobody adds it here, and the gate goes on reporting green over a shrinking
 * fraction of the site. Reading the links out of the rendered document rather than out of
 * `NAV_ROUTES` also catches a route added to the footer, or to a card in the body.
 */
export async function unlistedPublicRoutes(browser: Browser, baseUrl: string): Promise<string[]> {
  const context = await browser.newContext();
  try {
    const page = await context.newPage();
    await page.goto(baseUrl + "/", { waitUntil: "networkidle", timeout: 120_000 });
    const hrefs = await page.evaluate(() =>
      Array.from(document.querySelectorAll("a[href]")).map((a) => a.getAttribute("href") ?? ""),
    );
    const listed = new Set(SCAN_TARGETS.map((t) => t.path));
    const unlisted = new Set<string>();
    for (const raw of hrefs) {
      const path = raw.split("#")[0].split("?")[0].replace(/(.)\/$/, "$1");
      if (!path.startsWith("/")) continue;
      if (listed.has(path)) continue;
      if (NOT_A_PUBLIC_PAGE.includes(path)) continue;
      if (COVERED_BY_REPRESENTATIVE.some((prefix) => path.startsWith(prefix))) continue;
      unlisted.add(path);
    }
    return [...unlisted].sort();
  } finally {
    await context.close();
  }
}

/** Format violations the way a person fixing them needs to read them. */
export function formatScan(scan: PageScan): string {
  return scan.violations
    .map(
      (v) =>
        `  [${v.impact}] ${v.id} — ${v.help}\n    ${v.helpUrl}\n` +
        v.nodes
          .map((n) => `    ${n.target}\n      ${n.html}\n      ${n.messages.join("\n      ")}`)
          .join("\n"),
    )
    .join("\n");
}

export async function launchBrowser(): Promise<{ browser: Browser; source: string; path: string }> {
  const { executablePath, source } = resolveChromium();
  const browser = await chromium.launch({
    executablePath,
    // The container this runs in has no user namespaces for Chromium's zygote sandbox,
    // and CI runners are the same. The pages are ours, served from loopback, from a
    // fixture — there is no untrusted content in this browser.
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  return { browser, source, path: executablePath };
}
