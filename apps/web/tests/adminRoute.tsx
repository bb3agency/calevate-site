import { act } from "@testing-library/react";
import { Suspense, type ReactElement } from "react";

import { renderAdminPage, type ClientPageRender, type Routes } from "./harness";

/**
 * `renderAdminPage`, for the admin screens that take a `params` PROMISE.
 *
 * `harness.tsx` says out loud that it renders admin screens synchronously because "there
 * is no Suspense boundary here and no `use(params)` promise on the screens this renders".
 * Every screen under `/admin/tenants/[tenantId]` breaks that premise: Next 15 hands a
 * page its route params as a promise, and React 19's `use()` SUSPENDS on it — even one
 * already resolved, because the resumption is a microtask. Without a boundary that throw
 * escapes the renderer and the test fails with a promise instead of an assertion.
 *
 * So the boundary lives here rather than in the harness: the harness is shared with the
 * client realm and with the admin screens that take no params, and widening it would make
 * every one of those tests render through a Suspense fallback they do not have in
 * production. This wrapper is the truthful shape for THESE routes and nothing else — the
 * real `app/admin/layout.tsx` is a client component tree that resolves the same way.
 *
 * `fallback={null}` on purpose: a fallback with content would be indistinguishable, in an
 * assertion on `container.textContent`, from the screen's own loading state — and several
 * tests below are specifically about which of those is on screen.
 *
 * ASYNC, for the reason `renderClientPage` is: a synchronous `render` returns with the
 * boundary still showing its fallback, and React's resumption then happens outside `act`,
 * where the act-environment queue never flushes it. That does not fail as an assertion —
 * it fails as an empty container and a warning, on EVERY test in the file at once, which
 * is a diagnosis nobody should have to make twice. Awaiting an async `act` around the
 * render lets the params promise settle before the test looks.
 */
export async function renderAdminRoute(
  ui: ReactElement,
  routes: Routes,
): Promise<ClientPageRender> {
  let result!: ClientPageRender;
  await act(async () => {
    result = renderAdminPage(<Suspense fallback={null}>{ui}</Suspense>, routes);
  });
  return result;
}

/** The route params a page reads with `use()`, in the shape Next 15 hands them over. */
export function routeParams<T extends Record<string, string>>(params: T): Promise<T> {
  return Promise.resolve(params);
}
