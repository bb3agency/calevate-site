/**
 * The D-22 read-only marker, and the machinery it silently depended on.
 *
 * Both tests here exist because of ONE incident, found by driving a browser rather than
 * by reading code: an operator following "View as client" landed in a client's console
 * with no marker of any kind, every data screen stuck on skeletons forever, and a sidebar
 * identity block showing two em-dashes. The console was indistinguishable from that
 * client's own login except for a query string.
 *
 * The cause was a DEADLOCK between a module-level promise and the component tree.
 * Entering a client is a step-up action (D-210) and the grant is minted lazily, inside
 * the CLIENT shell. On a `step_up_required` refusal `admin.ts::mint` awaits
 * `requireStepUp`, whose promise only `<StepUpPrompt />` can settle — and that component
 * was mounted in `app/admin/layout.tsx` alone. `publish()` reached no listener, no dialog
 * appeared, nothing settled, and every request in the impersonated console awaited a
 * grant that would never arrive. TanStack held every query `pending`: `data` undefined,
 * `error` null, forever.
 *
 * So the marker's absence was a SYMPTOM, and it had its own defect underneath —
 * `ViewAsBanner` covered "impersonating" and "the read failed" and rendered nothing in
 * between. Two tests, because the two failures are independent: fixing the deadlock does
 * not give the banner a pending state, and giving it one does not unblock the grant.
 */

import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// The D-22 handoff, which the shared setup's stub cannot express: it returns an empty
// `URLSearchParams` for every test, and `?view=admin` is the whole subject here.
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("view=admin"),
  usePathname: () => "/c/acme",
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

import ClientRealmLayout from "@/app/c/[slug]/layout";
import { dismissStepUpPrompt, requireStepUp } from "@/lib/authn/stepUpPrompt";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { stillLoading, stubApi } from "./harness";

/** The reads the shell itself makes on mount, all parked in flight. */
const SHELL_IN_FLIGHT = {
  "GET /v1/me": stillLoading(),
  "GET /v1/attention": stillLoading(),
};

/** The same shell with the server confirming the impersonation, as it does in practice. */
const SHELL_IMPERSONATING = {
  "GET /v1/me": {
    organization: { id: "org_1", name: "Sunrise Dental Care", slug: "acme" },
    role: "owner",
    impersonating: true,
  },
  "GET /v1/attention": stillLoading(),
};

/**
 * The layout MOUNTED AS THE APP MOUNTS IT — its own `ClientRealmProvider` and no other.
 *
 * Deliberately not `renderClientPage`: that helper supplies a `ClientRealmProvider` of its
 * own, and this layout brings one, so the shell would mount twice and with it two
 * `<StepUpPrompt />`s over one module-level store. The duplicate is an artefact of the
 * harness rather than anything the app does, and a test that has to work around its own
 * scaffolding is measuring the scaffolding.
 */
async function mountShell(routes: Record<string, unknown> = SHELL_IN_FLIGHT) {
  const calls = stubApi(routes);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  await act(async () => {
    render(
      <QueryClientProvider client={client}>
        <ClientRealmLayout params={Promise.resolve({ slug: "acme" })}>{null}</ClientRealmLayout>
      </QueryClientProvider>,
    );
  });
  return calls;
}

// `requireStepUp` keeps its pending promise at MODULE level and `<StepUpPrompt />`
// subscribes to it, so a tree left mounted by one test renders the NEXT test's dialog too
// and `findByRole` then finds two. Unmounting and settling between cases keeps each one
// measuring its own shell rather than the sum of the file.
afterEach(() => {
  dismissStepUpPrompt();
  cleanup();
});

describe("the read-only marker while the server has not answered yet", () => {
  it("says an operator is looking, rather than showing nothing at all", async () => {
    await mountShell();

    // The MARKER, not the confirmed banner: `me` has not answered, so the amber
    // "Viewing as …" line — which quotes the server's own `impersonating` — must not
    // appear. What must appear is that this tab was opened as an operator, because the
    // alternative is an unmarked console sitting in someone else's account.
    expect(await screen.findByText(/opening as an operator/i)).toBeTruthy();
    expect(screen.queryByText(/^Viewing as /)).toBeNull();
  });
});

describe("the step-up prompt is reachable from inside an impersonated console", () => {
  it("renders a dialog when the grant mint asks for a second factor", async () => {
    await mountShell();

    // `requireStepUp` is what `admin.ts::mint` awaits on a `step_up_required` refusal.
    // Called directly rather than through a refused mint because the DEADLOCK is not in
    // the mint: it is that nothing in this tree was listening. A test that drove the
    // whole mint would hang here exactly as the browser did, and a hanging test reads as
    // a slow suite rather than as this defect.
    let settled = false;
    await act(async () => {
      void requireStepUp("Opening acme as an operator.").then(() => {
        settled = true;
      });
    });

    // The dialog EXISTS in this shell. Before the fix `publish()` reached no listener
    // here, so nothing rendered and the promise below could never be settled by anyone.
    expect(await screen.findByRole("alertdialog")).toBeTruthy();
    expect(settled, "the prompt must still be waiting on a person, not resolved").toBe(false);
  });
});

describe("leaving an impersonated console", () => {
  it("offers a way back to the admin console, in the banner that says you are in one", async () => {
    await mountShell(SHELL_IMPERSONATING);

    // The confirmed banner, so this is the state an operator actually sits in.
    expect(await screen.findByText(/^Viewing as Sunrise Dental Care/)).toBeTruthy();

    // THE EXIT. There was none: the only control that looked like one was "Sign out" at
    // the foot of the sidebar, which ends the ADMIN session and drops the operator at a
    // sign-in page — so the real way out was knowing to edit the URL. Asserted by ROLE
    // and name rather than by test id, because what matters is that a person can find and
    // press it.
    const exit = await screen.findByRole("button", { name: /exit and return to the admin console/i });
    expect(exit).toBeTruthy();
  });
});
