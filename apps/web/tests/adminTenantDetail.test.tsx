import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render as rtlRender,
  screen,
  within,
  type RenderResult,
} from "@testing-library/react";
import { Suspense } from "react";
import { describe, expect, it, vi } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import TenantDetailPage from "@/app/admin/tenants/[tenantId]/page";
import TenantAgentsPage from "@/app/admin/tenants/[tenantId]/agents/page";
import type { KbSource, Margin, TenantSummary } from "@/lib/api/admin";
import type { Routes } from "./harness";

import { browserOffline, problem, stubApi } from "./harness";
import { renderAdminRoute, routeParams } from "./adminRoute";
import { KB_ALL_DELIVERED, WHATSAPP_NEVER_ASKED } from "./fixtures/sharedReads";

/**
 * The client detail screen — the one an operator opens to decide what to DO for a client,
 * which is why every test here is about a sentence the screen must not say.
 *
 * This page reads six lists (knowledge, approved-but-unpublished, agents, numbers,
 * templates, margin) and every one of them used to render its EMPTY state on a failed
 * request. On an operator console that direction is the expensive one:
 *
 * - "No numbers on file" after a failed read has an operator ask a client who already has
 *   a number to go and take out a second connection on their carrier account — money they
 *   spend, on a DLT header that then has to be untangled.
 * - "Nothing awaiting approval" after a failed read leaves a client's knowledge sitting in
 *   a queue nobody looks at again, because the queue said it was empty.
 * - An agents panel that returned `null` on failure was indistinguishable from a client
 *   with no agents at all, which is the most alarming fact this screen can state.
 *
 * The second theme is the D-22 promise. The write controls are gated on `admin:tenants`
 * — the permission `apps/api/admin/routes.py` requires — and disabled WITH the reason,
 * and the "view as client" entry point has to keep saying READ-ONLY where a keyboard user
 * can read it, not only in a `title` a mouse discovers.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000bb";
const SLUG = "sri-traders";

const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const MARGIN_PATH = `${TENANT_PATH}/margin`;
const QUEUE_PATH = "/v1/kb/sources?status=pending_approval";
const APPROVED_PATH = "/v1/kb/sources?status=approved";
const AGENTS_PATH = "/v1/agents";
const NUMBERS_PATH = "/v1/campaigns/numbers";
const TEMPLATES_PATH = "/v1/campaigns/templates";
// The spend-cap panel's read, impersonated like the rest of this screen's reads. Its own
// behaviour is asserted in `adminSpendCap.test.tsx`; it is here so this file's premise
// stays complete — an unrouted endpoint is a hole, not a detail (see `harness.tsx`).
const CAPS_PATH = "/v1/billing/caps";
const ME_PATH = ADMIN_ME_PATH;

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

/**
 * The admin's own identity, as `GET /v1/admin/me` answers it.
 *
 * No `impersonating` field and no organization, and that is the fix rather than a shorter
 * fixture: the console used to read `/v1/me` THROUGH an impersonating session — the only
 * way an admin token could reach it (core/auth.py) — which meant every gate on this screen
 * depended on entering a client, and on a hook remembering not to read `impersonating` as
 * a refusal. Every write here goes to the admin surface with the tenant in the path, where
 * impersonation is not involved at all.
 */
function me(permissions: string[]): AdminMe {
  return {
    realm: "admin",
    user_id: "0192f0aa-7777-7000-8000-0000000000cc",
    role: "operator",
    permissions,
  };
}

const OPERATOR = me([
  "org:read",
  "billing:read",
  "agents:read",
  "kb:write",
  "admin:tenants",
]);

function margin(over: Partial<Margin> = {}): Margin {
  return {
    month: "2026-08",
    minutes_used: "1204.5",
    calls: 412,
    revenue_inr: "1015900.00",
    cost_inr: "402350.50",
    margin_inr: "613549.50",
    margin_pct: "60.39",
    legs_unpriced: 0,
    tiers: {
      // BOTH SPELLINGS, because that is what the wire carries for one release
      // (hard rule 8 step 1, D-558): `*_base_rung` / `*_second_rung` are the
      // names, `*_premium` / `*_value` are deprecated and carry the identical
      // figure. The screen prefers the new pair;
      // `rungRenameFallback.test.tsx` is the one that omits it.
      minutes_base_rung: "900.00",
      minutes_second_rung: "280.00",
      minutes_premium: "900.00",
      minutes_value: "280.00",
      minutes_unattributed: "24.50",
      cost_base_rung_inr: "300000.00",
      cost_second_rung_inr: "90000.00",
      cost_premium_inr: "300000.00",
      cost_value_inr: "90000.00",
      cost_unattributed_inr: "12350.50",
    },
    ...over,
  };
}

function source(over: Partial<KbSource> = {}): KbSource {
  return {
    id: "0192f0aa-7777-7000-8000-0000000000dd",
    agent_id: "0192f0aa-7777-7000-8000-0000000000ee",
    name: "Clinic price list",
    kind: "text",
    status: "pending_approval",
    version: 3,
    chunks: 12,
    is_active: false,
    published_at: null,
    ...over,
  };
}

/** Everything green, so each test can break exactly one thing. */
function healthy(): Routes {
  return {
    [TENANT_PATH]: tenant(),
    [ME_PATH]: OPERATOR,
    [QUEUE_PATH]: [],
    [APPROVED_PATH]: [],
    [AGENTS_PATH]: [],
    [NUMBERS_PATH]: [],
    [TEMPLATES_PATH]: [],
    [MARGIN_PATH]: margin(),
    [CAPS_PATH]: {
      month: "2026-08",
      plan_cap_minutes: 5000,
      plan_cap_spend_inr: "40000.00",
      client_cap_minutes: null,
      client_cap_spend_inr: null,
      effective_cap_minutes: 5000,
      effective_cap_spend_inr: "40000.00",
      minutes_used: "812.00",
      spend_used_inr: "5002.40",
      capped: false,
    },
    "/v1/kb/delivery": KB_ALL_DELIVERED,
    [`${TENANT_PATH}/whatsapp-alerts`]: WHATSAPP_NEVER_ASKED,
  };
}

function render(routes: Partial<Routes> = {}) {
  return renderAdminRoute(
    <TenantDetailPage params={routeParams({ tenantId: TENANT })} />,
    {
      ...healthy(),
      ...routes,
    },
  );
}

describe("the client detail screen", () => {
  it("does not report an empty approval queue when the queue could not be read", async () => {
    const { container } = await render({
      [QUEUE_PATH]: problem(500, {
        title: "Upstream unavailable",
        detail: "The knowledge queue is unavailable.",
        retryable: true,
      }),
    });

    await screen.findByText("The knowledge queue is unavailable.");

    expect(container.textContent).not.toContain("Nothing awaiting approval");
  });

  it("refuses the approval queue while the browser is OFFLINE, rather than reporting it empty", async () => {
    // The paused-query hole (§52), in the `?.length` spelling the surfaceStates guard
    // cannot see. With the tenant already in cache the page renders its body and reaches
    // the queue card, but a queue read TanStack PARKS because the browser is offline
    // reports isLoading===false, error===null and data===undefined — so the old
    // `queue.data?.length` fell straight through to "Nothing awaiting approval", a claim
    // about this client's work made from a read that never arrived. The inner preview
    // branch already refused on exactly this; the queue did not, until it was fixed to.
    stubApi(healthy());
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    // Primed so the page gets past its tenant guard and reaches the queue card; the queue
    // read is what is left to PAUSE, which is the state under test. Everything else on the
    // page also pauses, but each panel refuses in its own section, so scoping the
    // assertions to the queue card isolates this one.
    client.setQueryData(["admin", "tenant", TENANT], tenant());
    browserOffline();

    let result!: RenderResult;
    await act(async () => {
      result = rtlRender(
        <QueryClientProvider client={client}>
          <Suspense fallback={null}>
            <TenantDetailPage params={routeParams({ tenantId: TENANT })} />
          </Suspense>
        </QueryClientProvider>,
      );
    });

    const card = (
      await within(result.container).findByRole("heading", {
        name: "Knowledge awaiting approval",
      })
    ).closest("section");
    expect(card, "the knowledge card should render").not.toBeNull();
    // A paused read is refused (ProblemNotice carries role="alert"), never reported as an
    // empty queue.
    expect(within(card!).queryByText("Nothing awaiting approval")).toBeNull();
    expect(
      within(card!).getByRole("alert"),
      "a paused queue must refuse, not fall silent or claim emptiness",
    ).toBeTruthy();
  });

  // The agent list moved from the overview to the Agents section (D-661); the two
  // sentences it must and must not say moved with it, unchanged.
  it("does not render silence where a client's agents should be", async () => {
    const { container } = await renderAdminRoute(
      <TenantAgentsPage params={routeParams({ tenantId: TENANT })} />,
      {
        ...healthy(),
      [AGENTS_PATH]: problem(500, {
        title: "Upstream unavailable",
        detail: "We could not list this client's agents.",
        retryable: true,
      }),
      },
    );

    await screen.findByText("We could not list this client's agents.");

    // The panel used to disappear entirely — the same silence as "this client has no
    // agents", which is a claim nobody should make from a failed request.
    expect(container.textContent).not.toContain("No agents yet");
  });

  it("says an empty list is empty when the SERVER says so", async () => {
    const { container } = await render();

    await screen.findByText("Nothing awaiting approval");

    // The counterpart to the four tests above: with 200s in hand the screen must state
    // the emptiness plainly, because an operator reading a refusal where there is simply
    // no work would go looking for an outage.
    expect(container.textContent).toContain("Nothing awaiting approval");
  });

  it("says a client has no agents only when the SERVER says so", async () => {
    await renderAdminRoute(<TenantAgentsPage params={routeParams({ tenantId: TENANT })} />, healthy());
    await screen.findByText(/No agents yet/);
  });

  it("disables every write with its reason when the session lacks admin:tenants", async () => {
    await render({
      [ME_PATH]: me(["org:read", "billing:read", "agents:read"]),
      [QUEUE_PATH]: [source()],
    });

    // The gate answers only once `/v1/admin/me` has, so the sentence settles the render.
    await screen.findAllByText(/does not have permission to/);

    // `findByRole`, not `getByRole`: the identity read no longer waits for the tenant to
    // supply a slug (it needs none), so the refusal can now paint a tick BEFORE the lists
    // whose controls it is refusing. Each control is awaited on its own panel's arrival.
    for (const name of [
      "Approve",
      "Reject…",
      // The registrar controls moved to Compliance › Campaign setup (D-661) and are
      // gated there; tests/adminCampaignSetup.test.tsx drives them.
    ]) {
      const button = await screen.findByRole("button", { name });
      expect(
        (button as HTMLButtonElement).disabled,
        `${name} must be disabled`,
      ).toBe(true);
    }

    // Disabled AND explained: a dead control with no sentence beside it is indistinguishable
    // from a broken screen, and the operator's next move is the curl this console replaced.
    // Reading stays available — briefing the colleague who can decide requires seeing
    // what is queued.
    expect(
      (screen.getByRole("button", { name: "Preview" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });

  it("rejects a source only after the operator writes a reason — never from one click", async () => {
    const decidePath = `/v1/admin/tenants/${TENANT}/kb/${source().id}/reject`;
    const { calls } = await render({
      [QUEUE_PATH]: [source()],
      [`POST ${decidePath}`]: { ok: true },
    });

    // Stage one: the quiet trigger opens the confirmation and sends NOTHING.
    const open = await screen.findByRole("button", { name: "Reject…" });
    await vi.waitFor(() =>
      expect((open as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(open);
    expect(calls.some((call) => call.path === decidePath)).toBe(false);

    // The confirmation names the specific document and demands the operator's own words —
    // the old one-click reject sent a hardcoded reason the operator never saw.
    expect(screen.getByText(/Rejecting/).textContent).toContain(
      "Clinic price list",
    );
    const submit = screen.getByRole("button", {
      name: "Reject this document",
    }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText(/Why it can't be used/), {
      target: { value: "Prices are last year's" },
    });
    await vi.waitFor(() =>
      expect(
        (
          screen.getByRole("button", {
            name: "Reject this document",
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(false),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Reject this document" }),
    );

    await vi.waitFor(() =>
      expect(
        calls.some(
          (call) => call.method === "POST" && call.path === decidePath,
        ),
      ).toBe(true),
    );
    const post = calls.find(
      (call) => call.method === "POST" && call.path === decidePath,
    );
    expect(JSON.parse(post?.body ?? "{}")).toEqual({
      reason: "Prices are last year's",
    });
  });

  it("keeps the writes live for a session that holds the permission", async () => {
    await render({ [QUEUE_PATH]: [source()] });

    // The negative test above is only meaningful if the gate can ever be open — an
    // always-disabled console would pass it and be useless.
    const approve = await screen.findByRole("button", { name: "Approve" });
    await vi.waitFor(() =>
      expect((approve as HTMLButtonElement).disabled).toBe(false),
    );
  });

  // The view-as link moved to the tenant layout's header (D-661); its "(logged), never
  // read-only" assertion moved with it, to adminTenantLayout.test.tsx.

  it("formats margin money without ever parsing it, and keeps 'not billed yet' out of 0%", async () => {
    const { container } = await render({
      [MARGIN_PATH]: margin({ margin_pct: null }),
    });

    await screen.findByText("₹10,15,900.00");

    // Indian grouping on the digits the server sent — the raw interpolation this screen
    // used to do printed ₹1015900.00 on a figure an operator quotes in a pricing call.
    expect(container.textContent).toContain("₹10,15,900.00");
    expect(container.textContent).not.toContain("₹1015900.00");
    // Nothing billed is not zero margin. An operator acts differently on each.
    expect(container.textContent).toContain("not billed yet");
    expect(container.textContent).not.toContain("0%");
  });

  /* --- The account state, where an operator actually looks ------------------------
   *
   * `organizations.status` was on this screen as one lowercase word in the grey subtitle,
   * under a page of agents, spend and a margin — all of which read as a healthy account.
   * `check_dispatch` asks the account state BEFORE it asks any gate, so a suspended client
   * dials nothing whatever else is green, and the operator opening this page to ask why is
   * the person the word was hidden from.
   */
  it("says plainly that a suspended account is stopped, and where to reverse it", async () => {
    const { container } = await render({ [TENANT_PATH]: tenant({ status: "suspended" }) });

    const title = await screen.findByText("This account is suspended.");
    // The half nobody guesses: outbound stops, inbound deliberately does not.
    expect(container.textContent).toContain("outbound dialling is refused");
    expect(container.textContent).toContain("Inbound answering is deliberately untouched");
    // Scoped to the banner. The nav above carries a link of the same name to the same
    // screen, and an unscoped query would pass on the nav alone — which is the wiring
    // this case exists to prove is NOT what is being asserted.
    const banner = within(title.parentElement as HTMLElement);
    expect(banner.getByRole("link", { name: "Account state" }).getAttribute("href")).toBe(
      `/admin/tenants/${TENANT}/lifecycle`,
    );
  });

  it("says a closed account is closed, and points at the one screen that reopens it", async () => {
    const { container } = await render({ [TENANT_PATH]: tenant({ status: "churned" }) });

    const title = await screen.findByText("This account is closed.");
    expect(container.textContent).toContain("Nobody at the client can sign in");
    const banner = within(title.parentElement as HTMLElement);
    expect(banner.getByRole("link", { name: "Closing the account" }).getAttribute("href")).toBe(
      `/admin/tenants/${TENANT}/closure`,
    );
    // THE COUNTDOWN IS NOT REPEATED HERE. `days_remaining` is computed server-side on one
    // clock and belongs beside the button that acts on it; a deadline printed on two
    // screens is a deadline that will disagree with itself.
    expect(container.textContent).not.toContain("days left");
  });

  it("shows no state banner at all for a live account", async () => {
    const { container } = await render();

    // The client's name moved to the tenant layout's header (D-661), so the page is
    // awaited on its own first figure.
    await screen.findByText("Live agents");
    expect(container.textContent).not.toContain("This account is suspended.");
    expect(container.textContent).not.toContain("This account is closed.");
  });

  // "Names the billing motion on the page" moved with the header line that carries it, to
  // adminTenantLayout.test.tsx.

  // The tenant read's refusal is the layout's now (adminTenantLayout.test.tsx): this page
  // is not mounted until the client has been read.

});
