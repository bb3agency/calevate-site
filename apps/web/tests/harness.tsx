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
      // `Object.hasOwn`, not `path in routes`: `in` walks the prototype chain, so a
      // path of "/constructor" would resolve to a function and the stub would answer a
      // request it was never given. The same defect this suite exists to catch.
      if (!Object.hasOwn(routes, path)) {
        throw new Error(
          `test stub has no route for ${path} — add it to the routes table, ` +
            `or the screen under test is calling an endpoint nobody expected`,
        );
      }
      return new Response(JSON.stringify(routes[path]), {
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
