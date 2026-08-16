import { QueryClient, QueryClientProvider, onlineManager } from "@tanstack/react-query";
import { act, render, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";
import { expect, vi } from "vitest";

import { clearImpersonationGrants } from "@/lib/api/admin";
import { API_BASE } from "@/lib/api/client";
import { ClientRealmProvider } from "@/lib/api/session";

/**
 * Render a `/c/[slug]` screen the way the browser does — REAL provider, REAL session,
 * REAL `apiRequest`, with the network as the only thing replaced.
 *
 * The seam is `fetch`, deliberately. `client.ts` is the one place the app calls it, and
 * it is where the auth header, the org header and problem+json handling live; stubbing
 * the query hooks instead would skip all of that and test a mock's opinion of the API.
 * Stubbing `fetch` means a test that passes has exercised the whole path from the route
 * table to the sentence on screen.
 *
 * Routes are keyed by the path `apiRequest` is given, so they read as the API's own
 * paths. An unrouted request throws rather than 404s: an unstubbed endpoint is a hole
 * in the test's premise, and a test should say so instead of quietly rendering an error
 * state that happens to contain the string it was looking for.
 */
export type Routes = Record<string, unknown>;

/**
 * A route that answers with an RFC-9457 problem instead of a 200.
 *
 * Several screens carry a failure branch that is a DECISION, not a fallback — the hold
 * queue must refuse to report "nobody is waiting" when it could not read the list, and
 * the launch panel must not render an empty blocker list under a dead button. Those
 * branches are only reachable through a non-2xx, and a route table that can only answer
 * 200 cannot reach them. Returning a malformed 200 instead would exercise a crash rather
 * than the error path.
 *
 * The media type matters: `client.ts` parses `problem+json` to build its `ApiError`, so
 * anything else would test a different branch than production takes.
 */
export class ProblemResponse {
  constructor(
    readonly status: number,
    readonly body: Record<string, unknown>,
  ) {}
}

/** An RFC-9457 refusal, as `apiRequest` will see it. */
export function problem(status: number, body: Record<string, unknown> = {}): ProblemResponse {
  return new ProblemResponse(status, body);
}

/**
 * A route that never answers — the LOADING half of §52, which had no way to be reached.
 *
 * "Loading is a skeleton, failure is a refusal, and neither is a number, a state, or an
 * empty state" has three states in it and this table could only produce two: a 200 and a
 * `problem()`. Both SETTLE, so `isLoading` is false by the first assertion and a test
 * claiming to check the in-flight branch was really checking the settled one — the trick
 * of asserting before the first `await` works only while nothing on the screen suspends,
 * which stops being true the moment a route reads `use(params)` (see `adminRoute.tsx`).
 *
 * A pending fetch is the honest way to hold a query in `isLoading`, because it is what
 * the browser actually does. Nothing here resolves or rejects it: the promise is
 * abandoned when the test ends, which is also what a navigated-away-from page does.
 */
export class NeverAnswers {}

/** A route stuck in flight, for asserting the skeleton rather than the settled state. */
export function stillLoading(): NeverAnswers {
  return new NeverAnswers();
}

/**
 * The THIRD state §52 did not name: a query TanStack never started.
 *
 * `stillLoading()` above closed the in-flight gap and left this one, and the two are not
 * the same branch. With the default `networkMode: "online"` (which `providers.tsx` keeps),
 * query-core does not run a fetch it believes cannot succeed — `query.js` sets
 * `fetchStatus: canFetch(networkMode) ? "fetching" : "paused"`, and `canFetch("online")`
 * is `onlineManager.isOnline()`. A PAUSED query reports `isPending === true`,
 * `isFetching === false` and therefore **`isLoading === false`**, with `error === null`
 * and `data === undefined`.
 *
 * So a `isLoading ? <Skeleton/> : error ? <Refusal/> : …` ladder takes neither arm and
 * renders its data branch on nothing. `client.ts` calls a console tab open across a
 * dropped connection "the normal case, not an edge", and six screens stated an empty
 * state as a fact in it.
 *
 * This flips the REAL switch rather than mocking a hook, so what a test exercises is the
 * library's own pause, exactly as a lost connection produces it. `setup.ts` puts the
 * browser back online after every test — before which `cleanup()` has already unmounted,
 * so nothing resumes into a torn-down tree.
 */
export function browserOffline(): void {
  onlineManager.setOnline(false);
}

/** One request the screen made, as the network saw it. */
export interface ApiCall {
  url: string;
  path: string;
  method: string;
  body: string | null;
  headers: Record<string, string>;
}

/**
 * The D-22 view-as grant mint — answered by DEFAULT when a route table does not.
 *
 * `viewAsSession()` now mints a short-lived grant before it can read anything from a
 * client surface (lib/api/admin.ts), so every admin screen that reads through
 * impersonation makes this call. Answering it here rather than in ~10 route tables is
 * the same judgement `setup.ts` makes about `next/navigation`: it is infrastructure the
 * screen under test did not ask for, and repeating it would bury each test's actual
 * premise. A test that cares about the grant flow itself puts its own entry in the
 * table and that entry wins — `adminImpersonationGrant.test.tsx` does exactly that.
 *
 * A FALLBACK, NOT A MERGE, and the difference is not stylistic: `{ ...routes, ... }`
 * would have been the obvious way to seed it, and it EVALUATES GETTERS. Several suites
 * define a route as `get "PATCH /v1/leads/lead-1001"()` so one endpoint can answer
 * differently on a retry, and spreading froze the first answer forever — a test asserting
 * a recovery path silently stopped being able to recover. So the table is never copied.
 *
 * The expiry is far enough out that no test races the console's refresh margin.
 */
const GRANT_ROUTE = "POST /v1/admin/impersonation-grants";

function defaultGrant(): Record<string, unknown> {
  return {
    slug: "stub",
    grant: "stub-view-as-grant",
    expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
  };
}

export function stubApi(routes: Routes): ApiCall[] {
  // Grants are cached per slug in a module-level map, so without this a grant minted by
  // one test would be reused by the next — silently changing how many requests the next
  // test's screen makes, depending on file order. Cleared where the network is replaced,
  // because that is what the cache is a cache of.
  clearImpersonationGrants();
  const calls: ApiCall[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      const path = url.startsWith(API_BASE) ? url.slice(API_BASE.length) : url;
      calls.push({
        url,
        path,
        method: init?.method ?? "GET",
        body: typeof init?.body === "string" ? init.body : null,
        headers: (init?.headers ?? {}) as Record<string, string>,
      });
      // A route may be keyed by path alone, or by `"<METHOD> <path>"` when one path
      // answers differently per verb — `/v1/lead-sources` is a list on GET and a
      // creation on POST, and a path-only table would have to answer both with one
      // object that is honestly neither. The method-scoped key wins when present.
      const method = init?.method ?? "GET";
      const scoped = `${method} ${path}`;
      // `Object.hasOwn`, not `path in routes`: `in` walks the prototype chain, so a
      // path of "/constructor" would resolve to a function and the stub would answer a
      // request it was never given. The same defect this suite exists to catch.
      const key = Object.hasOwn(routes, scoped) ? scoped : path;
      if (!Object.hasOwn(routes, key)) {
        if (scoped === GRANT_ROUTE) return jsonResponse(defaultGrant());
        throw new Error(
          `test stub has no route for ${scoped} — add it to the routes table, ` +
            `or the screen under test is calling an endpoint nobody expected`,
        );
      }
      const answer = routes[key];
      if (answer instanceof NeverAnswers) return new Promise<Response>(() => {});
      if (answer instanceof ProblemResponse) {
        return new Response(JSON.stringify(answer.body), {
          status: answer.status,
          headers: { "content-type": "application/problem+json" },
        });
      }
      return jsonResponse(answer);
    }),
  );
  return calls;
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

export interface ClientPageRender extends RenderResult {
  /** Every request the screen made, in order — the seam hard rule 6 is asserted at. */
  calls: ApiCall[];
}

/**
 * Async because these screens SUSPEND on the first paint.
 *
 * `ClientRealmProvider` puts a Suspense boundary around `useSearchParams`, and a route
 * page reads its `params` promise with React 19's `use()`. A plain synchronous `render`
 * therefore returns with the fallback on screen and React's own resumption happening
 * outside `act` — which shows up as an empty container and a warning, not as a failure
 * anyone can read. Awaiting an async `act` lets the boundary resolve before the test
 * looks.
 */
export async function renderClientPage(
  ui: ReactElement,
  routes: Routes,
  slug = "acme",
): Promise<ClientPageRender> {
  const calls = stubApi(routes);
  const client = new QueryClient({
    // No retries: every route here answers 200 or throws, so a retry can only turn a
    // broken premise into a slow one.
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  let result!: RenderResult;
  await act(async () => {
    result = render(
      <QueryClientProvider client={client}>
        <ClientRealmProvider slug={slug}>{ui}</ClientRealmProvider>
      </QueryClientProvider>,
    );
  });
  return Object.assign(result, { calls });
}

/**
 * Render an `/admin` screen — no realm provider, because the admin realm has none.
 *
 * `lib/api/admin.ts` builds its own `adminSession()` per call rather than reading a
 * context, which is the separation CLAUDE.md requires between the two realms ("separate
 * route groups + separate Clerk apps — never share session logic"). Wrapping an admin
 * page in `ClientRealmProvider` would test a composition the app does not have, and
 * would quietly give the page an org slug it is never supposed to hold: these are
 * CROSS-tenant reads.
 *
 * Not async, unlike `renderClientPage`: there is no Suspense boundary here and no
 * `use(params)` promise on the screens this renders. `findBy*` still awaits the query.
 */
export function renderAdminPage(ui: ReactElement, routes: Routes): ClientPageRender {
  const calls = stubApi(routes);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const result = render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  return Object.assign(result, { calls });
}

/**
 * Assert a sentence appears EXACTLY once on screen.
 *
 * `getByText` already throws on a second match, but it throws with "found multiple
 * elements", which reads as a selector problem. Several assertions in this suite are
 * about duplication itself — a reviewer's note that must not be printed twice — so the
 * count is the subject and says so.
 */
export function expectTextCount(container: HTMLElement, needle: string, times: number): void {
  const matches = (container.textContent ?? "").split(needle).length - 1;
  expect(matches, `occurrences of ${JSON.stringify(needle)}`).toBe(times);
}
