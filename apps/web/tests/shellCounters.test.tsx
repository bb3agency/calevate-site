import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";

import AdminLayout from "@/app/admin/layout";
import ClientRealmLayout from "@/app/c/[slug]/layout";
import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import { HOLDS_PATH } from "@/lib/api/holds";
import { KYC_REVIEWS_PATH } from "@/lib/api/kycReview";

import {
  noContent,
  problem,
  renderAdminPage,
  stillLoading,
  stubApi,
  type ApiCall,
  type Routes,
} from "./harness";
import { CLIENT_SHELL_ROUTES, LIVE_CALLS_PATH, NOTIFICATIONS_PATH } from "./fixtures/sharedReads";

/**
 * The two counters in the shell chrome — the operator's hold queue and the client's
 * attention bell — and the §52 defect they shared.
 *
 * Both were `count = q.data?.… ?? 0`, and both then rendered `{count > 0 && <badge/>}`.
 * The comment above each one argued the case for never printing a literal `0`, and both
 * were right about that and stopped one step short: coalescing to zero makes a FAILED
 * read pixel-identical to an all-clear. "Nobody is waiting" is the single claim a queue
 * badge must never make from a request that did not land, and shell chrome is where a
 * claim is trusted most — it is on every screen, it is never reloaded on its own, and
 * nobody goes looking for a notice behind a bell that looks calm.
 *
 * These are shells, not screens, so the refusal is a MARK and an accessible name rather
 * than a `ProblemNotice`: there is no room for a paragraph in a 36px button and no
 * sensible place to put one. What matters is that the three states — quiet, waiting, and
 * we-could-not-read — are three different things to a sighted reader and to a screen
 * reader, which is what the assertions below are.
 *
 * Every test asserts the REPLACEMENT is present, never only that the badge is gone: an
 * unrendered header satisfies "no badge" and is its own defect.
 *
 * The failures below are `retryable: false` ON PURPOSE. Both shells mount the app's own
 * `Providers`, whose query policy retries a retryable problem twice with backoff — so a
 * `retryable: true` fixture leaves `error` null for seconds and a `findBy*` times out
 * against a screen that is still, correctly, trying. The branch under test is the settled
 * one; asserting it through the retry budget would be testing the clock.
 */

const ADMIN_ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000a1",
  role: "superadmin",
  permissions: ["admin:tenants", "org:read", "ops:manage"],
};

function adminRoutes(over: Partial<Routes> = {}): Routes {
  return {
    [ADMIN_ME_PATH]: ADMIN_ME,
    [HOLDS_PATH]: [],
    [KYC_REVIEWS_PATH]: [],
    "/v1/admin/tenants": [],
    ...over,
  };
}

function renderAdminShell(routes: Partial<Routes> = {}) {
  return renderAdminPage(
    <AdminLayout>
      <p>screen</p>
    </AdminLayout>,
    adminRoutes(routes),
  );
}

/**
 * The client shell mounts its OWN `ClientRealmProvider`, so `renderClientPage` would nest
 * a second one — a composition the app never has. Same reasoning as navDrawer.test.tsx.
 */
async function renderClientShell(
  routes: Record<string, unknown>,
): Promise<ApiCall[]> {
  const calls = stubApi({
    ...CLIENT_SHELL_ROUTES,
    "/v1/me": { organization: { name: "Acme" }, role: "owner" },
    ...routes,
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  await act(async () => {
    const ui: ReactElement = (
      <QueryClientProvider client={client}>
        <ClientRealmLayout params={Promise.resolve({ slug: "acme" })}>
          <p>screen</p>
        </ClientRealmLayout>
      </QueryClientProvider>
    );
    render(ui);
  });
  return calls;
}

/** A hold, in the shape `/v1/admin/compliance/holds` sends. */
const HELD = [
  {
    tenant_id: "t1",
    tenant_name: "Sri Traders",
    slug: "sri",
    rules: ["kyc_pending"],
  },
  {
    tenant_id: "t2",
    tenant_name: "Kiran Clinic",
    slug: "kiran",
    rules: ["dlt_pe"],
  },
];

describe("the admin shell's bell (held accounts and identity checks)", () => {
  it("says the queue could not be read, instead of looking like an all-clear", async () => {
    renderAdminShell({
      [HOLDS_PATH]: problem(503, { title: "Service unavailable" }),
    });

    // The mark is PRESENT and named. Its absence — the old `?? 0` behaviour — is exactly
    // what a healthy, empty queue looks like, so "no badge" proves nothing either way.
    const link = await screen.findByLabelText(
      "Waiting on us: we could not read every queue",
    );
    expect(link.querySelector("[data-testid=attention-unchecked]")).toBeTruthy();
  });

  it("counts what the server sent when the server answered", async () => {
    renderAdminShell({ [HOLDS_PATH]: HELD });

    const link = await screen.findByLabelText("Waiting on us: 2");
    expect(link.textContent).toContain("2");
  });

  it("shows no badge, and no mark, on a real all-clear", async () => {
    // The premise of both tests above: three states, three renderings.
    renderAdminShell();

    const link = await screen.findByLabelText("Waiting on us");
    expect(link.textContent).not.toContain("?");
  });

  it("adds the identity checks waiting for a reviewer to the held accounts", async () => {
    renderAdminShell({
      [HOLDS_PATH]: HELD,
      [KYC_REVIEWS_PATH]: [{ tenant_id: "t3", name: "Vennela Nest", submitted_at: "2026-10-22T05:00:00Z" }],
    });

    const button = await screen.findByLabelText("Waiting on us: 3");
    expect(button.textContent).toContain("3");
    act(() => button.click());
    expect(await screen.findByText("Identity checks to review")).toBeTruthy();
    expect(screen.getByText("1 waiting")).toBeTruthy();
    expect(screen.getByText("2 waiting")).toBeTruthy();
  });

  it("never asks for identity checks an operator may not review", async () => {
    // No stub for the review queue: a request for it would fail the read and mark "?".
    renderAdminPage(
      <AdminLayout>
        <p>screen</p>
      </AdminLayout>,
      {
        [ADMIN_ME_PATH]: { ...ADMIN_ME, role: "support", permissions: ["org:read"] },
        [HOLDS_PATH]: HELD,
        "/v1/admin/tenants": [],
      },
    );

    const button = await screen.findByLabelText("Waiting on us: 2");
    act(() => button.click());
    expect(await screen.findByText("2 waiting")).toBeTruthy();
    expect(screen.queryByText("Identity checks to review")).toBeNull();
  });

  it("shows no count, and no mark, while the queue is still being read", async () => {
    renderAdminShell({ [HOLDS_PATH]: stillLoading() });

    const link = await screen.findByLabelText("Waiting on us");
    expect(link.textContent).not.toContain("?");
    expect(link.textContent).not.toContain("0");
  });
});

/** One unread attention item and one read announcement, as `/v1/notifications` sends them. */
const FEED = {
  items: [
    {
      id: "lead-1",
      source: "attention",
      kind: "lead_hot",
      title: "Ravi is interested",
      detail: "Asked for a call back",
      href: "/leads/lead-1",
      link_label: null,
      occurred_at: "2026-10-24T05:00:00Z",
      tone: "info",
      unread: true,
    },
    {
      id: "ann-1",
      source: "announcement",
      kind: "announcement",
      title: "New voices are ready",
      detail: null,
      href: "https://calevate.tech/changes",
      link_label: "See what changed",
      occurred_at: "2026-10-23T05:00:00Z",
      tone: "success",
      unread: false,
    },
  ],
  unread: 3,
  attention_total: 4,
  seen_through: "2026-10-23T06:00:00Z",
};

describe("the client shell's notification bell", () => {
  it("says the feed could not be read, instead of looking like an all-clear", async () => {
    await renderClientShell({
      [NOTIFICATIONS_PATH]: problem(503, { title: "Service unavailable" }),
    });

    const link = await screen.findByLabelText(
      "Notifications: we couldn't check for new items. Open to try again.",
    );
    expect(link.getAttribute("title")).toContain("couldn't check");
    expect(link.querySelector("[data-testid=attention-unchecked]")).toBeTruthy();
  });

  it("badges the server's unread count, not the number of rows", async () => {
    await renderClientShell({ [NOTIFICATIONS_PATH]: FEED });

    const link = await screen.findByLabelText("Notifications: 3 unread");
    expect(link.textContent).toContain("3");
  });

  it("shows no badge, and no mark, on a real all-clear", async () => {
    await renderClientShell({});

    const link = await screen.findByRole("button", { name: "Notifications" });
    expect(link.textContent).not.toContain("?");
    expect(link.querySelector("[data-testid=attention-unchecked]")).toBeNull();
  });

  it("marks what was shown as seen when the panel closes, through the newest item", async () => {
    const calls = await renderClientShell({
      [NOTIFICATIONS_PATH]: FEED,
      "POST /v1/notifications/seen": { seen_through: "2026-10-24T05:00:00Z" },
    });
    const bell = await screen.findByLabelText("Notifications: 3 unread");
    await act(async () => fireEvent.click(bell));
    // An unread row says so to a screen reader; a console path stays inside the account.
    const panel = document.querySelector("[role=dialog]") as HTMLElement;
    const row = await within(panel).findByRole("link", { name: /New: Ravi is interested/ });
    expect(row.getAttribute("href")).toBe("/c/acme/leads/lead-1");
    expect(within(panel).getByRole("link", { name: /New voices are ready/ }).getAttribute("href")).toBe(
      "https://calevate.tech/changes",
    );
    expect(calls.some((call) => call.path === "/v1/notifications/seen")).toBe(false);
    await act(async () => fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" }));
    await waitFor(() =>
      expect(JSON.parse(calls.find((call) => call.path === "/v1/notifications/seen")?.body ?? "null")).toEqual({
        through: "2026-10-24T05:00:00Z",
      }),
    );
  });
});

describe("the client shell's announcement strip", () => {
  const ANNOUNCED = {
    items: [
      {
        id: "a1",
        message: "Calls may be slow tonight from 11pm",
        tone: "critical",
        link_url: "/billing",
        link_label: "Check your credit",
        starts_at: "2026-10-24T00:00:00Z",
        ends_at: null,
      },
      {
        id: "a2",
        message: "A quieter note",
        tone: "info",
        link_url: null,
        link_label: null,
        starts_at: "2026-10-24T00:00:00Z",
        ends_at: null,
      },
    ],
  };

  it("shows the most urgent one, with its link inside the account, and dismisses it", async () => {
    const calls = await renderClientShell({
      "/v1/announcements": ANNOUNCED,
      "POST /v1/announcements/a1/dismiss": noContent(),
    });
    const strip = (await screen.findByText("Calls may be slow tonight from 11pm")).closest("[role=alert]") as HTMLElement;
    expect(strip.textContent).toContain("Calls may be slow tonight from 11pm");
    expect(strip.textContent).not.toContain("A quieter note");
    expect(within(strip).getByRole("link", { name: "Check your credit" }).getAttribute("href")).toBe(
      "/c/acme/billing",
    );
    await act(async () =>
      fireEvent.click(within(strip).getByRole("button", { name: "Dismiss this announcement" })),
    );
    await waitFor(() =>
      expect(calls.some((call) => call.method === "POST" && call.path === "/v1/announcements/a1/dismiss")).toBe(true),
    );
  });

  it("renders nothing when nothing is announced", async () => {
    await renderClientShell({});
    await screen.findByRole("button", { name: "Notifications" });
    expect(screen.queryByRole("button", { name: "Dismiss this announcement" })).toBeNull();
  });
});

describe("the client shell's identity block", () => {
  /*
   * The same rule as the bell above, applied to the one place in the shell that says
   * WHOSE ACCOUNT THIS IS. It rendered `—` for the organisation and `—` for the role off
   * `me.data?.… ?? "—"` with `me.error` unread: an honest absence marker for a second and
   * a permanent, unexplained one after that, on a console an operator can also be
   * impersonating into. Two dashes are not a refusal.
   */
  it("names the failure instead of leaving two permanent dashes", async () => {
    await renderClientShell({
      "/v1/me": problem(503, {
        title: "Service unavailable",
        retryable: false,
      }),
      "/v1/attention": { total: 0, items: [] },
    });

    expect(await screen.findByText("Account not read")).toBeTruthy();
    expect(
      screen.getByText("Reload to see whose account this is"),
    ).toBeTruthy();
  });

  it("says whose account it is when the server answered", async () => {
    await renderClientShell({ "/v1/attention": { total: 0, items: [] } });

    expect(await screen.findByText("Acme")).toBeTruthy();
    expect(screen.queryByText("Account not read")).toBeNull();
  });
});

/**
 * THE LIVE-CALLS PILL — how many calls are in progress, from the same 20-second call poll
 * as every other call list. It only ever asserts that calls ARE live: nothing while the
 * read is out, nothing on zero, nothing on a failure.
 */
describe("the client shell's live-calls pill", () => {
  const LIVE = {
    id: "c-live",
    agent_id: "a1",
    agent_name: "Reception",
    direction: "inbound",
    status: "in_progress",
    caller_e164: "+919876543210",
    started_at: "2026-10-01T04:30:00Z",
    duration_s: null,
    outcome_tag: null,
    sentiment: null,
    summary: null,
    lead_id: null,
  };

  it("names how many calls are live and opens the log filtered to them", async () => {
    await renderClientShell({
      "/v1/attention": { total: 0, items: [] },
      [LIVE_CALLS_PATH]: [LIVE, { ...LIVE, id: "c-live-2" }],
    });
    const pill = await screen.findByRole("link", { name: "2 calls in progress now" });
    expect(pill.getAttribute("href")).toBe("/c/acme/calls?status=in_progress");
    // The number is the count, never a caller's digits.
    expect(pill.getAttribute("href")).not.toMatch(/\d{10}/);
    expect(pill.textContent).toBe("Live: 2 calls");
    // On a phone only the dot and the count are drawn, so the page title keeps its room;
    // the words stay for a screen reader.
    const words = [...pill.querySelectorAll("span")].filter((s) => /^ ?(Live:|calls)/.test(s.textContent?.trim() ?? "") && s.children.length === 0);
    expect(words.map((s) => s.className)).toEqual([expect.stringContaining("max-sm:sr-only"), expect.stringContaining("max-sm:sr-only")]);
  });

  it("opens the one live call itself, where the live panel shows who is speaking", async () => {
    await renderClientShell({
      "/v1/attention": { total: 0, items: [] },
      [LIVE_CALLS_PATH]: [LIVE],
    });
    const pill = await screen.findByRole("link", { name: "1 call in progress now" });
    expect(pill.getAttribute("href")).toBe("/c/acme/calls/c-live");
    expect(pill.textContent).toBe("Live: 1 call");
  });

  it("renders nothing when no call is live", async () => {
    await renderClientShell({ "/v1/attention": { total: 0, items: [] } });
    await screen.findByText("Acme");
    expect(screen.queryByRole("link", { name: /in progress now/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /Live calls/ })).toBeNull();
  });

  it("says it could not check, rather than going quiet, when the read failed", async () => {
    await renderClientShell({
      "/v1/attention": { total: 0, items: [] },
      [LIVE_CALLS_PATH]: problem(503, { title: "Service unavailable" }),
    });
    expect(
      await screen.findByRole("link", { name: /^Live calls: couldn't check/ }),
    ).toBeTruthy();
    expect(screen.getByText("couldn't check", { exact: false })).toBeTruthy();
  });
});
