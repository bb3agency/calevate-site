import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import TenantLayout from "@/app/admin/tenants/[tenantId]/layout";
import ClosurePage from "@/app/admin/tenants/[tenantId]/closure/page";
import {
  TENANT_SECTIONS,
  currentTenantSection,
} from "@/app/admin/tenants/[tenantId]/tenantSections";
import type { TenantSummary } from "@/lib/api/admin";

import { problem, stillLoading, type Routes } from "./harness";
import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * One client's pages share a header (name, state, one action) and a grouped section menu
 * (D-661). The layout also owns the tenant read, so a sub-page never mounts over a client
 * nobody has confirmed exists.
 */

let pathname = "/";
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => pathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
}));

const TENANT = "0192f0aa-7777-7000-8000-0000000000bb";
const SLUG = "sri-traders";
const BASE = `/admin/tenants/${TENANT}`;

function tenant(over: Partial<TenantSummary> = {}): TenantSummary {
  return {
    id: TENANT,
    name: "Sri Traders",
    slug: SLUG,
    status: "active",
    plan_tier: "prepaid",
    vertical_template: "clinic",
    live_agents: 2,
    calls_7d: 412,
    leads: 96,
    last_call_at: "2026-08-12T09:15:00Z",
    holds: [],
    capped: false,
    ...over,
  };
}

const ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-7777-7000-8000-0000000000cc",
  role: "operator",
  permissions: ["org:read", "admin:tenants"],
};

function render(routes: Routes = {}, at = `${BASE}/kyc`) {
  pathname = at;
  return renderAdminRoute(
    <TenantLayout params={routeParams({ tenantId: TENANT })}>
      <h2>Sub-page body</h2>
    </TenantLayout>,
    { [ADMIN_ME_PATH]: ME, [`/v1/admin/tenants/${TENANT}`]: tenant(), ...routes },
  );
}

beforeEach(() => {
  pathname = "/";
});

describe("the client header", () => {
  it("names the client as the page's one h1, with its state", async () => {
    const { container } = await render({
      [`/v1/admin/tenants/${TENANT}`]: tenant({ status: "suspended", capped: true }),
    });
    const h1s = await screen.findAllByRole("heading", { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0].textContent).toBe("Sri Traders");
    expect(container.textContent).toContain("suspended");
    expect(container.textContent).toContain("capped");
    expect(container.textContent).toContain(`/c/${SLUG}`);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Sub-page body");
  });

  it("names the billing motion on every page of the client, not only on the commercials screen", async () => {
    // Moved from adminTenantDetail.test.tsx with the header line. Which way the money
    // moves decides what the rest of the client's pages mean: a managed client has no
    // wallet to be empty, so "why have their calls stopped" has a different answer.
    await render({ [`/v1/admin/tenants/${TENANT}`]: tenant({ plan_tier: "managed" }) });
    const header = (await screen.findByRole("heading", { level: 1 })).closest("header");
    expect(header?.textContent).toContain("managed");
  });

  it("says the view-as link is LOGGED where a keyboard user reads it, never read-only", async () => {
    /**
     * Moved from adminTenantDetail.test.tsx with the link. D-587 lets a view-as session
     * change the account, so "(read-only)" would be a promise the product breaks; what
     * stays true is that everything viewed and changed is recorded against the operator,
     * and that belongs in the label, not only in a `title`. The `view=admin` marker selects
     * the impersonating credential and grants nothing (lib/api/session.tsx).
     */
    await render();

    const link = await screen.findByRole("link", { name: /View as client \(logged\)/ });
    expect(link.getAttribute("href")).toBe(`/c/${SLUG}?view=admin`);
    expect(screen.queryByRole("link", { name: /read-only/i })).toBeNull();
  });
});

describe("the tenant read belongs to the layout", () => {
  it("does not mount the sub-page while the client is loading", async () => {
    const { container } = await render({ [`/v1/admin/tenants/${TENANT}`]: stillLoading() });
    expect(container.textContent).not.toContain("Sub-page body");
  });

  it("refuses in the server's words, and never says the client does not exist", async () => {
    const { container } = await render({
      [`/v1/admin/tenants/${TENANT}`]: problem(500, {
        title: "Upstream unavailable",
        detail: "We could not read this client.",
        retryable: true,
      }),
    });
    await screen.findByText("We could not read this client.");
    expect(container.textContent).not.toContain("Sub-page body");
    expect(container.textContent).not.toContain("not found");
  });
});

describe("the section menu", () => {
  it("links every section and marks the open one", async () => {
    await render();
    const nav = await screen.findByRole("navigation", { name: "Client sections" });
    const links = [...nav.querySelectorAll("a")];
    expect(links.map((a) => a.getAttribute("href"))).toEqual(
      TENANT_SECTIONS.map((s) => `${BASE}${s.path}`),
    );
    const current = nav.querySelectorAll('[aria-current="true"]');
    expect(current).toHaveLength(1);
    expect(current[0].textContent).toBe("Identity & carrier");
    // The sidebar owns "page"; the menu must not make a second claim.
    expect(nav.querySelector('[aria-current="page"]')).toBeNull();
  });

  it("carries a deeper route up to its item, and the merged invitations route to People", () => {
    expect(currentTenantSection(TENANT, `${BASE}/agents/a1/prompt`)?.label).toBe("Agents");
    expect(currentTenantSection(TENANT, `${BASE}/invitations`)?.label).toBe("People");
    expect(currentTenantSection(TENANT, BASE)?.label).toBe("Overview");
    expect(currentTenantSection(TENANT, `${BASE}/`)?.label).toBe("Overview");
    expect(currentTenantSection(TENANT, `${BASE}/no-such-page`)).toBeUndefined();
    expect(currentTenantSection(TENANT, "/admin/tenants/other/kyc")).toBeUndefined();
  });
});


/**
 * An ERASED client (Proposal A). Erasure marks the organisation deleted and the directory
 * read then answers 404, which used to leave the DPDP erasure certificate unreachable. Only
 * a 404, and only on the Closing route, mounts the page; the "erased" claim waits for the
 * closure read, so an id that never existed is not told it was erased.
 */
describe("an erased client", () => {
  const NOT_FOUND = problem(404, { title: "Not found", detail: "Client not found.", retryable: false });
  const CLOSURE_PATH = `/v1/admin/tenants/${TENANT}/closure`;
  const ERASURE_PATH = `/v1/admin/tenants/${TENANT}/erasure`;
  const ERASED_CLOSURE = {
    tenant_id: TENANT,
    status: "churned",
    closed_at: "2026-08-20T05:30:00Z",
    erase_after: "2026-09-19T05:30:00Z",
    reason: "Not renewing after the pilot.",
    closed_by: null,
    erased_at: "2026-09-19T06:00:00Z",
    restorable: false,
    days_remaining: null,
  };
  const CERTIFICATE = {
    request_id: "0192f0aa-7777-7000-8000-0000000000e2",
    tenant_id: TENANT,
    status: "completed",
    reason: "client asked, ticket 4471",
    requested_at: "2026-09-19T05:45:00Z",
    completed_at: "2026-09-19T06:00:00Z",
    proof: null,
    limitations: [],
  };

  function renderClosure(routes: Routes = {}, at = `${BASE}/closure`) {
    pathname = at;
    // ONE params promise for both, as Next passes it: `use()` suspends on each new promise.
    const params = routeParams({ tenantId: TENANT });
    return renderAdminRoute(
      <TenantLayout params={params}>
        <ClosurePage params={params} />
      </TenantLayout>,
      { [ADMIN_ME_PATH]: ME, [`/v1/admin/tenants/${TENANT}`]: NOT_FOUND, ...routes },
    );
  }

  it("reaches the Closing page and its erasure certificate", async () => {
    const { container } = await renderClosure({
      [CLOSURE_PATH]: ERASED_CLOSURE,
      [ERASURE_PATH]: [CERTIFICATE],
    });
    await screen.findByRole("heading", { level: 1, name: "Erased client" });
    await screen.findByText(/This client's data was erased on/);
    // Every other section 404s for an erased client, so the menu is not offered.
    expect(screen.queryByRole("navigation", { name: "Client sections" })).toBeNull();
    expect(container.textContent).not.toContain("View as client");
  });

  it("still refuses every other route with the 404", async () => {
    const { container } = await render({ [`/v1/admin/tenants/${TENANT}`]: NOT_FOUND });
    await screen.findByRole("alert");
    expect(container.textContent).toContain("Client not found.");
    expect(container.textContent).not.toContain("Erased client");
    expect(screen.queryByText("Sub-page body")).toBeNull();
  });

  it("leaves a non-404 failure on the Closing route exactly as it was", async () => {
    const { container } = await renderClosure({
      [`/v1/admin/tenants/${TENANT}`]: problem(503, {
        title: "Upstream unavailable",
        detail: "Service unavailable.",
        retryable: true,
      }),
      [CLOSURE_PATH]: ERASED_CLOSURE,
      [ERASURE_PATH]: [CERTIFICATE],
    });
    await screen.findByRole("alert");
    expect(container.textContent).toContain("Service unavailable.");
    expect(container.textContent).not.toContain("Erased client");
    expect(container.textContent).not.toContain("This client's data was erased on");
  });

  it("shows the closure read's own 404 for an id that never existed, and claims no erasure", async () => {
    const { container } = await renderClosure({
      [CLOSURE_PATH]: problem(404, {
        title: "Not found",
        detail: "Client not found.",
        retryable: false,
      }),
    });
    await screen.findByRole("alert");
    await screen.findByRole("heading", { level: 1, name: "Client not available" });
    expect(container.textContent).not.toContain("Erased client");
    expect(container.textContent).toContain("Client not found.");
  });
});
