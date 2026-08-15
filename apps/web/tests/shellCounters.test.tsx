import { act, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";

import AdminLayout from "@/app/admin/layout";
import ClientRealmLayout from "@/app/c/[slug]/layout";
import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import { HOLDS_PATH } from "@/lib/api/holds";

import { problem, renderAdminPage, stillLoading, stubApi, type Routes } from "./harness";

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
} as AdminMe;

function adminRoutes(over: Partial<Routes> = {}): Routes {
  return {
    [ADMIN_ME_PATH]: ADMIN_ME,
    [HOLDS_PATH]: [],
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
async function renderClientShell(routes: Record<string, unknown>): Promise<void> {
  stubApi({ "/v1/me": { organization: { name: "Acme" }, role: "owner" }, ...routes });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
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
}

/** A hold, in the shape `/v1/admin/compliance/holds` sends. */
const HELD = [
  { tenant_id: "t1", tenant_name: "Sri Traders", slug: "sri", rules: ["kyc_pending"] },
  { tenant_id: "t2", tenant_name: "Kiran Clinic", slug: "kiran", rules: ["dlt_pe"] },
];

describe("the admin shell's hold-queue badge", () => {
  it("says the queue could not be read, instead of looking like an all-clear", async () => {
    renderAdminShell({
      [HOLDS_PATH]: problem(503, { title: "Service unavailable" }),
    });

    // The mark is PRESENT and named. Its absence — the old `?? 0` behaviour — is exactly
    // what a healthy, empty queue looks like, so "no badge" proves nothing either way.
    const link = await screen.findByLabelText("Held accounts: we could not read the queue");
    expect(link.textContent).toContain("?");
  });

  it("counts what the server sent when the server answered", async () => {
    renderAdminShell({ [HOLDS_PATH]: HELD });

    const link = await screen.findByLabelText("Held accounts: 2 waiting on us");
    expect(link.textContent).toContain("2");
  });

  it("shows no badge, and no mark, on a real all-clear", async () => {
    // The premise of both tests above: three states, three renderings.
    renderAdminShell();

    const link = await screen.findByLabelText("Held accounts");
    expect(link.textContent).not.toContain("?");
  });

  it("shows no count, and no mark, while the queue is still being read", async () => {
    renderAdminShell({ [HOLDS_PATH]: stillLoading() });

    const link = await screen.findByLabelText("Held accounts");
    expect(link.textContent).not.toContain("?");
    expect(link.textContent).not.toContain("0");
  });
});

describe("the client shell's attention bell", () => {
  it("says the queue could not be read, instead of looking like an all-clear", async () => {
    await renderClientShell({
      "/v1/attention": problem(503, { title: "Service unavailable" }),
    });

    const link = await screen.findByLabelText("Needs attention: we could not read your queue");
    expect(link.textContent).toContain("?");
  });

  it("counts what the server sent when the server answered", async () => {
    await renderClientShell({ "/v1/attention": { total: 3, items: [] } });

    const link = await screen.findByLabelText("Needs attention: 3 item(s)");
    expect(link.textContent).toContain("3");
  });

  it("shows no badge, and no mark, on a real all-clear", async () => {
    await renderClientShell({ "/v1/attention": { total: 0, items: [] } });

    const link = await screen.findByLabelText("Needs attention");
    expect(link.textContent).not.toContain("?");
  });
});
