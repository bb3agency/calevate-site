import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";
import { expect, vi } from "vitest";

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

/** One request the screen made, as the network saw it. */
export interface ApiCall {
  url: string;
  path: string;
  method: string;
  body: string | null;
  headers: Record<string, string>;
}

export function stubApi(routes: Routes): ApiCall[] {
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
        throw new Error(
          `test stub has no route for ${scoped} — add it to the routes table, ` +
            `or the screen under test is calling an endpoint nobody expected`,
        );
      }
      const answer = routes[key];
      if (answer instanceof ProblemResponse) {
        return new Response(JSON.stringify(answer.body), {
          status: answer.status,
          headers: { "content-type": "application/problem+json" },
        });
      }
      return new Response(JSON.stringify(answer), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
  return calls;
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
